from __future__ import annotations

from pathlib import Path
import sys

if __package__ in {None, ""}:
    scripts_dir = Path(__file__).resolve().parents[1]
    if str(scripts_dir) not in sys.path:
        sys.path.insert(0, str(scripts_dir))
    from render.cli import main
else:
    from .cli import main


if __name__ == "__main__":
    raise SystemExit(main())
