"""规则式任务解析：识别输入类型（DDL / EXPLAIN / SQL 审查 / 建表需求）并提取语句与表名。"""
from __future__ import annotations

import re

_FENCE_RE = re.compile(r"```(?:sql|SQL)?\s*\n(.*?)```", re.DOTALL)
_CREATE_TABLE_RE = re.compile(r"\bCREATE\s+(TABLE|MATERIALIZED\s+VIEW)\b", re.IGNORECASE)
_EXPLAIN_MARKER_RE = re.compile(
    r"(Granules?\s*:|PrimaryKeyAll|Key\s*Condition\s*:|Parts\s*:|ReadFromMergeTree|EXPLAIN\s+PIPELINE|Query pipeline|^\s*Expression\s*\(\()", re.IGNORECASE | re.MULTILINE,
)
_QUERY_RE = re.compile(r"\b(SELECT|INSERT|ALTER|DELETE|WITH)\b", re.IGNORECASE)
_TABLE_RE = re.compile(r"\b(?:FROM|JOIN|INTO|UPDATE)\s+([`\"\[]?[\w.]+[`\"\]]?)", re.IGNORECASE)

# 建表需求意图（描述性需求，而非现成 CREATE TABLE 语句）
_DESIGN_INTENT_RE = re.compile(r"(建表|建一张|建个表|创建表|创建一张|设计表|设计一张|表设计|帮我生成.*表|新建.*表|怎么建|如何建)", re.IGNORECASE)
_TABLE_HINT_RE = re.compile(r"(?:表名[是为:：\s]*|叫\s*|名为\s*)([`\"\[]?[\w.]+[`\"\]]?)")
_SCENARIO_HINTS = [
    ("cdc_upsert", re.compile(r"(cdc|upsert|入湖|替换|去重|保留最新|最新版本)", re.IGNORECASE)),
    ("collapsing", re.compile(r"(回撤|折叠|collaps|撤销|增减)", re.IGNORECASE)),
    ("agg_rollup", re.compile(r"(汇总|预聚合|聚合表|rollup|看板|大盘|报表)", re.IGNORECASE)),
]


def detect_ddl_design(text: str) -> dict:
    """识别"帮我建一张表"类描述性需求，推断场景与表名。"""
    if _CREATE_TABLE_RE.search(text) or _QUERY_RE.search(text):
        return {"intent": False, "scenario": None, "table": None}
    if not _DESIGN_INTENT_RE.search(text):
        return {"intent": False, "scenario": None, "table": None}
    scenario = "append_log"
    for name, pattern in _SCENARIO_HINTS:
        if pattern.search(text):
            scenario = name
            break
    m = _TABLE_HINT_RE.search(text)
    table = m.group(1).strip("`\"[]") if m else ""
    return {"intent": True, "scenario": scenario, "table": table}


def _extract_sql_blocks(text: str) -> tuple[list[str], str]:
    """提取 ``` 代码块内的 SQL；无代码块时整体视为待分析文本。"""
    blocks = [b.strip() for b in _FENCE_RE.findall(text) if b.strip()]
    if blocks:
        sqls = [b for b in blocks if _QUERY_RE.search(b) or _CREATE_TABLE_RE.search(b)]
        return sqls, "\n".join(blocks)
    return [], text


def analyze_request(text: str) -> dict:
    """解析用户请求：返回 {kind, sqls, explain_text, ddl_text, tables, has_*}。"""
    blocks, remainder = _extract_sql_blocks(text)
    candidates = blocks if blocks else ([remainder.strip()] if _QUERY_RE.search(remainder) or _CREATE_TABLE_RE.search(remainder) else [])

    ddl_texts, explain_texts, sqls = [], [], []
    for cand in candidates:
        if _CREATE_TABLE_RE.search(cand):
            ddl_texts.append(cand)
        elif _EXPLAIN_MARKER_RE.search(cand) and not _QUERY_RE.search(cand):
            explain_texts.append(cand)  # 纯 EXPLAIN 输出（无 SELECT 关键字的执行计划文本）
        elif _QUERY_RE.search(cand):
            sqls.append(cand)

    # 代码块之外再扫一遍裸文本中的 EXPLAIN 输出特征
    if not explain_texts and ("Granules" in remainder or "Key Condition" in remainder):
        explain_texts.append(remainder)

    # 描述性建表需求（无现成 DDL）
    design = detect_ddl_design(text)

    tables: list[str] = []
    for chunk in sqls + ddl_texts:
        for m in _TABLE_RE.finditer(chunk):
            name = m.group(1).strip("`\"[]")
            if name.lower() not in ("select", "if", "not"):
                tables.append(name)
    if design["table"]:
        tables.append(design["table"])
    seen = set()
    tables = [t for t in tables if not (t in seen or seen.add(t))]

    has_ddl, has_explain, has_query = bool(ddl_texts), bool(explain_texts), bool(sqls)
    has_design = design["intent"]
    if has_ddl and (has_explain or has_query):
        kind = "mixed"
    elif has_ddl:
        kind = "ddl"
    elif has_design:
        kind = "ddl_design"
    elif has_explain:
        kind = "explain"
    elif has_query:
        kind = "sql_review"
    else:
        kind = "unknown"

    return {
        "kind": kind,
        "sqls": sqls,
        "ddl_texts": ddl_texts,
        "explain_texts": explain_texts,
        "ddl_design": design,
        "tables": tables[:10],
        "has_ddl": has_ddl,
        "has_explain": has_explain,
        "has_query": has_query,
        "has_design": has_design,
    }
