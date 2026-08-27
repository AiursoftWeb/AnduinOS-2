"""QEMU process and disposable-machine lifecycle."""

from __future__ import annotations

import os
import platform
import resource
import shutil
import socket
import subprocess
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path

from PIL import Image, UnidentifiedImageError

from .errors import ConfigurationError, ProtocolError
from .firmware import FirmwareSelection
from .model import Architecture, Firmware, Network
from .process_lifecycle import parent_death_preexec
from .qmp import QmpClient
from .serial import SerialConsole


PERSISTENT_LIVE_FREE_SPACE_GIB = 4


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
    file_size_limit_bytes: int | None = None
    backing_disk: Path | None = None
    live_media: Path | None = None


class QemuVm:
    def __init__(self, config: QemuConfig):
        self.config = config
        self.process: subprocess.Popen[bytes] | None = None
        self.qmp: QmpClient | None = None
        self.serial: SerialConsole | None = None
        self._runtime: tempfile.TemporaryDirectory[str] | None = None
        self._log = None
        self._live_media_attached = False

    @property
    def spice_socket(self) -> Path:
        if self._runtime is None:
            raise RuntimeError("QEMU runtime directory is not initialized")
        return Path(self._runtime.name) / "spice.sock"

    @property
    def running(self) -> bool:
        return self.process is not None and self.process.poll() is None

    @property
    def live_media_attached(self) -> bool:
        return self._live_media_attached

    def create_disk(self) -> None:
        if self.config.disk.exists():
            raise ConfigurationError(
                f"Refusing to reuse target disk: {self.config.disk}"
            )
        self.config.disk.parent.mkdir(parents=True, exist_ok=True)
        command = ["qemu-img", "create", "-f", "qcow2"]
        if self.config.backing_disk is not None:
            try:
                backing = self.config.backing_disk.resolve(strict=True)
            except OSError as error:
                raise ConfigurationError(
                    f"Overlay backing disk is unavailable: {error}"
                ) from error
            if not backing.is_file() or backing.is_symlink():
                raise ConfigurationError(
                    f"Overlay backing disk is not a regular file: {backing}"
                )
            if backing == self.config.disk.resolve():
                raise ConfigurationError("Overlay cannot back itself")
            command.extend(("-F", "qcow2", "-b", str(backing)))
        command.extend((str(self.config.disk), f"{self.config.disk_gib}G"))
        _run_checked(command)

    def create_live_media(self) -> None:
        """Copy the ISO to a writable, extended USB-like hybrid image."""

        destination = self.config.live_media
        if destination is None:
            return
        if destination.name != "live-media.raw" or destination.is_symlink():
            raise ConfigurationError(
                f"Refusing unexpected persistent Live-media target: {destination}"
            )
        if destination.exists():
            raise ConfigurationError(
                f"Refusing to reuse persistent Live media: {destination}"
            )
        source = self.config.iso.resolve(strict=True)
        if not source.is_file() or source.is_symlink():
            raise ConfigurationError(f"ISO is not a regular file: {source}")
        destination.parent.mkdir(parents=True, exist_ok=True)
        try:
            shutil.copyfile(source, destination)
            with destination.open("r+b") as stream:
                stream.truncate(
                    source.stat().st_size + PERSISTENT_LIVE_FREE_SPACE_GIB * 1024**3
                )
        except BaseException:
            destination.unlink(missing_ok=True)
            raise

    def command(self, *, attach_iso: bool) -> list[str]:
        cfg = self.config
        if self._runtime is None:
            raise RuntimeError("QEMU runtime directory is not initialized")
        runtime = Path(self._runtime.name)
        qmp_path = runtime / "qmp.sock"
        serial_path = runtime / "serial.sock"
        spice_path = runtime / "spice.sock"
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
            "-spice",
            f"unix=on,addr={spice_path},disable-ticketing=on",
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
            "-device",
            "virtio-serial-pci,id=virtio-serial0",
            "-chardev",
            "spicevmc,id=vdagent,name=vdagent",
            "-device",
            "virtserialport,chardev=vdagent,name=com.redhat.spice.0",
        ]
        if cfg.architecture is Architecture.AMD64:
            # q35 already creates its chipset i8042/PS2 controller even with
            # -nodefaults.  Adding a second `-device i8042` duplicates the
            # firmware's KBD/MOU ACPI namespace and pollutes the guest journal.
            machine = "q35,smm=on" if cfg.firmware.is_uefi else "q35"
            command += [
                "-machine",
                machine,
                "-cpu",
                "host" if cfg.acceleration == "kvm" else "max",
                "-device",
                "virtio-vga,id=video0",
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
            if cfg.live_media is None:
                command += [
                    "-drive",
                    f"file={cfg.iso},if=none,id=cdrom,format=raw,readonly=on",
                    "-device",
                    "scsi-cd,bus=scsi0.0,drive=cdrom,bootindex=1",
                ]
            else:
                command += [
                    "-drive",
                    (
                        f"file={cfg.live_media},if=none,id=live-media,"
                        "format=raw,cache=writeback"
                    ),
                    "-device",
                    (
                        "scsi-hd,bus=scsi0.0,drive=live-media,"
                        "serial=ANDUINOS-TEST-LIVE,bootindex=1"
                    ),
                ]
        return command

    def start(self, *, attach_iso: bool, phase: str | None = None) -> None:
        if self.running:
            raise RuntimeError("QEMU is already running")
        self._runtime = tempfile.TemporaryDirectory(prefix="anduinos-qemu-")
        runtime = Path(self._runtime.name)
        qmp_path = runtime / "qmp.sock"
        serial_path = runtime / "serial.sock"
        self.config.artifacts.mkdir(parents=True, exist_ok=True)
        stem = phase or ("live" if attach_iso else "installed")
        log_path = self.config.artifacts / f"qemu-{stem}.log"
        self._log = log_path.open("wb")
        command = self.command(attach_iso=attach_iso)
        (self.config.artifacts / f"qemu-{stem}.command").write_text(
            _shell_render(command) + "\n", encoding="utf-8"
        )
        limiter = (
            _file_size_limiter(self.config.file_size_limit_bytes)
            if self.config.file_size_limit_bytes is not None
            else None
        )
        self.process = subprocess.Popen(
            command,
            stdin=subprocess.DEVNULL,
            stdout=self._log,
            stderr=subprocess.STDOUT,
            preexec_fn=parent_death_preexec(limiter),
        )
        self._live_media_attached = attach_iso and self.config.live_media is not None
        self.qmp = QmpClient(qmp_path, timeout=30)
        self.qmp.connect()
        if self.config.network is not Network.ONLINE:
            self.qmp.set_link("nic0", up=False)
        transcript = self.config.artifacts / f"serial-{stem}.log"
        self.serial = SerialConsole(serial_path, transcript, timeout=30)
        self.serial.connect()

    def screenshot(self, name: str) -> Path:
        if self.qmp is None:
            raise ProtocolError("QMP is not connected")
        # QMP screendump is universally available as an uncompressed PPM, but
        # retaining every 1280x800 frame in that form consumes roughly 3 MiB.
        # A full matrix captures dozens of frames, so immediately encode the
        # exact pixels losslessly and keep only the substantially smaller PNG.
        raw = self.config.artifacts / f".{name}.capture.ppm"
        encoded = self.config.artifacts / f".{name}.capture.png"
        destination = self.config.artifacts / f"{name}.png"
        raw.unlink(missing_ok=True)
        encoded.unlink(missing_ok=True)
        try:
            self.qmp.screendump(raw)
            with Image.open(raw) as source:
                source.load()
                if source.format != "PPM":
                    raise ProtocolError(
                        f"QMP returned an unexpected screenshot format: {source.format}"
                    )
                source.save(encoded, format="PNG", compress_level=6)
            os.replace(encoded, destination)
        except (OSError, UnidentifiedImageError) as error:
            raise ProtocolError(
                f"Could not retain QMP screenshot {name!r} as PNG: {error}"
            ) from error
        finally:
            raw.unlink(missing_ok=True)
            encoded.unlink(missing_ok=True)
        return destination

    def wait(self, timeout: float) -> int:
        if self.process is None:
            raise RuntimeError("QEMU was not started")
        try:
            return self.process.wait(timeout=timeout)
        except subprocess.TimeoutExpired as error:
            raise ProtocolError("QEMU did not stop before the timeout") from error

    def stop(self) -> None:
        # Shutdown is deliberately best-effort across independent resources.
        # A stale QMP/serial socket must never skip process termination and
        # leave the multi-gigabyte target disk in use.
        qmp = self.qmp
        self.qmp = None
        if qmp is not None:
            try:
                qmp.quit()
            except Exception:
                pass
            try:
                qmp.close()
            except Exception:
                pass

        process = self.process
        if process is not None:
            if process.poll() is None:
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    try:
                        process.terminate()
                        process.wait(timeout=5)
                    except (subprocess.TimeoutExpired, OSError):
                        pass
                except OSError:
                    pass
                finally:
                    if process.poll() is None:
                        process.kill()
                        process.wait(timeout=5)
            if process.poll() is None:
                raise ProtocolError("QEMU remained alive after SIGKILL")
            self.process = None
        self._live_media_attached = False

        serial = self.serial
        self.serial = None
        if serial is not None:
            try:
                serial.close()
            except Exception:
                pass

        log = self._log
        self._log = None
        if log is not None:
            try:
                log.close()
            except Exception:
                pass

        runtime = self._runtime
        self._runtime = None
        if runtime is not None:
            try:
                runtime.cleanup()
            except OSError:
                pass


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


def _file_size_limiter(limit_bytes: int):
    """Return the minimal child hook that hard-limits RAM-backed qcow growth."""

    def apply_limit() -> None:
        resource.setrlimit(resource.RLIMIT_FSIZE, (limit_bytes, limit_bytes))

    return apply_limit


def _shell_render(command: list[str]) -> str:
    import shlex

    return shlex.join(command)
