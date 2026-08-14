"""Read-only inspection of the ISO supplied to the test framework."""

from __future__ import annotations

import hashlib
import re
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

from .errors import ConfigurationError
from .model import Architecture


@dataclass(frozen=True)
class IsoInspection:
    path: Path
    sha256: str
    architecture: Architecture
    has_bios_boot: bool
    has_uefi_boot: bool
    boot_report: str


def inspect_iso(path: Path, expected_architecture: Architecture) -> IsoInspection:
    resolved = path.expanduser().resolve(strict=True)
    if not resolved.is_file() or resolved.is_symlink():
        raise ConfigurationError(f"ISO is not a regular file: {resolved}")
    if shutil.which("xorriso") is None:
        raise ConfigurationError("Required executable is missing: xorriso")
    digest = _sha256(resolved)
    architecture = _read_architecture(resolved)
    if architecture is not expected_architecture:
        raise ConfigurationError(
            f"ISO architecture is {architecture.value}, requested "
            f"{expected_architecture.value}"
        )
    report = _boot_report(resolved)
    has_bios = re.search(r"El Torito boot img\s*:\s*\S+\s+BIOS\b", report) is not None
    has_uefi = re.search(r"El Torito boot img\s*:\s*\S+\s+UEFI\b", report) is not None
    if expected_architecture is Architecture.AMD64 and not has_bios:
        raise ConfigurationError("AMD64 ISO has no El Torito BIOS boot image")
    if not has_uefi:
        raise ConfigurationError("ISO has no El Torito UEFI boot image")
    return IsoInspection(
        path=resolved,
        sha256=digest,
        architecture=architecture,
        has_bios_boot=has_bios,
        has_uefi_boot=has_uefi,
        boot_report=report,
    )


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(4 * 1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _read_architecture(path: Path) -> Architecture:
    with tempfile.TemporaryDirectory(prefix="anduinos-iso-inspect-") as directory:
        destination = Path(directory) / "README.diskdefines"
        result = subprocess.run(
            (
                "xorriso",
                "-osirrox",
                "on",
                "-indev",
                str(path),
                "-extract",
                "/README.diskdefines",
                str(destination),
            ),
            check=False,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            timeout=60,
        )
        if result.returncode != 0 or not destination.is_file():
            raise ConfigurationError(
                "Cannot extract /README.diskdefines from ISO: "
                + result.stdout.strip()
            )
        content = destination.read_text(encoding="utf-8", errors="replace")
    match = re.search(r"^#define ARCH\s+(amd64|arm64)\s*$", content, re.MULTILINE)
    if match is None:
        raise ConfigurationError("ISO does not declare a supported architecture")
    return Architecture(match.group(1))


def _boot_report(path: Path) -> str:
    result = subprocess.run(
        (
            "xorriso",
            "-indev",
            str(path),
            "-report_el_torito",
            "plain",
            "-report_system_area",
            "plain",
        ),
        check=False,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        timeout=60,
    )
    if result.returncode != 0:
        raise ConfigurationError("Cannot inspect ISO boot records")
    return result.stdout
