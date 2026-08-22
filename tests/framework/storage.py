"""Fail-closed storage selection for disposable virtual machines."""

from __future__ import annotations

import hashlib
import os
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path

from .errors import ConfigurationError


GIB = 1024**3
MIB = 1024**2
DEFAULT_RAMDISK_THRESHOLD_GIB = 16
RAMDISK_MIN_FREE_GIB = 8
RAMDISK_MAX_QCOW_GIB = 12
RAMDISK_HOST_RESERVE_GIB = 2
RAMDISK_SELECTION_HEADROOM_GIB = 2
WORKSPACE_TOKEN_ENV = "ANDUINOS_TEST_WORKSPACE_TOKEN"


@dataclass(frozen=True)
class StorageCapacity:
    filesystem_path: Path
    free_bytes: int
    required_bytes: int

    @property
    def free_gib(self) -> float:
        return self.free_bytes / GIB

    @property
    def required_gib(self) -> float:
        return self.required_bytes / GIB


@dataclass(frozen=True)
class DiskStorage:
    """One run's target-disk workspace and the reason it was selected."""

    root: Path
    backend: str
    reason: str
    memory_available_bytes: int | None = None
    ramdisk_free_bytes: int | None = None
    qcow_limit_bytes: int | None = None

    @property
    def is_ramdisk(self) -> bool:
        return self.backend == "ramdisk"


def inspect_capacity(
    artifact_path: Path,
    disk_gib: int,
    reserve_gib: int,
) -> StorageCapacity:
    """Measure a persistent filesystem that may contain the whole qcow2."""

    probe = _existing_parent(artifact_path)
    usage = shutil.disk_usage(probe)
    return StorageCapacity(
        filesystem_path=probe,
        free_bytes=usage.free,
        # A sparse qcow2 is allowed to grow to the entire advertised guest
        # disk. Budget against that upper bound, not yesterday's typical use.
        required_bytes=(disk_gib + reserve_gib) * GIB,
    )


def assert_capacity(
    artifact_path: Path,
    disk_gib: int,
    reserve_gib: int,
) -> StorageCapacity:
    capacity = inspect_capacity(artifact_path, disk_gib, reserve_gib)
    if capacity.free_bytes < capacity.required_bytes:
        raise ConfigurationError(
            "Refusing to start a disposable VM: "
            f"{capacity.free_gib:.1f} GiB is free on the target-disk "
            "filesystem, "
            f"but a {disk_gib} GiB guest plus the {reserve_gib} GiB safety "
            f"reserve requires {capacity.required_gib:.1f} GiB. "
            "Free space, allow the automatic RAM-disk backend, choose another "
            "--artifacts filesystem, or reduce --disk-size only when the image "
            "is known to fit."
        )
    return capacity


