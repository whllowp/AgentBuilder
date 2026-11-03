"""ReviewAdvisorAgent：LLM 工具调用模式 + 无 LLM 的离线管线。"""
from __future__ import annotations

from . import _bootstrap  # noqa: F401 —— 必须最先导入以建立 sys.path

from pathlib import Path

from common.agentcore import BaseAgent, ToolRegistry
from common.llm.client import LLMClient

from advisor_tools import build_registry, polish_findings, tone_check

from .config import AgentConfig


class ReviewAdvisorAgent:
    def __init__(self, config: AgentConfig, llm: LLMClient | None = None):
        self.config = config
        self.llm = llm or self._default_llm()
        self.tools: ToolRegistry = build_registry(config.agent_dir, config.tools)
        self.system_prompt = (config.prompts_dir / "system.md").read_text(encoding="utf-8")
        self._core = BaseAgent(
            llm=self.llm, system_prompt=self.system_prompt, tools=self.tools,
            max_iterations=config.max_iterations,
        )

    def _default_llm(self) -> LLMClient:
        s = self.config.llm
        return LLMClient(
            base_url=s.base_url, model=s.model, api_key=s.api_key, api_key_env=s.api_key_env,
            temperature=s.temperature, timeout=s.timeout, max_retries=s.max_retries,
        )

    def run(self, request: str):
        return self._core.run(request)

    # ---------------- 离线模式 ----------------

    def offline(self, request: str) -> dict:
        """无 LLM 管线：优先按 JSON 发现润色；否则对文本做语气检查。"""
        request = (request or "").strip()
        if request.startswith("[") or request.startswith("{"):
            polished = polish_findings(request)
            tone = tone_check(polished.get("review_text", "")) if polished.get("ok") else {"ok": True, "issues": [], "summary": "无"}
            report = self._report(polished, tone, mode="polish")
            return {"polished": polished, "tone": tone, "report": report}
        tone = tone_check(request)
        report = self._report(None, tone, mode="tone")
        return {"polished": None, "tone": tone, "report": report}

    def _report(self, polished, tone, mode) -> str:
        lines = ["# 代码评审意见顾问报告", ""]
        if mode == "polish" and polished and polished.get("ok"):
            lines.append("## 评审意见（可发出）\n")
            lines.append(polished["review_text"])
            lines.append("")
            lines.append("## 语气检查\n")
            lines.append(f"- {tone['summary']}")
            lines.append("")
            lines.append("## 给作者的回复模板（按需选用）\n")
            for t in polished.get("reply_templates", []):
                lines.append(f"- {t}")
            lines.append("")
        elif mode == "polish":
            lines.append(f"输入解析失败：{polished.get('error')}")
        else:
            lines.append("## 语气检查\n")
            if tone["issues"]:
                for i in tone["issues"]:
                    lines.append(f"- ❌ [{i['type']}] `…{i['context']}…` → {i['fix']}")
            else:
                lines.append("- ✅ 语气检查通过：对事不对人、可执行、无攻击性措辞")
            lines.append("")
        lines.append("---")
        lines.append("*本报告由 code-review-advisor 离线管线生成（未调用 LLM）。*")
        return "\n".join(lines)


def load_agent(agent_dir: str | Path | None = None) -> ReviewAdvisorAgent:
    if agent_dir is None:
        agent_dir = Path(__file__).resolve().parents[2]
    return ReviewAdvisorAgent(AgentConfig.load(agent_dir))
