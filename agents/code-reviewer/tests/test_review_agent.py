"""code-reviewer Agent 集成测试：离线管线 + Mock LLM 工具回路。"""
import pytest

from code_review_agent.agent import CodeReviewerAgent, load_agent
from code_review_agent.config import AgentConfig
from common.llm.client import LLMResponse, ToolCall
from common.llm.mock import MockLLM

DIFF = """\
diff --git a/src/PayService.java b/src/PayService.java
--- a/src/PayService.java
+++ b/src/PayService.java
@@ -5,2 +5,5 @@ class PayService {
     void pay() {}
+    void audit() {
+        ExecutorService pool = Executors.newFixedThreadPool(4);
+    }
diff --git a/src/PayServiceTest.java b/src/PayServiceTest.java
new file mode 100644
--- /dev/null
+++ b/src/PayServiceTest.java
@@ -0,0 +1,1 @@
+class PayServiceTest {}
diff --git a/yarn.lock b/yarn.lock
--- a/yarn.lock
+++ b/yarn.lock
@@ -1,1 +1,1 @@
+# lock
"""


@pytest.fixture()
def agent() -> CodeReviewerAgent:
    return load_agent()


def test_config_and_tools(agent):
    assert agent.config.name == "code-reviewer"
    for t in ("inspect_diff", "static_scan", "match_rules", "knowledge_search"):
        assert t in agent.tools.names()


def test_offline_pipeline(agent):
    result = agent.offline(DIFF)
    assert result["stats"]["reviewed"] == 2 and result["stats"]["filtered"] == 1
    assert any(b for b in result["bundles"] if len(b["files"]) == 2)  # 实现-测试配对
    assert result["rules"]["src/PayService.java"]  # Java 规则命中
    assert any(c["severity"] == "medium" and "Executors" in c["content"] for c in result["comments"])
    assert result["dropped_low"] == []  # 无 low


def test_offline_report_structure(agent):
    r = agent.offline(DIFF)["report"]
    assert "## 概览" in r and "## 评审意见" in r and "管线参考" in r
    assert "可合入" in r or "修复后可合入" in r  # 有结论


def test_offline_critical_blocks(agent):
    bad = (
        "diff --git a/config.py b/config.py\n--- a/config.py\n+++ b/config.py\n"
        "@@ -1,0 +1,1 @@\n+PASSWORD = \"super-secret-123\"\n"
    )
    result = agent.offline(bad)
    assert any(c["severity"] == "critical" for c in result["comments"])
    assert "阻断" in result["report"]


def test_offline_keep_low(agent):
    low = (
        "diff --git a/app/main.js b/app/main.js\n--- a/app/main.js\n+++ b/app/main.js\n"
        "@@ -1,0 +1,1 @@\n+console.log('debug');\n"
    )
    default = agent.offline(low)
    assert default["comments"] == [] and len(default["dropped_low"]) == 1
    agent.config.keep_low = True
    kept = agent.offline(low)
    assert len(kept["comments"]) == 1 and "已忽略" not in kept["report"]
    agent.config.keep_low = False


def test_empty_diff(agent):
    result = agent.offline("")
    assert result["ok"] is False
    assert "未解析到任何变更" in result["report"]


def test_mock_llm_tool_loop(agent):
    llm = MockLLM(
        [
            LLMResponse(tool_calls=[ToolCall(id="c1", name="inspect_diff", arguments={"diff_text": DIFF})]),
            LLMResponse(content="## 概览\n评审完成"),
        ]
    )
    a = CodeReviewerAgent(agent.config, llm=llm)
    result = a.run("评审这个 diff")
    assert result.answer.startswith("## 概览")
    assert result.tool_trace[0].name == "inspect_diff" and result.tool_trace[0].ok


def test_config_defaults(tmp_path):
    cfg = AgentConfig.load(tmp_path)
    assert cfg.name == "code-reviewer" and cfg.keep_low is False and cfg.comment_language == "zh"
