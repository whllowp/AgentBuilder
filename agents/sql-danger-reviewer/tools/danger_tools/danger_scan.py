"""高危操作代码检验引擎：按《高危操作代码检验规范.md》扫描破坏性 SQL/DDL 与脚本命令。

设计要点（对应规范第 3 章对抗对策）：
- 字符串字面量先掩码再匹配（`SELECT 'DROP TABLE x'` 不误报），掩出的字面量另行按 DGR-402 提示；
- 注释剥离采用**双规范化**：注释→空（对抗 `DR/**/OP` 断词拼回关键词）与注释→空格（保留相邻词边界），
  两种变体各自过一遍规则并去重 —— 规范 3.2 注入免疫；
- 大小写/多空白/反引号与双引号标识符统一（t_case / t_backtick 免疫）；
- WHERE 守卫分析在**字面量完整**的文本上做（`LIKE '%'` 恒真、`'A3'` 值守卫可识别）；
- 恒真条件（1=1 / true / IS NOT NULL / 自引用 IN / LIKE '%'）视为无守卫；
- EXPLAIN 前缀不实际执行 → 降级为提示；`-- safe:` 显式标记降一级（不解除非豁免 DROP 的阻断）；
- 应用代码动态拼装（execute/f-string/拼接/EXECUTE IMMEDIATE/PREPARE）→ DGR-205；
- 脚本命令（rm -rf、客户端 -q 直连执行破坏语句）→ DGR-50x。
"""
from __future__ import annotations

import re
from dataclasses import asdict, dataclass

# ---------- 基础正规化 ----------

_COMMENT_BLOCK_RE = re.compile(r"/\*.*?\*/", re.DOTALL)
_COMMENT_LINE_RE = re.compile(r"--[^\n]*|#[^\n]*")
_SAFE_MARKER_RE = re.compile(r"safe\s*[:：]\s*(\S[^\n]*)", re.IGNORECASE)
_STRING_RE = re.compile(r"'(?:[^'\\]|\\.)*'")
_BACKTICK_RE = re.compile(r"[`\"`]")

_DROP_DB_RE = re.compile(r"\bDROP\s+(?:DATABASE|SCHEMA)\b", re.IGNORECASE)
_DROP_TABLE_RE = re.compile(r"\bDROP\s+TABLE\s+(?:IF\s+EXISTS\s+)?[\w.]*", re.IGNORECASE)
_TRUNCATE_RE = re.compile(r"\bTRUNCATE\s+(?:TABLE\s+)?[\w.]*", re.IGNORECASE)
_DELETE_RE = re.compile(r"\bDELETE\s+FROM\s+[\w.]+", re.IGNORECASE)
_UPDATE_RE = re.compile(r"\bUPDATE\s+[\w.]+\s+SET\b", re.IGNORECASE)
_ALTER_DESTRUCTIVE_RE = re.compile(
    r"\bALTER\s+TABLE\s+[\w.]+.*?\b(DROP\s+COLUMN|DROP\s+PARTITION|DETACH\s+PARTITION|MODIFY\s+COLUMN|DROP\s+CONSTRAINT)\b",
    re.IGNORECASE,
)
_CK_MUTATION_RE = re.compile(r"\bALTER\s+TABLE\s+[\w.]+.*?\b(DELETE|UPDATE)\b", re.IGNORECASE)
_GRANT_RE = re.compile(r"\bGRANT\s+.*?\b(ALL|PUBLIC)\b|\bREVOKE\b", re.IGNORECASE | re.DOTALL)
_RENAME_RE = re.compile(r"\bRENAME\s+TABLE\b|\bEXCHANGE\s+TABLES\b", re.IGNORECASE)
_OPTIMIZE_RE = re.compile(r"\bOPTIMIZE\s+TABLE\b.*\bFINAL\b|\bVACUUM\s+FULL\b", re.IGNORECASE)
_EXPLAIN_PREFIX_RE = re.compile(r"^\s*(?:EXPLAIN|DESC(?:RIBE)?)\b", re.IGNORECASE)
_BEGIN_RE = re.compile(r"^\s*(?:BEGIN|START\s+TRANSACTION)\b", re.IGNORECASE)
_COMMIT_RE = re.compile(r"^\s*(?:COMMIT|ROLLBACK|END)\b", re.IGNORECASE)

