"""智能文件打包：参考 alibaba/open-code-review 的"关联文件合并为同一评审单元"。

打包原则（确定性）：
1. 实现与测试配对：同 stem 的 test/impl 文件进同一包（如 OrderService.java 与 OrderServiceTest.java）；
2. 同目录小文件聚合：同目录下小变更合并，减少评审单元数（对应其并发 sub-agent）；
3. 包大小上限：默认 ≤ 8 个文件 / ≤ 1200 新增行，超出则切分。
"""
from __future__ import annotations

import os
from pathlib import PurePosixPath

MAX_FILES_PER_BUNDLE = 8
MAX_LINES_PER_BUNDLE = 1200

_TEST_MARKERS = ("test", "spec", "_test", "test_")


def _stem(path: str) -> str:
    p = PurePosixPath(path)
    return p.stem


def _is_test(path: str) -> bool:
    name = _stem(path).lower()
    return any(m in name for m in _TEST_MARKERS) or "test" in PurePosixPath(path).parts


def _pair_key(path: str) -> str | None:
    """测试文件映射到其实现文件 stem（OrderServiceTest → OrderService）。"""
    if not _is_test(path):
        return None
    stem = _stem(path)
    for m in ("_test", "Test", "Spec", "spec"):
        if m in stem:
            return stem.replace(m, "") or None
    return None


def build_bundles(files: list[dict]) -> list[dict]:
    """files: diff_utils.parse_diff 的 files 列表。返回 bundles: [{id, files, added_lines}]"""
    bundles: list[dict] = []
    paired: set[int] = set()

    def _make(fs: list[dict]) -> dict:
        return {
            "id": f"bundle-{len(bundles) + 1}",
            "files": [f["path"] for f in fs],
            "added_lines": sum(f["added_lines"] for f in fs),
            "file_entries": fs,
        }

    def _key(obj: object) -> int:
        return id(obj)

    impl_by_stem = {}
    for f in files:
        impl_by_stem.setdefault(_stem(f["path"]), []).append(f)

    # 1) 实现-测试配对（双向：测试找实现，实现找测试）；未配上对的文件留给阶段 2
    for f in files:
        if _key(f) in paired:
            continue
        group = [f]
        key = _pair_key(f["path"])
        if key:  # f 是测试文件：找同 stem 的实现
            for impl in impl_by_stem.get(key, []):
                if _key(impl) not in paired:
                    group.append(impl)
        else:  # f 是实现文件：找映射到它的测试文件
            for other in files:
                if _key(other) in paired or other is f:
                    continue
                if _pair_key(other["path"]) == _stem(f["path"]):
                    group.append(other)
        if len(group) > 1:
            for g in group:
                paired.add(_key(g))
            bundles.append(_make(group))

    remaining = [f for f in files if _key(f) not in paired]

    # 2) 同目录聚合（控制包大小）
    by_dir: dict[str, list[dict]] = {}
    for f in remaining:
        by_dir.setdefault(str(PurePosixPath(f["path"]).parent), []).append(f)

    for d in sorted(by_dir):
        current, lines = [], 0
        for f in sorted(by_dir[d], key=lambda x: x["path"]):
            if current and (len(current) >= MAX_FILES_PER_BUNDLE or lines + f["added_lines"] > MAX_LINES_PER_BUNDLE):
                bundles.append(_make(current))
                current, lines = [], 0
            current.append(f)
            lines += f["added_lines"]
        if current:
            bundles.append(_make(current))

    return bundles
