"""Minimal crash supervisor for the native-code acceptance worker."""

from __future__ import annotations

import contextlib
import faulthandler
import os
import secrets
import signal
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from .disk_cleanup import (
    DiskCleanupError,
    format_cleanup_report,
    reclaim_orphaned_disks,
    test_results_lease,
)
from .process_lifecycle import parent_death_preexec
from .storage import cleanup_supervised_ramdisk_workspaces


WORKER_ENV = "ANDUINOS_TEST_WORKER"
WORKSPACE_TOKEN_ENV = "ANDUINOS_TEST_WORKSPACE_TOKEN"
FAULT_LOG_ENV = "ANDUINOS_TEST_FAULT_LOG"
_FAULT_STREAM = None


def configure_worker_fault_handler() -> None:
    """Persist fatal Python thread stacks before native modules can be imported."""

    global _FAULT_STREAM
    destination = os.environ.get(FAULT_LOG_ENV)
    if not destination:
        return
    descriptor = os.open(
        destination,
        os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_CLOEXEC,
        0o600,
    )
    _FAULT_STREAM = os.fdopen(
        descriptor,
        "w",
        encoding="utf-8",
        errors="backslashreplace",
        buffering=1,
    )
    faulthandler.enable(file=_FAULT_STREAM, all_threads=True)


def supervised_main(entrypoint: Path, argv: list[str]) -> int:
    """Run the real CLI in an isolated child and recover after native crashes."""

    token = secrets.token_hex(8)
    try:
        worker_argv, artifacts = _ensure_artifacts_argument(argv, token)
    except ValueError as error:
        print(f"error: {error}", file=sys.stderr)
        return 2
    artifacts_preexisting = artifacts.exists()
    environment = os.environ.copy()
    environment[WORKER_ENV] = "1"
    environment[WORKSPACE_TOKEN_ENV] = token
    # A native crash otherwise reports only its terminating signal. CPython's
    # fault handler emits every Python thread at the point of failure.
    environment.setdefault("PYTHONFAULTHANDLER", "1")
    fault_log = _worker_fault_log_path(artifacts, token)
    fault_log.parent.mkdir(parents=True, exist_ok=True)
    if fault_log.exists() or fault_log.is_symlink():
        print(f"error: refusing preexisting worker fault log: {fault_log}", file=sys.stderr)
        return 2
    environment[FAULT_LOG_ENV] = str(fault_log)
    command = (sys.executable, str(entrypoint.resolve()), *worker_argv)
    retain_disks = any(
        item in {"--keep-passed-disk", "--keep-passed-disks", "--keep-failed-disk"}
        for item in worker_argv
    )
    try:
        with test_results_lease(artifacts.parent):
            report = reclaim_orphaned_disks(
                artifacts.parent,
                exclude_roots=(artifacts,),
            )
            if report.candidate_count or report.skipped_paths:
                print(format_cleanup_report(report))
            return run_supervised_worker(
                command,
                environment=environment,
                artifacts=artifacts,
                artifacts_preexisting=artifacts_preexisting,
                workspace_token=token,
                retain_disks=retain_disks,
                fault_log=fault_log,
            )
    except DiskCleanupError as error:
        print(f"error: acceptance disk preflight failed: {error}", file=sys.stderr)
        return 2


def run_supervised_worker(
    command: tuple[str, ...],
    *,
    environment: dict[str, str],
    artifacts: Path,
    artifacts_preexisting: bool,
    workspace_token: str,
    retain_disks: bool,
    fault_log: Path | None = None,
    stdout=None,
    stderr=None,
) -> int:
    """Execute one worker and clean its exact resources after every exit kind."""

    worker = subprocess.Popen(
        command,
        env=environment,
        stdin=None,
        stdout=stdout,
        stderr=stderr,
        start_new_session=True,
        preexec_fn=parent_death_preexec(),
    )
    interrupted = False
    returncode: int | None = None
    cleanup_error: Exception | None = None
    try:
        with _termination_as_interrupt():
            returncode = worker.wait()
    except KeyboardInterrupt:
        interrupted = True
        _signal_group(worker.pid, signal.SIGINT)
        try:
            returncode = worker.wait(timeout=10)
        except subprocess.TimeoutExpired:
            returncode = None
    finally:
        _terminate_process_group(worker)
        try:
            cleanup_supervised_ramdisk_workspaces(workspace_token)
            if not retain_disks:
                _cleanup_persistent_disks(artifacts, artifacts_preexisting)
        except Exception as error:  # cleanup failure must remain visible
            cleanup_error = error
        try:
            if fault_log is not None:
                _finalize_worker_fault_log(
                    fault_log,
                    artifacts,
                    artifacts_preexisting,
                )
        except Exception as error:
            if cleanup_error is None:
                cleanup_error = error

    if cleanup_error is not None:
        print(f"error: supervisor cleanup failed: {cleanup_error}", file=sys.stderr)
        if returncode == 0:
            return 2
    if interrupted:
        print(
            "error: acceptance supervisor interrupted; child processes and "
            "disposable disks were reclaimed",
            file=sys.stderr,
        )
        return 130
    assert returncode is not None
    if returncode < 0:
        signum = -returncode
        try:
            name = signal.Signals(signum).name
        except ValueError:
            name = str(signum)
        print(
            f"error: acceptance worker terminated by {name}; supervisor "
            "reclaimed child processes and disposable disks",
            file=sys.stderr,
        )
        return 128 + signum
    return returncode