_RM_RF_RE = re.compile(r"\brm\s+(-[a-zA-Z]*r[a-zA-Z]*f|-[a-zA-Z]*f[a-zA-Z]*r)\s+(\S+)", re.IGNORECASE)
_CLIENT_QUERY_RE = re.compile(
    r"\b(?:clickhouse-client|psql|mysql|beeline)\b[^;\n]*?(?:-q|--query|-e)\s*['\"]?([^'\";\n]+)", re.IGNORECASE
)

# 动态 SQL（应用代码上下文）
_DYNAMIC_EXEC_RE = re.compile(
    r"(?:cursor\.execute|\.execute|\.executemany|exec|EXECUTE\s+IMMEDIATE|sp_executesql|PREPARE\s+\w+\s+FROM)"
    r"[\s(]*[fN]?['\"]([^'\"]*)['\"]",
    re.IGNORECASE,
)
_DYNAMIC_CONCAT_RE = re.compile(
    r"['\"](?:DROP|TRUNCATE|DELETE|ALTER|GRANT|REVOKE|RENAME|OPTIMIZE|VACUUM|UPDATE|DETACH|EXCHANGE)[^'\"]*['\"]\s*\+",
    re.IGNORECASE,
)
_DYNAMIC_FSTRING_RE = re.compile(
    r"f['\"][^'\"]*(?:DROP\s+(?:TABLE|DATABASE)|DELETE\s+FROM|TRUNCATE|UPDATE\s+[\w.]+\s+SET)[^'\"]*['\"]",
    re.IGNORECASE,
)

# WHERE 守卫分析（在字面量完整文本上执行）
_WHERE_SPLIT_RE = re.compile(r"\bWHERE\b", re.IGNORECASE)
_CLAUSE_END_RE = re.compile(r"\b(GROUP\s+BY|ORDER\s+BY|HAVING|LIMIT|OFFSET|FOR\s+|RETURNING|SETTINGS)\b", re.IGNORECASE)
_SELF_IN_RE = re.compile(r"\bIN\s*\(\s*SELECT\s+[\w.]+\s+FROM\s+([\w.]+)\s*\)", re.IGNORECASE)
# 值域守卫：运算符后跟字面量（数字/引号）。符号运算符后不能加 \b（= 后是空格，非词边界）
_GUARD_EQ_RE = re.compile(r"[\w.\"]+\s*(?:=|!=|<>|>=|<=|>|<|BETWEEN|LIKE|IN\s*\()\s*['\"0-9]", re.IGNORECASE)
_GUARD_EQ_ANY_RE = re.compile(r"[\w.\"]+\s*(?:=|!=|<>|>=|<=|>|<|\bBETWEEN\b|\bLIKE\b|\bIN\b)", re.IGNORECASE)
_KEY_COL_RE = re.compile(r"(?:id|key|uid|code)", re.IGNORECASE)

_SEV_ORDER = {"致命": 0, "高危": 1, "中危": 2, "提示": 3}


@dataclass
class Finding:
    rule_id: str
    severity: str  # 致命 / 高危 / 中危 / 提示
    title: str
    evidence: str
    suggestion: str
    spec_ref: str
    statement_index: int = 0


def _split_statements(text: str) -> list[str]:
    """按分号切分（字符串内分号免疫）；返回去空白后的语句列表。"""
    stmts, buf, in_str = [], [], False
    i = 0
    while i < len(text):
        ch = text[i]
        if ch == "'" and (i == 0 or text[i - 1] != "\\"):
            in_str = not in_str
        if ch == ";" and not in_str:
            stmts.append("".join(buf))
            buf = []
        else:
            buf.append(ch)
        i += 1
    if buf:
        stmts.append("".join(buf))
    return [s.strip() for s in stmts if s.strip()]


