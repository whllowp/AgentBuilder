"""code-review-adversary 的 Agent 工具集与注册入口（防御性红队）。

评测专用耦合：被测引擎在 `agents/code-reviewer/tools/review_tools`，生产代码不 import 对方 Agent。
"""
from __future__ import annotations

import sys
from pathlib import Path

from common.agentcore import ToolRegistry

from .commit_attack import build_corpus, evaluate

_ADVERSARY_DIR = Path(__file__).resolve().parents[2]
_REVIEWER_TOOLS = _ADVERSARY_DIR.parent / "code-reviewer" / "tools"
if str(_REVIEWER_TOOLS) not in sys.path:
    sys.path.insert(0, str(_REVIEWER_TOOLS))

from review_tools.static_scan import scan_diff  # noqa: E402


def build_registry(agent_dir: str | Path, enabled: dict[str, bool] | None = None) -> ToolRegistry:
    enabled = enabled or {}
    registry = ToolRegistry()

    if enabled.get("generate_attacks", True):

        def _gen(max_tier: int = 10) -> dict:
            corpus = build_corpus(max_tier=max_tier)
            det = [a for a in corpus if a["kind"] == "deterministic"]
            bench = [a for a in corpus if a["kind"] == "llm-benchmark"]
            return {"corpus": corpus, "count": len(corpus), "deterministic": len(det),
                    "benchmark": len(bench),
                    "hint": "deterministic 类自动判定；llm-benchmark 类是语义 bug 基准，供 LLM 模式评审加压，不自动判定"}

        registry.register(
            name="generate_attacks",
            description="生成 commit 对抗语料（T1 明文缺陷 → T10 高级语义基准）：可机检项规避/伪装（密钥下划线与 yaml 形态、调试语句变体、多行链式反模式、大 diff 掩埋、多文件混合）、误报攻击（测试路径假凭据、带负责人的 TODO）、语义 bug 基准（差一错误/并发/泄漏/注入）。仅用于测试自有 code-reviewer 引擎。",
            parameters={
                "type": "object",
                "properties": {"max_tier": {"type": "integer", "description": "技术级上限 1-10，默认 10"}},
                "required": [],
            },
            func=_gen,
        )

    if enabled.get("evaluate_attacks", True):

        def _eval(payloads: str) -> dict:
            from review_tools.diff_utils import parse_diff
            items = [x for x in payloads.splitlines() if x.strip()]
            results = []
            for p in items:
                findings = [f for f in scan_diff(parse_diff(p)) if f["severity"] != "low"]
                results.append({"payload": p[:70], "findings_n": len(findings),
                                "top": findings[0]["severity"] if findings else None})
            return {"results": results, "note": "被测：code-reviewer static_scan（low 已按报告策略豁免）"}

        registry.register(
            name="evaluate_attacks",
            description="把 diff payload 逐行送入被测引擎（static_scan）评估命中情况（low 级按报告策略豁免）。红队生成攻击后必调用以验证是否打穿。",
            parameters={
                "type": "object",
                "properties": {"payloads": {"type": "string", "description": "每行一个 diff payload"}},
                "required": ["payloads"],
            },
            func=_eval,
        )

    if enabled.get("run_iteration", True):

        def _run(rounds: int = 10) -> dict:
            rows = []
            for r in range(1, max(1, min(rounds, 10)) + 1):
                stats = evaluate(build_corpus(max_tier=r), scan_diff)
                rows.append({"round": r, "recall": stats["recall"], "fp_rate": stats["fp_rate"],
                             "misses": len(stats["misses"]), "benchmark": stats["benchmark_n"]})
            return {"rounds": rows, "note": "完整报告请运行 harness/iterate.py"}

        registry.register(
            name="run_iteration",
            description="跑 1-10 轮递进对抗迭代（每轮 = 技术 1..r 累计），返回确定性攻击的检出率/误报率与语义基准数。评估评审引擎整体健壮性时调用。",
            parameters={
                "type": "object",
                "properties": {"rounds": {"type": "integer", "description": "轮数 1-10，默认 10"}},
                "required": [],
            },
            func=_run,
        )

    return registry


__all__ = ["build_registry", "build_corpus", "evaluate", "scan_diff"]
