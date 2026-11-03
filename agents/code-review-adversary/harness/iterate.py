"""10 轮 commit 对抗迭代 harness：红队（commit_attack）vs code-reviewer 的 static_scan。

用法：
  python agents/code-review-adversary/harness/iterate.py --rounds 10 \
      --out agents/code-review-adversary/reports/iteration-report.md

- deterministic 攻击：自动判定（检出率/误报率，low 级按报告策略豁免）；
- llm-benchmark 攻击：导出为 reports/llm-benchmark.md（语义 bug 是 LLM 评审的责任区，不自动判定——诚实度量）。
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

HARNESS_DIR = Path(__file__).resolve().parent
ADVERSARY_DIR = HARNESS_DIR.parent
REPO_ROOT = ADVERSARY_DIR.parent.parent
REVIEWER_TOOLS = REPO_ROOT / "agents" / "code-reviewer" / "tools"

for p in (str(REPO_ROOT), str(REVIEWER_TOOLS), str(ADVERSARY_DIR / "tools")):
    if p not in sys.path:
        sys.path.insert(0, p)

from cr_adversary_tools.commit_attack import build_corpus, evaluate  # noqa: E402
from review_tools.static_scan import scan_diff  # noqa: E402

_TIER_NAME = {1: "明文缺陷基线", 2: "密钥伪装", 3: "调试语句伪装", 4: "反模式变体", 5: "大 diff 掩埋",
              6: "过滤/路径对抗", 7: "误报攻击", 8: "多文件混合", 9: "语义 bug 基准", 10: "高级语义基准"}


def run(rounds: int = 10, log_path: Path | None = None) -> dict:
    hardening = []
    if log_path and log_path.exists():
        try:
            hardening = json.loads(log_path.read_text(encoding="utf-8"))
        except Exception:
            hardening = []
    rows = []
    for r in range(1, rounds + 1):
        stats = evaluate(build_corpus(max_tier=r), scan_diff)
        notes = "；".join(h.get("note", "") for h in hardening if h.get("round") == r)
        rows.append({"round": r, "recall": stats["recall"], "fp_rate": stats["fp_rate"],
                     "misses": len(stats["misses"]), "benchmark": stats["benchmark_n"], "hardening": notes,
                     "_misses": stats["misses"], "_benchmark": [b for b in stats["results"] if b["kind"] == "llm-benchmark"]})
    det_ok = all(row["recall"] == 1.0 and row["fp_rate"] == 0.0 for row in rows)
    return {"rounds": rows, "passed": det_ok}


def render(data: dict, rounds: int) -> str:
    lines = ["# code-reviewer 对抗迭代报告（10 轮）", ""]
    lines.append("红队：`agents/code-review-adversary`（commit 攻击技术 T1~T10）")
    lines.append("被测：`agents/code-reviewer/tools/review_tools/static_scan.py`（确定性引擎；LLM 语义层另见基准集）")
    lines.append("")
    verdict = "✅ deterministic 攻击全轮 100%/0%" if data["passed"] else "❌ 存在确定性缺口"
    lines.append(f"## 结论\n- {verdict}")
    last = data["rounds"][-1]
    lines.append(f"- 终态：确定性攻击检出率 {last['recall']:.0%}、误报率 {last['fp_rate']:.0%}；"
                 f"语义基准 {last['benchmark']} 条导出至 llm-benchmark.md（由 LLM 模式消化，不自动判定）")
    lines.append("- 开发迭代史：红队曾打穿 3 处（yaml 未加引号密钥、多行链式 Executors、测试路径假凭据误报），"
                 "已回补：SECRET_UNQUOTED_RE、跨行 Executors 检测、测试路径凭据降 low（详见 hardening-log.json）")
    lines.append("")
    lines.append("## 逐轮结果\n")
    lines.append("| 轮 | 技术 | 检出率 | 误报率 | 打穿 | 语义基准 | 本轮加固 |")
    lines.append("| --- | --- | --- | --- | --- | --- | --- |")
    for r in data["rounds"]:
        lines.append(f"| {r['round']} | {_TIER_NAME.get(r['round'], '')} | {r['recall']:.0%} "
                     f"| {r['fp_rate']:.0%} | {r['misses']} | {r['benchmark']} | {r['hardening'] or '—'} |")
    lines.append("")
    misses = [m for r in data["rounds"] for m in r["_misses"]]
    if misses:
        lines.append("## 打穿明细\n")
        for m in misses:
            lines.append(f"- `{m['id']}`（{m['technique']}，期望 {m['expect']}，实际 {m['verdict']}）：{m['payload'][:80]}…")
        lines.append("")
    lines.append("## 边界声明\n")
    lines.append("- deterministic 攻击针对可机检项（凭据/调试/反模式/掩埋）——自动判定；")
    lines.append("- 语义 bug（差一错误、并发、泄漏、注入）是 LLM 评审的责任区，导出为基准集不冒充通过。")
    lines.append("")
    lines.append("## 复现\n```bash\npython agents/code-review-adversary/harness/iterate.py --rounds 10\n```")
    return "\n".join(lines)


def render_benchmark(data: dict) -> str:
    lines = ["# LLM 语义评审基准集（红队导出）", "",
             "以下 diff 各含一个语义缺陷，用于 LLM 模式评审加压：模型应定位并给出 category/severity。", ""]
    for r in data["rounds"]:
        for b in r["_benchmark"]:
            lines.append(f"## {b['id']}（{b['technique']}）")
            lines.append("```diff")
            lines.append(b["payload"].rstrip())
            lines.append("```")
            lines.append("")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--rounds", type=int, default=10)
    ap.add_argument("--out", default=str(ADVERSARY_DIR / "reports" / "iteration-report.md"))
    args = ap.parse_args(argv)

    log_path = ADVERSARY_DIR / "reports" / "hardening-log.json"
    data = run(rounds=args.rounds, log_path=log_path)
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(render(data, args.rounds), encoding="utf-8")
    (out.parent / "llm-benchmark.md").write_text(render_benchmark(data), encoding="utf-8")

    last = data["rounds"][-1]
    print(f"最终轮：检出率 {last['recall']:.0%}，误报率 {last['fp_rate']:.0%}，打穿 {last['misses']}，"
          f"语义基准 {last['benchmark']} → {'PASS' if data['passed'] else 'FAIL'}")
    print(f"报告: {out} | 基准: {out.parent / 'llm-benchmark.md'}")
    return 0 if data["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
