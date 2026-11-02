"""命令行入口。

用法（在仓库任意位置）：
  python agents/sql-danger-adversary/src/sql_adversary_agent/cli.py --offline            # 全量 T1..T10
  python agents/sql-danger-adversary/src/sql_adversary_agent/cli.py "5" --offline        # T1..T5
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

from sql_adversary_agent.agent import load_agent

from common.llm.client import LLMError


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="代码评审对抗 Agent（防御性红队：测试 danger_scan）")
    parser.add_argument("request", nargs="?", default="", help="可选：技术级上限数字（1-10），缺省全量")
    parser.add_argument("--agent-dir", default=None, help="Agent 目录（默认自动推断）")
    parser.add_argument("--offline", action="store_true", help="离线模式：规则管线，不调用 LLM")
    parser.add_argument("--out", default=None, help="把报告写入指定文件")
    parser.add_argument("--trace", action="store_true", help="打印工具调用轨迹（LLM 模式）")
    args = parser.parse_args(argv)

    agent = load_agent(args.agent_dir)

    if args.offline:
        result = agent.offline(args.request)
        report, ok = result["report"], (result["stats"]["recall"] == 1.0 and result["stats"]["fp_rate"] == 0.0)
    else:
        try:
            result = agent.run(args.request or "对检测引擎跑一轮全量对抗测试")
        except LLMError as exc:
            print(f"[LLM 不可用] {exc}\n可先使用 --offline 离线模式，或在 config.yaml / 环境变量中配置 LLM。", file=sys.stderr)
            return 2
        report, ok = result.answer, True
        if args.trace:
            print("---- 工具调用轨迹 ----", file=sys.stderr)
            for record in result.tool_trace:
                status = "ok" if record.ok else f"失败: {record.error}"
                print(f"  {record.name}({record.arguments}) -> {status}", file=sys.stderr)

    if args.out:
        Path(args.out).write_text(report, encoding="utf-8")
        print(f"报告已写入: {args.out}")
    else:
        print(report)
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
