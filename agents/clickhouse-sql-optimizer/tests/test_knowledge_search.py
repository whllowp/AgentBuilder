"""知识库检索测试（common/tools/knowledge_search）。"""
from pathlib import Path

from common.tools.knowledge_search import search

KNOWLEDGE_DIR = Path(__file__).resolve().parent.parent / "knowledge"


def test_search_order_by():
    hits = search(KNOWLEDGE_DIR, "order by 排序键 低基数", 2)
    assert hits
    assert any("ORDER BY" in h["title"] or "MergeTree" in h["title"] for h in hits)


def test_search_join_dictionary():
    hits = search(KNOWLEDGE_DIR, "join 字典 dictGet", 2)
    assert hits
    assert any("JOIN" in h["title"] or "字典" in h["title"] for h in hits)


def test_search_final_dedup():
    hits = search(KNOWLEDGE_DIR, "final argMax 去重", 2)
    assert hits
    assert any("MergeTree" in h["title"] or "物化" in h["title"] for h in hits)


def test_search_skip_index():
    hits = search(KNOWLEDGE_DIR, "跳数索引 bloom_filter minmax", 2)
    assert hits
    assert any("跳数索引" in h["title"] or "分区" in h["title"] for h in hits)


def test_search_slow_query_sop():
    hits = search(KNOWLEDGE_DIR, "慢SQL 定位 流程 SOP query_log", 2)
    assert hits
    assert any("SOP" in h["title"] or "慢 SQL" in h["title"] for h in hits)


def test_excerpts_present():
    hits = search(KNOWLEDGE_DIR, "partition 过度分区", 1)
    assert hits[0]["excerpt"]
    assert hits[0]["score"] > 0


def test_top_k_bounded():
    hits = search(KNOWLEDGE_DIR, "clickhouse 优化", 99)
    assert len(hits) <= 5


def test_no_match_returns_empty():
    assert search(KNOWLEDGE_DIR, "zzz不存在词qqq", 1) == []
