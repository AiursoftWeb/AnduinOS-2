"""Read-only inspection of the ISO supplied to the test framework."""

from __future__ import annotations

import hashlib
import re
import shlex
import shutil
import struct
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
    persistent_entry: "PersistentLiveGrubEntry"

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


@dataclass(frozen=True)
class PersistentLiveGrubEntry:
    name: str
    kernel_arguments: tuple[str, ...]


def inspect_iso(path: Path, expected_architecture: Architecture) -> IsoInspection:
    resolved = path.expanduser().resolve(strict=True)
    if not resolved.is_file() or resolved.is_symlink():
        raise ConfigurationError(f"ISO is not a regular file: {resolved}")
    if shutil.which("xorriso") is None:
        raise ConfigurationError("Required executable is missing: xorriso")
    for executable in ("mcopy", "sbverify"):
        if shutil.which(executable) is None:
            raise ConfigurationError(
                f"Required executable is missing: {executable}"
            )
    digest = _sha256(resolved)
    architecture = _read_architecture(resolved)
    if architecture is not expected_architecture:
        raise ConfigurationError(
            f"ISO architecture is {architecture.value}, requested "
            f"{expected_architecture.value}"
        )
    report = _boot_report(resolved)
    _validate_efi_payload(resolved, architecture)
    live_entries, persistent_entry = _read_live_entries(resolved)
    has_bios = re.search(r"El Torito boot img\s*:\s*\S+\s+BIOS\b", report) is not None
    has_uefi = re.search(r"El Torito boot img\s*:\s*\S+\s+UEFI\b", report) is not None
    if expected_architecture is Architecture.AMD64 and not has_bios:
        raise ConfigurationError("AMD64 ISO has no El Torito BIOS boot image")
    if not has_uefi:
        raise ConfigurationError("ISO has no El Torito UEFI boot image")
    partition_offset = re.search(
        r"^Partition offset\s*:\s*(\d+)\s*$",
        report,
        re.MULTILINE,
    )
    if partition_offset is None or int(partition_offset.group(1)) <= 0:
        raise ConfigurationError(
            "ISO partition 1 is not offset for Dracut persistent-media support"
        )
    return IsoInspection(
        path=resolved,
        sha256=digest,
        architecture=architecture,
        has_bios_boot=has_bios,
        has_uefi_boot=has_uefi,
        boot_report=report,
        live_entries=live_entries,
        persistent_entry=persistent_entry,
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


def _validate_efi_payload(path: Path, architecture: Architecture) -> None:
    names = (
        ("BOOTX64.EFI", "grubx64.efi", "mmx64.efi")
        if architecture is Architecture.AMD64
        else ("BOOTAA64.EFI", "grubaa64.efi", "mmaa64.efi")
    )
    expected_machine = {
        Architecture.AMD64: 0x8664,
        Architecture.ARM64: 0xAA64,
    }[architecture]
    with tempfile.TemporaryDirectory(prefix="anduinos-efi-inspect-") as directory:
        root = Path(directory)
        image = root / "efiboot.img"
        _extract(path, "/EFI/efiboot.img", image)
        for name in names:
            payload = root / name
            _extract_fat_member(image, f"::/EFI/BOOT/{name}", payload)
            machine = _pe_machine(payload)
            if machine != expected_machine:
                raise ConfigurationError(
                    f"EFI payload {name} has PE machine 0x{machine:04x}, "
                    f"expected {architecture.value}"
                )
            result = subprocess.run(
                ("sbverify", "--list", str(payload)),
                check=False,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                timeout=30,
            )
            if result.returncode != 0 or "signature" not in result.stdout.lower():
                raise ConfigurationError(f"EFI payload is not signed: {name}")

        if architecture is Architecture.ARM64:
            bridge = root / "grub.cfg"
            _extract_fat_member(image, "::/EFI/BOOT/grub.cfg", bridge)
            content = bridge.read_text(encoding="utf-8", errors="strict")
            required = (
                "search --no-floppy --label --set=anduinos_iso anduinos",
                "set prefix=($anduinos_iso)/boot/grub",
                "configfile $prefix/grub.cfg",
            )
            if any(line not in content for line in required):
                raise ConfigurationError(
                    "ARM64 EFI bridge does not load the ISO GRUB configuration"
                )
            if re.search(r"(?:/home/|/root/|new_building_os|image/isolinux)", content):
                raise ConfigurationError(
                    "ARM64 EFI bridge contains a build-host path"
                )


def _pe_machine(path: Path) -> int:
    data = path.read_bytes()
    if len(data) < 0x40 or data[:2] != b"MZ":
        raise ConfigurationError(f"EFI payload is not a PE image: {path.name}")
    pe_offset = struct.unpack_from("<I", data, 0x3C)[0]
    if pe_offset + 6 > len(data) or data[pe_offset : pe_offset + 4] != b"PE\0\0":
        raise ConfigurationError(f"EFI payload has no PE header: {path.name}")
    return struct.unpack_from("<H", data, pe_offset + 4)[0]


def _extract_fat_member(image: Path, source: str, destination: Path) -> None:
    result = subprocess.run(
        ("mcopy", "-i", str(image), source, str(destination)),
        check=False,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        timeout=30,
    )
    if result.returncode != 0 or not destination.is_file():
        raise ConfigurationError(
            f"Cannot extract {source} from EFI image: " + result.stdout.strip()
        )


def _read_live_entries(
    path: Path,
) -> tuple[tuple[LiveGrubEntry, ...], PersistentLiveGrubEntry]:
    with tempfile.TemporaryDirectory(prefix="anduinos-grub-inspect-") as directory:
        destination = Path(directory) / "grub.cfg"
        _extract(path, "/boot/grub/grub.cfg", destination)
        content = destination.read_text(encoding="utf-8", errors="replace")
    _validate_dracut_live_contract(content)
    return _parse_live_entries(content), _parse_persistent_entry(content)


def _validate_dracut_live_contract(content: str) -> None:
    if any(value in content for value in ("boot=casper", "/casper/")):
        raise ConfigurationError("ISO GRUB still contains the retired Live ABI")
    linux_lines = re.findall(
        r"^\s*linux\s+/LiveOS/vmlinuz\s+(.+)$", content, re.MULTILINE
    )
    initrd_lines = re.findall(
        r"^\s*initrd\s+(\S+)\s*$", content, re.MULTILINE
    )
    if len(linux_lines) != 31 or len(initrd_lines) != len(linux_lines):
        raise ConfigurationError(
            "ISO GRUB must contain 28 regional and 3 advanced Live entries"
        )
    if set(initrd_lines) != {"/LiveOS/initrd"}:
        raise ConfigurationError("ISO GRUB references an unexpected Live initrd")

    parsed = [tuple(shlex.split(line)) for line in linux_lines]
    required = {
        "root=live:CDLABEL=anduinos",
        "rd.live.dir=LiveOS",
        "rd.live.squashimg=rootfs.squashfs",
        "rd.anduinos.live=1",
    }
    for arguments in parsed:
        if not required <= set(arguments):
            raise ConfigurationError("A Live entry is missing the Dracut root contract")
        if "rd.overlay" not in arguments and not any(
            value.startswith("rd.overlay=") for value in arguments
        ):
            raise ConfigurationError("A Live entry has no writable overlay contract")

    persistent = [
        set(arguments)
        for arguments in parsed
        if any(value.startswith("rd.overlay=LABEL=") for value in arguments)
    ]
    if len(persistent) != 1 or not {
        "rd.overlay=LABEL=ANDUINOS-PERSIST",
        "rd.live.overlay.cowfs=ext4",
    } <= persistent[0]:
        raise ConfigurationError("ISO GRUB has an invalid persistent overlay entry")
    if sum("rd.live.check=1" in arguments for arguments in parsed) != 1:
        raise ConfigurationError("ISO GRUB must contain exactly one media-check entry")
    if sum("nomodeset" in arguments for arguments in parsed) != 1:
        raise ConfigurationError("ISO GRUB must contain exactly one safe-graphics entry")


def _parse_live_entries(content: str) -> tuple[LiveGrubEntry, ...]:
    entries: list[LiveGrubEntry] = []
    pattern = re.compile(
        r'^\s*menuentry\s+"(?P<name>[^"]+)"\s*\{(?P<body>.*?)^\s*\}',
        re.MULTILINE | re.DOTALL,
    )
    for match in pattern.finditer(content):
        linux = re.search(r"^\s*linux\s+/LiveOS/vmlinuz\s+(.+)$", match["body"], re.MULTILINE)
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


def _parse_persistent_entry(content: str) -> PersistentLiveGrubEntry:
    entries: list[PersistentLiveGrubEntry] = []
    pattern = re.compile(
        r'^\s*menuentry\s+"(?P<name>[^"]+)"\s*\{(?P<body>.*?)^\s*\}',
        re.MULTILINE | re.DOTALL,
    )
    for match in pattern.finditer(content):
        linux = re.search(
            r"^\s*linux\s+/LiveOS/vmlinuz\s+(.+)$",
            match["body"],
            re.MULTILINE,
        )
        if linux is None:
            continue
        arguments = tuple(shlex.split(linux.group(1)))
        if "rd.overlay=LABEL=ANDUINOS-PERSIST" not in arguments:
            continue
        entries.append(
            PersistentLiveGrubEntry(
                name=match["name"],
                kernel_arguments=arguments,
            )
        )
    if len(entries) != 1:
        raise ConfigurationError(
            "ISO GRUB must declare exactly one persistent Live entry"
        )
    return entries[0]


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
