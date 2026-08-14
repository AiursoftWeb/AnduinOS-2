#!/usr/bin/env python3
"""Run the AnduinOS ISO black-box acceptance matrix."""

from __future__ import annotations

import sys
from pathlib import Path


TESTS_DIRECTORY = Path(__file__).resolve().parent
if str(TESTS_DIRECTORY) not in sys.path:
    sys.path.insert(0, str(TESTS_DIRECTORY))

from iso_test.cli import main  # noqa: E402


if __name__ == "__main__":
    raise SystemExit(main())
