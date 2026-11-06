#!/usr/bin/python3
"""Real kernel transitions and independent readback in a disposable ISO guest."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess

from btrfs_rollback_oracle import validate_restart


STORE = Path("/.snapshots/anduinos-btrfs-snapshots-manager")
STATE = Path("/home/anduinos-acceptance-kernel-rollback.json")
MARKER = Path("/etc/anduinos-acceptance-kernel-rollback")
HOME = Path("/home/anduinos-acceptance-kernel-user-data")
CLI = "anduinos-btrfs-snapshots-manager-cli"
REQUIRED = "/mnt/anduinos-acceptance-required"
LOG = Path("/home/anduinos-acceptance-kernel-commands.log")


def run(*args):
    result = subprocess.run(args, text=True, capture_output=True, timeout=1800)
    # Package hooks write diagnostics to stderr even on success. Keep those
    # messages without mixing them into the JSON control response on stdout.
    with LOG.open("a") as log:
        log.write(json.dumps(args) + "\n" + result.stdout + result.stderr + "\n")
    require(result.returncode == 0,
            f"{args[0]} failed ({result.returncode}): " + (result.stdout + result.stderr)[-4000:])
    return result.stdout.strip()


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def digest(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def snapshot_root(identifier):
    return STORE / "deployments" / identifier / "root"


def create_snapshot(title):
    return json.loads(run(CLI, "create", "--json", title,
                          "Disposable cross-kernel acceptance"))["id"]


def root_identity():
    fields = {}
    for line in run("btrfs", "subvolume", "show", "/").splitlines():
        name, separator, value = line.strip().partition(":")
        if separator and name in ("UUID", "Parent UUID"):
            fields[name] = value.strip()
    require(set(fields) == {"UUID", "Parent UUID"}, "Incomplete running root identity")
    return fields


def select_default(kernel):
    """Select a real generated entry, preserving the ordinary GRUB boot path."""
    for name, target in (("vmlinuz", f"vmlinuz-{kernel}"),
                         ("initrd.img", f"initrd.img-{kernel}")):
        path = Path("/boot") / name
        require(path.is_symlink(), f"Expected the managed /boot/{name} symlink")
        path.unlink()
        path.symlink_to(target)
    config = Path("/boot/grub/grub.cfg").read_text()
    submenu = re.search(r"\$menuentry_id_option '([^']*gnulinux-advanced-[^']+)'", config)
    entry = re.search(r"\$menuentry_id_option '([^']*gnulinux-" + re.escape(kernel)
                      + r"-advanced-[^']+)'", config)
    require(submenu and entry, "No generated normal entry for the alternate kernel")
    selection = submenu[1] + ">" + entry[1]
    Path("/etc/default/grub.d/zz-acceptance-kernel.cfg").write_text(
        "GRUB_DEFAULT='" + selection + "'\nGRUB_TIMEOUT=2\n"
    )
    run("update-grub")
    run("grub-script-check", "/boot/grub/grub.cfg")


def prepare(variant):
    require(run("systemd-detect-virt", "--vm") in ("qemu", "kvm"), "Not a disposable QEMU guest")
    require(Path("/dev/disk/by-id/virtio-ANDUINOS-TEST-TARGET").exists(),
            "Acceptance target disk identity is missing")
    require(run("findmnt", "-n", "-o", "FSTYPE", "/") == "btrfs", "Root is not Btrfs")
    require(not STATE.exists() and not MARKER.exists() and not HOME.exists(),
            "Refusing to reuse a kernel rollback workload")
    require(run("/usr/libexec/anduinos-btrfs-snapshots-manager-initramfs",
                "--protocol-version") == "3", "ISO lacks restart-after-restore support")
    require(run("mokutil", "--sb-state") == "SecureBoot enabled",
            "Cross-kernel acceptance must retain Secure Boot")
    initial = os.uname().release
    require(Path("/boot/vmlinuz").resolve().name == "vmlinuz-" + initial,
            "Initial kernel is not the installed default")
    title = "Acceptance " + variant + " kernel rollback"
    fstab = Path("/etc/fstab")
    saved_fstab = fstab.read_text()
    MARKER.write_text("A\n")
    HOME.write_text("A\n")
    if variant == "failed-target":
        # Observation only: preserve the failing boot's journal in the shared
        # /var/log subvolume so fallback cannot pass on an arbitrary power cut.
        # The ordinary five-minute sync interval would lose the final mount
        # failure when this test simulates a user's hard restart after a minute.
        Path("/var/log/journal").mkdir(parents=True, exist_ok=True)
        run("systemd-tmpfiles", "--create", "--prefix=/var/log/journal")
        journal_config = Path("/etc/systemd/journald.conf.d")
        journal_config.mkdir(parents=True, exist_ok=True)
        (journal_config / "90-acceptance-fault.conf").write_text(
            "[Journal]\nStorage=persistent\nSyncIntervalSec=1s\n"
        )
        run("systemctl", "restart", "systemd-journald.service")
        run("journalctl", "--flush")
        Path(REQUIRED).mkdir()
        fstab.write_text(saved_fstab + "\n/dev/disk/by-label/ANDUINOS-ABSENT-ACCEPTANCE "
                         + REQUIRED + " ext4 defaults,x-systemd.device-timeout=5s 0 0\n")
    target = None
    try:
        if variant != "default-kernel":
            target = create_snapshot(title)
    finally:
        fstab.write_text(saved_fstab)

    # Select by actual installed/available ABI, never by suite or a frozen
    # upstream version. Either direction is valid: an ISO may already contain
    # the newest kernel available that day. Missing payloads fail preparation.
    run("apt-get", "-o", "APT::Update::Error-Mode=any", "update")
    installed = {path.name.removeprefix("vmlinuz-") for path in Path("/boot").glob("vmlinuz-*")}
    available = {name.removeprefix("linux-image-") for name in run("apt-cache", "pkgnames").splitlines()
                 if re.fullmatch(r"linux-image-[0-9][0-9.]*-[0-9]+-generic", name)}
    candidates = (installed | available) - {initial}
    require(candidates, "No second Ubuntu kernel ABI is available for real boot acceptance")
    ordered = subprocess.check_output(("sort", "-V"), input="\n".join(candidates), text=True).splitlines()
    alternate = ordered[-1]
    run("apt-get", "--yes", "--no-remove", "--no-install-recommends", "install",
        "linux-image-" + alternate, "linux-modules-" + alternate)
    run("sbverify", "--list", "/boot/vmlinuz-" + alternate)
    require(not run("dpkg", "--audit"), "Kernel installation left unconfigured packages")
    select_default(alternate)
    if variant == "default-kernel":
        # The recorded running ABI is A, but both default boot links now select
        # B. This snapshot must restore B, not metadata's stale running ABI.
        target = create_snapshot(title)
    require(target is not None, "No acceptance snapshot was created")
    root = snapshot_root(target)
    target_kernel = alternate if variant == "default-kernel" else initial
    require((root / "boot/vmlinuz").readlink().name == "vmlinuz-" + target_kernel,
            "Snapshot default kernel differs from the intended target")
    metadata = json.loads((STORE / "metadata" / (target + ".json")).read_text())
    require(metadata["kernel_release"] == initial, "Snapshot did not record the running ABI")
    MARKER.write_text("B\n")
    HOME.write_text("B\n")
    state = dict(variant=variant, title=title, target=target, initial=initial,
                 alternate=alternate, target_kernel=target_kernel,
                 recorded_kernel=metadata["kernel_release"],
                 kernel_sha256=digest(root / "boot" / ("vmlinuz-" + target_kernel)),
                 initrd_sha256=digest(root / "boot" / ("initrd.img-" + target_kernel)))
    STATE.write_text(json.dumps(state))
    os.sync()
    return state


def ready():
    state = json.loads(STATE.read_text())
    require(os.uname().release == state["alternate"], "Alternate Ubuntu kernel did not boot")
    require(MARKER.read_text() == HOME.read_text() == "B\n", "Baseline B is not intact")
    # Recovery protects the original writable root by renaming it. A failed
    # target must return that exact root, rather than clone the safety snapshot.
    state["protected_root"] = root_identity()
    STATE.write_text(json.dumps(state))
    if state["target_kernel"] != state["alternate"]:
        # The current root must not supply the target's modules. The real
        # snapshot retains them; scheduling must use only the current kernel.
        modules = Path("/usr/lib/modules") / state["target_kernel"]
        require(modules.is_dir(), "Expected target modules before the deliberate fault")
        modules.rename(modules.with_name(modules.name + ".acceptance-hidden"))
    return state


def verify():
    state = json.loads(STATE.read_text())
    require(not (STORE / "transactions/pending-rollback.json").exists(), "Rollback is still pending")
    records = [json.loads(path.read_text()) for path in (STORE / "rollback-history").glob("*.json")]
    matches = [record for record in records if record.get("target_deployment_id") == state["target"]]
    require(len(matches) == 1, "Expected one completed cross-kernel transaction")
    record = matches[0]
    require(record["schema_version"] == 7 and record["recovery_protocol_version"] == 3,
            "Cross-kernel restore did not use the restart protocol")
    require(record["kernel_release"] == state["alternate"]
            and record["target_kernel_release"] == state["target_kernel"],
            "Transaction selected the wrong apply or target kernel")
    failed = state["variant"] == "failed-target"
    expected = state["alternate"] if failed else state["target_kernel"]
    require(os.uname().release == expected, "Running kernel does not belong to the selected root")
    require(MARKER.read_text() == ("B\n" if failed else "A\n"), "Wrong system root is running")
    require(HOME.read_text() == "B\n", "System rollback changed independent newer Home data")
    require(record["applying_boot_id"] != record["target_boot_id"], "Restore did not cross a boot boundary")
    selected = record["fallback_deployment_id"] if failed else state["target"]
    identity = root_identity()
    metadata = json.loads((STORE / "metadata" / (selected + ".json")).read_text())
    if failed:
        require(identity == state["protected_root"], "Fallback did not return the protected original root")
    else:
        require(identity["Parent UUID"] == metadata["snapshot_uuid"],
                "Running root is not a child of the selected snapshot")
    require(record["reset_home"] is False and record["home_only"] is False
            and record["purge_history"] is False, "Rollback changed its requested scope")
    if failed:
        require(record["phase"] == "reverted" and record["checkpoint"] == "reverted-recorded",
                "Unconfirmed target did not automatically return to the protected fallback")
        require(record["target_boot_id"] != Path("/proc/sys/kernel/random/boot_id").read_text().strip(),
                "Fallback did not reboot after replacing the target root")
        unit = run("systemd-escape", "--path", "--suffix=mount", REQUIRED)
        # journalctl's boot selector uses compact sd-id128, whereas the
        # recovery transaction stores the canonical UUID from /proc.
        journal = run("journalctl", "--boot=" + record["target_boot_id"].replace("-", ""),
                      "--unit=" + unit, "--output=json", "--no-pager")
        entries = [json.loads(line) for line in journal.splitlines() if line.startswith("{")]
        require(any(item.get("JOB_RESULT") in ("failed", "dependency", "timeout")
                    or "Dependency failed" in item.get("MESSAGE", "") for item in entries),
                "No journal evidence of the deliberately failed required mount")
    else:
        validate_restart(record)
        require(digest("/boot/vmlinuz-" + expected) == state["kernel_sha256"]
                and digest("/boot/initrd.img-" + expected) == state["initrd_sha256"],
                "Restored kernel/initrd differ from the selected snapshot")
    require(not run("dpkg", "--audit"), "Restored package database is inconsistent")
    require(run("mokutil", "--sb-state") == "SecureBoot enabled", "Secure Boot was disabled")
    return dict(state=state, transaction=record, running_kernel=os.uname().release,
                boot_id=Path("/proc/sys/kernel/random/boot_id").read_text().strip())


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("prepare", "ready", "verify"))
    parser.add_argument("variant", nargs="?", choices=("cross-kernel", "failed-target", "default-kernel"))
    args = parser.parse_args()
    print(json.dumps(prepare(args.variant) if args.action == "prepare"
                     else ready() if args.action == "ready" else verify()))
