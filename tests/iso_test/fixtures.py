"""Deterministic desktop fixture artifacts used inside acceptance guests."""

from __future__ import annotations

import hashlib
import io
import os
import shutil
import struct
import subprocess
import tempfile
import urllib.request
from dataclasses import dataclass
from pathlib import Path

from PIL import Image, ImageDraw

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


@dataclass(frozen=True)
class FileIntegrationFixtures:
    image: Path
    video: Path
    deb: Path
    text: Path


def build_file_integration_fixtures(destination: Path) -> FileIntegrationFixtures:
    """Build small redistributable files for real desktop integration tests."""

    destination.mkdir(parents=True, exist_ok=True)
    image = destination / "AnduinOS-Image.png"
    video = destination / "AnduinOS-Video.mp4"
    deb = destination / "anduinos-acceptance-fixture_1.0_all.deb"
    text = destination / "AnduinOS-Chinese.txt"

    fixture_image = Image.new("RGB", (320, 240), (0, 0, 0))
    draw = ImageDraw.Draw(fixture_image)
    draw.rectangle((0, 0, 159, 119), fill=(235, 45, 55))
    draw.rectangle((160, 0, 319, 119), fill=(45, 210, 90))
    draw.rectangle((0, 120, 159, 239), fill=(45, 100, 235))
    draw.rectangle((160, 120, 319, 239), fill=(245, 210, 40))
    draw.rectangle((12, 12, 307, 227), outline=(255, 255, 255), width=5)
    fixture_image.save(image, format="PNG")

    if shutil.which("ffmpeg") is None:
        raise ConfigurationError("Required executable is missing: ffmpeg")
    video.unlink(missing_ok=True)
    encoded = subprocess.run(
        (
            "ffmpeg",
            "-hide_banner",
            "-loglevel",
            "error",
            "-loop",
            "1",
            "-i",
            str(image),
            "-t",
            "3",
            "-r",
            "12",
            "-c:v",
            "mpeg4",
            "-q:v",
            "2",
            "-pix_fmt",
            "yuv420p",
            "-movflags",
            "+faststart",
            "-an",
            "-y",
            str(video),
        ),
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        timeout=60,
    )
    if encoded.returncode != 0 or not video.is_file() or video.stat().st_size < 1024:
        raise ConfigurationError(
            "Cannot build deterministic MP4 fixture: " + encoded.stdout.strip()
        )

    if shutil.which("dpkg-deb") is None:
        raise ConfigurationError("Required executable is missing: dpkg-deb")
    package_root = destination / ".deb-root"
    shutil.rmtree(package_root, ignore_errors=True)
    control = package_root / "DEBIAN" / "control"
    control.parent.mkdir(parents=True)
    control.write_text(
        "Package: anduinos-acceptance-fixture\n"
        "Version: 1.0\n"
        "Architecture: all\n"
        "Maintainer: AnduinOS Test Framework <noreply@anduinos.com>\n"
        "Section: utils\n"
        "Priority: optional\n"
        "Description: AnduinOS Acceptance Fixture\n"
        " Harmless local-package page fixture. It must never be installed.\n",
        encoding="utf-8",
    )
    readme = (
        package_root
        / "usr"
        / "share"
        / "doc"
        / "anduinos-acceptance-fixture"
        / "README"
    )
    readme.parent.mkdir(parents=True)
    readme.write_text(
        "This package exists only as an unopened acceptance-test fixture.\n",
        encoding="utf-8",
    )
    fixture_epoch = 1_700_000_000
    for path in sorted(package_root.rglob("*"), reverse=True):
        os.utime(path, (fixture_epoch, fixture_epoch), follow_symlinks=False)
    os.utime(package_root, (fixture_epoch, fixture_epoch))
    deb.unlink(missing_ok=True)
    packaged = subprocess.run(
        ("dpkg-deb", "--build", "--root-owner-group", str(package_root), str(deb)),
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        timeout=30,
        env={**os.environ, "SOURCE_DATE_EPOCH": str(fixture_epoch)},
    )
    shutil.rmtree(package_root, ignore_errors=True)
    if packaged.returncode != 0 or not deb.is_file():
        raise ConfigurationError(
            "Cannot build harmless DEB fixture: " + packaged.stdout.strip()
        )

    text.write_text("", encoding="utf-8")
    return FileIntegrationFixtures(image=image, video=video, deb=deb, text=text)


def build_appimage_fixture(
    architecture: Architecture,
    destination: Path,
) -> Path:
    """Build the architecture-specific real Type-2 AppImage fixture."""

    destination.mkdir(parents=True, exist_ok=True)
    appimage = destination / "AnduinOS-Acceptance.AppImage"
    _build_appimage(architecture, appimage)
    return appimage


