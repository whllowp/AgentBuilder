"""sql-danger-reviewer 的 Agent 工具集与注册入口。"""
from __future__ import annotations

from pathlib import Path

from common.agentcore import ToolRegistry
from common.tools.knowledge_search import search

from .danger_scan import scan_code


APPROVAL_CHECKLIST = [
    "审批：变更工单（影响表、行数预估、执行人、复核人）",
    "备份：目标表 RENAME 归档或快照/导出，保留可回滚时长",
    "回滚：写好逆向 DDL/DML 并在预发演练通过",
    "窗口：业务低峰执行；DML 分批 + 事务；ClickHouse mutation 配 mutations_sync=0 并监控 system.mutations",
]


def build_registry(agent_dir: str | Path, enabled: dict[str, bool] | None = None) -> ToolRegistry:
    agent_dir = Path(agent_dir)
    enabled = enabled or {}
    registry = ToolRegistry()

    if enabled.get("danger_scan", True):

        def _scan(code: str) -> dict:
            return scan_code(code)

        registry.register(
            name="danger_scan",
            description="扫描 SQL 脚本或含 SQL 的代码，检测高危操作（全表 UPDATE/DELETE、DROP DATABASE/TABLE、TRUNCATE、ALTER 破坏子句、mutation、动态拼装、rm -rf 等，DGR-1xx~5xx 规则）。免疫大小写/注释/引用/恒真/CTE/事务/三明治/动态等混淆（规范第 3 章）。返回分级发现、verdict(block/review/pass) 与 requires_approval。收到任何待评审代码必先调用。",
            parameters={
                "type": "object",
                "properties": {
                    "code": {"type": "string", "description": "SQL 脚本或包含 SQL 的应用/脚本代码"},
                },
                "required": ["code"],
            },
            func=_scan,
        )

    if enabled.get("knowledge_search", True):
        knowledge_dir = agent_dir / "knowledge"

        def _search(query: str, top_k: int = 2) -> dict:
            results = search(knowledge_dir, query, top_k)
            return {
                "results": results,
                "hint": "摘录自知识库（规范提炼）；可换关键词如: 恒真 1=1、注释注入、mutation、豁免 tmp" if results else "未命中，尝试换关键词",
            }

        registry.register(
            name="knowledge_search",
            description="检索高危操作检验知识库：DGR 规则目录与分级豁免、对抗（混淆/绕过）手法与检测对策、曾被红队打穿的缺口。涉及规则细节或判断依据时先查再答。",
            parameters={
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "关键词，如: 恒真 WHERE 1=1、动态 SQL 拼接、豁免 tmp"},
                    "top_k": {"type": "integer", "description": "返回条数，1-5，默认 2"},
                },
                "required": ["query"],
            },
            func=_search,
        )

    if enabled.get("approval_checklist", True):

        def _checklist(rule_id: str = "") -> dict:
            return {
                "checklist": APPROVAL_CHECKLIST,
                "note": f"针对 {rule_id} 的四件套要求；任何致命/高危 requires_approval=true" if rule_id else "通用放行四件套",
            }

        registry.register(
            name="approval_checklist",
            description="获取高危操作放行四件套（审批/备份/回滚/窗口）。给出 block 结论或用户询问'怎么才能放行'时调用。",
            parameters={
                "type": "object",
                "properties": {
                    "rule_id": {"type": "string", "description": "可选：命中的规则号，如 DGR-105"},
                },
                "required": [],
            },
            func=_checklist,
        )

    return registry


__all__ = ["build_registry", "scan_code", "APPROVAL_CHECKLIST"]
