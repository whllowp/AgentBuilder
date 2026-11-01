"""FlinkOperatorAgent：LLM 工具调用模式 + 无 LLM 的离线 pipeline 模式。"""
from __future__ import annotations

from . import _bootstrap  # noqa: F401 —— 必须最先导入以建立 sys.path

import os
from pathlib import Path

from common.agentcore import BaseAgent, ToolRegistry
from common.llm.client import LLMClient

from flink_tools import build_registry
from flink_tools.code_validator import validate_code
from flink_tools.source_codegen import generate_builtin_usage, generate_custom_source

from .analyzer import analyze_requirement
from .config import AgentConfig


class FlinkOperatorAgent:
    def __init__(self, config: AgentConfig, llm: LLMClient | None = None):
        self.config = config
        self.llm = llm or self._default_llm()
        self.tools: ToolRegistry = build_registry(config.agent_dir, config.tools)
        self.system_prompt = (config.prompts_dir / "system.md").read_text(encoding="utf-8")
        self._core = BaseAgent(
            llm=self.llm,
            system_prompt=self.system_prompt,
            tools=self.tools,
            max_iterations=config.max_iterations,
        )

    def _default_llm(self) -> LLMClient:
        settings = self.config.llm
        return LLMClient(
            base_url=settings.base_url,
            model=settings.model,
            api_key=settings.api_key,
            api_key_env=settings.api_key_env,
            temperature=settings.temperature,
            timeout=settings.timeout,
            max_retries=settings.max_retries,
        )

    # ---------------- LLM 模式 ----------------

    def run(self, request: str):
        """完整 Agent 回路（需可用的 LLM 端点）。"""
        return self._core.run(request)

    # ---------------- 离线模式 ----------------

    def offline(self, request: str) -> dict:
        """无 LLM 的规则管线：解析需求 -> 生成代码 -> 静态审查 -> 组装报告。"""
        profile = analyze_requirement(request)
        generation = self._generate(profile)
        context = "数据倾斜" if profile.get("data_skew") else ""
        issues = validate_code(generation["code"], context) if generation else {"ok": True, "issues": [], "summary": "无代码"}
        report = self._build_report(profile, generation, issues)
        return {"profile": profile, "generation": generation, "validation": issues, "report": report}

    def _generate(self, profile: dict) -> dict | None:
        kind = profile["kind"]
        if kind == "custom":
            return generate_custom_source(
                source_name=profile.get("source_name") or "Custom",
                bounded=bool(profile.get("bounded")),
            )
        if kind in ("cdc", "kafka", "file", "datagen"):
            return generate_builtin_usage(kind)
        return None

    def _build_report(self, profile: dict, generation: dict | None, validation: dict) -> str:
        lines: list[str] = ["# Flink Source 开发报告", ""]

        lines.append("## 需求解析\n")
        lines.append("| 项 | 值 |")
        lines.append("| --- | --- |")
        kind_desc = {
            "custom": "自定义 Source（FLIP-27）",
            "kafka": "内置 KafkaSource",
            "cdc": "Flink CDC（数据库摄入，阿里规范首选）",
            "file": "内置 FileSource",
            "datagen": "内置 DataGeneratorSource",
            "unknown": "未识别（见下方建议）",
        }
        lines.append(f"| Source 类型 | {kind_desc.get(profile['kind'], profile['kind'])} |")
        lines.append(f"| 有界性 | {'有界（批）' if profile.get('bounded') else '无界（流）' if profile.get('bounded') is not None else '未说明，默认无界'} |")
        lines.append(f"| 时间语义 | {'事件时间（需 WatermarkStrategy）' if profile.get('event_time') else '处理时间（noWatermarks）'} |")
        lines.append(f"| 语言 | {profile.get('language', 'java')} |")
        if profile.get("parallelism"):
            lines.append(f"| 并行度 | {profile['parallelism']} |")
        lines.append("")

        if profile.get("language") == "python" and profile["kind"] == "custom":
            lines.append("> 注意：Flink 1.17 的 Python API 不支持 Split Reader API，自定义 Source 需用 Java 开发。以下按 Java 生成。\n")

        if generation:
            lines.append("## 代码\n")
            if generation.get("filename"):
                lines.append(f"**文件**: `{generation['filename']}`\n")
            lines.append(f"```{generation.get('language', 'java')}")
            lines.append(generation["code"])
            lines.append("```\n")
            for dep in generation.get("dependencies", []):
                lines.append(f"- Maven 依赖: {dep}")
            if generation.get("dependencies"):
                lines.append("")
            if generation.get("todo_points"):
                lines.append("**骨架中的 TODO 对接点**:\n")
                for todo in generation["todo_points"]:
                    lines.append(f"- [ ] {todo}")
                lines.append("")
            if profile.get("event_time"):
                lines.append("**事件时间配置**（WatermarkStrategy 必须传给 `env.fromSource`，不可用 `assignTimestampsAndWatermarks`）:\n")
                lines.append("```java")
                lines.append("WatermarkStrategy<" + ("String" if generation.get("language") == "java" else "T") + "> wm =")
                lines.append("    WatermarkStrategy.<String>forBoundedOutOfOrderness(Duration.ofSeconds(5))")
                lines.append("        .withTimestampAssigner((event, ts) -> /* 从事件字段提取时间戳 */ ts);")
                lines.append("env.fromSource(source, wm, \"source-name\");")
                lines.append("```\n")
        else:
            lines.append("## 代码\n")
            lines.append("未能从需求中识别 Source 类型。可参考的三条路径：")
            lines.append("1. **自定义 Source**（对接自有系统）：说明外部系统与数据格式，将生成 FLIP-27 骨架（Source / Split / SplitEnumerator / SourceReaderBase / SplitReader）。")
            lines.append("2. **内置 Source**：Kafka（topic 消费）、File（文件/目录读取）、DataGenerator（造数压测）。")
            lines.append("3. **普通算子开发**（map/process/keyBy 等）：直接描述转换逻辑。\n")

        lines.append("## 审查结果\n")
        if validation.get("issues"):
            for issue in validation["issues"]:
                icon = {"error": "❌", "warning": "⚠️ ", "info": "ℹ️ "}.get(issue["severity"], "-")
                lines.append(f"- {icon} [{issue['severity']}] {issue['message']}")
        else:
            lines.append("- ✅ 静态检查未发现问题")
        lines.append("")

        lines.append("## 生产与监控建议（阿里规范）\n")
        kind = profile.get("kind")
        if kind == "kafka":
            lines.append("- **并行度对齐**：Source 并行度等于或小于 Topic 分区总数，避免 Reader 空转。")
        if kind == "cdc":
            lines.append("- **CDC 并行度**：全量同步阶段并行度与 Chunk 切分策略匹配，最大化数据库并发读取；checkpoint 间隔不宜过大（binlog 位点依赖 checkpoint 推进）。")
        if profile.get("event_time"):
            lines.append("- **防空闲分区**：WatermarkStrategy 配置 `withIdleness(...)` 或 Watermark Alignment，防止空闲/倾斜分区卡住全局水位线、下游窗口不触发。")
        if kind == "custom":
            lines.append("- **split 级对齐**：实现 `SplitReader#pauseOrResumeSplits`（骨架已含 TODO），多 Split 倾斜时自动暂停长尾分区。")
            lines.append("- **状态精简**：消费进度存入 Split；`snapshotState()` 只存必要元数据，严禁大对象入 State。")
        if profile.get("data_skew"):
            lines.append("- **数据倾斜**：keyBy 加盐打散（两阶段聚合）或 rebalance；SQL 侧开启 `table.optimizer.agg-phase-strategy=TWO_PHASE` 与 `table.optimizer.distinct-agg.split.enabled=true`。")
        lines.append("- **上线前压测**：用生产真实数据分布（非均匀假数据）做反压与 Checkpoint 耗时测试，重点观察长尾 Subtask。")
        lines.append("- **监控告警**：配置 Source 延迟、Checkpoint 失败率、空闲分区数；核心链路反压（isBackPressured / outPoolUsage > 80%）持续 5 分钟告警。")
        lines.append("")

        lines.append("## 使用与验证")
        lines.append("1. 将代码放入 Maven 工程（Flink 1.17.x，Java 8/11），依赖见上方 Maven 列表。")
        lines.append("2. 填充 TODO 对接点后本地运行 main() 冒烟。")
        lines.append("3. 有界场景：跑完应自动结束；无界场景：观察 checkpoint 与水位线推进。")
        lines.append("")

        lines.append("---")
        lines.append("*本报告由 flink-operator-developer 离线管线生成（未调用 LLM）；LLM 模式可获得交互式定制。*")
        return "\n".join(lines)


def load_agent(agent_dir: str | Path | None = None) -> FlinkOperatorAgent:
    """默认从本文件位置推断 Agent 目录构造 Agent。"""
    if agent_dir is None:
        agent_dir = Path(__file__).resolve().parents[2]
    return FlinkOperatorAgent(AgentConfig.load(agent_dir))
