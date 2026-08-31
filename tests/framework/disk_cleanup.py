"""Fail-closed reclamation of orphaned acceptance-test virtual disks."""

from __future__ import annotations

import argparse
import fcntl
import os
import stat
import sys
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator


LOCK_NAME = ".anduinos-test-disks.lock"
DISPOSABLE_DISK_NAMES = frozenset(
    {"target.qcow2", "overlay.qcow2", "live-media.raw"}
)
EXPLICIT_RETENTION_TEXT = "retained by explicit single-case option"


class DiskCleanupError(RuntimeError):
    """Base class for a cleanup request that cannot be completed safely."""


class ActiveTestRunError(DiskCleanupError):
    """Raised when another acceptance run owns the result-root lease."""


@dataclass(frozen=True)
class CleanupReport:
    removed_files: tuple[Path, ...]
    reclaimed_bytes: int
    preserved_files: tuple[Path, ...]
    skipped_paths: tuple[Path, ...]
    dry_run: bool = False

    @property
    def candidate_count(self) -> int:
        return len(self.removed_files)


@dataclass(frozen=True)
class _Candidate:
    path: Path
    device: int
    inode: int
    allocated_bytes: int


def cleanup_main(argv: list[str] | None = None) -> int:
    """Run the maintenance mode exposed by the singular test entrypoint."""

    parser = argparse.ArgumentParser(
        prog="tests/run.py clean-disks",
        description="Reclaim orphaned disposable disks while preserving evidence",
    )
    parser.add_argument(
        "--root",
        type=Path,
        default=Path.cwd() / "test-results",
        help="acceptance result root (default: ./test-results)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="report reclaimable disks without deleting them",
    )
    args = parser.parse_args(argv)
    try:
        with test_results_lease(args.root):
            report = reclaim_orphaned_disks(args.root, dry_run=args.dry_run)
    except DiskCleanupError as error:
        print(f"error: {error}", file=sys.stderr)
        return 2
    print(format_cleanup_report(report))
    for path in report.skipped_paths:
        print(f"warning: preserved unsafe path: {path}", file=sys.stderr)
    return 0


@contextmanager
def test_results_lease(root: Path, *, blocking: bool = False) -> Iterator[None]:
    """Exclusively own one result root for cleanup and a complete test run.

    The kernel releases the flock after normal exit, SIGKILL, or host reboot.
    A subsequent run can therefore distinguish abandoned disks from a live
    acceptance run without trusting a stale PID file.
    """

    resolved = _prepare_root(root)
    lock_path = resolved / LOCK_NAME
    if lock_path.is_symlink():
        raise DiskCleanupError(f"refusing symlinked test-results lock: {lock_path}")
    flags = os.O_RDWR | os.O_CREAT | os.O_CLOEXEC
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    descriptor = os.open(lock_path, flags, 0o600)
    try:
        metadata = os.fstat(descriptor)
        if metadata.st_uid != os.getuid() or not stat.S_ISREG(metadata.st_mode):
            raise DiskCleanupError(f"unsafe test-results lock: {lock_path}")
        operation = fcntl.LOCK_EX
        if not blocking:
            operation |= fcntl.LOCK_NB
        try:
            fcntl.flock(descriptor, operation)
        except BlockingIOError as error:
            raise ActiveTestRunError(
                f"another acceptance run is active under {resolved}"
            ) from error
        yield
    finally:
        os.close(descriptor)


