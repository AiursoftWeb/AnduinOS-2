"""Deterministic desktop fixture artifacts used inside acceptance guests."""

from __future__ import annotations

import hashlib
import os
import shutil
import struct
import subprocess
import tempfile
import urllib.request
from pathlib import Path

from .errors import ConfigurationError
from .model import Architecture


_APPIMAGE_RUNTIMES = {
    Architecture.AMD64: (
        "runtime-x86_64",
        "1cc49bcf1e2ccd593c379adb17c9f85a36d619088296504de95b1d06215aebbf",
    ),
    Architecture.ARM64: (
        "runtime-aarch64",
        "7d5d772b7c32f0c84caf0a452a3072a5709027d7eac5856feb89a7a7a8881372",
    ),
}
_RUNTIME_BASE = (
    "https://github.com/AppImage/type2-runtime/releases/download/continuous"
)


def build_desktop_fixtures(
    architecture: Architecture,
    destination: Path,
) -> tuple[Path, Path]:
    """Build a real Type-2 AppImage and a structurally valid PE fixture."""

    destination.mkdir(parents=True, exist_ok=True)
    appimage = destination / "AnduinOS-Acceptance.AppImage"
    pe = destination / "cpu-z.exe"
    _build_appimage(architecture, appimage)
    _build_pe(pe)
    return appimage, pe


def _build_appimage(architecture: Architecture, destination: Path) -> None:
    if shutil.which("mksquashfs") is None:
        raise ConfigurationError("Required executable is missing: mksquashfs")
    runtime_name, expected_sha256 = _APPIMAGE_RUNTIMES[architecture]
    runtime = _cached_runtime(runtime_name, expected_sha256)
    with tempfile.TemporaryDirectory(prefix="anduinos-appimage-") as directory:
        root = Path(directory)
        appdir = root / "Acceptance.AppDir"
        appdir.mkdir()
        apprun = appdir / "AppRun"
        apprun.write_text(
            "#!/bin/sh\n"
            "exec zenity --info "
            "--title='AnduinOS AppImage Acceptance Fixture' "
            "--text='A real Type-2 AppImage launched successfully.'\n",
            encoding="utf-8",
        )
        apprun.chmod(0o755)
        desktop = appdir / "anduinos-acceptance.desktop"
        desktop.write_text(
            "[Desktop Entry]\n"
            "Type=Application\n"
            "Name=AnduinOS AppImage Acceptance Fixture\n"
            "Exec=AppRun\n"
            "Icon=anduinos-acceptance\n"
            "Categories=Utility;\n",
            encoding="utf-8",
        )
        payload = root / "payload.squashfs"
        result = subprocess.run(
            (
                "mksquashfs",
                str(appdir),
                str(payload),
                "-noappend",
                "-no-progress",
                "-quiet",
            ),
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            timeout=60,
        )
        if result.returncode != 0:
            raise ConfigurationError(
                "Cannot build AppImage SquashFS payload: " + result.stdout.strip()
            )
        temporary = destination.with_suffix(destination.suffix + ".tmp")
        with temporary.open("wb") as output:
            output.write(runtime.read_bytes())
            output.write(payload.read_bytes())
        temporary.chmod(0o755)
        temporary.replace(destination)
    content = destination.read_bytes()
    if content[8:11] != b"AI\x02" or b"hsqs" not in content:
        raise ConfigurationError("Generated fixture is not a Type-2 AppImage")


def _cached_runtime(name: str, expected_sha256: str) -> Path:
    cache_root = Path(
        os.environ.get(
            "XDG_CACHE_HOME",
            str(Path.home() / ".cache"),
        )
    ) / "anduinos-acceptance" / "appimage-runtime"
    cache_root.mkdir(parents=True, exist_ok=True)
    destination = cache_root / f"{name}-{expected_sha256}"
    if destination.is_file() and _sha256(destination) == expected_sha256:
        return destination
    temporary = destination.with_suffix(".download")
    try:
        with urllib.request.urlopen(f"{_RUNTIME_BASE}/{name}", timeout=60) as source:
            with temporary.open("wb") as output:
                shutil.copyfileobj(source, output)
    except OSError as error:
        raise ConfigurationError(
            f"Cannot download the pinned official AppImage runtime {name}: {error}"
        ) from error
    actual = _sha256(temporary)
    if actual != expected_sha256:
        temporary.unlink(missing_ok=True)
        raise ConfigurationError(
            f"Official AppImage runtime digest changed for {name}: "
            f"expected {expected_sha256}, got {actual}"
        )
    temporary.chmod(0o755)
    temporary.replace(destination)
    return destination


def _build_pe(destination: Path) -> None:
    """Create the smallest PE shape accepted by the product's safe validator."""

    content = bytearray(512)
    content[0:2] = b"MZ"
    content[60:64] = struct.pack("<I", 0x80)
    content[0x80:0x84] = b"PE\0\0"
    content[0x84:0x86] = struct.pack("<H", 0x8664)
    destination.write_bytes(content)
    destination.chmod(0o644)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()
