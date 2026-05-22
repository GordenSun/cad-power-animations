from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from collections.abc import Sequence


def main(argv: Sequence[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    skill_dir = Path(__file__).resolve().parents[2]
    viewer_dir = skill_dir / "scripts" / "viewer"
    command = ["npm", "--prefix", str(viewer_dir), "run", "snapshot", "--", *args]
    return subprocess.call(command)


if __name__ == "__main__":
    raise SystemExit(main())
