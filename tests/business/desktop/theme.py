"""GTK, Qt, Firefox, and shell theme synchronization behavior."""

from .context import *  # noqa: F403


class ThemeChecks:
    def _exercise_gtk_theme(
        self,
        vm: QemuVm,
        base: PromotedBase,
        artifacts: Path,
    ) -> None:
        """Prove one live GTK process visibly repaints from dark to light."""

        assert vm.serial is not None
        remote = self._prepare_theme_fixture(vm)
        unit = "anduinos-gtk-theme-fixture.service"
        self._select_desktop_theme(vm, artifacts, "dark", "gtk-dark-baseline")
        cursors = self._journal_cursors(vm)
        launch = _desktop_command(
            self.username,
            (
                "bash",
                "-lc",
                "systemd-run --user --unit=anduinos-gtk-theme-fixture "
                "--collect --property=Type=exec "
                "--setenv=HOME=\"$HOME\" "
                "--setenv=XDG_RUNTIME_DIR=\"$XDG_RUNTIME_DIR\" "
                "--setenv=DBUS_SESSION_BUS_ADDRESS=\"$DBUS_SESSION_BUS_ADDRESS\" "
                "--setenv=WAYLAND_DISPLAY=\"$WAYLAND_DISPLAY\" "
                "--setenv=DISPLAY=\"$DISPLAY\" --setenv=NO_AT_BRIDGE=0 "
                f"python3 {remote}/theme_fixture.py",
            ),
        )
        vm.serial.run(launch, timeout=60)
        self._assert_theme_marker(
            vm,
            artifacts,
            "GTK SCHEME prefer-dark",
            "gtk-dark",
        )
        before_pid = self._theme_fixture_pid(vm, unit)
        dark = vm.screenshot("theme-gtk-dark")
        self._select_desktop_theme(vm, artifacts, "light", "gtk-light")
        self._assert_theme_marker(
            vm,
            artifacts,
            "GTK SCHEME default",
            "gtk-light",
        )
        after_pid = self._theme_fixture_pid(vm, unit)
        _validate_same_fixture_process(before_pid, after_pid, "GTK")
        light = vm.screenshot("theme-gtk-light")
        assert_theme_transition(light, dark, artifacts / "theme-gtk-visual.json")
        (artifacts / "theme-gtk-process.txt").write_text(
            f"dark-pid={before_pid}\nlight-pid={after_pid}\n",
            encoding="utf-8",
        )
        self._assert_scoped_journal(
            vm, base, cursors, artifacts, scope="theme-gtk"
        )
        self._stop_user_unit(vm, unit)

    def _exercise_qt_theme(
        self,
        vm: QemuVm,
        base: PromotedBase,
        artifacts: Path,
    ) -> None:
        """Run a deterministic Qt 6 app and prove its live palette follows Shell."""

        assert vm.serial is not None and vm.qmp is not None
        remote = self._prepare_theme_fixture(vm)
        self.phase_callback(
            base.scenario.id,
            "desktop-theme",
            "Installing the deterministic Qt 6 fixture application",
        )
        installed = vm.serial.run(
            "set -e; export DEBIAN_FRONTEND=noninteractive; "
            "apt-get update; apt-get install -y python3-pyqt6 "
            "qt6-gtk-platformtheme qt6-qpa-plugins qt6-wayland; "
            "dpkg-query -W -f='${binary:Package} ${db:Status-Abbrev} ${Version}\\n' "
            "python3-pyqt6 qt6-gtk-platformtheme qt6-qpa-plugins qt6-wayland",
            timeout=600,
        )
        (artifacts / "theme-qt-package.txt").write_text(
            installed.stdout + "\n", encoding="utf-8"
        )
        self._select_desktop_theme(vm, artifacts, "dark", "qt-dark-baseline")
        cursors = self._journal_cursors(vm)
        unit = "anduinos-qt-theme-fixture.service"
        launch = _desktop_command(
            self.username,
            (
                "bash",
                "-lc",
                "systemd-run --user --unit=anduinos-qt-theme-fixture "
                "--collect --property=Type=exec "
                "--setenv=HOME=\"$HOME\" "
                "--setenv=XDG_RUNTIME_DIR=\"$XDG_RUNTIME_DIR\" "
                "--setenv=DBUS_SESSION_BUS_ADDRESS=\"$DBUS_SESSION_BUS_ADDRESS\" "
                "--setenv=WAYLAND_DISPLAY=\"$WAYLAND_DISPLAY\" "
                "--setenv=DISPLAY=\"$DISPLAY\" --setenv=NO_AT_BRIDGE=0 "
                "--setenv=QT_LINUX_ACCESSIBILITY_ALWAYS_ON=1 "
                f"python3 {remote}/qt_theme_fixture.py",
            ),
        )
        vm.serial.run(launch, timeout=60)
        self._assert_theme_marker(
            vm,
            artifacts,
            "QT PALETTE DARK",
            "qt-dark",
        )
        vm.qmp.send_key("meta_l-up")
        time.sleep(1)
        before_pid = self._theme_fixture_pid(vm, unit)
        dark = vm.screenshot("theme-qt-dark")
        self._select_desktop_theme(vm, artifacts, "light", "qt-light")
        self._assert_theme_marker(
            vm,
            artifacts,
            "QT PALETTE LIGHT",
            "qt-light",
        )
        after_pid = self._theme_fixture_pid(vm, unit)
        _validate_same_fixture_process(before_pid, after_pid, "Qt")
        light = vm.screenshot("theme-qt-light")
        assert_theme_transition(light, dark, artifacts / "theme-qt-visual.json")
        (artifacts / "theme-qt-process.txt").write_text(
            f"dark-pid={before_pid}\nlight-pid={after_pid}\n",
            encoding="utf-8",
        )
        self._assert_scoped_journal(
            vm, base, cursors, artifacts, scope="theme-qt"
        )
        self._stop_user_unit(vm, unit)

    def _exercise_firefox_theme(
        self,
        vm: QemuVm,
        base: PromotedBase,
        artifacts: Path,
    ) -> None:
        """Prove Firefox receives prefers-color-scheme without restarting."""

        assert vm.serial is not None and vm.qmp is not None
        remote = self._prepare_theme_fixture(vm)
        profile = f"{remote}/firefox-profile"
        vm.serial.run(
            f"install -d -m 0700 -o {shlex.quote(self.username)} "
            f"-g {shlex.quote(self.username)} {profile}; "
            f"printf '%s\\n' "
            "'user_pref(\"browser.shell.checkDefaultBrowser\", false);' "
            "'user_pref(\"browser.aboutwelcome.enabled\", false);' "
            "'user_pref(\"browser.preonboarding.enabled\", false);' "
            "'user_pref(\"trailhead.firstrun.didSeeAboutWelcome\", true);' "
            "'user_pref(\"browser.startup.homepage_override.mstone\", \"ignore\");' "
            "'user_pref(\"datareporting.policy.dataSubmissionEnabled\", false);' "
            "'user_pref(\"termsofuse.bypassNotification\", true);' "
            "'user_pref(\"termsofuse.acceptedVersion\", 999);' "
            "'user_pref(\"accessibility.force_disabled\", -1);' "
            f"> {profile}/user.js; "
            f"chown {shlex.quote(self.username)}:{shlex.quote(self.username)} "
            f"{profile}/user.js"
        )
        self._select_desktop_theme(vm, artifacts, "dark", "firefox-dark-baseline")
        cursors = self._journal_cursors(vm)
        unit = "anduinos-firefox-theme-fixture.service"
        launch = _desktop_command(
            self.username,
            (
                "bash",
                "-lc",
                "systemd-run --user --unit=anduinos-firefox-theme-fixture "
                "--collect --property=Type=exec "
                "--setenv=HOME=\"$HOME\" "
                "--setenv=XDG_RUNTIME_DIR=\"$XDG_RUNTIME_DIR\" "
                "--setenv=DBUS_SESSION_BUS_ADDRESS=\"$DBUS_SESSION_BUS_ADDRESS\" "
                "--setenv=WAYLAND_DISPLAY=\"$WAYLAND_DISPLAY\" "
                "--setenv=DISPLAY=\"$DISPLAY\" --setenv=NO_AT_BRIDGE=0 "
                f"firefox --no-remote --profile {profile} "
                f"file://{remote}/theme_fixture.html",
            ),
        )
        vm.serial.run(launch, timeout=60)
        self._assert_theme_marker(vm, artifacts, "FIREFOX DARK", "firefox-dark")
        vm.qmp.send_key("meta_l-up")
        time.sleep(1)
        before_pid = self._theme_fixture_pid(vm, unit)
        dark = vm.screenshot("theme-firefox-dark")
        self._select_desktop_theme(vm, artifacts, "light", "firefox-light")
        self._assert_theme_marker(vm, artifacts, "FIREFOX LIGHT", "firefox-light")
        after_pid = self._theme_fixture_pid(vm, unit)
        _validate_same_fixture_process(before_pid, after_pid, "Firefox")
        light = vm.screenshot("theme-firefox-light")
        assert_theme_transition(light, dark, artifacts / "theme-firefox-visual.json")
        (artifacts / "theme-firefox-process.txt").write_text(
            f"dark-pid={before_pid}\nlight-pid={after_pid}\n",
            encoding="utf-8",
        )
        self._assert_scoped_journal(
            vm, base, cursors, artifacts, scope="theme-firefox"
        )
        self._stop_user_unit(vm, unit)

    def _prepare_theme_fixture(self, vm: QemuVm) -> str:
        assert vm.serial is not None
        remote = "/run/anduinos-feature-theme"
        vm.serial.run(f"install -d -m 0777 {remote}/evidence")
        self.driver.upload(vm.serial, remote)
        vm.serial.upload(self.theme_fixture, f"{remote}/theme_fixture.py", 0o755)
        vm.serial.upload(
            self.qt_theme_fixture,
            f"{remote}/qt_theme_fixture.py",
            0o755,
        )
        vm.serial.upload(
            self.theme_web_fixture,
            f"{remote}/theme_fixture.html",
            0o644,
        )
        return remote

    def _select_desktop_theme(
        self,
        vm: QemuVm,
        artifacts: Path,
        expected: str,
        label: str,
    ) -> None:
        remote = self._prepare_theme_fixture(vm)
        command = _desktop_command(
            self.username,
            (
                "python3",
                f"{remote}/atspi_driver.py",
                "theme-set",
                "--expected",
                expected,
                "--evidence",
                f"{remote}/evidence",
            ),
        )
        result = _run_with_qmp_key_requests(vm, command, timeout=180)
        (artifacts / f"theme-{label}-events.jsonl").write_text(
            result.stdout + "\n", encoding="utf-8"
        )
        if result.returncode != 0:
            raise TestFailure(
                f"GNOME Shell could not select the {expected} theme:\n"
                + result.stdout[-8000:]
            )
        _validate_theme_selection(result.stdout, expected)

    def _assert_theme_marker(
        self,
        vm: QemuVm,
        artifacts: Path,
        expected: str,
        label: str,
    ) -> None:
        assert vm.serial is not None
        remote = "/run/anduinos-feature-theme"
        command = _desktop_command(
            self.username,
            (
                "python3",
                f"{remote}/atspi_driver.py",
                "theme-assert-marker",
                "--expected",
                expected,
                "--evidence",
                f"{remote}/evidence",
            ),
        )
        result = vm.serial.run(command, timeout=120, check=False)
        (artifacts / f"theme-{label}-marker.jsonl").write_text(
            result.stdout + "\n", encoding="utf-8"
        )
        if result.returncode != 0:
            raise TestFailure(
                f"Theme fixture did not expose marker {expected!r}:\n"
                + result.stdout[-8000:]
            )
        _validate_theme_marker(result.stdout, expected)

    def _theme_fixture_pid(self, vm: QemuVm, unit: str) -> int:
        assert vm.serial is not None
        result = vm.serial.run(
            _desktop_command(
                self.username,
                ("systemctl", "--user", "show", unit, "-p", "MainPID", "--value"),
            ),
            timeout=30,
        )
        try:
            pid = int(result.stdout.strip().splitlines()[-1])
        except (IndexError, ValueError) as error:
            raise TestFailure(f"Could not read fixture PID for {unit}") from error
        if pid <= 1:
            raise TestFailure(f"Theme fixture unit is not running: {unit}")
        return pid

    def _stop_user_unit(self, vm: QemuVm, unit: str) -> None:
        assert vm.serial is not None
        vm.serial.run(
            _desktop_command(self.username, ("systemctl", "--user", "stop", unit)),
            timeout=30,
            check=False,
        )
