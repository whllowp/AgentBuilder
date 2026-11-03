"""code-review-advisor 的 Agent 工具集与注册入口。"""
from __future__ import annotations

from pathlib import Path

from common.agentcore import ToolRegistry
from common.tools.knowledge_search import search

from .comment_polish import polish_findings, tone_check


def build_registry(agent_dir: str | Path, enabled: dict[str, bool] | None = None) -> ToolRegistry:
    agent_dir = Path(agent_dir)
    enabled = enabled or {}
    registry = ToolRegistry()

    if enabled.get("polish_comments", True):

        def _polish(findings: str) -> dict:
            return polish_findings(findings)

        registry.register(
            name="polish_comments",
            description="把结构化评审发现（code-reviewer 的评论 JSON 数组，或 {title,evidence,severity,category,suggestion} 列表）润色成'合适的代码意见'：按 问题-影响-建议-依据 结构、按严重度排序、nit 标注、开场收尾礼仪；并附给作者的三类回复模板（接受/部分接受/说明背景）。产出评审意见前调用。",
            parameters={
                "type": "object",
                "properties": {
                    "findings": {"type": "string", "description": "发现列表的 JSON 字符串"},
                },
                "required": ["findings"],
            },
            func=_polish,
        )

    if enabled.get("tone_check", True):

        def _tone(draft: str) -> dict:
            return tone_check(draft)

        registry.register(
            name="tone_check",
            description="对评审意见草稿做语气检查：攻击性评价、人身指向（'你又错了'）、绝对化（'必须/肯定'）、反问质问、翻旧账，逐条给出替换建议。发出评论前调用，确保对事不对人。",
            parameters={
                "type": "object",
                "properties": {
                    "draft": {"type": "string", "description": "待检查的评审意见草稿"},
                },
                "required": ["draft"],
            },
            func=_tone,
        )

    if enabled.get("knowledge_search", True):
        knowledge_dir = agent_dir / "knowledge"

        def _search(query: str, top_k: int = 2) -> dict:
            results = search(knowledge_dir, query, top_k)
            return {"results": results, "hint": "知识库摘录；可换关键词：nit 分歧 措辞 模板" if results else "未命中"}

        registry.register(
            name="knowledge_search",
            description="检索代码评审礼仪知识库：意见结构与措辞模板、severity 语义、nit 与分歧处理、跨文化/远程协作注意点。拿不准怎么表达时先查。",
            parameters={
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "关键词，如: 措辞 模板、不同意 怎么回复、nit 处理"},
                    "top_k": {"type": "integer", "description": "返回条数，默认 2"},
                },
                "required": ["query"],
            },
            func=_search,
        )

    return registry


__all__ = ["build_registry", "polish_findings", "tone_check"]
