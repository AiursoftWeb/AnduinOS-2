"""GNOME Shell, taskbar, desktop, and deterministic fixture behavior."""

from .context import *  # noqa: F403


class ShellChecks:
    def _exercise_start_button_logo(
        self,
        vm: QemuVm,
        base: PromotedBase,
        artifacts: Path,
    ) -> None:
        """Prove Super opens ArcMenu and its rendered button is AnduinOS-branded."""

        event = self._run_shell_driver(
            vm,
            base,
            artifacts,
            mode="shell-start-button",
            validator=_validate_start_button_events,
        )
        assert vm.serial is not None
        asset = event["asset"]
        assert isinstance(asset, str)
        contract = vm.serial.run(
            _desktop_command(
                self.username,
                (
                    "bash",
                    "-lc",
                    "set -e; schema=org.gnome.shell.extensions.arcmenu; "
                    "schema_dir=/usr/share/gnome-shell/extensions/"
                    "arcmenu@arcmenu.com/schemas; "
                    "printf 'menu-button-icon=%s\\n' "
                    '"$(gsettings --schemadir "$schema_dir" get "$schema" '
                    'menu-button-icon)"; '
                    "printf 'menu-button-icon-size=%s\\n' "
                    '"$(gsettings --schemadir "$schema_dir" get "$schema" '
                    'menu-button-icon-size)"; '
                    f"sha256sum {shlex.quote(asset)}",
                ),
            ),
            timeout=30,
            check=False,
        )
        (artifacts / "start-button-contract.txt").write_text(
            contract.stdout + "\n", encoding="utf-8"
        )
        _validate_start_button_contract(contract.stdout, event)
        template = (
            artifacts
            / "guest-shell-evidence"
            / "shell-start-button"
            / "start-button-installed-logo.png"
        )
        if not template.is_file():
            raise TestFailure("The guest did not return its rendered Start logo template")
        frame = vm.screenshot("start-button-logo")
        bounds = event["bounds"]
        assert isinstance(bounds, list)
        assert_start_button_logo(
            frame,
            template,
            bounds,
            artifacts / "start-button-logo-analysis.json",
        )

    def _exercise_panel_pin(
        self,
        vm: QemuVm,
        base: PromotedBase,
        artifacts: Path,
    ) -> None:
        """Pin a fixture and prove the favorite survives a fresh Shell session."""

        assert vm.serial is not None
        before_session = self._graphical_session_id(vm, self.username)
        initial = self._run_shell_driver(
            vm,
            base,
            artifacts,
            mode="shell-panel-pin",
            validator=_validate_panel_pin_initial_events,
            text_inputs={
                "panel-pin-search-text": "AnduinOS Panel Acceptance Fixture"
            },
        )
        self.phase_callback(
            base.scenario.id,
            "shell-panel-taskbar",
            "Recreating GNOME Shell to verify the pinned launcher persists",
        )
        self._logout_graphical_user(vm, self.username)
        _login_gdm(vm, self.username, self.password, timeout=150)
        login = self._wait_for_graphical_identity(vm, self.username, timeout=150)
        _validate_graphical_login(login, self.username)
        after_session = self._graphical_session_id(vm, self.username)
        persisted = self._run_shell_driver(
            vm,
            base,
            artifacts,
            mode="shell-panel-pin-persisted",
            validator=_validate_panel_pin_persisted_events,
        )
        _validate_panel_pin_roundtrip(
            initial,
            persisted,
            before_session=before_session,
            after_session=after_session,
        )
        (artifacts / "panel-pin-session-roundtrip.txt").write_text(
            f"before-session={before_session}\nafter-session={after_session}\n",
            encoding="utf-8",
        )

    def _exercise_panel_remove(
        self,
        vm: QemuVm,
        base: PromotedBase,
        artifacts: Path,
    ) -> None:
        """Use the real localized taskbar menu to remove the pinned fixture."""

        self._run_shell_driver(
            vm,
            base,
            artifacts,
            mode="shell-panel-remove",
            validator=_validate_panel_remove_events,
        )

    def _exercise_appindicator_roundtrip(
        self,
        vm: QemuVm,
        base: PromotedBase,
        artifacts: Path,
    ) -> None:
        """Hide a real GTK window to SNI and restore it through GNOME Shell."""

        assert vm.serial is not None
        fixture = "/usr/local/lib/anduinos-acceptance-shell/indicator_fixture.py"
        launch = vm.serial.run(
            _desktop_command(
                self.username,
                (
                    "bash",
                    "-lc",
                    "systemctl --user stop anduinos-indicator-fixture.service "
                    ">/dev/null 2>&1 || true; "
                    "systemd-run --user --unit=anduinos-indicator-fixture "
                    "--collect --property=Type=exec "
                    "--setenv=HOME=\"$HOME\" "
                    "--setenv=XDG_RUNTIME_DIR=\"$XDG_RUNTIME_DIR\" "
                    "--setenv=DBUS_SESSION_BUS_ADDRESS=\"$DBUS_SESSION_BUS_ADDRESS\" "
                    "--setenv=WAYLAND_DISPLAY=\"$WAYLAND_DISPLAY\" "
                    "--setenv=DISPLAY=\"$DISPLAY\" --setenv=NO_AT_BRIDGE=0 "
                    "--setenv=GDK_DEBUG=no-portals "
                    f"python3 {fixture}",
                ),
            ),
            timeout=60,
            check=False,
        )
        (artifacts / "appindicator-launch.txt").write_text(
            launch.stdout + "\n", encoding="utf-8"
        )
        if launch.returncode != 0:
            raise TestFailure(
                "Could not launch the AppIndicator fixture:\n"
                + launch.stdout[-4000:]
            )
        active = vm.serial.run(
            _desktop_command(
                self.username,
                (
                    "systemctl",
                    "--user",
                    "is-active",
                    "anduinos-indicator-fixture.service",
                ),
            ),
            timeout=30,
            check=False,
        )
        if active.returncode != 0 or active.stdout.strip().splitlines()[-1:] != ["active"]:
            raise TestFailure(
                "The AppIndicator fixture exited before interaction:\n"
                + active.stdout[-4000:]
            )
        ready = vm.serial.run(
            _desktop_command(
                self.username,
                (
                    "bash",
                    "-lc",
                    "for attempt in $(seq 1 60); do "
                    "journalctl --user -u anduinos-indicator-fixture.service "
                    "--no-pager -o cat | grep -Fqx 'indicator-window=visible' "
                    "&& exit 0; "
                    "systemctl --user is-active --quiet "
                    "anduinos-indicator-fixture.service || break; "
                    "sleep 0.5; done; "
                    "journalctl --user -u anduinos-indicator-fixture.service "
                    "--no-pager -o cat; exit 1",
                ),
            ),
            timeout=45,
            check=False,
        )
        (artifacts / "appindicator-ready.txt").write_text(
            ready.stdout + "\n", encoding="utf-8"
        )
        if ready.returncode != 0:
            raise TestFailure(
                "The AppIndicator fixture did not create its baseline window:\n"
                + ready.stdout[-4000:]
            )
        self._run_shell_driver(
            vm,
            base,
            artifacts,
            mode="shell-appindicator-roundtrip",
            validator=_validate_appindicator_roundtrip_events,
        )

    def _exercise_desktop_shortcut(
        self,
        vm: QemuVm,
        base: PromotedBase,
        artifacts: Path,
    ) -> None:
        """Create, display, and launch a real DING desktop shortcut."""

        self._run_shell_driver(
            vm,
            base,
            artifacts,
            mode="shell-desktop-shortcut",
            validator=_validate_desktop_shortcut_events,
            text_inputs={
                "desktop-shortcut-search-text": (
                    "AnduinOS Panel Acceptance Fixture"
                ),
                # Match the desktop filename as well as its displayed label.
                # This ASCII token is unique even when the desktop locale is
                # translated.
                "desktop-shortcut-ding-search-text": "AcceptancePanelFixture",
            },
        )

    def _exercise_desktop_icons(
        self,
        vm: QemuVm,
        base: PromotedBase,
        artifacts: Path,
    ) -> None:
        """Prove the installed desktop exposes its localized default icons."""

        self._run_shell_driver(
            vm,
            base,
            artifacts,
            mode="shell-desktop-icons",
            validator=_validate_desktop_icon_events,
        )

    def _exercise_ptyxis_initial_size(
        self,
        vm: QemuVm,
        base: PromotedBase,
        artifacts: Path,
    ) -> None:
        """Reject an ignored or zero-sized Ptyxis default before launching it."""

        assert vm.serial is not None
        assert_release_contract(
            vm.serial,
            self.username,
            artifacts,
            "terminal.ptyxis-initial-size",
        )

    def _exercise_desktop_terminal(
        self,
        vm: QemuVm,
        base: PromotedBase,
        artifacts: Path,
    ) -> None:
        """Open and close the real terminal from DING's background menu."""

        self._run_shell_driver(
            vm,
            base,
            artifacts,
            mode="shell-desktop-terminal",
            validator=_validate_desktop_terminal_events,
        )

    def _exercise_spotify_store(
        self,
        vm: QemuVm,
        base: PromotedBase,
        artifacts: Path,
    ) -> None:
        """Open Spotify's cached Software details with the VM link down."""

        assert vm.qmp is not None and vm.serial is not None
        vm.qmp.set_link("nic0", up=False)
        network = vm.serial.run(
            "set -euo pipefail\n"
            "interfaces=()\n"
            "for path in /sys/class/net/*; do\n"
            "  iface=${path##*/}\n"
            "  test \"$iface\" = lo && continue\n"
            "  interfaces+=(\"$iface\")\n"
            "done\n"
            "test \"${#interfaces[@]}\" -eq 1\n"
            "iface=${interfaces[0]}\n"
            "for _ in $(seq 1 30); do\n"
            "  carrier=$(cat \"/sys/class/net/$iface/carrier\" 2>/dev/null || echo 0)\n"
            "  state=$(cat \"/sys/class/net/$iface/operstate\")\n"
            "  test \"$carrier\" = 0 && test \"$state\" != up && break\n"
            "  sleep 1\n"
            "done\n"
            "test \"$carrier\" = 0\n"
            "test \"$state\" != up\n"
            "printf 'qmp-link=nic0-down\\ninterface=%s\\ncarrier=%s\\noperstate=%s\\n' "
            "\"$iface\" \"$carrier\" \"$state\"",
            timeout=45,
        )
        (artifacts / "spotify-network-isolation.txt").write_text(
            network.stdout + "\n",
            encoding="utf-8",
        )

        self._run_shell_driver(
            vm,
            base,
            artifacts,
            mode="shell-spotify-store",
            validator=_validate_spotify_store_events,
            text_inputs={"spotify-search-text": "Spotify"},
        )
    def _graphical_session_id(self, vm: QemuVm, user: str) -> str:
        assert vm.serial is not None
        session = vm.serial.run(
            f"loginctl show-user {shlex.quote(user)} -p Display --value",
            timeout=30,
        ).stdout.strip()
        if not session or not re.fullmatch(r"[A-Za-z0-9_.-]+", session):
            raise TestFailure(f"Could not identify the graphical session for {user!r}")
        return session

    def _install_shell_fixture(
        self,
        vm: QemuVm,
        *,
        shortcut_fixture: bool,
        panel_fixture: bool,
        indicator_fixture: bool,
    ) -> None:
        """Install only the overlay-local identities needed before Shell starts."""

        assert vm.serial is not None
        fixture = "/usr/local/lib/anduinos-acceptance-shell"
        vm.serial.run(f"install -d -m 0755 {fixture}")
        self.driver.upload(vm.serial, fixture)
        contracts = [f"test -x {shlex.quote(fixture + '/atspi_driver.py')}"]
        if shortcut_fixture:
            vm.serial.upload(
                self.shell_fixture,
                f"{fixture}/shell_fixture.py",
                0o755,
            )
            desktop = (
                "/usr/share/applications/"
                "com.anduinos.AcceptanceShellFixture.desktop"
            )
            vm.serial.upload(self.shell_desktop_fixture, desktop, 0o644)
            contracts.extend(
                (
                    f"test -x {shlex.quote(fixture + '/shell_fixture.py')}",
                    f"test -s {shlex.quote(desktop)}",
                    f"grep -Fx 'Icon=utilities-terminal' {shlex.quote(desktop)}",
                )
            )
        if panel_fixture:
            vm.serial.upload(
                self.panel_fixture,
                f"{fixture}/panel_fixture.py",
                0o755,
            )
            panel_desktop = (
                "/usr/share/applications/"
                "com.anduinos.AcceptancePanelFixture.desktop"
            )
            vm.serial.upload(self.panel_desktop_fixture, panel_desktop, 0o644)
            contracts.extend(
                (
                    f"test -x {shlex.quote(fixture + '/panel_fixture.py')}",
                    f"test -s {shlex.quote(panel_desktop)}",
                    f"grep -Fx 'Icon=utilities-terminal' {shlex.quote(panel_desktop)}",
                )
            )
        if indicator_fixture:
            vm.serial.upload(
                self.indicator_fixture,
                f"{fixture}/indicator_fixture.py",
                0o755,
            )
            contracts.append(
                f"test -x {shlex.quote(fixture + '/indicator_fixture.py')}"
            )
        contract_script = "; ".join(contracts)
        contract = vm.serial.run(
            "set -e; "
            f"{contract_script}; "
            "if command -v update-desktop-database >/dev/null; then "
            "update-desktop-database /usr/share/applications; fi; "
            f"touch {shlex.quote(fixture + '/.prepared')}; "
            "printf 'shell-fixture-desktop=ready\\n'",
            timeout=60,
            check=False,
        )
        if contract.returncode != 0 or "shell-fixture-desktop=ready" not in contract.stdout:
            raise TestFailure(
                "The Shell fixture has no valid desktop application identity:\n"
                + contract.stdout[-4000:]
            )

    def _prepare_shell_fixture(self, vm: QemuVm, *, launch_windows: bool) -> str:
        """Verify the pre-session fixture and optionally launch both windows."""

        assert vm.serial is not None
        remote = "/run/anduinos-feature-shell"
        fixture = "/usr/local/lib/anduinos-acceptance-shell"
        shortcut_contract = ""
        if launch_windows:
            shortcut_contract = (
                f"test -x {shlex.quote(fixture + '/shell_fixture.py')}; "
                f"ln -sfn {shlex.quote(fixture + '/shell_fixture.py')} "
                f"{shlex.quote(remote + '/shell_fixture.py')}; "
            )
        prepared = vm.serial.run(
            "set -e; "
            f"test -f {shlex.quote(fixture + '/.prepared')}; "
            f"test -x {shlex.quote(fixture + '/atspi_driver.py')}; "
            f"install -d -m 0777 {shlex.quote(remote + '/evidence')}; "
            f"ln -sfn {shlex.quote(fixture + '/atspi_driver.py')} "
            f"{shlex.quote(remote + '/atspi_driver.py')}; "
            f"{shortcut_contract}"
            "printf 'shell-fixture=prepared\\n'",
            timeout=30,
            check=False,
        )
        if prepared.returncode != 0 or "shell-fixture=prepared" not in prepared.stdout:
            raise TestFailure(
                "The pre-session Shell fixture is unavailable:\n"
                + prepared.stdout[-4000:]
            )
        if not launch_windows:
            return remote
        unit = "anduinos-shell-fixture.service"
        launch = _desktop_command(
            self.username,
            (
                "bash",
                "-lc",
                "systemctl --user stop anduinos-shell-fixture.service "
                ">/dev/null 2>&1 || true; "
                "systemd-run --user --unit=anduinos-shell-fixture "
                "--collect --property=Type=exec "
                "--setenv=HOME=\"$HOME\" "
                "--setenv=XDG_RUNTIME_DIR=\"$XDG_RUNTIME_DIR\" "
                "--setenv=DBUS_SESSION_BUS_ADDRESS=\"$DBUS_SESSION_BUS_ADDRESS\" "
                "--setenv=WAYLAND_DISPLAY=\"$WAYLAND_DISPLAY\" "
                "--setenv=DISPLAY=\"$DISPLAY\" --setenv=NO_AT_BRIDGE=0 "
                f"python3 {remote}/shell_fixture.py",
            ),
        )
        result = vm.serial.run(launch, timeout=60, check=False)
        if result.returncode != 0:
            raise TestFailure(
                "Could not launch the two-window Shell fixture:\n"
                + result.stdout[-4000:]
            )
        status = vm.serial.run(
            _desktop_command(
                self.username,
                ("systemctl", "--user", "is-active", unit),
            ),
            timeout=30,
            check=False,
        )
        if status.returncode != 0 or status.stdout.strip().splitlines()[-1:] != ["active"]:
            raise TestFailure(
                "The two-window Shell fixture exited before shortcut testing:\n"
                + status.stdout[-4000:]
            )
        return remote

    def _run_shell_driver(
        self,
        vm: QemuVm,
        base: PromotedBase,
        artifacts: Path,
        *,
        mode: str,
        validator: Callable[[str], object],
        text_inputs: dict[str, str] | None = None,
        secret_texts: dict[str, str] | None = None,
        screenshot_validator: Callable[[Path, object], None] | None = None,
    ) -> object:
        """Run one semantic Shell probe with QMP input and scoped logs."""

        assert vm.serial is not None
        remote = self._prepare_shell_fixture(vm, launch_windows=False)
        if mode in _LOCAL_SEARCH_DRIVER_MODES:
            self._assert_local_search_provider_isolation(vm, artifacts, mode)
        elif mode in _SOFTWARE_SEARCH_DRIVER_MODES:
            preflight_cursors = self._journal_cursors(vm)
            self._stabilize_shell_search_provider(vm, artifacts)
            self._assert_scoped_journal(
                vm,
                base,
                preflight_cursors,
                artifacts,
                scope="shell-search-provider-preflight",
            )
        cursors = self._journal_cursors(vm)
        command = _desktop_command(
            self.username,
            (
                "python3",
                f"{remote}/atspi_driver.py",
                mode,
                "--evidence",
                f"{remote}/evidence/{mode}",
            ),
        )
        result = _run_with_qmp_key_requests(
            vm,
            command,
            timeout=240,
            text_inputs=text_inputs,
            secret_texts=secret_texts,
            request_trace=artifacts / f"{mode}-qmp-requests.jsonl",
        )
        (artifacts / f"{mode}-events.jsonl").write_text(
            result.stdout + "\n", encoding="utf-8"
        )
        _retrieve_tree(vm.serial, remote, artifacts / "guest-shell-evidence")
        if result.returncode != 0:
            raise TestFailure(
                f"GNOME Shell probe {mode!r} failed:\n" + result.stdout[-8000:]
            )
        validated = validator(result.stdout)
        frame = vm.screenshot(mode)
        if screenshot_validator is not None:
            screenshot_validator(frame, validated)
        self._assert_scoped_journal(
            vm,
            base,
            cursors,
            artifacts,
            scope=mode,
        )
        if mode in _LOCAL_SEARCH_DRIVER_MODES:
            self._assert_local_search_provider_remained_isolated(
                vm,
                artifacts,
                mode,
            )
        return validated

    def _configure_local_search_provider_isolation(
        self,
        vm: QemuVm,
        artifacts: Path,
    ) -> None:
        """Disable Software search before login in one disposable overlay.

        ArcMenu's local application tests and GNOME Software's remote search
        tests have different owners and different failure contracts. Writing
        this setting before login prevents Shell from D-Bus-activating the
        Software provider while it constructs the local-search model. The
        overlay is discarded after the suite, so no installed user policy is
        changed and the dedicated store suites still exercise the real
        provider with fatal journal checking enabled.
        """

        assert vm.serial is not None
        user = shlex.quote(self.username)
        provider = shlex.quote(_SOFTWARE_SEARCH_PROVIDER_ID)
        script = f"""
set -euo pipefail
user={user}
provider={provider}
home=$(getent passwd "$user" | cut -d: -f6)
test -n "$home"
provider_file=/usr/share/gnome-shell/search-providers/org.gnome.Software-search-provider.ini
test -r "$provider_file"
declared=$(sed -n 's/^DesktopId=//p' "$provider_file")
test "$declared" = "$provider"
runuser -u "$user" -- env HOME="$home" dbus-run-session -- \
    python3 - "$provider" <<'PY'
import sys

from gi.repository import Gio

provider = sys.argv[1]
settings = Gio.Settings.new("org.gnome.desktop.search-providers")
disabled = list(settings.get_strv("disabled"))
if provider not in disabled:
    disabled.append(provider)
    if not settings.set_strv("disabled", disabled):
        raise SystemExit("could not update the disabled search-provider list")
Gio.Settings.sync()
print(f"provider={{provider}}")
print(f"configured={{settings.get_value('disabled').print_(True)}}")
PY
""".strip()
        result = vm.serial.run(script, timeout=60, check=False)
        (artifacts / "local-search-provider-isolation-before-login.txt").write_text(
            result.stdout + "\n", encoding="utf-8"
        )
        _validate_local_search_provider_isolation_configuration(
            result.stdout,
            result.returncode,
        )

    def _assert_local_search_provider_isolation(
        self,
        vm: QemuVm,
        artifacts: Path,
        scope: str,
    ) -> None:
        """Temporarily mask Software in a disposable local-search session."""

        assert vm.serial is not None
        script = """
set -euo pipefail
unit=gnome-software.service
provider=org.gnome.Software.desktop
configured=$(gsettings get org.gnome.desktop.search-providers disabled)
before_state=$(systemctl --user is-active "$unit" 2>/dev/null || true)
before_restarts=$(systemctl --user show "$unit" -p NRestarts --value 2>/dev/null || printf 0)
systemctl --user mask --runtime --now "$unit"
after_load=$(systemctl --user show "$unit" -p LoadState --value)
after_state=$(systemctl --user is-active "$unit" 2>/dev/null || true)
after_pid=$(systemctl --user show "$unit" -p MainPID --value 2>/dev/null || printf 0)
printf 'provider=%s\nconfigured=%s\n' "$provider" "$configured"
printf 'before_state=%s before_restarts=%s\n' \
    "$before_state" "$before_restarts"
printf 'after_load=%s after_state=%s after_pid=%s\n' \
    "$after_load" "$after_state" "$after_pid"
""".strip()
        result = vm.serial.run(
            _desktop_command(self.username, ("bash", "-lc", script)),
            timeout=60,
            check=False,
        )
        (artifacts / f"{scope}-software-search-isolation.txt").write_text(
            result.stdout + "\n", encoding="utf-8"
        )
        _validate_local_search_provider_runtime_isolation(
            result.stdout,
            result.returncode,
        )

    def _assert_local_search_provider_remained_isolated(
        self,
        vm: QemuVm,
        artifacts: Path,
        scope: str,
    ) -> None:
        """Prove the local ArcMenu action did not activate Software."""

        assert vm.serial is not None
        script = """
set -euo pipefail
unit=gnome-software.service
provider=org.gnome.Software.desktop
configured=$(gsettings get org.gnome.desktop.search-providers disabled)
load=$(systemctl --user show "$unit" -p LoadState --value)
state=$(systemctl --user is-active "$unit" 2>/dev/null || true)
pid=$(systemctl --user show "$unit" -p MainPID --value 2>/dev/null || printf 0)
printf 'provider=%s\nconfigured=%s\n' "$provider" "$configured"
printf 'load=%s state=%s pid=%s\n' "$load" "$state" "$pid"
""".strip()
        result = vm.serial.run(
            _desktop_command(self.username, ("bash", "-lc", script)),
            timeout=30,
            check=False,
        )
        (artifacts / f"{scope}-software-search-isolation-after.txt").write_text(
            result.stdout + "\n", encoding="utf-8"
        )
        _validate_local_search_provider_post_action_isolation(
            result.stdout,
            result.returncode,
        )

    def _stabilize_shell_search_provider(
        self,
        vm: QemuVm,
        artifacts: Path,
    ) -> None:
        """Prove the Software search provider is healthy before action cursors.

        GNOME starts its Software search provider as part of the desktop
        session, while feature probes begin as soon as AT-SPI is ready.  A
        provider process which was born before the action cursor can still
        finish initialization after that cursor, which would falsely attribute
        a login-time fault to the panel gesture.  Warm the real SearchProvider2
        endpoint once and require an unchanged live process with a zero restart
        counter for 15 seconds before opening the action cursor.

        A retry is deliberately forbidden.  A SIGSEGV followed by systemd's
        automatic restart is a product failure, not a successful warm-up.  The
        transcript also records the exact GNOME Software and PackageKit binary
        versions so a crash can be tied to the shipped implementation.
        """

        assert vm.serial is not None
        script = """
set -uo pipefail
unit=gnome-software.service
for package in gnome-software gnome-software-plugin-deb packagekit libpackagekit-glib2-18; do
    version=$(dpkg-query -W -f='${Version}' "$package" 2>/dev/null || true)
    printf 'package=%s version=%s\n' "$package" "${version:-missing}"
done
before_pid=$(systemctl --user show "$unit" -p MainPID --value 2>/dev/null || printf 0)
before_restarts=$(systemctl --user show "$unit" -p NRestarts --value 2>/dev/null || printf 0)
before_active=$(systemctl --user is-active "$unit" 2>/dev/null || true)
printf 'before_pid=%s before_restarts=%s before_active=%s\n' \
    "$before_pid" "$before_restarts" "$before_active"
if test "$before_restarts" != 0; then
    printf '%s\n' 'search-provider=crashed-before-preflight'
    exit 1
fi
if ! timeout 60 gdbus call --session \
    --dest org.gnome.Software \
    --object-path /org/gnome/Software/SearchProvider \
    --method org.gnome.Shell.SearchProvider2.GetInitialResultSet \
    "['anduinos-acceptance-preflight']"; then
    printf '%s\n' 'search-provider=query-failed'
    exit 1
fi
sleep 15
after_pid=$(systemctl --user show "$unit" -p MainPID --value 2>/dev/null || printf 0)
after_restarts=$(systemctl --user show "$unit" -p NRestarts --value 2>/dev/null || printf 0)
after_active=$(systemctl --user is-active "$unit" 2>/dev/null || true)
printf 'after_pid=%s after_restarts=%s after_active=%s\n' \
    "$after_pid" "$after_restarts" "$after_active"
if test "$after_active" = active \
    && test "$after_pid" != 0 \
    && test "$after_restarts" = 0 \
    && { test "$before_pid" = 0 || test "$before_pid" = "$after_pid"; }; then
    printf 'search-provider=ready pid=%s restarts=%s\n' \
        "$after_pid" "$after_restarts"
    exit 0
fi
printf '%s\n' 'search-provider=unstable'
exit 1
""".strip()
        result = vm.serial.run(
            _desktop_command(self.username, ("bash", "-lc", script)),
            timeout=240,
            check=False,
        )
        (artifacts / "shell-search-provider-preflight.txt").write_text(
            result.stdout + "\n",
            encoding="utf-8",
        )
        _validate_search_provider_preflight(result.stdout, result.returncode)
