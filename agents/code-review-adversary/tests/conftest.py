import sys
from pathlib import Path

TESTS_DIR = Path(__file__).resolve().parent
AGENT_DIR = TESTS_DIR.parent
REPO_ROOT = AGENT_DIR.parent.parent
REVIEWER_TOOLS = REPO_ROOT / "agents" / "code-reviewer" / "tools"

for path in (str(REPO_ROOT), str(AGENT_DIR / "src"), str(AGENT_DIR / "tools"), str(REVIEWER_TOOLS)):
    if path not in sys.path:
        sys.path.insert(0, path)
