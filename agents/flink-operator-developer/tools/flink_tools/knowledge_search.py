"""知识库检索工具：对 knowledge/ 目录下的 Markdown 做轻量关键词打分与摘录。

注：2026-11 后该实现已下沉为通用能力 common/tools/knowledge_search.py，本文件按原文恢复保留。
"""
from __future__ import annotations

import re
from pathlib import Path

_FRONTMATTER_RE = re.compile(r"\A---\s*\n(.*?)\n---\s*\n", re.DOTALL)
_META_KV_RE = re.compile(r"^(\w+):\s*(.+)$", re.MULTILINE)


def _parse(doc: str) -> tuple[dict, str]:
    meta = {}
    body = doc
    m = _FRONTMATTER_RE.match(doc)
    if m:
        for kv in _META_KV_RE.finditer(m.group(1)):
            meta[kv.group(1).lower()] = kv.group(2).strip()
        body = doc[m.end():]
    return meta, body


def _terms(query: str) -> list[str]:
    raw = re.split(r"[\s,，、;；]+", query.strip().lower())
    return [t for t in raw if len(t) >= 1]


def _count(text: str, term: str) -> int:
    if not term:
        return 0
    if re.match(r"^[\w-]+$", term):  # 英文词按单词边界计
        return len(re.findall(rf"\b{re.escape(term)}\b", text, re.IGNORECASE))
    return text.lower().count(term)  # 中文按子串计


def _best_excerpt(body: str, terms: list[str], limit: int = 1200) -> str:
    sections = re.split(r"\n(?=## )", body)
    best, best_score = sections[0] if sections else body, -1
    for section in sections:
        score = sum(min(_count(section, t), 8) for t in terms)
        if score > best_score:
            best, best_score = section, score
    excerpt = best.strip()
    return excerpt[:limit] + ("…" if len(excerpt) > limit else "")


def search(knowledge_dir: str | Path, query: str, top_k: int = 2) -> list[dict]:
    """按 title(5x) / keywords(3x) / body(1x) 加权计分，返回 top_k 条目与最佳小节摘录。"""
    root = Path(knowledge_dir)
    if not root.is_dir():
        raise FileNotFoundError(f"知识库目录不存在: {root}")
    terms = _terms(query)
    if not terms:
        return []

    results = []
    for path in sorted(root.glob("*.md")):
        meta, body = _parse(path.read_text(encoding="utf-8"))
        title = meta.get("title", path.stem)
        title_l, body_l = title.lower(), body.lower()
        keywords = meta.get("keywords", "")

        score = (
            5 * sum(min(_count(title_l, t), 3) for t in terms)
            + 3 * sum(min(_count(keywords, t), 3) for t in terms)
            + 1 * sum(min(_count(body_l, t), 10) for t in terms)
        )
        if score > 0:
            results.append(
                {
                    "file": path.name,
                    "title": title,
                    "source": meta.get("source", ""),
                    "score": score,
                    "excerpt": _best_excerpt(body, terms),
                }
            )

    results.sort(key=lambda r: r["score"], reverse=True)
    return results[: max(1, min(int(top_k), 5))]
