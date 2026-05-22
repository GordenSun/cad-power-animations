from __future__ import annotations

import sys
from pathlib import Path


def ensure_inspect_import_path() -> None:
    inspect_dir = Path(__file__).resolve().parents[1] / "inspect"
    inspect_path = str(inspect_dir)
    if inspect_path not in sys.path:
        sys.path.insert(0, inspect_path)
