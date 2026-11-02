"""命令行入口。

用法（在仓库任意位置）：
  python agents/sql-danger-reviewer/src/sql_danger_agent/cli.py "DELETE FROM orders" --offline
  cat script.sql | python agents/sql-danger-reviewer/src/sql_danger_agent/cli.py - --offline --out report.md
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

from sql_danger_agent.agent import load_agent

from common.llm.client import LLMError


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="高危操作代码检验 Agent（DGR-1xx~5xx）")
    parser.add_argument("code", help="待评审的 SQL/代码文本；传 - 从 stdin 读取")
    parser.add_argument("--agent-dir", default=None, help="Agent 目录（默认自动推断）")
    parser.add_argument("--offline", action="store_true", help="离线模式：规则管线，不调用 LLM")
    parser.add_argument("--out", default=None, help="把报告写入指定文件")
    parser.add_argument("--trace", action="store_true", help="打印工具调用轨迹（LLM 模式）")
    args = parser.parse_args(argv)

    code = sys.stdin.read() if args.code == "-" else args.code
    agent = load_agent(args.agent_dir)

    if args.offline:
        result = agent.offline(code)
        report, verdict = result["report"], result["scan"].get("verdict")
    else:
        try:
            result = agent.run(code)
        except LLMError as exc:
            print(f"[LLM 不可用] {exc}\n可先使用 --offline 离线模式，或在 config.yaml / 环境变量中配置 LLM。", file=sys.stderr)
            return 2
        report = result.answer
        verdict = None
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
    return 0 if verdict != "block" else 1  # block 时以非零码退出，便于 CI 拦截


if __name__ == "__main__":
    raise SystemExit(main())
