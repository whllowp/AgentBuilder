"""perf-capacity-planner 的 Agent 工具集与注册入口。"""
from __future__ import annotations

from pathlib import Path

from common.agentcore import ToolRegistry
from common.tools.knowledge_search import search

from .capacity_calc import plan
from .spec_parser import parse_spec


def build_registry(agent_dir: str | Path, enabled: dict[str, bool] | None = None) -> ToolRegistry:
    agent_dir = Path(agent_dir)
    enabled = enabled or {}
    registry = ToolRegistry()

    if enabled.get("capacity_plan", True):

        def _plan(spec: str) -> dict:
            import json
            if isinstance(spec, str):
                if spec.strip().startswith("{"):
                    try:
                        spec = json.loads(spec)
                    except json.JSONDecodeError:
                        return {"ok": False, "error": "spec JSON 不合法"}
                else:
                    parsed = parse_spec(spec)
                    if parsed.get("engine", "unknown") == "unknown":
                        return {"ok": False, "error": "未能识别引擎（clickhouse/kafka/flink/generic）", "parsed": parsed}
                    spec = {k: v for k, v in parsed.items() if k not in ("engine", "raw_text") and v is not None}
                    spec["engine"] = parsed["engine"]
            return plan(spec)

        registry.register(
            name="capacity_plan",
            description="性能容量计算（输出公式+假设+水位阈值+敏感性）：clickhouse=日行数/行宽/TTL→存储/主键内存/分区数；kafka=消息速率/大小/保留→分区数/存储；flink=吞吐/状态/键基数→并行度/slots/TM/内存；generic=QPS/时延→线程与连接池。输入自然语言需求或 JSON spec。容量评估必调用。",
            parameters={
                "type": "object",
                "properties": {
                    "spec": {"type": "string", "description": "自然语言容量需求，或 JSON：{\"engine\":\"clickhouse\",\"rows_per_day\":..,\"avg_row_bytes\":..}"},
                },
                "required": ["spec"],
            },
            func=_plan,
        )

    if enabled.get("knowledge_search", True):
        knowledge_dir = agent_dir / "knowledge"

        def _search(query: str, top_k: int = 2) -> dict:
            results = search(knowledge_dir, query, top_k)
            return {"results": results, "hint": "知识库摘录；可换关键词：水位 扩容 压测 系数" if results else "未命中"}

        registry.register(
            name="knowledge_search",
            description="检索性能容量知识库：容量模型与经验系数（压缩比/单分区吞吐/RocksDB 放大）、水位与扩容阈值（50/70 规则）、压测验证要求。解释系数或给扩容建议时先查。",
            parameters={
                "type": "object",
                "properties": {"query": {"type": "string", "description": "关键词，如: 压缩比 系数、扩容 阈值"}, "top_k": {"type": "integer"}},
                "required": ["query"],
            },
            func=_search,
        )

    return registry


__all__ = ["build_registry", "plan", "parse_spec"]
