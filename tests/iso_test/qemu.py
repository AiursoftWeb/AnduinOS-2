"""QEMU process and disposable-machine lifecycle."""

from __future__ import annotations

import os
import platform
import shutil
import socket
import subprocess
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path

from .errors import ConfigurationError, ProtocolError
from .firmware import FirmwareSelection
from .model import Architecture, Firmware, Network
from .qmp import QmpClient
from .serial import SerialConsole


@dataclass(frozen=True)
class QemuConfig:
    architecture: Architecture
    firmware: Firmware
    network: Network
    memory_mib: int
    cpus: int
    disk_gib: int
    ssh_forward_port: int
    iso: Path
    disk: Path
    variables: Path | None
    firmware_selection: FirmwareSelection | None
    artifacts: Path
    qemu_binary: str
    acceleration: str


class QemuVm:
    def __init__(self, config: QemuConfig):
        self.config = config
        self.process: subprocess.Popen[bytes] | None = None
        self.qmp: QmpClient | None = None
        self.serial: SerialConsole | None = None
        self._runtime: tempfile.TemporaryDirectory[str] | None = None
        self._log = None

    @property
    def running(self) -> bool:
        return self.process is not None and self.process.poll() is None

    def create_disk(self) -> None:
        if self.config.disk.exists():
            raise ConfigurationError(
                f"Refusing to reuse target disk: {self.config.disk}"
            )
        self.config.disk.parent.mkdir(parents=True, exist_ok=True)
        _run_checked(
            [
                "qemu-img",
                "create",
                "-f",
                "qcow2",
                str(self.config.disk),
                f"{self.config.disk_gib}G",
            ]
        )

    def command(self, *, attach_iso: bool) -> list[str]:
        cfg = self.config
        if self._runtime is None:
            raise RuntimeError("QEMU runtime directory is not initialized")
        runtime = Path(self._runtime.name)
        qmp_path = runtime / "qmp.sock"
        serial_path = runtime / "serial.sock"
        command = [
            cfg.qemu_binary,
            "-name",
            f"AnduinOS acceptance: {cfg.artifacts.name}",
            "-nodefaults",
            "-no-reboot",
            "-m",
            str(cfg.memory_mib),
            "-smp",
            str(cfg.cpus),
            "-display",
            "none",
            "-qmp",
            f"unix:{qmp_path},server=on,wait=off",
            "-chardev",
            f"socket,id=serial0,path={serial_path},server=on,wait=off",
            "-serial",
            "chardev:serial0",
            "-monitor",
            "none",
            "-accel",
            cfg.acceleration,
            "-device",
            "virtio-scsi-pci,id=scsi0",
            "-drive",
            f"file={cfg.disk},if=none,id=target,format=qcow2,cache=writeback",
            "-device",
            "virtio-blk-pci,drive=target,serial=ANDUINOS-TEST-TARGET,bootindex=2",
            "-netdev",
            (
                "user,id=net0,restrict=off,"
                f"hostfwd=tcp:127.0.0.1:{cfg.ssh_forward_port}-:22"
            ),
            "-device",
            "virtio-net-pci,id=nic0,netdev=net0",
            "-device",
            "qemu-xhci,id=xhci",
            "-device",
            "usb-kbd,bus=xhci.0",
            "-device",
            "usb-tablet,bus=xhci.0",
        ]
        if cfg.architecture is Architecture.AMD64:
            machine = "q35,smm=on" if cfg.firmware.is_uefi else "q35"
            command += [
                "-machine",
                machine,
                "-cpu",
                "host" if cfg.acceleration == "kvm" else "max",
                "-device",
                "virtio-vga,id=video0",
                # SeaBIOS and GRUB cannot consume the xHCI keyboard. Keep a
                # legacy controller for pre-boot automation; the USB devices
                # remain the normal GNOME input path.
                "-device",
                "i8042",
            ]
            if cfg.firmware.secure_boot:
                command += [
                    "-global",
                    "driver=cfi.pflash01,property=secure,value=on",
                ]
        else:
            cpu = "host" if cfg.acceleration == "kvm" else "neoverse-n1"
            command += [
                "-machine",
                "virt,gic-version=3",
                "-cpu",
                cpu,
                "-device",
                "virtio-gpu-pci,id=video0",
            ]
        if cfg.firmware_selection is not None:
            if cfg.variables is None:
                raise ConfigurationError("UEFI VM has no writable variable store")
            command += [
                "-drive",
                (
                    "if=pflash,format=raw,readonly=on,file="
                    f"{cfg.firmware_selection.code}"
                ),
                "-drive",
                f"if=pflash,format=raw,file={cfg.variables}",
            ]
        if attach_iso:
            command += [
                "-drive",
                f"file={cfg.iso},if=none,id=cdrom,format=raw,readonly=on",
                "-device",
                "scsi-cd,bus=scsi0.0,drive=cdrom,bootindex=1",
            ]
        return command

    def start(self, *, attach_iso: bool) -> None:
        if self.running:
            raise RuntimeError("QEMU is already running")
        self._runtime = tempfile.TemporaryDirectory(prefix="anduinos-qemu-")
        runtime = Path(self._runtime.name)
        qmp_path = runtime / "qmp.sock"
        serial_path = runtime / "serial.sock"
        self.config.artifacts.mkdir(parents=True, exist_ok=True)
        log_path = self.config.artifacts / (
            "qemu-live.log" if attach_iso else "qemu-installed.log"
        )
        self._log = log_path.open("wb")
        command = self.command(attach_iso=attach_iso)
        (self.config.artifacts / (
            "qemu-live.command" if attach_iso else "qemu-installed.command"
        )).write_text(_shell_render(command) + "\n", encoding="utf-8")
        self.process = subprocess.Popen(
            command,
            stdin=subprocess.DEVNULL,
            stdout=self._log,
            stderr=subprocess.STDOUT,
        )
        self.qmp = QmpClient(qmp_path, timeout=30)
        self.qmp.connect()
        if self.config.network is Network.OFFLINE:
            self.qmp.set_link("nic0", up=False)
        transcript = self.config.artifacts / (
            "serial-live.log" if attach_iso else "serial-installed.log"
        )
        self.serial = SerialConsole(serial_path, transcript, timeout=30)
        self.serial.connect()

    def screenshot(self, name: str) -> Path:
        if self.qmp is None:
            raise ProtocolError("QMP is not connected")
        destination = self.config.artifacts / f"{name}.ppm"
        self.qmp.screendump(destination)
        return destination

    def wait(self, timeout: float) -> int:
        if self.process is None:
            raise RuntimeError("QEMU was not started")
        try:
            return self.process.wait(timeout=timeout)
        except subprocess.TimeoutExpired as error:
            raise ProtocolError("QEMU did not stop before the timeout") from error

    def stop(self) -> None:
        if self.qmp is not None:
            self.qmp.quit()
            self.qmp.close()
            self.qmp = None
        if self.process is not None:
            try:
                self.process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                self.process.terminate()
                try:
                    self.process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    self.process.kill()
                    self.process.wait(timeout=5)
            self.process = None
        if self.serial is not None:
            self.serial.close()
            self.serial = None
        if self._log is not None:
            self._log.close()
            self._log = None
        if self._runtime is not None:
            self._runtime.cleanup()
            self._runtime = None


