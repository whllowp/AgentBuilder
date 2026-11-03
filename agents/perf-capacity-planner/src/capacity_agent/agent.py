"""CapacityPlannerAgent：LLM 工具调用模式 + 无 LLM 的离线管线。"""
from __future__ import annotations

from . import _bootstrap  # noqa: F401

from pathlib import Path

from common.agentcore import BaseAgent, ToolRegistry
from common.llm.client import LLMClient

from capacity_tools import build_registry, parse_spec, plan

from .config import AgentConfig

_ENGINE_TITLE = {"clickhouse": "ClickHouse 存储/主键内存/分区", "kafka": "Kafka 分区与存储",
                 "flink": "Flink 并行度与资源", "generic": "通用线程/连接池"}


class CapacityPlannerAgent:
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
        parsed = parse_spec(request or "")
        engine = parsed.get("engine", "unknown")
        result = plan({k: v for k, v in parsed.items() if k not in ("engine", "raw_text") and v is not None} | {"engine": engine}) if engine != "unknown" else {"ok": False, "error": "未识别引擎"}
        return {"parsed": parsed, "result": result, "report": self._report(parsed, result)}

    def _report(self, parsed: dict, result: dict) -> str:
        lines = ["# 性能容量评估报告", ""]
        if not result.get("formula"):
            lines.append(f"未识别到引擎（clickhouse/kafka/flink/generic）。请描述量级，如：\"ClickHouse 日增 2 亿行，行宽 200B，保留 90 天，双副本\"。")
            return "\n".join(lines)
        engine = result.get("engine", parsed.get("engine"))
        lines.append(f"## 需求解析\n\n- 引擎：{_ENGINE_TITLE.get(engine, engine)}")
        params = {k: v for k, v in parsed.items() if k not in ("engine", "raw_text") and v is not None}
        lines.append(f"- 解析参数：{params}")
        lines.append("")
        lines.append("## 容量结论\n")
        lines.append("| 项 | 值 |")
        lines.append("| --- | --- |")
        for k, v in result.get("results", {}).items():
            lines.append(f"| {k} | {v} |")
        lines.append("")
        lines.append("## 假设与公式\n")
        lines.append(f"- 公式：{result.get('formula', '')}")
        for a in result.get("assumptions", []):
            lines.append(f"- 假设：{a}")
        lines.append("")
        lines.append("## 建议\n")
        for r in result.get("recommendations", []):
            lines.append(f"- {r}")
        lines.append("")
        lines.append(f"## 水位与扩容\n- {self.config.watermark_rule}；结构性水位（分区>1000/持续反压/lag 趋势增长）无视百分比立即处理。")
        lines.append("")
        lines.append("## 验证方法\n- 影子流量/回放压测（真实数据分布），观察目标水位与 P99；上线首周预测偏差 >30% 即修正系数。")
        lines.append("")
        lines.append(f"## 敏感性\n- {result.get('sensitivity', '')}")
        lines.append("")
        lines.append("---")
        lines.append("*本报告由 perf-capacity-planner 离线管线生成（未调用 LLM）；LLM 模式可交互修正系数。*")
        return "\n".join(lines)


def load_agent(agent_dir: str | Path | None = None) -> CapacityPlannerAgent:
    if agent_dir is None:
        agent_dir = Path(__file__).resolve().parents[2]
    return CapacityPlannerAgent(AgentConfig.load(agent_dir))
