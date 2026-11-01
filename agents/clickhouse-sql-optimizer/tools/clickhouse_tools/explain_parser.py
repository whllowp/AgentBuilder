"""EXPLAIN 输出解析器：提取分区裁剪 / granule 裁剪 / 键条件等量化指标并给出建议。

兼容 EXPLAIN PLAN 常见输出（`Parts: N/M`、`Granules: N/M`、`Key Condition:`、
`Reading ... in reverse order`、PREWHERE 移动标记），对 EXPLAIN ANALYZE 的耗时行做尽力提取。
"""
from __future__ import annotations

import re

_PARTS_RE = re.compile(r"(?:PrimaryKeyAll)?[Pp]arts:\s*(\d+)\s*/\s*(\d+)")
_GRANULES_RE = re.compile(r"(?:PrimaryKeyAll)?Granules:\s*(\d+)\s*/\s*(\d+)", re.IGNORECASE)
_KEY_COND_RE = re.compile(r"Key\s*Condition:\s*(.+)")
_PREWHERE_RE = re.compile(r"\bPREWHERE\b|move\s+to\s+PREWHERE|Where\s*\(PREWHERE", re.IGNORECASE)
_WHERE_RE = re.compile(r"\bWHERE\b|Filter\s*\(", re.IGNORECASE)
_READ_COLS_RE = re.compile(r"Expression\s*\(\((.+?)\)\)")
_DURATION_RE = re.compile(r"elapsed:\s*([\d.]+)\s*(ms|s)", re.IGNORECASE)


def _ratio(n: int, m: int) -> float:
    return round(n / m, 4) if m else 0.0


def parse_explain(text: str) -> dict:
    """解析 EXPLAIN 文本，返回 {ok, metrics, advice, summary}。"""
    if not text or not text.strip():
        return {"ok": False, "error": "EXPLAIN 输出为空", "metrics": {}, "advice": [], "summary": "无内容"}

    metrics: dict = {"stage": "plan"}
    if re.search(r"Query pipeline|Pipe", text, re.IGNORECASE) and "Granules" not in text:
        metrics["stage"] = "pipeline"

    parts = _PARTS_RE.search(text)
    if parts:
        read_p, total_p = int(parts.group(1)), int(parts.group(2))
        metrics["parts_read"], metrics["parts_total"] = read_p, total_p
        metrics["parts_read_ratio"] = _ratio(read_p, total_p)

    gran = _GRANULES_RE.search(text)
    if gran:
        read_g, total_g = int(gran.group(1)), int(gran.group(2))
        metrics["granules_read"], metrics["granules_total"] = read_g, total_g
        metrics["granules_read_ratio"] = _ratio(read_g, total_g)

    key_cond = _KEY_COND_RE.search(text)
    if key_cond:
        metrics["key_condition"] = key_cond.group(1).strip()[:200]
    metrics["filter_moved_to_prewhere"] = bool(_PREWHERE_RE.search(text))
    metrics["has_where"] = bool(_WHERE_RE.search(text))

    read_cols = _READ_COLS_RE.search(text)
    if read_cols:
        cols = [c.strip().split()[-1].strip(",") for c in read_cols.group(1).split(",")]
        metrics["read_columns"] = [c for c in cols if c][:20]

    durations = [(float(v), u) for v, u in _DURATION_RE.findall(text)]
    if durations:
        ms = sum(v * (1000 if u.lower() == "s" else 1) for v, u in durations)
        metrics["elapsed_ms_total"] = round(ms, 1)

    # ---------------- 建议生成 ----------------
    advice: list[dict] = []

    pr = metrics.get("parts_read_ratio")
    if pr is not None and pr > 0.5 and metrics.get("parts_total", 0) > 1:
        advice.append(
            {
                "severity": "warning",
                "title": f"分区裁剪不佳（读取 {metrics['parts_read']}/{metrics['parts_total']} part，{pr:.0%}）",
                "action": "WHERE 中补充分区列条件（与 PARTITION BY 表达式对齐的半开区间），目标 parts_read_ratio < 0.2。参考规范 5.2-5。",
            }
        )
    elif pr is not None and pr <= 0.2 and metrics.get("parts_total", 0) > 10:
        advice.append(
            {
                "severity": "info",
                "title": f"分区裁剪良好（读取 {metrics['parts_read']}/{metrics['parts_total']} part）",
                "action": "分区层已生效，继续看 granule 层。",
            }
        )

    gr = metrics.get("granules_read_ratio")
    if gr is not None and gr > 0.3:
        advice.append(
            {
                "severity": "warning",
                "title": f"主键/稀疏索引裁剪不佳（读取 {metrics['granules_read']}/{metrics['granules_total']} granule，{gr:.0%}）",
                "action": "过滤条件未命中排序键前缀：改写 WHERE 使等值/IN 条件对齐 ORDER BY 前缀列；非键高选择性列加跳数索引（minmax/set/bloom_filter）。参考规范 5.2-1/5.2-4。",
            }
        )
    elif gr is not None and gr <= 0.05 and metrics.get("granules_total", 0) > 100:
        advice.append(
            {
                "severity": "info",
                "title": f"稀疏索引裁剪良好（读取 {metrics['granules_read']}/{metrics['granules_total']} granule，{gr:.1%}）",
                "action": "排序键设计对该查询有效。若仍慢，瓶颈大概率在列宽/聚合/JOIN，转向列裁剪与预聚合。",
            }
        )

    if "key_condition" not in metrics and metrics.get("has_where"):
        advice.append(
            {
                "severity": "warning",
                "title": "无 Key Condition（WHERE 条件未作用到主键索引）",
                "action": "WHERE 中的过滤列不在排序键前缀上，或被函数包裹（toDate(ts)=d 之类）。改写为半开区间并对齐排序键；EXPLAIN indexes=1 复查。参考规范 4.1-3。",
            }
        )
    if "key_condition" in metrics and "unknown" in metrics["key_condition"].lower():
        advice.append(
            {
                "severity": "warning",
                "title": "Key Condition 含 unknown（条件无法用于索引裁剪）",
                "action": f"键条件：{metrics['key_condition']}。通常是键列被函数/类型转换包裹，改写为区间比较后重试。",
            }
        )

    if metrics.get("read_columns") and len(metrics["read_columns"]) >= 15:
        advice.append(
            {
                "severity": "info",
                "title": f"读取列较多（{len(metrics['read_columns'])} 列）",
                "action": "列存按列计费：裁剪到业务所需列，避免 SELECT *。参考规范 4.1-1。",
            }
        )

    if not advice:
        advice.append(
            {
                "severity": "info",
                "title": "未提取到显著异常指标",
                "action": "可补充 `EXPLAIN ANALYZE`（真实执行统计）与 system.query_log 的 ProfileEvents 定位 I/O vs CPU 瓶颈。参考规范 5.1。",
            }
        )

    bits = []
    if "parts_read" in metrics:
        bits.append(f"parts {metrics['parts_read']}/{metrics['parts_total']}")
    if "granules_read" in metrics:
        bits.append(f"granules {metrics['granules_read']}/{metrics['granules_total']}")
    if "key_condition" in metrics:
        bits.append("有键条件" if "unknown" not in metrics["key_condition"].lower() else "键条件 unknown")
    summary = "EXPLAIN 指标：" + ("，".join(bits) if bits else "仅通用指标") + f"；{len(advice)} 条建议"
    return {"ok": True, "metrics": metrics, "advice": advice, "summary": summary}
