"""danger_scan 引擎测试：规则命中 + 豁免守卫 + 对抗混淆免疫 + 误报控制。"""
from danger_tools.danger_scan import scan_code


def test_delete_without_where_fatal():
    r = scan_code("DELETE FROM dws.orders")
    f = [x for x in r["findings"] if x["rule_id"] == "DGR-101"]
    assert f and f[0]["severity"] == "致命"
    assert r["verdict"] == "block" and r["requires_approval"]


def test_update_without_where_fatal():
    r = scan_code("UPDATE dws.orders SET status = 9")
    assert any(x["rule_id"] == "DGR-102" and x["severity"] == "致命" for x in r["findings"])


def test_drop_database_fatal():
    r = scan_code("DROP DATABASE sales")
    assert any(x["rule_id"] == "DGR-104" and x["severity"] == "致命" for x in r["findings"])


def test_drop_table_fatal_vs_tmp_exempt():
    r = scan_code("DROP TABLE dws.orders")
    assert any(x["rule_id"] == "DGR-105" and x["severity"] == "致命" for x in r["findings"])
    r2 = scan_code("DROP TABLE IF EXISTS tmp_stage_orders")
    only = [x for x in r2["findings"] if x["severity"] in ("致命", "高危")]
    assert not only and r2["verdict"] == "pass"


def test_truncate_high_and_tmp_exempt():
    r = scan_code("TRUNCATE TABLE dws.events")
    assert any(x["rule_id"] == "DGR-201" and x["severity"] == "高危" for x in r["findings"])
    assert scan_code("TRUNCATE TABLE tmp_stage_events")["verdict"] == "pass"


def test_guarded_delete_passes():
    r = scan_code("DELETE FROM dws.orders WHERE id = 5")
    assert r["verdict"] == "pass"
    assert any(x["rule_id"] == "DGR-403" for x in r["findings"])


def test_nonkey_guard_is_review():
    r = scan_code("UPDATE dws.orders SET status = 9 WHERE city = 'SH'")
    assert r["verdict"] == "review"
    assert any(x["rule_id"] == "DGR-203" for x in r["findings"])


def test_tautology_variants_fatal():
    for w in ("WHERE 1=1", "WHERE true", "WHERE id IS NOT NULL",
              "WHERE id IN (SELECT id FROM dws.orders)", "WHERE remark LIKE '%'",
              "WHERE 1=1 OR id = 5"):
        r = scan_code(f"DELETE FROM dws.orders {w}")
        assert any(x["severity"] == "致命" for x in r["findings"]), w


def test_and_mixed_guard_not_tautology():
    r = scan_code("DELETE FROM dws.orders WHERE id = 5 AND status = 1")
    assert not any(x["severity"] == "致命" for x in r["findings"])


def test_comment_split_keyword_detected():
    r = scan_code("DR/**/OP TABLE dws.orders")
    assert any(x["rule_id"] == "DGR-105" for x in r["findings"])


def test_case_and_space_obfuscation():
    r = scan_code("dRoP   tAbLe dws.orders")
    assert any(x["rule_id"] == "DGR-105" for x in r["findings"])


def test_backtick_identifiers():
    r = scan_code("DELETE FROM `dws`.`orders` WHERE `id` = 5")
    assert r["verdict"] == "pass"


def test_cte_wrapped_delete():
    r = scan_code("WITH g AS (SELECT 1) DELETE FROM dws.orders")
    assert any(x["rule_id"] == "DGR-101" and x["severity"] == "致命" for x in r["findings"])


def test_transaction_dressing_still_blocks():
    r = scan_code("BEGIN; DROP TABLE dws.orders; COMMIT;")
    assert r["verdict"] == "block"
    assert not any(x["rule_id"] == "DGR-302" for x in r["findings"])  # 有事务不再提示 302


