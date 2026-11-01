"""慢 SQL 六步 SOP 与诊断 SQL 生成器测试。"""
from clickhouse_tools.diagnostics import build_diagnostics


def test_sop_six_steps():
    d = build_diagnostics()
    names = [s["name"] for s in d["sop"]]
    assert names == ["发现", "取证", "归因", "改写", "验证", "固化"]
    assert all(s["action"] for s in d["sop"])


def test_queries_tagged_with_stage():
    d = build_diagnostics()
    for q in d["queries"]:
        assert q.get("stage") in range(1, 7)
        assert q["stage_name"]  # 每条 SQL 都能映射到 SOP 步骤
        assert "sql" in q and "purpose" in q


def test_queries_cover_key_stages():
    d = build_diagnostics()
    stages = {q["stage"] for q in d["queries"]}
    assert 1 in stages and 2 in stages and 3 in stages and 5 in stages and 6 in stages


def test_table_specific_query_injected():
    d = build_diagnostics("dws.events")
    assert any(q["name"] == "table_stats" and "dws.events" in q["sql"] for q in d["queries"])


def test_table_name_sanitized():
    d = build_diagnostics("t'; DROP TABLE x")
    stats = next(q for q in d["queries"] if q["name"] == "table_stats")
    # 单引号被剥离，无法注入/破坏 SQL 字符串字面量
    assert "t'; DROP" not in stats["sql"]
    assert "''" not in stats["sql"]
    assert "DROP TABLE x" in stats["sql"]  # 仅作为无害的表名字面量片段


def test_query_names_unique():
    d = build_diagnostics("t")
    names = [q["name"] for q in d["queries"]]
    assert len(names) == len(set(names))
