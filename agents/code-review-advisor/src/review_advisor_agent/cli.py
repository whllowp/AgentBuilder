"""命令行入口。

用法：
  python agents/code-review-advisor/src/review_advisor_agent/cli.py '[{"title":..,"severity":..}]' --offline
  echo "草稿文本" | python agents/code-review-advisor/src/review_advisor_agent/cli.py - --offline
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

from review_advisor_agent.agent import load_agent

from common.llm.client import LLMError


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="代码评审意见顾问（润色 + 语气检查）")
    parser.add_argument("input", help="JSON 发现数组（润色）或意见草稿文本（语气检查）；- 从 stdin 读取")
    parser.add_argument("--agent-dir", default=None)
    parser.add_argument("--offline", action="store_true", help="离线模式：规则管线，不调用 LLM")
    parser.add_argument("--out", default=None, help="把报告写入指定文件")
    parser.add_argument("--trace", action="store_true", help="打印工具调用轨迹（LLM 模式）")
    args = parser.parse_args(argv)

    text = sys.stdin.read() if args.input == "-" else args.input
    agent = load_agent(args.agent_dir)

    if args.offline:
        result = agent.offline(text)
        report = result["report"]
        ok = result["tone"]["ok"]
    else:
        try:
            result = agent.run(text)
        except LLMError as exc:
            print(f"[LLM 不可用] {exc}\n可先使用 --offline 离线模式。", file=sys.stderr)
            return 2
        report = result.answer
        ok = True
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
