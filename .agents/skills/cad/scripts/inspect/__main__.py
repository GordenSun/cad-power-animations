from __future__ import annotations

from pathlib import Path
import sys

TOOL_DIR = Path(__file__).resolve().parent
SCRIPTS_DIR = TOOL_DIR.parent
for path in (SCRIPTS_DIR, TOOL_DIR):
    path_text = str(path)
    if path_text not in sys.path:
        sys.path.insert(0, path_text)

from cli import main


if __name__ == "__main__":
    raise SystemExit(main())
