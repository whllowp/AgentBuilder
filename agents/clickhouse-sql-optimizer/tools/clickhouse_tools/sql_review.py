"""SQL 静态审查规则引擎：按《clickhouse开发规范.md》第 4/5 章提炼的 14 条规则。

不依赖数据库连接，纯文本启发式；表结构未知时规则措辞为"若命中排序键/分区键"。
"""
from __future__ import annotations

import re
from dataclasses import asdict, dataclass

# 键列上常见的函数包裹（命中排序键/分区键时裁剪失效）
_KEY_FUNC_RE = re.compile(
    r"\b(toDate|toDateTime|toYYYYMM|toYYYYMMDD|toYYYYWW|toMonday|toStartOfDay|"
    r"toStartOfHour|toStartOfMonth|toStartOfQuarter|formatDateTime|substr|substring|"
    r"lower|upper|toString|toUInt\d+|toInt\d+)\s*\(",
    re.IGNORECASE,
)
_SELECT_STAR_RE = re.compile(r"\bSELECT\s+\*", re.IGNORECASE)
_DISTINCT_STAR_RE = re.compile(r"\bSELECT\s+DISTINCT\s+\*", re.IGNORECASE)
_WHERE_RE = re.compile(r"\bWHERE\b", re.IGNORECASE)
_OFFSET_COMMA_RE = re.compile(r"\bLIMIT\s+(\d+)\s*,\s*(\d+)", re.IGNORECASE)
_OFFSET_KW_RE = re.compile(r"\bOFFSET\s+(\d+)", re.IGNORECASE)
_FINAL_RE = re.compile(r"\bFROM\s+[\w.`\"]+\s+FINAL\b", re.IGNORECASE)
_LEADING_LIKE_RE = re.compile(r"\bLIKE\s+'%", re.IGNORECASE)
_COUNT_DISTINCT_RE = re.compile(r"\bcount\s*\(\s*(DISTINCT|uniqExact)\b", re.IGNORECASE)
_JOIN_RE = re.compile(r"\bJOIN\b", re.IGNORECASE)
_IN_SUBQUERY_RE = re.compile(r"\b(IN|NOT\s+IN)\s*\(\s*SELECT\b", re.IGNORECASE)
_ORDER_BY_RE = re.compile(r"\bORDER\s+BY\b", re.IGNORECASE)
_LIMIT_RE = re.compile(r"\bLIMIT\b", re.IGNORECASE)
_ALTER_MUTATION_RE = re.compile(r"\bALTER\s+TABLE\b[^;]*\b(DELETE|UPDATE)\b", re.IGNORECASE)
_INSERT_VALUES_RE = re.compile(r"\bINSERT\s+INTO\b[^;]*?\bVALUES\b", re.IGNORECASE)
_TUPLE_SEP_RE = re.compile(r"\)\s*,\s*\(")
_COMMA_JOIN_RE = re.compile(r"\bFROM\s+[\w.`\"]+\s*,\s*[\w.`\"]+", re.IGNORECASE)
_SELECT_RE = re.compile(r"\bSELECT\b", re.IGNORECASE)
_FROM_RE = re.compile(r"\bFROM\b", re.IGNORECASE)

_SQL_KEYWORD_RE = re.compile(
    r"\b(SELECT|INSERT|ALTER|DELETE|UPDATE|CREATE|WITH|EXPLAIN|GRANT|RENAME|TRUNCATE|OPTIMIZE|SHOW|SYSTEM|SET|USE|DESC)\b",
    re.IGNORECASE,
)


@dataclass
class Issue:
    rule_id: str
    severity: str  # error / warning / info
    title: str
    evidence: str
    suggestion: str
    spec_ref: str


