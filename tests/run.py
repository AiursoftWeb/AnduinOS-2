#!/usr/bin/env python3
"""Run the AnduinOS ISO black-box acceptance matrix."""

from __future__ import annotations

import os
import sys
from pathlib import Path


TESTS_DIRECTORY = Path(__file__).resolve().parent
if str(TESTS_DIRECTORY) not in sys.path:
    sys.path.insert(0, str(TESTS_DIRECTORY))

if __name__ == "__main__":
    # Keep the long-running CLI in a child process.  The parent imports no
    # image/UI native modules and can still reclaim QEMU and qcow2 files if a
    # codec or accessibility library terminates the worker with SIGSEGV.
    if os.environ.get("ANDUINOS_TEST_WORKER") == "1":
        from iso_test.supervisor import configure_worker_fault_handler

        configure_worker_fault_handler()
        from iso_test.cli import main

        raise SystemExit(main())
    from iso_test.supervisor import supervised_main

    raise SystemExit(supervised_main(Path(__file__), sys.argv[1:]))