def resolve_qemu(architecture: Architecture) -> tuple[str, str]:
    binary_name = (
        "qemu-system-x86_64"
        if architecture is Architecture.AMD64
        else "qemu-system-aarch64"
    )
    binary = shutil.which(binary_name)
    if binary is None:
        raise ConfigurationError(f"Required executable is missing: {binary_name}")
    if shutil.which("qemu-img") is None:
        raise ConfigurationError("Required executable is missing: qemu-img")
    host = platform.machine().lower()
    native = (
        architecture is Architecture.AMD64 and host in {"x86_64", "amd64"}
    ) or (
        architecture is Architecture.ARM64 and host in {"aarch64", "arm64"}
    )
    use_kvm = native and os.access("/dev/kvm", os.R_OK | os.W_OK)
    return binary, "kvm" if use_kvm else "tcg,thread=multi"


def allocate_tcp_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.bind(("127.0.0.1", 0))
        return int(listener.getsockname()[1])


def _run_checked(command: list[str]) -> None:
    result = subprocess.run(
        command,
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        timeout=60,
    )
    if result.returncode != 0:
        raise ConfigurationError(
            f"Command failed ({command[0]}): {result.stdout.strip()}"
        )


def _shell_render(command: list[str]) -> str:
    import shlex

    return shlex.join(command)
