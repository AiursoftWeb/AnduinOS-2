"""End-to-end orchestration for one declarative acceptance scenario."""

from __future__ import annotations

import base64
import concurrent.futures
import io
import json
import os
import re
import shlex
import subprocess
import tarfile
import tempfile
import time
from dataclasses import asdict, dataclass
from pathlib import Path, PurePosixPath
from collections.abc import Callable

from .assertions import assert_installed_environment, assert_live_environment
from .errors import ProtocolError, TestFailure
from .firmware import FirmwareOverrides, copy_variables, resolve_firmware
from .grub import (
    InstalledBootFiles,
    boot_installed_with_debug_shell,
    boot_iso_with_debug_shell,
)
from .iso import IsoInspection
from .model import Architecture, Firmware, MatrixDefaults, Scenario, SshPolicy
from .qemu import QemuConfig, QemuVm, allocate_tcp_port, resolve_qemu


@dataclass(frozen=True)
class RunnerOptions:
    artifacts_root: Path
    firmware_overrides: FirmwareOverrides
    memory_mib: int
    cpus: int
    disk_gib: int
    boot_timeout_seconds: int
    install_timeout_seconds: int
    command_timeout_seconds: int
    firmware_delay_seconds: float
    smoke_only: bool = False


@dataclass(frozen=True)
class ScenarioResult:
    id: str
    status: str
    seconds: float
    artifacts: Path
    error: str = ""


