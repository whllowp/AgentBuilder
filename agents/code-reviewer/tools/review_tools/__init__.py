"""code-reviewer 的 Agent 工具集与注册入口（参考 alibaba/open-code-review 设计）。"""
from __future__ import annotations

from pathlib import Path

from common.agentcore import ToolRegistry
from common.tools.knowledge_search import search

from .bundle import build_bundles
from .diff_utils import parse_diff
from .rule_engine import DEFAULT_RULES, load_user_rules, match_rules
from .static_scan import group_report, scan_diff


def review_pipeline(diff_text: str, repo_root: str | Path | None = None, keep_low: bool = False) -> dict:
    """确定性管线：文件筛选 -> 智能打包 -> 规则匹配 -> 静态扫描 -> 分组报告。"""
    parsed = parse_diff(diff_text)
    bundles = build_bundles(parsed["files"])
    rules = {f["path"]: match_rules(f["path"], repo_root=repo_root) for f in parsed["files"]}
    comments = scan_diff(parsed)
    report = group_report(comments, keep_low=keep_low)
    return {
        "ok": bool(parsed["files"]) or bool(parsed["filtered"]),
        "stats": parsed["stats"],
        "filtered_files": [f["path"] for f in parsed["filtered"]],
        "bundles": [{"id": b["id"], "files": b["files"], "added_lines": b["added_lines"]} for b in bundles],
        "rules": {p: r["rules"] for p, r in rules.items() if r["rules"]},
        "comments": report["kept"],
        "dropped_low": report["dropped_low"],
        "summary": (
            f"文件 {parsed['stats']['total']}（评审 {parsed['stats']['reviewed']} / 过滤 {parsed['stats']['filtered']}），"
            f"打包 {len(bundles)} 个评审单元，确定性发现 {len(report['kept'])} 条"
            f"（另忽略疑似误报 low {len(report['dropped_low'])} 条）"
        ),
    }


def build_registry(agent_dir: str | Path, enabled: dict[str, bool] | None = None) -> ToolRegistry:
    agent_dir = Path(agent_dir)
    enabled = enabled or {}
    registry = ToolRegistry()

    if enabled.get("inspect_diff", True):

        def _inspect(diff_text: str, repo_root: str = "") -> dict:
            parsed = parse_diff(diff_text)
            bundles = build_bundles(parsed["files"])
            user_rules, rule_source = load_user_rules(repo_root or None)
            return {
                "stats": parsed["stats"],
                "filtered_files": [f["path"] for f in parsed["filtered"]],
                "review_files": [f["path"] for f in parsed["files"]],
                "bundles": [{"id": b["id"], "files": b["files"], "added_lines": b["added_lines"]} for b in bundles],
                "rule_source": rule_source,
                "user_rules_count": len(user_rules),
                "hint": "文件筛选与打包已确定；下一步对每个文件 match_rules 后交 static_scan / LLM 评审",
            }

        registry.register(
            name="inspect_diff",
            description="解析 git diff：精准文件筛选（锁文件/生成物/三方库默认过滤并留统计）、智能打包（实现-测试配对、同目录聚合）、规则来源（rule.json 覆盖/合并）。评审任何 diff 的第一步。",
            parameters={
                "type": "object",
                "properties": {
                    "diff_text": {"type": "string", "description": "git diff 的统一 diff 文本"},
                    "repo_root": {"type": "string", "description": "可选：仓库根目录（用于发现 .opencodereview/rule.json）"},
                },
                "required": ["diff_text"],
            },
            func=_inspect,
        )

    if enabled.get("static_scan", True):

        def _scan(diff_text: str, keep_low: bool = False) -> dict:
            parsed = parse_diff(diff_text)
            comments = scan_diff(parsed)
            report = group_report(comments, keep_low=keep_low)
            return {
                "comments": report["kept"],
                "dropped_low": report["dropped_low"],
                "by_category": report["by_category"],
                "note": "确定性检查（凭据/冲突标记/调试语句/语言专项）；low 项默认按惯例忽略备查",
            }

        registry.register(
            name="static_scan",
            description="对 diff 新增行做确定性检查并输出结构化评论（path/行号/category/severity/suggestion）：硬编码凭据(critical)、冲突标记(critical)、debugger、裸 except/吞异常、Executors 线程池、static SimpleDateFormat、可变默认参数等。LLM 评审前先跑，避免重复报告可机检问题。",
            parameters={
                "type": "object",
                "properties": {
                    "diff_text": {"type": "string", "description": "统一 diff 文本"},
                    "keep_low": {"type": "boolean", "description": "true 则保留 low 级（默认按 open-code-review 惯例丢弃疑似误报 low）"},
                },
                "required": ["diff_text"],
            },
            func=_scan,
        )

    if enabled.get("match_rules", True):

        def _match(path: str, repo_root: str = "") -> dict:
            return match_rules(path, repo_root=repo_root or None)

        registry.register(
            name="match_rules",
            description="按文件路径匹配评审规则（glob 模板）：内置默认规则（Java/JS/TS/Py/Go/SQL/测试/配置）与 .opencodereview/rule.json 用户规则（默认替换内置，merge_system_rule=true 合并）。LLM 评审某文件前取其专属规则文本聚焦注意力。",
            parameters={
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "文件路径（相对仓库根）"},
                    "repo_root": {"type": "string", "description": "可选：仓库根目录"},
                },
                "required": ["path"],
            },
            func=_match,
        )

    if enabled.get("knowledge_search", True):
        knowledge_dir = agent_dir / "knowledge"

        def _search(query: str, top_k: int = 2) -> dict:
            results = search(knowledge_dir, query, top_k)
            return {"results": results, "hint": "知识库摘录；可换关键词：管线 打包 规则 severity 评论结构" if results else "未命中"}

        registry.register(
            name="knowledge_search",
            description="检索代码评审知识库：open-code-review 式确定性管线（筛选/打包/规则匹配/定位/反思）、评论结构与严重度语义、默认规则要点。涉及流程或输出格式问题时先查。",
            parameters={
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "关键词，如: 打包 配对、severity low 丢弃、rule.json merge"},
                    "top_k": {"type": "integer", "description": "返回条数，默认 2"},
                },
                "required": ["query"],
            },
            func=_search,
        )

    return registry


__all__ = ["build_registry", "review_pipeline", "parse_diff", "build_bundles", "match_rules", "scan_diff", "group_report", "DEFAULT_RULES"]
