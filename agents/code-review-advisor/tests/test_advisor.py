"""code-review-advisor 测试：润色、语气检查、Agent 集成。"""
import json

import pytest

from advisor_tools.comment_polish import polish_findings, tone_check
from review_advisor_agent.agent import ReviewAdvisorAgent, load_agent
from common.llm.client import LLMResponse, ToolCall
from common.llm.mock import MockLLM


FINDINGS = [
    {"title": "疑似硬编码凭据", "severity": "critical", "category": "security",
     "existing_code": 'DB_PASSWORD = "x"', "suggestion_code": "走密钥管理", "thinking": "secret"},
    {"title": "使用 var 声明", "severity": "low", "category": "style",
     "existing_code": "var x = 1", "suggestion_code": "const x = 1", "thinking": "var"},
]


def test_polish_orders_and_labels():
    r = polish_findings(FINDINGS)
    assert r["ok"] and r["count"] == 2
    assert r["polished"][0]["severity"] == "critical"
    assert "[阻断]" in r["polished"][0]["text"] and "（依据：secret）" in r["polished"][0]["text"]
    assert "[nit]" in r["polished"][1]["text"]
    assert "总体看这个变更方向没问题" in r["review_text"] and "欢迎讨论" in r["review_text"]


def test_polish_accepts_json_string():
    r = polish_findings(json.dumps(FINDINGS, ensure_ascii=False))
    assert r["ok"]


def test_polish_rejects_bad_input():
    assert not polish_findings("not json")["ok"]
    assert not polish_findings([])["ok"]


def test_polish_reply_templates():
    r = polish_findings(FINDINGS)
    assert len(r["reply_templates"]) == 3 and any("follow-up" in t for t in r["reply_templates"])


def test_tone_check_flags():
    r = tone_check("这段代码太差了，你怎么又错了？必须马上改！我说了多少次了。")
    assert not r["ok"]
    types = {i["type"] for i in r["issues"]}
    assert {"攻击性评价", "人身指向"} <= types
    assert all(i["fix"] for i in r["issues"])


def test_tone_check_clean():
    assert tone_check("这处实现在大流量下可能成为瓶颈，建议改为批量写入（依据：规范 X）。")["ok"]


@pytest.fixture()
def agent():
    return load_agent()


def test_agent_offline_polish(agent):
    result = agent.offline(json.dumps(FINDINGS, ensure_ascii=False))
    assert "评审意见（可发出）" in result["report"] and result["tone"]["ok"]


def test_agent_offline_tone_only(agent):
    result = agent.offline("这写得太垃圾了")
    assert not result["tone"]["ok"] and "语气检查" in result["report"]


def test_mock_llm_loop(agent):
    llm = MockLLM([
        LLMResponse(tool_calls=[ToolCall(id="c1", name="tone_check", arguments={"draft": "必须改"})]),
        LLMResponse(content="## 评审意见\n已润色"),
    ])
    a = ReviewAdvisorAgent(agent.config, llm=llm)
    r = a.run("检查我的草稿")
    assert r.answer.startswith("## 评审意见") and r.tool_trace[0].name == "tone_check"
