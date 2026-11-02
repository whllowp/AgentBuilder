"""命令行入口。

用法（在仓库任意位置）：
  git diff | python agents/code-reviewer/src/code_review_agent/cli.py - --offline
  python agents/code-reviewer/src/code_review_agent/cli.py diff.txt --offline --out report.md
  python agents/code-reviewer/src/code_review_agent/cli.py diff.txt --offline --format json
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

try:
    from . import _bootstrap  # 包方式导入
except ImportError:
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import _bootstrap  # 脚本方式运行

from code_review_agent.agent import load_agent

from common.llm.client import LLMError


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="代码评审 Agent（参考 alibaba/open-code-review：管线+行级评论）")
    parser.add_argument("diff", help="统一 diff 文本文件路径；传 - 从 stdin 读取")
    parser.add_argument("--agent-dir", default=None, help="Agent 目录（默认自动推断）")
    parser.add_argument("--offline", action="store_true", help="离线模式：确定性管线，不调用 LLM")
    parser.add_argument("--format", default="text", choices=["text", "json"], help="输出格式")
    parser.add_argument("--keep-low", action="store_true", help="保留 low 级意见（默认丢弃备查）")
    parser.add_argument("--out", default=None, help="把结果写入指定文件")
    parser.add_argument("--trace", action="store_true", help="打印工具调用轨迹（LLM 模式）")
    args = parser.parse_args(argv)

    diff_text = sys.stdin.read() if args.diff == "-" else Path(args.diff).read_text(encoding="utf-8")
    agent = load_agent(args.agent_dir)
    if args.keep_low:
        agent.config.keep_low = True

    if args.offline:
        result = agent.offline(diff_text)
        output = json.dumps(
            {k: v for k, v in result.items() if k != "report"}, ensure_ascii=False, indent=1
        ) if args.format == "json" else result["report"]
        blocked = any(c["severity"] == "critical" for c in result.get("comments", []))
    else:
        try:
            result = agent.run(diff_text)
        except LLMError as exc:
            print(f"[LLM 不可用] {exc}\n可先使用 --offline 确定性管线，或在 config.yaml / 环境变量中配置 LLM。", file=sys.stderr)
            return 2
        output = result.answer
        blocked = False
        if args.trace:
            print("---- 工具调用轨迹 ----", file=sys.stderr)
            for record in result.tool_trace:
                status = "ok" if record.ok else f"失败: {record.error}"
                print(f"  {record.name}({record.arguments}) -> {status}", file=sys.stderr)

    if args.out:
        Path(args.out).write_text(output, encoding="utf-8")
        print(f"结果已写入: {args.out}")
    else:
        print(output)
    return 1 if blocked else 0  # critical 时非零退出，可接 CI


if __name__ == "__main__":
    raise SystemExit(main())
