"""code-review-adversary 测试：语料、评估器（含回归检测）、Agent 离线管线。"""
import pytest

from cr_adversary_tools.commit_attack import build_corpus, evaluate
from cr_adversary_agent.agent import CrAdversaryAgent, load_agent
from review_tools.static_scan import scan_diff
from common.llm.client import LLMResponse, ToolCall
from common.llm.mock import MockLLM


def test_corpus_shape():
    corpus = build_corpus(10)
    kinds = {a["kind"] for a in corpus}
    assert kinds == {"deterministic", "llm-benchmark"}
    det = [a for a in corpus if a["kind"] == "deterministic"]
    assert all(a["expect"] in ("danger", "benign") for a in det)
    tiers = {a["tier"] for a in corpus}
    assert tiers == set(range(1, 11))


def test_full_corpus_green():
    stats = evaluate(build_corpus(10), scan_diff)
    assert stats["recall"] == 1.0 and stats["fp_rate"] == 0.0
    assert stats["benchmark_n"] == 9 and stats["misses"] == []


def test_evaluate_detects_regression():
    def dead(_):
        return []

    stats = evaluate([a for a in build_corpus(2)], dead)
    assert stats["recall"] == 0.0 and stats["misses"]


@pytest.fixture()
def agent():
    return load_agent()


def test_agent_offline_green(agent):
    result = agent.offline("")
    assert result["stats"]["recall"] == 1.0 and result["stats"]["fp_rate"] == 0.0
    assert "未被打穿" in result["report"] and "语义基准" in result["report"]


def test_agent_offline_tier_limit(agent):
    assert agent.offline("测到 4 级")["max_tier"] == 4


def test_mock_llm_loop(agent):
    llm = MockLLM([
        LLMResponse(tool_calls=[ToolCall(id="c1", name="generate_attacks", arguments={"max_tier": 1})]),
        LLMResponse(content="## 对抗结论\n全绿"),
    ])
    a = CrAdversaryAgent(agent.config, llm=llm)
    r = a.run("生成攻击")
    assert r.answer.startswith("## 对抗结论") and r.tool_trace[0].name == "generate_attacks"
