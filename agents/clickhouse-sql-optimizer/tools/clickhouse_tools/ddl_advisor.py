"""建表 DDL 评估器：解析 CREATE TABLE 并按《clickhouse开发规范.md》第 2 章规则评估。

正则启发式解析（非完整 SQL parser），覆盖常见 DDL 形态；解析失败时返回 parse_error。
"""
from __future__ import annotations

import re
from dataclasses import asdict, dataclass

_ENGINE_RE = re.compile(r"ENGINE\s*=\s*([A-Za-z]+)\s*(?:\(([^)]*)\))?", re.IGNORECASE)
_PARTITION_RE = re.compile(r"\bPARTITION\s+BY\s+([^\n(;]+)", re.IGNORECASE)
_ORDER_BY_RE = re.compile(r"\bORDER\s+BY\s*(?:\(([^)]*)\)|([^\n(;]+))", re.IGNORECASE)
_PRIMARY_KEY_RE = re.compile(r"\bPRIMARY\s+KEY\s*(?:\(([^)]*)\)|([^\n(;]+))", re.IGNORECASE)
_TTL_RE = re.compile(r"\bTTL\s+([^\n;]+)", re.IGNORECASE)
_SAMPLE_RE = re.compile(r"\bSAMPLE\s+BY\s+([^\n(;]+)", re.IGNORECASE)
_SKIP_INDEX_RE = re.compile(r"\bINDEX\s+(\w+)[^\n]*?TYPE\s+(\w+)", re.IGNORECASE)

# 疑似高基数列名（作 ORDER BY 首列时预警）
_HIGH_CARD_NAME_RE = re.compile(r"(uuid|guid|trace_id|request_id|session_id|rand|hash)$", re.IGNORECASE)
# 疑似时间列名
_TIME_NAME_RE = re.compile(r"(^ts$|_time$|_at$|^time$|timestamp|created|updated|datetime)", re.IGNORECASE)
# 疑似金额列名
_MONEY_NAME_RE = re.compile(r"(amount|money|price|fee|cost|balance|total_amt|pay_amt)", re.IGNORECASE)
# 疑似状态/枚举列名
_ENUM_NAME_RE = re.compile(r"(status|type|state|level|channel|platform|gender)$", re.IGNORECASE)


@dataclass
class DdlIssue:
    rule_id: str
    severity: str
    title: str
    evidence: str
    suggestion: str
    spec_ref: str


def _split_top_level(text: str) -> list[str]:
    """按括号深度 0 的逗号切分（列定义、索引、约束各自成段）。"""
    parts, buf, depth = [], [], 0
    for ch in text:
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
        if ch == "," and depth == 0:
            parts.append("".join(buf).strip())
            buf = []
        else:
            buf.append(ch)
    if buf:
        parts.append("".join(buf).strip())
    return [p for p in parts if p]


def _parse_columns(body: str) -> list[dict]:
    columns = []
    for part in _split_top_level(body):
        head = part.split()[0] if part.split() else ""
        if head.upper() in ("INDEX", "CONSTRAINT", "PROJECTION", "PRIMARY", "BLOOM"):
            continue
        m = re.match(r"([`\"\[]?[\w]+[`\"\]]?)\s+([A-Za-z][\w]*(?:\([^)]*\))?(?:\([^)]*\))?)", part)
        if not m:
            continue
        name, col_type = m.group(1).strip("`\"[]"), m.group(2)
        cm = re.search(r"COMMENT\s+'([^']*)'", part, re.IGNORECASE)
        columns.append(
            {
                "name": name,
                "type": col_type,
                "nullable": col_type.startswith("Nullable"),
                "low_cardinality": col_type.startswith("LowCardinality"),
                "comment": cm.group(1) if cm else "",
            }
        )
    return columns


