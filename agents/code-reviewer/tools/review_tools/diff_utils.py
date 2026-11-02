"""统一 diff 解析与文件筛选：参考 alibaba/open-code-review 的"精准文件筛选"阶段。

- 解析 `git diff` 输出：变更文件、hunk、新增行及其在新文件中的行号（行级定位基础）；
- 按可配置模式过滤：锁文件/生成物/三方库/二进制等默认不评审，但保留统计（透明可审计）。
"""
from __future__ import annotations

import fnmatch
import re

_DIFF_FILE_RE = re.compile(r"^diff --git (?:(?:a/)?(?P<a>\S+) (?:(?:b/)?(?P<b>\S+))?)", re.MULTILINE)
_HUNK_RE = re.compile(r"^@@ -\d+(?:,\d+)? \+(?P<start>\d+)(?:,(?P<len>\d+))? @@")
_BINARY_RE = re.compile(r"^Binary files ")

# 默认过滤（参考 open-code-review 文件筛选：高噪声、低价值路径不进入评审）
DEFAULT_FILTERS = [
    "*.lock", "package-lock.json", "pnpm-lock.yaml", "yarn.lock", "poetry.lock", "uv.lock",
    "go.sum", "*.min.js", "*.min.css", "*.map",
    "vendor/**", "node_modules/**", "dist/**", "build/**", "third_party/**", "thirdparty/**",
    "*.pb.go", "*_pb2.py", "*.generated.*", "*.designer.cs",
    "*.png", "*.jpg", "*.jpeg", "*.gif", "*.ico", "*.pdf", "*.woff", "*.woff2", "*.ttf", "*.eot",
    "*.jar", "*.class", "*.so", "*.dll", "*.exe", "*.bin",
]

_MAX_REVIEW_LINES = 2000  # 单文件超过该 diff 行数则打"过大拆分"标记而非静默跳过（透明化）


def _is_filtered(path: str, filters: list[str]) -> bool:
    return any(fnmatch.fnmatch(path, pat) for pat in filters)


def parse_diff(diff_text: str, filters: list[str] | None = None) -> dict:
    """解析统一 diff，返回 {files, filtered, stats}。

    files: [{path, added_lines, removed_lines, is_new, is_binary, too_large,
             hunks: [{start, lines: [(new_line_no, text, kind)}]}]
    """
    filters = DEFAULT_FILTERS if filters is None else filters
    if not diff_text or not diff_text.strip():
        return {"files": [], "filtered": [], "stats": {"total": 0, "reviewed": 0, "filtered": 0}}

    sections = re.split(r"(?=^diff --git )", diff_text, flags=re.MULTILINE)
    files, filtered = [], []
    for sec in sections:
        m = _DIFF_FILE_RE.match(sec)
        if not m:
            continue
        path = (m.group("b") or m.group("a") or "").strip()
        path = path.lstrip("b/").lstrip("a/") if path.startswith(("a/", "b/")) else path
        # 解析 +++ 行优先（更可靠）
        pm = re.search(r"^\+\+\+ (?:b/)?(.+)$", sec, re.MULTILINE)
        if pm:
            path = pm.group(1).strip()
        if path == "/dev/null":
            continue
        entry = {
            "path": path,
            "is_binary": bool(_BINARY_RE.search(sec)),
            "is_new": bool(re.search(r"^--- /dev/null", sec, re.MULTILINE)),
            "hunks": [],
            "added_lines": 0,
            "removed_lines": 0,
        }
        cur, cur_line = None, None
        for line in sec.splitlines():
            if line.startswith("@@"):
                hm = _HUNK_RE.match(line)
                if hm:
                    cur = {"start": int(hm.group("start")), "lines": []}
                    entry["hunks"].append(cur)
                    cur_line = cur["start"]
                continue
            if cur is None or line.startswith(("diff --git", "+++", "---")):
                continue
            if line.startswith("+"):
                cur["lines"].append({"line": cur_line, "text": line[1:], "kind": "add"})
                entry["added_lines"] += 1
                cur_line += 1
            elif line.startswith("-"):
                cur["lines"].append({"line": None, "text": line[1:], "kind": "del"})
                entry["removed_lines"] += 1
            else:
                cur_line += 1
        entry["too_large"] = entry["added_lines"] > _MAX_REVIEW_LINES
        if entry["is_binary"] or _is_filtered(path, filters):
            entry["reason"] = "binary" if entry["is_binary"] else "filtered"
            filtered.append(entry)
        else:
            files.append(entry)

    return {
        "files": files,
        "filtered": filtered,
        "stats": {
            "total": len(files) + len(filtered),
            "reviewed": len(files),
            "filtered": len(filtered),
            "added": sum(f["added_lines"] for f in files),
            "removed": sum(f["removed_lines"] for f in files),
        },
    }


def added_lines(file_entry: dict) -> list[dict]:
    """展开某文件全部新增行（带新文件行号）。"""
    out = []
    for h in file_entry["hunks"]:
        out.extend(l for l in h["lines"] if l["kind"] == "add")
    return out


def file_content_lines(file_entry: dict, max_context: int = 3) -> dict[int, str]:
    """从 diff 还原可见的新文件行（含少量上下文），供静态检查定位。"""
    visible: dict[int, str] = {}
    for h in file_entry["hunks"]:
        ln = h["start"]
        for l in h["lines"]:
            if l["kind"] == "add":
                visible[ln] = l["text"]
                ln += 1
            elif l["kind"] == "del":
                continue
            else:
                visible[ln] = l["text"]
                ln += 1
    return visible
