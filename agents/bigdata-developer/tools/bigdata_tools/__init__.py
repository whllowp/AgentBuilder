"""bigdata-developer 的 Agent 工具集与注册入口。"""
from __future__ import annotations

from pathlib import Path

from common.agentcore import ToolRegistry
from common.tools.knowledge_search import search

from .etl_codegen import generate
from .etl_review import review_code


def build_registry(agent_dir: str | Path, enabled: dict[str, bool] | None = None) -> ToolRegistry:
    agent_dir = Path(agent_dir)
    enabled = enabled or {}
    registry = ToolRegistry()

    if enabled.get("etl_codegen", True):

        def _gen(scenario: str, table: str = "", dt_col: str = "dt") -> dict:
            return generate(scenario, table=table, dt_col=dt_col)

        registry.register(
            name="etl_codegen",
            description="生成大数据 ETL 模板：hive_partition=分区表 DDL+动态分区增量拉取；hive_zipper=拉链表（全量初始化+每日关链开链）；flink_sql=Kafka 源+维表 lookup+sink 作业骨架；airflow_dag=依赖/重试/幂等/对账/告警 DAG；dolphinsched=DS 工作流（超时/重试/对账）。要开发大数据任务代码时调用，生成后建议 etl_review 自检。",
            parameters={
                "type": "object",
                "properties": {
                    "scenario": {"type": "string", "enum": ["hive_partition", "hive_zipper", "flink_sql", "airflow_dag", "dolphinsched"]},
                    "table": {"type": "string", "description": "核心表名（不带库名），如 dwd_event"},
                    "dt_col": {"type": "string", "description": "分区列名，默认 dt"},
                },
                "required": ["scenario"],
            },
            func=_gen,
        )

    if enabled.get("etl_review", True):

        def _review(code: str) -> dict:
            return review_code(code)

        registry.register(
            name="etl_review",
            description="静态审查 ETL/调度代码（8 条规则）：INSERT OVERWRITE 无分区、SELECT* 直通、增量缺时间过滤、DAG 缺重试/串行、缺对账、拉链漏 end_date 开链条件、DROP 非 tmp 表。收到任何 ETL SQL/DAG 代码时调用。",
            parameters={
                "type": "object",
                "properties": {"code": {"type": "string", "description": "ETL SQL / Airflow DAG / DS 工作流代码"}},
                "required": ["code"],
            },
            func=_review,
        )

    if enabled.get("knowledge_search", True):
        knowledge_dir = agent_dir / "knowledge"

        def _search(query: str, top_k: int = 2) -> dict:
            results = search(knowledge_dir, query, top_k)
            return {"results": results, "hint": "知识库摘录；可换关键词：拉链 幂等 重试 对账" if results else "未命中"}

        registry.register(
            name="knowledge_search",
            description="检索大数据开发知识库：ETL 最佳实践（幂等/重试/回滚、分区与增量、拉链表、数据质量校验）、调度规范。涉及设计取舍时先查。",
            parameters={
                "type": "object",
                "properties": {"query": {"type": "string"}, "top_k": {"type": "integer"}},
                "required": ["query"],
            },
            func=_search,
        )

    return registry


__all__ = ["build_registry", "generate", "review_code"]
