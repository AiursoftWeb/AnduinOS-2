"""Account creation, GDM, password, branding, and greeter behavior."""

from .context import *  # noqa: F403
from framework.spice_input import SpiceCursorObserver


class AccountChecks:
    def _exercise_account_add_user(
        self,
        vm: QemuVm,
        base: PromotedBase,
        artifacts: Path,
    ) -> None:
        """Create a standard user through the real GNOME Settings dialog."""

        assert vm.serial is not None
        remote = self._prepare_account_fixture(vm)
        command = _desktop_command(
            self.username,
            (
                "python3",
                f"{remote}/atspi_driver.py",
                "accounts-create",
                "--account",
                self.secondary_username,
                "--full-name",
                self.secondary_full_name,
                "--evidence",
                f"{remote}/evidence/account-create",
            ),
        )
        self.phase_callback(base.scenario.id, "accounts-gdm", "Creating user in GNOME Settings")
        result = _run_with_qmp_key_requests(
            vm,
            command,
            timeout=300,
            secret_texts={
                "accounts-polkit-password": self.password,
                "accounts-initial-password": self.secondary_initial_password,
                "accounts-initial-confirmation": self.secondary_initial_password,
            },
        )
        (artifacts / "account-create-events.jsonl").write_text(
            result.stdout + "\n", encoding="utf-8"
        )
        _retrieve_tree(vm.serial, remote, artifacts / "guest-account-evidence")
        if result.returncode != 0:
            raise TestFailure(
                "GNOME Settings could not create the secondary account:\n"
                + result.stdout[-8000:]
            )
        _validate_account_creation_events(result.stdout)
        record = vm.serial.run(
            "set -euo pipefail\n"
            f"user={shlex.quote(self.secondary_username)}\n"
            "getent passwd \"$user\" >/dev/null\n"
            "printf 'account=%s\\n' \"$user\"\n"
            "printf 'passwd=present\\n'\n"
            "groups=$(id -nG \"$user\")\n"
            "printf 'groups=%s\\n' \"$groups\"\n"
            "if printf '%s\\n' \"$groups\" | tr ' ' '\\n' | grep -Fxq sudo; then "
            "printf 'standard-user=no\\n'; else printf 'standard-user=yes\\n'; fi\n"
            "passwd -S \"$user\" | awk '$2 == \"P\" {print \"password=usable\"}'\n",
            timeout=60,
        ).stdout
        _validate_account_record(record, self.secondary_username)
        (artifacts / "account-created.txt").write_text(record + "\n", encoding="utf-8")
        fingerprint = self._password_fingerprint(vm, self.secondary_username)
        (artifacts / "account-initial-password-fingerprint.txt").write_text(
            fingerprint + "\n", encoding="utf-8"
        )
        vm.screenshot("account-created-in-settings")

    def _exercise_account_new_user_login(
        self,
        vm: QemuVm,
        base: PromotedBase,
        artifacts: Path,
    ) -> None:
        assert vm.serial is not None
        self.phase_callback(base.scenario.id, "accounts-gdm", "Logging out and selecting the new GDM user")
        self._logout_graphical_user(vm, self.username)
        vm.screenshot("account-first-gdm")
        self._select_gdm_account(
            vm,
            artifacts,
            self.secondary_username,
            self.secondary_full_name,
            self.secondary_initial_password,
            "initial",
        )
        evidence = self._wait_for_graphical_identity(
            vm,
            self.secondary_username,
            timeout=150,
        )
        _validate_graphical_login(evidence, self.secondary_username)
        (artifacts / "account-initial-login.txt").write_text(
            evidence + "\n", encoding="utf-8"
        )
        vm.screenshot("account-secondary-first-session")

    def _exercise_account_change_password(
        self,
        vm: QemuVm,
        base: PromotedBase,
        artifacts: Path,
    ) -> None:
        assert vm.serial is not None
        remote = "/run/anduinos-feature-accounts"
        before = (artifacts / "account-initial-password-fingerprint.txt").read_text(
            encoding="utf-8"
        ).strip()
        command = _desktop_command(
            self.secondary_username,
            (
                "python3",
                f"{remote}/atspi_driver.py",
                "accounts-change-password",
                "--evidence",
                f"{remote}/evidence/account-change-password",
            ),
        )
        self.phase_callback(base.scenario.id, "accounts-gdm", "Changing the new user's password in Settings")
        result = _run_with_qmp_key_requests(
            vm,
            command,
            timeout=300,
            secret_texts={
                **{
                    f"accounts-current-password-attempt-{attempt}": (
                        self.secondary_initial_password
                    )
                    for attempt in range(12)
                },
                "accounts-new-password": self.secondary_new_password,
                "accounts-new-confirmation": self.secondary_new_password,
            },
        )
        (artifacts / "account-password-events.jsonl").write_text(
            result.stdout + "\n", encoding="utf-8"
        )
        _retrieve_tree(vm.serial, remote, artifacts / "guest-account-evidence")
        if result.returncode != 0:
            raise TestFailure(
                "The secondary user could not change its password through Settings:\n"
                + result.stdout[-8000:]
            )
        _validate_password_change_events(result.stdout)
        after = self._password_fingerprint(vm, self.secondary_username)
        _validate_password_fingerprint_change(before, after)
        (artifacts / "account-password-fingerprints.txt").write_text(
            f"before={before}\nafter={after}\n", encoding="utf-8"
        )

        # A changed shadow hash is supporting evidence.  A second real GDM
        # login with the replacement password is the behavioral oracle.
        self._logout_graphical_user(vm, self.secondary_username)
        self._select_gdm_account(
            vm,
            artifacts,
            self.secondary_username,
            self.secondary_full_name,
            self.secondary_new_password,
            "changed-password",
        )
        login = self._wait_for_graphical_identity(
            vm,
            self.secondary_username,
            timeout=150,
        )
        _validate_graphical_login(login, self.secondary_username)
        (artifacts / "account-new-password-login.txt").write_text(
            login + "\n", encoding="utf-8"
        )

    def _exercise_account_logout_gdm(
        self,
        vm: QemuVm,
        base: PromotedBase,
        artifacts: Path,
    ) -> None:
        assert vm.serial is not None
        self.phase_callback(base.scenario.id, "accounts-gdm", "Logging out to the GDM user chooser")
        self._logout_graphical_user(vm, self.secondary_username)
        remote = "/run/anduinos-feature-accounts"
        gdm = self._gdm_user(vm)
        command = _desktop_command(
            gdm,
            (
                "python3",
                f"{remote}/atspi_driver.py",
                "gdm-audit-users",
                "--account",
                self.secondary_username,
                "--full-name",
                self.secondary_full_name,
                "--original-account",
                self.username,
                "--original-full-name",
                self.full_name,
                "--evidence",
                f"{remote}/evidence/gdm-audit",
            ),
        )
        result = vm.serial.run(command, timeout=120, check=False)
        (artifacts / "gdm-user-events.jsonl").write_text(
            result.stdout + "\n", encoding="utf-8"
        )
        _retrieve_tree(vm.serial, remote, artifacts / "guest-account-evidence")
        if result.returncode != 0:
            raise TestFailure(
                "GDM did not expose both installed users through AT-SPI:\n"
                + result.stdout[-8000:]
            )
        _validate_gdm_user_events(
            result.stdout,
            self.username,
            self.secondary_username,
        )
        vm.screenshot("account-logout-gdm")

    def _exercise_gdm_branding(
        self,
        vm: QemuVm,
        base: PromotedBase,
        artifacts: Path,
    ) -> None:
        assert vm.serial is not None
        gdm = self._gdm_user(vm)
        cursor_contract = vm.serial.run(
            _desktop_command(
                gdm,
                (
                    "env",
                    "DCONF_PROFILE=gdm",
                    "bash",
                    "-lc",
                    "printf 'cursor-theme=%s\\n' \"$(gsettings get org.gnome.desktop.interface cursor-theme)\"; "
                    "printf 'cursor-size=%s\\n' \"$(gsettings get org.gnome.desktop.interface cursor-size)\"",
                ),
            ),
            timeout=60,
        ).stdout
        package_contract = vm.serial.run(
            "set -e; dpkg-query -W -f='gdm-brand-package=${db:Status-Abbrev} ${Version}\\n' "
            "anduinos-gdm3-wallpaper; "
            "test -s /usr/share/pixmaps/anduinos_text_smaller.png; "
            "printf 'gdm-brand-asset=present\\n'",
            timeout=30,
        ).stdout
        contract = _join_contract_outputs(cursor_contract, package_contract)
        (artifacts / "gdm-branding-contract.txt").write_text(
            contract + "\n", encoding="utf-8"
        )
        _validate_gdm_cursor_contract(contract)
        screenshot = vm.screenshot("gdm-branding")
        watermark = artifacts / "gdm-anduinos-watermark.png"
        _retrieve_file(
            vm.serial,
            "/usr/share/pixmaps/anduinos_text_smaller.png",
            watermark,
        )
        match = plymouth_match(screenshot, watermark)
        (artifacts / "gdm-branding-analysis.json").write_text(
            json.dumps(match, indent=2) + "\n", encoding="utf-8"
        )
        if not match.get("matched"):
            raise TestFailure(
                "The visible GDM frame did not contain the installed AnduinOS "
                f"wordmark: {match}"
            )

    def _exercise_gdm_cursor(
        self,
        vm: QemuVm,
        base: PromotedBase,
        artifacts: Path,
    ) -> None:
        assert vm.qmp is not None and vm.serial is not None
        gdm = self._gdm_user(vm)
        policy = self._gdm_gsettings_get(
            vm, gdm, "org.gnome.desktop.lockdown", "disable-save-to-disk"
        )
        if policy != "true":
            raise TestFailure("GDM screenshot lockdown is unexpectedly disabled")

        # Observe the same separate hardware plane a SPICE viewer receives.
        # Do not unlock GDM, impersonate MediaKeys, or substitute a stock arrow.
        # The requested QMP coordinates alone are never evidence of movement.
        with SpiceCursorObserver(vm.spice_socket, artifacts) as cursor:
            initial = vm.screenshot("gdm-cursor-framebuffer-initial")
            with Image.open(initial) as frame:
                width, height = frame.size
            # Wake the initially hidden cursor before measuring two fresh moves.
            vm.qmp.move_pointer_absolute(0.5, 0.5)
            cursor._run_for(1.0)
            views = []
            for label, fraction in (("left", 0.25), ("right", 0.75)):
                cursor.observe_move(
                    lambda: vm.qmp.move_pointer_absolute(fraction, 0.5),
                    round(fraction * (width - 1)),
                    round(0.5 * (height - 1)),
                )
                raw = vm.screenshot(f"gdm-cursor-{label}-framebuffer")
                view = artifacts / f"gdm-cursor-{label}.png"
                cursor.save_view(raw, view)
                views.append(view)
            before, after = views

        unchanged = self._gdm_gsettings_get(
            vm, gdm, "org.gnome.desktop.lockdown", "disable-save-to-disk"
        )
        (artifacts / "gdm-screenshot-lockdown.txt").write_text(
            f"before={policy}\nafter={unchanged}\n", encoding="utf-8"
        )
        if unchanged != policy:
            raise TestFailure("GDM screenshot lockdown changed during cursor capture")
        assert_pointer_motion(before, after, artifacts / "gdm-cursor-motion.json")

        # End with the original account usable.  This also proves that adding
        # and changing another account did not break the installer-created one.
        self._select_gdm_account(
            vm,
            artifacts,
            self.username,
            self.full_name,
            self.password,
            "original-relogin",
        )
        login = self._wait_for_graphical_identity(vm, self.username, timeout=150)
        _validate_graphical_login(login, self.username)
        (artifacts / "account-original-relogin.txt").write_text(
            login + "\n", encoding="utf-8"
        )
        vm.screenshot("account-original-session-restored")

    def _gdm_gsettings_get(
        self,
        vm: QemuVm,
        gdm: str,
        schema: str,
        key: str,
    ) -> str:
        """Read the same file-backed dconf profile used by the real greeter."""

        assert vm.serial is not None
        return vm.serial.run(
            _desktop_command(
                gdm,
                (
                    "env",
                    "DCONF_PROFILE=gdm",
                    "gsettings",
                    "get",
                    schema,
                    key,
                ),
            ),
            timeout=30,
        ).stdout.strip()

    def _prepare_account_fixture(self, vm: QemuVm) -> str:
        assert vm.serial is not None
        remote = "/run/anduinos-feature-accounts"
        vm.serial.run(f"install -d -m 0777 {remote}/evidence")
        self.driver.upload(vm.serial, remote)
        return remote

    def _logout_graphical_user(self, vm: QemuVm, user: str) -> None:
        assert vm.serial is not None
        result = vm.serial.run(
            _desktop_command(user, ("gnome-session-quit", "--logout", "--no-prompt")),
            timeout=60,
            check=False,
        )
        deadline = time.monotonic() + 120
        while time.monotonic() < deadline:
            if not _graphical_user_optional(vm.serial):
                break
            time.sleep(1)
        else:
            raise TestFailure(
                f"GNOME logout for {user} did not end its graphical session; "
                "command output:\n" + result.stdout[-4000:]
            )

        # The regular user's Wayland socket disappears before the greeter has
        # necessarily created its own bus and compositor socket. Starting an
        # AT-SPI command in that black-frame gap fails immediately with empty
        # output, so explicitly wait for the real GDM desktop transport.
        gdm = self._gdm_user(vm)
        ready_command = _desktop_command(gdm, ("true",))
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            ready = vm.serial.run(ready_command, timeout=30, check=False)
            if ready.returncode == 0:
                time.sleep(1)
                return
            time.sleep(1)
        raise TestFailure(
            f"GNOME logout for {user} ended the session, but the GDM desktop "
            "transport never became ready"
        )

    def _select_gdm_account(
        self,
        vm: QemuVm,
        artifacts: Path,
        account: str,
        full_name: str,
        password: str,
        label: str,
    ) -> None:
        assert vm.serial is not None
        remote = "/run/anduinos-feature-accounts"
        try:
            _authenticate_gdm_account(
                vm, self._gdm_user(vm), remote, artifacts,
                account, full_name, password, label, timeout=120,
            )
        finally:
            _retrieve_tree(vm.serial, remote, artifacts / "guest-account-evidence")

    def _wait_for_graphical_identity(
        self,
        vm: QemuVm,
        expected: str,
        *,
        timeout: float,
    ) -> str:
        assert vm.serial is not None
        deadline = time.monotonic() + timeout
        observed = ""
        last_contract = ""
        while time.monotonic() < deadline:
            observed = _graphical_user_optional(vm.serial)
            if observed == expected:
                contract = vm.serial.run(
                    "set -e; "
                    f"user={shlex.quote(expected)}; "
                    "uid=$(id -u \"$user\"); "
                    "session=$(loginctl show-user \"$user\" -p Display --value); "
                    "test -n \"$session\"; "
                    "name=$(loginctl show-session \"$session\" -p Name --value); "
                    "class=$(loginctl show-session \"$session\" -p Class --value); "
                    "type=$(loginctl show-session \"$session\" -p Type --value); "
                    "active=$(loginctl show-session \"$session\" -p Active --value); "
                    "remote=$(loginctl show-session \"$session\" -p Remote --value); "
                    "test \"$name\" = \"$user\"; test \"$class\" = user; "
                    "test \"$type\" = wayland; test \"$active\" = yes; "
                    "test \"$remote\" = no; "
                    "printf 'graphical-user=%s\\n' \"$user\"; "
                    "printf 'session-id=%s\\n' \"$session\"; "
                    "printf 'session-name=%s\\n' \"$name\"; "
                    "printf 'session-class=%s\\n' \"$class\"; "
                    "printf 'session-type=%s\\n' \"$type\"; "
                    "printf 'session-active=%s\\n' \"$active\"; "
                    "printf 'session-remote=%s\\n' \"$remote\"; "
                    "home=$(getent passwd \"$user\" | cut -d: -f6); "
                    "test \"$(stat -c %U \"$home\")\" = \"$user\"; "
                    "printf 'home-owner=%s\\n' \"$user\"",
                    timeout=60,
                    check=False,
                )
                last_contract = contract.stdout
                if contract.returncode == 0:
                    return contract.stdout
            time.sleep(1)
        raise TestFailure(
            f"Expected active local Wayland user {expected!r}, last observed "
            f"{observed!r}; last contract output={last_contract[-2000:]!r}"
        )

    def _gdm_user(self, vm: QemuVm) -> str:
        assert vm.serial is not None
        deadline = time.monotonic() + 120
        while time.monotonic() < deadline:
            user = _gdm_user_optional(vm.serial)
            if user:
                return user
            time.sleep(1)
        diagnostics = vm.serial.run(
            "loginctl list-sessions --no-legend || true; "
            "for user in gdm-greeter gdm; do "
            "uid=$(id -u \"$user\" 2>/dev/null) || continue; "
            "printf '\\n[%s uid=%s]\\n' \"$user\" \"$uid\"; "
            "find \"/run/user/$uid\" -maxdepth 1 -printf '%y %f\\n' "
            "2>&1 | sort; done",
            timeout=30,
            check=False,
        )
        raise TestFailure(
            "GDM did not expose a greeter account with a live session bus and "
            "Wayland socket:\n" + diagnostics.stdout[-8000:]
        )

    def _password_fingerprint(self, vm: QemuVm, user: str) -> str:
        assert vm.serial is not None
        result = vm.serial.run(
            "set -e; hash=$(getent shadow "
            f"{shlex.quote(user)} | cut -d: -f2); "
            "test -n \"$hash\"; test \"$hash\" != '!'; test \"$hash\" != '*'; "
            "printf '%s' \"$hash\" | sha256sum | cut -d' ' -f1",
            timeout=30,
        )
        return result.stdout.strip().splitlines()[-1]
