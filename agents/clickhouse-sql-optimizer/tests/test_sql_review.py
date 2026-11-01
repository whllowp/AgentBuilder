"""SQL 审查规则引擎测试。"""
from clickhouse_tools.sql_review import review_sql


def test_clean_sql_passes():
    r = review_sql("SELECT tenant_id, count() FROM events WHERE tenant_id = 1 AND ts >= now() - INTERVAL 1 DAY GROUP BY tenant_id LIMIT 20")
    assert r["ok"]
    assert r["issues"] == []
    assert "未发现问题" in r["summary"]


def test_select_star():
    r = review_sql("SELECT * FROM events WHERE ts > 1")
    assert any(i["rule_id"] == "select_star" and i["severity"] == "error" for i in r["issues"])


def test_distinct_star():
    r = review_sql("SELECT DISTINCT * FROM t")
    assert any(i["rule_id"] == "select_star" for i in r["issues"])


def test_no_where():
    r = review_sql("SELECT tenant_id FROM events")
    assert any(i["rule_id"] == "no_where" for i in r["issues"])


def test_key_function_wrapper():
    r = review_sql("SELECT id FROM t WHERE toDate(ts) = '2026-09-01' AND tenant_id = 3")
    assert any(i["rule_id"] == "key_function" for i in r["issues"])
    assert "半开区间" in next(i for i in r["issues"] if i["rule_id"] == "key_function")["suggestion"]


def test_key_function_not_triggered_in_select():
    # 函数不在 WHERE 中不算
    r = review_sql("SELECT toDate(ts) AS d, tenant_id FROM t WHERE tenant_id = 1")
    assert not any(i["rule_id"] == "key_function" for i in r["issues"])


def test_big_offset_comma():
    r = review_sql("SELECT id FROM t WHERE x = 1 ORDER BY id LIMIT 100000, 20")
    assert any(i["rule_id"] == "big_offset" and "keyset" in i["suggestion"] for i in r["issues"])


def test_big_offset_keyword():
    r = review_sql("SELECT id FROM t WHERE x = 1 ORDER BY id LIMIT 20 OFFSET 5000")
    assert any(i["rule_id"] == "big_offset" for i in r["issues"])


def test_small_offset_ok():
    r = review_sql("SELECT id FROM t WHERE x = 1 ORDER BY id LIMIT 20 OFFSET 40")
    assert not any(i["rule_id"] == "big_offset" for i in r["issues"])


def test_final_modifier():
    r = review_sql("SELECT id, name FROM orders FINAL WHERE id = 1")
    assert any(i["rule_id"] == "final_read_cost" for i in r["issues"])


def test_leading_wildcard_like():
    r = review_sql("SELECT id FROM logs WHERE message LIKE '%timeout%'")
    assert any(i["rule_id"] == "leading_wildcard_like" for i in r["issues"])


def test_prefix_like_ok():
    r = review_sql("SELECT id FROM logs WHERE host LIKE 'web-%'")
    assert not any(i["rule_id"] == "leading_wildcard_like" for i in r["issues"])


def test_exact_distinct():
    r = review_sql("SELECT count(DISTINCT user_id) FROM visits WHERE dt = 1")
    assert any(i["rule_id"] == "exact_distinct" for i in r["issues"])


def test_too_many_joins():
    sql = (
        "SELECT a.id FROM a JOIN b ON a.x = b.x JOIN c ON a.y = c.y "
        "JOIN d ON a.z = d.z JOIN e ON a.w = e.w WHERE a.id > 0"
    )
    r = review_sql(sql)
    assert any(i["rule_id"] == "too_many_joins" for i in r["issues"])


def test_two_joins_fine():
    r = review_sql("SELECT a.id FROM a JOIN b ON a.x = b.x JOIN c ON a.y = c.y WHERE a.id > 0")
    assert not any(i["rule_id"] == "too_many_joins" for i in r["issues"])


def test_in_subquery():
    r = review_sql("SELECT id FROM t WHERE uid IN (SELECT uid FROM dim WHERE active = 1)")
    assert any(i["rule_id"] == "in_subquery" for i in r["issues"])


def test_mutation():
    r = review_sql("ALTER TABLE events DELETE WHERE tenant_id = 7")
    assert any(i["rule_id"] == "mutation_api" for i in r["issues"])


def test_lightweight_delete_not_flagged_as_mutation():
    r = review_sql("DELETE FROM events WHERE tenant_id = 7")
    assert not any(i["rule_id"] == "mutation_api" for i in r["issues"])


def test_single_row_insert():
    r = review_sql("INSERT INTO t (a, b) VALUES (1, 'x')")
    assert any(i["rule_id"] == "single_row_insert" and i["severity"] == "error" for i in r["issues"])


def test_multi_row_insert_ok():
    r = review_sql("INSERT INTO t (a, b) VALUES (1, 'x'), (2, 'y'), (3, 'z')")
    assert not any(i["rule_id"] == "single_row_insert" for i in r["issues"])


def test_semicolon_in_string():
    r = review_sql("SELECT a FROM t WHERE msg = 'a;b' -- 注释\n")
    assert r["statements"] == 1
    assert not any(i["rule_id"] == "no_where" for i in r["issues"])


def test_issues_sorted_by_severity():
    r = review_sql("SELECT * FROM t")
    severities = [i["severity"] for i in r["issues"]]
    assert severities == sorted(severities, key=lambda s: {"error": 0, "warning": 1, "info": 2}[s])


def test_empty_input():
    r = review_sql("你好")
    assert not r["ok"]
    assert r["issues"] == []
