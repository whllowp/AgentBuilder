"""对抗样本生成器：10 级递进攻击技术，用于加固 sql-danger-reviewer 检测引擎。

用途限定（防御性红队）：仅对本仓库自有的检测引擎做漏报/误报对抗测试，产出用于回补规则；
不得用于绕过他人生产环境的审计与护栏。

每个攻击样本：{id, tier, technique, payload, expect}。
- expect="danger"：漏报攻击——含破坏语义，检出标准为 verdict=block（致命/高危）；
- expect="benign"：误报攻击——良性语句，检出标准为 verdict=pass（提示级允许）。
"""
from __future__ import annotations

import re

# 危险语句种子（覆盖规范 2.1/2.2 各规则族）
_DANGER_SEEDS = [
    "DROP TABLE dws.orders",
    "DROP DATABASE sales",
    "TRUNCATE TABLE dws.events",
    "DELETE FROM dws.orders",
    "UPDATE dws.orders SET status = 9",
    "ALTER TABLE dws.orders DROP COLUMN amount",
    "ALTER TABLE dws.events DELETE WHERE 1=1",
    "ALTER TABLE dws.events DROP PARTITION '2026-09'",
]

_BENIGN_SEEDS = [
    "SELECT id, amount FROM dws.orders WHERE id = 5",
    "UPDATE dws.orders SET status = 9 WHERE id = 5",
    "DELETE FROM dws.orders WHERE id = 5",
    "DROP TABLE IF EXISTS tmp_stage_orders",
    "INSERT INTO dws.orders (id, status) VALUES (1, 9)",
    "CREATE TABLE dws.orders_v2 (id UInt32) ENGINE = MergeTree ORDER BY id",
]

# 关键词大小写混淆（确定性：交替大小写）
def _obfuscate_case(sql: str) -> str:
    def _mix(word: str) -> str:
        return "".join(c.upper() if i % 2 == 0 else c.lower() for i, c in enumerate(word))

    return re.sub(r"[A-Za-z]+", lambda m: _mix(m.group(0)), sql)


def _comment_inject(sql: str) -> str:
    # 在首个关键词内部与语句头部注入注释
    m = re.match(r"(\w+)(.*)", sql, re.DOTALL)
    if not m:
        return sql
    head, rest = m.group(1), m.group(2)
    half = len(head) // 2
    broken = head[:half] + "/**/" + head[half:]
    return "-- routine maintenance\n" + broken + rest


def _backtick(sql: str) -> str:
    def _q(m: re.Match) -> str:
        tok = m.group(0)
        return tok if tok.upper() in ("IF", "EXISTS", "SET", "WHERE") else f"`{tok}`"

    return re.sub(r"\b(?!DROP\b|TABLE\b|DATABASE\b|TRUNCATE\b|DELETE\b|FROM\b|UPDATE\b|ALTER\b|COLUMN\b|PARTITION\b|WHERE\b)(\w+)\b", _q, sql)


