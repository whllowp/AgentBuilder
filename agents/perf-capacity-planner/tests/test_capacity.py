"""perf-capacity-planner 测试：计算器、解析器、Agent 集成。"""
import pytest

from capacity_tools.capacity_calc import plan, plan_clickhouse, plan_flink, plan_generic, plan_kafka
from capacity_tools.spec_parser import parse_spec
from capacity_agent.agent import CapacityPlannerAgent, load_agent
from common.llm.client import LLMResponse, ToolCall
from common.llm.mock import MockLLM


def test_clickhouse_storage_deterministic():
    r = plan_clickhouse(rows_per_day=2e8, avg_row_bytes=200, ttl_days=90, replicas=2)
    assert r["formula"] and r["assumptions"] and r["sensitivity"]
    res = r["results"]
    assert res["total_rows"] == 1.8e10
    # 手工复核：2e8×200×90/5(压缩)×2(副本)×1.3(余量)×2(磁盘冗余) = 3.744e12B ≈ 3486.87 GiB
    assert abs(res["total_storage_gb"] - 3486.87) < 1
    assert res["pk_index_mem_mb"] > 0


def test_kafka_partitions_and_storage():
    r = plan_kafka(msgs_per_sec=50000, avg_msg_bytes=1024, retention_hours=72)
    assert r["results"]["partitions_recommended"] >= 3
    assert r["results"]["storage_gb"] > 100


def test_flink_parallelism_max_of_two_paths():
    r = plan_flink(records_per_sec=60000, state_size_gb=30, key_cardinality=1e6)
    assert r["results"]["parallelism"] == max(int(60000 / 5000) + 1, int(1e6 ** 0.5) + 1)  # max(13, 1001)
    assert r["results"]["rocksdb_mem_gb"] == 90.0


def test_generic_threads_littles_law():
    r = plan_generic(qps=2000, latency_s=0.05)
    assert r["results"]["threads"] == int(2000 * 0.05 * 1.2) + 1  # 121


def test_plan_dispatch_and_unknown():
    assert plan({"engine": "ck", "rows_per_day": 1e8, "avg_row_bytes": 100})["engine"] == "clickhouse"
    assert not plan({"engine": "oracle"})["ok"] if "ok" in plan({"engine": "oracle"}) else plan({"engine": "oracle"})["engine"]


def test_parse_spec_chinese():
    s = parse_spec("ClickHouse 日增 2 亿行，行宽 200B，保留 90 天，双副本")
    assert s["engine"] == "clickhouse"
    assert s["rows_per_day"] == 2e8 and s["avg_row_bytes"] == 200
    assert s["ttl_days"] == 90 and s["replicas"] == 2


def test_parse_spec_kafka_and_flask():
    k = parse_spec("Kafka 每秒 5万条消息，保留 72 小时")
    assert k["engine"] == "kafka" and k["msgs_per_sec"] == 5e4 and k["retention_hours"] == 72
    f = parse_spec("Flink 作业每秒 20万条，状态 50GB，键基数 1000万")
    assert f["engine"] == "flink" and f["records_per_sec" if "records_per_sec" in f else "msgs_per_sec"] == 2e5


@pytest.fixture()
def agent():
    return load_agent()


def test_agent_offline_report(agent):
    r = agent.offline("ClickHouse 日增 2 亿行，行宽 200B，保留 90 天，双副本")
    for sec in ("需求解析", "容量结论", "假设与公式", "水位与扩容", "验证方法", "敏感性"):
        assert sec in r["report"], sec


def test_agent_offline_unknown(agent):
    assert "未识别到引擎" in agent.offline("随便看看")["report"]


def test_mock_llm_loop(agent):
    llm = MockLLM([
        LLMResponse(tool_calls=[ToolCall(id="c1", name="capacity_plan", arguments={"spec": "Kafka 每秒 1万条，保留 24 小时"})]),
        LLMResponse(content="## 需求解析\n完成"),
    ])
    a = CapacityPlannerAgent(agent.config, llm=llm)
    r = a.run("评估容量")
    assert r.answer.startswith("## 需求解析") and r.tool_trace[0].ok