def _strip_comments(stmt: str, join: bool) -> tuple[str, str]:
    """剥离注释。join=True 时注释替换为空串（对抗 DR/**/OP 断词），否则替换为空格（保留词边界）。"""
    comments: list[str] = []
    repl = "" if join else " "

    def _block(m: re.Match) -> str:
        comments.append(m.group(0))
        return repl

    def _line(m: re.Match) -> str:
        comments.append(m.group(0))
        return "\n" if not join else ""

    clean = _COMMENT_BLOCK_RE.sub(_block, stmt)
    clean = _COMMENT_LINE_RE.sub(_line, clean)
    return re.sub(r"\s+", " ", clean).strip(), " ".join(comments)


def _mask_strings(clean: str) -> tuple[str, list[str]]:
    """把单引号字面量替换为占位符；返回 (掩码文本, 字面量列表)。"""
    literals: list[str] = []

    def _sub(m: re.Match) -> str:
        literals.append(m.group(0))
        return " '__str__' "

    return _STRING_RE.sub(_sub, clean), literals


def _norm(masked: str) -> str:
    """统一反引号/双引号标识符与空白。"""
    s = _BACKTICK_RE.sub("", masked)
    return re.sub(r"\s+", " ", s).strip()


def _table_of(match: re.Match, fallback: str = "") -> str:
    toks = match.group(0).split()
    return toks[-1].strip("`\"") if toks else fallback


def _where_clause(norm_stmt: str) -> str | None:
    m = _WHERE_SPLIT_RE.search(norm_stmt)
    if not m:
        return None
    rest = norm_stmt[m.end():]
    end = _CLAUSE_END_RE.search(rest)
    return rest[: end.start()].strip() if end else rest.strip()


def _is_tautology(where: str) -> bool:
    w = re.sub(r"\s+", " ", where.strip().strip("()").strip()).lower()
    if not w:
        return True
    if re.fullmatch(r"(?:1\s*=\s*1|true|false\s*=\s*false|'t'|:t)", w):
        return True
    if re.fullmatch(r"[\w.]+\s+is\s+not\s+null", w):
        return True
    if re.fullmatch(r"[\w.]+\s+like\s+'%'", w):
        return True
    if " or " in f" {w} ":
        parts = re.split(r"\bor\b", w)
        return any(_is_tautology(p.strip()) for p in parts if p.strip())
    if " and " in f" {w} ":
        parts = re.split(r"\band\b", w)
        return all(_is_tautology(p.strip()) for p in parts if p.strip())
    return False


def _has_real_guard(where: str) -> bool:
    """WHERE 中存在值域过滤（比较/IN/BETWEEN/LIKE 带具体值）。在字面量完整文本上执行。"""
    if not where:
        return False
    return bool(_GUARD_EQ_RE.search(where) or _GUARD_EQ_ANY_RE.search(where))


def _is_self_in(where: str, outer_table: str) -> bool:
    m = _SELF_IN_RE.search(where)
    return bool(m and outer_table and m.group(1).strip("`\"").lower() == outer_table.lower())


def _sev_downgrade(sev: str) -> str:
    order = ["致命", "高危", "中危", "提示"]
    return order[min(order.index(sev) + 1, 3)]


def _looks_danger_literal(s: str) -> str | None:
    """文本内是否含破坏语义（用于 DGR-402 / 动态拼接判断）。"""
    if _DROP_DB_RE.search(s):
        return "DROP DATABASE/SCHEMA"
    if _DROP_TABLE_RE.search(s) or _TRUNCATE_RE.search(s):
        return "DROP TABLE / TRUNCATE"
    if re.search(r"\bDELETE\s+FROM\b", s, re.IGNORECASE) or _UPDATE_RE.search(s):
        return "DELETE/UPDATE"
    if _ALTER_DESTRUCTIVE_RE.search(s) or _CK_MUTATION_RE.search(s):
        return "ALTER 破坏性子句"
    return None


# ---------- 单语句扫描 ----------

