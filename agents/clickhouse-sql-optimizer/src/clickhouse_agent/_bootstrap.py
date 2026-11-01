"""导入路径引导：保证从任意工作目录都能 import common / clickhouse_tools / 本包。"""
from __future__ import annotations

import sys
from pathlib import Path

PKG_DIR = Path(__file__).resolve().parent          # .../src/clickhouse_agent
SRC_DIR = PKG_DIR.parent                            # .../src
AGENT_DIR = SRC_DIR.parent                          # .../clickhouse-sql-optimizer
TOOLS_DIR = AGENT_DIR / "tools"                     # .../tools
REPO_ROOT = AGENT_DIR.parent.parent                 # .../Agent-builder

for path in (str(REPO_ROOT), str(SRC_DIR), str(TOOLS_DIR)):
    if path not in sys.path:
        sys.path.insert(0, path)
