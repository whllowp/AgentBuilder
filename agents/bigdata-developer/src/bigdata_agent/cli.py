"""命令行入口。

用法：
  python agents/bigdata-developer/src/bigdata_agent/cli.py "帮我写一个订单拉链表" --offline
  cat job.sql | python agents/bigdata-developer/src/bigdata_agent/cli.py - --offline
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

try:
    from . import _bootstrap
except ImportError:
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import _bootstrap

from bigdata_agent.agent import load_agent

from common.llm.client import LLMError


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="大数据开发 Agent（ETL 生成与审查）")
    parser.add_argument("request", help="需求描述，或待审查的代码（- 从 stdin 读取）")
    parser.add_argument("--agent-dir", default=None)
    parser.add_argument("--offline", action="store_true")
    parser.add_argument("--out", default=None)
    parser.add_argument("--trace", action="store_true")
    args = parser.parse_args(argv)

    text = sys.stdin.read() if args.request == "-" else args.request
    agent = load_agent(args.agent_dir)
    if args.offline:
        result = agent.offline(text)
        report = result["report"]
    else:
        try:
            result = agent.run(text)
        except LLMError as exc:
            print(f"[LLM 不可用] {exc}\n可先使用 --offline 离线模式。", file=sys.stderr)
            return 2
        report = result.answer
        if args.trace:
            print("---- 工具调用轨迹 ----", file=sys.stderr)
            for record in result.tool_trace:
                print(f"  {record.name}({record.arguments}) -> {'ok' if record.ok else record.error}", file=sys.stderr)

    if args.out:
        Path(args.out).write_text(report, encoding="utf-8")
        print(f"报告已写入: {args.out}")
    else:
        print(report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
