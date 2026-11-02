"""Adversary Agent 集成测试：离线管线 + Mock LLM 工具回路。"""
import pytest

from sql_adversary_agent.agent import SqlDangerAdversaryAgent, load_agent
from sql_adversary_agent.config import AgentConfig
from common.llm.client import LLMResponse, ToolCall
from common.llm.mock import MockLLM


@pytest.fixture()
def agent() -> SqlDangerAdversaryAgent:
    return load_agent()


def test_config_and_tools(agent):
    assert agent.config.name == "sql-danger-adversary"
    assert agent.config.target_agent == "sql-danger-reviewer"
    for t in ("generate_attacks", "evaluate_attacks", "run_iteration"):
        assert t in agent.tools.names()


def test_offline_full_green(agent):
    result = agent.offline("")
    assert result["max_tier"] == 10
    assert result["stats"]["recall"] == 1.0 and result["stats"]["fp_rate"] == 0.0
    r = result["report"]
    assert "## 对抗结论" in r and "技术级覆盖" in r and "未被打穿" in r and "复现命令" in r


def test_offline_tier_limit_from_request(agent):
    result = agent.offline("测到第 5 级")
    assert result["max_tier"] == 5


def test_offline_report_has_tier_table(agent):
    result = agent.offline("3")
    assert "| T1 |" in result["report"] and "| T3 |" in result["report"] and "T4" not in result["report"].split("## 技术级覆盖")[1].split("##")[0]


def test_mock_llm_tool_loop(agent):
    llm = MockLLM(
        [
            LLMResponse(tool_calls=[ToolCall(id="c1", name="run_iteration", arguments={"rounds": 1})]),
            LLMResponse(content="## 对抗结论\n全绿"),
        ]
    )
    a = SqlDangerAdversaryAgent(agent.config, llm=llm)
    result = a.run("跑一轮")
    assert result.answer.startswith("## 对抗结论")
    assert result.tool_trace[0].name == "run_iteration" and result.tool_trace[0].ok


def test_config_defaults(tmp_path):
    cfg = AgentConfig.load(tmp_path)
    assert cfg.rounds == 10 and cfg.target_agent == "sql-danger-reviewer"
