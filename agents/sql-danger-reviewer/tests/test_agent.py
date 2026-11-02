"""Reviewer Agent 集成测试：离线管线 + Mock LLM 工具回路。"""
import pytest

from sql_danger_agent.agent import SqlDangerReviewerAgent, load_agent
from sql_danger_agent.config import AgentConfig
from common.llm.client import LLMResponse, ToolCall
from common.llm.mock import MockLLM


@pytest.fixture()
def agent() -> SqlDangerReviewerAgent:
    return load_agent()


def test_config_and_tools(agent):
    assert agent.config.name == "sql-danger-reviewer"
    for t in ("danger_scan", "knowledge_search", "approval_checklist"):
        assert t in agent.tools.names()


def test_offline_blocks_dangerous(agent):
    result = agent.offline("UPDATE dws.orders SET status = 9 WHERE 1=1")
    assert result["scan"]["verdict"] == "block"
    assert "扫描结论" in result["report"] and "放行路径" in result["report"]


def test_offline_passes_benign(agent):
    result = agent.offline("DELETE FROM dws.orders WHERE id = 5")
    assert result["scan"]["verdict"] == "pass"
    assert "未发现高危操作" in result["report"]


def test_offline_report_sections(agent):
    result = agent.offline("DROP TABLE dws.orders;\nTRUNCATE TABLE dws.events;")
    r = result["report"]
    assert "## 扫描结论" in r and "## 发现明细" in r and "## 改写建议" in r
    assert "四件套" in r  # requires_approval 时给放行路径


def test_offline_knowledge_hits(agent):
    result = agent.offline("DELETE FROM dws.orders")
    assert result["knowledge"]  # 规则佐证命中


def test_mock_llm_tool_loop(agent):
    llm = MockLLM(
        [
            LLMResponse(tool_calls=[ToolCall(id="c1", name="danger_scan", arguments={"code": "DROP TABLE dws.orders"})]),
            LLMResponse(content="## 扫描结论\n⛔ block"),
        ]
    )
    a = SqlDangerReviewerAgent(agent.config, llm=llm)
    result = a.run("评审这段代码")
    assert result.answer.startswith("## 扫描结论")
    assert result.iterations == 2
    assert result.tool_trace[0].name == "danger_scan" and result.tool_trace[0].ok


def test_config_defaults(tmp_path):
    cfg = AgentConfig.load(tmp_path)
    assert cfg.name == "sql-danger-reviewer"
    assert cfg.temperature if hasattr(cfg, "temperature") else True