def select_disk_storage(
    artifacts_root: Path,
    *,
    memory_mib: int,
    mode: str = "auto",
    ramdisk_threshold_gib: int = DEFAULT_RAMDISK_THRESHOLD_GIB,
    retain_disk: bool = False,
) -> DiskStorage:
    """Choose tmpfs when it is both useful and safe, otherwise use artifacts."""

    if mode not in {"auto", "ramdisk", "filesystem"}:
        raise ConfigurationError(f"Unknown disk backend: {mode}")
    if ramdisk_threshold_gib < 1:
        raise ConfigurationError("RAM-disk threshold must be at least 1 GiB")
    persistent = DiskStorage(
        root=artifacts_root,
        backend="filesystem",
        reason="persistent filesystem requested",
    )
    if mode == "filesystem":
        return persistent
    if retain_disk:
        return DiskStorage(
            root=artifacts_root,
            backend="filesystem",
            reason="explicit disk retention requires persistent storage",
        )

    available = _read_mem_available()
    threshold = ramdisk_threshold_gib * GIB
    if available is None:
        return _ramdisk_unavailable(
            mode,
            persistent,
            "MemAvailable is unavailable on this host",
        )
    if available <= threshold:
        return _ramdisk_unavailable(
            mode,
            persistent,
            f"MemAvailable is {available / GIB:.1f} GiB, not above the "
            f"{ramdisk_threshold_gib} GiB threshold",
        )

    candidates: list[tuple[Path, int, int]] = []
    for candidate in _ramdisk_candidates():
        try:
            resolved = candidate.expanduser().resolve()
            if not resolved.is_dir() or not os.access(resolved, os.W_OK | os.X_OK):
                continue
            if _filesystem_type(resolved) != "tmpfs":
                continue
            free = shutil.disk_usage(resolved).free
        except OSError:
            continue
        qcow_limit = min(free, RAMDISK_MAX_QCOW_GIB * GIB)
        candidates.append((resolved, free, qcow_limit))

    minimum = RAMDISK_MIN_FREE_GIB * GIB
    guest = memory_mib * MIB
    host_reserve = RAMDISK_HOST_RESERVE_GIB * GIB
    selection_headroom = RAMDISK_SELECTION_HEADROOM_GIB * GIB
    # QEMU receives an RLIMIT_FSIZE equal to qcow_limit, so this is an enforced
    # allocation budget rather than an estimate of how sparse qcow2 usually is.
    safe = [
        item
        for item in candidates
        if item[1] >= minimum
        and available >= item[2] + guest + host_reserve + selection_headroom
    ]
    if not safe:
        details = (
            "no writable tmpfs has at least "
            f"{RAMDISK_MIN_FREE_GIB} GiB free while preserving "
            f"{memory_mib / 1024:.1f} GiB for QEMU and "
            f"{RAMDISK_HOST_RESERVE_GIB} GiB for the host, plus "
            f"{RAMDISK_SELECTION_HEADROOM_GIB} GiB startup headroom"
        )
        return _ramdisk_unavailable(mode, persistent, details)

    mount, free, qcow_limit = max(safe, key=lambda item: (item[2], item[1]))
    token = os.environ.get(WORKSPACE_TOKEN_ENV)
    if token is None:
        token = hashlib.sha256(
            f"{artifacts_root.expanduser().resolve()}\0{os.getpid()}".encode()
        ).hexdigest()[:16]
    _validate_workspace_token(token)
    root = mount / f"anduinos-iso-tests-{os.getuid()}" / token
    return DiskStorage(
        root=root,
        backend="ramdisk",
        reason=(
            f"MemAvailable {available / GIB:.1f} GiB exceeds "
            f"{ramdisk_threshold_gib} GiB; {mount} has {free / GIB:.1f} GiB "
            f"free with a hard {qcow_limit / GIB:.1f} GiB qcow2 limit"
        ),
        memory_available_bytes=available,
        ramdisk_free_bytes=free,
        qcow_limit_bytes=qcow_limit,
    )


def assert_disk_storage_ready(
    storage: DiskStorage,
    *,
    disk_gib: int,
    filesystem_reserve_gib: int,
    memory_mib: int,
) -> StorageCapacity:
    """Revalidate the selected backend before the run and every scenario."""

    if not storage.is_ramdisk:
        return assert_capacity(storage.root, disk_gib, filesystem_reserve_gib)

    mount = _existing_parent(storage.root)
    if _filesystem_type(mount) != "tmpfs":
        raise ConfigurationError(
            f"RAM-disk workspace is no longer on tmpfs: {storage.root}"
        )
    free = shutil.disk_usage(mount).free
    available = _read_mem_available()
    if available is None:
        raise ConfigurationError("MemAvailable disappeared after RAM-disk selection")
    minimum = RAMDISK_MIN_FREE_GIB * GIB
    qcow_limit = storage.qcow_limit_bytes
    if qcow_limit is None:
        raise ConfigurationError("RAM-disk workspace has no enforced qcow2 limit")
    required_memory = (
        qcow_limit + memory_mib * MIB + RAMDISK_HOST_RESERVE_GIB * GIB
    )
    if free < min(minimum, qcow_limit) or available < required_memory:
        raise ConfigurationError(
            "RAM-disk safety conditions changed before QEMU start: "
            f"tmpfs has {free / GIB:.1f} GiB free and MemAvailable is "
            f"{available / GIB:.1f} GiB; the enforced "
            f"{qcow_limit / GIB:.1f} GiB qcow2 budget plus QEMU memory and "
            "the host reserve are required"
        )
    return StorageCapacity(mount, free, qcow_limit)


def prepare_disk_storage(storage: DiskStorage) -> None:
    """Create only the private run directory; never mount or format anything."""

    if not storage.is_ramdisk:
        return
    parent = storage.root.parent
    if parent.exists():
        stat = parent.stat()
        if stat.st_uid != os.getuid() or parent.is_symlink():
            raise ConfigurationError(f"Unsafe shared RAM-disk directory: {parent}")
    else:
        parent.mkdir(mode=0o700)
    storage.root.mkdir(mode=0o700)


