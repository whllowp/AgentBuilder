"""任务解析器测试。"""
from clickhouse_agent.analyzer import analyze_request, detect_ddl_design


def test_detects_ddl():
    text = "帮我看看这张表设计：\n```sql\nCREATE TABLE events (ts DateTime) ENGINE = MergeTree ORDER BY ts\n```"
    p = analyze_request(text)
    assert p["kind"] == "ddl"
    assert len(p["ddl_texts"]) == 1
    assert p["has_ddl"]


def test_detects_sql_review():
    p = analyze_request("这个查询很慢：```sql\nSELECT * FROM orders WHERE toDate(ts) = '2026-09-01'\n```")
    assert p["kind"] == "sql_review"
    assert len(p["sqls"]) == 1
    assert p["tables"] == ["orders"]


def test_detects_explain_text():
    text = "EXPLAIN 结果：\n```\nExpression ((count()))\n  ReadFromMergeTree (t)\n  PrimaryKey\n    Key Condition: (id in [1, 1])\n    PrimaryKeyAllGranules: 2/100\n```"
    p = analyze_request(text)
    assert p["kind"] == "explain"
    assert p["has_explain"]


def test_bare_explain_without_fence():
    text = "Granules: 90/100\nParts: 10/10\nKey Condition: (unknown)"
    p = analyze_request(text)
    assert p["kind"] == "explain"


def test_mixed_input():
    text = (
        "表结构和查询如下：\n```sql\nCREATE TABLE t (a UInt32) ENGINE = MergeTree ORDER BY a\n```\n"
        "```sql\nSELECT * FROM t\n```"
    )
    p = analyze_request(text)
    assert p["kind"] == "mixed"
    assert p["has_ddl"] and p["has_query"]


def test_unknown_input():
    p = analyze_request("ClickHouse 怎么优化？")
    assert p["kind"] == "unknown"
    assert not p["sqls"] and not p["ddl_texts"] and not p["explain_texts"]


# ---------------- 建表需求识别 ----------------

def test_design_intent_log():
    d = detect_ddl_design("帮我建一张明细日志表，按租户和事件类型查")
    assert d["intent"]
    assert d["scenario"] == "append_log"


def test_design_intent_cdc():
    d = detect_ddl_design("建一张表做 cdc 入湖，按 order_id 去重保留最新")
    assert d["intent"]
    assert d["scenario"] == "cdc_upsert"


def test_design_intent_collapsing():
    d = detect_ddl_design("我要建个表支持回撤语义的指标")
    assert d["scenario"] == "collapsing"


def test_design_intent_rollup():
    d = detect_ddl_design("帮我建一张看板用的预聚合汇总表")
    assert d["scenario"] == "agg_rollup"


def test_design_intent_with_table_name():
    d = detect_ddl_design("帮我建一张表，表名为 dws.orders_log")
    assert d["intent"]
    assert d["table"] == "dws.orders_log"


def test_design_intent_not_triggered_for_existing_ddl():
    d = detect_ddl_design("CREATE TABLE t (a UInt32) ENGINE = MergeTree ORDER BY a")
    assert not d["intent"]


def test_design_intent_not_triggered_for_query():
    d = detect_ddl_design("SELECT * FROM t")
    assert not d["intent"]


def test_analyze_request_ddl_design_kind():
    p = analyze_request("帮我建一张明细表")
    assert p["kind"] == "ddl_design"
    assert p["has_design"]