def reclaim_orphaned_disks(
    root: Path,
    *,
    exclude_roots: tuple[Path, ...] = (),
    dry_run: bool = False,
) -> CleanupReport:
    """Remove only known disposable disk paths from inactive result runs.

    Callers must hold :func:`test_results_lease` for the same root.  Durable
    evidence remains in place.  Explicitly retained single-case debug disks,
    foreign-owned paths, symlinks, and unrecognized directory shapes are never
    removed.
    """

    resolved = _prepare_root(root)
    excluded = {
        path.expanduser().resolve(strict=False)
        for path in exclude_roots
    }
    candidates: list[_Candidate] = []
    preserved: list[Path] = []
    skipped: list[Path] = []

    for run in sorted(resolved.iterdir()):
        if run.name == LOCK_NAME or not run.exists():
            continue
        if run.is_symlink() or not run.is_dir():
            if run.is_symlink():
                skipped.append(run)
            continue
        if run.resolve() in excluded:
            preserved.extend(_existing_disks(run))
            continue
        if run.stat().st_uid != os.getuid():
            skipped.append(run)
            continue

        for case in sorted(run.iterdir()):
            if case.name == "feature-overlays" or not case.exists():
                continue
            if case.is_symlink() or not case.is_dir():
                if case.is_symlink():
                    skipped.append(case)
                continue
            if case.stat().st_uid != os.getuid():
                skipped.append(case)
                continue
            target = case / "target.qcow2"
            retained, unsafe_note = _retention_status(case)
            if unsafe_note is not None:
                skipped.append(unsafe_note)
                if target.exists() or target.is_symlink():
                    preserved.append(target)
            elif retained:
                if target.exists() or target.is_symlink():
                    preserved.append(target)
            else:
                _consider(target, candidates, skipped)
            _consider(case / "live-media.raw", candidates, skipped)

        overlays = run / "feature-overlays"
        if overlays.is_symlink():
            skipped.append(overlays)
        elif overlays.is_dir() and overlays.stat().st_uid == os.getuid():
            for suite in sorted(overlays.iterdir()):
                if suite.is_symlink() or not suite.is_dir():
                    if suite.is_symlink():
                        skipped.append(suite)
                    continue
                if suite.stat().st_uid != os.getuid():
                    skipped.append(suite)
                    continue
                _consider(suite / "overlay.qcow2", candidates, skipped)
        elif overlays.exists():
            skipped.append(overlays)

    if not dry_run:
        for candidate in candidates:
            _unlink_candidate(candidate)

    return CleanupReport(
        removed_files=tuple(item.path for item in candidates),
        reclaimed_bytes=sum(item.allocated_bytes for item in candidates),
        preserved_files=tuple(preserved),
        skipped_paths=tuple(skipped),
        dry_run=dry_run,
    )


def format_cleanup_report(report: CleanupReport) -> str:
    action = "would reclaim" if report.dry_run else "reclaimed"
    amount = _format_bytes(report.reclaimed_bytes)
    return (
        f"Test disk cleanup: {action} {report.candidate_count} file(s), "
        f"{amount}; preserved {len(report.preserved_files)} explicit/current "
        f"disk(s); skipped {len(report.skipped_paths)} unsafe path(s)"
    )


def _prepare_root(root: Path) -> Path:
    expanded = root.expanduser()
    if expanded.is_symlink():
        raise DiskCleanupError(f"refusing symlinked test-results root: {expanded}")
    expanded.mkdir(parents=True, exist_ok=True)
    resolved = expanded.resolve(strict=True)
    metadata = resolved.stat()
    if metadata.st_uid != os.getuid() or not stat.S_ISDIR(metadata.st_mode):
        raise DiskCleanupError(f"unsafe test-results root: {resolved}")
    return resolved


def _retention_status(case: Path) -> tuple[bool, Path | None]:
    note = case / "target-disk-retention.txt"
    if not note.exists() and not note.is_symlink():
        return False, None
    if note.is_symlink():
        return False, note
    try:
        metadata = note.stat()
        if not stat.S_ISREG(metadata.st_mode) or metadata.st_uid != os.getuid():
            return False, note
        retained = EXPLICIT_RETENTION_TEXT in note.read_text(
            encoding="utf-8",
            errors="replace",
        )
        return retained, None
    except OSError:
        return False, note


def _consider(
    path: Path,
    candidates: list[_Candidate],
    skipped: list[Path],
) -> None:
    if not path.exists() and not path.is_symlink():
        return
    if path.name not in DISPOSABLE_DISK_NAMES:
        raise DiskCleanupError(f"refusing unexpected disk cleanup target: {path}")
    metadata = path.lstat()
    if path.is_symlink() or not stat.S_ISREG(metadata.st_mode):
        skipped.append(path)
        return
    if metadata.st_uid != os.getuid():
        skipped.append(path)
        return
    candidates.append(
        _Candidate(
            path=path,
            device=metadata.st_dev,
            inode=metadata.st_ino,
            allocated_bytes=metadata.st_blocks * 512,
        )
    )


def _unlink_candidate(candidate: _Candidate) -> None:
    metadata = candidate.path.lstat()
    if (
        candidate.path.is_symlink()
        or not stat.S_ISREG(metadata.st_mode)
        or metadata.st_uid != os.getuid()
        or metadata.st_dev != candidate.device
        or metadata.st_ino != candidate.inode
    ):
        raise DiskCleanupError(
            f"disk cleanup target changed during validation: {candidate.path}"
        )
    candidate.path.unlink()


def _existing_disks(root: Path) -> list[Path]:
    result: list[Path] = []
    for path in root.rglob("*"):
        if path.name in DISPOSABLE_DISK_NAMES and (
            path.exists() or path.is_symlink()
        ):
            result.append(path)
    return result


def _format_bytes(value: int) -> str:
    amount = float(value)
    for unit in ("B", "KiB", "MiB", "GiB", "TiB"):
        if amount < 1024 or unit == "TiB":
            return f"{amount:.1f} {unit}"
        amount /= 1024
    raise AssertionError("unreachable")
