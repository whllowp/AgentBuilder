"""CodeReviewerAgent：LLM 工具调用模式 + 无 LLM 的离线确定性管线。"""
from __future__ import annotations

from . import _bootstrap  # noqa: F401 —— 必须最先导入以建立 sys.path

import json
from pathlib import Path

from common.agentcore import BaseAgent, ToolRegistry
from common.llm.client import LLMClient

from review_tools import build_registry, review_pipeline

from .config import AgentConfig

_SEV_ICON = {"critical": "🔴", "high": "🟠", "medium": "🟡", "low": "🔵"}
_SEV_ORDER = {"critical": 0, "high": 1, "medium": 2, "low": 3}


class CodeReviewerAgent:
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

    # ---------------- LLM 模式 ----------------

    def run(self, request: str):
        return self._core.run(request)

    # ---------------- 离线模式 ----------------

    def offline(self, diff_text: str) -> dict:
        """确定性管线：筛选 -> 打包 -> 规则匹配 -> 静态扫描 -> 分组报告。"""
        result = review_pipeline(diff_text, keep_low=self.config.keep_low)
        result["report"] = self._build_report(result)
        return result

    def _build_report(self, result: dict) -> str:
        stats = result.get("stats", {})
        lines = ["# 代码评审报告（code-reviewer）", ""]
        lines.append("> 管线参考 alibaba/open-code-review：文件筛选 → 智能打包 → 规则匹配 → 行级定位；low 项默认丢弃备查。")
        lines.append("")

        if not result.get("ok"):
            lines.append("未解析到任何变更（diff 为空或全部被过滤）。")
            return "\n".join(lines)

        # ---- 概览 ----
        lines.append("## 概览\n")
        lines.append(f"- 文件：{stats.get('total', 0)}（评审 {stats.get('reviewed', 0)} / 过滤 {stats.get('filtered', 0)}），"
                     f"+{stats.get('added', 0)}/-{stats.get('removed', 0)} 行")
        lines.append(f"- 评审单元（打包）：{len(result.get('bundles', []))} 个")
        if result.get("filtered_files"):
            shown = ", ".join(result["filtered_files"][:8])
            lines.append(f"- 已过滤：{shown}{'…' if len(result['filtered_files']) > 8 else ''}")
        cats = result.get("comments") and _category_counts(result["comments"])
        if cats:
            lines.append(f"- 分类统计：{cats}")
        blocked = any(c["severity"] == "critical" for c in result["comments"])
        should_fix = any(c["severity"] in ("critical", "high") for c in result["comments"])
        verdict = "⛔ 阻断：存在 critical 问题" if blocked else ("⚠️ 修复后可合入：存在 high 问题" if should_fix else
                  ("✅ 可合入（含 medium 建议）" if result["comments"] else "✅ 可合入：确定性检查未发现问题"))
        lines.append(f"- 结论：{verdict}")
        lines.append("")

        # ---- 分组意见 ----
        comments = sorted(result["comments"], key=lambda c: (_SEV_ORDER.get(c["severity"], 9), c["path"], c["start_line"]))
        if comments:
            lines.append("## 评审意见（按严重度）\n")
            for sev in ("critical", "high", "medium", "low"):
                group = [c for c in comments if c["severity"] == sev]
                if not group:
                    continue
                lines.append(f"### {sev.upper()}（{len(group)}）\n")
                for c in group:
                    loc = f"{c['path']}:{c['start_line']}" if c["start_line"] else f"{c['path']}:?"
                    lines.append(f"- {_SEV_ICON[sev]} **[{c['category']}] `{loc}`** {c['content']}")
                    if c.get("existing_code"):
                        lines.append(f"  - 原文：`{str(c['existing_code'])[:100]}`")
                    if c.get("suggestion_code"):
                        lines.append(f"  - 建议：`{str(c['suggestion_code'])[:100]}`")
                lines.append("")
        else:
            lines.append("## 评审意见\n")
            lines.append("- 确定性检查未发现问题；语义层问题（逻辑/边界/并发/测试）建议走 LLM 模式。")
            lines.append("")

        # ---- 忽略的 low ----
        dropped = result.get("dropped_low", [])
        if dropped:
            lines.append(f"## 已忽略的 low 项（疑似误报备查，共 {len(dropped)}）\n")
            for c in dropped[:10]:
                lines.append(f"- [{c['category']}] `{c['path']}:{c['start_line']}` {c['content']}")
            lines.append("")

        # ---- 规则与下一步 ----
        lines.append("## 规则匹配（LLM 模式的聚焦规则）\n")
        for path, rules in list(result.get("rules", {}).items())[:6]:
            lines.append(f"- `{path}`：{len(rules)} 条规则（{rules[0][:50]}…）")
        lines.append("")
        lines.append("```bash")
        lines.append("# 深度评审（语义层问题）：")
        lines.append("# python agents/code-reviewer/src/code_review_agent/cli.py \"<diff>\"   # LLM 模式")
        lines.append("```")
        lines.append("")
        lines.append("---")
        lines.append("*本报告由 code-reviewer 离线确定性管线生成（未调用 LLM）。*")
        return "\n".join(lines)


def _category_counts(comments: list[dict]) -> str:
    counts: dict[str, int] = {}
    for c in comments:
        counts[c["category"]] = counts.get(c["category"], 0) + 1
    return json.dumps(counts, ensure_ascii=False)


def load_agent(agent_dir: str | Path | None = None) -> CodeReviewerAgent:
    if agent_dir is None:
        agent_dir = Path(__file__).resolve().parents[2]
    return CodeReviewerAgent(AgentConfig.load(agent_dir))
