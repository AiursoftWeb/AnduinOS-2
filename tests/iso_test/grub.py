"""Keyboard-driven, non-persistent GRUB command-line injection."""

from __future__ import annotations

import time
from dataclasses import dataclass

from .errors import ProtocolError
from .model import Architecture, Filesystem
from .qmp import QmpClient
from .serial import SerialConsole


@dataclass(frozen=True)
class InstalledBootFiles:
    """Exact target-owned kernel paths discovered after installation."""

    kernel: str
    initrd: str


def debug_kernel_arguments(architecture: Architecture) -> str:
    tty = "ttyS0" if architecture is Architecture.AMD64 else "ttyAMA0"
    return (
        f" console={tty},115200"
        f" systemd.mask=serial-getty@{tty}.service"
        f" systemd.debug_shell={tty}"
    )


def boot_iso_with_debug_shell(
    qmp: QmpClient,
    console: SerialConsole,
    architecture: Architecture,
    *,
    firmware_delay: float,
    synchronize_prompt: bool = False,
) -> None:
    """Boot the known immutable Casper paths from GRUB's command line."""

    time.sleep(firmware_delay)
    qmp.send_key("c")
    if not synchronize_prompt:
        time.sleep(2.0)
    else:
        # shim-backed Secure Boot has a variable terminal-switch delay. The
        # serial GRUB prompt is a deterministic synchronization boundary;
        # fixed sleeps can lose the first characters of the kernel command.
        console.wait_for_text("grub>", timeout=30)
        time.sleep(0.25)
    kernel = (
        "linux /casper/vmlinuz boot=casper nopersistent"
        + debug_kernel_arguments(architecture)
    )
    _submit_grub_command(qmp, console, kernel, synchronize_prompt)
    _submit_grub_command(
        qmp, console, "initrd /casper/initrd", synchronize_prompt
    )
    qmp.type_text("boot")
    _commit_boot(qmp, console)


def boot_installed_with_debug_shell(
    qmp: QmpClient,
    console: SerialConsole,
    architecture: Architecture,
    filesystem: Filesystem,
    boot_files: InstalledBootFiles,
    *,
    firmware_delay: float,
) -> None:
    """Use the installed GRUB and its one-shot visible menu to boot target."""

    time.sleep(firmware_delay)
    qmp.send_key("c")
    time.sleep(2.0)
    commands = [
        f"search --file --set=root {boot_files.kernel}",
        "probe --set=root_uuid --fs-uuid $root",
        (
            f"linux {boot_files.kernel} root=UUID=$root_uuid"
            + (
                " rootflags=subvol=@root"
                if filesystem is Filesystem.BTRFS
                else ""
            )
            + " ro"
            + debug_kernel_arguments(architecture)
        ),
        f"initrd {boot_files.initrd}",
    ]
    for command in commands:
        qmp.type_text(command)
        qmp.send_key("ret", hold_ms=100)
        time.sleep(0.75)
    qmp.type_text("boot")
    _commit_boot(qmp, console)


def _submit_grub_command(
    qmp: QmpClient,
    console: SerialConsole,
    command: str,
    synchronize_prompt: bool,
) -> None:
    qmp.type_text(command)
    qmp.send_key("ret", hold_ms=100)
    if synchronize_prompt:
        console.wait_for_text("grub>", timeout=30)
        time.sleep(0.25)
    else:
        time.sleep(0.75)


def _commit_boot(qmp: QmpClient, console: SerialConsole) -> None:
    """Do not let shell probes race a GRUB command awaiting Enter."""

    last_error: ProtocolError | None = None
    for _ in range(3):
        qmp.send_key("ret", hold_ms=150)
        try:
            console.wait_for_text("Linux version", timeout=15)
            return
        except ProtocolError as error:
            last_error = error
    raise ProtocolError("GRUB did not start the selected kernel") from last_error