def build_windows_executable_fixture(destination: Path) -> Path:
    """Build the structurally valid CPU-Z-named PE fixture."""

    destination.mkdir(parents=True, exist_ok=True)
    pe = destination / "cpu-z.exe"
    _build_pe(pe)
    return pe


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
    """Create a harmless PE64 fixture with a deterministic embedded icon."""

    icon = Image.new("RGB", (256, 256), (52, 18, 116))
    draw = ImageDraw.Draw(icon)
    draw.rounded_rectangle((52, 52, 204, 204), radius=12, fill="white")
    draw.rectangle((75, 75, 181, 181), fill=(52, 18, 116))
    draw.rounded_rectangle((100, 100, 156, 156), radius=10, fill="white")
    icon_stream = io.BytesIO()
    icon.save(icon_stream, format="PNG")
    icon_data = icon_stream.getvalue()

    resource_rva = 0x1000
    resource = _build_pe_icon_resources(icon_data, resource_rva)
    file_alignment = 0x200
    section_alignment = 0x1000
    headers_size = 0x200
    raw_size = _align_up(len(resource), file_alignment)
    content = bytearray(headers_size + raw_size)

    content[0:2] = b"MZ"
    struct.pack_into("<I", content, 60, 0x80)
    content[0x80:0x84] = b"PE\0\0"

    coff = 0x84
    struct.pack_into(
        "<HHIIIHH",
        content,
        coff,
        0x8664,  # AMD64; the fixture is data-only and is never executed directly.
        1,
        0,
        0,
        0,
        0xF0,
        0x0022,
    )
    optional = coff + 20
    struct.pack_into("<H", content, optional, 0x20B)
    struct.pack_into("<I", content, optional + 8, raw_size)
    struct.pack_into("<I", content, optional + 20, resource_rva)
    struct.pack_into("<Q", content, optional + 24, 0x140000000)
    struct.pack_into("<I", content, optional + 32, section_alignment)
    struct.pack_into("<I", content, optional + 36, file_alignment)
    struct.pack_into("<HH", content, optional + 40, 6, 0)
    struct.pack_into("<HH", content, optional + 48, 6, 0)
    struct.pack_into("<I", content, optional + 56, 0x2000)
    struct.pack_into("<I", content, optional + 60, headers_size)
    struct.pack_into("<H", content, optional + 68, 2)
    struct.pack_into("<H", content, optional + 70, 0x8160)
    struct.pack_into("<QQQQ", content, optional + 72, 0x100000, 0x1000, 0x100000, 0x1000)
    struct.pack_into("<I", content, optional + 108, 16)
    struct.pack_into("<II", content, optional + 128, resource_rva, len(resource))

    section = optional + 0xF0
    content[section : section + 8] = b".rsrc\0\0\0"
    struct.pack_into("<I", content, section + 8, len(resource))
    struct.pack_into("<I", content, section + 12, resource_rva)
    struct.pack_into("<I", content, section + 16, raw_size)
    struct.pack_into("<I", content, section + 20, headers_size)
    struct.pack_into("<I", content, section + 36, 0x40000040)
    content[headers_size : headers_size + len(resource)] = resource

    destination.write_bytes(content)
    destination.chmod(0o644)


def _build_pe_icon_resources(icon_data: bytes, resource_rva: int) -> bytes:
    """Build RT_ICON/RT_GROUP_ICON directories understood by icoextract."""

    root = 0x00
    icon_type = 0x20
    icon_name = 0x38
    icon_entry = 0x50
    group_type = 0x60
    group_name = 0x78
    group_entry = 0x90
    icon_offset = 0xA0
    group_offset = _align_up(icon_offset + len(icon_data), 4)
    group_data = struct.pack(
        "<HHHBBBBHHIH",
        0,
        1,
        1,
        0,  # ICO encodes 256-pixel width and height as zero bytes.
        0,
        0,
        0,
        1,
        32,
        len(icon_data),
        1,
    )
    resources = bytearray(group_offset + len(group_data))

    def directory(offset: int, entries: tuple[tuple[int, int, bool], ...]) -> None:
        struct.pack_into("<IIHHHH", resources, offset, 0, 0, 0, 0, 0, len(entries))
        for index, (identifier, target, is_directory) in enumerate(entries):
            value = target | (0x80000000 if is_directory else 0)
            struct.pack_into("<II", resources, offset + 16 + index * 8, identifier, value)

    directory(root, ((3, icon_type, True), (14, group_type, True)))
    directory(icon_type, ((1, icon_name, True),))
    directory(icon_name, ((0x409, icon_entry, False),))
    directory(group_type, ((1, group_name, True),))
    directory(group_name, ((0x409, group_entry, False),))
    struct.pack_into(
        "<IIII",
        resources,
        icon_entry,
        resource_rva + icon_offset,
        len(icon_data),
        0,
        0,
    )
    struct.pack_into(
        "<IIII",
        resources,
        group_entry,
        resource_rva + group_offset,
        len(group_data),
        0,
        0,
    )
    resources[icon_offset : icon_offset + len(icon_data)] = icon_data
    resources[group_offset : group_offset + len(group_data)] = group_data
    return bytes(resources)


def _align_up(value: int, alignment: int) -> int:
    return (value + alignment - 1) // alignment * alignment


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()
