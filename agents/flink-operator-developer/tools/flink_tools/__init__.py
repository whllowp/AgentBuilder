"""flink-operator-developer 的 Agent 工具集与注册入口。"""
from __future__ import annotations

from pathlib import Path

from common.agentcore import ToolRegistry

from .code_validator import validate_code
from .knowledge_search import search
from .source_codegen import generate_builtin_usage, generate_custom_source


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
                "hint": "摘录来自知识库原文；如需更多细节可用更具体的关键词再次检索" if results else "未命中，尝试换关键词",
            }

        registry.register(
            name="knowledge_search",
            description="检索 Flink 1.17 Data Source API 知识库（官方文档提炼），返回最相关条目与小节摘录。涉及 API 细节、水位线规则、线程模型时先查再答。",
            parameters={
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "关键词，中英混合效果好，如: watermark per-split 对齐"},
                    "top_k": {"type": "integer", "description": "返回条数，1-5，默认 2"},
                },
                "required": ["query"],
            },
            func=_search,
        )

    if enabled.get("source_codegen", True):

        def _codegen(
            mode: str,
            source_name: str = "Custom",
            record_type: str = "String",
            package: str = "com.example.flink",
            bounded: bool = False,
            bootstrap_servers: str = "<bootstrap_servers>",
            topic: str = "<topic>",
            group_id: str = "<group_id>",
            path: str = "<path>",
            hostname: str = "<hostname>",
            database: str = "<database>",
            table_list: str = "<database>.<table>",
            username: str = "<username>",
        ) -> dict:
            if mode == "custom_source":
                return generate_custom_source(source_name, record_type, package, bounded)
            return generate_builtin_usage(
                mode,
                bootstrap_servers=bootstrap_servers,
                topic=topic,
                group_id=group_id,
                path=path,
                hostname=hostname,
                database=database,
                table_list=table_list,
                username=username,
            )

        registry.register(
            name="source_codegen",
            description="生成 Flink 1.17 Source 代码：mode=custom_source 生成 FLIP-27 自定义 Source 完整骨架（含阿里规范要求的状态精简、split 级 watermark 对齐钩子、Unaligned Checkpoint）；mode=cdc 生成 MySQL CDC 用法（阿里规范：数据库摄入首选）；mode=kafka|file|datagen 生成内置 Source 的 fromSource 用法示例。",
            parameters={
                "type": "object",
                "properties": {
                    "mode": {"type": "string", "enum": ["custom_source", "cdc", "kafka", "file", "datagen"]},
                    "source_name": {"type": "string", "description": "自定义 Source 名称（类名前缀），如 Mqtt、OrderLog"},
                    "record_type": {"type": "string", "description": "输出记录的 Java 类型，默认 String"},
                    "package": {"type": "string", "description": "Java 包名"},
                    "bounded": {"type": "boolean", "description": "true=有界(批) false=无界(流)"},
                    "bootstrap_servers": {"type": "string", "description": "kafka 模式: broker 地址"},
                    "topic": {"type": "string", "description": "kafka 模式: topic"},
                    "group_id": {"type": "string", "description": "kafka 模式: 消费组"},
                    "path": {"type": "string", "description": "file 模式: 文件/目录路径"},
                    "hostname": {"type": "string", "description": "cdc 模式: 数据库地址"},
                    "database": {"type": "string", "description": "cdc 模式: 库名"},
                    "table_list": {"type": "string", "description": "cdc 模式: 库.表，支持正则"},
                    "username": {"type": "string", "description": "cdc 模式: 账号"},
                },
                "required": ["mode"],
            },
            func=_codegen,
        )

    if enabled.get("code_validator", True):

        def _validate(code: str, context: str = "") -> dict:
            return validate_code(code, context)

        registry.register(
            name="validate_code",
            description="静态审查 Flink 代码（官方 API 规范 + 阿里生产规范）：遗留 SourceFunction/addSource、水位线误用（assignTimestampsAndWatermarks）与空闲分区防护（withIdleness/对齐）、Source 接口完整性、并行度与分区对齐、UDF 重对象复用、RocksDB/Unaligned Checkpoint 建议、processElement 同步 I/O 等。生成代码后或收到用户代码时调用。",
            parameters={
                "type": "object",
                "properties": {
                    "code": {"type": "string", "description": "待审查的代码文本"},
                    "context": {"type": "string", "description": "补充说明，如作业类型、时间语义、是否存在数据倾斜（会启用倾斜专项检查）"},
                },
                "required": ["code"],
            },
            func=_validate,
        )

    return registry


__all__ = ["build_registry", "generate_custom_source", "generate_builtin_usage", "validate_code", "search"]