def _scan_stmt(stmt: str, idx: int) -> list[Finding]:
    findings: list[Finding] = []
    seen: set[tuple] = set()

    for join in (False, True):  # 双规范化：空格变体 + 拼接变体，命中并集（规范 3.2）
        clean, comments = _strip_comments(stmt, join=join)
        if not clean:
            continue
        safe_marker = _SAFE_MARKER_RE.search(comments or "")
        masked, literals = _mask_strings(clean)
        norm = _norm(masked)
        # WHERE 守卫分析用字面量完整的规范化文本（识别 LIKE '%'、'A3' 等）
        norm_lit = _norm(clean)
        if not norm:
            continue
        is_explain = bool(_EXPLAIN_PREFIX_RE.match(norm))

        def add(rule_id, severity, title, evidence, suggestion, spec_ref):
            key = (rule_id, title.split("（")[0])
            if key in seen:
                return
            seen.add(key)
            sev = severity
            note = ""
            if safe_marker:
                sev = _sev_downgrade(sev)
                note = f"；-- safe 标记降为 {sev}（{safe_marker.group(1)[:30]}），仍需人工核对"
            if is_explain and sev in ("致命", "高危"):
                sev = "提示"
                rule_id = "DGR-403"
                note = "；EXPLAIN 前缀不实际执行，降为提示"
            findings.append(Finding(rule_id, sev, title, (evidence + note)[:160], suggestion + note, spec_ref, idx))

        if _DROP_DB_RE.search(norm):
            add("DGR-104", "致命", "DROP DATABASE/SCHEMA（删库）", norm[:120],
                "生产一律禁止；如为环境销毁需双人复核 + 备份归档 + 工单授权。", "规范 2.1 DGR-104")

        m = _DROP_TABLE_RE.search(norm)
        if m:
            table = _table_of(m)
            if re.match(r"^(tmp_|_staging|tmp$)", table, re.IGNORECASE):
                add("DGR-401", "提示", f"豁免名 DROP（{table}）", norm[:120],
                    "tmp/staging 表清理可放行，确认无下游依赖。", "规范 4.1")
            else:
                add("DGR-105", "致命", f"DROP TABLE {table}（非豁免名）", norm[:120],
                    "删表需：新表迁移评审或 RENAME 归档备份 + 审批工单 + 回滚 DDL。", "规范 2.1 DGR-105")

        m = _TRUNCATE_RE.search(norm)
        if m:
            table = _table_of(m)
            if re.match(r"^(tmp_|_staging|tmp$)", table, re.IGNORECASE):
                add("DGR-401", "提示", f"豁免名 TRUNCATE（{table}）", norm[:120], "tmp/staging 表清空可放行。", "规范 4.1")
            else:
                add("DGR-201", "高危", f"TRUNCATE TABLE {table}", norm[:120],
                    "全表清空不可逆：改 DELETE + 分批，或走审批 + 备份。", "规范 2.2 DGR-201")

        # DELETE / UPDATE 守卫分析（WHERE 取字面量完整文本）
        for re_, rule_id, label, tpos in (
            (_DELETE_RE, "DGR-101", "DELETE", -1),   # "DELETE FROM t" 尾 token 即表名
            (_UPDATE_RE, "DGR-102", "UPDATE", 1),    # "UPDATE t SET" 匹配尾部是 SET，表名取第 2 个 token
        ):
            m = re_.search(norm)
            if not m:
                continue
            toks = m.group(0).split()
            table = toks[tpos].strip("`\"") if abs(tpos) <= len(toks) else (toks[-1] if toks else "")
            where = _where_clause(norm_lit)
            if where is None:
                add(rule_id, "致命", f"{label} 无 WHERE（全表操作 {table}）", norm[:120],
                    "必须补键等值 WHERE；全量重写需求走新表迁移。", f"规范 2.1 {rule_id}")
            elif _is_tautology(where) or _is_self_in(where, table):
                add(rule_id, "致命", f"{label} WHERE 为恒真条件（等效全表 {table}）", f"... WHERE {where[:80]}",
                    "恒真条件（1=1/true/IS NOT NULL/自引用 IN/LIKE '%%'）等效无守卫，改为真实过滤。",
                    f"规范 2.1 DGR-103/{rule_id}")
            elif _has_real_guard(where):
                g = _GUARD_EQ_ANY_RE.search(where)
                col = g.group(0).split()[0].strip("`\"") if g else ""
                if col and _KEY_COL_RE.search(col):
                    add("DGR-403", "提示", f"{label} 带键条件（{col} ...）", f"... WHERE {where[:80]}",
                        "键等值条件视为有守卫；批量脚本建议分批 + 事务。", "规范 4.3")
                else:
                    add("DGR-203", "中危", f"{label} 条件疑似非唯一键（{col} ...）", f"... WHERE {where[:80]}",
                        "评估影响行数：非键条件可能命中大范围；加 LIMIT/分批与窗口审批。", "规范 2.2 DGR-203")
            else:
                add(rule_id, "致命", f"{label} 的 WHERE 无有效守卫", f"... WHERE {where[:80]}",
                    "WHERE 中无值域过滤（如仅有列间比较），按无守卫处理。", f"规范 2.1 {rule_id}")

        m = _ALTER_DESTRUCTIVE_RE.search(norm)
        if m:
            add("DGR-202", "高危", f"ALTER 破坏性子句（{m.group(1)}）", norm[:120],
                "DROP COLUMN/PARTITION、MODIFY COLUMN 不可逆：确认备份与新列兼容性，走变更审批。",
                "规范 2.2 DGR-202")

        m = _CK_MUTATION_RE.search(norm)
        if m and not _ALTER_DESTRUCTIVE_RE.search(norm):
            verb = m.group(1).upper()
            where = _where_clause(norm_lit)
            if where is None or _is_tautology(where):
                add("DGR-204", "致命", f"ClickHouse mutation 恒真/无条件（ALTER ... {verb}）", norm[:120],
                    "mutation 重写整个 part；恒真条件=全表重写。改轻量删除或新表迁移。",
                    "规范 2.2 DGR-204 / DGR-103")
            else:
                add("DGR-204", "高危", f"ClickHouse mutation（ALTER ... {verb}）", norm[:120],
                    "mutation 放低峰批处理 + mutations_sync=0 + system.mutations 监控。", "规范 2.2 DGR-204")

        if _GRANT_RE.search(norm):
            add("DGR-206", "高危", "权限变更（GRANT/REVOKE）", norm[:120],
                "ALL/PUBLIC 权限禁止常规合入；最小权限申请 + 安全复核。", "规范 2.2 DGR-206")

        if _RENAME_RE.search(norm):
            add("DGR-301", "中危", "RENAME/EXCHANGE TABLES", norm[:120],
                "对象级替换影响下游引用：核对血缘与消费方。", "规范 2.3 DGR-301")

        if _OPTIMIZE_RE.search(norm):
            add("DGR-303", "中危", "OPTIMIZE ... FINAL / VACUUM FULL", norm[:120],
                "重操作需窗口期执行。", "规范 2.3 DGR-303")

        # 字面量/注释中的危险词（不执行，仅提示；只在无更高级发现时输出，避免噪音）
        if not findings:
            for lit in literals:
                danger = _looks_danger_literal(lit)
                if danger:
                    add("DGR-402", "提示", f"字面量中含破坏语义（{danger}）", lit[:100],
                        "确认该字符串不会被拼接执行；动态执行路径见 DGR-205。", "规范 2.4 DGR-402")
                    break
            else:
                if comments:
                    danger = _looks_danger_literal(comments)
                    if danger:
                        add("DGR-402", "提示", f"注释中提及破坏操作（{danger}）", comments[:100],
                            "确认注释对应的语句在实现前已受检。", "规范 2.4 DGR-402")

    return findings


