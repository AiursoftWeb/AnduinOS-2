"""End-to-end orchestration for one declarative acceptance scenario."""

from __future__ import annotations

import concurrent.futures
import json
import os
import re
import shlex
import shutil
import subprocess
import tarfile
import tempfile
import time
import traceback
import uuid
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from pathlib import Path, PurePosixPath
from collections.abc import Callable

from .assertions import (
    RELEASE_CONTRACT_CHECKS,
    assert_installed_environment,
    assert_installed_region,
    assert_live_environment,
    assert_live_region,
    assert_passwordless_sudo_behavior,
    assert_release_contract,
)
from .base import PromotedBase, _discard_variable_store, promote_base
from .errors import ProtocolError, TestFailure
from .display import SpiceDisplayController
from .fixtures import build_appimage_fixture, build_windows_executable_fixture
from .firmware import FirmwareOverrides, copy_variables, resolve_firmware
from .grub import (
    InstalledBootFiles,
    boot_iso_with_debug_shell,
    render_installed_grub_instrumentation,
    render_installed_grub_restoration,
)
from .iso import IsoInspection
from .journal import (
    JournalPolicy,
    parse_journal_jsonl,
    parse_package_versions,
    render_guest_collection_script,
    render_verdict,
)
from .model import Architecture, Firmware, MatrixDefaults, Network, Scenario, SshPolicy
from .qemu import QemuConfig, QemuVm, allocate_tcp_port, resolve_qemu
from .spice_input import SpiceInputClient
from .storage import DiskStorage, assert_disk_storage_ready
from .visual import assert_cpu_z_thumbnail, assert_font_fixture, plymouth_match
from .wifi import WifiLab, WifiLabState


@dataclass(frozen=True)
class RunnerOptions:
    artifacts_root: Path
    disk_storage: DiskStorage
    firmware_overrides: FirmwareOverrides
    memory_mib: int
    cpus: int
    disk_gib: int
    boot_timeout_seconds: int
    install_timeout_seconds: int
    command_timeout_seconds: int
    firmware_delay_seconds: float
    free_space_reserve_gib: int = 10
    smoke_only: bool = False
    keep_passed_disk: bool = False
    keep_failed_disk: bool = False


@dataclass(frozen=True)
class ScenarioResult:
    id: str
    status: str
    seconds: float
    artifacts: Path
    error: str = ""
    promoted_base: PromotedBase | None = None


def scenario_check_ids(
    scenario: Scenario,
    *,
    smoke_only: bool = False,
) -> tuple[str, ...]:
    """Declare exactly the assertion boundaries emitted for one scenario."""

    checks = ["live-boot"]
    if smoke_only:
        return tuple(checks)
    checks = [
        "regional.grub-contract",
        "live-boot",
        "regional.grub-live-propagation",
        "installer-ui",
        "target-boot-files",
    ]
    if scenario.mok_enrollment:
        checks.append("mok-manager-workflow")
    checks.append("installed-boot")
    if scenario.mok_enrollment:
        checks.append("mok-enrollment")
    if scenario.network is Network.WIFI:
        checks.append("network.wifi-migration-hwsim")
    checks.extend(
        (
            "installed-contracts",
            _passwordless_sudo_check_id(scenario),
            _automatic_login_check_id(scenario),
            "regional.installed-zh-cn",
            "theme.cursor-user-session",
        )
    )
    installed_index = checks.index("installed-contracts") + 1
    checks[installed_index:installed_index] = RELEASE_CONTRACT_CHECKS
    if scenario.desktop_release_gate:
        checks.extend(
            (
                "render.twemoji-water-pistol",
                "files.appimage-open",
                "files.exe-thumbnail-fixture",
                "files.exe-open-fixture",
                "shell.extension-policy",
                "shell.extension-errors",
                "display.spice-resize",
            )
        )
    if scenario.snapshots_manager:
        checks.append("snapshots-manager")
    checks.append("host-ssh")
    if scenario.ssh is SshPolicy.TOGGLE:
        checks.append("gnome-ssh-toggle")
    if scenario.desktop_release_gate:
        checks.extend(
            (
                "journal.action-scoped",
                "journal.boot-and-idle",
                "boot.plymouth-anduinos-logo",
            )
        )
    return tuple(checks)


def _automatic_login_check_id(scenario: Scenario) -> str:
    return (
        "login.autologin-enabled"
        if scenario.automatic_login
        else "login.autologin-disabled"
    )


def _passwordless_sudo_check_id(scenario: Scenario) -> str:
    return (
        "sudo.passwordless-enabled"
        if scenario.passwordless_sudo
        else "sudo.password-required"
    )


