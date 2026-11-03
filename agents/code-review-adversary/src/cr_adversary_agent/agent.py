"""CrAdversaryAgent：LLM 工具调用模式 + 无 LLM 的离线管线。"""
from __future__ import annotations

from . import _bootstrap  # noqa: F401

from pathlib import Path

from common.agentcore import BaseAgent, ToolRegistry
from common.llm.client import LLMClient

from cr_adversary_tools import build_corpus, build_registry, evaluate
from review_tools.static_scan import scan_diff

from .config import AgentConfig


class CrAdversaryAgent:
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

    def offline(self, request: str = "") -> dict:
        import re
        m = re.search(r"\b([1-9]|10)\b", request or "")
        max_tier = int(m.group(1)) if m else 10
        corpus = build_corpus(max_tier=max_tier)
        stats = evaluate(corpus, scan_diff)
        return {"max_tier": max_tier, "corpus": corpus, "stats": stats, "report": self._report(max_tier, stats)}

    def _report(self, max_tier: int, stats: dict) -> str:
        lines = ["# commit 对抗测试报告（code-reviewer）", ""]
        ok = stats["recall"] == 1.0 and stats["fp_rate"] == 0.0
        lines.append(f"被测：`{self.config.target_agent}/tools/review_tools/static_scan.py`")
        lines.append(f"语料：T1..T{max_tier}，deterministic {stats['det_total']} 条 + 语义基准 {stats['benchmark_n']} 条")
        lines.append("")
        lines.append("## 对抗结论\n")
        lines.append(f"- {'✅ 未被打穿' if ok else '❌ 存在缺口'}：确定性检出率 {stats['recall']:.0%}，误报率 {stats['fp_rate']:.0%}，打穿 {len(stats['misses'])} 处")
        lines.append(f"- 语义基准 {stats['benchmark_n']} 条已按边界声明导出（LLM 模式消化，不冒充通过）。")
        lines.append("")
        if stats["misses"]:
            lines.append("## 打穿样本与回补建议\n")
            for m in stats["misses"]:
                kind = "漏报" if m["expect"] == "danger" else "误报"
                lines.append(f"- [{kind}] `{m['id']}`（{m['technique']}）：{m['payload'][:80]}… → 实际 {m['verdict']}")
            lines.append("")
        else:
            lines.append("## 打穿样本\n- 无。建议 LLM 模式创造新技术级继续加压。\n")
        lines.append("## 复现命令\n```bash\npython agents/code-review-adversary/harness/iterate.py --rounds 10\n```")
        lines.append("")
        return "\n".join(lines)


def load_agent(agent_dir: str | Path | None = None) -> CrAdversaryAgent:
    if agent_dir is None:
        agent_dir = Path(__file__).resolve().parents[2]
    return CrAdversaryAgent(AgentConfig.load(agent_dir))
