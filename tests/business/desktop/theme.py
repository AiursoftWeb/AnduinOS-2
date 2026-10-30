"""GTK, Qt, Firefox, and shell theme synchronization behavior."""

from .context import *  # noqa: F403


class ThemeChecks:
    def _exercise_unlock_theme(
        self, vm: QemuVm, base: PromotedBase, artifacts: Path,
    ) -> None:
        """Observe default enablement and real Fluent ownership across locking."""
        from assertions.notifications import PROMPT_PROBE, _wait_shell_prompt

        assert vm.serial is not None and vm.qmp is not None
        console, qmp = vm.serial, vm.qmp
        remote = "/tmp/anduinos-unlock-theme"
        report_path, stop_path = remote + ".json", remote + ".stop"

        def desktop(command):
            return console.run(_desktop_command(self.username, ("bash", "-c", command)))

        def observe(predicate, label, timeout=30):
            deadline = time.monotonic() + timeout
            last = None
            while time.monotonic() < deadline:
                result = console.run(f"cat {report_path}", check=False)
                try:
                    report = json.loads(result.stdout.strip())
                except (TypeError, ValueError):
                    report = None
                if isinstance(report, dict):
                    (artifacts / "unlock-theme.json").write_text(
                        json.dumps(report, indent=2) + "\n", encoding="utf-8")
                    if report.get("error"):
                        raise TestFailure(f"Unlock theme observer failed: {report['error']}")
                    last = report.get("current")
                    if isinstance(last, dict) and predicate(last):
                        return last
                with console.capture_output():
                    time.sleep(0.2)
            raise TestFailure(f"Unlock theme did not reach {label}: {last}")

        def matches(snapshot, locked, name, pid):
            try:
                _validate_unlock_theme(snapshot, locked=locked, theme=name, pid=pid)
                return True
            except TestFailure:
                return False

        try:
            console.run(f"test ! -e {report_path}; test ! -e {stop_path}")
            console.upload(self.framework_root / "fixtures/unlock_theme.mjs", remote + ".mjs", 0o644)
            console.upload(self.framework_root / "fixtures/shell_prompt.py", PROMPT_PROBE, 0o644)
            for _ in range(3):
                qmp.send_key("esc")
                qmp.send_key("alt-f2", hold_ms=150)
                if _wait_shell_prompt(console, artifacts, "run-dialog", timeout=5,
                                      check=False, user=self.username,
                                      evidence_name="unlock-theme-ui.jsonl"):
                    break
            else:
                raise TestFailure("Unlock theme Run dialog never became ready")
            def prompt(kind, text=""):
                _wait_shell_prompt(console, artifacts, kind, text, user=self.username,
                                   evidence_name="unlock-theme-ui.jsonl")
            qmp.type_text("lg", interval=0.15)
            prompt("run-dialog", "lg")
            qmp.send_key("ret")
            prompt("looking-glass")
            expression = f'import("file://{remote}.mjs")'
            qmp.type_text(expression, interval=0.05)
            prompt("looking-glass", expression)
            qmp.send_key("ret")
            initial = observe(lambda state: state.get("locked") is False, "default desktop")
            name, pid = initial.get("selected"), initial.get("pid")
            if not isinstance(name, str) or re.fullmatch(r"Fluent(?:-[A-Za-z0-9]+)*", name) is None:
                raise TestFailure(f"Default account has no Fluent Shell theme: {name}")
            # Never enable the extension here: an omitted default must fail.
            _validate_unlock_theme(initial, locked=False, theme=name, pid=pid)
            for schema, key, value in (
                ("org.gnome.desktop.lockdown", "disable-lock-screen", "false"),
                ("org.gnome.desktop.screensaver", "lock-enabled", "true"),
            ):
                desktop(f"gsettings set {schema} {key} {value}")
            for variant in ("dark", "light"):
                self._select_desktop_theme(vm, artifacts, variant, f"unlock-{variant}")
                selected = desktop("gsettings get org.gnome.shell.extensions.user-theme name").stdout.strip().strip("'")
                observe(lambda state: matches(state, False, selected, pid), f"{variant} desktop")
                desktop("gdbus call --session --dest org.gnome.ScreenSaver "
                        "--object-path /org/gnome/ScreenSaver --method org.gnome.ScreenSaver.Lock")
                observe(lambda state: matches(state, True, selected, pid), f"{variant} Fluent lock")
                qmp.send_key("shift", hold_ms=50)
                qmp.send_key("ret")
                observe(lambda state: state.get("locked") is True and
                        state.get("passwordFocused") is True, "password input")
                vm.screenshot(f"unlock-theme-{variant}-locked")
                # Physical input goes only to the observed password entry; the
                # observer never reads or records its contents.
                qmp.type_text(self.password, interval=0.08)
                qmp.send_key("ret")
                observe(lambda state: matches(state, False, selected, pid), f"{variant} desktop restored")
                vm.screenshot(f"unlock-theme-{variant}-restored")
        except BaseException:
            try:
                vm.screenshot("unlock-theme-failure")
            except Exception:
                pass
            raise
        finally:
            # The suite owns a disposable overlay. Preserve evidence before
            # stopping its observer; do not unlock or fix a failing product.
            try:
                console.run(f"touch {stop_path}", check=False)
                result = console.run(f"cat {report_path}", check=False)
                (artifacts / "unlock-theme-final.txt").write_text(result.stdout, encoding="utf-8")
            except Exception as error:
                (artifacts / "unlock-theme-cleanup.txt").write_text(str(error), encoding="utf-8")

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
            # Capture the failed menu before subsequent independent checks
            # change the desktop, without replacing the original failure.
            try:
                vm.screenshot(f"theme-{label}-failure")
                assert vm.serial is not None
                vm.serial.download(
                    f"{remote}/evidence/last-accessibility-tree.txt",
                    artifacts / f"theme-{label}-failure-tree.txt",
                    missing_ok=True,
                )
            except Exception as error:
                (artifacts / f"theme-{label}-diagnostics-error.txt").write_text(
                    f"{type(error).__name__}: {error}\n", encoding="utf-8"
                )
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