class ScenarioRunner:
    def __init__(
        self,
        inspection: IsoInspection,
        architecture: Architecture,
        defaults: MatrixDefaults,
        options: RunnerOptions,
        status_callback: Callable[[str, str], None] | None = None,
        check_callback: Callable[[str, str, str, str], None] | None = None,
    ):
        self.inspection = inspection
        self.architecture = architecture
        self.defaults = defaults
        self.options = options
        self.driver = Path(__file__).parents[1] / "guest" / "atspi_driver.py"
        self.journal_policy = JournalPolicy.load(
            Path(__file__).parents[1] / "journal-policy.json"
        )
        self.status = status_callback or _status
        self.check_status = check_callback
        self._check_details: dict[tuple[str, str], str] = {}
        self._check_states: dict[str, dict[str, str]] = {}

    @contextmanager
    def _check(self, scenario: Scenario, identifier: str):
        """Emit a child verdict around the exact code that owns the assertion."""

        key = (scenario.id, identifier)
        self._emit_check(scenario.id, identifier, "running", "Running assertions")
        try:
            yield
        except BaseException as error:
            self._emit_check(
                scenario.id,
                identifier,
                "failed",
                f"{type(error).__name__}: {error}",
            )
            self._check_details.pop(key, None)
            raise
        else:
            detail = self._check_details.pop(key, "All assertions passed")
            self._emit_check(scenario.id, identifier, "passed", detail)

    def _check_note(
        self,
        scenario: Scenario,
        identifier: str,
        detail: str,
    ) -> None:
        details = getattr(self, "_check_details", None)
        if details is None:
            details = {}
            self._check_details = details
        details[(scenario.id, identifier)] = detail
        self._emit_check(scenario.id, identifier, "running", detail)

    def _emit_check(
        self,
        scenario_id: str,
        identifier: str,
        state: str,
        detail: str,
    ) -> None:
        plans = getattr(self, "_check_states", {})
        if scenario_id in plans:
            try:
                plans[scenario_id][identifier] = state
            except KeyError as error:
                raise TestFailure(
                    f"{scenario_id}: emitted undeclared child check {identifier!r}"
                ) from error
        callback = getattr(self, "check_status", None)
        if callback is not None:
            callback(scenario_id, identifier, state, detail)

    def run(self, scenario: Scenario, *, promote: bool = False) -> ScenarioResult:
        started = time.monotonic()
        if not hasattr(self, "_check_states"):
            self._check_states = {}
        self._check_states[scenario.id] = {
            identifier: "pending"
            for identifier in scenario_check_ids(
                scenario,
                smoke_only=self.options.smoke_only,
            )
        }
        artifacts = self.options.artifacts_root / scenario.id
        if artifacts.exists():
            raise TestFailure(f"Refusing to reuse artifact directory: {artifacts}")
        artifacts.mkdir(parents=True)
        # Recheck for every scenario. A previous explicitly retained disk or
        # another host workload must not let a matrix consume the last bytes
        # after the initial CLI preflight. Capacity failures abort the run;
        # they are host safety failures, not product failures.
        assert_disk_storage_ready(
            self.options.disk_storage,
            disk_gib=self.options.disk_gib,
            filesystem_reserve_gib=self.options.free_space_reserve_gib,
            memory_mib=self.options.memory_mib,
        )
        vm: QemuVm | None = None
        wifi_lab = WifiLab() if scenario.network is Network.WIFI else None
        passed = False
        base_retained = False
        try:
            vm = self._create_vm(scenario, artifacts)
            vm.create_disk()
            self._write_manifest(scenario, vm.config, artifacts)
            boot_files = self._run_live_phase(
                vm,
                scenario,
                artifacts,
                wifi_lab=wifi_lab,
            )
            if self.options.smoke_only:
                self._assert_check_completion(scenario)
                if wifi_lab is not None:
                    wifi_lab.assert_not_leaked(artifacts)
                passed = True
                return ScenarioResult(
                    scenario.id,
                    "passed",
                    time.monotonic() - started,
                    artifacts,
                )
            if boot_files is None:
                raise TestFailure("Installer run did not discover target boot files")
            self._run_target_phase(
                vm,
                scenario,
                boot_files,
                artifacts,
                prepare_overlay_base=promote,
                wifi_lab=wifi_lab,
            )
            self._assert_check_completion(scenario)
            promoted = None
            if promote:
                promoted = promote_base(
                    vm,
                    scenario,
                    self.defaults,
                    self.inspection,
                    boot_files,
                    Path(__file__).parents[1],
                )
                base_retained = True
                (artifacts / "target-disk-retention.txt").write_text(
                    "passed target disk promoted as a temporary immutable "
                    "feature-suite base; it will be deleted after all overlays\n",
                    encoding="utf-8",
                )
            if wifi_lab is not None:
                wifi_lab.assert_not_leaked(artifacts)
            passed = True
            return ScenarioResult(
                scenario.id,
                "passed",
                time.monotonic() - started,
                artifacts,
                promoted_base=promoted,
            )
        except Exception as error:
            if vm is not None and vm.running:
                try:
                    vm.screenshot("failure")
                except Exception:
                    pass
            message = f"{type(error).__name__}: {error}"
            diagnostic = traceback.format_exc()
            if wifi_lab is not None:
                message = message.replace(wifi_lab.password, "<redacted-wifi-secret>")
                diagnostic = diagnostic.replace(
                    wifi_lab.password, "<redacted-wifi-secret>"
                )
            (artifacts / "failure.txt").write_text(
                message + "\n\n" + diagnostic,
                encoding="utf-8",
            )
            if wifi_lab is not None:
                try:
                    wifi_lab.assert_not_leaked(artifacts)
                except Exception as leak_error:
                    error = leak_error
                    message = f"{type(leak_error).__name__}: {leak_error}"
                    (artifacts / "failure.txt").write_text(
                        message + "\n",
                        encoding="utf-8",
                    )
            return ScenarioResult(
                scenario.id,
                "failed",
                time.monotonic() - started,
                artifacts,
                message,
            )
        finally:
            if vm is not None:
                try:
                    vm.stop()
                finally:
                    # Delete only after stop has either reaped QEMU or exposed
                    # that it is still running. `_finalize_disk` refuses the
                    # latter instead of unlinking a live block device.
                    if not base_retained:
                        self._finalize_disk(vm, artifacts, passed=passed)

    def _assert_check_completion(self, scenario: Scenario) -> None:
        incomplete = [
            f"{identifier}={state}"
            for identifier, state in self._check_states[scenario.id].items()
            if state != "passed"
        ]
        if incomplete:
            raise TestFailure(
                "Scenario reached the end without passing every declared child "
                "check: " + ", ".join(incomplete)
            )

    def _finalize_disk(
        self,
        vm: QemuVm,
        artifacts: Path,
        *,
        passed: bool,
    ) -> None:
        if vm.running:
            raise TestFailure("Cannot finalize a target disk while QEMU is running")
        outcome = "passed" if passed else "failed"
        keep = (
            self.options.keep_passed_disk
            if passed
            else self.options.keep_failed_disk
        )
        if keep:
            message = (
                f"{outcome} target disk and its UEFI variables retained by "
                "explicit single-case option\n"
            )
        elif vm.config.disk.exists():
            vm.config.disk.unlink()
            _discard_variable_store(getattr(vm.config, "variables", None))
            message = (
                f"{outcome} target disk discarded; disposable UEFI variables "
                "discarded; durable logs, compressed screenshots, serial "
                "transcripts, and structured evidence remain\n"
            )
        else:
            _discard_variable_store(getattr(vm.config, "variables", None))
            message = f"{outcome} target disk was never created\n"
        if self.options.disk_storage.is_ramdisk:
            try:
                vm.config.disk.parent.rmdir()
            except OSError:
                pass
        (artifacts / "target-disk-retention.txt").write_text(
            message, encoding="utf-8"
        )

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
            disk=self.options.disk_storage.root / scenario.id / "target.qcow2",
            variables=variables,
            firmware_selection=selection,
            artifacts=artifacts,
            qemu_binary=qemu_binary,
            acceleration=acceleration,
            file_size_limit_bytes=self.options.disk_storage.qcow_limit_bytes,
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
                "disk_backend": self.options.disk_storage.backend,
                "disk_workspace": str(self.options.disk_storage.root),
                "disk_backend_reason": self.options.disk_storage.reason,
                "disk_file_size_limit_bytes": config.file_size_limit_bytes,
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
        *,
        wifi_lab: WifiLab | None = None,
    ) -> InstalledBootFiles | None:
        if self.options.smoke_only:
            live_entry = self._live_grub_entry()
        else:
            with self._check(scenario, "regional.grub-contract"):
                live_entry = self._assert_grub_regional_contract(artifacts)
        with self._check(scenario, "live-boot"):
            self.status(scenario.id, "Booting original ISO")
            vm.start(attach_iso=True)
            assert vm.qmp is not None and vm.serial is not None
            boot_iso_with_debug_shell(
                vm.qmp,
                vm.serial,
                self.architecture,
                firmware_delay=self.options.firmware_delay_seconds,
                menu_entry_index=self.inspection.live_entries.index(live_entry),
                kernel_arguments=live_entry.kernel_arguments,
                spice_socket=vm.spice_socket,
            )
            vm.serial.timeout = self.options.command_timeout_seconds
            vm.serial.wait_for_shell(self.options.boot_timeout_seconds)
            wifi_state = None
            if wifi_lab is not None:
                self.status(scenario.id, "Creating isolated in-guest WPA2 lab")
                wifi_state = wifi_lab.start(
                    vm.serial,
                    artifacts / "live-wifi-lab.txt",
                )
            self.status(scenario.id, "Live GNOME and serial control are ready")
            assert_live_environment(
                vm.serial,
                scenario,
                artifacts,
                self.defaults.live_locale,
                self.defaults.live_timezone,
                session_timeout_seconds=self.options.boot_timeout_seconds,
                check_region=self.options.smoke_only,
            )
            vm.screenshot("live-desktop")
        if self.options.smoke_only:
            _power_off(vm)
            return None
        with self._check(scenario, "regional.grub-live-propagation"):
            self.status(
                scenario.id,
                "Checking GRUB locale and timezone in the real Live GNOME session",
            )
            assert_live_region(
                vm.serial,
                self.defaults.live_locale,
                self.defaults.live_timezone,
                artifacts,
                session_timeout_seconds=self.options.boot_timeout_seconds,
            )
        with self._check(scenario, "installer-ui"):
            self._run_installer_driver(
                vm,
                scenario,
                artifacts,
                wifi_lab=wifi_lab,
                wifi_state=wifi_state,
            )
        with self._check(scenario, "target-boot-files"):
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
        *,
        wifi_lab: WifiLab | None = None,
        wifi_state: WifiLabState | None = None,
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
        if wifi_lab is not None:
            config["wifi_ssid"] = wifi_lab.ssid
            config["wifi_password_length"] = len(wifi_lab.password)
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
            secret_texts=(
                {"wifi-password": wifi_lab.password}
                if wifi_lab is not None
                else None
            ),
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
        if wifi_lab is not None:
            if wifi_state is None:
                raise TestFailure("Wi-Fi installer run has no live radio state")
            wifi_lab.capture_live_profile(
                vm.serial,
                wifi_state,
                artifacts / "live-wifi-profile.txt",
            )
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
        *,
        prepare_overlay_base: bool = False,
        wifi_lab: WifiLab | None = None,
    ) -> None:
        if scenario.mok_enrollment:
            with self._check(scenario, "mok-manager-workflow"):
                self._enroll_mok(vm, scenario, artifacts)
        with self._check(scenario, "installed-boot"):
            self.status(scenario.id, "Booting installed target without ISO")
            vm.start(attach_iso=False)
            assert vm.qmp is not None and vm.serial is not None
            vm.serial.timeout = self.options.command_timeout_seconds
            vm.serial.wait_for_shell(self.options.boot_timeout_seconds)
            restoration = vm.serial.run(
                render_installed_grub_restoration(),
                timeout=30,
            )
            (artifacts / "installed-grub-restoration.txt").write_text(
                restoration.stdout + "\n",
                encoding="utf-8",
            )
        if scenario.mok_enrollment:
            with self._check(scenario, "mok-enrollment"):
                self._assert_mok_enrollment_lifecycle(vm, scenario, artifacts)
        if wifi_lab is not None:
            with self._check(scenario, "network.wifi-migration-hwsim"):
                self.status(
                    scenario.id,
                    "Recreating the AP without supplying credentials to NetworkManager",
                )
                wifi_lab.start(
                    vm.serial,
                    artifacts / "installed-wifi-lab.txt",
                    require_client_disconnected=False,
                )
                wifi_lab.assert_installed_reconnect(
                    vm.serial,
                    artifacts / "installed-wifi-reconnect.txt",
                )
        with self._check(scenario, "installed-contracts"):
            assert_installed_environment(
                vm.serial,
                scenario,
                self.architecture,
                self.defaults.username,
                self.defaults.hostname.casefold(),
                artifacts,
            )
        self._assert_installed_release_contracts(vm, scenario, artifacts)
        desktop_failures: list[str] = []
        with self._check(scenario, _passwordless_sudo_check_id(scenario)):
            self.status(
                scenario.id,
                "Verifying the installed user's sudo authentication policy",
            )
            assert_passwordless_sudo_behavior(
                vm.serial,
                scenario,
                self.defaults.username,
                artifacts,
            )
        with self._check(scenario, _automatic_login_check_id(scenario)):
            self._assert_automatic_login_behavior(vm, scenario, artifacts)
            if not scenario.automatic_login:
                vm.screenshot("installed-gdm")
                self.status(scenario.id, "Logging into the installed GNOME desktop")
                _login_gdm(
                    vm,
                    self.defaults.username,
                    self.defaults.password,
                    timeout=120,
                )
            else:
                vm.screenshot("installed-automatic-login")
            graphical_user = _graphical_user(vm.serial)
            if graphical_user != self.defaults.username:
                raise TestFailure(
                    "Installed GNOME session belongs to unexpected user: "
                    f"{graphical_user}"
                )
        with self._check(scenario, "regional.installed-zh-cn"):
            self.status(
                scenario.id,
                "Checking installed configuration and the active GNOME region",
            )
            assert_installed_region(
                vm.serial,
                self.defaults.username,
                self.defaults.live_locale,
                self.defaults.live_timezone,
                artifacts,
            )
            self._assert_installed_ui_region(vm, scenario, artifacts)
        with self._check(scenario, "theme.cursor-user-session"):
            vm.screenshot("installed-desktop")
            self._assert_desktop_session(vm, scenario, artifacts)
        desktop_action_cursors = (
            self._capture_journal_cursors(vm)
            if scenario.desktop_release_gate
            else None
        )
        if scenario.desktop_release_gate:
            for label, check in (
                (
                    "render.twemoji-water-pistol",
                    lambda: self._exercise_font_rendering(vm, scenario, artifacts),
                ),
                (
                    "files.appimage-open",
                    lambda: self._exercise_appimage_open(
                        vm, scenario, artifacts
                    ),
                ),
                (
                    "files.exe-thumbnail-fixture",
                    lambda: self._exercise_windows_executable_thumbnail(
                        vm, scenario, artifacts
                    ),
                ),
                (
                    "files.exe-open-fixture",
                    lambda: self._exercise_windows_executable_open(
                        vm, scenario, artifacts
                    ),
                ),
                (
                    "shell.extension-policy",
                    lambda: self._assert_gnome_extensions(vm, scenario, artifacts),
                ),
                (
                    "shell.extension-errors",
                    lambda: self._assert_gnome_extension_errors(
                        vm, scenario, artifacts
                    ),
                ),
                (
                    "display.spice-resize",
                    lambda: self._exercise_dynamic_resolution(
                        vm, scenario, artifacts
                    ),
                ),
            ):
                self._collect_gate_failure(
                    scenario, label, check, desktop_failures, artifacts
                )
        if scenario.snapshots_manager:
            with self._check(scenario, "snapshots-manager"):
                self._exercise_snapshots_manager(vm, scenario, artifacts)
        if scenario.desktop_release_gate:
            self._collect_gate_failure(
                scenario,
                "host-ssh",
                lambda: self._assert_host_ssh(vm, scenario, artifacts),
                desktop_failures,
                artifacts,
            )
        else:
            with self._check(scenario, "host-ssh"):
                self._assert_host_ssh(vm, scenario, artifacts)
        if scenario.ssh is SshPolicy.TOGGLE:
            with self._check(scenario, "gnome-ssh-toggle"):
                self._exercise_gnome_ssh_switch(vm, scenario, artifacts)
        if scenario.desktop_release_gate:
            assert desktop_action_cursors is not None
            self._collect_gate_failure(
                scenario,
                "journal.action-scoped",
                lambda: self._assert_action_scoped_journal(
                    vm,
                    scenario,
                    desktop_action_cursors,
                    artifacts,
                ),
                desktop_failures,
                artifacts,
            )
            self._collect_gate_failure(
                scenario,
                "journal.boot-and-idle",
                lambda: self._assert_journal_health(vm, scenario, artifacts),
                desktop_failures,
                artifacts,
            )
        if scenario.desktop_release_gate:
            _retrieve_file(
                vm.serial,
                "/usr/share/plymouth/themes/anduinos/watermark.png",
                artifacts / "plymouth-watermark.png",
            )
        if prepare_overlay_base:
            # Every overlay boots the product's generated default menuentry.
            # The immutable run-local base carries a byte-for-byte backup plus
            # a command-line-only debug edit; each writable overlay restores
            # the original immediately after its first serial shell appears.
            instrumentation = vm.serial.run(
                render_installed_grub_instrumentation(
                    self.architecture,
                    mounted_target=False,
                ),
                timeout=60,
            )
            (artifacts / "feature-base-grub-instrumentation.txt").write_text(
                instrumentation.stdout + "\n",
                encoding="utf-8",
            )
        _power_off(vm)
        if scenario.desktop_release_gate:
            self._collect_gate_failure(
                scenario,
                "boot.plymouth-anduinos-logo",
                lambda: self._assert_passive_plymouth_boot(
                    vm, scenario, artifacts
                ),
                desktop_failures,
                artifacts,
            )
        if desktop_failures:
            raise TestFailure(
                "Desktop release gates failed:\n- "
                + "\n- ".join(desktop_failures)
            )

    def _collect_gate_failure(
        self,
        scenario: Scenario,
        label: str,
        check: Callable[[], None],
        failures: list[str],
        artifacts: Path,
    ) -> None:
        self._emit_check(scenario.id, label, "running", "Running assertions")
        try:
            check()
        except Exception as error:
            message = f"{label}: {type(error).__name__}: {error}"
            self._emit_check(scenario.id, label, "failed", message)
            getattr(self, "_check_details", {}).pop((scenario.id, label), None)
            failures.append(message)
            with (artifacts / "gate-failures.txt").open(
                "a", encoding="utf-8"
            ) as stream:
                stream.write(message + "\n")
        else:
            detail = getattr(self, "_check_details", {}).pop(
                (scenario.id, label),
                "All assertions passed",
            )
            self._emit_check(scenario.id, label, "passed", detail)

    def _assert_installed_release_contracts(
        self,
        vm: QemuVm,
        scenario: Scenario,
        artifacts: Path,
    ) -> None:
        """Collect every cheap contract, then stop before graphical exercises."""

        assert vm.serial is not None
        failures: list[str] = []
        for identifier in RELEASE_CONTRACT_CHECKS:
            self._collect_gate_failure(
                scenario,
                identifier,
                lambda identifier=identifier: assert_release_contract(
                    vm.serial,
                    self.defaults.username,
                    artifacts,
                    identifier,
                ),
                failures,
                artifacts,
            )
        if failures:
            raise TestFailure(
                "Installed-system release contracts failed:\n- "
                + "\n- ".join(failures)
            )

    def _live_grub_entry(self):
        entry = self.inspection.live_entry(self.defaults.live_grub_entry)
        if entry.locale != self.defaults.live_locale:
            raise TestFailure(
                f"GRUB entry locale is {entry.locale}, expected {self.defaults.live_locale}"
            )
        if entry.timezone != self.defaults.live_timezone:
            raise TestFailure(
                "GRUB entry timezone is "
                f"{entry.timezone}, expected {self.defaults.live_timezone}"
            )
        return entry

    def _assert_grub_regional_contract(self, artifacts: Path):
        """Retain the exact 28-entry ISO contract before QEMU can boot it."""

        entry = self._live_grub_entry()
        values = [
            {
                "name": candidate.name,
                "locale": candidate.locale,
                "timezone": candidate.timezone,
                "kernel_arguments": list(candidate.kernel_arguments),
            }
            for candidate in self.inspection.live_entries
        ]
        if len(values) != 28 or len({value["name"] for value in values}) != 28:
            raise TestFailure("ISO GRUB regional contract is not 28 unique entries")
        selected = [
            value for value in values if value["name"] == self.defaults.live_grub_entry
        ]
        if len(selected) != 1:
            raise TestFailure("Selected GRUB regional entry is not unique")
        report = {
            "entry_count": len(values),
            "selected_entry": selected[0],
            "expected_locale": self.defaults.live_locale,
            "expected_timezone": self.defaults.live_timezone,
            "entries": values,
        }
        (artifacts / "iso-grub-regional-contract.json").write_text(
            json.dumps(report, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        return entry

    def _assert_automatic_login_behavior(
        self,
        vm: QemuVm,
        scenario: Scenario,
        artifacts: Path,
    ) -> None:
        assert vm.serial is not None
        if scenario.automatic_login:
            self.status(
                scenario.id,
                "Waiting for GDM automatic login without sending credentials",
            )
            deadline = time.monotonic() + 180
            observed = ""
            while time.monotonic() < deadline:
                observed = _graphical_user_optional(vm.serial)
                if observed == self.defaults.username:
                    break
                if observed:
                    raise TestFailure(
                        "GDM automatically opened the wrong account: " + observed
                    )
                time.sleep(2)
            else:
                raise TestFailure(
                    "GDM automatic login was selected, but no user desktop opened "
                    "without keyboard input"
                )
            message = "automatic-login=observed-without-input\n"
        else:
            # GDM is already active here. Give it enough time to expose an
            # accidental auto-login, while deliberately sending no QMP keys.
            time.sleep(8)
            observed = _graphical_user_optional(vm.serial)
            if observed:
                raise TestFailure(
                    "GDM automatic login was disabled, but a graphical user session "
                    f"opened for {observed}"
                )
            message = "automatic-login=not-observed-before-password\n"
        (artifacts / "installed-gdm-behavior.txt").write_text(
            message, encoding="utf-8"
        )

    def _assert_desktop_session(
        self,
        vm: QemuVm,
        scenario: Scenario,
        artifacts: Path,
    ) -> None:
        assert vm.serial is not None
        self.status(scenario.id, "Checking the active GNOME cursor contract")
        script = r"""
set -euo pipefail
theme=$(gsettings get org.gnome.desktop.interface cursor-theme)
size=$(gsettings get org.gnome.desktop.interface cursor-size)
printf 'cursor-theme=%s\ncursor-size=%s\n' "$theme" "$size"
test "$theme" = "'Fluent-dark-cursors'"
test "$size" = 32
test -d /usr/share/icons/Fluent-dark-cursors/cursors
test -e /usr/share/icons/Fluent-dark-cursors/cursors/left_ptr
"""
        result = vm.serial.run(
            _desktop_command(
                self.defaults.username,
                ("bash", "-lc", script),
            ),
            timeout=60,
        )
        (artifacts / "installed-desktop-contracts.txt").write_text(
            result.stdout + "\n", encoding="utf-8"
        )

    def _assert_installed_ui_region(
        self,
        vm: QemuVm,
        scenario: Scenario,
        artifacts: Path,
    ) -> None:
        assert vm.serial is not None
        remote_root = "/run/anduinos-acceptance-region"
        vm.serial.run(f"install -d -m 0777 {remote_root}/evidence")
        vm.serial.upload(self.driver, f"{remote_root}/atspi_driver.py", 0o755)
        command = _desktop_command(
            self.defaults.username,
            (
                "python3",
                f"{remote_root}/atspi_driver.py",
                "installed-region-zh-cn",
                "--evidence",
                f"{remote_root}/evidence",
            ),
        )
        result = vm.serial.run(command, timeout=90, check=False)
        with (artifacts / "atspi-events.jsonl").open("a", encoding="utf-8") as stream:
            stream.write(result.stdout + "\n")
        _retrieve_tree(
            vm.serial,
            remote_root,
            artifacts / "guest-region-evidence",
        )
        if result.returncode != 0:
            raise TestFailure(
                "Installed GNOME region probe failed through AT-SPI:\n"
                + result.stdout[-8000:]
            )
        _validate_installed_region_ui_events(result.stdout)

    def _exercise_font_rendering(
        self,
        vm: QemuVm,
        scenario: Scenario,
        artifacts: Path,
    ) -> None:
        assert vm.serial is not None
        self.status(
            scenario.id,
            "Rendering Chinese and the green Twemoji water pistol in GTK",
        )
        remote_root = "/run/anduinos-acceptance-fonts"
        vm.serial.run(f"install -d -m 0777 {remote_root}/evidence")
        vm.serial.upload(self.driver, f"{remote_root}/atspi_driver.py", 0o755)
        fixture = Path(__file__).parents[1] / "guest" / "font_fixture.py"
        vm.serial.upload(fixture, f"{remote_root}/font_fixture.py", 0o755)
        command = _desktop_command(
            self.defaults.username,
            (
                "python3",
                f"{remote_root}/atspi_driver.py",
                "font-rendering",
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
            artifacts / "guest-font-evidence",
        )
        _retrieve_file(
            vm.serial,
            "/tmp/anduinos-font-fixture.stdout",
            artifacts / "font-fixture.stdout",
        )
        if result.returncode != 0:
            raise TestFailure(
                "GTK font rendering fixture failed through AT-SPI:\n"
                + result.stdout[-8000:]
            )
        time.sleep(1)
        screenshot = vm.screenshot("font-rendering")
        assert_font_fixture(screenshot, artifacts / "font-rendering-analysis.json")
        vm.serial.run(
            "pkill -f '/run/anduinos-acceptance-fonts/font_fixture.py' || true",
            timeout=30,
            check=False,
        )

    def _prepare_desktop_file_check(
        self,
        vm: QemuVm,
        remote_root: str,
    ) -> str:
        assert vm.serial is not None
        downloads = f"/home/{self.defaults.username}/Downloads"
        vm.serial.run(
            f"install -d -m 0777 {remote_root}/evidence\n"
            f"install -d -o {self.defaults.username} -g {self.defaults.username} "
            f"-m 0755 {shlex.quote(downloads)}"
        )
        vm.serial.upload(self.driver, f"{remote_root}/atspi_driver.py", 0o755)
        return downloads

    def _exercise_appimage_open(
        self,
        vm: QemuVm,
        scenario: Scenario,
        artifacts: Path,
    ) -> None:
        assert vm.serial is not None
        self.status(
            scenario.id,
            "Opening a real architecture-specific Type-2 AppImage through Nautilus",
        )
        fixture_root = artifacts / "host-appimage-fixture"
        appimage = build_appimage_fixture(self.architecture, fixture_root)
        remote_root = "/run/anduinos-acceptance-appimage"
        downloads = self._prepare_desktop_file_check(vm, remote_root)
        vm.serial.upload(appimage, f"{downloads}/{appimage.name}", 0o755)
        blocked_name = "AnduinOS-Blocked.AppImage"
        vm.serial.upload(appimage, f"{downloads}/{blocked_name}", 0o644)
        validation = vm.serial.run(
            f"set -euo pipefail\n"
            f"chown {self.defaults.username}:{self.defaults.username} "
            f"{shlex.quote(downloads)}/{appimage.name} "
            f"{shlex.quote(downloads)}/{blocked_name}\n"
            f"test \"$(dd if={shlex.quote(downloads)}/{appimage.name} "
            "bs=1 skip=8 count=3 status=none | base64 -w0)\" = QUkC\n"
            f"grep -a -q hsqs {shlex.quote(downloads)}/{appimage.name}\n"
            f"offset=$(runuser -u {self.defaults.username} -- "
            f"{shlex.quote(downloads)}/{appimage.name} --appimage-offset)\n"
            f"test \"$offset\" -gt 0\n"
            f"printf 'appimage-payload-offset=%s\\n' \"$offset\"\n"
            f"appimage_mime=$(runuser -u {self.defaults.username} -- "
            f"xdg-mime query filetype {shlex.quote(downloads)}/{appimage.name})\n"
            f"appimage_default=$(runuser -u {self.defaults.username} -- "
            f"xdg-mime query default \"$appimage_mime\")\n"
            "if test -e /usr/share/applications/"
            "com.anduinos.AppImageRunner.desktop; then "
            "appimage_runner_present=yes; else appimage_runner_present=no; fi\n"
            f"appimage_mode=$(stat -c %a {shlex.quote(downloads)}/{appimage.name})\n"
            f"appimage_blocked_mode=$(stat -c %a "
            f"{shlex.quote(downloads)}/{blocked_name})\n"
            f"printf 'appimage-mime=%s\\nappimage-default=%s\\n"
            "appimage-runner-present=%s\\nappimage-mode=%s\\n"
            "appimage-blocked-mode=%s\\n' "
            '"$appimage_mime" "$appimage_default" '
            '"$appimage_runner_present" "$appimage_mode" '
            '"$appimage_blocked_mode"\n'
            f"file {shlex.quote(downloads)}/{appimage.name}\n"
            f"sha256sum {shlex.quote(downloads)}/{appimage.name}",
            timeout=120,
            check=False,
        )
        (artifacts / "appimage-fixture.txt").write_text(
            validation.stdout + "\n", encoding="utf-8"
        )
        if validation.returncode != 0:
            raise TestFailure(
                "AppImage fixture structural validation failed before Nautilus "
                "activation:\n" + validation.stdout[-8000:]
            )
        _validate_appimage_fixture_contract(validation.stdout)
        command = _desktop_command(
            self.defaults.username,
            (
                "python3",
                f"{remote_root}/atspi_driver.py",
                "appimage-file",
                "--evidence",
                f"{remote_root}/evidence",
            ),
        )
        result = _run_with_qmp_key_requests(
            vm,
            command,
            timeout=180,
            request_trace=artifacts / "appimage-input-trace.jsonl",
        )
        (artifacts / "appimage-atspi-events.jsonl").write_text(
            result.stdout + "\n", encoding="utf-8"
        )
        _retrieve_tree(
            vm.serial,
            remote_root,
            artifacts / "guest-appimage-evidence",
        )
        _retrieve_file(
            vm.serial,
            "/tmp/anduinos-nautilus.stdout",
            artifacts / "appimage-nautilus.stdout",
        )
        if result.returncode != 0:
            direct = vm.serial.run(
                _desktop_command(
                    self.defaults.username,
                    (
                        "bash",
                        "-lc",
                        f"{shlex.quote(downloads)}/{appimage.name} "
                        ">/tmp/anduinos-appimage-direct.stdout 2>&1 & "
                        "child=$!; printf 'pid=%s\\n' \"$child\"; sleep 5; "
                        "if kill -0 \"$child\" 2>/dev/null; then "
                        "printf 'state=running\\n'; kill \"$child\"; "
                        "wait \"$child\" || true; "
                        "else wait \"$child\"; status=$?; "
                        "printf 'state=exited\\nexit=%s\\n' \"$status\"; fi; "
                        "cat /tmp/anduinos-appimage-direct.stdout",
                    ),
                ),
                timeout=30,
                check=False,
            )
            (artifacts / "appimage-direct-diagnostic.txt").write_text(
                direct.stdout + "\n", encoding="utf-8"
            )
            raise TestFailure(
                "AppImage desktop dispatch failed through Nautilus AT-SPI:\n"
                + result.stdout[-8000:]
            )
        blocked_command = _desktop_command(
            self.defaults.username,
            (
                "python3",
                f"{remote_root}/atspi_driver.py",
                "appimage-file-non-executable",
                "--evidence",
                f"{remote_root}/evidence/blocked",
            ),
        )
        blocked = _run_with_qmp_key_requests(
            vm,
            blocked_command,
            timeout=120,
            request_trace=artifacts / "appimage-blocked-input-trace.jsonl",
        )
        (artifacts / "appimage-blocked-atspi-events.jsonl").write_text(
            blocked.stdout + "\n", encoding="utf-8"
        )
        _retrieve_tree(
            vm.serial,
            remote_root,
            artifacts / "guest-appimage-evidence",
        )
        if blocked.returncode != 0:
            raise TestFailure(
                "A non-executable AppImage did not preserve the execution "
                "boundary:\n" + blocked.stdout[-8000:]
            )
        _validate_appimage_blocked_events(blocked.stdout)

    def _prepare_windows_executable_fixture(
        self,
        vm: QemuVm,
        artifacts: Path,
        remote_root: str,
        evidence_label: str,
    ) -> tuple[Path, str]:
        assert vm.serial is not None
        fixture_root = artifacts / f"host-windows-executable-{evidence_label}"
        pe = build_windows_executable_fixture(fixture_root)
        downloads = self._prepare_desktop_file_check(vm, remote_root)
        vm.serial.upload(pe, f"{downloads}/{pe.name}", 0o644)
        validation = vm.serial.run(
            f"set -euo pipefail\n"
            f"chown {self.defaults.username}:{self.defaults.username} "
            f"{shlex.quote(downloads)}/{pe.name}\n"
            f"test \"$(head -c2 {shlex.quote(downloads)}/{pe.name})\" = MZ\n"
            f"pe_mime=$(runuser -u {self.defaults.username} -- "
            f"xdg-mime query filetype {shlex.quote(downloads)}/{pe.name})\n"
            f"pe_default=$(runuser -u {self.defaults.username} -- "
            f"xdg-mime query default \"$pe_mime\")\n"
            f"printf 'pe-mime=%s\\npe-default=%s\\n' \"$pe_mime\" \"$pe_default\"\n"
            "command -v exe-thumbnailer\n"
            "test -f /usr/share/thumbnailers/exe-thumbnailer.thumbnailer\n"
            "grep -Fq 'application/vnd.microsoft.portable-executable' "
            "/usr/share/thumbnailers/exe-thumbnailer.thumbnailer\n"
            f"file {shlex.quote(downloads)}/{pe.name}\n"
            f"sha256sum {shlex.quote(downloads)}/{pe.name}",
            timeout=120,
            check=False,
        )
        (artifacts / f"windows-executable-{evidence_label}-fixture.txt").write_text(
            validation.stdout + "\n", encoding="utf-8"
        )
        if validation.returncode != 0:
            raise TestFailure(
                "Windows PE fixture structural validation failed before Nautilus "
                "activation:\n" + validation.stdout[-8000:]
            )
        _validate_windows_executable_fixture_contract(validation.stdout)
        return pe, downloads

    def _exercise_windows_executable_thumbnail(
        self,
        vm: QemuVm,
        scenario: Scenario,
        artifacts: Path,
    ) -> None:
        assert vm.serial is not None
        self.status(
            scenario.id,
            "Generating the embedded PE icon through Nautilus' thumbnailer",
        )
        remote_root = "/run/anduinos-acceptance-windows-thumbnail"
        self._prepare_windows_executable_fixture(
            vm,
            artifacts,
            remote_root,
            "thumbnail",
        )
        command = _desktop_command(
            self.defaults.username,
            (
                "python3",
                f"{remote_root}/atspi_driver.py",
                "windows-executable-thumbnail",
                "--evidence",
                f"{remote_root}/evidence",
            ),
        )
        result = vm.serial.run(command, timeout=180, check=False)
        (artifacts / "windows-executable-thumbnail-events.jsonl").write_text(
            result.stdout + "\n", encoding="utf-8"
        )
        _retrieve_tree(
            vm.serial,
            remote_root,
            artifacts / "guest-windows-thumbnail-evidence",
        )
        if result.returncode != 0:
            raise TestFailure(
                "Nautilus did not generate the local PE fixture thumbnail:\n"
                + result.stdout[-8000:]
            )
        desktop_evidence = _validate_windows_executable_thumbnail_events(
            result.stdout,
            self.defaults.username,
        )
        thumbnail_path = desktop_evidence["cache_path"]
        assert isinstance(thumbnail_path, str)
        thumbnail = artifacts / "windows-executable-thumbnail.png"
        _retrieve_file(vm.serial, thumbnail_path, thumbnail)
        assert_cpu_z_thumbnail(
            thumbnail,
            artifacts / "windows-executable-thumbnail-analysis.json",
        )

    def _exercise_windows_executable_open(
        self,
        vm: QemuVm,
        scenario: Scenario,
        artifacts: Path,
    ) -> None:
        assert vm.serial is not None
        self.status(
            scenario.id,
            "Opening a structurally valid CPU-Z-named PE through Nautilus",
        )
        remote_root = "/run/anduinos-acceptance-windows-open"
        pe, downloads = self._prepare_windows_executable_fixture(
            vm,
            artifacts,
            remote_root,
            "open",
        )
        command = _desktop_command(
            self.defaults.username,
            (
                "python3",
                f"{remote_root}/atspi_driver.py",
                "windows-executable-file",
                "--evidence",
                f"{remote_root}/evidence",
            ),
        )
        result = _run_with_qmp_key_requests(
            vm,
            command,
            timeout=180,
            request_trace=artifacts / "windows-executable-input-trace.jsonl",
        )
        (artifacts / "windows-executable-atspi-events.jsonl").write_text(
            result.stdout + "\n", encoding="utf-8"
        )
        _retrieve_tree(
            vm.serial,
            remote_root,
            artifacts / "guest-windows-executable-evidence",
        )
        _retrieve_file(
            vm.serial,
            "/tmp/anduinos-nautilus.stdout",
            artifacts / "windows-executable-nautilus.stdout",
        )
        if result.returncode != 0:
            diagnostic = vm.serial.run(
                _desktop_command(
                    self.defaults.username,
                    (
                        "bash",
                        "-lc",
                        f"mime=$(xdg-mime query filetype "
                        f"{shlex.quote(downloads)}/{pe.name}); "
                        "printf 'mime=%s\\ndefault=%s\\n' \"$mime\" "
                        "\"$(xdg-mime query default \"$mime\")\"; "
                        "pgrep -af anduinos-exe-runner || true",
                    ),
                ),
                timeout=30,
                check=False,
            )
            (artifacts / "windows-executable-direct-diagnostic.txt").write_text(
                diagnostic.stdout + "\n", encoding="utf-8"
            )
            raise TestFailure(
                "Windows executable desktop dispatch failed through Nautilus "
                "AT-SPI:\n" + result.stdout[-8000:]
            )
        _validate_windows_executable_open_events(result.stdout)

    def _assert_gnome_extensions(
        self,
        vm: QemuVm,
        scenario: Scenario,
        artifacts: Path,
    ) -> None:
        assert vm.serial is not None
        self.status(scenario.id, "Checking every default GNOME extension's live state")
        excluded = (
            "simple-weather@romanlefler.com",
            "network-stats@gnome.noroadsleft.xyz",
        )
        script = f"""
set -euo pipefail
installed=$(find /usr/share/gnome-shell/extensions -mindepth 1 -maxdepth 1 -type d -printf '%f\\n' | sort)
configured=$(gsettings get org.gnome.shell enabled-extensions | tr "'[]," '\\n' | sed 's/^[[:space:]]*//;s/[[:space:]]*$//' | sed '/^$/d' | sort)
expected=$(printf '%s\\n' "$installed" | grep -Fvx {shlex.quote(excluded[0])} | grep -Fvx {shlex.quote(excluded[1])})
printf '%s\\n' "$installed" > /tmp/anduinos-extensions-installed
printf '%s\\n' "$configured" > /tmp/anduinos-extensions-configured
printf '%s\\n' "$expected" > /tmp/anduinos-extensions-expected
diff -u /tmp/anduinos-extensions-expected /tmp/anduinos-extensions-configured
for uuid in $expected; do
    info=$(LC_ALL=C gnome-extensions info "$uuid")
    printf '\\n[%s]\\n%s\\n' "$uuid" "$info"
    printf '%s\\n' "$info" | grep -Eq '^[[:space:]]*State:[[:space:]]+ACTIVE[[:space:]]*$'
done
for uuid in {shlex.quote(excluded[0])} {shlex.quote(excluded[1])}; do
    printf '%s\\n' "$installed" | grep -Fx "$uuid"
    info=$(LC_ALL=C gnome-extensions info "$uuid")
    printf '\\n[%s]\\n%s\\n' "$uuid" "$info"
    ! printf '%s\\n' "$info" | grep -Eq '^[[:space:]]*State:[[:space:]]+ACTIVE[[:space:]]*$'
done
"""
        result = vm.serial.run(
            _desktop_command(
                self.defaults.username,
                ("bash", "-lc", script),
            ),
            timeout=180,
            check=False,
        )
        (artifacts / "installed-gnome-extensions.txt").write_text(
            result.stdout + "\n", encoding="utf-8"
        )
        if result.returncode != 0:
            raise TestFailure(
                "Default GNOME extension inventory/state is invalid:\n"
                + result.stdout[-8000:]
            )

    def _assert_gnome_extension_errors(
        self,
        vm: QemuVm,
        scenario: Scenario,
        artifacts: Path,
    ) -> None:
        """Fail on GNOME Shell/extension errors even when every UUID is active."""

        assert vm.serial is not None
        policy = self.journal_policy
        system = vm.serial.run(
            render_guest_collection_script(policy),
            timeout=180,
            check=False,
        )
        user = vm.serial.run(
            _desktop_command(
                self.defaults.username,
                (
                    "bash",
                    "-lc",
                    render_guest_collection_script(policy, user=True),
                ),
            ),
            timeout=180,
            check=False,
        )
        (artifacts / "extension-system-journal.jsonl").write_text(
            system.stdout + "\n", encoding="utf-8"
        )
        (artifacts / "extension-user-journal.jsonl").write_text(
            user.stdout + "\n", encoding="utf-8"
        )
        if system.returncode != 0 or user.returncode != 0:
            raise TestFailure("Could not collect GNOME extension journal evidence")

        entries = (
            *parse_journal_jsonl(system.stdout, "system"),
            *parse_journal_jsonl(user.stdout, "user"),
        )
        extension_entries = tuple(
            entry for entry in entries if _is_gnome_extension_entry(entry)
        )
        packages = " ".join(shlex.quote(item) for item in policy.packages)
        package_result = vm.serial.run(
            "set -uo pipefail\n"
            f"for package in {packages}; do\n"
            "  dpkg-query -W -f='${Package}\\t${Version}\\n' \"$package\" "
            "2>/dev/null || true\n"
            "done",
            timeout=60,
            check=False,
        )
        if package_result.returncode != 0:
            raise TestFailure("Could not collect extension-policy package versions")
        versions = parse_package_versions(package_result.stdout)
        verdict = policy.classify(extension_entries, scenario, versions)
        (artifacts / "extension-journal-verdict.json").write_text(
            json.dumps(verdict.to_dict(), ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        (artifacts / "extension-journal-verdict.txt").write_text(
            render_verdict(verdict), encoding="utf-8"
        )
        if not verdict.passed:
            raise TestFailure(
                f"GNOME Shell/extensions produced {len(verdict.blockers)} "
                "release-blocking journal error(s); inspect "
                "extension-journal-verdict.json"
            )

    def _exercise_dynamic_resolution(
        self,
        vm: QemuVm,
        scenario: Scenario,
        artifacts: Path,
    ) -> None:
        assert vm.serial is not None
        self.status(scenario.id, "Resizing a real SPICE client and querying Mutter")
        agent = vm.serial.run(
            "set -e\n"
            "pgrep -a spice-vdagent\n"
            "test -c /dev/virtio-ports/com.redhat.spice.0\n",
            timeout=60,
        )
        observations: list[dict[str, object]] = []
        with SpiceDisplayController(vm.spice_socket, artifacts) as viewer:
            baseline, baseline_raw = self._wait_for_display_mode(vm, previous=None)
            for width, height in ((1000, 760), (1420, 920)):
                viewer.resize(width, height)
                mode, raw = self._wait_for_display_mode(
                    vm,
                    previous=(
                        tuple(observations[-1]["mode"])
                        if observations
                        else baseline
                    ),
                )
                observations.append(
                    {
                        "requested_window": [width, height],
                        "mode": list(mode),
                        "gdctl": raw,
                    }
                )
        first = tuple(observations[0]["mode"])
        second = tuple(observations[1]["mode"])
        if first == second or second[0] <= first[0] or second[1] <= first[1]:
            raise TestFailure(
                f"Mutter did not follow increasing SPICE client sizes: {first} -> {second}"
            )
        for observation in observations:
            requested = observation["requested_window"]
            mode = observation["mode"]
            if abs(requested[0] - mode[0]) > 180 or abs(requested[1] - mode[1]) > 180:
                raise TestFailure(
                    "SPICE/Mutter mode is not close to the client geometry: "
                    f"requested={requested}, mode={mode}"
                )
        (artifacts / "installed-spice-resolution.json").write_text(
            json.dumps(
                {
                    "spice_agent": agent.stdout,
                    "baseline": {"mode": list(baseline), "gdctl": baseline_raw},
                    "observations": observations,
                },
                ensure_ascii=False,
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )

    def _wait_for_display_mode(
        self,
        vm: QemuVm,
        previous: tuple[int, int] | None,
    ) -> tuple[tuple[int, int], str]:
        assert vm.serial is not None
        deadline = time.monotonic() + 45
        last = ""
        while time.monotonic() < deadline:
            result = vm.serial.run(
                _desktop_command(
                    self.defaults.username,
                    ("bash", "-lc", "LC_ALL=C gdctl show"),
                ),
                timeout=30,
                check=False,
            )
            last = result.stdout
            match = re.search(r"Current mode.*?([0-9]{3,5})x([0-9]{3,5})@", last, re.DOTALL)
            if result.returncode == 0 and match is not None:
                mode = (int(match.group(1)), int(match.group(2)))
                if previous is None or mode != previous:
                    return mode, last
            time.sleep(1)
        raise TestFailure(
            "Mutter did not report a changed current mode after SPICE resize:\n"
            + last[-4000:]
        )

    def _capture_journal_cursors(self, vm: QemuVm) -> dict[str, str]:
        assert vm.serial is not None
        command = (
            "journalctl -b -n 0 --show-cursor --no-pager | "
            "sed -n 's/^-- cursor: //p'"
        )
        system = vm.serial.run(command, timeout=30, check=False)
        user = vm.serial.run(
            _desktop_command(
                self.defaults.username,
                ("bash", "-lc", command),
            ),
            timeout=30,
            check=False,
        )
        system_values = system.stdout.strip().splitlines()
        user_values = user.stdout.strip().splitlines()
        if (
            system.returncode != 0
            or user.returncode != 0
            or not system_values
            or not user_values
        ):
            raise TestFailure("Could not establish installed desktop journal cursors")
        return {"system": system_values[-1], "user": user_values[-1]}

    def _assert_action_scoped_journal(
        self,
        vm: QemuVm,
        scenario: Scenario,
        cursors: dict[str, str],
        artifacts: Path,
    ) -> None:
        """Classify only messages created by the installed desktop exercises."""

        assert vm.serial is not None
        if set(cursors) != {"system", "user"} or not all(cursors.values()):
            raise TestFailure("Installed desktop journal cursors are incomplete")
        policy = self.journal_policy
        system = vm.serial.run(
            render_guest_collection_script(
                policy,
                after_cursor=cursors["system"],
            ),
            timeout=180,
            check=False,
        )
        user = vm.serial.run(
            _desktop_command(
                self.defaults.username,
                (
                    "bash",
                    "-lc",
                    render_guest_collection_script(
                        policy,
                        user=True,
                        after_cursor=cursors["user"],
                    ),
                ),
            ),
            timeout=180,
            check=False,
        )
        (artifacts / "desktop-actions-system-journal.jsonl").write_text(
            system.stdout + "\n", encoding="utf-8"
        )
        (artifacts / "desktop-actions-user-journal.jsonl").write_text(
            user.stdout + "\n", encoding="utf-8"
        )
        if system.returncode != 0 or user.returncode != 0:
            raise TestFailure("Could not collect action-scoped desktop journal")
        packages = " ".join(shlex.quote(item) for item in policy.packages)
        package_result = vm.serial.run(
            "set -uo pipefail\n"
            f"for package in {packages}; do\n"
            "  dpkg-query -W -f='${Package}\\t${Version}\\n' \"$package\" "
            "2>/dev/null || true\n"
            "done",
            timeout=60,
            check=False,
        )
        if package_result.returncode != 0:
            raise TestFailure("Could not collect action-journal package versions")
        entries = (
            *parse_journal_jsonl(system.stdout, "system"),
            *parse_journal_jsonl(user.stdout, "user"),
        )
        verdict = policy.classify(
            entries,
            scenario,
            parse_package_versions(package_result.stdout),
            action_scope="installed-desktop-gate",
        )
        (artifacts / "desktop-actions-journal-verdict.json").write_text(
            json.dumps(verdict.to_dict(), ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        (artifacts / "desktop-actions-journal-verdict.txt").write_text(
            render_verdict(verdict), encoding="utf-8"
        )
        if not verdict.passed:
            raise TestFailure(
                f"Installed desktop actions produced {len(verdict.blockers)} "
                "release-blocking journal error(s); inspect "
                "desktop-actions-journal-verdict.json"
            )

    def _assert_journal_health(
        self,
        vm: QemuVm,
        scenario: Scenario,
        artifacts: Path,
    ) -> None:
        assert vm.serial is not None
        self.status(
            scenario.id,
            "Classifying journal blockers and versioned known diagnostics",
        )
        policy = self.journal_policy
        shutil.copy2(
            Path(__file__).parents[1] / "journal-policy.json",
            artifacts / "journal-policy.json",
        )
        system_journal = vm.serial.run(
            render_guest_collection_script(policy),
            timeout=180,
            check=False,
        )
        user_journal = vm.serial.run(
            _desktop_command(
                self.defaults.username,
                (
                    "bash",
                    "-lc",
                    render_guest_collection_script(policy, user=True),
                ),
            ),
            timeout=180,
            check=False,
        )
        (artifacts / "installed-system-journal.jsonl").write_text(
            system_journal.stdout + "\n", encoding="utf-8"
        )
        (artifacts / "installed-user-journal.jsonl").write_text(
            user_journal.stdout + "\n", encoding="utf-8"
        )
        if system_journal.returncode != 0 or user_journal.returncode != 0:
            raise TestFailure(
                "Could not collect structured system and user journal evidence"
            )

        system_units = vm.serial.run(
            "systemctl --failed --no-legend --plain",
            timeout=60,
            check=False,
        )
        user_units = vm.serial.run(
            _desktop_command(
                self.defaults.username,
                (
                    "bash",
                    "-lc",
                    "systemctl --user --failed --no-legend --plain",
                ),
            ),
            timeout=60,
            check=False,
        )
        if system_units.returncode != 0 or user_units.returncode != 0:
            raise TestFailure("Could not query failed systemd units")

        packages = " ".join(shlex.quote(item) for item in policy.packages)
        package_result = vm.serial.run(
            "set -uo pipefail\n"
            f"for package in {packages}; do\n"
            "  dpkg-query -W -f='${Package}\\t${Version}\\n' "
            '"$package" 2>/dev/null || true\n'
            "done",
            timeout=60,
        )
        package_versions = parse_package_versions(package_result.stdout)
        (artifacts / "installed-journal-package-versions.txt").write_text(
            package_result.stdout + "\n", encoding="utf-8"
        )

        functional_script = r"""
set -euo pipefail
shell_pid=$(pgrep -n -x gnome-shell)
keyboard_pid=$(pgrep -n -x gsd-keyboard)
keyring_pid=$(pgrep -n -x gnome-keyring-d)
test -n "$shell_pid"
test -n "$keyboard_pid"
test -n "$keyring_pid"
sources=$(gsettings get org.gnome.desktop.input-sources sources)
printf 'gnome-shell-pid=%s\n' "$shell_pid"
printf 'gsd-keyboard-pid=%s\n' "$keyboard_pid"
printf 'gnome-keyring-pid=%s\n' "$keyring_pid"
printf 'input-sources=%s\n' "$sources"
"""
        if scenario.rime:
            functional_script += "printf '%s' \"$sources\" | grep -q \"'ibus', 'rime'\"\n"
        functional = vm.serial.run(
            _desktop_command(
                self.defaults.username,
                ("bash", "-lc", functional_script),
            ),
            timeout=60,
            check=False,
        )
        (artifacts / "installed-journal-functional-health.txt").write_text(
            functional.stdout + "\n", encoding="utf-8"
        )

        entries = parse_journal_jsonl(system_journal.stdout, "system") + (
            parse_journal_jsonl(user_journal.stdout, "user")
        )
        verdict = policy.classify(
            entries,
            scenario,
            package_versions,
            failed_system_units=system_units.stdout.splitlines(),
            failed_user_units=user_units.stdout.splitlines(),
        )
        report = render_verdict(verdict)
        (artifacts / "installed-journal-verdict.json").write_text(
            json.dumps(verdict.to_dict(), indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        (artifacts / "installed-system-journal-gate.txt").write_text(
            "=== systemctl --failed ===\n"
            + (system_units.stdout or "none")
            + "\n\n"
            + report,
            encoding="utf-8",
        )
        (artifacts / "installed-user-journal-gate.txt").write_text(
            "=== systemctl --user --failed ===\n"
            + (user_units.stdout or "none")
            + "\n\n"
            + report,
            encoding="utf-8",
        )
        self.status(
            scenario.id,
            f"Journal: {len(verdict.blockers)} blockers, "
            f"{len(verdict.known_diagnostics)} known diagnostics",
        )
        self._check_note(
            scenario,
            "journal.boot-and-idle",
            f"{len(verdict.blockers)} blockers; "
            f"{len(verdict.known_diagnostics)} known diagnostics",
        )
        failures = []
        if functional.returncode != 0:
            failures.append(
                "GNOME Shell, keyboard, keyring, or input-source functional "
                "health check failed"
            )
        if not verdict.passed:
            failures.append(
                f"{len(verdict.blockers)} unexpected journal/systemd blocker(s)"
            )
        if failures:
            raise TestFailure(
                "; ".join(failures)
                + "; inspect installed-journal-verdict.json and "
                "installed-journal-functional-health.txt"
            )

    def _assert_passive_plymouth_boot(
        self,
        vm: QemuVm,
        scenario: Scenario,
        artifacts: Path,
    ) -> None:
        """Observe an ordinary installed boot without editing or driving GRUB."""

        watermark = artifacts / "plymouth-watermark.png"
        if not watermark.is_file() or not watermark.stat().st_size:
            raise TestFailure("Installed AnduinOS Plymouth watermark is missing")
        self.status(
            scenario.id,
            "Watching an unmodified installed boot for the AnduinOS Plymouth logo",
        )
        vm.start(attach_iso=False, phase="plymouth-passive")
        deadline = time.monotonic() + self.options.boot_timeout_seconds
        probe = artifacts / "plymouth-probe.png"
        observations: list[dict[str, object]] = []
        matched: dict[str, object] | None = None
        try:
            while time.monotonic() < deadline and vm.running:
                try:
                    probe = vm.screenshot("plymouth-probe")
                    result = plymouth_match(probe, watermark)
                    result["seconds"] = round(
                        self.options.boot_timeout_seconds
                        - (deadline - time.monotonic()),
                        2,
                    )
                    observations.append(result)
                    if result.get("matched") is True:
                        matched = result
                        shutil.copy2(probe, artifacts / "plymouth-branding.png")
                        break
                except (OSError, ProtocolError):
                    pass
                time.sleep(0.2 if self.architecture is Architecture.AMD64 else 0.5)
        finally:
            vm.stop()
        report = {
            "matched": matched is not None,
            "match": matched,
            "observations": observations,
            "boot_mode": "passive; ISO detached; no GRUB or guest input",
        }
        (artifacts / "plymouth-analysis.json").write_text(
            json.dumps(report, indent=2) + "\n", encoding="utf-8"
        )
        probe.unlink(missing_ok=True)
        if matched is None:
            raise TestFailure(
                "An ordinary installed boot never displayed the installed "
                "AnduinOS Plymouth watermark"
            )

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
            "MokManager keyboard workflow completed; lifecycle verification follows.\n",
            encoding="utf-8",
        )

    def _assert_mok_enrollment_lifecycle(
        self,
        vm: QemuVm,
        scenario: Scenario,
        artifacts: Path,
    ) -> None:
        if not scenario.mok_enrollment:
            raise TestFailure("MOK lifecycle assertion used for a non-enrollment case")
        assert vm.serial is not None
        pending_path = artifacts / "target-grub-one-shot.txt"
        try:
            pending_output = pending_path.read_text(encoding="utf-8")
        except OSError as error:
            raise TestFailure(f"Cannot read pre-enrollment MOK evidence: {error}") from error
        result = vm.serial.run(
            r"""
set -euo pipefail
state=$(mokutil --sb-state)
printf '%s\n' "$state" | grep -qi 'SecureBoot enabled'
test -z "$(mokutil --list-new 2>/dev/null)"
certificate=/var/lib/shim-signed/mok/MOK.der
test -s "$certificate"
expected=$(openssl x509 -inform DER -in "$certificate" -noout -fingerprint -sha1 | cut -d= -f2 | tr -d ':' | tr '[:lower:]' '[:upper:]')
normalized=$(mokutil --list-enrolled | tr -d ':' | tr '[:lower:]' '[:upper:]')
printf '%s' "$normalized" | grep -Fq "$expected"
printf 'MOK_SECURE_BOOT=enabled\n'
printf 'MOK_PENDING=none\n'
printf 'MOK_ENROLLED_FINGERPRINT=%s\n' "$expected"
""",
            check=False,
        )
        destination = artifacts / "mok-enrollment-verification.txt"
        destination.write_text(result.stdout + "\n", encoding="utf-8")
        if result.returncode != 0:
            raise TestFailure(
                "Installed MOK lifecycle probe failed with exit "
                f"{result.returncode}:\n{result.stdout[-8000:]}"
            )
        _validate_mok_lifecycle_evidence(pending_output, result.stdout)
        self._check_note(
            scenario,
            "mok-enrollment",
            "Secure Boot enabled; pending cleared; installed certificate enrolled",
        )

    def _show_target_grub_once(
        self,
        vm: QemuVm,
        scenario: Scenario,
        artifacts: Path,
    ) -> InstalledBootFiles:
        """Validate target boot files and arm a reversible normal GRUB boot."""

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
test -s /cdrom/casper/vmlinuz
target_kernel_sha256=$(sha256sum "$mountpoint/boot/$kernel" | awk '{{ print $1 }}')
iso_kernel_sha256=$(sha256sum /cdrom/casper/vmlinuz | awk '{{ print $1 }}')
lsinitramfs "$mountpoint/boot/$initrd" >/dev/null
printf 'ANDUINOS_TARGET_KERNEL_SHA256=%s\n' "$target_kernel_sha256"
printf 'ANDUINOS_ISO_KERNEL_SHA256=%s\n' "$iso_kernel_sha256"
printf 'ANDUINOS_INITRD_CHECK=ok\n'
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
printf 'ANDUINOS_KERNEL=%s\n' "$kernel"
printf 'ANDUINOS_INITRD=%s\n' "$initrd"
grub-editenv "$mountpoint/boot/grub/grubenv" list
{render_installed_grub_instrumentation(self.architecture, mounted_target=True)}
sync
"""
        result = vm.serial.run(script, timeout=120)
        (artifacts / "target-grub-one-shot.txt").write_text(
            result.stdout + "\n", encoding="utf-8"
        )
        _validate_target_boot_integrity(result.stdout)
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


def _is_gnome_extension_entry(entry) -> bool:
    component = entry.component_text
    return bool(
        re.search(r"(^|[|/])gnome-shell($|[|/])", component, re.IGNORECASE)
        or re.search(r"\b(extension|JS ERROR)\b", entry.message, re.IGNORECASE)
    )


def _scenario_json(scenario: Scenario) -> dict[str, object]:
    value = asdict(scenario)
    value["architectures"] = [item.value for item in scenario.architectures]
    for key in ("firmware", "network", "filesystem", "ssh"):
        value[key] = value[key].value
    return value


_SUPPORTED_GUEST_QMP_KEYS = frozenset(
    {
        "tab",
        "spc",
        "ret",
        "down",
        "alt-tab",
        "alt-f4",
        "ctrl-shift-u",
        "meta_l-tab",
        "meta_l-i",
        "meta_l-u",
        "meta_l-shift-s",
        "meta_l",
        "esc",
        "shift-f10",
        "shift-tab",
    }
)


def _guest_qmp_key_supported(key: str) -> bool:
    return key in _SUPPORTED_GUEST_QMP_KEYS or re.fullmatch(
        r"alt-[a-z]", key
    ) is not None


def _run_with_qmp_key_requests(
    vm: QemuVm,
    command: str,
    *,
    timeout: float,
    secret_text: str | None = None,
    secret_texts: dict[str, str] | None = None,
    text_inputs: dict[str, str] | None = None,
    request_trace: Path | None = None,
):
    """Run a serial command while serving semantic keyboard requests via QMP."""

    assert vm.serial is not None and vm.qmp is not None
    transcript = vm.serial.transcript
    offset = transcript.stat().st_size if transcript.exists() else 0
    partial = ""
    handled: set[str] = set()

    def record_request(**values: object) -> None:
        if request_trace is None:
            return
        request_trace.parent.mkdir(parents=True, exist_ok=True)
        with request_trace.open("a", encoding="utf-8") as stream:
            stream.write(
                json.dumps(
                    {"event": "host-qmp-request", **values},
                    ensure_ascii=False,
                )
                + "\n"
            )

    def serve_transcript() -> None:
        nonlocal offset, partial
        if not transcript.exists():
            return
        with transcript.open("rb") as stream:
            stream.seek(offset)
            chunk = stream.read()
            offset = stream.tell()
        if not chunk:
            return
        partial += chunk.decode("utf-8", errors="replace").replace("\r", "")
        lines = partial.split("\n")
        partial = lines.pop()
        for line in lines:
            double_click_request = _parse_spice_double_click_request(line)
            if double_click_request is not None:
                identifier, x_px, y_px, bounds, double_click_time_ms = (
                    double_click_request
                )
                if identifier in handled:
                    continue
                handled.add(identifier)
                started = time.monotonic_ns()
                try:
                    vm.qmp.validate_pointer_bounds(x_px, y_px, bounds)
                    with SpiceInputClient(vm.spice_socket) as pointer:
                        pointer.double_click_pointer_pixels(
                            x_px,
                            y_px,
                            double_click_time_ms=double_click_time_ms,
                        )
                except BaseException as error:
                    record_request(
                        request=identifier,
                        kind="double-click",
                        x_px=x_px,
                        y_px=y_px,
                        button="left",
                        clicks=2,
                        positioning_clicks=1,
                        double_click_time_ms=double_click_time_ms,
                        input_transport="spice-vdagent",
                        completed=False,
                        duration_ms=round(
                            (time.monotonic_ns() - started) / 1_000_000,
                            3,
                        ),
                        error=f"{type(error).__name__}: {error}",
                    )
                    raise
                record_request(
                    request=identifier,
                    kind="double-click",
                    x_px=x_px,
                    y_px=y_px,
                    button="left",
                    clicks=2,
                    positioning_clicks=1,
                    double_click_time_ms=double_click_time_ms,
                    input_transport="spice-vdagent",
                    client_mouse_mode=2,
                    position_coupled_to_press=True,
                    completed=True,
                    duration_ms=round(
                        (time.monotonic_ns() - started) / 1_000_000,
                        3,
                    ),
                )
                continue
            click_request = _parse_qmp_click_request(line)
            if click_request is not None:
                identifier, x_px, y_px, button = click_request
                if identifier in handled:
                    continue
                handled.add(identifier)
                started = time.monotonic_ns()
                try:
                    vm.qmp.click_pointer_pixels(
                        x_px,
                        y_px,
                        button=button,
                    )
                except BaseException as error:
                    record_request(
                        request=identifier,
                        kind="click",
                        x_px=x_px,
                        y_px=y_px,
                        button=button,
                        completed=False,
                        duration_ms=round(
                            (time.monotonic_ns() - started) / 1_000_000,
                            3,
                        ),
                        error=f"{type(error).__name__}: {error}",
                    )
                    raise
                record_request(
                    request=identifier,
                    kind="click",
                    x_px=x_px,
                    y_px=y_px,
                    button=button,
                    completed=True,
                    duration_ms=round(
                        (time.monotonic_ns() - started) / 1_000_000,
                        3,
                    ),
                )
                continue
            secret_request = _parse_qmp_secret_request(line)
            if secret_request is not None:
                if secret_request in handled:
                    continue
                supplied = _resolve_qmp_secret(
                    secret_request,
                    secret_text=secret_text,
                    secret_texts=secret_texts,
                )
                handled.add(secret_request)
                vm.qmp.type_text(supplied, interval=0.06)
                continue
            text_request = _parse_qmp_text_request(line)
            if text_request is not None:
                if text_request in handled:
                    continue
                if text_inputs is None or text_request not in text_inputs:
                    raise TestFailure(
                        f"Guest requested text {text_request!r}, but no value was supplied"
                    )
                value = text_inputs[text_request]
                if not isinstance(value, str) or not value:
                    raise TestFailure(
                        f"Guest text request {text_request!r} resolved to an invalid value"
                    )
                handled.add(text_request)
                vm.qmp.type_text(value, interval=0.06)
                continue
            request = _parse_qmp_key_request(line)
            if request is None:
                continue
            identifier, key = request
            if identifier in handled:
                continue
            if not _guest_qmp_key_supported(key):
                raise TestFailure(f"Guest requested unsupported QMP key: {key!r}")
            handled.add(identifier)
            started = time.monotonic_ns()
            try:
                vm.qmp.send_key(key)
            except BaseException as error:
                record_request(
                    request=identifier,
                    kind="key",
                    key=key,
                    input_transport="qmp-hmp",
                    completed=False,
                    duration_ms=round(
                        (time.monotonic_ns() - started) / 1_000_000,
                        3,
                    ),
                    error=f"{type(error).__name__}: {error}",
                )
                raise
            record_request(
                request=identifier,
                kind="key",
                key=key,
                input_transport="qmp-hmp",
                completed=True,
                duration_ms=round(
                    (time.monotonic_ns() - started) / 1_000_000,
                    3,
                ),
            )

    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(
            vm.serial.run,
            command,
            timeout=timeout,
            check=False,
        )
        while not future.done():
            serve_transcript()
            time.sleep(0.05)
        result = future.result()
        # The guest may emit its final request and exit between the loop's
        # done() check and the next transcript read. Drain once after joining
        # the command so terminal QMP requests cannot be silently lost.
        serve_transcript()
        return result


def _parse_spice_double_click_request(
    line: str,
) -> tuple[str, float, float, tuple[int, int, int, int], int] | None:
    """Parse one semantic two-press gesture at an AT-SPI-derived pixel."""

    start = line.find('{"event": "spice-double-click"')
    if start < 0:
        return None
    try:
        request = json.loads(line[start:])
    except json.JSONDecodeError:
        return None
    identifier = request.get("request")
    x = request.get("x_px")
    y = request.get("y_px")
    clicks = request.get("clicks")
    positioning_clicks = request.get("positioning_clicks")
    double_click_time_ms = request.get("double_click_time_ms")
    button = request.get("button")
    bounds = request.get("bounds")
    if not isinstance(identifier, str) or not identifier:
        return None
    if (
        isinstance(x, bool)
        or isinstance(y, bool)
        or not isinstance(x, (int, float))
        or not isinstance(y, (int, float))
        or float(x) < 0.0
        or float(y) < 0.0
        or clicks != 2
        or positioning_clicks != 1
        or isinstance(double_click_time_ms, bool)
        or not isinstance(double_click_time_ms, int)
        or not 100 <= double_click_time_ms <= 5000
        or button != "left"
        or not isinstance(bounds, list)
        or len(bounds) != 4
        or any(isinstance(value, bool) or not isinstance(value, int) for value in bounds)
        or min(bounds) < 0
        or bounds[2] < 2
        or bounds[3] < 2
    ):
        return None
    typed_bounds = (bounds[0], bounds[1], bounds[2], bounds[3])
    expected_x = bounds[0] + bounds[2] / 2
    expected_y = bounds[1] + bounds[3] / 2
    if abs(float(x) - expected_x) > 0.001 or abs(float(y) - expected_y) > 0.001:
        return None
    return identifier, float(x), float(y), typed_bounds, double_click_time_ms


def _parse_qmp_click_request(
    line: str,
) -> tuple[str, float, float, str] | None:
    """Parse a guest request to click an AT-SPI-derived screen pixel."""

    start = line.find('{"event": "qmp-click"')
    if start < 0:
        return None
    try:
        request = json.loads(line[start:])
    except json.JSONDecodeError:
        return None
    identifier = request.get("request")
    x = request.get("x_px")
    y = request.get("y_px")
    button = request.get("button", "left")
    if not isinstance(identifier, str) or not identifier:
        return None
    if (
        isinstance(x, bool)
        or isinstance(y, bool)
        or not isinstance(x, (int, float))
        or not isinstance(y, (int, float))
    ):
        return None
    pixel_x = float(x)
    pixel_y = float(y)
    if pixel_x < 0.0 or pixel_y < 0.0:
        return None
    if button not in {"left", "right"}:
        return None
    # A single-click request must remain a single click.  The dedicated
    # The dedicated SPICE double-click protocol sends exactly two complete
    # primary-button gestures after a rendered hover acknowledgement.
    if "click_count" in request:
        return None
    return identifier, pixel_x, pixel_y, button


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


def _parse_qmp_text_request(line: str) -> str | None:
    """Parse a named, non-secret deterministic text-input request."""

    start = line.find('{"event": "qmp-text"')
    if start < 0:
        return None
    try:
        request = json.loads(line[start:])
    except json.JSONDecodeError:
        return None
    identifier = request.get("request")
    if not isinstance(identifier, str) or not identifier:
        return None
    return identifier


def _parse_qmp_secret_request(line: str) -> str | None:
    """Parse an opaque request whose secret value never crosses the guest log."""

    start = line.find('{"event": "qmp-secret"')
    if start < 0:
        return None
    try:
        request = json.loads(line[start:])
    except json.JSONDecodeError:
        return None
    identifier = request.get("request")
    if not isinstance(identifier, str) or not identifier:
        return None
    return identifier


def _resolve_qmp_secret(
    request: str,
    *,
    secret_text: str | None,
    secret_texts: dict[str, str] | None,
) -> str:
    """Resolve an opaque guest request without putting its value in logs."""

    if secret_texts is not None and request in secret_texts:
        value = secret_texts[request]
    else:
        value = secret_text
    if value is None:
        raise TestFailure(
            f"Guest requested secret {request!r}, but no value was supplied"
        )
    if not value:
        raise TestFailure(f"Guest secret {request!r} must not be empty")
    return value


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


def _validate_target_boot_integrity(output: str) -> None:
    """Reject a damaged installed kernel or an unreadable generated initramfs."""

    def exact_value(key: str) -> str:
        matches = re.findall(rf"^{re.escape(key)}=(\S+)$", output, re.MULTILINE)
        if len(matches) != 1:
            raise TestFailure(
                f"Target boot integrity probe did not return exactly one {key}"
            )
        return matches[0]

    target_hash = exact_value("ANDUINOS_TARGET_KERNEL_SHA256")
    iso_hash = exact_value("ANDUINOS_ISO_KERNEL_SHA256")
    for label, digest in (("target kernel", target_hash), ("ISO kernel", iso_hash)):
        if re.fullmatch(r"[0-9a-f]{64}", digest) is None:
            raise TestFailure(f"{label} returned an invalid SHA-256 digest")
    if target_hash != iso_hash:
        raise TestFailure(
            "Installed kernel differs byte-for-byte from the immutable ISO kernel"
        )
    if exact_value("ANDUINOS_INITRD_CHECK") != "ok":
        raise TestFailure("Installed initramfs did not pass structural validation")


def _validate_mok_lifecycle_evidence(
    pending_output: str,
    enrolled_output: str,
) -> None:
    """Correlate the pre-reboot pending certificate with the enrolled key."""

    def exact(output: str, key: str) -> str:
        matches = re.findall(rf"^{re.escape(key)}=(\S+)$", output, re.MULTILINE)
        if len(matches) != 1:
            raise TestFailure(f"MOK lifecycle evidence requires exactly one {key}")
        return matches[0]

    pending = exact(pending_output, "MOK_PENDING_FINGERPRINT")
    enrolled = exact(enrolled_output, "MOK_ENROLLED_FINGERPRINT")
    for label, fingerprint in (("pending", pending), ("enrolled", enrolled)):
        if re.fullmatch(r"[0-9A-F]{40}", fingerprint) is None:
            raise TestFailure(f"MOK {label} fingerprint is malformed")
    if exact(enrolled_output, "MOK_SECURE_BOOT") != "enabled":
        raise TestFailure("Secure Boot is not enabled after MOK enrollment")
    if exact(enrolled_output, "MOK_PENDING") != "none":
        raise TestFailure("MOK enrollment still has a pending certificate")
    if pending != enrolled:
        raise TestFailure(
            "The enrolled MOK fingerprint differs from the pre-reboot request"
        )


_GRAPHICAL_USER_SCRIPT = r"""
set -e
for runtime in $(find /run/user -mindepth 1 -maxdepth 1 -type d | sort -V -r); do
    uid=${runtime##*/}
    user=$(getent passwd "$uid" | cut -d: -f1)
    shell=$(getent passwd "$uid" | cut -d: -f7)
    [ -n "$user" ] || continue
    case "$user:$shell" in
        gdm:*|gdm-greeter:*|*:/usr/sbin/nologin|*:/bin/false) continue ;;
    esac
    [ -S "$runtime/bus" ] || continue
    find "$runtime" -maxdepth 1 -type s -name 'wayland-[0-9]*' 2>/dev/null | grep -q . || continue
    printf '%s\n' "$user"
    exit 0
done
exit 1
"""


def _graphical_user(console) -> str:
    result = console.run(_GRAPHICAL_USER_SCRIPT)
    return result.stdout.strip().splitlines()[-1]


def _graphical_user_optional(console) -> str:
    result = console.run(_GRAPHICAL_USER_SCRIPT, check=False)
    if result.returncode != 0 or not result.stdout.strip():
        return ""
    return result.stdout.strip().splitlines()[-1]


def _fixture_contract_values(
    output: str,
    required: set[str],
) -> dict[str, str]:
    values: dict[str, str] = {}
    for raw_line in output.splitlines():
        key, separator, value = raw_line.partition("=")
        if separator and key in required:
            if key in values:
                raise TestFailure(f"Duplicate desktop fixture evidence: {key}")
            values[key] = value.strip()
    missing = sorted(required - values.keys())
    if missing:
        raise TestFailure(
            "Desktop fixture evidence is incomplete: " + ", ".join(missing)
        )
    return values


def _validate_appimage_fixture_contract(output: str) -> None:
    """Validate native executable dispatch without inventing a MIME runner."""

    values = _fixture_contract_values(
        output,
        {
            "appimage-mime",
            "appimage-default",
            "appimage-runner-present",
            "appimage-mode",
            "appimage-blocked-mode",
        },
    )
    if values["appimage-mime"] not in {
        "application/vnd.appimage",
        "application/x-iso9660-appimage",
    }:
        raise TestFailure(
            "AppImage received an unsupported MIME type: "
            + values["appimage-mime"]
        )
    if values["appimage-default"]:
        raise TestFailure(
            "Executable AppImage unexpectedly depends on a MIME handler: "
            + values["appimage-default"]
        )
    if values["appimage-runner-present"] != "no":
        raise TestFailure("The obsolete AppImage MIME runner is still installed")
    if values["appimage-mode"] != "755":
        raise TestFailure(
            "The positive AppImage fixture is not explicitly executable: "
            + values["appimage-mode"]
        )
    if values["appimage-blocked-mode"] != "644":
        raise TestFailure(
            "The negative AppImage fixture accidentally has execute permission: "
            + values["appimage-blocked-mode"]
        )


def _validate_appimage_blocked_events(output: str) -> None:
    events: list[dict[str, object]] = []
    for line in output.splitlines():
        try:
            value = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict) and isinstance(value.get("event"), str):
            events.append(value)
    blocked = [
        value
        for value in events
        if value.get("event") == "nautilus-open-blocked"
    ]
    if len(blocked) != 1:
        raise TestFailure("Nautilus returned no unique blocked AppImage event")
    value = blocked[0]
    if (
        value.get("filename") != "AnduinOS-Blocked.AppImage"
        or value.get("executable") is not False
        or value.get("fixture_window_visible") is not False
        or value.get("process_running") is not False
        or value.get("activation_method")
        not in {"host-spice-double-click", "selected-item-qmp-enter"}
    ):
        raise TestFailure("The non-executable AppImage crossed the execution boundary")


def _validate_windows_executable_fixture_contract(output: str) -> None:
    """Validate PE MIME dispatch without depending on the AppImage result."""

    values = _fixture_contract_values(output, {"pe-mime", "pe-default"})
    if values["pe-mime"] != "application/vnd.microsoft.portable-executable":
        raise TestFailure(
            "CPU-Z PE fixture received the wrong MIME type: " + values["pe-mime"]
        )
    if values["pe-default"] != "com.anduinos.ExeRunner.desktop":
        rendered = values["pe-default"] or "<none>"
        raise TestFailure(
            "CPU-Z PE default handler is missing or incorrect: " + rendered
        )


def _validate_windows_executable_thumbnail_events(
    output: str,
    username: str,
) -> dict[str, object]:
    """Require one visible, retrievable Nautilus thumbnail for the PE fixture."""

    events = _driver_events(output)
    thumbnails = [
        (index, value)
        for index, value in enumerate(events)
        if value.get("event") == "file-thumbnail"
        and value.get("filename") == "cpu-z.exe"
    ]
    if len(thumbnails) != 1:
        raise TestFailure("Windows PE workflow did not emit one thumbnail event")
    _, thumbnail = thumbnails[0]
    cache_path = thumbnail.get("cache_path")
    visible = thumbnail.get("visible_nodes")
    expected_uri = f"file:///home/{username}/Downloads/cpu-z.exe"
    if (
        thumbnail.get("uri") != expected_uri
        or not isinstance(cache_path, str)
        or re.fullmatch(
            rf"/home/{re.escape(username)}/\.cache/thumbnails/"
            r"(?:normal|large|x-large|xx-large)/[0-9a-f]{32}\.png",
            cache_path,
        )
        is None
        or isinstance(thumbnail.get("cache_size"), bool)
        or not isinstance(thumbnail.get("cache_size"), int)
        or thumbnail["cache_size"] <= 128
        or not isinstance(visible, list)
        or not any(
            isinstance(item, dict) and item.get("name") == "cpu-z.exe"
            for item in visible
        )
    ):
        raise TestFailure("Windows PE fixture returned invalid thumbnail evidence")
    return thumbnail


def _validate_windows_executable_open_events(output: str) -> None:
    """Require one real Nautilus activation followed by EXE Runner UI."""

    events = _driver_events(output)
    opened = [
        (index, value)
        for index, value in enumerate(events)
        if value.get("event") == "nautilus-open"
        and value.get("filename") == "cpu-z.exe"
    ]
    recommendations = [
        (index, value)
        for index, value in enumerate(events)
        if value.get("event") == "cpu-z-recommendation"
    ]
    if len(opened) != 1 or len(recommendations) != 1:
        raise TestFailure(
            "Windows PE workflow did not emit one open and EXE Runner "
            "recommendation event"
        )
    opened_index, activation = opened[0]
    recommendation_index, recommendation = recommendations[0]
    if (
        activation.get("activation_method")
        not in {"host-spice-double-click", "selected-item-qmp-enter"}
        or not isinstance(activation.get("observed"), str)
        or not activation["observed"]
        or recommendation.get("application") != "AnduinOS Windows EXE Runner"
    ):
        raise TestFailure("Windows PE fixture did not reach the real EXE Runner")
    if not opened_index < recommendation_index:
        raise TestFailure("Windows PE workflow events occurred out of order")


def _driver_events(output: str) -> list[dict[str, object]]:
    events: list[dict[str, object]] = []
    for line in output.splitlines():
        try:
            value = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict) and isinstance(value.get("event"), str):
            events.append(value)
    return events


def _validate_installed_region_ui_events(output: str) -> None:
    values = [
        value
        for value in _driver_events(output)
        if value.get("event") == "installed-region-zh-cn"
    ]
    if len(values) != 1:
        raise TestFailure(
            "Installed GNOME region probe did not emit one exact UI observation"
        )
    value = values[0]
    if value.get("desktop_labels") != ["主目录", "回收站"]:
        raise TestFailure(
            "Installed GNOME desktop is not visibly localized to Simplified Chinese"
        )
    frame = value.get("desktop_frame")
    if (
        not isinstance(frame, dict)
        or frame.get("application") != "gjs"
        or frame.get("role") != "frame"
        or not str(frame.get("name", "")).startswith("Desktop Icons")
    ):
        raise TestFailure(
            "Installed region evidence did not come from the real DING desktop"
        )
    bounds = frame.get("bounds")
    if (
        not isinstance(bounds, list)
        or len(bounds) != 4
        or any(isinstance(item, bool) or not isinstance(item, int) for item in bounds)
        or bounds[2] < 640
        or bounds[3] < 400
    ):
        raise TestFailure("Installed region evidence has no usable desktop bounds")


def _desktop_command(
    user: str,
    command: tuple[str, ...],
    *,
    managed: bool = False,
) -> str:
    rendered = shlex.join(command)
    quoted_user = shlex.quote(user)
    common = f"""
set -e
user={quoted_user}
uid=$(id -u "$user")
runtime=/run/user/$uid
home=$(getent passwd "$user" | cut -d: -f6)
wayland=$(find "$runtime" -maxdepth 1 -type s -name 'wayland-[0-9]*' -printf '%f\\n' 2>/dev/null | head -n1)
test -S "$runtime/bus"
test -n "$wayland"
"""
    environment = r"""
runuser -u "$user" -- env \
    HOME="$home" \
    XDG_RUNTIME_DIR="$runtime" \
    DBUS_SESSION_BUS_ADDRESS="unix:path=$runtime/bus" \
    WAYLAND_DISPLAY="$wayland" DISPLAY=:0 NO_AT_BRIDGE=0 \
    XDG_CURRENT_DESKTOP=GNOME XDG_SESSION_DESKTOP=gnome \
    DESKTOP_SESSION=gnome GDMSESSION=gnome"""
    if managed:
        return common + environment + f""" \
    systemd-run --user --wait --pipe --collect --quiet \
        --setenv=HOME="$home" \
        --setenv=XDG_RUNTIME_DIR="$runtime" \
        --setenv=DBUS_SESSION_BUS_ADDRESS="unix:path=$runtime/bus" \
        --setenv=WAYLAND_DISPLAY="$wayland" --setenv=DISPLAY=:0 \
        --setenv=NO_AT_BRIDGE=0 --setenv=XDG_CURRENT_DESKTOP=GNOME \
        --setenv=XDG_SESSION_DESKTOP=gnome --setenv=DESKTOP_SESSION=gnome \
        --setenv=GDMSESSION=gnome -- {rendered}
"""
    return common + environment + f" \\\n    {rendered}\n"


def _retrieve_tree(console, remote_root: str, destination: Path) -> None:
    token = uuid.uuid4().hex
    remote_archive = f"/run/anduinos-evidence-{token}.tar.gz"
    destination.parent.mkdir(parents=True, exist_ok=True)
    local_archive = destination.parent / f".{destination.name}-{token}.tar.gz"
    console.run(
        "set -euo pipefail\n"
        f"tar -C {shlex.quote(remote_root)} -czf "
        f"{shlex.quote(remote_archive)} evidence\n"
        f"test -s {shlex.quote(remote_archive)}",
        timeout=120,
    )
    try:
        console.download(remote_archive, local_archive)
        destination.mkdir(parents=True, exist_ok=True)
        with tarfile.open(local_archive, mode="r:gz") as archive:
            for member in archive.getmembers():
                path = PurePosixPath(member.name)
                if path.is_absolute() or ".." in path.parts or not member.isfile():
                    continue
                relative = (
                    Path(*path.parts[1:])
                    if path.parts[:1] == ("evidence",)
                    else Path(*path.parts)
                )
                if not relative.parts:
                    continue
                target = destination / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                source = archive.extractfile(member)
                if source is not None:
                    target.write_bytes(source.read())
    finally:
        local_archive.unlink(missing_ok=True)
        console.run(f"rm -f {shlex.quote(remote_archive)}", check=False)


def _retrieve_file(console, source: str, destination: Path) -> None:
    console.download(source, destination, missing_ok=True)


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
    try:
        vm.serial.run("sync", timeout=30)
        # The harness exits the Live VM through QMP instead of asking the
        # desktop session to shut down.  Flush the named target block node
        # explicitly so the next QEMU process cannot observe acknowledged
        # writes or qcow2 metadata still pending at this instrumentation
        # boundary.
        vm.qmp.flush_block_device("target")
        vm.qmp.quit()
        vm.wait(15)
    finally:
        vm.stop()


def _status(identifier: str, message: str) -> None:
    print(f"[{identifier}] {message}", flush=True)