def _statements(sql: str) -> list[str]:
    """按分号切分语句（忽略单引号字符串内的分号），剔除注释与空串。"""
    stmts, buf, in_str = [], [], False
    i = 0
    while i < len(sql):
        ch = sql[i]
        if ch == "'" and (i == 0 or sql[i - 1] != "\\"):
            in_str = not in_str
        if ch == ";" and not in_str:
            stmts.append("".join(buf))
            buf = []
        else:
            buf.append(ch)
        i += 1
    if buf:
        stmts.append("".join(buf))
    cleaned = []
    for s in stmts:
        s = re.sub(r"--[^\n]*", "", s)
        s = re.sub(r"/\*.*?\*/", "", s, flags=re.DOTALL)
        if s.strip():
            cleaned.append(s.strip())
    return cleaned


def _evidence(stmt: str, match: re.Match, width: int = 60) -> str:
    start = max(match.start() - 10, 0)
    snippet = stmt[start : match.end() + width].replace("\n", " ").strip()
    return snippet[:120] + ("…" if len(snippet) > 120 else "")


def _check_select_star(stmts: list[str]) -> list[Issue]:
    issues = []
    for s in stmts:
        m = _SELECT_STAR_RE.search(s) or _DISTINCT_STAR_RE.search(s)
        if m:
            issues.append(
                Issue(
                    rule_id="select_star",
                    severity="error",
                    title="禁止 SELECT *（含 DISTINCT *）",
                    evidence=_evidence(s, m),
                    suggestion="列存按列读：明确列出所需列。官方实测列裁剪常有 10x 级差异；EXPLAIN 的 Read columns 可验证。",
                    spec_ref="规范 4.1-1",
                )
            )
    return issues


def _check_no_where(stmts: list[str]) -> list[Issue]:
    issues = []
    for s in stmts:
        if _SELECT_RE.search(s) and _FROM_RE.search(s) and not _WHERE_RE.search(s):
            m = _SELECT_RE.search(s)
            issues.append(
                Issue(
                    rule_id="no_where",
                    severity="warning",
                    title="SELECT 无 WHERE 条件（全表扫描）",
                    evidence=_evidence(s, m),
                    suggestion="大表查询必须带 WHERE，且过滤条件尽量命中排序键前缀或分区键；纯聚合需求应走预聚合表（MV/投影）。",
                    spec_ref="规范 4.1-2",
                )
            )
    return issues


def _check_key_function(stmts: list[str]) -> list[Issue]:
    issues = []
    for s in stmts:
        wm = _WHERE_RE.search(s)
        if not wm:
            continue
        where_part = s[wm.start() :]
        m = _KEY_FUNC_RE.search(where_part)
        if m:
            issues.append(
                Issue(
                    rule_id="key_function",
                    severity="warning",
                    title="WHERE 中对列使用函数包裹（若该列在排序键/分区键上则裁剪失效）",
                    evidence=_evidence(where_part, m),
                    suggestion="改写为半开区间或等值比较：toDate(ts)=d → ts>=d AND ts<d+1；toYYYYMM(c)=m → c>=月初 AND c<次月初。改写后用 EXPLAIN 确认 Key Condition 不再是 unknown。",
                    spec_ref="规范 4.1-3",
                )
            )
    return issues


def _check_big_offset(stmts: list[str]) -> list[Issue]:
    issues = []
    for s in stmts:
        m = _OFFSET_COMMA_RE.search(s)
        offset = int(m.group(1)) if m else None
        if offset is None:
            m = _OFFSET_KW_RE.search(s)
            offset = int(m.group(1)) if m else None
        if offset is not None and offset >= 1000 and m is not None:
            issues.append(
                Issue(
                    rule_id="big_offset",
                    severity="warning",
                    title=f"大偏移分页（offset={offset}）",
                    evidence=_evidence(s, m),
                    suggestion="LIMIT offset,n 需要先扫描并丢弃 offset 行。改用 keyset 分页：WHERE (id, ts) > (last_id, last_ts) ORDER BY id, ts LIMIT n。",
                    spec_ref="规范 4.1-4",
                )
            )
    return issues


