"""容量需求文本解析：从中文描述提取引擎与关键参数（行/天、行宽、保留期、QPS 等）。"""
from __future__ import annotations

import re

_ENGINE_PATTERNS = [
    ("clickhouse", re.compile(r"clickhouse|\bck\b|列存|排序键|分区表", re.IGNORECASE)),
    ("kafka", re.compile(r"kafka|topic|消息队列|分区数", re.IGNORECASE)),
    ("flink", re.compile(r"flink|实时计算|流式|水位线|checkpoint", re.IGNORECASE)),
    ("generic", re.compile(r"qps|tps|接口|服务|并发", re.IGNORECASE)),
]


def _num(text: str, patterns: list[tuple[str, re.Pattern]], default: float | None = None) -> float | None:
    for name, pat in patterns:
        m = pat.search(text)
        if m:
            try:
                return float(m.group(1).replace(",", ""))
            except ValueError:
                continue
    return default


def parse_spec(text: str) -> dict:
    """解析容量需求描述 → plan() 可用的 spec。"""
    t = text or ""
    engine = next((name for name, pat in _ENGINE_PATTERNS if pat.search(t)), None)

    # 万/亿 归一：日均 X 亿行 / X 万条 / X w
    def _scaled(pattern: str) -> float | None:
        m = re.search(pattern, t)
        if not m:
            return None
        v = float(m.group(1).replace(",", ""))
        unit = m.group(2)
        mult = {"亿": 1e8, "万": 1e4, "w": 1e4, "W": 1e4, "k": 1e3, "K": 1e3, "": 1}.get(unit, 1)
        return v * mult

    rows = (_scaled(r"日[均增]\s*([0-9.]+)\s*(亿|万|w|W|k|K|)(?:行|条|记录)")
            or _scaled(r"([0-9.]+)\s*(亿|万|w|W|k|K|)(?:行|条)/天")
            or _scaled(r"每秒\s*([0-9.]+)\s*(亿|万|w|W|k|K|)(?:条|行|消息)"))
    qps = _scaled(r"([0-9.]+)\s*(万|w|W|k|K|)(?:\s*qps| qps|QPS)")
    row_bytes = _num(t, [("", re.compile(r"(?:行宽|平均.{0,4}大小|单条.{0,6})[^0-9]*([0-9.]+)\s*(?:b|B|字节)"))], default=200.0)
    ttl = _num(t, [("", re.compile(r"(?:保留|TTL|存留)[^0-9]*([0-9.]+)\s*天")), ("", re.compile(r"保留[^0-9]*([0-9.]+)\s*小时"))])
    retention_hours = _num(t, [("", re.compile(r"保留[^0-9]*([0-9.]+)\s*小时"))])
    replicas = _num(t, [("", re.compile(r"(?:副本|副本数)[^0-9双两二]*(\d+)"))])
    if replicas is None:
        m = re.search(r"(双|两|二)[副本]", t)
        if m:
            replicas = 2.0
    state_gb = _num(t, [("", re.compile(r"状态[^0-9]*([0-9.]+)\s*[gG][bB]?"))])
    key_card = _num(t, [("", re.compile(r"(?:键|key|维)[^0-9]{0,6}基数[^0-9]*([0-9.]+)\s*(亿|万|w|W|k|K|)"))])

    spec: dict = {"engine": engine or "unknown", "raw_text": t[:200]}
    if rows:
        spec["rows_per_day" if "每秒" not in t else "msgs_per_sec"] = rows
    if qps:
        spec["qps"] = qps
    if row_bytes:
        spec["avg_row_bytes"] = row_bytes
    if ttl and "小时" not in (ttl and ""):
        spec["ttl_days"] = int(ttl)
    if retention_hours:
        spec["retention_hours"] = int(retention_hours)
    if replicas:
        spec["replicas"] = int(replicas)
    if state_gb:
        spec["state_size_gb"] = state_gb
    if key_card:
        spec["key_cardinality"] = key_card
    # Flink 语义对齐：每秒速率统一映射为 records_per_sec
    if spec.get("engine") == "flink" and "msgs_per_sec" in spec:
        spec["records_per_sec"] = spec.pop("msgs_per_sec")
    return spec


__all__ = ["parse_spec"]
