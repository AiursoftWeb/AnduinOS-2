"""Immutable installation-base promotion and disposable qcow2 overlays."""

from __future__ import annotations

import fcntl
import hashlib
import json
import os
import shutil
import subprocess
from contextlib import contextmanager
from dataclasses import asdict, dataclass, replace
from pathlib import Path

from .errors import ConfigurationError, TestFailure
from .grub import InstalledBootFiles
from .iso import IsoInspection
from .model import Architecture, MatrixDefaults, Scenario
from .qemu import QemuConfig, QemuVm, allocate_tcp_port
from .storage import DiskStorage


@dataclass(frozen=True)
class PromotedBase:
    identity: str
    architecture: Architecture
    scenario: Scenario
    disk: Path
    variables: Path | None
    config: QemuConfig
    boot_files: InstalledBootFiles
    disk_sha256: str
    disk_size_bytes: int
    disk_mtime_ns: int
    variables_sha256: str | None
    variables_size_bytes: int | None
    variables_mtime_ns: int | None
    manifest: Path
    lock_path: Path

    @contextmanager
    def locked(self):
        """Prevent base cleanup while an overlay still references it."""

        self.lock_path.parent.mkdir(parents=True, exist_ok=True)
        with self.lock_path.open("a+", encoding="utf-8") as stream:
            fcntl.flock(stream.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(stream.fileno(), fcntl.LOCK_UN)

    def overlay_vm(
        self,
        suite_id: str,
        artifacts: Path,
        storage: DiskStorage,
    ) -> QemuVm:
        """Create a VM definition whose only writable system state is an overlay."""

        safe_id = _safe_identifier(suite_id)
        overlay = storage.root / "feature-overlays" / safe_id / "overlay.qcow2"
        variables = None
        if self.variables is not None:
            variables = artifacts / "uefi-vars.fd"
            if variables.exists():
                raise ConfigurationError(
                    f"Refusing to reuse feature UEFI variables: {variables}"
                )
            variables.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(self.variables, variables)
            variables.chmod(0o600)
        config = replace(
            self.config,
            disk=overlay,
            backing_disk=self.disk,
            variables=variables,
            artifacts=artifacts,
            ssh_forward_port=allocate_tcp_port(),
        )
        return QemuVm(config)

    def verify_integrity(self) -> dict[str, object]:
        """Prove that the published backing files stayed byte-for-byte immutable."""

        disk_stat = _immutable_file_stat(self.disk, "installation base")
        if disk_stat.st_size != self.disk_size_bytes:
            raise TestFailure(
                "Immutable installation base changed size: "
                f"expected {self.disk_size_bytes}, observed {disk_stat.st_size}"
            )
        if disk_stat.st_mtime_ns != self.disk_mtime_ns:
            raise TestFailure(
                "Immutable installation base modification time changed: "
                f"expected {self.disk_mtime_ns}, observed {disk_stat.st_mtime_ns}"
            )
        qcow2 = _check_qcow2(self.disk)
        observed_disk_sha256 = _sha256(self.disk)
        if observed_disk_sha256 != self.disk_sha256:
            raise TestFailure(
                "Immutable installation base content changed: "
                f"expected SHA-256 {self.disk_sha256}, observed "
                f"{observed_disk_sha256}"
            )

        observed_variables_sha256 = None
        if self.variables is not None:
            variables_stat = _immutable_file_stat(
                self.variables,
                "installation-base UEFI variables",
            )
            if variables_stat.st_size != self.variables_size_bytes:
                raise TestFailure(
                    "Immutable installation-base UEFI variables changed size"
                )
            if variables_stat.st_mtime_ns != self.variables_mtime_ns:
                raise TestFailure(
                    "Immutable installation-base UEFI variables modification "
                    "time changed"
                )
            observed_variables_sha256 = _sha256(self.variables)
            if observed_variables_sha256 != self.variables_sha256:
                raise TestFailure(
                    "Immutable installation-base UEFI variables content changed"
                )

        return {
            "state": "verified-immutable",
            "disk": str(self.disk),
            "disk_size_bytes": disk_stat.st_size,
            "disk_sha256": observed_disk_sha256,
            "qcow2_check": qcow2,
            "variables": str(self.variables) if self.variables is not None else None,
            "variables_size_bytes": (
                self.variables_size_bytes if self.variables is not None else None
            ),
            "variables_sha256": observed_variables_sha256,
        }

    def cleanup(self) -> None:
        """Remove the exact promoted boot state; hashed evidence remains."""

        if self.disk.exists():
            self.disk.chmod(0o600)
            self.disk.unlink()
        _discard_variable_store(self.variables)
        self.lock_path.unlink(missing_ok=True)


def promote_base(
    vm: QemuVm,
    scenario: Scenario,
    defaults: MatrixDefaults,
    inspection: IsoInspection,
    boot_files: InstalledBootFiles,
    framework_root: Path,
) -> PromotedBase:
    """Atomically publish a closed, verified target as an immutable run-local base."""

    if vm.running:
        raise TestFailure("Cannot promote an installation base while QEMU is running")
    disk = vm.config.disk.resolve()
    if not disk.is_file() or disk.is_symlink():
        raise TestFailure(f"Verified target disk is unavailable for promotion: {disk}")
    variables = vm.config.variables.resolve() if vm.config.variables else None
    if variables is not None and not variables.is_file():
        raise TestFailure("Installed UEFI variable store is unavailable for promotion")
    # QMP has already flushed the open block node and reaped QEMU.  This host
    # fsync is the final publication barrier before another QEMU process may
    # use the file as a backing image.
    _sync_file_and_parent(disk)
    qcow2 = _check_qcow2(disk)
    disk_stat = disk.stat()
    disk_sha256 = _sha256(disk)
    variables_stat = None
    variables_sha256 = None
    if variables is not None:
        _sync_file_and_parent(variables)
        variables_stat = variables.stat()
        variables_sha256 = _sha256(variables)
    payload = _identity_payload(
        vm.config,
        scenario,
        defaults,
        inspection,
        boot_files,
        framework_root,
        disk_sha256,
        variables_sha256,
    )
    identity = hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    sidecar = disk.with_name("base-manifest.json")
    manifest = vm.config.artifacts / "base-manifest.json"
    document = {
        "schema_version": 2,
        "identity": identity,
        "state": "verified-and-immutable",
        "disk": str(disk),
        "sidecar": str(sidecar),
        "variables": str(variables) if variables is not None else None,
        "integrity": {
            "disk_size_bytes": disk_stat.st_size,
            "disk_mtime_ns": disk_stat.st_mtime_ns,
            "disk_sha256": disk_sha256,
            "qcow2_check": qcow2,
            "variables_size_bytes": (
                variables_stat.st_size if variables_stat is not None else None
            ),
            "variables_mtime_ns": (
                variables_stat.st_mtime_ns if variables_stat is not None else None
            ),
            "variables_sha256": variables_sha256,
        },
        "boot_files": asdict(boot_files),
        "identity_inputs": payload,
    }
    rendered = json.dumps(document, ensure_ascii=False, indent=2) + "\n"
    _write_atomic(sidecar, rendered)
    _write_atomic(manifest, rendered)
    disk.chmod(0o400)
    if variables is not None:
        variables.chmod(0o400)
    return PromotedBase(
        identity=identity,
        architecture=vm.config.architecture,
        scenario=scenario,
        disk=disk,
        variables=variables,
        config=vm.config,
        boot_files=boot_files,
        disk_sha256=disk_sha256,
        disk_size_bytes=disk_stat.st_size,
        disk_mtime_ns=disk_stat.st_mtime_ns,
        variables_sha256=variables_sha256,
        variables_size_bytes=(
            variables_stat.st_size if variables_stat is not None else None
        ),
        variables_mtime_ns=(
            variables_stat.st_mtime_ns if variables_stat is not None else None
        ),
        manifest=manifest,
        lock_path=disk.with_name("base.lock"),
    )


def discard_overlay(vm: QemuVm) -> None:
    """Stop QEMU and unlink only its explicitly configured writable state."""

    vm.stop()
    disk = vm.config.disk
    if vm.config.backing_disk is None:
        raise ConfigurationError("Refusing overlay cleanup without a backing disk")
    if disk.name != "overlay.qcow2":
        raise ConfigurationError(f"Refusing unexpected overlay cleanup target: {disk}")
    disk.unlink(missing_ok=True)
    _discard_variable_store(vm.config.variables)
    try:
        disk.parent.rmdir()
    except OSError:
        pass


def _discard_variable_store(variables: Path | None) -> None:
    """Delete only a runner-created UEFI VARS file, never its system template."""

    if variables is None or not variables.exists():
        return
    if variables.name != "uefi-vars.fd" or variables.is_symlink():
        raise ConfigurationError(
            f"Refusing unexpected UEFI variable-store cleanup target: {variables}"
        )
    variables.unlink()


def _identity_payload(
    config: QemuConfig,
    scenario: Scenario,
    defaults: MatrixDefaults,
    inspection: IsoInspection,
    boot_files: InstalledBootFiles,
    framework_root: Path,
    disk_sha256: str,
    variables_sha256: str | None,
) -> dict[str, object]:
    firmware = config.firmware_selection
    return {
        "iso_sha256": inspection.sha256,
        "architecture": config.architecture.value,
        "scenario": _jsonable(asdict(scenario)),
        "defaults": asdict(defaults),
        "boot_files": asdict(boot_files),
        "installed_disk_sha256": disk_sha256,
        "installed_variables_sha256": variables_sha256,
        "firmware_code_sha256": (
            _sha256(firmware.code) if firmware is not None else None
        ),
        "original_vars_sha256": (
            _sha256(firmware.variables_template) if firmware is not None else None
        ),
        "framework_git_revision": _git_revision(framework_root),
        "framework_tree_sha256": _framework_digest(framework_root),
    }


def _framework_digest(root: Path) -> str:
    source_roots = ("framework", "business", "assertions", "fixtures", "cases")
    candidates = sorted(
        path
        for name in source_roots
        for path in (root / name).rglob("*")
        if path.is_file()
        and "__pycache__" not in path.parts
        and path.suffix != ".pyc"
    )
    digest = hashlib.sha256()
    for path in candidates:
        if not path.is_file():
            continue
        digest.update(str(path.relative_to(root)).encode("utf-8") + b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def _git_revision(root: Path) -> str:
    result = subprocess.run(
        ("git", "rev-parse", "HEAD"),
        cwd=root.parent,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        check=False,
        timeout=10,
    )
    return result.stdout.strip() if result.returncode == 0 else "unavailable"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _immutable_file_stat(path: Path, label: str) -> os.stat_result:
    if path.is_symlink() or not path.is_file():
        raise TestFailure(f"Immutable {label} is unavailable: {path}")
    result = path.stat()
    if result.st_mode & 0o222:
        raise TestFailure(f"Immutable {label} became writable: {path}")
    return result


def _sync_file_and_parent(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    parent_descriptor = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(parent_descriptor)
    finally:
        os.close(parent_descriptor)


def _check_qcow2(path: Path) -> dict[str, object]:
    result = subprocess.run(
        ("qemu-img", "check", "--output=json", "-f", "qcow2", str(path)),
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
        timeout=600,
    )
    if result.returncode != 0:
        raise TestFailure(
            "qcow2 integrity check failed for immutable installation base "
            f"(exit {result.returncode}): {result.stdout.strip()}"
        )
    try:
        document = json.loads(result.stdout)
    except json.JSONDecodeError as error:
        raise TestFailure(
            "qemu-img check returned malformed JSON for immutable installation base"
        ) from error
    if not isinstance(document, dict):
        raise TestFailure(
            "qemu-img check returned a non-object integrity report"
        )
    return document


def _write_atomic(path: Path, value: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + f".tmp-{os.getpid()}")
    temporary.write_text(value, encoding="utf-8")
    os.replace(temporary, path)


def _jsonable(value):
    if isinstance(value, dict):
        return {key: _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(item) for item in value]
    if hasattr(value, "value"):
        return value.value
    return value


def _safe_identifier(value: str) -> str:
    if not value or any(
        character not in "abcdefghijklmnopqrstuvwxyz0123456789-." for character in value
    ):
        raise ConfigurationError(f"Unsafe feature-suite identifier: {value!r}")
    return value
