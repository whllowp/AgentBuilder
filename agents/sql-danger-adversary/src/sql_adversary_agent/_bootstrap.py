"""导入路径引导：保证从任意工作目录都能 import common / adversary_tools / 本包与被测引擎。"""
from __future__ import annotations

import sys
from pathlib import Path

PKG_DIR = Path(__file__).resolve().parent
SRC_DIR = PKG_DIR.parent
AGENT_DIR = SRC_DIR.parent
TOOLS_DIR = AGENT_DIR / "tools"
REPO_ROOT = AGENT_DIR.parent.parent
REVIEWER_TOOLS = REPO_ROOT / "agents" / "sql-danger-reviewer" / "tools"  # 评测专用：被测引擎路径

for path in (str(REPO_ROOT), str(SRC_DIR), str(TOOLS_DIR), str(REVIEWER_TOOLS)):
    if path not in sys.path:
        sys.path.insert(0, path)
