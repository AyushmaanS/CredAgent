#!/usr/bin/env python3
"""Report which configuration values are set. Never prints key values."""

from __future__ import annotations

import stat
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from credagent.config.settings import ConfigError, load_settings  # noqa: E402


def main() -> int:
    try:
        s = load_settings()
    except ConfigError as exc:
        print(f"Config problem: {exc}")
        return 1
    for k, v in s.describe().items():
        print(f"  {k:28} {v}")
    ok = True
    if s.env_file.exists():
        mode = stat.S_IMODE(s.env_file.stat().st_mode)
        if mode & 0o077:
            print(f"\n  WARNING: {s.env_file.name} is readable by other users ({oct(mode)}). "
                  f"Run: chmod 600 {s.env_file.name}")
            ok = False
    missing = [k for k, v in s.describe().items() if v == "missing"]
    if missing:
        print(f"\n  Missing: {', '.join(missing)} — see README 'Local environment'.")
        ok = False
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
