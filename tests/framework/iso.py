"""Read-only inspection of the ISO supplied to the test framework."""

from __future__ import annotations

import hashlib
import re
import shlex
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
    live_entries: tuple["LiveGrubEntry", ...]

    def live_entry(self, name: str) -> "LiveGrubEntry":
        matches = [entry for entry in self.live_entries if entry.name == name]
        if len(matches) != 1:
            raise ConfigurationError(
                f"ISO GRUB has {len(matches)} live entries named {name!r}"
            )
        return matches[0]


@dataclass(frozen=True)
class LiveGrubEntry:
    name: str
    kernel_arguments: tuple[str, ...]
    locale: str
    timezone: str


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
    live_entries = _read_live_entries(resolved)
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
        live_entries=live_entries,
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
        _extract(path, "/README.diskdefines", destination)
        content = destination.read_text(encoding="utf-8", errors="replace")
    match = re.search(r"^#define ARCH\s+(amd64|arm64)\s*$", content, re.MULTILINE)
    if match is None:
        raise ConfigurationError("ISO does not declare a supported architecture")
    return Architecture(match.group(1))


def _read_live_entries(path: Path) -> tuple[LiveGrubEntry, ...]:
    with tempfile.TemporaryDirectory(prefix="anduinos-grub-inspect-") as directory:
        destination = Path(directory) / "grub.cfg"
        _extract(path, "/boot/grub/grub.cfg", destination)
        content = destination.read_text(encoding="utf-8", errors="replace")
    return _parse_live_entries(content)


def _parse_live_entries(content: str) -> tuple[LiveGrubEntry, ...]:
    entries: list[LiveGrubEntry] = []
    pattern = re.compile(
        r'^\s*menuentry\s+"(?P<name>[^"]+)"\s*\{(?P<body>.*?)^\s*\}',
        re.MULTILINE | re.DOTALL,
    )
    for match in pattern.finditer(content):
        linux = re.search(r"^\s*linux\s+/casper/vmlinuz\s+(.+)$", match["body"], re.MULTILINE)
        if linux is None:
            continue
        arguments = tuple(shlex.split(linux.group(1)))
        values = {
            key: value
            for token in arguments
            if "=" in token
            for key, value in (token.split("=", 1),)
        }
        if "locale" not in values or "timezone" not in values:
            continue
        if values.get("systemd.timezone") != values["timezone"]:
            raise ConfigurationError(
                f"GRUB entry {match['name']!r} has contradictory timezone arguments"
            )
        entries.append(
            LiveGrubEntry(
                name=match["name"],
                kernel_arguments=arguments,
                locale=values["locale"],
                timezone=values["timezone"],
            )
        )
    if len(entries) != 28:
        raise ConfigurationError(
            f"ISO GRUB must declare 28 locale/timezone live entries; found {len(entries)}"
        )
    if len({entry.name for entry in entries}) != len(entries):
        raise ConfigurationError("ISO GRUB contains duplicate localized live entry names")
    return tuple(entries)


def _extract(iso: Path, source: str, destination: Path) -> None:
    result = subprocess.run(
        (
            "xorriso",
            "-osirrox",
            "on",
            "-indev",
            str(iso),
            "-extract",
            source,
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
            f"Cannot extract {source} from ISO: " + result.stdout.strip()
        )


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
