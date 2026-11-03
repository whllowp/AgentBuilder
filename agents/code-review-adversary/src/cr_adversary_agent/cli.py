"""命令行入口。

用法：
  python agents/code-review-adversary/src/cr_adversary_agent/cli.py --offline          # 全量 T1..T10
  python agents/code-review-adversary/src/cr_adversary_agent/cli.py "4" --offline      # T1..T4
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

try:
    from . import _bootstrap  # 包方式导入
except ImportError:
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import _bootstrap  # 脚本方式运行

from cr_adversary_agent.agent import load_agent

from common.llm.client import LLMError


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="commit 对抗红队 Agent（测试 code-reviewer 引擎）")
    parser.add_argument("request", nargs="?", default="", help="可选：技术级上限（1-10），缺省全量")
    parser.add_argument("--agent-dir", default=None)
    parser.add_argument("--offline", action="store_true")
    parser.add_argument("--out", default=None)
    parser.add_argument("--trace", action="store_true")
    args = parser.parse_args(argv)

    agent = load_agent(args.agent_dir)
    if args.offline:
        result = agent.offline(args.request)
        report, ok = result["report"], (result["stats"]["recall"] == 1.0 and result["stats"]["fp_rate"] == 0.0)
    else:
        try:
            result = agent.run(args.request or "对 code-reviewer 跑一轮全量对抗")
        except LLMError as exc:
            print(f"[LLM 不可用] {exc}\n可先使用 --offline 离线模式。", file=sys.stderr)
            return 2
        report, ok = result.answer, True
        if args.trace:
            print("---- 工具调用轨迹 ----", file=sys.stderr)
            for record in result.tool_trace:
                print(f"  {record.name}({record.arguments}) -> {'ok' if record.ok else record.error}", file=sys.stderr)

    if args.out:
        Path(args.out).write_text(report, encoding="utf-8")
        print(f"报告已写入: {args.out}")
    else:
        print(report)
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
