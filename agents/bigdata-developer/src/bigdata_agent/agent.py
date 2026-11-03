"""BigdataDeveloperAgent：LLM 工具调用模式 + 无 LLM 的离线管线。"""
from __future__ import annotations

from . import _bootstrap  # noqa: F401

import re
from pathlib import Path

from common.agentcore import BaseAgent, ToolRegistry
from common.llm.client import LLMClient

from bigdata_tools import build_registry, generate, review_code

from .config import AgentConfig

_ICON = {"高危": "🟠", "中危": "🟡", "低危": "🔵"}

_SCENARIO_KEYS = [
    ("hive_zipper", re.compile(r"拉链|scd|关链|开链|历史版本", re.IGNORECASE)),
    ("flink_sql", re.compile(r"flink|实时|流式|lookup|维表", re.IGNORECASE)),
    ("airflow_dag", re.compile(r"airflow|dag|调度.{0,6}(任务|作业)", re.IGNORECASE)),
    ("dolphinsched", re.compile(r"dolphinscheduler|海豚|ds\s*工作流", re.IGNORECASE)),
    ("hive_partition", re.compile(r"hive|分区表|ods|dwd|离线", re.IGNORECASE)),
]


def detect_scenario(text: str) -> str:
    for name, pat in _SCENARIO_KEYS:
        if pat.search(text or ""):
            return name
    return "hive_partition"


class BigdataDeveloperAgent:
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
        """生成模板 + 自检审查 + 报告；输入为代码时只审查。"""
        text = request or ""
        has_code = bool(re.search(r"INSERT|CREATE TABLE|import |DAG\(|tasks:", text, re.IGNORECASE)) and (
            len(text.splitlines()) >= 2 or ";" in text
        )
        if has_code:
            review = review_code(text)
            return {"mode": "review", "review": review, "report": self._review_report(review)}

        scenario = detect_scenario(text)
        m = re.search(r"表名[是为:：\s]*([A-Za-z_]\w*)", text)
        table = m.group(1) if m else ""
        gen = generate(scenario, table=table)
        review = review_code("\n\n".join(c for _, c in gen.get("artifacts", []))) if gen.get("ok") else {"findings": [], "summary": "未生成"}
        return {"mode": "codegen", "scenario": scenario, "generation": gen, "review": review,
                "report": self._codegen_report(scenario, gen, review)}

    def _codegen_report(self, scenario, gen, review) -> str:
        lines = ["# 大数据开发报告", "", "## 需求解析\n", f"- 场景：{scenario}（按关键词推断；不符请补充描述）"]
        if not gen.get("ok"):
            lines.append(f"- 生成失败：{gen.get('error')}")
            return "\n".join(lines)
        lines += ["", "## 代码\n"]
        for fname, code in gen["artifacts"]:
            lines.append(f"**{fname}**")
            lang = "python" if fname.endswith(".py") else ("yaml" if fname.endswith((".yaml", ".yml")) else "sql")
            lines.append(f"```{lang}")
            lines.append(code)
            lines.append("```\n")
        lines.append("## 设计要点\n")
        for n in gen.get("notes", []):
            lines.append(f"- {n}")
        lines += ["", "## 审查结果（模板自检）\n", f"- {review.get('summary', '未审查')}"]
        for f in review.get("findings", []):
            lines.append(f"- {_ICON.get(f['severity'], '-')} [{f['rule_id']}] {f['title']}：{f['suggestion']}")
        lines += ["", "## 上线检查单\n",
                  "- 调度参数：${ds}/${ds_nodash} 与分区对齐；补数走独立 backfill；",
                  "- 回滚：分区级用前一日分区重建；拉链单日重跑先回滚该分区；",
                  "- 对账：行数源 vs 目标 + 主键唯一性，失败即阻断下游；",
                  "- 告警：失败进值班群，超时与重试参数已内置模板。", "",
                  "---",
                  "*本报告由 bigdata-developer 离线管线生成（未调用 LLM）。*"]
        return "\n".join(lines)

    def _review_report(self, review) -> str:
        lines = ["# ETL 代码审查报告", "", f"- {review.get('summary', '')}"]
        for f in review.get("findings", []):
            lines.append(f"- {_ICON.get(f['severity'], '-')} [{f['rule_id']}] {f['title']}\n  - 证据：`{f['evidence'][:90]}`\n  - {f['suggestion']}")
        lines += ["", "---", "*本报告由 bigdata-developer 离线管线生成（未调用 LLM）。*"]
        return "\n".join(lines)


def load_agent(agent_dir: str | Path | None = None) -> BigdataDeveloperAgent:
    if agent_dir is None:
        agent_dir = Path(__file__).resolve().parents[2]
    return BigdataDeveloperAgent(AgentConfig.load(agent_dir))