def cleanup_disk_storage(storage: DiskStorage) -> None:
    """Remove only the private tmpfs workspace created for this process."""

    if not storage.is_ramdisk or not storage.root.exists():
        return
    if storage.root.is_symlink() or storage.root.stat().st_uid != os.getuid():
        raise ConfigurationError(
            f"Refusing to clean unsafe RAM-disk workspace: {storage.root}"
        )
    shutil.rmtree(storage.root)
    try:
        storage.root.parent.rmdir()
    except OSError:
        pass


def cleanup_supervised_ramdisk_workspaces(token: str) -> None:
    """Reclaim only the supervisor-token workspace on known writable tmpfs mounts."""

    _validate_workspace_token(token)
    for candidate in _ramdisk_candidates():
        try:
            mount = candidate.expanduser().resolve()
            if not mount.is_dir() or _filesystem_type(mount) != "tmpfs":
                continue
            root = mount / f"anduinos-iso-tests-{os.getuid()}" / token
            if not root.exists():
                continue
            cleanup_disk_storage(DiskStorage(root, "ramdisk", "supervisor cleanup"))
        except OSError:
            continue


def _validate_workspace_token(token: str) -> None:
    if len(token) != 16 or any(value not in "0123456789abcdef" for value in token):
        raise ConfigurationError("Unsafe acceptance workspace token")


def _ramdisk_unavailable(
    mode: str,
    fallback: DiskStorage,
    reason: str,
) -> DiskStorage:
    if mode == "ramdisk":
        raise ConfigurationError(f"RAM-disk backend requested but unavailable: {reason}")
    return DiskStorage(
        root=fallback.root,
        backend=fallback.backend,
        reason=f"RAM-disk auto-selection skipped: {reason}",
    )


def _read_mem_available(path: Path = Path("/proc/meminfo")) -> int | None:
    try:
        for line in path.read_text(encoding="ascii").splitlines():
            if line.startswith("MemAvailable:"):
                return int(line.split()[1]) * 1024
    except (OSError, ValueError, IndexError):
        return None
    return None


def _ramdisk_candidates() -> tuple[Path, ...]:
    values: list[Path] = []
    override = os.environ.get("ANDUINOS_TEST_RAMDISK")
    runtime = os.environ.get("XDG_RUNTIME_DIR")
    if override:
        values.append(Path(override))
    values.extend((Path("/dev/shm"), Path("/run/shm")))
    if runtime:
        values.append(Path(runtime))
    values.append(Path(tempfile.gettempdir()))
    result: list[Path] = []
    seen: set[Path] = set()
    for value in values:
        try:
            resolved = value.expanduser().resolve()
        except OSError:
            continue
        if resolved not in seen:
            seen.add(resolved)
            result.append(resolved)
    return tuple(result)


def _filesystem_type(path: Path) -> str | None:
    """Return the longest matching mount's type from Linux mountinfo."""

    try:
        lines = Path("/proc/self/mountinfo").read_text(encoding="utf-8").splitlines()
    except OSError:
        return None
    resolved = path.resolve()
    best: tuple[int, str] | None = None
    for line in lines:
        left, separator, right = line.partition(" - ")
        if not separator:
            continue
        fields = left.split()
        after = right.split()
        if len(fields) < 5 or not after:
            continue
        mount = Path(_unescape_mountinfo(fields[4]))
        try:
            resolved.relative_to(mount)
        except ValueError:
            continue
        score = len(mount.parts)
        if best is None or score > best[0]:
            best = (score, after[0])
    return best[1] if best else None


def _unescape_mountinfo(value: str) -> str:
    for escaped, plain in (
        ("\\040", " "),
        ("\\011", "\t"),
        ("\\012", "\n"),
        ("\\134", "\\"),
    ):
        value = value.replace(escaped, plain)
    return value


def _existing_parent(path: Path) -> Path:
    probe = path.expanduser().resolve()
    while not probe.exists():
        parent = probe.parent
        if parent == probe:
            raise ConfigurationError(
                f"Cannot find an existing parent for storage path: {path}"
            )
        probe = parent
    return probe
