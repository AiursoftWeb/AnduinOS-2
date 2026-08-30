"""Live boot, graphical installer, target boot, and failure collection phases."""

from .context import *  # noqa: F403


class InstallationPhases:
    def _run_live_phase(
        self,
        vm: QemuVm,
        scenario: Scenario,
        artifacts: Path,
        *,
        wifi_lab: WifiLab | None = None,
    ) -> InstalledBootFiles | None:
        with self._check(scenario, "regional.grub-contract"):
            live_entry = self._assert_grub_regional_contract(artifacts)
        persistent = scenario.live_mode is LiveMode.PERSISTENT
        with self._check(scenario, "live-boot"):
            self.status(
                scenario.id,
                "Booting writable persistent Live media"
                if persistent
                else "Booting original read-only ISO",
            )
            self._boot_live_session(
                vm,
                live_entry,
                persistent=persistent,
                phase=("live-persistent-first" if persistent else "live-temporary"),
            )
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
                check_region=False,
            )
            vm.screenshot(
                "live-persistent-first" if persistent else "live-desktop"
            )
        with self._check(scenario, "live.identity-contract"):
            self.status(
                scenario.id,
                "Checking the exact Live account and automatic-login contract",
            )
            assert_live_identity(
                vm.serial,
                artifacts,
                session_timeout_seconds=self.options.boot_timeout_seconds,
            )
        with self._check(
            scenario,
            "live.persistent-overlay" if persistent else "live.temporary-overlay",
        ):
            if persistent:
                self._create_persistent_live_sentinel(vm, artifacts)
                _power_off(vm)
                self.status(
                    scenario.id,
                    "Rebooting the same Live media to prove durable overlay state",
                )
                self._boot_live_session(
                    vm,
                    live_entry,
                    persistent=True,
                    phase="live-persistent-second",
                )
                assert_live_environment(
                    vm.serial,
                    scenario,
                    artifacts,
                    self.defaults.live_locale,
                    self.defaults.live_timezone,
                    session_timeout_seconds=self.options.boot_timeout_seconds,
                    check_region=False,
                )
                self._assert_persistent_live_sentinel(vm, artifacts)
                vm.screenshot("live-persistent-second")
            else:
                self._assert_temporary_live_overlay(vm, artifacts)
        with self._check(scenario, "packages.live-image-junk-absent"):
            self.status(
                scenario.id,
                "Checking the Live image for forbidden packages",
            )
            assert_no_image_junk(vm.serial, artifacts, "live")
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
        if scenario.firmware.is_uefi:
            with self._check(scenario, "boot.uefi-vendor-registration"):
                self.status(
                    scenario.id,
                    "Checking UEFI vendor entry before the first target boot",
                )
                self._assert_uefi_boot_registration(vm, scenario, artifacts)
        _power_off(vm)
        self.status(scenario.id, "Installation complete; ISO detached")
        return boot_files

    def _boot_live_session(
        self,
        vm: QemuVm,
        regional_entry,
        *,
        persistent: bool,
        phase: str,
    ) -> None:
        entry = self.inspection.persistent_entry if persistent else regional_entry
        extra_arguments = (
            (
                f"locale={self.defaults.live_locale}",
                f"timezone={self.defaults.live_timezone}",
                f"systemd.timezone={self.defaults.live_timezone}",
            )
            if persistent
            else ()
        )
        vm.start(attach_iso=True, phase=phase)
        assert vm.qmp is not None and vm.serial is not None
        boot_iso_with_debug_shell(
            vm.qmp,
            vm.serial,
            self.architecture,
            firmware_delay=self.options.firmware_delay_seconds,
            menu_entry_index=(
                1
                if persistent
                else self.inspection.live_entries.index(regional_entry)
            ),
            menu_path=((1, 1) if persistent else None),
            kernel_arguments=entry.kernel_arguments,
            extra_kernel_arguments=extra_arguments,
            spice_socket=vm.spice_socket,
        )
        vm.serial.timeout = self.options.command_timeout_seconds
        vm.serial.wait_for_shell(self.options.boot_timeout_seconds)

    def _assert_temporary_live_overlay(
        self,
        vm: QemuVm,
        artifacts: Path,
    ) -> None:
        assert vm.serial is not None
        result = vm.serial.run(
            r"""
set -euo pipefail
test ! -e /dev/disk/by-label/ANDUINOS-PERSIST
root_options=$(findmnt -n -o OPTIONS /)
upperdir=$(printf '%s\n' "$root_options" | sed -n 's/.*upperdir=\([^,]*\).*/\1/p')
test -n "$upperdir"
upperdir=$(readlink -f "$upperdir")
upper_fstype=$(findmnt -n -T "$upperdir" -o FSTYPE)
printf 'mode=temporary\nroot-options=%s\nupperdir=%s\nupper-fstype=%s\n' \
    "$root_options" "$upperdir" "$upper_fstype"
test "$upper_fstype" = tmpfs
"""
        )
        (artifacts / "live-temporary-overlay.txt").write_text(
            result.stdout + "\n", encoding="utf-8"
        )

    def _create_persistent_live_sentinel(
        self,
        vm: QemuVm,
        artifacts: Path,
    ) -> None:
        assert vm.serial is not None
        result = vm.serial.run(
            r"""
set -euo pipefail
device=$(readlink -f /dev/disk/by-label/ANDUINOS-PERSIST)
test -b "$device"
test "$(blkid -s TYPE -o value "$device")" = ext4
root_options=$(findmnt -n -o OPTIONS /)
upperdir=$(printf '%s\n' "$root_options" | sed -n 's/.*upperdir=\([^,]*\).*/\1/p')
test -n "$upperdir"
upperdir=$(readlink -f "$upperdir")
upper_source=$(findmnt -n -T "$upperdir" -o SOURCE)
upper_source=${upper_source%%\[*}
test "$(blkid -s LABEL -o value "$upper_source")" = ANDUINOS-PERSIST
test ! -e /var/lib/anduinos-acceptance-live-persistence
printf '%s\n' 'anduinos-persistent-live-v1' \
    > /var/lib/anduinos-acceptance-live-persistence
sync
printf 'mode=persistent-first-boot\ndevice=%s\nupperdir=%s\nupper-source=%s\n' \
    "$device" "$upperdir" "$upper_source"
"""
        )
        (artifacts / "live-persistent-first-boot.txt").write_text(
            result.stdout + "\n", encoding="utf-8"
        )

    def _assert_persistent_live_sentinel(
        self,
        vm: QemuVm,
        artifacts: Path,
    ) -> None:
        assert vm.serial is not None
        result = vm.serial.run(
            r"""
set -euo pipefail
device=$(readlink -f /dev/disk/by-label/ANDUINOS-PERSIST)
test -b "$device"
test "$(blkid -s TYPE -o value "$device")" = ext4
grep -Fxq 'anduinos-persistent-live-v1' \
    /var/lib/anduinos-acceptance-live-persistence
root_options=$(findmnt -n -o OPTIONS /)
upperdir=$(printf '%s\n' "$root_options" | sed -n 's/.*upperdir=\([^,]*\).*/\1/p')
upperdir=$(readlink -f "$upperdir")
upper_source=$(findmnt -n -T "$upperdir" -o SOURCE)
upper_source=${upper_source%%\[*}
test "$(blkid -s LABEL -o value "$upper_source")" = ANDUINOS-PERSIST
printf 'mode=persistent-second-boot\nsentinel=survived\ndevice=%s\nupperdir=%s\nupper-source=%s\n' \
    "$device" "$upperdir" "$upper_source"
"""
        )
        (artifacts / "live-persistent-second-boot.txt").write_text(
            result.stdout + "\n", encoding="utf-8"
        )

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
        self.driver.upload(vm.serial, remote_root)
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
            if scenario.desktop_contracts
            else None
        )
        if scenario.desktop_contracts:
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
        if scenario.desktop_contracts:
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
        if scenario.desktop_contracts:
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
        if scenario.desktop_contracts:
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
        if scenario.desktop_contracts:
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
                "Installed desktop checks failed:\n- "
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