def parse_ddl(ddl: str) -> dict:
    m_body = re.search(r"\((.*)\)\s*ENGINE", ddl, re.DOTALL | re.IGNORECASE)
    if not m_body:
        # 宽松一点：第一对顶层括号
        m_body = re.search(r"\(((?:[^()]|\([^)]*\))*)\)", ddl, re.DOTALL)
    if not m_body:
        return {"ok": False, "error": "未能定位列定义区（CREATE TABLE 的括号体）"}

    eng = _ENGINE_RE.search(ddl)
    part = _PARTITION_RE.search(ddl)
    ob = _ORDER_BY_RE.search(ddl)
    pk = _PRIMARY_KEY_RE.search(ddl)
    ttl = _TTL_RE.search(ddl)
    sample = _SAMPLE_RE.search(ddl)

    order_cols = []
    if ob:
        raw = (ob.group(1) or ob.group(2) or "").strip()
        order_cols = [c.strip().strip("`\"[] ").split()[0] for c in raw.split(",") if c.strip()]
    pk_cols = []
    if pk:
        raw = (pk.group(1) or pk.group(2) or "").strip()
        pk_cols = [c.strip().strip("`\"[] ").split()[0] for c in raw.split(",") if c.strip()]

    return {
        "ok": True,
        "engine": eng.group(1) if eng else None,
        "engine_args": (eng.group(2) or "").strip() if eng and eng.group(2) else "",
        "partition_by": part.group(1).strip() if part else None,
        "order_by": order_cols,
        "primary_key": pk_cols,
        "ttl": ttl.group(1).strip() if ttl else None,
        "sample_by": sample.group(1).strip() if sample else None,
        "skip_indexes": [{"name": n, "type": t} for n, t in _SKIP_INDEX_RE.findall(ddl)],
        "columns": _parse_columns(m_body.group(1)),
    }


