"""DDL 评估器测试。"""
from clickhouse_tools.ddl_advisor import advise_ddl, parse_ddl


GOOD_DDL = """
CREATE TABLE dws.events
(
    tenant_id UInt32 COMMENT '租户',
    event_type LowCardinality(String) COMMENT '事件类型',
    event_date DateTime COMMENT '时间',
    user_id UInt64,
    amount Decimal(18, 2),
    INDEX idx_user user_id TYPE bloom_filter(0.01) GRANULARITY 1
)
ENGINE = ReplacingMergeTree(updated_at)
PARTITION BY toYYYYMM(event_date)
ORDER BY (tenant_id, event_type, event_date)
TTL event_date + INTERVAL 90 DAY
SETTINGS index_granularity = 8192
"""


def test_parse_basic_fields():
    p = parse_ddl(GOOD_DDL)
    assert p["ok"]
    assert p["engine"] == "ReplacingMergeTree"
    assert p["engine_args"] == "updated_at"
    assert p["order_by"] == ["tenant_id", "event_type", "event_date"]
    assert p["partition_by"].startswith("toYYYYMM")
    assert len(p["columns"]) == 5
    assert p["skip_indexes"][0]["type"] == "bloom_filter"
    assert p["ttl"]


def test_good_ddl_no_critical_issue():
    r = advise_ddl(GOOD_DDL)
    assert r["ok"]
    assert not any(i["severity"] == "error" for i in r["issues"])


def test_missing_order_by():
    ddl = "CREATE TABLE t (a UInt32, ts DateTime) ENGINE = MergeTree PARTITION BY tuple()"
    r = advise_ddl(ddl)
    assert any(i["rule_id"] == "no_order_by" and i["severity"] == "error" for i in r["issues"])


def test_order_by_time_first_flagged():
    ddl = (
        "CREATE TABLE t (tenant_id UInt32, ts DateTime, uid UUID) "
        "ENGINE = MergeTree ORDER BY (ts, tenant_id)"
    )
    r = advise_ddl(ddl)
    assert any(i["rule_id"] == "order_by_time_first" for i in r["issues"])


def test_order_by_uuid_first_flagged():
    ddl = (
        "CREATE TABLE t (trace_id String, tenant_id UInt32) "
        "ENGINE = MergeTree ORDER BY (trace_id, tenant_id)"
    )
    r = advise_ddl(ddl)
    assert any(i["rule_id"] == "order_by_high_card_first" for i in r["issues"])


def test_pk_not_prefix_flagged():
    ddl = (
        "CREATE TABLE t (a UInt32, b UInt32, c UInt32) "
        "ENGINE = MergeTree ORDER BY (a, b, c) PRIMARY KEY (b)"
    )
    r = advise_ddl(ddl)
    assert any(i["rule_id"] == "pk_not_prefix" and i["severity"] == "error" for i in r["issues"])


def test_daily_partition_without_ttl_flagged():
    ddl = (
        "CREATE TABLE t (a UInt32, ts DateTime) "
        "ENGINE = MergeTree ORDER BY (a, ts) PARTITION BY toYYYYMMDD(ts)"
    )
    r = advise_ddl(ddl)
    assert any(i["rule_id"] == "over_partition" for i in r["issues"])


def test_month_partition_with_ttl_ok():
    ddl = (
        "CREATE TABLE t (a UInt32, ts DateTime) "
        "ENGINE = MergeTree ORDER BY (a, ts) PARTITION BY toYYYYMM(ts) "
        "TTL ts + INTERVAL 90 DAY"
    )
    r = advise_ddl(ddl)
    assert not any(i["rule_id"] == "over_partition" for i in r["issues"])


def test_float_money_flagged():
    ddl = (
        "CREATE TABLE t (tenant_id UInt32, pay_amount Float64, ts DateTime) "
        "ENGINE = MergeTree ORDER BY (tenant_id, ts)"
    )
    r = advise_ddl(ddl)
    assert any(i["rule_id"] == "float_money" and i["severity"] == "error" for i in r["issues"])


def test_nullable_abuse_flagged():
    cols = ", ".join(f"col{i} Nullable(String)" for i in range(6))
    ddl = f"CREATE TABLE t ({cols}, ts DateTime) ENGINE = MergeTree ORDER BY (col0, ts)"
    r = advise_ddl(ddl)
    assert any(i["rule_id"] == "nullable_abuse" for i in r["issues"])


def test_replacing_without_version_flagged():
    ddl = "CREATE TABLE t (order_id UInt64, val String) ENGINE = ReplacingMergeTree() ORDER BY order_id"
    r = advise_ddl(ddl)
    assert any(i["rule_id"] == "rmt_no_version" for i in r["issues"])


def test_collapsing_without_sign_flagged():
    ddl = "CREATE TABLE t (k UInt32, v Int64) ENGINE = CollapsingMergeTree(sign) ORDER BY k"
    r = advise_ddl(ddl)
    # sign 列在列定义中不存在
    assert any(i["rule_id"] == "collapsing_no_sign" for i in r["issues"])


def test_collapsing_with_sign_ok():
    ddl = (
        "CREATE TABLE t (k UInt32, v Int64, sign Int8) "
        "ENGINE = CollapsingMergeTree(sign) ORDER BY k"
    )
    r = advise_ddl(ddl)
    assert not any(i["rule_id"] == "collapsing_no_sign" for i in r["issues"])


def test_no_ttl_hint():
    ddl = "CREATE TABLE t (tenant_id UInt32, ts DateTime) ENGINE = MergeTree ORDER BY (tenant_id, ts)"
    r = advise_ddl(ddl)
    assert any(i["rule_id"] == "no_ttl" and i["severity"] == "info" for i in r["issues"])


def test_parse_failure():
    r = advise_ddl("这不是建表语句")
    assert not r["ok"]
    assert "解析失败" in r["summary"]
