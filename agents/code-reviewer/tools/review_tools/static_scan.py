"""确定性静态扫描：对 diff 新增行做高信号检查，输出 open-code-review 兼容的结构化评论。

评论结构（与其一致）：
{path, content, start_line, end_line, category, severity, existing_code?, suggestion_code?, thinking?}
category ∈ bug/security/performance/maintainability/test/style/documentation/other
severity ∈ critical/high/medium/low
"""
from __future__ import annotations

import re

from .diff_utils import added_lines

CATEGORY = ("bug", "security", "performance", "maintainability", "test", "style", "documentation", "other")
SEVERITY = ("critical", "high", "medium", "low")
_SEV_ORDER = {s: i for i, s in enumerate(SEVERITY)}

_SECRET_RE = re.compile(
    r"[\w-]*(password|passwd|secret|api[_-]?key|apikey|access[_-]?key|token|private[_-]?key)[\w-]*\s*[:=]\s*['\"][^'\"\s]{8,}",
    re.IGNORECASE,
)
_CONFLICT_RE = re.compile(r"^(<<<<<<<|=======$|>>>>>>>)")
_DEBUGGER_RE = re.compile(r"\bdebugger\b\s*;?")
_CONSOLE_RE = re.compile(r"\bconsole\.(log|debug)\s*\(")
_LOOSE_EQ_RE = re.compile(r"[^=!<>]==[^=]|[^!]!=[^=]")
_VAR_RE = re.compile(r"^\s*var\s+\w+")
_PRINT_RE = re.compile(r"^\s*print\s*\(")
_BARE_EXCEPT_RE = re.compile(r"^\s*except\s*:")
_EXCEPT_BROAD_RE = re.compile(r"^\s*except\s+(Exception|BaseException)\s*(as\s+\w+)?\s*:")
_PASS_RE = re.compile(r"^\s*pass\s*$")
_MUTABLE_DEF_RE = re.compile(r"def\s+\w+\s*\([^)]*=\s*(\[\]|\{\}|set\(\))")
_EXECUTORS_RE = re.compile(r"\bExecutors\.new(Fixed|Cached|Single|Scheduled)ThreadPool")
_STATIC_SDF_RE = re.compile(r"static[^;\n]*SimpleDateFormat")
_STACK_TRACE_RE = re.compile(r"\.printStackTrace\s*\(")
_EMPTY_CATCH_RE = re.compile(r"catch\s*\([^)]*\)\s*\{\s*\}")
_TODO_RE = re.compile(r"\b(TODO|FIXME)\b")
_GO_IGNORE_ERR_RE = re.compile(r"^\s*_\s*=\s*err\b")
_ANY_RE = re.compile(r":\s*any\b")


def _comment(path, line, category, severity, content, existing="", suggestion="", thinking=""):
    return {
        "path": path,
        "content": content,
        "start_line": line if line is not None else 0,
        "end_line": line if line is not None else 0,
        "category": category,
        "severity": severity,
        "existing_code": existing[:200],
        "suggestion_code": suggestion,
        "thinking": thinking,
    }


