#!/usr/bin/python3
"""Guest entry point for the packaged AT-SPI acceptance driver."""

import sys
from pathlib import Path


# Resolve symlinks because shell fixtures keep one immutable driver package and
# expose its entry point from per-check runtime directories.
sys.path.insert(0, str(Path(__file__).resolve().parent))

from ui.main import main


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as error:
        print(f"UI-ERROR: {type(error).__name__}: {error}", flush=True)
        raise
