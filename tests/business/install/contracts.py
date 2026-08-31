"""Installed release, region, login, desktop, and font contracts."""

from .context import *  # noqa: F403


class InstallationContracts:
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

    def _live_grub_entry(self, scenario: Scenario):
        region = scenario_live_region(self.defaults, scenario)
        entry = self.inspection.live_entry(region.grub_entry)
        if entry.locale != region.locale:
            raise TestFailure(
                f"GRUB entry locale is {entry.locale}, expected {region.locale}"
            )
        if entry.timezone != region.timezone:
            raise TestFailure(
                "GRUB entry timezone is "
                f"{entry.timezone}, expected {region.timezone}"
            )
        if entry.keyboard != region.keyboard:
            raise TestFailure(
                "GRUB entry keyboard is "
                f"{entry.keyboard}, expected {region.keyboard}"
            )
        return entry

    def _assert_grub_regional_contract(
        self,
        scenario: Scenario,
        artifacts: Path,
    ):
        """Retain the exact 28-entry ISO contract before QEMU can boot it."""

        region = scenario_live_region(self.defaults, scenario)
        entry = self._live_grub_entry(scenario)
        values = [
            {
                "name": candidate.name,
                "locale": candidate.locale,
                "timezone": candidate.timezone,
                "keyboard": candidate.keyboard,
                "kernel_arguments": list(candidate.kernel_arguments),
            }
            for candidate in self.inspection.live_entries
        ]
        if len(values) != 28 or len({value["name"] for value in values}) != 28:
            raise TestFailure("ISO GRUB regional contract is not 28 unique entries")
        selected = [
            value for value in values if value["name"] == region.grub_entry
        ]
        if len(selected) != 1:
            raise TestFailure("Selected GRUB regional entry is not unique")
        report = {
            "entry_count": len(values),
            "selected_entry": selected[0],
            "expected_locale": region.locale,
            "expected_timezone": region.timezone,
            "expected_keyboard": region.keyboard,
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
        self.driver.upload(vm.serial, remote_root)
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
        # The guest waits up to 120 seconds for DING to re-register after a
        # repaired accessibility bus.  Keep the outer serial deadline larger
        # so slow ARM TCG cannot terminate a valid in-guest readiness wait.
        result = vm.serial.run(command, timeout=180, check=False)
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
        self.driver.upload(vm.serial, remote_root)
        fixture = Path(__file__).parents[2] / "fixtures/font_fixture.py"
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
