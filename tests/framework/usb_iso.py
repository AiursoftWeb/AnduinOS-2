"""Build disposable FAT media using Rufus's label-replacement semantics.

This models ISO mode, not the Windows executable. Never repair parameter names
after rewriting: doing so would conceal the regression this test must catch.
"""
from __future__ import annotations

import hashlib
import re
import shlex
import struct
import subprocess
from pathlib import Path

from .errors import TestFailure
from .iso import volume_label

TOKENS = {"options", "append", "linux", "linuxefi", "$linux", "search", "for"}
OFFSET = 1024 * 1024


def rewrite_config(content: str, source_label: str, usb_label: str) -> str:
    # Rufus src/iso.c + parser.c: case-insensitive leading token matching,
    # case-sensitive substring replacement, at most four occurrences per line.
    source = source_label.replace(" ", r"\x20")
    target = usb_label.replace(" ", r"\x20")
    return "".join(
        line.replace(source, target, 4)
        if line.strip() and line.lstrip().split(None, 1)[0].lower() in TOKENS
        else line
        for line in content.splitlines(keepends=True)
    )


def assert_preserved_arguments(before: str, after: str, source: str, target: str) -> None:
    def entries(text):
        return [shlex.split(line.strip())[1:] for line in text.splitlines()
                if re.match(r"^\s*linux\s", line)]
    old, new = entries(before), entries(after)
    if not old or len(old) != len(new):
        raise TestFailure("ISO-mode fixture has no matching Linux entries")
    for original, rewritten in zip(old, new):
        expected = [f"root=live:CDLABEL={target}" if arg == f"root=live:CDLABEL={source}"
                    else arg for arg in original]
        if rewritten != expected:
            raise TestFailure("Rufus label rewriting changes non-label boot arguments: "
                              + " ".join(rewritten))


def run(*command: str, **kwargs):
    return subprocess.run(command, check=True, stdout=subprocess.PIPE,
                          stderr=subprocess.PIPE, timeout=300, **kwargs)


def prepare_iso_usb(iso: Path, work: Path, usb_label: str) -> Path:
    if not re.fullmatch(r"[A-Z0-9_]{1,11}", usb_label):
        raise ValueError("Unsafe FAT test label")
    tree = work / "tree"
    tree.mkdir()
    run("xorriso", "-osirrox", "on", "-indev", str(iso), "-extract", "/", str(tree))
    # xorriso preserves read-only directory modes. Only our private extraction
    # tree is made writable; the supplied ISO remains untouched.
    for directory in [tree, *(p for p in tree.rglob('*') if p.is_dir() and not p.is_symlink())]:
        directory.chmod(directory.stat().st_mode | 0o700)
    efi = tree / "EFI/BOOT"
    efi.mkdir(parents=True, exist_ok=True)
    run("mcopy", "-o", "-i", str(tree / "EFI/efiboot.img"), "::/EFI/BOOT/*", str(efi))
    source = volume_label(iso)
    main = tree / "boot/grub/grub.cfg"
    before = main.read_text()
    after = rewrite_config(before, source, usb_label)
    assert_preserved_arguments(before, after, source, usb_label)
    for path in tree.rglob('*'):
        if path.is_file() and not path.is_symlink() and path.suffix.lower() in {'.cfg', '.conf'}:
            path.chmod(path.stat().st_mode | 0o600)
            path.write_text(rewrite_config(path.read_text(), source, usb_label))
    (work.parent / f"grub-{usb_label}.cfg").write_text(after)
    image = work / "live-media.raw"
    size = ((iso.stat().st_size + 1024**3 + OFFSET - 1) // OFFSET) * OFFSET
    with image.open('xb') as stream:
        stream.truncate(size)
        mbr = bytearray(512)
        mbr[446:462] = struct.pack('<B3sB3sII', 0x80, b'\xfe\xff\xff', 0x0c,
                                   b'\xfe\xff\xff', OFFSET // 512, (size-OFFSET)//512)
        mbr[510:512] = b'\x55\xaa'
        stream.seek(0)
        stream.write(mbr)
    run("mkfs.vfat", "-F", "32", "-n", usb_label, "--offset", str(OFFSET//512), str(image))
    spec = f"{image}@@{OFFSET}"
    run("mcopy", "-s", "-i", spec, *(str(p) for p in tree.iterdir()), "::/")
    # Prove extraction did not corrupt the actual system payload.
    digest = hashlib.md5()
    with (tree / 'LiveOS/rootfs.squashfs').open('rb') as stream:
        while block := stream.read(4*1024*1024):
            digest.update(block)
    with subprocess.Popen(['mtype', '-i', spec, '::/LiveOS/rootfs.squashfs'], stdout=subprocess.PIPE) as proc:
        copied = hashlib.md5()
        while block := proc.stdout.read(4*1024*1024):
            copied.update(block)
        if proc.wait() or copied.digest() != digest.digest():
            raise TestFailure("FAT fixture system payload differs from ISO")
    (work.parent / f"payload-{usb_label}.md5").write_text(digest.hexdigest() + '\n')
    return image