class ScenarioRunner:
    def __init__(
        self,
        inspection: IsoInspection,
        architecture: Architecture,
        defaults: MatrixDefaults,
        options: RunnerOptions,
        status_callback: Callable[[str, str], None] | None = None,
    ):
        self.inspection = inspection
        self.architecture = architecture
        self.defaults = defaults
        self.options = options
        self.driver = Path(__file__).parents[1] / "guest" / "atspi_driver.py"
        self.status = status_callback or _status

    def run(self, scenario: Scenario) -> ScenarioResult:
        started = time.monotonic()
        artifacts = self.options.artifacts_root / scenario.id
        if artifacts.exists():
            raise TestFailure(f"Refusing to reuse artifact directory: {artifacts}")
        artifacts.mkdir(parents=True)
        vm: QemuVm | None = None
        try:
            vm = self._create_vm(scenario, artifacts)
            vm.create_disk()
            self._write_manifest(scenario, vm.config, artifacts)
            boot_files = self._run_live_phase(vm, scenario, artifacts)
            if self.options.smoke_only:
                return ScenarioResult(
                    scenario.id,
                    "passed",
                    time.monotonic() - started,
                    artifacts,
                )
            if boot_files is None:
                raise TestFailure("Installer run did not discover target boot files")
            self._run_target_phase(vm, scenario, boot_files, artifacts)
            return ScenarioResult(
                scenario.id,
                "passed",
                time.monotonic() - started,
                artifacts,
            )
        except Exception as error:
            if vm is not None and vm.running:
                try:
                    vm.screenshot("failure")
                except Exception:
                    pass
            (artifacts / "failure.txt").write_text(
                f"{type(error).__name__}: {error}\n", encoding="utf-8"
            )
            return ScenarioResult(
                scenario.id,
                "failed",
                time.monotonic() - started,
                artifacts,
                f"{type(error).__name__}: {error}",
            )
        finally:
            if vm is not None:
                vm.stop()

    def _create_vm(self, scenario: Scenario, artifacts: Path) -> QemuVm:
        selection = resolve_firmware(
            self.architecture,
            scenario.firmware,
            self.options.firmware_overrides,
        )
        variables = None
        if selection is not None:
            variables = copy_variables(selection, artifacts / "uefi-vars.fd")
        qemu_binary, acceleration = resolve_qemu(self.architecture)
        config = QemuConfig(
            architecture=self.architecture,
            firmware=scenario.firmware,
            network=scenario.network,
            memory_mib=self.options.memory_mib,
            cpus=self.options.cpus,
            disk_gib=self.options.disk_gib,
            ssh_forward_port=allocate_tcp_port(),
            iso=self.inspection.path,
            disk=artifacts / "target.qcow2",
            variables=variables,
            firmware_selection=selection,
            artifacts=artifacts,
            qemu_binary=qemu_binary,
            acceleration=acceleration,
        )
        return QemuVm(config)

    def _write_manifest(
        self,
        scenario: Scenario,
        config: QemuConfig,
        artifacts: Path,
    ) -> None:
        value = {
            "iso": str(self.inspection.path),
            "iso_sha256": self.inspection.sha256,
            "architecture": self.architecture.value,
            "scenario": _scenario_json(scenario),
            "qemu": {
                "binary": config.qemu_binary,
                "acceleration": config.acceleration,
                "memory_mib": config.memory_mib,
                "cpus": config.cpus,
                "disk_gib": config.disk_gib,
                "ssh_forward_port": config.ssh_forward_port,
                "firmware_code": (
                    str(config.firmware_selection.code)
                    if config.firmware_selection is not None
                    else None
                ),
                "firmware_vars_template": (
                    str(config.firmware_selection.variables_template)
                    if config.firmware_selection is not None
                    else None
                ),
            },
        }
        (artifacts / "manifest.json").write_text(
            json.dumps(value, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )

    def _run_live_phase(
        self,
        vm: QemuVm,
        scenario: Scenario,
        artifacts: Path,
    ) -> InstalledBootFiles | None:
        self.status(scenario.id, "Booting original ISO")
        vm.start(attach_iso=True)
        assert vm.qmp is not None and vm.serial is not None
        boot_iso_with_debug_shell(
            vm.qmp,
            vm.serial,
            self.architecture,
            firmware_delay=self.options.firmware_delay_seconds,
            synchronize_prompt=scenario.firmware.secure_boot,
        )
        vm.serial.timeout = self.options.command_timeout_seconds
        vm.serial.wait_for_shell(self.options.boot_timeout_seconds)
        self.status(scenario.id, "Live GNOME and serial control are ready")
        assert_live_environment(vm.serial, scenario, artifacts)
        vm.screenshot("live-desktop")
        if self.options.smoke_only:
            _power_off(vm)
            return None
        self._run_installer_driver(vm, scenario, artifacts)
        boot_files = self._show_target_grub_once(vm, scenario, artifacts)
        self._assert_live_cleanup(vm, artifacts)
        vm.screenshot("installer-complete")
        _power_off(vm)
        self.status(scenario.id, "Installation complete; ISO detached")
        return boot_files

    def _run_installer_driver(
        self,
        vm: QemuVm,
        scenario: Scenario,
        artifacts: Path,
    ) -> None:
        assert vm.serial is not None
        remote_root = "/run/anduinos-acceptance"
        vm.serial.run(f"install -d -m 0777 {remote_root}/evidence")
        vm.serial.upload(self.driver, f"{remote_root}/atspi_driver.py", 0o755)
        config_path = artifacts / "installer-driver-config.json"
        config = {
            **_scenario_json(scenario),
            "username": self.defaults.username,
            "full_name": self.defaults.full_name,
            "hostname": self.defaults.hostname,
            "password": self.defaults.password,
            "install_timeout_seconds": self.options.install_timeout_seconds,
        }
        config_path.write_text(
            json.dumps(config, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        vm.serial.upload(config_path, f"{remote_root}/config.json", 0o644)
        user = _graphical_user(vm.serial)
        self.status(scenario.id, f"Driving GTK installer as {user} through AT-SPI")
        command = _desktop_command(
            user,
            (
                "python3",
                f"{remote_root}/atspi_driver.py",
                "install",
                "--config",
                f"{remote_root}/config.json",
                "--evidence",
                f"{remote_root}/evidence",
            ),
        )
        result = _run_with_qmp_key_requests(
            vm,
            command,
            timeout=self.options.install_timeout_seconds + 300,
        )
        (artifacts / "atspi-events.jsonl").write_text(
            result.stdout + "\n", encoding="utf-8"
        )
        _retrieve_tree(vm.serial, remote_root, artifacts / "guest-ui-evidence")
        _retrieve_file(
            vm.serial,
            "/tmp/anduinos-installer-ui.stdout",
            artifacts / "installer-ui.stdout",
        )
        if result.returncode != 0:
            raise TestFailure(
                "AT-SPI installer driver failed:\n" + result.stdout[-8000:]
            )
        output_path = artifacts / "guest-ui-evidence" / "installer-output.txt"
        try:
            output = output_path.read_text(encoding="utf-8")
        except OSError as error:
            raise TestFailure(
                f"Installer did not expose its executor output: {error}"
            ) from error
        _validate_installer_output(output, scenario.online_features)
        if scenario.online_features:
            driver_result = vm.serial.run(
                r"""
set -euo pipefail
if [ -e /run/anduinos-installer-drivers ]; then
    printf 'package-list-present=yes\n'
    cat /run/anduinos-installer-drivers
    test ! -s /run/anduinos-installer-drivers
else
    printf 'package-list-present=no; ubuntu-drivers found no package to install\n'
fi
"""
            )
            (artifacts / "live-driver-resolution.txt").write_text(
                driver_result.stdout + "\n", encoding="utf-8"
            )

    def _run_target_phase(
        self,
        vm: QemuVm,
        scenario: Scenario,
        boot_files: InstalledBootFiles,
        artifacts: Path,
    ) -> None:
        if scenario.mok_enrollment:
            self._enroll_mok(vm, scenario, artifacts)
        self.status(scenario.id, "Booting installed target without ISO")
        vm.start(attach_iso=False)
        assert vm.qmp is not None and vm.serial is not None
        boot_installed_with_debug_shell(
            vm.qmp,
            vm.serial,
            self.architecture,
            scenario.filesystem,
            boot_files,
            firmware_delay=self.options.firmware_delay_seconds,
        )
        vm.serial.timeout = self.options.command_timeout_seconds
        vm.serial.wait_for_shell(self.options.boot_timeout_seconds)
        # Every scenario deliberately sets GRUB's standard recordfail flag so
        # its otherwise timing-dependent hidden menu is available for this
        # controlled serial-debug boot.  Clear it immediately; the installed
        # system must keep its normal boot policy after the acceptance test.
        vm.serial.run(
            "grub-editenv /boot/grub/grubenv unset recordfail menu_show_once",
            timeout=30,
        )
        assert_installed_environment(
            vm.serial,
            scenario,
            self.architecture,
            self.defaults.username,
            self.defaults.hostname.casefold(),
            artifacts,
        )
        vm.screenshot("installed-gdm")
        self.status(scenario.id, "Logging into the installed GNOME desktop")
        _login_gdm(
            vm,
            self.defaults.username,
            self.defaults.password,
            timeout=120,
        )
        graphical_user = _graphical_user(vm.serial)
        if graphical_user != self.defaults.username:
            raise TestFailure(
                "Installed GNOME session belongs to unexpected user: "
                f"{graphical_user}"
            )
        vm.screenshot("installed-desktop")
        if scenario.snapshots_manager:
            self._exercise_snapshots_manager(vm, scenario, artifacts)
        self._assert_host_ssh(vm, scenario, artifacts)
        if scenario.ssh is SshPolicy.TOGGLE:
            self._exercise_gnome_ssh_switch(vm, scenario, artifacts)
        _power_off(vm)

    def _enroll_mok(
        self,
        vm: QemuVm,
        scenario: Scenario,
        artifacts: Path,
    ) -> None:
        self.status(scenario.id, "Completing MOK enrollment with fresh UEFI VARS")
        vm.start(attach_iso=False)
        assert vm.qmp is not None
        delay = self.options.firmware_delay_seconds + (
            18 if self.architecture is Architecture.ARM64 else 8
        )
        time.sleep(delay)
        vm.screenshot("mok-manager")
        sequence = (
            ("down", 0.5),
            ("ret", 1.0),
            ("down", 0.5),
            ("ret", 1.0),
            ("down", 0.5),
            ("ret", 1.0),
        )
        for key, pause in sequence:
            vm.qmp.send_key(key)
            time.sleep(pause)
        vm.qmp.type_text(self.defaults.mok_password, interval=0.08)
        vm.qmp.send_key("ret")
        time.sleep(1)
        vm.qmp.send_key("ret")
        try:
            vm.wait(180)
        except ProtocolError:
            vm.screenshot("mok-manager-timeout")
            raise TestFailure("MokManager did not reboot after enrollment")
        finally:
            vm.stop()
        (artifacts / "mok-enrollment.txt").write_text(
            "MokManager keyboard workflow completed; in-guest mokutil verification follows.\n",
            encoding="utf-8",
        )

    def _show_target_grub_once(
        self,
        vm: QemuVm,
        scenario: Scenario,
        artifacts: Path,
    ) -> InstalledBootFiles:
        """Expose installed GRUB for one controlled post-install boot."""

        assert vm.serial is not None
        mount_options = (
            "-o subvol=@root" if scenario.filesystem.value == "btrfs" else ""
        )
        script = f"""
set -euo pipefail
root_device=$(lsblk -pnro NAME,FSTYPE,TYPE | awk '$2 == "{scenario.filesystem.value}" && $3 == "part" {{ print $1; exit }}')
test -b "$root_device"
mountpoint=$(mktemp -d /run/anduinos-target.XXXXXX)
cleanup() {{ umount "$mountpoint" 2>/dev/null || true; rmdir "$mountpoint" 2>/dev/null || true; }}
trap cleanup EXIT
mount {mount_options} "$root_device" "$mountpoint"
test -s "$mountpoint/boot/grub/grub.cfg"
grub-script-check "$mountpoint/boot/grub/grub.cfg"
kernel=$(find "$mountpoint/boot" -maxdepth 1 -type f -name 'vmlinuz-*' -printf '%f\n' | sort -V | tail -n1)
test -n "$kernel"
version=${{kernel#vmlinuz-}}
initrd="initrd.img-$version"
test -s "$mountpoint/boot/$kernel"
test -s "$mountpoint/boot/$initrd"
if [ "{scenario.firmware.value}" = "uefi-sb" ]; then
    certificate="$mountpoint/var/lib/shim-signed/mok/MOK.der"
    test -s "$certificate"
    pending=$(mokutil --list-new 2>/dev/null)
    test -n "$pending"
    expected=$(openssl x509 -inform DER -in "$certificate" -noout -fingerprint -sha1 | cut -d= -f2 | tr -d ':' | tr '[:lower:]' '[:upper:]')
    normalized=$(printf '%s' "$pending" | tr -d ':' | tr '[:lower:]' '[:upper:]')
    printf '%s' "$normalized" | grep -Fq "$expected"
    printf 'MOK_PENDING_FINGERPRINT=%s\n' "$expected"
elif [ "{scenario.firmware.value}" = "uefi-nosb" ]; then
    test -z "$(mokutil --list-new 2>/dev/null)"
    printf 'MOK_PENDING=none\n'
fi
grub-editenv "$mountpoint/boot/grub/grubenv" unset menu_show_once recordfail
grub-editenv "$mountpoint/boot/grub/grubenv" set recordfail=1
printf 'ANDUINOS_KERNEL=%s\n' "$kernel"
printf 'ANDUINOS_INITRD=%s\n' "$initrd"
grub-editenv "$mountpoint/boot/grub/grubenv" list
sync
"""
        result = vm.serial.run(script, timeout=120)
        (artifacts / "target-grub-one-shot.txt").write_text(
            result.stdout + "\n", encoding="utf-8"
        )
        kernel = _extract_boot_filename(result.stdout, "ANDUINOS_KERNEL", "vmlinuz-")
        initrd = _extract_boot_filename(result.stdout, "ANDUINOS_INITRD", "initrd.img-")
        prefix = "/@root/boot" if scenario.filesystem.value == "btrfs" else "/boot"
        return InstalledBootFiles(
            kernel=f"{prefix}/{kernel}",
            initrd=f"{prefix}/{initrd}",
        )

    def _assert_live_cleanup(self, vm: QemuVm, artifacts: Path) -> None:
        """Prove that neither the installer nor target inspection leaked mounts."""

        assert vm.serial is not None
        result = vm.serial.run(
            r"""
set -euo pipefail
mount_targets=$(findmnt -rn -o TARGET)
printf '%s\n' "$mount_targets"
if printf '%s\n' "$mount_targets" | grep -Eq '^/target($|/)|^/run/anduinos-target\.'; then
    echo 'Installer or harness target mount remains active' >&2
    exit 1
fi
if find /run -maxdepth 1 -type d -name 'anduinos-target.*' -print -quit | grep -q .; then
    echo 'Harness target mount directory remains' >&2
    exit 1
fi
printf 'temporary-target-mounts=clean\n'
"""
        )
        (artifacts / "live-post-install-cleanup.txt").write_text(
            result.stdout + "\n", encoding="utf-8"
        )

    def _assert_host_ssh(
        self,
        vm: QemuVm,
        scenario: Scenario,
        artifacts: Path,
    ) -> None:
        port = vm.config.ssh_forward_port
        if scenario.ssh is SshPolicy.ENABLED:
            output = _ssh_login_eventually(
                port,
                self.defaults.username,
                self.defaults.password,
            )
            root = _ssh_login(
                port,
                "root",
                self.defaults.password,
                should_succeed=False,
            )
            text = output + "\nroot-login:\n" + root
        else:
            text = _ssh_login(
                port,
                self.defaults.username,
                self.defaults.password,
                should_succeed=False,
            )
        (artifacts / "host-ssh.txt").write_text(text, encoding="utf-8")

    def _exercise_gnome_ssh_switch(
        self,
        vm: QemuVm,
        scenario: Scenario,
        artifacts: Path,
    ) -> None:
        assert vm.qmp is not None and vm.serial is not None
        self.status(scenario.id, "Toggling Secure Shell in GNOME Settings")
        _login_gdm(
            vm,
            self.defaults.username,
            self.defaults.password,
            timeout=120,
        )
        remote_root = "/run/anduinos-acceptance-installed"
        vm.serial.run(f"install -d -m 0777 {remote_root}/evidence")
        vm.serial.upload(self.driver, f"{remote_root}/atspi_driver.py", 0o755)

        def run_driver(mode: str) -> str:
            command = _desktop_command(
                self.defaults.username,
                (
                    "python3",
                    f"{remote_root}/atspi_driver.py",
                    mode,
                    "--evidence",
                    f"{remote_root}/evidence",
                ),
                managed=True,
            )
            result = vm.serial.run(command, timeout=180, check=False)
            with (artifacts / "atspi-events.jsonl").open(
                "a", encoding="utf-8"
            ) as stream:
                stream.write(result.stdout + "\n")
            _retrieve_tree(
                vm.serial,
                remote_root,
                artifacts / "guest-settings-evidence",
            )
            _retrieve_file(
                vm.serial,
                "/tmp/gnome-control-center.stdout",
                artifacts / "gnome-control-center.stdout",
            )
            if result.returncode != 0:
                raise TestFailure(
                    f"GNOME Secure Shell UI mode {mode!r} failed:\n"
                    + result.stdout[-8000:]
                )
            return result.stdout

        run_driver("secure-shell-prepare")
        for _ in range(30):
            row = run_driver("secure-shell-row")
            if '"focused": true' in row:
                break
            vm.qmp.send_key("tab")
            time.sleep(0.3)
        else:
            raise TestFailure("Secure Shell row never received focus")
        vm.qmp.send_key("spc")
        time.sleep(1)
        for _ in range(12):
            probe = run_driver("secure-shell-probe")
            if '"focused": true' in probe and '"enabled": true' in probe:
                if '"active": true' in probe:
                    raise TestFailure("Secure Shell unexpectedly started enabled")
                break
            if '"focused": false' in probe:
                vm.qmp.send_key("tab")
            time.sleep(0.3)
        else:
            raise TestFailure("Secure Shell switch never received focus")
        vm.screenshot("secure-shell-dialog")

        # The outer AdwSwitchRow owns accessibility state and focus; its unique
        # inner GtkSwitch owns the activation action used by the guest driver.
        ssh_evidence: list[str] = []
        for mode, active in (("secure-shell-on", True), ("secure-shell-off", False)):
            result = run_driver(mode)
            if '"event": "polkit-required"' in result:
                vm.screenshot(f"{mode}-polkit-before-input")
                vm.qmp.type_text(
                    self.defaults.password,
                    interval=0.06,
                )
                vm.screenshot(f"{mode}-polkit-password-entered")
                vm.qmp.send_key("ret")
                run_driver(
                    "secure-shell-assert-on"
                    if active
                    else "secure-shell-assert-off"
                )
            time.sleep(2)
            vm.screenshot(f"{mode}-after-input")
            if active:
                ssh_evidence.append(
                    "after GNOME enabled Secure Shell:\n"
                    + _ssh_login_eventually(
                        vm.config.ssh_forward_port,
                        self.defaults.username,
                        self.defaults.password,
                    )
                )
            else:
                _assert_guest_ssh_stopped(vm.serial, artifacts)
                ssh_evidence.append(
                    "after GNOME disabled Secure Shell:\n"
                    + _ssh_login(
                        vm.config.ssh_forward_port,
                        self.defaults.username,
                        self.defaults.password,
                        should_succeed=False,
                    )
                )
        (artifacts / "host-ssh-toggle.txt").write_text(
            "\n\n".join(ssh_evidence) + "\n",
            encoding="utf-8",
        )
        vm.serial.run(
            _desktop_command(
                self.defaults.username,
                ("pkill", "-x", "gnome-control-center"),
            ),
            timeout=30,
            check=False,
        )

    def _exercise_snapshots_manager(
        self,
        vm: QemuVm,
        scenario: Scenario,
        artifacts: Path,
    ) -> None:
        assert vm.serial is not None
        self.status(scenario.id, "Launching Disk Snapshots Manager through GNOME")
        remote_root = "/run/anduinos-acceptance-snapshots"
        vm.serial.run(f"install -d -m 0777 {remote_root}/evidence")
        vm.serial.upload(self.driver, f"{remote_root}/atspi_driver.py", 0o755)
        command = _desktop_command(
            self.defaults.username,
            (
                "python3",
                f"{remote_root}/atspi_driver.py",
                "snapshots-manager",
                "--evidence",
                f"{remote_root}/evidence",
            ),
        )
        result = vm.serial.run(command, timeout=180, check=False)
        with (artifacts / "atspi-events.jsonl").open("a", encoding="utf-8") as stream:
            stream.write(result.stdout + "\n")
        _retrieve_tree(
            vm.serial,
            remote_root,
            artifacts / "guest-snapshots-evidence",
        )
        _retrieve_file(
            vm.serial,
            "/tmp/anduinos-snapshots-manager.stdout",
            artifacts / "snapshots-manager.stdout",
        )
        if result.returncode != 0:
            raise TestFailure(
                "Disk Snapshots Manager did not launch through AT-SPI:\n"
                + result.stdout[-8000:]
            )


def _scenario_json(scenario: Scenario) -> dict[str, object]:
    value = asdict(scenario)
    value["architectures"] = [item.value for item in scenario.architectures]
    for key in ("firmware", "network", "filesystem", "ssh"):
        value[key] = value[key].value
    return value


def _run_with_qmp_key_requests(
    vm: QemuVm,
    command: str,
    *,
    timeout: float,
):
    """Run a serial command while serving semantic keyboard requests via QMP."""

    assert vm.serial is not None and vm.qmp is not None
    transcript = vm.serial.transcript
    offset = transcript.stat().st_size if transcript.exists() else 0
    partial = ""
    handled: set[str] = set()
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(
            vm.serial.run,
            command,
            timeout=timeout,
            check=False,
        )
        while not future.done():
            if transcript.exists():
                with transcript.open("rb") as stream:
                    stream.seek(offset)
                    chunk = stream.read()
                    offset = stream.tell()
                if chunk:
                    partial += chunk.decode("utf-8", errors="replace").replace(
                        "\r", ""
                    )
                    lines = partial.split("\n")
                    partial = lines.pop()
                    for line in lines:
                        request = _parse_qmp_key_request(line)
                        if request is None:
                            continue
                        identifier, key = request
                        if identifier in handled:
                            continue
                        if key not in {"tab", "spc"}:
                            raise TestFailure(
                                f"Guest requested unsupported QMP key: {key!r}"
                            )
                        handled.add(identifier)
                        vm.qmp.send_key(key)
            time.sleep(0.05)
        return future.result()


def _parse_qmp_key_request(line: str) -> tuple[str, str] | None:
    start = line.find('{"event": "qmp-key"')
    if start < 0:
        return None
    try:
        request = json.loads(line[start:])
    except json.JSONDecodeError:
        return None
    identifier = request.get("request")
    key = request.get("key")
    if not isinstance(identifier, str) or not identifier:
        return None
    if not isinstance(key, str) or not key:
        return None
    return identifier, key


def _validate_installer_output(output: str, expects_driver_flow: bool) -> None:
    """Validate the executor transcript exposed by the real GTK output tab."""

    if not output.strip():
        raise TestFailure("Installer executor output is empty")
    folded = output.casefold()
    fatal_markers = (
        "traceback (most recent call last)",
        "fatal step",
        "installation failed",
    )
    for marker in fatal_markers:
        if marker in folded:
            raise TestFailure(
                f"Installer executor output contains fatal marker: {marker}"
            )
    if not expects_driver_flow:
        return
    command = (
        "ubuntu-drivers install --no-oem --package-list "
        "/run/anduinos-installer-drivers"
    )
    if command not in output:
        raise TestFailure(
            "Online scenario did not execute the ubuntu-drivers install flow"
        )
    no_driver_messages = (
        "all the available drivers are already installed.",
        "all available drivers are already installed.",
    )
    if not any(message in folded for message in no_driver_messages):
        raise TestFailure(
            "QEMU driver flow did not report that no additional driver is needed"
        )


def _extract_boot_filename(output: str, key: str, prefix: str) -> str:
    matches = re.findall(rf"^{re.escape(key)}=(\S+)$", output, re.MULTILINE)
    if len(matches) != 1:
        raise TestFailure(f"Target discovery did not return exactly one {key}")
    filename = matches[0]
    if not filename.startswith(prefix) or re.fullmatch(
        r"[A-Za-z0-9][A-Za-z0-9._+-]*", filename
    ) is None:
        raise TestFailure(f"Target returned an unsafe boot filename: {filename!r}")
    return filename


def _graphical_user(console) -> str:
    result = console.run(
        r"""
set -e
for runtime in $(find /run/user -mindepth 1 -maxdepth 1 -type d | sort -V -r); do
    uid=${runtime##*/}
    user=$(getent passwd "$uid" | cut -d: -f1)
    [ -n "$user" ] || continue
    [ "$user" != gdm ] || continue
    [ -S "$runtime/bus" ] || continue
    find "$runtime" -maxdepth 1 -type s -name 'wayland-[0-9]*' 2>/dev/null | grep -q . || continue
    printf '%s\n' "$user"
    exit 0
done
exit 1
"""
    )
    return result.stdout.strip().splitlines()[-1]


def _desktop_command(
    user: str,
    command: tuple[str, ...],
    *,
    managed: bool = False,
) -> str:
    rendered = shlex.join(command)
    quoted_user = shlex.quote(user)
    return f"""
set -e
user={quoted_user}
uid=$(id -u "$user")
runtime=/run/user/$uid
home=$(getent passwd "$user" | cut -d: -f6)
wayland=$(find "$runtime" -maxdepth 1 -type s -name 'wayland-[0-9]*' -printf '%f\\n' 2>/dev/null | head -n1)
test -S "$runtime/bus"
test -n "$wayland"
managed={"true" if managed else "false"}
if $managed; then
    rendered="systemd-run --user --wait --pipe --collect --quiet \\
        --setenv=HOME=$home \\
        --setenv=XDG_RUNTIME_DIR=$runtime \\
        --setenv=DBUS_SESSION_BUS_ADDRESS=unix:path=$runtime/bus \\
        --setenv=WAYLAND_DISPLAY=$wayland --setenv=DISPLAY=:0 \\
        --setenv=NO_AT_BRIDGE=0 --setenv=XDG_CURRENT_DESKTOP=GNOME \\
        --setenv=XDG_SESSION_DESKTOP=gnome --setenv=DESKTOP_SESSION=gnome \\
        --setenv=GDMSESSION=gnome -- {rendered}"
else
    rendered={shlex.quote(rendered)}
fi
runuser -u "$user" -- env \\
    HOME="$home" \\
    XDG_RUNTIME_DIR="$runtime" \\
    DBUS_SESSION_BUS_ADDRESS="unix:path=$runtime/bus" \\
    WAYLAND_DISPLAY="$wayland" DISPLAY=:0 NO_AT_BRIDGE=0 \\
    XDG_CURRENT_DESKTOP=GNOME XDG_SESSION_DESKTOP=gnome \\
    DESKTOP_SESSION=gnome GDMSESSION=gnome \\
    /bin/bash -c "$rendered"
"""


def _retrieve_tree(console, remote_root: str, destination: Path) -> None:
    result = console.run(
        f"tar -C {shlex.quote(remote_root)} -czf - evidence | base64 -w0",
        timeout=120,
    )
    data = base64.b64decode(result.stdout.strip(), validate=True)
    destination.mkdir(parents=True, exist_ok=True)
    with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as archive:
        for member in archive.getmembers():
            path = PurePosixPath(member.name)
            if path.is_absolute() or ".." in path.parts or not member.isfile():
                continue
            relative = Path(*path.parts[1:]) if path.parts[:1] == ("evidence",) else Path(*path.parts)
            if not relative.parts:
                continue
            target = destination / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            source = archive.extractfile(member)
            if source is not None:
                target.write_bytes(source.read())


def _retrieve_file(console, source: str, destination: Path) -> None:
    result = console.run(
        f"test ! -f {shlex.quote(source)} || base64 -w0 {shlex.quote(source)}"
    )
    if result.stdout.strip():
        destination.write_bytes(base64.b64decode(result.stdout.strip(), validate=True))


def _login_gdm(vm: QemuVm, username: str, password: str, timeout: float) -> None:
    assert vm.qmp is not None and vm.serial is not None
    deadline = time.monotonic() + timeout
    for attempt in range(3):
        active = vm.serial.run(
            f"loginctl show-user {shlex.quote(username)} -p State --value 2>/dev/null || true"
        ).stdout.strip()
        if active == "active":
            return
        vm.qmp.send_key("ret")
        time.sleep(1)
        vm.qmp.type_text(password, interval=0.06)
        vm.qmp.send_key("ret")
        time.sleep(8)
        if time.monotonic() >= deadline:
            break
    raise TestFailure("Could not log the test account into GNOME through GDM")


def _ssh_login(
    port: int,
    username: str,
    password: str,
    *,
    should_succeed: bool,
) -> str:
    command = [
        "ssh",
        "-F",
        "/dev/null",
        "-p",
        str(port),
        "-o",
        "StrictHostKeyChecking=no",
        "-o",
        "UserKnownHostsFile=/dev/null",
        "-o",
        "PreferredAuthentications=password",
        "-o",
        "PubkeyAuthentication=no",
        "-o",
        "ConnectTimeout=15",
        "-o",
        "NumberOfPasswordPrompts=1",
        "-o",
        "ControlMaster=no",
        "-o",
        "ControlPersist=no",
        "-o",
        "ControlPath=none",
        f"{username}@127.0.0.1",
        "id -un",
    ]
    # A pipe or an inherited PTY is not necessarily ssh's controlling TTY.
    # In that situation OpenSSH does not read a password from stdin and may
    # silently fall back to askpass. Force that documented path explicitly.
    with tempfile.TemporaryDirectory(prefix="anduinos-ssh-askpass-") as directory:
        askpass = Path(directory) / "askpass"
        askpass.write_text(
            "#!/bin/sh\nprintf '%s\\n' \"$ANDUINOS_ACCEPTANCE_SSH_PASSWORD\"\n",
            encoding="utf-8",
        )
        askpass.chmod(0o700)
        environment = os.environ.copy()
        environment.update(
            {
                "DISPLAY": environment.get("DISPLAY") or ":0",
                "SSH_ASKPASS": str(askpass),
                "SSH_ASKPASS_REQUIRE": "force",
                "ANDUINOS_ACCEPTANCE_SSH_PASSWORD": password,
            }
        )
        try:
            result = subprocess.run(
                command,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                timeout=45,
                env=environment,
                check=False,
            )
            returncode = result.returncode
            text = result.stdout
        except subprocess.TimeoutExpired as error:
            returncode = 124
            text = str(error.stdout or "") + str(error.stderr or "")
    succeeded = returncode == 0 and username in text
    if succeeded != should_succeed:
        expectation = "succeed" if should_succeed else "fail"
        raise TestFailure(
            f"SSH login for {username} should {expectation}; rc={returncode}\n{text}"
        )
    return text


def _ssh_login_eventually(port: int, username: str, password: str) -> str:
    last_error: TestFailure | None = None
    for _ in range(6):
        try:
            return _ssh_login(
                port,
                username,
                password,
                should_succeed=True,
            )
        except TestFailure as error:
            last_error = error
            time.sleep(2)
    raise TestFailure("SSH did not become ready after GNOME enabled it") from last_error


def _assert_guest_ssh_stopped(console, artifacts: Path) -> None:
    result = console.run(
        r"""
set +e
for _ in $(seq 1 30); do
    if ! systemctl is-active --quiet ssh.socket \
        && ! systemctl is-active --quiet ssh.service \
        && ! ss -H -ltn 'sport = :22' | grep -q .; then
        break
    fi
    sleep 1
done
socket_enabled=$(systemctl is-enabled ssh.socket 2>/dev/null || true)
service_enabled=$(systemctl is-enabled ssh.service 2>/dev/null || true)
socket_active=$(systemctl is-active ssh.socket 2>/dev/null || true)
service_active=$(systemctl is-active ssh.service 2>/dev/null || true)
listeners=$(ss -H -ltn 'sport = :22' || true)
printf 'ssh.socket enabled=%s active=%s\n' "$socket_enabled" "$socket_active"
printf 'ssh.service enabled=%s active=%s\n' "$service_enabled" "$service_active"
printf 'listeners=%s\n' "$listeners"
test "$socket_enabled" != enabled
test "$service_enabled" != enabled
test "$socket_active" != active
test "$service_active" != active
test -z "$listeners"
""",
        timeout=45,
        check=False,
    )
    (artifacts / "installed-ssh-after-gnome-off.txt").write_text(
        result.stdout + "\n",
        encoding="utf-8",
    )
    if result.returncode != 0:
        raise TestFailure(
            "GNOME disabled its Secure Shell switch, but SSH remained enabled, "
            "active, or listening:\n" + result.stdout
        )


def _power_off(vm: QemuVm) -> None:
    """Flush guest filesystems and close the disposable VM through QMP."""

    assert vm.serial is not None and vm.qmp is not None
    vm.serial.run("sync", timeout=30)
    vm.qmp.quit()
    vm.wait(15)
    vm.stop()


def _status(identifier: str, message: str) -> None:
    print(f"[{identifier}] {message}", flush=True)
