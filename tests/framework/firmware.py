"""Architecture-aware QEMU firmware resolution."""

from __future__ import annotations

import shutil
from dataclasses import dataclass
from pathlib import Path

from .errors import ConfigurationError
from .model import Architecture, Firmware


@dataclass(frozen=True)
class FirmwareOverrides:
    uefi_code: Path | None = None
    uefi_vars_no_secure_boot: Path | None = None
    uefi_vars_secure_boot: Path | None = None


@dataclass(frozen=True)
class FirmwareSelection:
    code: Path
    variables_template: Path


_DEFAULTS = {
    Architecture.AMD64: {
        "code": (
            Path("/usr/share/OVMF/OVMF_CODE_4M.secboot.fd"),
            Path("/usr/share/OVMF/OVMF_CODE.secboot.fd"),
        ),
        "vars-nosb": (
            Path("/usr/share/OVMF/OVMF_VARS_4M.fd"),
            Path("/usr/share/OVMF/OVMF_VARS.fd"),
        ),
        "vars-sb": (
            Path("/usr/share/OVMF/OVMF_VARS_4M.ms.fd"),
            Path("/usr/share/OVMF/OVMF_VARS.ms.fd"),
        ),
    },
    Architecture.ARM64: {
        "code": (
            Path("/usr/share/AAVMF/AAVMF_CODE.ms.fd"),
            Path("/usr/share/AAVMF/AAVMF_CODE.fd"),
        ),
        "vars-nosb": (Path("/usr/share/AAVMF/AAVMF_VARS.fd"),),
        "vars-sb": (
            Path("/usr/share/AAVMF/AAVMF_VARS.ms.fd"),
        ),
    },
}


def resolve_firmware(
    architecture: Architecture,
    firmware: Firmware,
    overrides: FirmwareOverrides,
) -> FirmwareSelection | None:
    if firmware is Firmware.BIOS:
        return None
    code = _resolve(
        overrides.uefi_code,
        _DEFAULTS[architecture]["code"],
        "UEFI code",
    )
    variable_override = (
        overrides.uefi_vars_secure_boot
        if firmware.secure_boot
        else overrides.uefi_vars_no_secure_boot
    )
    key = "vars-sb" if firmware.secure_boot else "vars-nosb"
    variables = _resolve(
        variable_override,
        _DEFAULTS[architecture][key],
        "UEFI variable-store template",
    )
    if code == variables:
        raise ConfigurationError("UEFI code and variables must be different files")
    return FirmwareSelection(code=code, variables_template=variables)


def copy_variables(selection: FirmwareSelection, destination: Path) -> Path:
    if destination.exists():
        raise ConfigurationError(
            f"Refusing to overwrite UEFI variable store: {destination}"
        )
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(selection.variables_template, destination)
    destination.chmod(0o600)
    return destination


def _resolve(override: Path | None, candidates: tuple[Path, ...], label: str) -> Path:
    if override is not None:
        path = override.expanduser().resolve(strict=True)
        if not path.is_file():
            raise ConfigurationError(f"{label} is not a regular file: {path}")
        return path
    for candidate in candidates:
        if candidate.is_file():
            return candidate.resolve()
    rendered = ", ".join(str(item) for item in candidates)
    raise ConfigurationError(f"Cannot find {label}; tried: {rendered}")
