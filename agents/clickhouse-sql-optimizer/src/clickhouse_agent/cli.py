"""命令行入口。

用法（在仓库任意位置）：
  python agents/clickhouse-sql-optimizer/src/clickhouse_agent/cli.py "SELECT * FROM t" --offline
  python agents/clickhouse-sql-optimizer/src/clickhouse_agent/cli.py "需求 + SQL" --out report.md --trace
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

from clickhouse_agent.agent import load_agent

from common.llm.client import LLMError


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="ClickHouse SQL 优化 Agent（审查 / DDL 评估 / 建表生成 / EXPLAIN 解读）")
    parser.add_argument("request", help="优化需求：SQL、DDL、EXPLAIN 输出或建表场景描述")
    parser.add_argument("--agent-dir", default=None, help="Agent 目录（默认自动推断）")
    parser.add_argument("--offline", action="store_true", help="离线模式：规则管线，不调用 LLM")
    parser.add_argument("--out", default=None, help="把报告写入指定文件")
    parser.add_argument("--trace", action="store_true", help="打印工具调用轨迹（LLM 模式）")
    args = parser.parse_args(argv)

    agent = load_agent(args.agent_dir)

    if args.offline:
        result = agent.offline(args.request)
        report = result["report"]
    else:
        try:
            result = agent.run(args.request)
        except LLMError as exc:
            print(f"[LLM 不可用] {exc}\n可先使用 --offline 离线模式，或在 config.yaml / 环境变量中配置 LLM。", file=sys.stderr)
            return 2
        report = result.answer
        if args.trace:
            print("---- 工具调用轨迹 ----", file=sys.stderr)
            for record in result.tool_trace:
                status = "ok" if record.ok else f"失败: {record.error}"
                print(f"  {record.name}({record.arguments}) -> {status}", file=sys.stderr)
            print(f"  迭代轮数: {result.iterations}", file=sys.stderr)

    if args.out:
        Path(args.out).write_text(report, encoding="utf-8")
        print(f"报告已写入: {args.out}")
    else:
        print(report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
