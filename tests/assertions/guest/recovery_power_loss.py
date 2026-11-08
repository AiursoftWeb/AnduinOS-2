"""Reversible observation/fault injection for the disposable recovery VM only."""

import os
import json
from pathlib import Path
import re
import sys
import tempfile


CONFIRM = "anduinos-btrfs-snapshots-manager-confirm.service"


def instrument(text, architecture, *, restore=False):
    if architecture not in ("amd64", "arm64"):
        raise ValueError("Unsupported serial architecture")
    tty = "ttyS0" if architecture == "amd64" else "ttyAMA0"
    suffix = f" console={tty},115200 systemd.mask={CONFIRM}"
    if restore:
        # Recovery may already have regenerated GRUB and removed the entry.
        return text.replace(suffix, "")
    lines = text.splitlines(keepends=True)
    targets = [i for i, line in enumerate(lines) if re.match(r"\s*linux\s", line)
               and " anduinos.btrfs_snapshots_manager=" in line]
    if len(targets) != 1:
        raise ValueError("Expected exactly one armed product recovery entry")
    index = targets[0]
    if any(arg in lines[index] for arg in ("console=", "systemd.mask=", "systemd.debug_shell=")):
        raise ValueError("Recovery entry already has test/console overrides")
    lines[index] = lines[index].rstrip("\n") + suffix + "\n"
    return "".join(lines)


def main():
    mode, architecture, *version = sys.argv[1:]
    if version == ["3"]:
        # v3 completes apply and reboots before userspace. Its target GRUB file
        # comes from the immutable snapshot, not the current root. Read that
        # entry so the host can add a one-boot mask in the actual menu editor;
        # never modify the snapshot or leave a persistent unit mask behind.
        pending = Path("/.snapshots/anduinos-btrfs-snapshots-manager/transactions/pending-rollback.json")
        transaction = json.loads(pending.read_text())
        identifier = transaction["target_deployment_id"]
        config = pending.parents[1] / "deployments" / identifier / "root/boot/grub/grub.cfg"
        lines = config.read_text().splitlines()
        start = next(i for i, line in enumerate(lines) if line.startswith("menuentry "))
        linux = next(i for i in range(start + 1, len(lines))
                     if re.match(r"\s*linux\s", lines[i]))
        # GRUB prepends setparams to the entry body in its editor. The body
        # still starts with the newline after the opening brace, so its linux
        # command is one Down beyond the offset in grub.cfg. Without this,
        # the one-boot fault parameters are appended to search, not linux.
        print(f"target-editor-kernel-line={linux - start + 1}")
        return
    if mode not in ("prepare", "restore"):
        raise ValueError("Unknown instrumentation mode")
    config = Path("/boot/grub/grub.cfg")
    if config.is_symlink() or not config.is_file():
        raise ValueError("Expected a regular installed GRUB configuration")
    original = config.read_text()
    changed = instrument(original, architecture, restore=mode == "restore")
    metadata = config.stat()
    fd, temporary = tempfile.mkstemp(prefix=".acceptance-power-loss-", dir=config.parent)
    try:
        with os.fdopen(fd, "w") as output:
            os.fchmod(output.fileno(), metadata.st_mode & 0o7777)
            os.fchown(output.fileno(), metadata.st_uid, metadata.st_gid)
            output.write(changed)
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, config)
        os.sync()
    finally:
        Path(temporary).unlink(missing_ok=True)
    print(f"power-loss-instrumentation={mode}")


if __name__ == "__main__":
    main()