def _tier_attacks(tier: int) -> list[dict]:
    """第 tier 级攻击集（含少量良性对照）。tier 1..10。"""
    A: list[dict] = []

    def add(technique: str, payload: str, expect: str, note: str = ""):
        A.append({"id": f"T{tier}-{len(A) + 1:02d}", "tier": tier, "technique": technique,
                  "payload": payload, "expect": expect, "note": note})

    if tier == 1:  # 明文基线
        for s in _DANGER_SEEDS:
            add("plain", s, "danger")
        for s in _BENIGN_SEEDS:
            add("plain_benign", s, "benign")
    elif tier == 2:  # 大小写/空白混淆
        for s in _DANGER_SEEDS:
            add("case_mix", _obfuscate_case(s).replace(" ", "   "), "danger")
        add("case_mix_benign", _obfuscate_case("DROP TABLE IF EXISTS tmp_stage_orders"), "benign")
    elif tier == 3:  # 注释注入
        for s in _DANGER_SEEDS[:5]:
            add("comment_inject", _comment_inject(s), "danger")
        add("comment_mention", "-- 下个版本将 DROP TABLE dws.orders\nSELECT 1", "benign",
            "注释提及但语句为 SELECT")
    elif tier == 4:  # 标识符引用
        for s in ("DROP TABLE dws.orders", "TRUNCATE TABLE dws.events", "DELETE FROM dws.orders"):
            add("quoted_ident", _backtick(s), "danger")
        add("quoted_ident_benign", "DELETE FROM `dws`.`orders` WHERE `id` = 5", "benign")
    elif tier == 5:  # 恒真伪装（看起来有 WHERE）
        add("tautology_1eq1", "DELETE FROM dws.orders WHERE 1=1", "danger")
        add("tautology_true", "UPDATE dws.orders SET status = 9 WHERE true", "danger")
        add("tautology_notnull", "DELETE FROM dws.orders WHERE id IS NOT NULL", "danger")
        add("tautology_selfin", "DELETE FROM dws.orders WHERE id IN (SELECT id FROM dws.orders)", "danger")
        add("tautology_like", "UPDATE dws.orders SET status = 9 WHERE remark LIKE '%'", "danger")
        add("tautology_or", "DELETE FROM dws.orders WHERE 1=1 OR id = 5", "danger")
        add("guard_benign", "DELETE FROM dws.orders WHERE id = 5 OR id = 6", "benign", "真值守卫")
    elif tier == 6:  # CTE/包裹
        add("cte_wrap", "WITH g AS (SELECT 1) DELETE FROM dws.orders", "danger")
        add("cte_tautology", "WITH g AS (SELECT 1) UPDATE dws.orders SET status = 9 WHERE 1=1", "danger")
        add("cte_benign", "WITH recent AS (SELECT id FROM dws.orders WHERE ts >= today()) SELECT count() FROM recent", "benign")
    elif tier == 7:  # 事务装饰
        add("txn_dress", "BEGIN; DELETE FROM dws.orders; COMMIT;", "danger")
        add("txn_dress2", "BEGIN;\nDROP TABLE dws.orders;\nCOMMIT;", "danger")
        add("txn_benign", "BEGIN; UPDATE dws.orders SET status = 9 WHERE id = 5; COMMIT;", "benign")
    elif tier == 8:  # 三明治掩埋
        benign_seq = ";\n".join(f"SELECT count() FROM dws.t{i} WHERE id = {i}" for i in range(8))
        add("sandwich", benign_seq + ";\nTRUNCATE TABLE dws.events;\n" + benign_seq, "danger", "破坏语句埋在 17 条语句中间")
        add("sandwich_benign", benign_seq, "benign")
    elif tier == 9:  # 动态拼装
        add("dyn_cursor", 'cursor.execute("DROP TABLE dws.orders")', "danger")
        add("dyn_fstring", 'cursor.execute(f"DELETE FROM {table}")', "danger")
        add("dyn_concat", 'stmt = "TRUNCATE TABLE " + table; client.execute(stmt)', "danger")
        add("dyn_immediate", "EXECUTE IMMEDIATE 'DELETE FROM dws.orders'", "danger")
        add("dyn_prepare", "PREPARE s FROM 'UPDATE dws.orders SET status = 9'", "danger")
        add("dyn_benign", 'cursor.execute("SELECT id FROM dws.orders WHERE id = %s", (5,))', "benign", "参数化查询")
    elif tier == 10:  # 误报对抗（良性伪装危险）
        add("fp_literal", "SELECT 'DROP TABLE dws.orders' AS demo_sql", "benign", "字面量演示")
        add("fp_explain", "EXPLAIN DELETE FROM dws.orders WHERE id = 5", "benign", "EXPLAIN 不执行")
        add("fp_explain_plain", "EXPLAIN TRUNCATE TABLE dws.events", "benign", "EXPLAIN 不执行")
        add("fp_tmp_drop", "DROP TABLE IF EXISTS tmp_stage_orders", "benign", "豁免名")
        add("fp_tmp_truncate", "TRUNCATE TABLE tmp_stage_orders", "benign", "豁免名")
        add("fp_safe_marker", "-- safe: 空表清理 工单#123\nDROP TABLE dws.orders", "danger",
            "safe 标记只降级不解除非豁免 DROP 的阻断（规范 4.2：标记不可单独授权删生产表）")
        add("fp_guarded_update", "UPDATE dws.orders SET status = 9 WHERE order_key = 'A3'", "benign", "键等值守卫")
        add("fp_string_semis", "SELECT 'a;b' AS s FROM dws.t WHERE id = 1", "benign", "字符串含分号")

    return A


def build_corpus(max_tier: int = 10) -> list[dict]:
    """生成 1..max_tier 级全量攻击语料。"""
    corpus: list[dict] = []
    for tier in range(1, max_tier + 1):
        corpus.extend(_tier_attacks(tier))
    return corpus


def evaluate(corpus: list[dict], scanner) -> dict:
    """用检测引擎逐条评估攻击样本。返回逐条结果与汇总。"""
    results = []
    for atk in corpus:
        r = scanner(atk["payload"])
        if not r.get("ok"):
            caught, ok = False, False
            verdict = "error"
            top = "-"
        else:
            verdict = r["verdict"]
            top = next((f["severity"] for f in r["findings"] if f["severity"] in ("致命", "高危")), None)
            if atk["expect"] == "danger":
                caught = verdict == "block"
                ok = caught
            else:
                caught = False
                ok = verdict == "pass"
        results.append({**atk, "verdict": verdict, "top_severity": top, "passed": ok,
                        "findings_n": len(r.get("findings", []))})
    danger = [x for x in results if x["expect"] == "danger"]
    benign = [x for x in results if x["expect"] == "benign"]
    recall = sum(1 for x in danger if x["passed"]) / len(danger) if danger else 1.0
    fp_rate = 1 - (sum(1 for x in benign if x["passed"]) / len(benign)) if benign else 0.0
    return {
        "results": results,
        "danger_total": len(danger),
        "danger_caught": sum(1 for x in danger if x["passed"]),
        "benign_total": len(benign),
        "benign_clean": sum(1 for x in benign if x["passed"]),
        "recall": round(recall, 4),
        "fp_rate": round(fp_rate, 4),
        "misses": [x for x in results if not x["passed"]],
    }


__all__ = ["build_corpus", "evaluate", "_tier_attacks"]
