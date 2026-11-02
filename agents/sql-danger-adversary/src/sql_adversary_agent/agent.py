"""SqlDangerAdversaryAgent：LLM 工具调用模式 + 无 LLM 的离线 pipeline 模式。

离线管线：生成全量攻击语料 -> 被测引擎逐条评估 -> 缺口归因（按技术级汇总）-> Markdown 对抗报告。
"""
from __future__ import annotations

from . import _bootstrap  # noqa: F401 —— 必须最先导入以建立 sys.path

from pathlib import Path

from common.agentcore import BaseAgent, ToolRegistry
from common.llm.client import LLMClient

from adversary_tools import build_corpus, build_registry, evaluate
from danger_tools.danger_scan import scan_code

from .config import AgentConfig

_TIER_NAME = {
    1: "明文基线", 2: "大小写/空白混淆", 3: "注释断词", 4: "标识符引用", 5: "恒真伪装",
    6: "CTE/包裹", 7: "事务装饰", 8: "三明治掩埋", 9: "动态拼装", 10: "误报对抗",
}


class SqlDangerAdversaryAgent:
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

    def offline(self, request: str = "") -> dict:
        """无 LLM 管线。request 可为空（全量）或含技术级数字（如 '5' 表示 T1..T5）。"""
        max_tier = 10
        m = __import__("re").search(r"\b([1-9]|10)\b", request or "")
        if m:
            max_tier = int(m.group(1))
        corpus = build_corpus(max_tier=max_tier)
        stats = evaluate(corpus, scan_code)
        report = self._build_report(max_tier, corpus, stats)
        return {"max_tier": max_tier, "corpus": corpus, "stats": stats, "report": report}

    def _build_report(self, max_tier: int, corpus: list, stats: dict) -> str:
        lines = ["# 代码评审对抗测试报告", ""]
        lines.append(f"被测引擎：`{self.config.target_agent}/tools/danger_tools/danger_scan.py`（DGR 规则）")
        lines.append(f"攻击语料：T1..T{max_tier} 共 {len(corpus)} 条（漏报攻击 {stats['danger_total']} / 误报攻击 {stats['benign_total']}）")
        lines.append("")
        lines.append("## 对抗结论\n")
        ok = stats["recall"] == 1.0 and stats["fp_rate"] == 0.0
        lines.append(f"- {'✅ 未被打穿' if ok else '❌ 存在缺口'}：检出率 {stats['recall']:.0%}，误报率 {stats['fp_rate']:.0%}，打穿 {len(stats['misses'])} 处")
        lines.append(f"- 验收线（规范第 6 章）：第 10 轮检出率 100% 且误报率 0%。")
        lines.append("")

        # 按技术级汇总
        lines.append("## 技术级覆盖\n")
        lines.append("| 级 | 技术 | 漏报攻击 | 检出 | 误报攻击 | 干净 |")
        lines.append("| --- | --- | --- | --- | --- | --- |")
        by_tier = {}
        for x in stats["results"]:
            t = x["tier"]
            d = by_tier.setdefault(t, {"d": 0, "dc": 0, "b": 0, "bc": 0})
            if x["expect"] == "danger":
                d["d"] += 1
                d["dc"] += 1 if x["passed"] else 0
            else:
                d["b"] += 1
                d["bc"] += 1 if x["passed"] else 0
        for t in sorted(by_tier):
            d = by_tier[t]
            lines.append(f"| T{t} | {_TIER_NAME.get(t, '')} | {d['d']} | {d['dc']} | {d['b']} | {d['bc']} |")
        lines.append("")

        if stats["misses"]:
            lines.append("## 打穿样本与回补建议\n")
            for m in stats["misses"]:
                kind = "漏报" if m["expect"] == "danger" else "误报"
                lines.append(f"- [{kind}] `{m['id']}`（{m['technique']}）：`{m['payload'][:90]}` → 实际 verdict={m['verdict']}")
            lines.append("")
            lines.append("回补路径：修订《高危操作代码检验规范.md》对应 DGR 条目 → danger_scan.py 规则/正规化 → 重跑 `harness/iterate.py`。")
            lines.append("")
        else:
            lines.append("## 打穿样本\n")
            lines.append("- 无。引擎对当前技术级免疫；建议扩充新攻击技术（LLM 模式）继续加压。")
            lines.append("")

        lines.append("## 复现命令\n")
        lines.append("```bash")
        lines.append("python agents/sql-danger-adversary/harness/iterate.py --rounds 10")
        lines.append("```")
        lines.append("")
        lines.append("---")
        lines.append("*本报告由 sql-danger-adversary 离线管线生成（未调用 LLM）；LLM 模式可创造新技术级攻击。*")
        return "\n".join(lines)


def load_agent(agent_dir: str | Path | None = None) -> SqlDangerAdversaryAgent:
    if agent_dir is None:
        agent_dir = Path(__file__).resolve().parents[2]
    return SqlDangerAdversaryAgent(AgentConfig.load(agent_dir))
