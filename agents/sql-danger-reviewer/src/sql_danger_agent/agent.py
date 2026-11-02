"""SqlDangerReviewerAgent：LLM 工具调用模式 + 无 LLM 的离线 pipeline 模式。"""
from __future__ import annotations

from . import _bootstrap  # noqa: F401 —— 必须最先导入以建立 sys.path

from pathlib import Path

from common.agentcore import BaseAgent, ToolRegistry
from common.llm.client import LLMClient
from common.tools.knowledge_search import search as knowledge_search

from danger_tools import APPROVAL_CHECKLIST, build_registry, scan_code

from .config import AgentConfig

_ICON = {"致命": "🔴", "高危": "🟠", "中危": "🟡", "提示": "🔵"}


class SqlDangerReviewerAgent:
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

    def offline(self, request: str) -> dict:
        """无 LLM 管线：扫描 -> 知识库佐证 -> 放行四件套 -> Markdown 报告。"""
        result = scan_code(request)
        knowledge = self._knowledge_hits(result)
        report = self._build_report(request, result, knowledge)
        return {"scan": result, "knowledge": knowledge, "report": report}

    def _knowledge_hits(self, result: dict) -> list[dict]:
        if not result.get("ok"):
            return []
        topics = []
        for f in result.get("findings", []):
            rid = f.get("rule_id", "")
            if rid in ("DGR-101", "DGR-102", "DGR-103"):
                topics.append("恒真 WHERE 1=1 全表")
            elif rid in ("DGR-104", "DGR-105", "DGR-201"):
                topics.append("删库 删表 TRUNCATE 豁免 tmp")
            elif rid in ("DGR-204",):
                topics.append("mutation ALTER DELETE")
            elif rid in ("DGR-205",):
                topics.append("动态 SQL 拼接 f-string")
            elif rid in ("DGR-402",):
                topics.append("字面量 注释 误报 EXPLAIN")
        hits, seen = [], set()
        for topic in topics[:4]:
            try:
                for r in knowledge_search(self.config.knowledge_dir, topic, 1):
                    if r["file"] not in seen:
                        seen.add(r["file"])
                        hits.append(r)
            except FileNotFoundError:
                break
        return hits[:3]

    def _build_report(self, code: str, result: dict, knowledge: list[dict]) -> str:
        lines = ["# 高危操作代码评审报告", ""]

        if not result.get("ok"):
            lines.append("输入为空或未识别到内容，无法扫描。")
            return "\n".join(lines)

        counts = result["counts"]
        verdict = result["verdict"]
        lines.append("## 扫描结论\n")
        icon = {"block": "⛔ block（阻断合入）", "review": "⚠️ review（评审确认）", "pass": "✅ pass"}.get(verdict, verdict)
        lines.append(f"- 结论：**{icon}**，requires_approval = {result['requires_approval']}")
        lines.append(f"- {result['summary']}")
        if result["requires_approval"]:
            lines.append("- 放行四件套：" + "；".join(APPROVAL_CHECKLIST))
        lines.append("")

        lines.append("## 发现明细\n")
        if result["findings"] and counts["提示"] == len(result["findings"]):
            lines.append("- 未发现高危操作（仅提示级信息，无需阻断）：")
            for f in result["findings"]:
                lines.append(f"  - 🔵 {f['rule_id']} {f['title']}")
            lines.append("")
        elif result["findings"]:
            lines.append("| 级别 | 规则 | 证据（原文） | 建议 |")
            lines.append("| --- | --- | --- | --- |")
            for f in result["findings"]:
                ev = f["evidence"].replace("|", "\\|")[:80]
                lines.append(
                    f"| {_ICON.get(f['severity'], '-')} {f['severity']} | {f['rule_id']} {f['title'].split('（')[0]} | `{ev}` | {f['suggestion'].split('；')[0]} |"
                )
            lines.append("")
        else:
            lines.append("- 未发现高危操作（DGR-1xx~5xx 全部通过）。")
            lines.append("")

        lines.append("## 改写建议\n")
        gave = False
        for f in result["findings"]:
            if f["severity"] in ("致命", "高危"):
                gave = True
                lines.append(f"- {_ICON.get(f['severity'], '-')} **{f['rule_id']} {f['title']}**")
                lines.append(f"  - {f['suggestion']}")
        if not gave:
            lines.append("- 无需改写；保持键等值守卫与豁免命名规范。")
        lines.append("")

        lines.append("## 放行路径\n")
        lines.append("1. 确认不可用更安全写法替代（键等值 WHERE / RENAME 归档 / 轻量删除）。")
        lines.append("2. 走变更审批（工单：影响表、行数预估、执行人、复核人）。")
        lines.append("3. 备份（RENAME 归档或快照）+ 回滚演练。")
        lines.append("4. 低峰窗口分批执行；注意：`-- safe:` 注释只降一级，不构成放行。")
        lines.append("")

        if knowledge:
            lines.append("## 规范依据（知识库命中）\n")
            for k in knowledge:
                lines.append(f"- **{k['title']}**（{k['file']}）：{k['excerpt'][:140]}…")
            lines.append("")
        lines.append(f"完整规范见《{self.config.spec_file}》（Agent 根目录）。")
        lines.append("")
        lines.append("---")
        lines.append("*本报告由 sql-danger-reviewer 离线管线生成（未调用 LLM）；LLM 模式可获得交互式评审。*")
        return "\n".join(lines)


def load_agent(agent_dir: str | Path | None = None) -> SqlDangerReviewerAgent:
    if agent_dir is None:
        agent_dir = Path(__file__).resolve().parents[2]
    return SqlDangerReviewerAgent(AgentConfig.load(agent_dir))