def _check_final(stmts: list[str]) -> list[Issue]:
    issues = []
    for s in stmts:
        m = _FINAL_RE.search(s)
        if m:
            issues.append(
                Issue(
                    rule_id="final_read_cost",
                    severity="info",
                    title="查询使用 FINAL（有查询时代价）",
                    evidence=_evidence(s, m),
                    suggestion="FINAL 读更多数据且限制部分下推（官方 1.5 亿行实测 1.5s vs argMax 1.0s）。高频报表：MV+argMax 预物化最新值，或 LIMIT 1 BY key ORDER BY version DESC；低频后台任务可保留 FINAL。",
                    spec_ref="规范 2.9-1 / 4.3-1",
                )
            )
    return issues


def _check_leading_like(stmts: list[str]) -> list[Issue]:
    issues = []
    for s in stmts:
        m = _LEADING_LIKE_RE.search(s)
        if m:
            issues.append(
                Issue(
                    rule_id="leading_wildcard_like",
                    severity="warning",
                    title="LIKE 前导通配（全块扫描）",
                    evidence=_evidence(s, m),
                    suggestion="'%xxx%' 无法用主键裁剪。给该列建 tokenbf_v1（分词）/ngrambf_v1（子串）跳数索引并配 hasToken()，或 v26.2+ 用 inverted 倒排索引。",
                    spec_ref="规范 4.1-8",
                )
            )
    return issues


def _check_count_distinct(stmts: list[str]) -> list[Issue]:
    issues = []
    for s in stmts:
        m = _COUNT_DISTINCT_RE.search(s)
        if m:
            issues.append(
                Issue(
                    rule_id="exact_distinct",
                    severity="info",
                    title="精确去重 count(DISTINCT)/uniqExact",
                    evidence=_evidence(s, m),
                    suggestion="基数上亿时改 uniq()（误差<1%，内存恒定）或 uniqCombined()；分位数用 quantileTDigest。业务允许近似时收益显著。",
                    spec_ref="规范 4.1-7",
                )
            )
    return issues


def _check_joins(stmts: list[str]) -> list[Issue]:
    issues = []
    for s in stmts:
        joins = _JOIN_RE.findall(s)
        if len(joins) >= 4:
            issues.append(
                Issue(
                    rule_id="too_many_joins",
                    severity="warning",
                    title=f"单查询 {len(joins)} 个 JOIN（交互查询上限 3~4）",
                    evidence=f"JOIN x{len(joins)}: {s[:100]}…",
                    suggestion="在 ETL 层预关联成宽表，或维度小表改字典 dictGet（官方实测约 3x）；v24.4+ 谓词下推与 v25.x 多表重排可缓解但不能消除复杂度。",
                    spec_ref="规范 4.2-2/4.2-3",
                )
            )
        m = _COMMA_JOIN_RE.search(s)
        if m:
            issues.append(
                Issue(
                    rule_id="comma_join",
                    severity="warning",
                    title="逗号连接（无 JOIN 条件的 CROSS 风格）",
                    evidence=_evidence(s, m),
                    suggestion="显式写 JOIN ... ON 并把过滤条件放进 JOIN ON/WHERE，让 v24.4+ 谓词下推生效；避免无意识笛卡尔积。",
                    spec_ref="规范 4.2-1",
                )
            )
    return issues


def _check_in_subquery(stmts: list[str]) -> list[Issue]:
    issues = []
    for s in stmts:
        m = _IN_SUBQUERY_RE.search(s)
        if m:
            issues.append(
                Issue(
                    rule_id="in_subquery",
                    severity="info",
                    title="IN (SELECT ...) 子查询",
                    evidence=_evidence(s, m),
                    suggestion="Distributed 表下子查询会在每个分片全量执行：改 GLOBAL IN，或把右侧物化为临时表/字典；右表大时评估 grace_hash JOIN。",
                    spec_ref="规范 4.2-5",
                )
            )
    return issues


