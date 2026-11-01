"""clickhouse-sql-optimizer 的 Agent 工具集与注册入口。"""
from __future__ import annotations

from pathlib import Path

from common.agentcore import ToolRegistry
from common.tools.knowledge_search import search

from .ddl_advisor import advise_ddl
from .ddl_codegen import generate_ddl
from .diagnostics import build_diagnostics
from .explain_parser import parse_explain
from .sql_review import review_sql


def build_registry(agent_dir: str | Path, enabled: dict[str, bool] | None = None) -> ToolRegistry:
    """把本 Agent 的工具注册到 ToolRegistry。

    agent_dir: Agent 根目录（用于定位 knowledge/）。
    enabled: config.yaml 中 tools 段的开关；缺省全部启用。
    """
    agent_dir = Path(agent_dir)
    enabled = enabled or {}
    registry = ToolRegistry()

    if enabled.get("knowledge_search", True):
        knowledge_dir = agent_dir / "knowledge"

        def _search(query: str, top_k: int = 2) -> dict:
            results = search(knowledge_dir, query, top_k)
            return {
                "results": results,
                "hint": "摘录来自知识库（规范提炼）；如需更多细节用更具体的中英混合关键词再次检索" if results else "未命中，尝试换关键词（如: order by 低基数、final 去重、join 字典）",
            }

        registry.register(
            name="knowledge_search",
            description="检索 ClickHouse 优化知识库（开发规范提炼）：排序键/引擎选择、分区与跳数索引、JOIN 与字典、物化视图与投影、慢SQL定位六步 SOP、常见陷阱。涉及规范细节时先查再答。",
            parameters={
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "关键词，中英混合效果好，如: order by 低基数、final argMax、granules 裁剪、慢SQL 定位"},
                    "top_k": {"type": "integer", "description": "返回条数，1-5，默认 2"},
                },
                "required": ["query"],
            },
            func=_search,
        )

    if enabled.get("review_sql", True):

        def _review(sql: str) -> dict:
            return review_sql(sql)

        registry.register(
            name="review_sql",
            description="静态审查 ClickHouse SQL（14 条规范规则）：SELECT*、无 WHERE、键列函数包裹、大偏移分页、FINAL 代价、前导通配 LIKE、精确去重、JOIN 数量/逗号连接、IN 子查询、无 LIMIT 排序、mutation 滥用、单行插入。返回分级问题与改写建议。收到任何查询语句时调用。",
            parameters={
                "type": "object",
                "properties": {
                    "sql": {"type": "string", "description": "待审查的 SQL 文本（可含多条语句）"},
                },
                "required": ["sql"],
            },
            func=_review,
        )

    if enabled.get("advise_ddl", True):

        def _advise(ddl: str) -> dict:
            return advise_ddl(ddl)

        registry.register(
            name="advise_ddl",
            description="评估建表 DDL：解析引擎/ORDER BY/分区/PRIMARY KEY/TTL/列类型/跳数索引，按规范检查 13 类问题（排序键设计、过度分区、Nullable/Float 滥用、ReplacingMergeTree 版本列、Collapsing Sign 等），返回结构化问题与建议。收到 CREATE TABLE 时调用。",
            parameters={
                "type": "object",
                "properties": {
                    "ddl": {"type": "string", "description": "CREATE TABLE 语句（SHOW CREATE TABLE 输出亦可）"},
                },
                "required": ["ddl"],
            },
            func=_advise,
        )

    if enabled.get("ddl_codegen", True):

        def _codegen(scenario: str, table: str = "", dimensions: str = "", time_col: str = "event_time", ttl_days: int = 90, partition: str = "") -> dict:
            return generate_ddl(scenario, table=table, dimensions=dimensions, time_col=time_col, ttl_days=ttl_days, partition=partition)

        registry.register(
            name="ddl_codegen",
            description="按场景生成合规建表 DDL：append_log=追加写明细表(MergeTree+分区+TTL+跳数索引)；cdc_upsert=CDC入湖去重(ReplacingMergeTree(updated_at)+软删)；collapsing=增减回撤(CollapsingMergeTree(sign))；agg_rollup=预聚合汇总(AggregatingMergeTree+物化视图+查询示例)。用户要建表/设计表但没给 DDL 时调用，生成后建议再调 advise_ddl 复核。",
            parameters={
                "type": "object",
                "properties": {
                    "scenario": {"type": "string", "enum": ["append_log", "cdc_upsert", "collapsing", "agg_rollup"], "description": "建表场景"},
                    "table": {"type": "string", "description": "表名（可含库名），如 dwd.event_log"},
                    "dimensions": {"type": "string", "description": "维度/业务主键列，逗号分隔，按过滤频率从高到低（低基数在前）"},
                    "time_col": {"type": "string", "description": "时间列名，默认 event_time"},
                    "ttl_days": {"type": "integer", "description": "TTL 天数，默认 90；0 表示不设"},
                    "partition": {"type": "string", "description": "分区粒度 month/day，默认按 TTL 自动（≤7天 TTL 用日）"},
                },
                "required": ["scenario"],
            },
            func=_codegen,
        )

    if enabled.get("parse_explain", True):

        def _explain(explain_output: str) -> dict:
            return parse_explain(explain_output)

        registry.register(
            name="parse_explain",
            description="解析 EXPLAIN 输出：提取 Parts/Granules 裁剪比、Key Condition、PREWHERE 下推、读取列数等指标，量化诊断分区裁剪与主键裁剪效果并给出建议。收到 EXPLAIN 结果文本时调用。",
            parameters={
                "type": "object",
                "properties": {
                    "explain_output": {"type": "string", "description": "EXPLAIN / EXPLAIN indexes=1 / EXPLAIN ANALYZE 的输出文本"},
                },
                "required": ["explain_output"],
            },
            func=_explain,
        )

    if enabled.get("build_diagnostics", True):

        def _diagnose(table: str = "") -> dict:
            return build_diagnostics(table)

        registry.register(
            name="build_diagnostics",
            description="生成慢SQL定位六步 SOP 与可在用户库执行的诊断 SQL 集合（按 SOP 阶段标注）：TOP 慢查询（system.query_log）、part 碎片健康度、mutation 堆积、async_insert 攒批、跳数索引命中验证模板、字典健康度。需要真实数据佐证优化建议时调用（不需要数据库连接）。",
            parameters={
                "type": "object",
                "properties": {
                    "table": {"type": "string", "description": "可选：关注的核心表名，会附加该表的规模与压缩统计"},
                },
                "required": [],
            },
            func=_diagnose,
        )

    return registry


__all__ = [
    "build_registry",
    "review_sql",
    "advise_ddl",
    "generate_ddl",
    "parse_explain",
    "build_diagnostics",
    "search",
]
