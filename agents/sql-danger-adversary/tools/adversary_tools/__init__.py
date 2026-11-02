"""sql-danger-adversary 的 Agent 工具集与注册入口。

用途限定（防御性红队）：仅用于对本仓库自有检测引擎（sql-danger-reviewer）做对抗测试与加固。
"""
from __future__ import annotations

import sys
from pathlib import Path

from common.agentcore import ToolRegistry

from .attack_gen import build_corpus, evaluate

_ADVERSARY_DIR = Path(__file__).resolve().parents[2]
_REVIEWER_TOOLS = _ADVERSARY_DIR.parent / "sql-danger-reviewer" / "tools"
if str(_REVIEWER_TOOLS) not in sys.path:
    sys.path.insert(0, str(_REVIEWER_TOOLS))  # 评测专用耦合：被测引擎在被测方目录（生产代码不 import 对方）

from danger_tools.danger_scan import scan_code  # noqa: E402


def build_registry(agent_dir: str | Path, enabled: dict[str, bool] | None = None) -> ToolRegistry:
    enabled = enabled or {}
    registry = ToolRegistry()

    if enabled.get("generate_attacks", True):

        def _gen(max_tier: int = 10) -> dict:
            corpus = build_corpus(max_tier=max_tier)
            return {
                "corpus": corpus,
                "count": len(corpus),
                "hint": "每条样本含 technique/payload/expect；expect=danger 为漏报攻击（检出标准 verdict=block），expect=benign 为误报攻击（标准 verdict=pass）",
            }

        registry.register(
            name="generate_attacks",
            description="生成递进攻击语料（T1 明文 → T10 误报对抗，共 62 条）：混淆/注释断词/引用/恒真伪装/CTE/事务装饰/三明治掩埋/动态拼装/良性伪装。用于加固检测引擎的对抗测试。",
            parameters={
                "type": "object",
                "properties": {
                    "max_tier": {"type": "integer", "description": "攻击技术上限 1-10，默认 10（全量）"},
                },
                "required": [],
            },
            func=_gen,
        )

    if enabled.get("evaluate_attacks", True):

        def _eval(payloads: str) -> dict:
            """对多行 payload 逐条跑被测引擎，返回逐条 verdict。"""
            items = [x for x in payloads.splitlines() if x.strip()]
            results = []
            for p in items:
                r = scan_code(p)
                results.append({
                    "payload": p[:80],
                    "ok": r.get("ok"),
                    "verdict": r.get("verdict"),
                    "top_severity": next((f["severity"] for f in r.get("findings", []) if f["severity"] in ("致命", "高危")), None),
                    "summary": r.get("summary", ""),
                })
            return {"results": results, "note": "被测引擎：sql-danger-reviewer/tools/danger_tools/danger_scan.py"}

        registry.register(
            name="evaluate_attacks",
            description="把攻击 payload 逐行送入被测检测引擎（danger_scan）评估，返回逐条 verdict 与最高级别。红队生成攻击后必调用以验证是否打穿。",
            parameters={
                "type": "object",
                "properties": {
                    "payloads": {"type": "string", "description": "每行一个待评估的 SQL/代码 payload"},
                },
                "required": ["payloads"],
            },
            func=_eval,
        )

    if enabled.get("run_iteration", True):

        def _run(rounds: int = 10) -> dict:
            round_rows = []
            for r in range(1, max(1, min(rounds, 10)) + 1):
                stats = evaluate(build_corpus(max_tier=r), scan_code)
                round_rows.append({
                    "round": r, "attacks": len(build_corpus(max_tier=r)),
                    "recall": stats["recall"], "fp_rate": stats["fp_rate"],
                    "misses": len(stats["misses"]),
                })
            return {"rounds": round_rows, "note": "完整报告请运行 harness/iterate.py"}

        registry.register(
            name="run_iteration",
            description="跑 1-10 轮递进对抗迭代（每轮 = 攻击技术 1..r 累计），返回逐轮检出率/误报率。评估检测引擎整体健壮性时调用。",
            parameters={
                "type": "object",
                "properties": {
                    "rounds": {"type": "integer", "description": "轮数 1-10，默认 10"},
                },
                "required": [],
            },
            func=_run,
        )

    return registry


__all__ = ["build_registry", "build_corpus", "evaluate", "scan_code"]