def _scan_dynamic_and_shell(text: str) -> list[Finding]:
    findings: list[Finding] = []
    seen: set[str] = set()
    for m in _DYNAMIC_EXEC_RE.finditer(text):
        lit = m.group(1)
        danger = _looks_danger_literal(lit)
        if not danger:
            continue
        probe = _norm(_strip_comments(lit, join=False)[0])
        where = _where_clause(probe)
        unguarded = where is None or _is_tautology(where)
        key = ("DGR-205", lit[:40])
        if key in seen:
            continue
        seen.add(key)
        findings.append(
            Finding("DGR-205", "致命" if unguarded else "高危",
                    f"动态拼装/执行破坏语句（{danger}）", m.group(0)[:120],
                    "参数化或移出动态 SQL；确需动态对象名时走白名单校验 + 审批。",
                    "规范 2.2 DGR-205")
        )
    if _DYNAMIC_CONCAT_RE.search(text) or _DYNAMIC_FSTRING_RE.search(text):
        first = text.strip().splitlines()[0][:120]
        findings.append(
            Finding("DGR-205", "高危", "字符串拼接/f-string 构造破坏语句", first,
                    "禁止拼接 DDL/DML：改参数绑定与白名单表名校验。", "规范 2.2 DGR-205")
        )
    for m in _RM_RF_RE.finditer(text):
        target = m.group(2)
        sev = "致命" if (target.startswith(("/", "~")) or "$" in target) else "高危"
        findings.append(
            Finding("DGR-501", sev, f"rm -rf 危险删除（{target}）", m.group(0)[:120],
                    "限制在明确目录内并加引号；禁止对根/家目录与未加引号变量递归删除。", "规范 2.5 DGR-501")
        )
    for m in _CLIENT_QUERY_RE.finditer(text):
        if _looks_danger_literal(m.group(1)):
            findings.append(
                Finding("DGR-502", "高危", "客户端 -q/-e 直连执行破坏语句", m.group(0)[:120],
                        "脚本内直连执行破坏语句需审批与环境校验（--dry-run 先行）。", "规范 2.5 DGR-502")
            )
    return findings


