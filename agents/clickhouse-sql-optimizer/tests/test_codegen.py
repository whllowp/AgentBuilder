"""建表代码生成器测试：生成物必须通过 advise_ddl 自检（无 error 级问题）。"""
from clickhouse_tools.ddl_advisor import advise_ddl
from clickhouse_tools.ddl_codegen import generate_ddl


def _selfcheck(ddl: str) -> list:
    r = advise_ddl(ddl)
    assert r["ok"], r.get("summary")
    return [i for i in r["issues"] if i["severity"] == "error"]


def test_append_log_generates_and_passes_selfcheck():
    g = generate_ddl("append_log", table="dwd.event_log", dimensions="tenant_id, event_type")
    assert g["ok"]
    assert "ENGINE = MergeTree" in g["ddl"]
    assert "ORDER BY (tenant_id, event_type, event_time)" in g["ddl"]
    assert "TTL" in g["ddl"]
    assert "bloom_filter" in g["ddl"]
    assert not _selfcheck(g["ddl"])
    assert g["notes"]


def test_cdc_upsert_generates_and_passes_selfcheck():
    g = generate_ddl("cdc_upsert", table="ods.orders_cdc", dimensions="order_id")
    assert g["ok"]
    assert "ReplacingMergeTree(updated_at)" in g["ddl"]
    assert "is_deleted" in g["ddl"]
    assert "min_age_to_force_merge_seconds" in g["ddl"]
    assert not _selfcheck(g["ddl"])


def test_collapsing_generates_and_passes_selfcheck():
    g = generate_ddl("collapsing", table="dws.metric_collapsing", dimensions="tenant_id")
    assert g["ok"]
    assert "CollapsingMergeTree(sign)" in g["ddl"]
    assert "sign Int8" in g["ddl"]
    assert not _selfcheck(g["ddl"])


def test_agg_rollup_generates_mv_and_query():
    g = generate_ddl("agg_rollup", table="dwd.event_log", dimensions="tenant_id, event_type")
    assert g["ok"]
    ddl, extras = g["ddl"], g["extras"]
    assert "AggregatingMergeTree" in ddl
    assert "AggregateFunction" in ddl
    assert any("CREATE MATERIALIZED VIEW" in e for e in extras)
    assert any("countMerge" in e for e in extras)
    assert not _selfcheck(ddl)


def test_partition_defaults_by_ttl():
    monthly = generate_ddl("append_log", ttl_days=90)
    daily = generate_ddl("append_log", ttl_days=7)
    assert "toYYYYMM(" in monthly["ddl"]
    assert "toYYYYMMDD(" in daily["ddl"]


def test_partition_explicit():
    g = generate_ddl("append_log", ttl_days=90, partition="day")
    assert "toYYYYMMDD(" in g["ddl"]


def test_invalid_table_name_falls_back_to_default():
    g = generate_ddl("append_log", table="bad name; drop table")
    assert g["ok"]
    assert "bad name" not in g["ddl"]


def test_dimensions_fallback_when_empty():
    g = generate_ddl("append_log", dimensions="!!!, ,,,")
    assert g["ok"]
    assert "tenant_id" in g["ddl"]  # 默认维度兜底


def test_unknown_scenario():
    g = generate_ddl("star_schema")
    assert not g["ok"]
    assert "未知场景" in g["error"]