def advise_ddl(ddl: str) -> dict:
    """评估建表 DDL，返回 {ok, parsed, issues, summary}。"""
    parsed = parse_ddl(ddl)
    if not parsed.get("ok"):
        return {"ok": False, "error": parsed.get("error"), "issues": [], "summary": "DDL 解析失败，请检查语句完整性"}

    issues: list[DdlIssue] = []
    engine = parsed["engine"] or ""
    cols = parsed["columns"]
    col_types = {c["name"]: c["type"] for c in cols}
    order_cols: list[str] = parsed["order_by"]

    def add(rule_id, severity, title, evidence, suggestion, spec_ref):
        issues.append(DdlIssue(rule_id, severity, title, evidence, suggestion, spec_ref))

    # 1. 引擎缺失 / 生产禁用引擎
    if not engine:
        add("no_engine", "error", "未声明 ENGINE", "ENGINE 子句缺失", "MergeTree 家族必须显式声明 ENGINE；按去重/回撤/聚合语义选型。", "规范 2.2-1")
    elif engine in ("Kafka", "Buffer", "RabbitMQ", "MySQL", "JDBC", "ODBC"):
        add(
            "bad_engine", "error", f"生产表禁用 {engine} 引擎直接落地", f"ENGINE = {engine}",
            "Kafka/RabbitMQ 引擎只作摄入管道（MV 落地到 MergeTree）；Buffer 异常重启丢数据；外部表引擎仅做联邦查询。", "规范 2.2-2",
        )

    # 2. MergeTree 家族必须有 ORDER BY
    is_family = "MergeTree" in engine if engine else False
    if engine and is_family and not order_cols:
        add(
            "no_order_by", "error", "MergeTree 家族缺少 ORDER BY", "ORDER BY 子句缺失",
            "按'低基数维度在前、时间在后'显式设计：ORDER BY (tenant_id, event_type, event_date)。官方：对的排序键可达 100x。", "规范 2.3-1",
        )

    # 3. ORDER BY 首列疑似高基数/时间
    if order_cols:
        first = order_cols[0]
        first_type = col_types.get(first, "")
        if _HIGH_CARD_NAME_RE.search(first) or first_type.upper().startswith("UUID"):
            add(
                "order_by_high_card_first", "warning", f"ORDER BY 首列 {first} 疑似高基数（UUID/随机 ID）",
                f"ORDER BY ({', '.join(order_cols)})",
                "首列高基数会稀释稀疏索引：改为低基数维度在前、高基数/时间在后。上线后不可改，需新表迁移。", "规范 2.3-1",
            )
        elif _TIME_NAME_RE.search(first) or first_type.lower().startswith(("datetime", "date")):
            add(
                "order_by_time_first", "warning", f"ORDER BY 首列 {first} 是时间列",
                f"ORDER BY ({', '.join(order_cols)})",
                "时间列打头使其他维度过滤失效（时间范围无法利用前缀）。重排为 (维度..., 时间列) 的漏斗结构。", "规范 2.3-1",
            )

    # 4. PRIMARY KEY 必须是 ORDER BY 前缀
    if parsed["primary_key"] and order_cols:
        if parsed["primary_key"] != order_cols[: len(parsed["primary_key"])]:
            add(
                "pk_not_prefix", "error", "PRIMARY KEY 不是 ORDER BY 的前缀",
                f"PRIMARY KEY ({', '.join(parsed['primary_key'])}) / ORDER BY ({', '.join(order_cols)})",
                "PRIMARY KEY 只能取 ORDER BY 的前缀子集（用于减小内存稀疏索引），不允许出现 ORDER BY 之外的列或乱序。", "规范 2.3-2",
            )

    # 5. 排序键列数过多
    if len(order_cols) > 4:
        add(
            "order_by_too_long", "info", f"ORDER BY 列数 {len(order_cols)} > 4",
            f"ORDER BY ({', '.join(order_cols)})",
            "排序键过长稀释前缀压缩收益并拖慢合并，一般 ≤ 4 列，保留过滤频率最高的前缀。", "规范 2.3-1",
        )

    # 6. 分区粒度
    pb = (parsed["partition_by"] or "").strip()
    if pb and pb != "tuple()":
        if ("toYYYYMMDD" in pb or "toDate" in pb) and not parsed["ttl"]:
            add(
                "over_partition", "warning", "细粒度分区但无 TTL（过度分区风险）",
                f"PARTITION BY {pb}，无 TTL",
                "分区是数据管理手段：超过几十个分区多半过度（parts 不跨分区合并，官方实测慢 46x）。无 TTL/数据 < 10 亿行建议 PARTITION BY tuple() 或改月分区；有 TTL 时分区粒度对齐 TTL。", "规范 2.4-1/2.4-2",
            )

    # 7. Nullable 滥用
    nullable = [c["name"] for c in cols if c["nullable"]]
    if len(nullable) > max(3, len(cols) * 0.3):
        add(
            "nullable_abuse", "warning", f"Nullable 列过多（{len(nullable)}/{len(cols)}）",
            f"Nullable 列: {', '.join(nullable[:8])}{'…' if len(nullable) > 8 else ''}",
            "Nullable 额外挂 UInt8 null 位图，拖慢查询与压缩。用默认值（0、''、epoch）+ 哨兵值；仅外部无法约束的数据用 Nullable。", "规范 2.5-6",
        )

    # 8. 金额用 Float
    for c in cols:
        base = c["type"].replace("Nullable(", "").rstrip(")")
        if base.startswith("Float") and _MONEY_NAME_RE.search(c["name"]):
            add(
                "float_money", "error", f"金额列 {c['name']} 使用 {base}",
                f"{c['name']} {c['type']}",
                "金额/费率必须 Decimal(18, x)，Float 有精度误差。", "规范 2.5-3",
            )
            break

    # 9. 疑似枚举列用 String 且无 LowCardinality
    plain_status = [c["name"] for c in cols if _ENUM_NAME_RE.search(c["name"]) and c["type"].startswith("String") and not c["low_cardinality"]]
    if plain_status:
        add(
            "no_low_cardinality", "info", f"低基数列建议 LowCardinality/Enum：{', '.join(plain_status[:4])}",
            f"String 列: {', '.join(plain_status[:4])}",
            "去重值 < 1 万的字符串列用 LowCardinality(String) 或 Enum8；配合 ZSTD 压缩收益明显。", "规范 2.5-1/2.5-2",
        )

    # 10. ReplacingMergeTree 版本列 / CollapsingMergeTree Sign
    if engine and "Replacing" in engine:
        args = parsed["engine_args"]
        if args:
            ver = args.split(",")[0].strip().strip("'\"")
            if ver and not _TIME_NAME_RE.search(ver) and "version" not in ver.lower() and "seq" not in ver.lower():
                add(
                    "rmt_bad_version", "warning", f"ReplacingMergeTree 版本列 {ver} 疑似非单调递增",
                    f"ENGINE = {engine}({args})",
                    "版本列必须单调递增（updated_at 时间戳或摄入 seq），否则'最新版本'无定义；软删场景加 is_deleted。", "规范 2.9-2",
                )
        else:
            add(
                "rmt_no_version", "warning", "ReplacingMergeTree 未指定版本列",
                "ENGINE = ReplacingMergeTree()",
                "加版本列：ENGINE = ReplacingMergeTree(updated_at)，否则按插入顺序取值，乱序写入时'最新'不确定。", "规范 2.9-2",
            )
    if engine and "Collapsing" in engine:
        sign_cols = [c["name"] for c in cols if c["type"].upper().startswith(("INT8", "TINYINT")) or "sign" in c["name"].lower()]
        if not sign_cols:
            add(
                "collapsing_no_sign", "error", "CollapsingMergeTree 缺少 Sign 列",
                f"ENGINE = {engine}",
                "需要 Sign Int8 列（±1），查询必须 SUM(Sign * measure)；乱序场景用 VersionedCollapsingMergeTree(Sign, Ver)。", "规范 2.2-1 / 4.3-3",
            )

    # 11. 有时间列但无 TTL（大表提示）
    has_dt = any(t.lower().startswith("datetime") for t in col_types.values())
    if has_dt and not parsed["ttl"]:
        add(
            "no_ttl", "info", "有时间列但未声明 TTL",
            "TTL 子句缺失",
            "明细大表应声明 TTL（或明确永久保留）；TTL 粒度 = 分区粒度时整分区删除效率最高。", "规范 2.8-1",
        )

    # 12. 无跳数索引提示（非键过滤列无从判断，仅在完全无索引时提示）
    if not parsed["skip_indexes"] and len(cols) > 10:
        add(
            "no_skip_index", "info", "宽表无跳数索引",
            f"{len(cols)} 列，0 个 DATA SKIP INDEX",
            "对不在排序键但常被过滤的列加索引：minmax(数值/时间)、set(低基数)、bloom_filter(高基数/数组)、tokenbf/ngrambf(文本)；EXPLAIN indexes=1 验证效果。", "规范 2.7-1/2.7-2",
        )

    # 13. 排序键上建了跳数索引（浪费）
    if parsed["skip_indexes"] and order_cols and any(i["name"] in order_cols for i in parsed["skip_indexes"]):
        add(
            "skip_index_on_key", "warning", "排序键列上建跳数索引是浪费",
            f"skip indexes: {parsed['skip_indexes']}",
            "跳数索引只加在**不在排序键**但常被过滤的列；排序键前缀列已被稀疏索引覆盖。请核对各 INDEX 的列是否与 ORDER BY 重叠。", "规范 2.7-1",
        )

    issues.sort(key=lambda i: {"error": 0, "warning": 1, "info": 2}.get(i.severity, 3))
    counts = {"error": 0, "warning": 0, "info": 0}
    for i in issues:
        counts[i.severity] += 1
    summary = (
        f"引擎 {engine or '未知'}，{len(cols)} 列，排序键 {len(order_cols)} 列，"
        f"发现 {len(issues)} 处问题：❌{counts['error']} / ⚠️{counts['warning']} / ℹ️{counts['info']}"
    )
    return {
        "ok": True,
        "parsed": {k: v for k, v in parsed.items() if k != "ok"},
        "issues": [asdict(i) for i in issues],
        "counts": counts,
        "summary": summary,
    }
