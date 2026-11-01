"""EXPLAIN 解析器测试。"""
from clickhouse_tools.explain_parser import parse_explain

GOOD_PLAN = """
Expression ((count() + 0))
  Aggregating
    Expression (count())
      ReadFromMergeTree (default.events)
      Indexes:
        PrimaryKey
          Key Condition: (tenant_id in [3, 3])
          PrimaryKeyAllParts: 2/20
          PrimaryKeyAllGranules: 31/1570
        Skip
          Name: idx_user
          Description: bloom_filter
          Parts: 2/2
          Granules: 5/31
"""

BAD_PLAN = """
Expression ((count()))
  Aggregating
    ReadFromMergeTree (default.events)
      Default Grantule: true
"""


def test_good_plan_metrics():
    r = parse_explain(GOOD_PLAN)
    assert r["ok"]
    m = r["metrics"]
    assert m["parts_read"] == 2 and m["parts_total"] == 20
    assert m["granules_read"] == 31 and m["granules_total"] == 1570
    assert "tenant_id" in m["key_condition"]
    assert m["parts_read_ratio"] == 0.1


def test_good_plan_advice_positive():
    r = parse_explain(GOOD_PLAN)
    titles = " ".join(a["title"] for a in r["advice"])
    assert "裁剪良好" in titles


def test_bad_plan_flags_no_key_condition():
    r = parse_explain("Expression ((x))\n  Filter (WHERE uid = 5)\n    ReadFromMergeTree (t)\n      Granules: 1570/1570")
    assert any("无 Key Condition" in a["title"] or "裁剪不佳" in a["title"] for a in r["advice"])


def test_full_scan_granules_flagged():
    text = "PrimaryKeyAllGranules: 1000/1000\nPrimaryKeyAllParts: 10/10"
    r = parse_explain(text)
    assert any("granule" in a["title"].lower() and "不佳" in a["title"] for a in r["advice"])
    assert any("分区" in a["title"] for a in r["advice"])


def test_unknown_key_condition_flagged():
    text = "Key Condition: (unknown)\nPrimaryKeyAllGranules: 5/100"
    r = parse_explain(text)
    assert any("unknown" in a["title"] for a in r["advice"])


def test_read_columns_extracted():
    text = "Expression ((tenant_id, count(), sum(amount)))\n  ReadFromMergeTree (t)\n    PrimaryKeyAllGranules: 1/100"
    r = parse_explain(text)
    cols = r["metrics"].get("read_columns", [])
    assert len(cols) == 3


def test_empty_input():
    r = parse_explain("")
    assert not r["ok"]
    assert r["summary"] == "无内容"


def test_generic_fallback_advice():
    r = parse_explain("Expression ((x))")
    assert r["ok"]
    assert r["advice"]  # 至少给出 EXPLAIN ANALYZE 建议