# ---------- 入口 ----------


def scan_code(text: str) -> dict:
    """扫描 SQL 脚本或含 SQL 的代码，返回 {ok, statements, findings, verdict, requires_approval, summary}。"""
    if not text or not text.strip():
        return {"ok": False, "statements": 0, "findings": [], "verdict": "error", "requires_approval": False,
                "summary": "输入为空"}

    stmts = _split_statements(text)
    findings: list[Finding] = []
    begin_seen = False
    for idx, stmt in enumerate(stmts, 1):
        n = _norm(_mask_strings(_strip_comments(stmt, join=False)[0])[0])
        if _BEGIN_RE.match(n):
            begin_seen = True
            continue
        if _COMMIT_RE.match(n):
            continue
        findings.extend(_scan_stmt(stmt, idx))

    findings.extend(_scan_dynamic_and_shell(text))

    has_destructive = any(f.severity in ("致命", "高危") for f in findings)
    if has_destructive and not (begin_seen or re.search(r"\bBEGIN\b|START\s+TRANSACTION", text, re.IGNORECASE)):
        findings.append(
            Finding("DGR-302", "中危", "破坏性操作未包裹事务", "-",
                    "DML 类操作放 BEGIN...ROLLBACK 可回滚窗口内验证；DDL 视数据库而定，至少分步执行。",
                    "规范 2.3 DGR-302", 0)
        )

    findings.sort(key=lambda f: _SEV_ORDER.get(f.severity, 9))
    counts = {"致命": 0, "高危": 0, "中危": 0, "提示": 0}
    for f in findings:
        counts[f.severity] += 1

    if counts["致命"]:
        verdict = "block"
    elif counts["高危"]:
        verdict = "block"  # 阻断合入，走 DBA 复核 + 授权（规范 2.2）
    elif counts["中危"]:
        verdict = "review"
    else:
        verdict = "pass"

    if not findings:
        summary = f"共 {len(stmts)} 条语句，未发现高危操作（DGR-1xx~5xx）"
    else:
        summary = (
            f"共 {len(stmts)} 条语句，发现 {len(findings)} 处："
            f"致命{counts['致命']} / 高危{counts['高危']} / 中危{counts['中危']} / 提示{counts['提示']}；verdict={verdict}"
        )
    return {
        "ok": True,
        "statements": len(stmts),
        "findings": [asdict(f) for f in findings],
        "counts": counts,
        "verdict": verdict,
        "requires_approval": counts["致命"] + counts["高危"] > 0,
        "summary": summary,
    }