def test_sandwich_buried_truncate():
    benign = ";\n".join(f"SELECT count() FROM dws.t{i} WHERE id = {i}" for i in range(6))
    r = scan_code(benign + ";\nTRUNCATE TABLE dws.events;\n" + benign)
    assert any(x["rule_id"] == "DGR-201" for x in r["findings"])


def test_ck_mutation():
    r = scan_code("ALTER TABLE dws.events DELETE WHERE tenant_id = 3")
    assert any(x["rule_id"] == "DGR-204" and x["severity"] == "高危" for x in r["findings"])
    r2 = scan_code("ALTER TABLE dws.events DELETE WHERE 1=1")
    assert any(x["rule_id"] == "DGR-204" and x["severity"] == "致命" for x in r2["findings"])


def test_alter_drop_partition():
    r = scan_code("ALTER TABLE dws.events DROP PARTITION '2026-09'")
    assert any(x["rule_id"] == "DGR-202" for x in r["findings"])


def test_grant_all_high():
    r = scan_code("GRANT ALL ON *.* TO app_user")
    assert any(x["rule_id"] == "DGR-206" and x["severity"] == "高危" for x in r["findings"])


def test_dynamic_sql_detected():
    for payload in (
        'cursor.execute("DROP TABLE dws.orders")',
        'cursor.execute(f"DELETE FROM {table}")',
        'stmt = "TRUNCATE TABLE " + table; client.execute(stmt)',
        "EXECUTE IMMEDIATE 'DELETE FROM dws.orders'",
        "PREPARE s FROM 'UPDATE dws.orders SET status = 9'",
    ):
        r = scan_code(payload)
        assert any(x["rule_id"] == "DGR-205" and x["severity"] in ("致命", "高危") for x in r["findings"]), payload


def test_parameterized_query_not_flagged():
    r = scan_code('cursor.execute("SELECT id FROM dws.orders WHERE id = %s", (5,))')
    assert r["verdict"] == "pass"


def test_rm_rf():
    r = scan_code("rm -rf /data/warehouse")
    assert any(x["rule_id"] == "DGR-501" and x["severity"] == "致命" for x in r["findings"])
    r2 = scan_code("rm -rf ./build")
    assert any(x["rule_id"] == "DGR-501" for x in r2["findings"])


def test_client_query_flag():
    r = scan_code("clickhouse-client -q 'DROP TABLE dws.orders'")
    assert any(x["rule_id"] == "DGR-502" for x in r["findings"])


# ---------------- 误报控制（良性不得阻断） ----------------

def test_fp_literal_demo():
    r = scan_code("SELECT 'DROP TABLE dws.orders' AS demo_sql")
    assert r["verdict"] == "pass"


def test_fp_comment_mention():
    r = scan_code("-- 下个版本将 DROP TABLE dws.orders\nSELECT 1")
    assert r["verdict"] == "pass"


def test_fp_explain_prefix():
    for s in ("EXPLAIN DELETE FROM dws.orders WHERE id = 5", "EXPLAIN TRUNCATE TABLE dws.events"):
        assert scan_code(s)["verdict"] == "pass", s


def test_fp_string_with_semicolon():
    r = scan_code("SELECT 'a;b' AS s FROM dws.t WHERE id = 1")
    assert r["statements"] == 1
    assert r["verdict"] == "pass"


def test_safe_marker_downgrades_but_not_clears():
    r = scan_code("-- safe: 空表清理 工单#123\nDROP TABLE dws.orders")
    # 致命降为高危，仍阻断；标记不可单独授权
    assert r["verdict"] == "block"
    top = [x for x in r["findings"] if x["rule_id"] == "DGR-105"]
    assert top and top[0]["severity"] == "高危"


def test_verdict_aggregation_and_empty():
    assert scan_code("")["ok"] is False
    assert scan_code("SELECT 1")["verdict"] == "pass"
    r = scan_code("UPDATE dws.orders SET status = 9 WHERE city = 'SH'")
    assert r["verdict"] == "review" and not r["requires_approval"]