def _check_order_no_limit(stmts: list[str]) -> list[Issue]:
    issues = []
    for s in stmts:
        if _ORDER_BY_RE.search(s) and _SELECT_RE.search(s) and not _LIMIT_RE.search(s):
            m = _ORDER_BY_RE.search(s)
            issues.append(
                Issue(
                    rule_id="order_no_limit",
                    severity="info",
                    title="ORDER BY 无 LIMIT（全量排序）",
                    evidence=_evidence(s, m),
                    suggestion="若结果集大，加 LIMIT（配合 optimize_read_in_order 命中排序键可免排序）；确需全量排序时评估 max_bytes_before_external_sort。",
                    spec_ref="规范 4.1-6",
                )
            )
    return issues


def _check_mutation(stmts: list[str]) -> list[Issue]:
    issues = []
    for s in stmts:
        m = _ALTER_MUTATION_RE.search(s)
        if m:
            issues.append(
                Issue(
                    rule_id="mutation_api",
                    severity="warning",
                    title="mutation（ALTER TABLE ... DELETE/UPDATE）",
                    evidence=_evidence(s, m),
                    suggestion="mutation 后台重写整个 part，禁止当常规 API。日常少量删除用轻量 DELETE FROM t WHERE ...；批量重写放低峰并用 mutations_sync=0 + system.mutations 监控；到期数据靠 TTL。",
                    spec_ref="规范 2.8-3 / 3-5",
                )
            )
    return issues


def _check_small_insert(stmts: list[str]) -> list[Issue]:
    issues = []
    for s in stmts:
        m = _INSERT_VALUES_RE.search(s)
        if m and not _TUPLE_SEP_RE.search(s[m.end():]):
            issues.append(
                Issue(
                    rule_id="single_row_insert",
                    severity="error",
                    title="单行 VALUES 插入（Too many parts 风险）",
                    evidence=_evidence(s, m),
                    suggestion="攒批：单次 INSERT ≥ 数千行（1~50MB），间隔 ≥ 1s；客户端无法改造时开 async_insert=1, wait_for_async_insert=1；禁止应用循环单条 INSERT。",
                    spec_ref="规范 3-1/3-2",
                )
            )
    return issues


_CHECKS = [
    _check_select_star,
    _check_no_where,
    _check_key_function,
    _check_big_offset,
    _check_final,
    _check_leading_like,
    _check_count_distinct,
    _check_joins,
    _check_in_subquery,
    _check_order_no_limit,
    _check_mutation,
    _check_small_insert,
]

_RULE_COUNT = 14  # 规则族数量（含 JOIN 组与插入组的子规则）


def review_sql(sql: str) -> dict:
    """审查一段 SQL 文本，返回 {ok, statements, issues, summary}。"""
    stmts = [s for s in _statements(sql) if _SQL_KEYWORD_RE.search(s)]
    if not stmts:
        return {"ok": False, "statements": 0, "issues": [], "summary": "未识别到 SQL 语句", "rule_count": _RULE_COUNT}

    issues: list[Issue] = []
    for check in _CHECKS:
        issues.extend(check(stmts))
    issues.sort(key=lambda i: {"error": 0, "warning": 1, "info": 2}.get(i.severity, 3))

    counts = {"error": 0, "warning": 0, "info": 0}
    for i in issues:
        counts[i.severity] += 1
    if not issues:
        summary = f"共 {len(stmts)} 条语句，静态审查未发现问题（{_RULE_COUNT} 条规则）"
    else:
        summary = (
            f"共 {len(stmts)} 条语句，发现 {len(issues)} 处问题："
            f"❌{counts['error']} / ⚠️{counts['warning']} / ℹ️{counts['info']}"
        )
    return {
        "ok": True,
        "statements": len(stmts),
        "issues": [asdict(i) for i in issues],
        "counts": counts,
        "summary": summary,
        "rule_count": _RULE_COUNT,
    }