def scan_file(file_entry: dict) -> list[dict]:
    """对一个 diff 文件的新增行做确定性检查（只评审变更，不翻旧账）。"""
    path = file_entry["path"]
    comments: list[dict] = []
    adds = added_lines(file_entry)
    src = "\n".join(l["text"] for l in adds)

    if file_entry.get("too_large"):
        comments.append(_comment(
            path, 1, "maintainability", "medium",
            f"单文件 diff 新增 {file_entry['added_lines']} 行，超过 {2000} 行评审上限，建议拆分 PR/提交后再评审",
            existing="（大 diff）", thinking="large-diff guard",
        ))

    for i, l in enumerate(adds):
        text, ln = l["text"], l["line"]
        nxt = adds[i + 1]["text"] if i + 1 < len(adds) else ""

        if _SECRET_RE.search(text):
            comments.append(_comment(
                path, ln, "security", "critical",
                "疑似硬编码凭据：新增行包含 password/secret/token/api_key 等敏感赋值，凭据必须走密钥管理，禁止入库",
                existing=text, suggestion="<从环境变量/密钥服务读取，并轮换已泄露凭据>",
                thinking="secret-pattern",
            ))
        if _CONFLICT_RE.match(text.strip()):
            comments.append(_comment(
                path, ln, "bug", "critical", "存在未解决的合并冲突标记", existing=text,
                suggestion="解决冲突后重新提交", thinking="conflict-marker",
            ))
        if _DEBUGGER_RE.search(text):
            comments.append(_comment(
                path, ln, "bug", "high", "调试语句 debugger 不得合入", existing=text,
                suggestion="删除该行", thinking="debugger",
            ))
        if _CONSOLE_RE.search(text) and "__tests__" not in path and "test" not in path.lower():
            comments.append(_comment(
                path, ln, "style", "low", "console.log/debug 调试输出不应合入生产代码", existing=text,
                suggestion="删除或替换为正式日志（含级别与上下文）", thinking="console-log",
            ))
        if path.endswith((".js", ".jsx", ".ts", ".tsx")):
            if _LOOSE_EQ_RE.search(text):
                comments.append(_comment(
                    path, ln, "bug", "low", "使用宽松相等（==/!=），应使用 ===/!== 避免隐式类型转换", existing=text,
                    suggestion=text.replace("==", "===").replace("!=", "!==") if "==" in text else "",
                    thinking="loose-eq",
                ))
            if _VAR_RE.match(text):
                comments.append(_comment(
                    path, ln, "style", "low", "禁用 var，使用 const/let", existing=text,
                    suggestion=text.replace("var", "const", 1), thinking="var-decl",
                ))
            if _ANY_RE.search(text):
                comments.append(_comment(
                    path, ln, "maintainability", "low", "TS 新代码引入 any，优先具体类型", existing=text,
                    thinking="ts-any",
                ))
        if path.endswith(".py") and "test" not in path.lower():
            if _BARE_EXCEPT_RE.match(text):
                comments.append(_comment(
                    path, ln, "bug", "high", "裸 except: 会吞掉 KeyboardInterrupt/SystemExit，必须捕获具体异常", existing=text,
                    suggestion="except SpecificError as e: ...", thinking="bare-except",
                ))
            elif _EXCEPT_BROAD_RE.match(text) and _PASS_RE.match(nxt):
                comments.append(_comment(
                    path, ln, "bug", "high", "except Exception 后直接 pass 吞异常，至少记录日志或重新抛出", existing=f"{text} / {nxt}",
                    suggestion="logging.exception(...) 或 raise", thinking="swallowed-exception",
                ))
            if _MUTABLE_DEF_RE.search(text):
                comments.append(_comment(
                    path, ln, "bug", "medium", "可变默认参数（=[]/={}）在多次调用间共享状态", existing=text,
                    suggestion="=None 然后函数体内初始化", thinking="mutable-default",
                ))
            if _PRINT_RE.match(text):
                comments.append(_comment(
                    path, ln, "style", "low", "print 调试输出不应合入，使用 logging", existing=text,
                    thinking="print-debug",
                ))
        if path.endswith(".java"):
            if _EXECUTORS_RE.search(text):
                comments.append(_comment(
                    path, ln, "performance", "medium",
                    "使用 Executors 创建线程池（阿里手册禁止）：队列无界可致 OOM，应手动 new ThreadPoolExecutor 并明确参数",
                    existing=text, suggestion="new ThreadPoolExecutor(core, max, keepAlive, unit, new LinkedBlockingQueue<>(cap), threadFactory, new ThreadPoolExecutor.CallerRunsPolicy())",
                    thinking="p3c-thread-pool",
                ))
            if _STATIC_SDF_RE.search(text):
                comments.append(_comment(
                    path, ln, "bug", "medium", "static SimpleDateFormat 线程不安全，并发下日期错乱（阿里手册）", existing=text,
                    suggestion="使用 ThreadLocal<SimpleDateFormat> 或 java.time.DateTimeFormatter", thinking="p3c-sdf",
                ))
            if _STACK_TRACE_RE.search(text):
                comments.append(_comment(
                    path, ln, "bug", "medium", "e.printStackTrace() 不入日志体系，应使用日志框架记录", existing=text,
                    suggestion="log.error(\"msg\", e)", thinking="p3c-printstacktrace",
                ))
            if _EMPTY_CATCH_RE.search(text):
                comments.append(_comment(
                    path, ln, "bug", "high", "空 catch 块吞异常，需记录或处理", existing=text, thinking="empty-catch",
                ))
        if path.endswith(".go") and _GO_IGNORE_ERR_RE.match(text):
            comments.append(_comment(
                path, ln, "bug", "low", "显式忽略 error 返回值，需注释原因或处理", existing=text, thinking="go-ignore-err",
            ))
        if _TODO_RE.search(text):
            comments.append(_comment(
                path, ln, "maintainability", "low", "新增 TODO/FIXME 需带负责人与工单（如 TODO(owner): xxx #工单号）", existing=text,
                suggestion="TODO(owner): 描述 #工单号", thinking="todo-owner",
            ))

    # 去重（同一行同一 thinking 只报一次）
    seen, uniq = set(), []
    for c in comments:
        key = (c["path"], c["start_line"], c["thinking"], c["content"][:40])
        if key not in seen:
            seen.add(key)
            uniq.append(c)
    return uniq


def scan_diff(parsed: dict) -> list[dict]:
    """对 parse_diff 结果的全部待评审文件扫描，返回按 severity 排序的评论列表。"""
    comments: list[dict] = []
    for f in parsed.get("files", []):
        comments.extend(scan_file(f))
    comments.sort(key=lambda c: (_SEV_ORDER.get(c["severity"], 9), c["path"], c["start_line"]))
    return comments


def group_report(comments: list[dict], keep_low: bool = False) -> dict:
    """按 open-code-review 报告策略：按严重度分组；默认丢弃疑似误报的 low 项（单列备查）。"""
    kept = [c for c in comments if keep_low or c["severity"] != "low"]
    dropped = [c for c in comments if c["severity"] == "low"] if not keep_low else []
    by_sev: dict[str, list[dict]] = {s: [] for s in SEVERITY}
    for c in kept:
        by_sev.setdefault(c["severity"], []).append(c)
    by_cat: dict[str, int] = {}
    for c in kept:
        by_cat[c["category"]] = by_cat.get(c["category"], 0) + 1
    return {"kept": kept, "dropped_low": dropped, "by_severity": {k: v for k, v in by_sev.items() if v}, "by_category": by_cat}
