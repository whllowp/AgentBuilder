"""命令行入口。

用法：
  python agents/perf-capacity-planner/src/capacity_agent/cli.py "ClickHouse 日增 2 亿行，行宽 200B，保留 90 天，双副本" --offline
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

from capacity_agent.agent import load_agent

from common.llm.client import LLMError


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="性能容量规划 Agent（CK/Kafka/Flink/通用）")
    parser.add_argument("request", help="容量需求描述")
    parser.add_argument("--agent-dir", default=None)
    parser.add_argument("--offline", action="store_true")
    parser.add_argument("--out", default=None)
    parser.add_argument("--trace", action="store_true")
    args = parser.parse_args(argv)

    agent = load_agent(args.agent_dir)
    if args.offline:
        result = agent.offline(args.request)
        report = result["report"]
    else:
        try:
            result = agent.run(args.request)
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
