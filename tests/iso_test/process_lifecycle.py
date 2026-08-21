"""Kernel-backed containment for acceptance-test child processes."""

from __future__ import annotations

import ctypes
import os
import signal
from collections.abc import Callable


_PR_SET_PDEATHSIG = 1
_LIBC = ctypes.CDLL(None, use_errno=True)


def parent_death_preexec(
    action: Callable[[], None] | None = None,
) -> Callable[[], None]:
    """Return a pre-exec hook that dies if the Python worker disappears.

    QEMU, Xvfb and remote-viewer may be alive while visual native modules are
    running in the worker.  Python ``finally`` blocks cannot run after SIGSEGV,
    so the kernel must own this last-resort containment boundary.
    """

    expected_parent = os.getpid()

    def configure() -> None:
        if _LIBC.prctl(_PR_SET_PDEATHSIG, signal.SIGKILL, 0, 0, 0) != 0:
            os._exit(127)
        # Close the race in which the parent died between fork and prctl.
        if os.getppid() != expected_parent:
            os.kill(os.getpid(), signal.SIGKILL)
        if action is not None:
            action()

    return configure