def _ensure_artifacts_argument(
    argv: list[str],
    token: str,
) -> tuple[list[str], Path]:
    values = list(argv)
    for index, value in enumerate(values):
        if value == "--artifacts":
            if index + 1 >= len(values) or values[index + 1].startswith("--"):
                raise ValueError("--artifacts requires a path")
            return values, Path(values[index + 1]).expanduser().resolve()
        if value.startswith("--artifacts="):
            path = value.partition("=")[2]
            if not path:
                raise ValueError("--artifacts requires a path")
            return values, Path(path).expanduser().resolve()

    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    artifacts = (Path.cwd() / "test-results" / timestamp).resolve()
    if artifacts.exists():
        artifacts = artifacts.with_name(f"{artifacts.name}-{token[:6]}")
    values.extend(("--artifacts", str(artifacts)))
    return values, artifacts


def _worker_fault_log_path(artifacts: Path, token: str) -> Path:
    return artifacts.parent / f".{artifacts.name}.{token}.worker-fault.log"


def _finalize_worker_fault_log(
    fault_log: Path,
    artifacts: Path,
    artifacts_preexisting: bool,
) -> None:
    if not fault_log.exists() and not fault_log.is_symlink():
        return
    if fault_log.is_symlink() or fault_log.stat().st_uid != os.getuid():
        raise RuntimeError(f"unsafe worker fault log: {fault_log}")
    if fault_log.stat().st_size == 0:
        fault_log.unlink()
        return
    if artifacts_preexisting:
        # Never place supervisor output inside a directory the run did not own.
        return
    if artifacts.exists():
        if artifacts.is_symlink() or artifacts.stat().st_uid != os.getuid():
            raise RuntimeError(f"unsafe supervised artifact root: {artifacts}")
    else:
        artifacts.mkdir(mode=0o700)
    destination = artifacts / "worker-fault.log"
    if destination.exists() or destination.is_symlink():
        raise RuntimeError(f"refusing preexisting worker fault evidence: {destination}")
    fault_log.replace(destination)


def _terminate_process_group(worker: subprocess.Popen) -> None:
    if worker.poll() is None:
        _signal_group(worker.pid, signal.SIGTERM)
        try:
            worker.wait(timeout=5)
        except subprocess.TimeoutExpired:
            _signal_group(worker.pid, signal.SIGKILL)
            worker.wait(timeout=5)
    # A worker killed by SIGSEGV may already be reaped while QEMU still owns
    # its process group.  Address that group explicitly after every exit.
    _signal_group(worker.pid, signal.SIGTERM)
    deadline = time.monotonic() + 3
    while _group_exists(worker.pid) and time.monotonic() < deadline:
        time.sleep(0.05)
    if _group_exists(worker.pid):
        _signal_group(worker.pid, signal.SIGKILL)


def _signal_group(process_group: int, requested: signal.Signals) -> None:
    try:
        os.killpg(process_group, requested)
    except ProcessLookupError:
        pass


def _group_exists(process_group: int) -> bool:
    try:
        os.killpg(process_group, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _cleanup_persistent_disks(root: Path, preexisting: bool) -> None:
    """Remove exact disposable disk names only from a run-created artifact root."""

    if preexisting or not root.exists():
        return
    if root.is_symlink() or root.stat().st_uid != os.getuid():
        raise RuntimeError(f"unsafe supervised artifact root: {root}")
    for child in root.iterdir():
        if child.is_symlink() or not child.is_dir():
            continue
        _unlink_exact(child / "target.qcow2")
        _unlink_exact(child / "live-media.raw")
    overlays = root / "feature-overlays"
    if overlays.is_dir() and not overlays.is_symlink():
        for suite in overlays.iterdir():
            if suite.is_symlink() or not suite.is_dir():
                continue
            _unlink_exact(suite / "overlay.qcow2")
            try:
                suite.rmdir()
            except OSError:
                pass
        try:
            overlays.rmdir()
        except OSError:
            pass


def _unlink_exact(path: Path) -> None:
    if not path.exists() and not path.is_symlink():
        return
    if path.name not in {"target.qcow2", "overlay.qcow2", "live-media.raw"}:
        raise RuntimeError(f"refusing unexpected disk cleanup target: {path}")
    path.unlink()


@contextlib.contextmanager
def _termination_as_interrupt():
    previous = signal.getsignal(signal.SIGTERM)

    def interrupt(_signum, _frame):
        raise KeyboardInterrupt

    signal.signal(signal.SIGTERM, interrupt)
    try:
        yield
    finally:
        signal.signal(signal.SIGTERM, previous)
