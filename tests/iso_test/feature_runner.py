"""Installed-system feature suites executed on disposable qcow2 overlays."""

from __future__ import annotations

import base64
import json
import hashlib
import re
import shlex
import shutil
import subprocess
import time
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from collections.abc import Callable

from PIL import Image, UnidentifiedImageError

from .base import PromotedBase, discard_overlay
from .assertions import assert_release_contract
from .errors import TestFailure
from .feature_model import FeatureSuite
from .fixtures import build_file_integration_fixtures
from .grub import render_installed_grub_restoration
from .journal import (
    JournalPolicy,
    parse_journal_jsonl,
    parse_package_versions,
    render_guest_collection_script,
    render_verdict,
)
from .qemu import QemuVm
from .runner import (
    RunnerOptions,
    _desktop_command,
    _graphical_user,
    _graphical_user_optional,
    _login_gdm,
    _power_off,
    _retrieve_file,
    _retrieve_tree,
    _run_with_qmp_key_requests,
)
from .visual import (
    assert_cpu_z_thumbnail,
    assert_wechat_login_window,
    assert_pointer_motion,
    assert_settings_about_logo,
    assert_fixture_quadrants,
    assert_start_button_logo,
    assert_swapcontrol_green,
    assert_theme_transition,
    plymouth_match,
)


_SHELL_DRIVER_CHECKS = frozenset(
    {
        "shell.initial-overview-hidden",
        "shortcut.super-tab",
        "shortcut.alt-tab",
        "shortcut.super-i",
        "branding.settings-about-logo",
        "appearance.swapcontrol-green",
        "shortcut.super-u",
        "shortcut.super-shift-s",
        "branding.start-button-logo",
        "panel.pin-application",
        "panel.remove-menu-localized",
        "shell.appindicator-roundtrip",
        "desktop.icons-visible",
        "desktop.context-menu-terminal",
        "desktop.create-shortcut",
        "search.spotify-store",
        "store.spotify-public",
        "app.wechat-install",
    }
)
_SHORTCUT_FIXTURE_CHECKS = frozenset({"shortcut.alt-tab"})
_PANEL_FIXTURE_CHECKS = frozenset(
    {
        "panel.pin-application",
        "panel.remove-menu-localized",
        "desktop.create-shortcut",
    }
)
_INDICATOR_FIXTURE_CHECKS = frozenset({"shell.appindicator-roundtrip"})
_LOCAL_ARCMENU_SEARCH_CHECKS = frozenset(
    {
        "panel.pin-application",
        "desktop.create-shortcut",
    }
)
_LOCAL_SEARCH_DRIVER_MODES = frozenset(
    {
        "shell-panel-pin",
        "shell-panel-pin-persisted",
        "shell-panel-remove",
        "shell-desktop-shortcut",
    }
)
_SOFTWARE_SEARCH_DRIVER_MODES = frozenset(
    {
        "shell-spotify-store",
        "public-wechat-install",
    }
)
_SOFTWARE_SEARCH_PROVIDER_ID = "org.gnome.Software.desktop"

_CPU_Z_VERSION = "2.20.2"
_CPU_Z_ARCHIVE = f"cpu-z_{_CPU_Z_VERSION}-en.zip"
_CPU_Z_URL = f"https://download.cpuid.com/cpu-z/{_CPU_Z_ARCHIVE}"
_CPU_Z_ARCHIVE_SHA256 = (
    "320e073a6f387464ac3faac5f010b5fe70e31fab30745883d023c8372e80f3c5"
)
_CPU_Z_MEMBER = "cpuz_x64.exe"
_CPU_Z_MEMBER_SHA256 = (
    "e1b0eda853641b75fa1a890e7811bc19b3be0ece0494c60f03d34247b7650126"
)
_CPU_Z_MEMBER_SIZE = 7_428_328
_CPU_Z_MIMES = frozenset(
    {
        "application/vnd.microsoft.portable-executable",
        "application/x-msdownload",
    }
)
_CPU_Z_HANDLER = "com.anduinos.ExeRunner.desktop"
_SPOTIFY_REMOTE = "flathub"
_SPOTIFY_REMOTE_URL = "https://dl.flathub.org/repo/"
_SPOTIFY_APP_ID = "com.spotify.Client"
_SPOTIFY_ARCH = "x86_64"
_SPOTIFY_REF = f"app/{_SPOTIFY_APP_ID}/{_SPOTIFY_ARCH}/stable"
_WECHAT_APP_ID = "com.tencent.WeChat"
_WECHAT_ARCH = "x86_64"
_WECHAT_REF = f"app/{_WECHAT_APP_ID}/{_WECHAT_ARCH}/stable"


@dataclass(frozen=True)
class FeatureSuiteResult:
    id: str
    source_case: str
    status: str
    seconds: float
    artifacts: Path
    error: str = ""


class FeatureSuiteRunner:
    """Run a declared suite without ever mutating its verified base image."""

    IMPLEMENTATION_METHODS = {
        "input.super-space-rime": "_exercise_rime_input",
        "system.ordinary-reboot": "_exercise_ordinary_reboot",
        "storage.btrfs-docker-rollback": "_exercise_btrfs_rollback",
        "account.add-user": "_exercise_account_add_user",
        "account.new-user-login": "_exercise_account_new_user_login",
        "account.change-password": "_exercise_account_change_password",
        "account.logout-gdm": "_exercise_account_logout_gdm",
        "branding.gdm": "_exercise_gdm_branding",
        "theme.cursor-gdm": "_exercise_gdm_cursor",
        "localization.zh-cn-contract": "_exercise_localization_zh_cn",
        "appearance.theme-menu-localized": "_exercise_theme_selector",
        "appearance.theme-gtk": "_exercise_gtk_theme",
        "appearance.theme-qt": "_exercise_qt_theme",
        "appearance.theme-firefox": "_exercise_firefox_theme",
        "shell.initial-overview-hidden": "_exercise_initial_overview",
        "shortcut.super-tab": "_exercise_super_tab",
        "shortcut.alt-tab": "_exercise_alt_tab",
        "shortcut.super-i": "_exercise_super_i",
        "branding.settings-about-logo": "_exercise_settings_about_branding",
        "tty.tty6-branding": "_exercise_tty6_branding",
        "appearance.swapcontrol-green": "_exercise_swapcontrol_green",
        "files.image-thumbnail": "_exercise_image_thumbnail",
        "files.video-thumbnail": "_exercise_video_thumbnail",
        "files.image-open": "_exercise_image_open",
        "files.video-open": "_exercise_video_open",
        "files.deb-software": "_exercise_deb_software",
        "input.utf8-chinese-text": "_exercise_chinese_editor",
        "shortcut.super-u": "_exercise_super_u",
        "shortcut.super-shift-s": "_exercise_screenshot_shortcut",
        "branding.start-button-logo": "_exercise_start_button_logo",
        "panel.pin-application": "_exercise_panel_pin",
        "panel.remove-menu-localized": "_exercise_panel_remove",
        "shell.appindicator-roundtrip": "_exercise_appindicator_roundtrip",
        "desktop.icons-visible": "_exercise_desktop_icons",
        "terminal.ptyxis-initial-size": "_exercise_ptyxis_initial_size",
        "desktop.context-menu-terminal": "_exercise_desktop_terminal",
        "desktop.create-shortcut": "_exercise_desktop_shortcut",
        "search.spotify-store": "_exercise_spotify_store",
        "files.cpuz-thumbnail-and-open": "_exercise_public_cpu_z",
        "apt.nextcloud-client-ppa": "_exercise_nextcloud_ppa",
        "store.spotify-public": "_exercise_spotify_public",
        "app.wechat-install": "_exercise_wechat_install",
    }

    def __init__(
        self,
        options: RunnerOptions,
        username: str,
        full_name: str,
        password: str,
        *,
        fail_fast: bool = False,
        phase_callback: Callable[[str, str, str], None] | None = None,
        check_callback: Callable[[str, str, str, str, str], None] | None = None,
    ) -> None:
        self.options = options
        self.username = username
        self.full_name = full_name
        self.password = password
        self.fail_fast = fail_fast
        self.phase_callback = phase_callback or (lambda _case, _suite, _phase: None)
        self.check_callback = check_callback
        self.framework_root = Path(__file__).parents[1]
        self.driver = self.framework_root / "guest" / "atspi_driver.py"
        self.gdm_screenshot_client = (
            self.framework_root / "guest" / "gdm_screenshot_client.py"
        )
        self.btrfs_rollback_oracle = (
            self.framework_root / "guest" / "btrfs_rollback_oracle.py"
        )
        self.input_fixture = self.framework_root / "guest" / "input_fixture.py"
        self.shell_fixture = self.framework_root / "guest" / "shell_fixture.py"
        self.shell_desktop_fixture = (
            self.framework_root
            / "guest"
            / "com.anduinos.AcceptanceShellFixture.desktop"
        )
        self.panel_fixture = self.framework_root / "guest" / "panel_fixture.py"
        self.indicator_fixture = (
            self.framework_root / "guest" / "indicator_fixture.py"
        )
        self.panel_desktop_fixture = (
            self.framework_root
            / "guest"
            / "com.anduinos.AcceptancePanelFixture.desktop"
        )
        self.theme_fixture = self.framework_root / "guest" / "theme_fixture.py"
        self.qt_theme_fixture = self.framework_root / "guest" / "qt_theme_fixture.py"
        self.theme_web_fixture = self.framework_root / "guest" / "theme_fixture.html"
        self.journal_policy = JournalPolicy.load(
            self.framework_root / "journal-policy.json"
        )
        self._states: dict[str, str] = {}
        self.secondary_username = "anduinossecondary"
        self.secondary_full_name = "AnduinOS Acceptance Secondary"
        self.secondary_initial_password = "AnduinOS-Secondary-456!"
        self.secondary_new_password = "AnduinOS-Secondary-789!"

    def run(
        self,
        base: PromotedBase,
        suite: FeatureSuite,
    ) -> FeatureSuiteResult:
        started = time.monotonic()
        source_case = base.scenario.id
        artifacts = (
            self.options.artifacts_root
            / source_case
            / "feature-suites"
            / suite.id
        )
        if artifacts.exists():
            raise TestFailure(f"Refusing to reuse feature artifacts: {artifacts}")
        artifacts.mkdir(parents=True)
        self._states = {identifier: "pending" for identifier in suite.checks}
        vm: QemuVm | None = None
        integrity_verified_after = False
        try:
            with base.locked():
                self._record_base_integrity(base, artifacts, "before")
                self.phase_callback(source_case, suite.id, "Creating disposable overlay")
                vm = base.overlay_vm(suite.id, artifacts, self.options.disk_storage)
                vm.create_disk()
                self._write_manifest(base, suite, vm, artifacts)
                self._boot_overlay(vm, base, suite)
                self._run_declared_checks(vm, base, suite, artifacts)
                self._assert_complete(suite)
                if vm.running:
                    self.phase_callback(source_case, suite.id, "Powering off disposable overlay")
                    _power_off(vm)
                self._record_base_integrity(base, artifacts, "after")
                integrity_verified_after = True
            return FeatureSuiteResult(
                suite.id,
                source_case,
                "passed",
                time.monotonic() - started,
                artifacts,
            )
        except BaseException as error:
            if vm is not None and vm.running:
                try:
                    vm.screenshot("failure")
                except Exception:
                    pass
                try:
                    assert vm.serial is not None
                    diagnostics = vm.serial.run(
                        "set +e; "
                        "printf '%s\\n' '--- loginctl ---'; loginctl list-sessions; "
                        "printf '%s\\n' '--- gdm ---'; "
                        "systemctl --no-pager --full status gdm.service; "
                        "printf '%s\\n' '--- journal ---'; "
                        "journalctl -b --no-pager -n 1200",
                        timeout=90,
                        check=False,
                    )
                    (artifacts / "failure-system-state.txt").write_text(
                        diagnostics.stdout + "\n", encoding="utf-8"
                    )
                except Exception:
                    pass
            (artifacts / "failure.txt").write_text(
                f"{type(error).__name__}: {error}\n", encoding="utf-8"
            )
            if isinstance(error, (KeyboardInterrupt, SystemExit)):
                raise
            return FeatureSuiteResult(
                suite.id,
                source_case,
                "failed",
                time.monotonic() - started,
                artifacts,
                f"{type(error).__name__}: {error}",
            )
        finally:
            if vm is not None:
                discard_overlay(vm)
                (artifacts / "overlay-retention.txt").write_text(
                    "Disposable overlay discarded after QEMU stopped; durable "
                    "logs, screenshots, and structured evidence remain.\n",
                    encoding="utf-8",
                )
            if not integrity_verified_after:
                # A boot/check failure may unwind the main lock while QEMU is
                # still alive.  Verify only after discard_overlay has reaped it,
                # then preserve this second failure as evidence without hiding
                # the original product/infrastructure error.
                try:
                    with base.locked():
                        self._record_base_integrity(base, artifacts, "after-failure")
                except Exception as integrity_error:
                    (artifacts / "base-integrity-after-failure.txt").write_text(
                        f"{type(integrity_error).__name__}: {integrity_error}\n",
                        encoding="utf-8",
                    )

    def _run_declared_checks(
        self,
        vm: QemuVm,
        base: PromotedBase,
        suite: FeatureSuite,
        artifacts: Path,
    ) -> None:
        """Run every safe check unless explicit fail-fast was requested.

        A failed product assertion does not make a still-running disposable
        guest unusable. Keep collecting independent evidence in that case so
        one defect cannot hide the remaining declared checks. Infrastructure
        and protocol failures are intentionally not caught here, and a product
        failure that stopped QEMU is fatal for the rest of the suite.
        """

        failures: list[tuple[str, TestFailure]] = []
        for identifier in suite.checks:
            try:
                with self._check(base.scenario.id, suite.id, identifier):
                    self._run_check(identifier, vm, base, artifacts)
            except TestFailure as error:
                failures.append((identifier, error))
                if self.fail_fast or not vm.running:
                    raise
        if failures:
            detail = "; ".join(
                f"{identifier}: {error}" for identifier, error in failures
            )
            raise TestFailure(
                f"{suite.id}: {len(failures)} declared check(s) failed: {detail}"
            )

    @staticmethod
    def _record_base_integrity(
        base: PromotedBase,
        artifacts: Path,
        phase: str,
    ) -> None:
        evidence = base.verify_integrity()
        (artifacts / f"base-integrity-{phase}.json").write_text(
            json.dumps(evidence, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )

    def _boot_overlay(
        self,
        vm: QemuVm,
        base: PromotedBase,
        suite: FeatureSuite,
    ) -> None:
        self.phase_callback(base.scenario.id, suite.id, "Booting verified installation base")
        vm.start(attach_iso=False, phase="feature")
        assert vm.qmp is not None and vm.serial is not None
        vm.serial.timeout = self.options.command_timeout_seconds
        vm.serial.wait_for_shell(self.options.boot_timeout_seconds)
        restoration = vm.serial.run(
            render_installed_grub_restoration(),
            timeout=30,
        )
        (vm.config.artifacts / "grub-restoration.txt").write_text(
            restoration.stdout + "\n",
            encoding="utf-8",
        )
        if _SHELL_DRIVER_CHECKS.intersection(suite.checks):
            # GNOME Shell must discover the deterministic fixture identity
            # when the user session starts. Rewriting its desktop entry while
            # Shell is running makes the Dash rebuild its model mid-frame and
            # can race icon creation, which is unrelated to shortcut behavior.
            self._install_shell_fixture(
                vm,
                shortcut_fixture=bool(
                    _SHORTCUT_FIXTURE_CHECKS.intersection(suite.checks)
                ),
                panel_fixture=bool(
                    _PANEL_FIXTURE_CHECKS.intersection(suite.checks)
                ),
                indicator_fixture=bool(
                    _INDICATOR_FIXTURE_CHECKS.intersection(suite.checks)
                ),
            )
        if _LOCAL_ARCMENU_SEARCH_CHECKS.intersection(suite.checks):
            # These suites exercise ArcMenu's own local application result.
            # Disable the unrelated Software provider before GNOME Shell is
            # born so an asynchronous PackageKit failure cannot be attributed
            # to a taskbar or desktop-shortcut gesture. Store suites use a
            # fresh overlay and deliberately keep the provider enabled.
            self._configure_local_search_provider_isolation(
                vm,
                vm.config.artifacts,
            )
        self.phase_callback(base.scenario.id, suite.id, "Logging into GNOME through GDM")
        _login_gdm(vm, self.username, self.password, timeout=120)
        if _graphical_user(vm.serial) != self.username:
            raise TestFailure("Feature overlay opened an unexpected GNOME session")

    @contextmanager
    def _check(self, case: str, suite: str, identifier: str):
        self._emit(case, suite, identifier, "running", "Running assertions")
        try:
            yield
        except BaseException as error:
            self._emit(
                case,
                suite,
                identifier,
                "failed",
                f"{type(error).__name__}: {error}",
            )
            raise
        else:
            self._emit(case, suite, identifier, "passed", "All assertions passed")

    def _emit(
        self,
        case: str,
        suite: str,
        identifier: str,
        state: str,
        detail: str,
    ) -> None:
        if identifier not in self._states:
            raise TestFailure(f"Feature runner emitted undeclared check {identifier!r}")
        self._states[identifier] = state
        if self.check_callback is not None:
            self.check_callback(case, suite, identifier, state, detail)

    def _assert_complete(self, suite: FeatureSuite) -> None:
        incomplete = [
            f"{identifier}={state}"
            for identifier, state in self._states.items()
            if state != "passed"
        ]
        if incomplete:
            raise TestFailure(
                f"{suite.id}: suite ended without passing every declared check: "
                + ", ".join(incomplete)
            )

    def _run_check(
        self,
        identifier: str,
        vm: QemuVm,
        base: PromotedBase,
        artifacts: Path,
    ) -> None:
        method = self.IMPLEMENTATION_METHODS.get(identifier)
        if method is None:
            raise TestFailure(f"No executable implementation for {identifier}")
        implementation = getattr(self, method)
        implementation(vm, base, artifacts)

    def _exercise_ordinary_reboot(
        self,
        vm: QemuVm,
        base: PromotedBase,
        artifacts: Path,
    ) -> None:
        """Prove that the same VM model can complete an ordinary guest reboot."""

        assert vm.serial is not None and vm.qmp is not None
        remote = "/run/anduinos-feature-lifecycle"
        vm.serial.run(f"install -d -m 0755 {remote}")
        key = self._prepare_power_control(vm, artifacts, remote)
        before = self._ssh(
            vm,
            key,
            "set -e; printf 'boot-id=%s\\n' "
            "\"$(cat /proc/sys/kernel/random/boot_id)\"; "
            "systemctl is-active graphical.target; systemctl is-active gdm; "
            "sudo -n /usr/local/sbin/anduinos-acceptance-package-health",
        )
        before_id = _last_value(before, "boot-id")
        (artifacts / "lifecycle-before-reboot.txt").write_text(
            before + "\n", encoding="utf-8"
        )

        self.phase_callback(
            base.scenario.id,
            "system-lifecycle",
            "Requesting ordinary guest reboot",
        )
        request = self._ssh(
            vm,
            key,
            "sudo -n /usr/local/sbin/anduinos-acceptance-reboot",
        )
        (artifacts / "lifecycle-reboot-request.txt").write_text(
            request + "\n", encoding="utf-8"
        )
        started = time.monotonic()
        self._wait_for_power_transition(
            vm,
            key,
            artifacts,
            "lifecycle-ordinary-reboot",
            timeout=150,
        )
        shutdown_seconds = time.monotonic() - started
        vm.stop()

        # This boot is deliberately untouched: no GRUB edit and no debug
        # shell.  SSH was installed in the disposable overlay before reboot.
        vm.start(attach_iso=False, phase="lifecycle-reboot")
        self._ssh_eventually(
            vm,
            key,
            self._graphical_boot_ready_command(),
            timeout=self.options.boot_timeout_seconds,
        )
        after = self._ssh(
            vm,
            key,
            "set -e; printf 'boot-id=%s\\n' "
            "\"$(cat /proc/sys/kernel/random/boot_id)\"; "
            "systemctl is-active graphical.target; systemctl is-active gdm; "
            "sudo -n /usr/local/sbin/anduinos-acceptance-package-health; "
            "printf 'ordinary-reboot=ok\\n'",
            timeout=180,
        )
        after_id = _last_value(after, "boot-id")
        _validate_distinct_boot_ids(before_id, after_id)
        (artifacts / "lifecycle-after-reboot.txt").write_text(
            after
            + f"\nbefore-boot-id={before_id}\nafter-boot-id={after_id}\n"
            + f"guest-shutdown-seconds={shutdown_seconds:.3f}\n",
            encoding="utf-8",
        )
        vm.screenshot("lifecycle-after-ordinary-reboot")
        # The successful second boot is intentionally free of the injected
        # serial debug shell, so the generic serial-based suite cleanup cannot
        # be used.  Flush through the authenticated guest channel, then close
        # the disposable VM through QMP.
        self._ssh(vm, key, "sync")
        vm.stop()

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
        remote = "/run/anduinos-feature-accounts/evidence"
        vm.serial.upload(
            self.gdm_screenshot_client,
            f"{remote}/gdm_screenshot_client.py",
            0o755,
        )
        policy_evidence = [self._backup_gdm_screenshot_policy(vm, gdm, remote)]
        try:
            gdm, opened = self._set_gdm_screenshot_policy(
                vm, remote, capture_enabled=True
            )
            policy_evidence.append(opened)
            policy_evidence.append(self._suspend_gdm_media_keys(vm, gdm))
            vm.qmp.move_pointer_absolute(0.25, 0.5)
            time.sleep(1)
            before = self._capture_gdm_cursor_frame(
                vm, gdm, remote, artifacts, "gdm-cursor-left"
            )
            vm.qmp.move_pointer_absolute(0.75, 0.5)
            time.sleep(1)
            after = self._capture_gdm_cursor_frame(
                vm, gdm, remote, artifacts, "gdm-cursor-right"
            )
        finally:
            _, restored = self._set_gdm_screenshot_policy(
                vm, remote, capture_enabled=False
            )
            policy_evidence.append(restored)
            (artifacts / "gdm-screenshot-lockdown.txt").write_text(
                "\n".join(policy_evidence) + "\n", encoding="utf-8"
            )
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

    def _backup_gdm_screenshot_policy(
        self,
        vm: QemuVm,
        gdm: str,
        remote: str,
    ) -> str:
        """Save the locked GDM policy before the overlay-only visual probe."""

        assert vm.serial is not None
        backup = f"{remote}/gdm-screenshot-policy"
        system_settings = "/usr/share/gdm/dconf/00-upstream-settings"
        system_locks = "/usr/share/gdm/dconf/locks/00-upstream-settings-locks"
        original = self._gdm_gsettings_get(
            vm,
            gdm,
            "org.gnome.desktop.lockdown",
            "disable-save-to-disk",
        )
        if original != "true":
            raise TestFailure(
                "GDM did not start with its expected save-to-disk lockdown: "
                f"observed {original!r} through DCONF_PROFILE=gdm"
            )
        result = vm.serial.run(
            "set -euo pipefail; "
            f"backup={shlex.quote(backup)}; "
            f"settings={shlex.quote(system_settings)}; "
            f"locks={shlex.quote(system_locks)}; "
            "install -d -m 0700 \"$backup\"; "
            "grep -Fxq 'file-db:/var/lib/gdm3/greeter-dconf-defaults' "
            "/usr/share/dconf/profile/gdm; "
            "grep -Fxq '/org/gnome/desktop/lockdown/disable-save-to-disk' \"$locks\"; "
            "grep -Eq '^disable-save-to-disk=true$' \"$settings\"; "
            "cp --preserve=all \"$settings\" \"$backup/settings\"; "
            "cp --preserve=all \"$locks\" \"$backup/locks\"; "
            "printf 'original-lockdown=true\\n'; "
            "sha256sum \"$backup/settings\" \"$backup/locks\"",
            timeout=30,
        )
        return result.stdout

    def _set_gdm_screenshot_policy(
        self,
        vm: QemuVm,
        remote: str,
        *,
        capture_enabled: bool,
    ) -> tuple[str, str]:
        """Open or restore the one locked key, restarting the real greeter."""

        assert vm.serial is not None
        backup = f"{remote}/gdm-screenshot-policy"
        settings = "/usr/share/gdm/dconf/00-upstream-settings"
        locks = "/usr/share/gdm/dconf/locks/00-upstream-settings-locks"
        if capture_enabled:
            result = vm.serial.run(
                "set -euo pipefail; "
                f"settings={shlex.quote(settings)}; locks={shlex.quote(locks)}; "
                "sed -i "
                "'\\|^/org/gnome/desktop/lockdown/disable-save-to-disk$|d' "
                "\"$locks\"; "
                "sed -i "
                "'s/^disable-save-to-disk=true$/disable-save-to-disk=false/' "
                "\"$settings\"; "
                "grep -Eq '^disable-save-to-disk=false$' \"$settings\"; "
                "! grep -Fxq "
                "'/org/gnome/desktop/lockdown/disable-save-to-disk' \"$locks\"; "
                "systemctl restart gdm.service; "
                "printf 'temporary-policy-files=prepared\\n'",
                timeout=60,
            ).stdout
            expected = "false"
        else:
            result = vm.serial.run(
                "set -euo pipefail; "
                f"backup={shlex.quote(backup)}; "
                f"settings={shlex.quote(settings)}; locks={shlex.quote(locks)}; "
                "cp --preserve=all --force \"$backup/settings\" \"$settings\"; "
                "cp --preserve=all --force \"$backup/locks\" \"$locks\"; "
                "cmp -s \"$backup/settings\" \"$settings\"; "
                "cmp -s \"$backup/locks\" \"$locks\"; "
                "systemctl restart gdm.service; "
                "printf 'policy-files-restored=yes\\n'",
                timeout=60,
            ).stdout
            expected = "true"
        gdm = self._gdm_user(vm)
        observed = self._gdm_gsettings_get(
            vm,
            gdm,
            "org.gnome.desktop.lockdown",
            "disable-save-to-disk",
        )
        if observed != expected:
            state = "temporary false" if capture_enabled else "restored true"
            raise TestFailure(
                f"GDM screenshot lockdown was not {state}: observed {observed!r}"
            )
        label = "temporary-lockdown=false" if capture_enabled else "restored-lockdown=true"
        if not capture_enabled:
            media_keys = vm.serial.run(
                _desktop_command(
                    gdm,
                    (
                        "bash",
                        "-lc",
                        "service=org.gnome.SettingsDaemon.MediaKeys.service; "
                        "deadline=$((SECONDS + 30)); "
                        "until systemctl --user is-active --quiet \"$service\"; do "
                        "if (( SECONDS >= deadline )); then "
                        "systemctl --user status \"$service\" --no-pager; exit 1; "
                        "fi; sleep 1; done; printf active",
                    ),
                ),
                timeout=45,
            ).stdout.strip()
            if media_keys != "active":
                raise TestFailure(
                    "GDM media-keys service was not restored after the visual probe"
                )
            result = _join_contract_outputs(result, "media-keys-restored=active")
        return gdm, _join_contract_outputs(result, label)

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

    def _capture_gdm_cursor_frame(
        self,
        vm: QemuVm,
        gdm: str,
        remote: str,
        artifacts: Path,
        label: str,
    ) -> Path:
        """Capture the compositor cursor plane from the real GDM session."""

        assert vm.serial is not None
        guest_path = f"{remote}/{label}.png"
        vm.serial.run(f"rm -f {shlex.quote(guest_path)}", timeout=30)
        result = vm.serial.run(
            _desktop_command(
                gdm,
                (
                    "python3",
                    f"{remote}/gdm_screenshot_client.py",
                    "--output",
                    guest_path,
                ),
            ),
            timeout=60,
            check=False,
        )
        (artifacts / f"{label}-capture.txt").write_text(
            result.stdout + "\n", encoding="utf-8"
        )
        if result.returncode != 0:
            raise TestFailure(
                "GDM Shell could not capture its compositor cursor plane with "
                f"include_cursor=true:\n{result.stdout[-4000:]}"
            )
        vm.serial.run(f"test -s {shlex.quote(guest_path)}", timeout=30)
        destination = artifacts / f"{label}.png"
        _retrieve_file(vm.serial, guest_path, destination)
        if not destination.is_file() or destination.stat().st_size == 0:
            raise TestFailure("GDM cursor screenshot was not retrieved")
        return destination

    def _suspend_gdm_media_keys(self, vm: QemuVm, gdm: str) -> str:
        """Release Shell's trusted sender name for the one-shot test client."""

        assert vm.serial is not None
        script = (
            "set -e; "
            "service=org.gnome.SettingsDaemon.MediaKeys.service; "
            "target=org.gnome.SettingsDaemon.MediaKeys.target; "
            "test \"$(systemctl --user is-active \"$service\")\" = active; "
            "systemctl --user stop \"$target\"; "
            "deadline=$((SECONDS + 15)); "
            "while systemctl --user is-active --quiet \"$service\"; do "
            "if (( SECONDS >= deadline )); then exit 1; fi; sleep 1; done; "
            "owner=$(gdbus call --session --dest org.freedesktop.DBus "
            "--object-path /org/freedesktop/DBus "
            "--method org.freedesktop.DBus.NameHasOwner "
            "org.gnome.SettingsDaemon.MediaKeys); "
            "test \"$owner\" = '(false,)'; "
            "printf 'media-keys-trusted-name=released\\n'"
        )
        result = vm.serial.run(
            _desktop_command(gdm, ("bash", "-lc", script)),
            timeout=45,
            check=False,
        )
        if result.returncode != 0:
            raise TestFailure(
                "Could not release the GDM media-keys sender name for the "
                "one-shot screenshot client:\n" + result.stdout[-4000:]
            )
        return result.stdout

    def _exercise_theme_selector(
        self,
        vm: QemuVm,
        base: PromotedBase,
        artifacts: Path,
    ) -> None:
        """Exercise the localized Shell selector and establish a dark baseline."""

        self._prepare_theme_fixture(vm)
        self.phase_callback(
            base.scenario.id,
            "desktop-theme",
            "Selecting dark style through the localized GNOME Shell menu",
        )
        self._select_desktop_theme(vm, artifacts, "dark", "selector-baseline")

    def _exercise_alt_tab(
        self,
        vm: QemuVm,
        base: PromotedBase,
        artifacts: Path,
    ) -> None:
        """Prove Alt+Tab moves focus between two real, distinct GTK windows."""

        self._prepare_shell_fixture(vm, launch_windows=True)
        self._run_shell_driver(
            vm,
            base,
            artifacts,
            mode="shortcut-alt-tab",
            validator=_validate_alt_tab_events,
        )

    def _exercise_initial_overview(
        self,
        vm: QemuVm,
        base: PromotedBase,
        artifacts: Path,
    ) -> None:
        """Observe the untouched post-login Shell state before any shortcut."""

        self._run_shell_driver(
            vm,
            base,
            artifacts,
            mode="shell-initial-overview",
            validator=_validate_initial_overview_events,
        )

    def _exercise_super_tab(
        self,
        vm: QemuVm,
        base: PromotedBase,
        artifacts: Path,
    ) -> None:
        """Prove AnduinOS Super+Tab shows and then hides the real Overview."""

        self._run_shell_driver(
            vm,
            base,
            artifacts,
            mode="shortcut-super-tab",
            validator=_validate_super_tab_events,
        )

    def _exercise_super_i(
        self,
        vm: QemuVm,
        base: PromotedBase,
        artifacts: Path,
    ) -> None:
        """Prove Super+I opens a focused GNOME Settings window."""

        self._run_shell_driver(
            vm,
            base,
            artifacts,
            mode="shortcut-super-i",
            validator=_validate_super_i_events,
        )
        assert vm.serial is not None
        vm.serial.run(
            _desktop_command(
                self.username,
                ("pkill", "-f", "(^|/)gnome-control-center( |$)"),
            ),
            timeout=30,
            check=False,
        )

    def _exercise_settings_about_branding(
        self,
        vm: QemuVm,
        base: PromotedBase,
        artifacts: Path,
    ) -> None:
        """Prove Settings paints AnduinOS identity on its real About page."""

        def assert_visible_logo(frame: Path, validated: object) -> None:
            if not isinstance(validated, dict):
                raise TestFailure("The Settings About validator returned no evidence")
            remote_assets = validated.get("assets")
            if not isinstance(remote_assets, list):
                raise TestFailure("The Settings About event returned no logo assets")
            templates = []
            for value in remote_assets:
                if not isinstance(value, dict):
                    raise TestFailure("The Settings About logo asset is malformed")
                rendered = value.get("rendered_template")
                if not isinstance(rendered, str):
                    raise TestFailure("The Settings About asset has no rendered template")
                templates.append(
                    artifacts
                    / "guest-shell-evidence"
                    / "settings-about-branding"
                    / Path(rendered).name
                )
            if any(not template.is_file() for template in templates):
                raise TestFailure(
                    "The guest did not return both rendered Settings About assets"
                )
            bounds = validated.get("bounds")
            if not isinstance(bounds, list):
                raise TestFailure("The Settings About event has no semantic bounds")
            assert_settings_about_logo(
                frame,
                templates,
                bounds,
                artifacts / "settings-about-logo-analysis.json",
            )

        assert vm.serial is not None
        try:
            self._run_shell_driver(
                vm,
                base,
                artifacts,
                mode="settings-about-branding",
                validator=_validate_settings_about_events,
                screenshot_validator=assert_visible_logo,
            )
        finally:
            vm.serial.run(
                _desktop_command(
                    self.username,
                    ("pkill", "-f", "(^|/)gnome-control-center( |$)"),
                ),
                timeout=30,
                check=False,
            )

    def _exercise_localization_zh_cn(
        self,
        vm: QemuVm,
        base: PromotedBase,
        artifacts: Path,
    ) -> None:
        """Require Chinese UI on three independent desktop surfaces."""

        assert vm.serial is not None
        try:
            self._run_shell_driver(
                vm,
                base,
                artifacts,
                mode="localization-zh-cn",
                validator=_validate_localization_zh_cn_events,
            )
        finally:
            vm.serial.run(
                _desktop_command(
                    self.username,
                    ("pkill", "-f", "(^|/)gnome-control-center( |$)"),
                ),
                timeout=30,
                check=False,
            )

    def _exercise_swapcontrol_green(
        self,
        vm: QemuVm,
        base: PromotedBase,
        artifacts: Path,
    ) -> None:
        """Prove the real Swap Control dashboard paints its green state."""

        def assert_green(frame: Path, _validated: object) -> None:
            assert_swapcontrol_green(
                frame,
                artifacts / "swapcontrol-green-analysis.json",
            )

        assert vm.serial is not None
        try:
            self._run_shell_driver(
                vm,
                base,
                artifacts,
                mode="swapcontrol-green",
                validator=_validate_swapcontrol_events,
                secret_texts={"swapcontrol-auth-password": self.password},
                screenshot_validator=assert_green,
            )
        finally:
            vm.serial.run(
                _desktop_command(
                    self.username,
                    ("pkill", "-f", "(^|/)swapcontrol-gtk( |$)"),
                ),
                timeout=30,
                check=False,
            )

    def _prepare_file_fixtures(
        self,
        vm: QemuVm,
        artifacts: Path,
    ) -> tuple[str, object]:
        """Upload a content-addressed desktop file set exactly once."""

        assert vm.serial is not None
        fixtures = build_file_integration_fixtures(
            artifacts / "host-file-fixtures"
        )
        paths = (fixtures.image, fixtures.video, fixtures.deb, fixtures.text)
        manifest = {
            path.name: {
                "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                "size": path.stat().st_size,
            }
            for path in paths
        }
        (artifacts / "file-fixture-manifest.json").write_text(
            json.dumps(manifest, indent=2) + "\n",
            encoding="utf-8",
        )
        remote = "/run/anduinos-feature-files"
        ready = vm.serial.run(
            f"test -f {shlex.quote(remote + '/.prepared')}",
            timeout=15,
            check=False,
        )
        if ready.returncode == 0:
            return remote, fixtures
        downloads = f"/home/{self.username}/Downloads"
        vm.serial.run(
            f"install -d -m 0777 {shlex.quote(remote + '/evidence')}\n"
            f"install -d -o {shlex.quote(self.username)} "
            f"-g {shlex.quote(self.username)} -m 0755 {shlex.quote(downloads)}",
            timeout=30,
        )
        vm.serial.upload(self.driver, f"{remote}/atspi_driver.py", 0o755)
        for path in paths:
            vm.serial.upload(path, f"{downloads}/{path.name}", 0o644)
        quoted_files = " ".join(
            shlex.quote(f"{downloads}/{path.name}") for path in paths
        )
        prepared = vm.serial.run(
            "set -euo pipefail\n"
            f"chown {shlex.quote(self.username)}:{shlex.quote(self.username)} "
            f"{quoted_files}\n"
            f"sha256sum {quoted_files}\n"
            f"touch {shlex.quote(remote + '/.prepared')}\n"
            "printf 'file-fixtures=prepared\\n'",
            timeout=60,
            check=False,
        )
        (artifacts / "file-fixture-guest-sha256.txt").write_text(
            prepared.stdout + "\n", encoding="utf-8"
        )
        if prepared.returncode != 0 or "file-fixtures=prepared" not in prepared.stdout:
            raise TestFailure(
                "Could not prepare desktop file fixtures:\n"
                + prepared.stdout[-8000:]
            )
        return remote, fixtures

    def _run_file_driver(
        self,
        vm: QemuVm,
        base: PromotedBase,
        artifacts: Path,
        *,
        mode: str,
        validator: Callable[[str], dict[str, object]],
        thumbnail_name: str | None = None,
        require_visible_fixture: bool = False,
        text_inputs: dict[str, str] | None = None,
    ) -> dict[str, object]:
        """Drive one real Nautilus operation and retain visual/journal evidence."""

        assert vm.serial is not None and vm.qmp is not None
        remote, _fixtures = self._prepare_file_fixtures(vm, artifacts)
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
            timeout=300,
            text_inputs=text_inputs,
            request_trace=artifacts / f"{mode}-qmp-requests.jsonl",
        )
        (artifacts / f"{mode}-events.jsonl").write_text(
            result.stdout + "\n", encoding="utf-8"
        )
        _retrieve_tree(vm.serial, remote, artifacts / "guest-file-evidence")
        if result.returncode != 0:
            raise TestFailure(
                f"Desktop file probe {mode!r} failed:\n" + result.stdout[-8000:]
            )
        validated = validator(result.stdout)
        frame = vm.screenshot(mode)
        if thumbnail_name is not None:
            cache_path = validated.get("cache_path")
            if not isinstance(cache_path, str):
                raise TestFailure("Thumbnail event returned no safe cache path")
            thumbnail = artifacts / thumbnail_name
            _retrieve_file(vm.serial, cache_path, thumbnail)
            if not thumbnail.is_file():
                raise TestFailure("The guest thumbnail could not be retrieved")
            assert_fixture_quadrants(
                thumbnail,
                artifacts / f"{Path(thumbnail_name).stem}-analysis.json",
            )
        if require_visible_fixture:
            assert_fixture_quadrants(
                frame,
                artifacts / f"{mode}-screen-analysis.json",
            )
        vm.qmp.send_key("alt-f4")
        time.sleep(1)
        self._assert_scoped_journal(
            vm,
            base,
            cursors,
            artifacts,
            scope=mode,
        )
        return validated

    def _exercise_image_thumbnail(
        self, vm: QemuVm, base: PromotedBase, artifacts: Path
    ) -> None:
        self._run_file_driver(
            vm,
            base,
            artifacts,
            mode="file-image-thumbnail",
            validator=lambda output: _validate_thumbnail_events(
                output, "AnduinOS-Image.png", self.username
            ),
            thumbnail_name="image-thumbnail.png",
        )

    def _exercise_video_thumbnail(
        self, vm: QemuVm, base: PromotedBase, artifacts: Path
    ) -> None:
        self._run_file_driver(
            vm,
            base,
            artifacts,
            mode="file-video-thumbnail",
            validator=lambda output: _validate_thumbnail_events(
                output, "AnduinOS-Video.mp4", self.username
            ),
            thumbnail_name="video-thumbnail.png",
        )

    def _exercise_image_open(
        self, vm: QemuVm, base: PromotedBase, artifacts: Path
    ) -> None:
        self._run_file_driver(
            vm,
            base,
            artifacts,
            mode="file-image-open",
            validator=_validate_image_open_events,
            require_visible_fixture=True,
        )

    def _exercise_video_open(
        self, vm: QemuVm, base: PromotedBase, artifacts: Path
    ) -> None:
        self._run_file_driver(
            vm,
            base,
            artifacts,
            mode="file-video-open",
            validator=_validate_video_open_events,
        )

    def _exercise_deb_software(
        self, vm: QemuVm, base: PromotedBase, artifacts: Path
    ) -> None:
        self._run_file_driver(
            vm,
            base,
            artifacts,
            mode="file-deb-software",
            validator=_validate_deb_software_events,
        )

    def _exercise_chinese_editor(
        self, vm: QemuVm, base: PromotedBase, artifacts: Path
    ) -> None:
        expected = "变角次亮采之门"
        assert vm.qmp is not None
        framebuffer = vm.qmp.framebuffer_size()
        if framebuffer != (1280, 800):
            raise TestFailure(
                "The Text Editor Save-row probe requires the acceptance "
                f"framebuffer to be 1280x800, observed {framebuffer[0]}x{framebuffer[1]}"
            )
        self._run_file_driver(
            vm,
            base,
            artifacts,
            mode="file-chinese-editor",
            validator=_validate_chinese_editor_events,
            text_inputs={
                f"chinese-editor-unicode-{index}-codepoint": f"{ord(character):x}"
                for index, character in enumerate(expected)
            },
        )

    def _exercise_super_u(
        self,
        vm: QemuVm,
        base: PromotedBase,
        artifacts: Path,
    ) -> None:
        """Prove Super+U exposes Network Stats and restores its initial state."""

        self._run_shell_driver(
            vm,
            base,
            artifacts,
            mode="shortcut-super-u",
            validator=_validate_super_u_events,
        )

    def _exercise_screenshot_shortcut(
        self,
        vm: QemuVm,
        base: PromotedBase,
        artifacts: Path,
    ) -> None:
        """Prove Super+Shift+S creates a real, decodable PNG screenshot."""

        event = self._run_shell_driver(
            vm,
            base,
            artifacts,
            mode="shortcut-screenshot",
            validator=_validate_screenshot_shortcut_events,
        )
        assert vm.serial is not None
        remote_path = event["path"]
        assert isinstance(remote_path, str)
        screenshot = artifacts / "shortcut-screenshot-created.png"
        _retrieve_file(vm.serial, remote_path, screenshot)
        if not screenshot.is_file() or screenshot.stat().st_size <= 1024:
            raise TestFailure(
                "The screenshot shortcut reported a PNG that the host could not retrieve"
            )
        try:
            with Image.open(screenshot) as image:
                if image.format != "PNG" or min(image.size) < 100:
                    raise TestFailure(
                        "The screenshot shortcut produced an implausible PNG image"
                    )
                image.verify()
        except (OSError, UnidentifiedImageError) as error:
            raise TestFailure(
                f"The screenshot shortcut produced an invalid PNG: {error}"
            ) from error

    def _exercise_tty6_branding(
        self,
        vm: QemuVm,
        base: PromotedBase,
        artifacts: Path,
    ) -> None:
        """Switch to the real tty6, inspect its visible cells, and return."""

        assert vm.serial is not None and vm.qmp is not None
        cursors = self._journal_cursors(vm)
        before = vm.serial.run(
            _graphical_vt_probe_command(self.username),
            timeout=60,
            check=False,
        )
        (artifacts / "tty6-before.txt").write_text(
            before.stdout + "\n", encoding="utf-8"
        )
        previous_vt = _validate_graphical_vt_evidence(
            before.stdout,
            before.returncode,
        )
        if previous_vt == 6:
            raise TestFailure("GNOME unexpectedly occupied tty6 before the shortcut")
        vm.screenshot("tty6-before")

        primary_error: BaseException | None = None
        restore_error: BaseException | None = None
        try:
            vm.qmp.send_key("ctrl-alt-f6")
            console = vm.serial.run(
                _tty6_probe_command(),
                timeout=60,
                check=False,
            )
            (artifacts / "tty6-console.txt").write_text(
                console.stdout + "\n", encoding="utf-8"
            )
            _validate_tty6_evidence(console.stdout, console.returncode)
            vm.screenshot("tty6-visible")
        except BaseException as error:
            primary_error = error
        finally:
            # A failed branding assertion must not strand later independent
            # checks on a text console. Return to the exact VT which owned the
            # active Wayland session rather than assuming that it is tty2.
            try:
                vm.qmp.send_key(f"ctrl-alt-f{previous_vt}")
                restored = vm.serial.run(
                    _graphical_vt_probe_command(
                        self.username,
                        wait_for=previous_vt,
                    ),
                    timeout=60,
                    check=False,
                )
                (artifacts / "tty6-restored.txt").write_text(
                    restored.stdout + "\n", encoding="utf-8"
                )
                _validate_graphical_vt_evidence(
                    restored.stdout,
                    restored.returncode,
                    expected_vt=previous_vt,
                )
                if _graphical_user(vm.serial) != self.username:
                    raise TestFailure(
                        "The original graphical user did not survive the tty6 round trip"
                    )
                vm.screenshot("tty6-restored")
            except BaseException as error:
                restore_error = error

        if primary_error is not None:
            if restore_error is not None:
                primary_error.add_note(
                    "Returning from tty6 also failed: "
                    f"{type(restore_error).__name__}: {restore_error}"
                )
            raise primary_error
        if restore_error is not None:
            raise restore_error
        self._assert_scoped_journal(
            vm,
            base,
            cursors,
            artifacts,
            scope="tty6-branding",
        )

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
                )
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

    def _exercise_spotify_public(
        self,
        vm: QemuVm,
        base: PromotedBase,
        artifacts: Path,
    ) -> None:
        """Refresh Flathub, then open its current Spotify details in Software."""

        assert vm.serial is not None
        catalog = vm.serial.run(
            _spotify_public_catalog_command(),
            timeout=900,
            check=False,
        )
        (artifacts / "spotify-public-catalog.txt").write_text(
            catalog.stdout + "\n", encoding="utf-8"
        )
        try:
            _validate_spotify_public_catalog_evidence(
                catalog.stdout,
                catalog.returncode,
            )
        except TestFailure as error:
            try:
                classification = _last_value(
                    catalog.stdout,
                    "spotify-public-failure-class",
                )
            except TestFailure:
                classification = "product-regression"
            if classification not in {"external-catalog", "product-regression"}:
                classification = "product-regression"
            (artifacts / "spotify-public-classification.txt").write_text(
                f"classification={classification}\nphase=catalog\n",
                encoding="utf-8",
            )
            raise TestFailure(f"[{classification}] {error}") from error

        reload_result = vm.serial.run(
            _desktop_command(
                self.username,
                (
                    "bash",
                    "-lc",
                    "set -euo pipefail; "
                    "systemctl --user stop gnome-software.service; "
                    "systemctl --user start gnome-software.service; "
                    "for _ in $(seq 1 60); do "
                    "systemctl --user is-active --quiet gnome-software.service "
                    "&& break; sleep 1; done; "
                    "systemctl --user is-active gnome-software.service; "
                    "printf 'spotify-public-software-reload=passed\\n'",
                ),
            ),
            timeout=120,
            check=False,
        )
        (artifacts / "spotify-public-software-reload.txt").write_text(
            reload_result.stdout + "\n", encoding="utf-8"
        )
        if (
            reload_result.returncode != 0
            or _last_value(
                reload_result.stdout,
                "spotify-public-software-reload",
            )
            != "passed"
        ):
            (artifacts / "spotify-public-classification.txt").write_text(
                "classification=product-regression\nphase=software-reload\n",
                encoding="utf-8",
            )
            raise TestFailure(
                "[product-regression] GNOME Software did not reload after the "
                "public AppStream refresh:\n"
                + reload_result.stdout[-8000:]
            )

        try:
            self._run_shell_driver(
                vm,
                base,
                artifacts,
                mode="shell-spotify-store",
                validator=_validate_spotify_store_events,
                text_inputs={"spotify-search-text": "Spotify"},
            )
        except TestFailure as error:
            (artifacts / "spotify-public-classification.txt").write_text(
                "classification=product-regression\nphase=desktop-ui\n",
                encoding="utf-8",
            )
            raise TestFailure(
                "[product-regression] the current public catalog resolved Spotify, "
                "but ArcMenu/GNOME Software could not open its details page: "
                f"{error}"
            ) from error
        (artifacts / "spotify-public-classification.txt").write_text(
            "classification=none\nphase=passed\n",
            encoding="utf-8",
        )

    def _exercise_wechat_install(
        self,
        vm: QemuVm,
        base: PromotedBase,
        artifacts: Path,
    ) -> None:
        """Install current native WeChat and launch it from the real start menu."""

        assert vm.serial is not None
        installed = vm.serial.run(
            _wechat_install_command(),
            timeout=1800,
            check=False,
        )
        (artifacts / "wechat-install.txt").write_text(
            installed.stdout + "\n", encoding="utf-8"
        )
        try:
            _validate_wechat_install_evidence(installed.stdout, installed.returncode)
        except TestFailure as error:
            classification = _safe_failure_class(
                installed.stdout,
                "wechat-failure-class",
                {"external-catalog", "external-artifact", "product-regression"},
            )
            (artifacts / "wechat-classification.txt").write_text(
                f"classification={classification}\nphase=install\n",
                encoding="utf-8",
            )
            raise TestFailure(f"[{classification}] {error}") from error

        try:
            self._run_shell_driver(
                vm,
                base,
                artifacts,
                mode="public-wechat-install",
                validator=_validate_wechat_install_events,
                text_inputs={"wechat-search-text": "WeChat"},
                screenshot_validator=lambda frame, evidence: (
                    assert_wechat_login_window(
                        frame,
                        artifacts / "wechat-login-window-analysis.json",
                        evidence,
                    )
                ),
            )
        except TestFailure as error:
            (artifacts / "wechat-classification.txt").write_text(
                "classification=product-regression\nphase=launch\n",
                encoding="utf-8",
            )
            raise TestFailure(
                "[product-regression] WeChat installed successfully but did not "
                f"launch from ArcMenu: {error}"
            ) from error
        (artifacts / "wechat-classification.txt").write_text(
            "classification=none\nphase=launched\n",
            encoding="utf-8",
        )

    def _exercise_wechat_tray(
        self,
        vm: QemuVm,
        base: PromotedBase,
        artifacts: Path,
    ) -> None:
        """Close WeChat to its lower-right indicator and restore the same app."""

        try:
            self._run_shell_driver(
                vm,
                base,
                artifacts,
                mode="public-wechat-tray",
                validator=_validate_wechat_tray_events,
                screenshot_validator=lambda frame, evidence: (
                    assert_wechat_login_window(
                        frame,
                        artifacts / "wechat-restored-window-analysis.json",
                        evidence,
                    )
                ),
            )
        except TestFailure as error:
            (artifacts / "wechat-tray-classification.txt").write_text(
                "classification=product-regression\nphase=tray-roundtrip\n",
                encoding="utf-8",
            )
            raise TestFailure(
                "[product-regression] WeChat did not preserve and restore its "
                f"process through the lower-right AppIndicator: {error}"
            ) from error
        (artifacts / "wechat-tray-classification.txt").write_text(
            "classification=none\nphase=passed\n",
            encoding="utf-8",
        )

    def _exercise_nextcloud_ppa(
        self,
        vm: QemuVm,
        base: PromotedBase,
        artifacts: Path,
    ) -> None:
        """Add the public Nextcloud PPA through the installed user's sudo."""

        assert vm.serial is not None
        sudoers = "/etc/sudoers.d/anduinos-acceptance-nextcloud-ppa"
        rule = (
            f"{self.username} ALL=(root) NOPASSWD: "
            "/usr/bin/add-apt-repository -y "
            r"ppa\:nextcloud-devs/client"
        )
        payload = base64.b64encode((rule + "\n").encode("utf-8")).decode("ascii")
        setup = vm.serial.run(
            "set -euo pipefail\n"
            "command -v add-apt-repository\n"
            "dpkg-query -W software-properties-common\n"
            f"printf '%s' {shlex.quote(payload)} | base64 -d > {sudoers}\n"
            f"chmod 0440 {sudoers}\n"
            f"visudo -cf {sudoers}\n"
            "printf 'nextcloud-ppa-sudo-policy=ready\\n'",
            timeout=60,
            check=False,
        )
        (artifacts / "nextcloud-ppa-preflight.txt").write_text(
            setup.stdout + "\n", encoding="utf-8"
        )
        if setup.returncode != 0:
            raise TestFailure(
                "Could not prepare the exact Nextcloud PPA sudo command:\n"
                + setup.stdout[-8000:]
            )

        cursors = self._journal_cursors(vm)
        command = None
        source = None
        cleanup = None
        try:
            command = vm.serial.run(
                _desktop_command(
                    self.username,
                    (
                        "bash",
                        "-lc",
                        "set -euo pipefail; "
                        "printf 'invoking-user=%s\\n' \"$(id -un)\"; "
                        "printf '%s\\n' "
                        "'command=sudo add-apt-repository -y "
                        "ppa:nextcloud-devs/client'; "
                        "sudo -n /usr/bin/add-apt-repository -y "
                        "ppa:nextcloud-devs/client; "
                        "printf 'repository-command=passed\\n'",
                    ),
                ),
                timeout=600,
                check=False,
            )
            (artifacts / "nextcloud-ppa-command.txt").write_text(
                command.stdout + "\n", encoding="utf-8"
            )
            source = vm.serial.run(
                _nextcloud_ppa_source_probe_command(),
                timeout=120,
                check=False,
            )
            (artifacts / "nextcloud-ppa-source.txt").write_text(
                source.stdout + "\n", encoding="utf-8"
            )
        finally:
            cleanup = vm.serial.run(
                f"rm -f {sudoers}; "
                f"test ! -e {sudoers}; "
                "printf 'nextcloud-ppa-sudo-policy=removed\\n'",
                timeout=30,
                check=False,
            )
            (artifacts / "nextcloud-ppa-cleanup.txt").write_text(
                cleanup.stdout + "\n", encoding="utf-8"
            )

        assert command is not None and source is not None and cleanup is not None
        evidence = "\n".join((command.stdout, source.stdout, cleanup.stdout))
        _validate_nextcloud_ppa_evidence(
            evidence,
            command.returncode or source.returncode or cleanup.returncode,
            self.username,
        )
        self._assert_scoped_journal(
            vm,
            base,
            cursors,
            artifacts,
            scope="nextcloud-ppa",
        )

    def _exercise_public_cpu_z(
        self,
        vm: QemuVm,
        base: PromotedBase,
        artifacts: Path,
    ) -> None:
        """Download, preview, and dispatch the pinned real CPU-Z executable."""

        assert vm.serial is not None and vm.qmp is not None
        remote = "/run/anduinos-feature-public-cpuz"
        vm.serial.run(
            f"install -d -m 0777 {shlex.quote(remote + '/evidence')}",
            timeout=30,
        )
        vm.serial.upload(self.driver, f"{remote}/atspi_driver.py", 0o755)

        downloaded = vm.serial.run(
            _desktop_command(
                self.username,
                ("bash", "-lc", _cpu_z_download_command()),
            ),
            timeout=600,
            check=False,
        )
        (artifacts / "cpu-z-download.txt").write_text(
            downloaded.stdout + "\n", encoding="utf-8"
        )
        _validate_cpu_z_download_evidence(downloaded.stdout, downloaded.returncode)

        cursors = self._journal_cursors(vm)
        command = _desktop_command(
            self.username,
            (
                "python3",
                f"{remote}/atspi_driver.py",
                "public-cpuz-file",
                "--filename",
                _CPU_Z_MEMBER,
                "--evidence",
                f"{remote}/evidence",
            ),
        )
        result = _run_with_qmp_key_requests(
            vm,
            command,
            timeout=300,
            request_trace=artifacts / "cpu-z-qmp-requests.jsonl",
        )
        (artifacts / "cpu-z-events.jsonl").write_text(
            result.stdout + "\n", encoding="utf-8"
        )
        _retrieve_tree(vm.serial, remote, artifacts / "guest-cpu-z-evidence")
        if result.returncode != 0:
            raise TestFailure(
                "The real CPU-Z Nautilus workflow failed:\n"
                + result.stdout[-8000:]
            )
        evidence = _validate_cpu_z_events(result.stdout, self.username)
        cache_path = evidence["cache_path"]
        assert isinstance(cache_path, str)
        thumbnail = artifacts / "cpu-z-thumbnail.png"
        _retrieve_file(vm.serial, cache_path, thumbnail)
        assert_cpu_z_thumbnail(
            thumbnail,
            artifacts / "cpu-z-thumbnail-analysis.json",
        )
        vm.screenshot("cpu-z-exe-runner-prerequisite")
        vm.qmp.send_key("alt-f4")
        time.sleep(1)
        self._assert_scoped_journal(
            vm,
            base,
            cursors,
            artifacts,
            scope="public-cpu-z",
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
        vm.serial.upload(self.driver, f"{fixture}/atspi_driver.py", 0o755)
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
        vm.serial.upload(self.driver, f"{remote}/atspi_driver.py", 0o755)
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

    def _prepare_account_fixture(self, vm: QemuVm) -> str:
        assert vm.serial is not None
        remote = "/run/anduinos-feature-accounts"
        vm.serial.run(f"install -d -m 0777 {remote}/evidence")
        vm.serial.upload(self.driver, f"{remote}/atspi_driver.py", 0o755)
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
        gdm = self._gdm_user(vm)
        command = _desktop_command(
            gdm,
            (
                "python3",
                f"{remote}/atspi_driver.py",
                "gdm-select-user",
                "--account",
                account,
                "--full-name",
                full_name,
                "--evidence",
                f"{remote}/evidence/gdm-{label}",
            ),
        )
        result = _run_with_qmp_key_requests(
            vm,
            command,
            timeout=120,
            secret_texts={"gdm-password": password},
        )
        (artifacts / f"gdm-{label}-events.jsonl").write_text(
            result.stdout + "\n", encoding="utf-8"
        )
        _retrieve_tree(vm.serial, remote, artifacts / "guest-account-evidence")
        if result.returncode != 0:
            raise TestFailure(
                f"Could not select and authenticate GDM account {account}:\n"
                + result.stdout[-8000:]
            )
        _validate_gdm_login_events(result.stdout, account, full_name)

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
        probe = (
            "for user in gdm-greeter gdm; do "
            "uid=$(id -u \"$user\" 2>/dev/null) || continue; "
            "runtime=/run/user/$uid; "
            "test -S \"$runtime/bus\" || continue; "
            "find \"$runtime\" -maxdepth 1 -type s -name 'wayland-[0-9]*' "
            "2>/dev/null | grep -q . || continue; "
            "printf '%s\\n' \"$user\"; exit 0; "
            "done; exit 1"
        )
        while time.monotonic() < deadline:
            result = vm.serial.run(probe, timeout=30, check=False)
            if result.returncode == 0 and result.stdout.strip():
                return result.stdout.strip().splitlines()[-1]
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

    def _exercise_btrfs_rollback(
        self,
        vm: QemuVm,
        base: PromotedBase,
        artifacts: Path,
    ) -> None:
        """Install Docker after a real snapshot, restore it, and boot twice."""

        assert vm.serial is not None and vm.qmp is not None
        title = "AnduinOS acceptance before Docker"
        root_sentinel = "/etc/anduinos-acceptance-after-snapshot"
        home_sentinel = f"/home/{self.username}/anduinos-acceptance-user-data"
        remote = "/run/anduinos-feature-btrfs"
        vm.serial.run(f"install -d -m 0777 {remote}/evidence")
        vm.serial.upload(self.driver, f"{remote}/atspi_driver.py", 0o755)

        precondition = vm.serial.run(
            "set -euo pipefail\n"
            "test \"$(findmnt -n -o FSTYPE /)\" = btrfs\n"
            "test \"$(findmnt -n -o FSROOT /)\" = /@root\n"
            "! dpkg-query -W -f='${db:Status-Abbrev}' docker.io 2>/dev/null "
            "| grep -q '^ii '\n"
            "test ! -e /usr/bin/docker\n"
            "anduinos-btrfs-snapshots-manager-cli status --json\n"
            "btrfs subvolume show /\n"
            "btrfs subvolume list /\n",
            timeout=120,
        )
        (artifacts / "btrfs-before.txt").write_text(
            precondition.stdout + "\n", encoding="utf-8"
        )

        key = self._prepare_power_control(vm, artifacts, remote)

        created = vm.serial.run(
            "anduinos-btrfs-snapshots-manager-cli create --json "
            f"{shlex.quote(title)} "
            f"{shlex.quote('Acceptance baseline before installing docker.io')}",
            timeout=300,
        )
        (artifacts / "btrfs-snapshot-created.json").write_text(
            created.stdout + "\n", encoding="utf-8"
        )
        deployment = _json_object(created.stdout)
        deployment_id = str(deployment.get("id") or deployment.get("deployment_id") or "")
        if not deployment_id:
            raise TestFailure("Snapshot manager did not return a deployment ID")
        verified = vm.serial.run(
            "anduinos-btrfs-snapshots-manager-cli verify "
            f"{shlex.quote(deployment_id)} --json",
            timeout=300,
        )
        (artifacts / "btrfs-snapshot-verified.json").write_text(
            verified.stdout + "\n", encoding="utf-8"
        )

        changed = vm.serial.run(
            "set -euo pipefail\n"
            "export DEBIAN_FRONTEND=noninteractive\n"
            "apt-get install --yes docker.io\n"
            "dpkg-query -W -f='${db:Status-Abbrev} ${Package} ${Version}\\n' "
            "docker.io | grep '^ii '\n"
            "test -x /usr/bin/docker\n"
            "systemctl enable --now docker.service\n"
            "systemctl is-active --quiet docker.service\n"
            f"printf 'root changes must roll back\\n' > {root_sentinel}\n"
            f"printf 'home data must survive\\n' > {home_sentinel}\n"
            f"chown {shlex.quote(self.username)}:{shlex.quote(self.username)} "
            f"{home_sentinel}\n"
            f"test -f {root_sentinel}\n"
            f"test -f {home_sentinel}\n",
            timeout=1200,
        )
        (artifacts / "btrfs-after-docker-install.txt").write_text(
            changed.stdout + "\n", encoding="utf-8"
        )

        arm = _desktop_command(
            self.username,
            (
                "python3",
                f"{remote}/atspi_driver.py",
                "snapshot-restore-arm",
                "--expected",
                title,
                "--evidence",
                f"{remote}/evidence",
            ),
        )
        armed = _run_with_qmp_key_requests(
            vm,
            arm,
            timeout=300,
            secret_text=self.password,
        )
        (artifacts / "btrfs-restore-atspi-events.jsonl").write_text(
            armed.stdout + "\n", encoding="utf-8"
        )
        _retrieve_tree(vm.serial, remote, artifacts / "guest-btrfs-evidence")
        if armed.returncode != 0:
            raise TestFailure(
                "The real snapshot-manager UI could not arm the selected restore:\n"
                + armed.stdout[-8000:]
            )

        # The UI has proved that the exact transaction is armed. Trigger an
        # ordinary systemd reboot through the pre-snapshot, least-privilege
        # control channel; do not boot a debug kernel or manipulate subvolumes.
        # QEMU's -no-reboot turns that guest reboot into a process exit, making
        # the product-owned GRUB/initramfs recovery boot explicit and observable.
        self.phase_callback(base.scenario.id, "btrfs-rollback", "Rebooting into armed rollback")
        reboot_request = self._ssh(
            vm,
            key,
            "sudo -n /usr/local/sbin/anduinos-acceptance-reboot",
        )
        (artifacts / "btrfs-rollback-reboot-request.txt").write_text(
            reboot_request + "\n", encoding="utf-8"
        )
        self._wait_for_power_transition(
            vm,
            key,
            artifacts,
            "btrfs-rollback-reboot",
            # systemd's default stop timeout alone is 90 seconds.  The
            # delayed request and the final firmware reset need their own
            # margin; cutting QEMU off at 90 seconds can manufacture a
            # failure immediately before systemd kills a stuck service.
            timeout=150,
        )
        vm.stop()
        vm.start(attach_iso=False, phase="rollback-apply")
        self._ssh_eventually(
            vm,
            key,
            self._graphical_boot_ready_command(),
            timeout=self.options.boot_timeout_seconds * 2,
        )
        first_boot = self._ssh(
            vm,
            key,
            self._rollback_health_command(
                root_sentinel,
                home_sentinel,
                deployment_id,
            ),
            timeout=300,
        )
        _validate_rollback_health(first_boot)
        (artifacts / "btrfs-after-rollback-first-boot.txt").write_text(
            first_boot + "\n", encoding="utf-8"
        )
        first_boot_id = _last_value(
            self._ssh(
                vm,
                key,
                "printf 'boot-id=%s\\n' \"$(cat /proc/sys/kernel/random/boot_id)\"",
            ),
            "boot-id",
        )

        self.phase_callback(base.scenario.id, "btrfs-rollback", "Performing ordinary reboot")
        second_reboot_request = self._ssh(
            vm,
            key,
            "sudo -n /usr/local/sbin/anduinos-acceptance-reboot",
        )
        (artifacts / "btrfs-ordinary-reboot-request.txt").write_text(
            second_reboot_request + "\n", encoding="utf-8"
        )
        self._wait_for_power_transition(
            vm,
            key,
            artifacts,
            "btrfs-ordinary-reboot",
            timeout=150,
        )
        vm.stop()
        vm.start(attach_iso=False, phase="rollback-second-boot")
        self._ssh_eventually(
            vm,
            key,
            self._graphical_boot_ready_command(),
            timeout=self.options.boot_timeout_seconds,
        )
        second_boot = self._ssh(
            vm,
            key,
            self._rollback_health_command(
                root_sentinel,
                home_sentinel,
                deployment_id,
            ),
            timeout=300,
        )
        _validate_rollback_health(second_boot)
        second_boot_id = _last_value(
            self._ssh(
                vm,
                key,
                "printf 'boot-id=%s\\n' \"$(cat /proc/sys/kernel/random/boot_id)\"",
            ),
            "boot-id",
        )
        _validate_distinct_boot_ids(first_boot_id, second_boot_id)
        (artifacts / "btrfs-after-rollback-second-boot.txt").write_text(
            second_boot + f"\nfirst-boot-id={first_boot_id}\n"
            f"second-boot-id={second_boot_id}\n",
            encoding="utf-8",
        )
        status = self._ssh(
            vm,
            key,
            "sudo -n /usr/local/sbin/anduinos-acceptance-rollback-state "
            + shlex.quote(deployment_id),
            timeout=180,
        )
        (artifacts / "btrfs-rollback-state.txt").write_text(
            status + "\n", encoding="utf-8"
        )

        # Prove the post-rollback graphical system, not merely sshd, is usable.
        vm.qmp.send_key("ret")
        time.sleep(1)
        vm.qmp.type_text(self.password, interval=0.06)
        vm.qmp.send_key("ret")
        graphical = self._ssh_eventually(
            vm,
            key,
            "set -e; systemctl is-active --quiet graphical.target; "
            "systemctl is-active --quiet gdm; "
            "loginctl list-sessions --no-legend | while read -r session rest; do "
            "test \"$(loginctl show-session \"$session\" -p Type --value)\" = wayland "
            "&& loginctl show-session \"$session\" -p Name --value; done | "
            f"grep -Fx {shlex.quote(self.username)}",
            timeout=120,
        )
        (artifacts / "btrfs-rollback-graphical-session.txt").write_text(
            graphical + "\n", encoding="utf-8"
        )
        vm.screenshot("btrfs-rollback-installed-gnome")
        poweroff_request = self._ssh(
            vm,
            key,
            "sudo -n /usr/local/sbin/anduinos-acceptance-poweroff",
        )
        (artifacts / "btrfs-poweroff-request.txt").write_text(
            poweroff_request + "\n", encoding="utf-8"
        )
        self._wait_for_power_transition(
            vm,
            key,
            artifacts,
            "btrfs-final-poweroff",
            timeout=150,
        )
        vm.stop()

    def _prepare_power_control(
        self,
        vm: QemuVm,
        artifacts: Path,
        remote: str,
    ) -> Path:
        """Install an overlay-local, least-privilege reboot control channel."""

        assert vm.serial is not None
        key = artifacts / "control-key"
        subprocess.run(
            ("ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-f", str(key)),
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            text=True,
            timeout=30,
        )
        vm.serial.upload(key.with_suffix(".pub"), f"{remote}/control-key.pub", 0o644)
        vm.serial.upload(
            self.btrfs_rollback_oracle,
            f"{remote}/btrfs_rollback_oracle.py",
            0o644,
        )
        vm.serial.run(
            "set -euo pipefail\n"
            f"home=$(getent passwd {shlex.quote(self.username)} | cut -d: -f6)\n"
            f"install -d -m 0700 -o {shlex.quote(self.username)} "
            f"-g {shlex.quote(self.username)} \"$home/.ssh\"\n"
            f"cat {remote}/control-key.pub >> \"$home/.ssh/authorized_keys\"\n"
            f"chown {shlex.quote(self.username)}:{shlex.quote(self.username)} "
            "\"$home/.ssh/authorized_keys\"\n"
            "chmod 0600 \"$home/.ssh/authorized_keys\"\n"
            "cat > /usr/local/sbin/anduinos-acceptance-reboot <<'EOF'\n"
            "#!/bin/sh\n"
            "set -eu\n"
            # The controlled boot uses systemd.debug_shell=ttyS*.  That unit
            # deliberately has no shutdown dependencies and IgnoreOnIsolate,
            # so it is not part of the product's ordinary reboot contract.
            "systemctl stop debug-shell.service 2>/dev/null || true\n"
            "exec /usr/bin/systemd-run --unit=anduinos-acceptance-reboot "
            "--on-active=2s /usr/bin/systemctl --no-block "
            "--check-inhibitors=no reboot\n"
            "EOF\n"
            "cat > /usr/local/sbin/anduinos-acceptance-poweroff <<'EOF'\n"
            "#!/bin/sh\n"
            "set -eu\n"
            "systemctl stop debug-shell.service 2>/dev/null || true\n"
            "exec /usr/bin/systemd-run --unit=anduinos-acceptance-poweroff "
            "--on-active=2s /usr/bin/systemctl --no-block "
            "--check-inhibitors=no poweroff\n"
            "EOF\n"
            "cat > /usr/local/sbin/anduinos-acceptance-package-health <<'EOF'\n"
            "#!/bin/sh\n"
            "set -eu\n"
            "test -z \"$(dpkg --audit)\"\n"
            "apt-get check\n"
            "printf 'dpkg=ok\\napt=ok\\n'\n"
            "EOF\n"
            "cat > /usr/local/sbin/anduinos-acceptance-boot-health <<'EOF'\n"
            "#!/bin/sh\n"
            "set -eu\n"
            "test -s /boot/grub/grub.cfg\n"
            "grub-script-check /boot/grub/grub.cfg\n"
            "kernel=$(readlink -f /boot/vmlinuz)\n"
            "initrd=$(readlink -f /boot/initrd.img)\n"
            "test -s \"$kernel\"\n"
            "test -s \"$initrd\"\n"
            "lsinitramfs \"$initrd\" >/dev/null\n"
            "printf 'boot-artifacts=ok\\n'\n"
            "EOF\n"
            "install -d -m 0755 /usr/local/lib/anduinos-acceptance\n"
            f"install -m 0755 {remote}/btrfs_rollback_oracle.py "
            "/usr/local/lib/anduinos-acceptance/btrfs_rollback_oracle.py\n"
            "btrfs subvolume get-default / > "
            "/usr/local/lib/anduinos-acceptance/btrfs-default.expected\n"
            "cat > /usr/local/sbin/anduinos-acceptance-rollback-state <<'EOF'\n"
            "#!/bin/bash\n"
            "set -euo pipefail\n"
            "test \"$#\" -eq 1\n"
            "expected_target=$1\n"
            "[[ \"$expected_target\" =~ ^[0-9a-f]{8}-[0-9a-f]{4}-"
            "[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$ ]]\n"
            "test \"$(findmnt -n -o FSTYPE /)\" = btrfs\n"
            "test \"$(findmnt -n -o FSROOT /)\" = /@root\n"
            "expected_default=$(cat "
            "/usr/local/lib/anduinos-acceptance/btrfs-default.expected)\n"
            "observed_default=$(btrfs subvolume get-default /)\n"
            "test \"$observed_default\" = \"$expected_default\"\n"
            "printf 'btrfs-default-subvolume=unchanged\\n'\n"
            "root_details=$(btrfs subvolume show --raw /)\n"
            "printf '%s\\n' \"$root_details\"\n"
            "printf '%s\\n' \"$root_details\" | "
            "grep -Eq '^[[:space:]]*Name:[[:space:]]+@root$'\n"
            "subvolumes=$(btrfs subvolume list /)\n"
            "printf '%s\\n' \"$subvolumes\"\n"
            "! printf '%s\\n' \"$subvolumes\" | "
            "grep -Eq '@root\\.snapshots-manager-(old|new)-'\n"
            "printf 'btrfs-staging-roots=absent\\n'\n"
            "standard_env=$(grub-editenv /boot/grub/grubenv list)\n"
            "! printf '%s\\n' \"$standard_env\" | "
            "grep -Eq '^(recordfail|menu_show_once)='\n"
            "recovery_env=/boot/efi/EFI/anduinos/btrfs-snapshots-manager-grubenv\n"
            "test -s \"$recovery_env\"\n"
            "recovery_selection=$(grub-editenv \"$recovery_env\" list)\n"
            "test -z \"$recovery_selection\"\n"
            "printf 'recovery-grubenv=empty\\n'\n"
            "unit=anduinos-btrfs-snapshots-manager-confirm.service\n"
            "test \"$(systemctl show \"$unit\" -p Result --value)\" = success\n"
            "test \"$(systemctl show \"$unit\" -p ExecMainStatus --value)\" = 0\n"
            "printf 'confirm-service=success\\n'\n"
            "/usr/bin/python3 "
            "/usr/local/lib/anduinos-acceptance/btrfs_rollback_oracle.py "
            "\"$expected_target\"\n"
            "journalctl -b -u \"$unit\" --no-pager\n"
            "EOF\n"
            "chmod 0755 /usr/local/sbin/anduinos-acceptance-reboot "
            "/usr/local/sbin/anduinos-acceptance-poweroff "
            "/usr/local/sbin/anduinos-acceptance-package-health "
            "/usr/local/sbin/anduinos-acceptance-boot-health "
            "/usr/local/sbin/anduinos-acceptance-rollback-state\n"
            f"printf '%s ALL=(root) NOPASSWD: "
            f"/usr/local/sbin/anduinos-acceptance-reboot, "
            f"/usr/local/sbin/anduinos-acceptance-poweroff, "
            f"/usr/local/sbin/anduinos-acceptance-package-health, "
            f"/usr/local/sbin/anduinos-acceptance-boot-health, "
            f"/usr/local/sbin/anduinos-acceptance-rollback-state\\n' "
            f"{shlex.quote(self.username)} "
            "> /etc/sudoers.d/anduinos-acceptance-power\n"
            "chmod 0440 /etc/sudoers.d/anduinos-acceptance-power\n"
            "visudo -cf /etc/sudoers.d/anduinos-acceptance-power\n"
            # This is an overlay-local harness channel, not a product SSH
            # assertion.  A persistent service is intentional here: QEMU's
            # host forwarding accepts a TCP connection even while a restored
            # guest has no listener, which can make a socket-activation probe
            # block during the recovery boot.  The dedicated service and key
            # are both captured by the pre-mutation snapshot and discarded
            # with the feature overlay.
            "systemctl enable --now ssh.service\n",
            timeout=60,
        )
        self._ssh_eventually(vm, key, "id -un | grep -Fx " + shlex.quote(self.username))
        return key

    def _wait_for_power_transition(
        self,
        vm: QemuVm,
        key: Path,
        artifacts: Path,
        label: str,
        *,
        timeout: float,
    ) -> None:
        """Wait for QEMU exit and retain systemd state if shutdown stalls."""

        if vm.process is None:
            raise TestFailure("Power transition was requested before QEMU started")
        deadline = time.monotonic() + timeout
        diagnostic_at = time.monotonic() + min(15.0, timeout / 3)
        diagnostic_path = artifacts / f"{label}-diagnostics.txt"
        diagnostic_written = False
        while time.monotonic() < deadline:
            if vm.process.poll() is not None:
                return
            if not diagnostic_written and time.monotonic() >= diagnostic_at:
                diagnostic_written = True
                output = self._collect_power_transition_diagnostics(vm, key)
                diagnostic_path.write_text(output + "\n", encoding="utf-8")
            time.sleep(0.5)
        if not diagnostic_written:
            diagnostic_path.write_text(
                "QEMU remained alive but the diagnostic collection deadline "
                "was not reached.\n",
                encoding="utf-8",
            )
        raise TestFailure(
            f"Guest {label.replace('-', ' ')} did not stop QEMU within "
            f"{timeout:.0f} seconds; see {diagnostic_path.name}"
        )

    def _collect_power_transition_diagnostics(self, vm: QemuVm, key: Path) -> str:
        """Collect shutdown state over serial first, because sshd stops early."""

        command = (
            "set +e; "
            "date --iso-8601=seconds; uptime; "
            "printf '\\n== system state ==\\n'; "
            "systemctl is-system-running; "
            "systemctl show -p ActiveState -p SubState -p Job "
            "reboot.target poweroff.target shutdown.target final.target; "
            "printf '\\n== acceptance units ==\\n'; "
            "systemctl status anduinos-acceptance-reboot.timer "
            "anduinos-acceptance-reboot.service "
            "anduinos-acceptance-poweroff.timer "
            "anduinos-acceptance-poweroff.service --no-pager; "
            "printf '\\n== jobs ==\\n'; systemctl list-jobs --no-pager; "
            "printf '\\n== failed units ==\\n'; "
            "systemctl list-units --state=failed --no-pager; "
            "printf '\\n== inhibitors ==\\n'; loginctl list-inhibitors --no-pager; "
            "printf '\\n== processes ==\\n'; "
            "ps -eo pid,ppid,state,wchan:32,comm,args --sort=pid; "
            "printf '\\n== transition journal ==\\n'; "
            "journalctl -b --since '-3 min' --no-pager "
            "-u anduinos-acceptance-reboot.timer "
            "-u anduinos-acceptance-reboot.service "
            "-u anduinos-acceptance-poweroff.timer "
            "-u anduinos-acceptance-poweroff.service "
            "-u systemd-logind.service"
        )
        failures: list[str] = []
        serial = getattr(vm, "serial", None)
        if serial is not None:
            try:
                result = serial.run(command, timeout=20, check=False)
                return "Collected over the root serial control channel.\n" + result.stdout
            except Exception as error:
                failures.append(
                    "Serial diagnostic collection failed: "
                    f"{type(error).__name__}: {error}"
                )
        try:
            output = self._ssh(vm, key, command, timeout=30, check=False)
            prefix = "\n".join(failures)
            if prefix:
                prefix += "\n"
            return prefix + "Collected over SSH.\n" + output
        except Exception as error:
            failures.append(
                "SSH diagnostic collection failed while QEMU remained alive: "
                f"{type(error).__name__}: {error}"
            )
            return "\n".join(failures)

    @staticmethod
    def _graphical_boot_ready_command() -> str:
        """Do not confuse early sshd availability with a completed boot."""

        return (
            "systemctl is-active --quiet graphical.target && "
            "systemctl is-active --quiet gdm"
        )

    @staticmethod
    def _rollback_health_command(
        root_sentinel: str,
        home_sentinel: str,
        deployment_id: str,
    ) -> str:
        return (
            "set -euo pipefail; "
            "test \"$(findmnt -n -o FSTYPE /)\" = btrfs; "
            "test \"$(findmnt -n -o FSROOT /)\" = /@root; "
            "! dpkg-query -W -f='${db:Status-Abbrev}' docker.io 2>/dev/null "
            "| grep -q '^ii '; "
            "test ! -e /usr/bin/docker; "
            f"test ! -e {shlex.quote(root_sentinel)}; "
            f"test -f {shlex.quote(home_sentinel)}; "
            "sudo -n /usr/local/sbin/anduinos-acceptance-package-health; "
            "printf 'docker=absent\\nroot-sentinel=absent\\n"
            "home-sentinel=present\\n'; "
            "systemctl is-active --quiet graphical.target; "
            "sudo -n /usr/local/sbin/anduinos-acceptance-boot-health; "
            "sudo -n /usr/local/sbin/anduinos-acceptance-rollback-state "
            f"{shlex.quote(deployment_id)}; "
            "printf 'rollback-health=ok\\n'"
        )

    def _ssh_eventually(
        self,
        vm: QemuVm,
        key: Path,
        command: str,
        *,
        timeout: float = 120,
    ) -> str:
        deadline = time.monotonic() + timeout
        last = ""
        while time.monotonic() < deadline:
            remaining = deadline - time.monotonic()
            attempt_timeout = max(1.0, min(15.0, remaining))
            try:
                return self._ssh(vm, key, command, timeout=attempt_timeout)
            except (TestFailure, subprocess.TimeoutExpired) as error:
                last = f"{type(error).__name__}: {error}"
                time.sleep(2)
        raise TestFailure("SSH control did not become healthy after boot: " + last[-4000:])

    def _ssh(
        self,
        vm: QemuVm,
        key: Path,
        command: str,
        *,
        timeout: float = 60,
        check: bool = True,
    ) -> str:
        invocation = (
            "ssh",
            "-F",
            "/dev/null",
            "-i",
            str(key),
            "-p",
            str(vm.config.ssh_forward_port),
            "-o",
            "BatchMode=yes",
            "-o",
            "StrictHostKeyChecking=no",
            "-o",
            "UserKnownHostsFile=/dev/null",
            "-o",
            "ConnectTimeout=10",
            "-o",
            "ConnectionAttempts=1",
            "-o",
            "ServerAliveInterval=5",
            "-o",
            "ServerAliveCountMax=1",
            f"{self.username}@127.0.0.1",
            command,
        )
        result = subprocess.run(
            invocation,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            check=False,
            timeout=timeout,
        )
        if check and result.returncode != 0:
            raise TestFailure(
                f"Feature SSH control failed with {result.returncode}:\n"
                + result.stdout[-8000:]
            )
        return result.stdout

    def _exercise_rime_input(
        self,
        vm: QemuVm,
        base: PromotedBase,
        artifacts: Path,
    ) -> None:
        assert vm.serial is not None and vm.qmp is not None
        remote = "/run/anduinos-feature-rime"
        vm.serial.run(f"install -d -m 0777 {remote}/evidence")
        vm.serial.upload(self.driver, f"{remote}/atspi_driver.py", 0o755)
        vm.serial.upload(self.input_fixture, f"{remote}/input_fixture.py", 0o755)

        precondition = vm.serial.run(
            _desktop_command(
                self.username,
                (
                    "bash",
                    "-lc",
                    "set -e; sources=$(gsettings get org.gnome.desktop.input-sources sources); "
                    "engine=$(ibus engine); printf 'sources=%s\\nengine=%s\\n' \"$sources\" \"$engine\"; "
                    "printf '%s\\n' 'user-manager-input-environment:'; "
                    "systemctl --user show-environment | "
                    "grep -E '^(GTK_IM_MODULE|QT_IM_MODULE|QT_IM_MODULES|XMODIFIERS|IBUS)=' || true; "
                    "printf '%s' \"$sources\" | grep -q \"'ibus', 'rime'\"; "
                    "test \"$engine\" != rime",
                ),
            ),
            timeout=60,
        )
        (artifacts / "rime-precondition.txt").write_text(
            precondition.stdout + "\n", encoding="utf-8"
        )
        original_engine = _last_value(precondition.stdout, "engine")

        launch = _desktop_command(
            self.username,
            (
                "bash",
                "-lc",
                "systemd-run --user --unit=anduinos-rime-input-fixture "
                "--collect --property=Type=exec "
                "--setenv=HOME=\"$HOME\" "
                "--setenv=XDG_RUNTIME_DIR=\"$XDG_RUNTIME_DIR\" "
                "--setenv=DBUS_SESSION_BUS_ADDRESS=\"$DBUS_SESSION_BUS_ADDRESS\" "
                "--setenv=WAYLAND_DISPLAY=\"$WAYLAND_DISPLAY\" "
                "--setenv=DISPLAY=\"$DISPLAY\" --setenv=NO_AT_BRIDGE=0 "
                f"python3 {remote}/input_fixture.py",
            ),
        )
        vm.serial.run(launch, timeout=60)
        prepared = vm.serial.run(
            _desktop_command(
                self.username,
                (
                    "python3",
                    f"{remote}/atspi_driver.py",
                    "rime-input-prepare",
                    "--evidence",
                    f"{remote}/evidence",
                ),
            ),
            timeout=120,
            check=False,
        )
        (artifacts / "rime-atspi-events.jsonl").write_text(
            prepared.stdout + "\n", encoding="utf-8"
        )
        if prepared.returncode != 0:
            _retrieve_tree(vm.serial, remote, artifacts / "guest-rime-evidence")
            raise TestFailure(
                "Could not focus the real GTK Rime fixture:\n"
                + prepared.stdout[-8000:]
            )

        cursors = self._journal_cursors(vm)
        vm.qmp.send_key("meta_l-spc")
        self._wait_for_ibus_engine(vm, "rime")
        self._wait_for_rime_ready(vm, artifacts)
        vm.qmp.type_text("nihao", interval=0.10)
        vm.qmp.send_key("spc")
        time.sleep(2)
        asserted = vm.serial.run(
            _desktop_command(
                self.username,
                (
                    "python3",
                    f"{remote}/atspi_driver.py",
                    "rime-input-assert",
                    "--expected",
                    "你好",
                    "--evidence",
                    f"{remote}/evidence",
                ),
            ),
            timeout=120,
            check=False,
        )
        with (artifacts / "rime-atspi-events.jsonl").open(
            "a", encoding="utf-8"
        ) as stream:
            stream.write(asserted.stdout + "\n")
        if asserted.returncode != 0:
            _retrieve_tree(vm.serial, remote, artifacts / "guest-rime-evidence")
            raise TestFailure(
                "Rime did not commit the exact expected Chinese text:\n"
                + asserted.stdout[-8000:]
            )
        _retrieve_tree(vm.serial, remote, artifacts / "guest-rime-evidence")
        _validate_rime_evidence(
            artifacts / "guest-rime-evidence" / "rime-input-result.json",
            "你好",
        )

        vm.qmp.send_key("meta_l-spc")
        self._wait_for_ibus_engine(vm, original_engine)
        self._assert_scoped_journal(vm, base, cursors, artifacts)
        vm.screenshot("rime-committed-chinese")
        vm.serial.run(
            _desktop_command(
                self.username,
                ("systemctl", "--user", "stop", "anduinos-rime-input-fixture.service"),
            ),
            timeout=30,
            check=False,
        )

    def _wait_for_ibus_engine(
        self,
        vm: QemuVm,
        expected: str,
        timeout: float = 30,
    ) -> None:
        assert vm.serial is not None
        deadline = time.monotonic() + timeout
        observed = ""
        while time.monotonic() < deadline:
            result = vm.serial.run(
                _desktop_command(self.username, ("ibus", "engine")),
                timeout=30,
                check=False,
            )
            observed = result.stdout.strip().splitlines()[-1] if result.stdout.strip() else ""
            if result.returncode == 0 and observed == expected:
                return
            time.sleep(0.5)
        raise TestFailure(
            f"IBus engine did not become {expected!r}; last observed {observed!r}"
        )

    def _wait_for_rime_ready(self, vm: QemuVm, artifacts: Path) -> None:
        """Wait for first-use deployment, not merely the IBus engine name.

        Rime compiles its schema and large dictionaries the first time a fresh
        account activates the engine.  ``ibus engine`` changes before that
        deployment is complete, so sending keys immediately races the real
        input method and can make a healthy installation look like raw ASCII
        input.  The generated schema and binary dictionaries are the durable
        readiness contract used by the engine itself.
        """

        assert vm.serial is not None
        command = _desktop_command(
            self.username,
            (
                "bash",
                "-lc",
                "set -e; root=$HOME/.config/ibus/rime; "
                "deadline=$((SECONDS + 180)); "
                "while ! { test -s \"$root/build/rime_ice.schema.yaml\" && "
                "test -s \"$root/build/rime_ice.table.bin\" && "
                "test -s \"$root/build/rime_ice.prism.bin\" && "
                "test -s \"$root/user.yaml\"; }; do "
                "if (( SECONDS >= deadline )); then "
                "printf '%s\\n' 'Rime first-use deployment did not finish'; "
                "find \"$root\" -maxdepth 2 -type f -printf '%s %p\\n' 2>/dev/null | sort; "
                "exit 1; fi; sleep 1; done; "
                "printf '%s\\n' 'Rime first-use deployment is ready'; "
                "find \"$root\" -maxdepth 2 -type f -printf '%s %p\\n' | sort",
            ),
        )
        result = vm.serial.run(command, timeout=210, check=False)
        (artifacts / "rime-deployment.txt").write_text(
            result.stdout + "\n", encoding="utf-8"
        )
        if result.returncode != 0:
            raise TestFailure(
                "Rime did not finish its first-use deployment:\n"
                + result.stdout[-8000:]
            )

    def _journal_cursors(self, vm: QemuVm) -> dict[str, str]:
        assert vm.serial is not None
        script = "journalctl -b -n 0 --show-cursor --no-pager | sed -n 's/^-- cursor: //p'"
        system = vm.serial.run(script, timeout=30).stdout.strip().splitlines()
        user = vm.serial.run(
            _desktop_command(self.username, ("bash", "-lc", script)),
            timeout=30,
        ).stdout.strip().splitlines()
        if not system or not user:
            raise TestFailure("Could not establish system and user journal cursors")
        return {"system": system[-1], "user": user[-1]}

    def _assert_scoped_journal(
        self,
        vm: QemuVm,
        base: PromotedBase,
        cursors: dict[str, str],
        artifacts: Path,
        *,
        scope: str = "rime",
    ) -> None:
        assert vm.serial is not None
        system = vm.serial.run(
            render_guest_collection_script(
                self.journal_policy,
                after_cursor=cursors["system"],
            ),
            timeout=120,
            check=False,
        )
        user = vm.serial.run(
            _desktop_command(
                self.username,
                (
                    "bash",
                    "-lc",
                    render_guest_collection_script(
                        self.journal_policy,
                        user=True,
                        after_cursor=cursors["user"],
                    ),
                ),
            ),
            timeout=120,
            check=False,
        )
        (artifacts / f"{scope}-system-journal.jsonl").write_text(
            system.stdout + "\n", encoding="utf-8"
        )
        (artifacts / f"{scope}-user-journal.jsonl").write_text(
            user.stdout + "\n", encoding="utf-8"
        )
        if system.returncode != 0 or user.returncode != 0:
            raise TestFailure("Could not collect action-scoped Rime journal evidence")
        packages = " ".join(shlex.quote(item) for item in self.journal_policy.packages)
        package_result = vm.serial.run(
            "set -uo pipefail\n"
            f"for package in {packages}; do\n"
            "  dpkg-query -W -f='${Package}\\t${Version}\\n' \"$package\" "
            "2>/dev/null || true\n"
            "done",
            timeout=60,
        )
        versions = parse_package_versions(package_result.stdout)
        entries = (
            *parse_journal_jsonl(system.stdout, "system"),
            *parse_journal_jsonl(user.stdout, "user"),
        )
        verdict = self.journal_policy.classify(
            entries,
            base.scenario,
            versions,
            action_scope=scope,
        )
        (artifacts / f"{scope}-journal-verdict.json").write_text(
            json.dumps(verdict.to_dict(), ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        (artifacts / f"{scope}-journal-verdict.txt").write_text(
            render_verdict(verdict) + "\n", encoding="utf-8"
        )
        shutil.copy2(
            self.framework_root / "journal-policy.json",
            artifacts / "journal-policy.json",
        )
        if not verdict.passed:
            raise TestFailure(
                f"{scope} produced action-scoped journal blockers:\n"
                + render_verdict(verdict)
            )

    @staticmethod
    def _write_manifest(
        base: PromotedBase,
        suite: FeatureSuite,
        vm: QemuVm,
        artifacts: Path,
    ) -> None:
        document = {
            "schema_version": 1,
            "suite": suite.id,
            "checks": list(suite.checks),
            "source_case": base.scenario.id,
            "base_identity": base.identity,
            "base_disk": str(base.disk),
            "overlay": str(vm.config.disk),
            "isolation": "qcow2-overlay",
        }
        (artifacts / "suite-manifest.json").write_text(
            json.dumps(document, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )


def _validate_search_provider_preflight(output: str, returncode: int) -> None:
    """Reject a Software provider which crashed and merely restarted."""

    if returncode != 0:
        raise TestFailure(
            "GNOME Software search provider did not reach a stable session state:\n"
            + output[-8000:]
        )

    expected_packages = {
        "gnome-software",
        "gnome-software-plugin-deb",
        "packagekit",
        "libpackagekit-glib2-18",
    }
    versions = {
        match.group("package"): match.group("version")
        for match in re.finditer(
            r"^package=(?P<package>[^ ]+) version=(?P<version>[^ ]+)$",
            output,
            re.MULTILINE,
        )
    }
    if set(versions) != expected_packages or any(
        version == "missing" for version in versions.values()
    ):
        raise TestFailure(
            "GNOME Software preflight did not record every installed package version"
        )

    before = re.search(
        r"^before_pid=(?P<pid>[0-9]+) before_restarts=(?P<restarts>[0-9]+) "
        r"before_active=(?P<active>[^ ]+)$",
        output,
        re.MULTILINE,
    )
    after = re.search(
        r"^after_pid=(?P<pid>[0-9]+) after_restarts=(?P<restarts>[0-9]+) "
        r"after_active=(?P<active>[^ ]+)$",
        output,
        re.MULTILINE,
    )
    ready = re.search(
        r"^search-provider=ready pid=(?P<pid>[0-9]+) "
        r"restarts=(?P<restarts>[0-9]+)$",
        output,
        re.MULTILINE,
    )
    if before is None or after is None or ready is None:
        raise TestFailure(
            "GNOME Software preflight omitted its process-lifecycle evidence"
        )

    before_pid = int(before.group("pid"))
    before_restarts = int(before.group("restarts"))
    after_pid = int(after.group("pid"))
    after_restarts = int(after.group("restarts"))
    if before_restarts != 0 or after_restarts != 0:
        raise TestFailure(
            "GNOME Software crashed and restarted before the feature action"
        )
    if after.group("active") != "active" or after_pid == 0:
        raise TestFailure("GNOME Software search provider is not active")
    if before_pid != 0 and before_pid != after_pid:
        raise TestFailure(
            "GNOME Software process changed during search-provider preflight"
        )
    if int(ready.group("pid")) != after_pid or int(ready.group("restarts")) != 0:
        raise TestFailure(
            "GNOME Software ready marker contradicts its lifecycle evidence"
        )


def _validate_local_search_provider_isolation_configuration(
    output: str,
    returncode: int,
) -> None:
    """Require the exact Software provider to be disabled before login."""

    if returncode != 0:
        raise TestFailure(
            "Could not configure local-search provider isolation before login:\n"
            + output[-4000:]
        )
    if f"provider={_SOFTWARE_SEARCH_PROVIDER_ID}" not in output:
        raise TestFailure("Local-search isolation resolved an unexpected provider")
    configured = re.search(r"^configured=(?P<value>.+)$", output, re.MULTILINE)
    if configured is None or _SOFTWARE_SEARCH_PROVIDER_ID not in configured.group(
        "value"
    ):
        raise TestFailure("GNOME Software was not disabled for local ArcMenu search")


def _validate_local_search_provider_runtime_isolation(
    output: str,
    returncode: int,
) -> None:
    """Require an inactive runtime mask before a local-search action."""

    if returncode != 0:
        raise TestFailure(
            "Could not enforce local-search provider isolation:\n" + output[-4000:]
        )
    configured = re.search(r"^configured=(?P<value>.+)$", output, re.MULTILINE)
    after = re.search(
        r"^after_load=(?P<load>[^ ]+) after_state=(?P<state>[^ ]+) "
        r"after_pid=(?P<pid>[0-9]+)$",
        output,
        re.MULTILINE,
    )
    if configured is None or _SOFTWARE_SEARCH_PROVIDER_ID not in configured.group(
        "value"
    ):
        raise TestFailure("Local ArcMenu search lost its Software-provider isolation")
    if (
        after is None
        or after.group("load") != "masked"
        or after.group("state") != "inactive"
        or int(after.group("pid")) != 0
    ):
        raise TestFailure("GNOME Software was not masked for local ArcMenu search")


def _validate_local_search_provider_post_action_isolation(
    output: str,
    returncode: int,
) -> None:
    """Require Software to remain masked and inactive after the action."""

    if returncode != 0:
        raise TestFailure(
            "Could not verify local-search provider isolation:\n" + output[-4000:]
        )
    configured = re.search(r"^configured=(?P<value>.+)$", output, re.MULTILINE)
    state = re.search(
        r"^load=(?P<load>[^ ]+) state=(?P<state>[^ ]+) pid=(?P<pid>[0-9]+)$",
        output,
        re.MULTILINE,
    )
    if configured is None or _SOFTWARE_SEARCH_PROVIDER_ID not in configured.group(
        "value"
    ):
        raise TestFailure("Local ArcMenu search lost its Software-provider isolation")
    if (
        state is None
        or state.group("load") != "masked"
        or state.group("state") != "inactive"
        or int(state.group("pid")) != 0
    ):
        raise TestFailure("Local ArcMenu search activated GNOME Software")


def _last_value(output: str, key: str) -> str:
    prefix = key + "="
    values = [line[len(prefix) :] for line in output.splitlines() if line.startswith(prefix)]
    if not values or not values[-1]:
        raise TestFailure(f"Missing {key!r} in feature precondition evidence")
    return values[-1]


def _safe_failure_class(
    output: str,
    key: str,
    allowed: set[str],
) -> str:
    """Return a declared failure class without hiding malformed evidence."""

    try:
        classification = _last_value(output, key)
    except TestFailure:
        return "product-regression"
    if classification not in allowed:
        return "product-regression"
    return classification


def _graphical_vt_probe_command(
    username: str,
    *,
    wait_for: int | None = None,
) -> str:
    """Render a guest probe which binds the active VT to the Wayland session."""

    if wait_for is not None and not 1 <= wait_for <= 12:
        raise ValueError("A graphical VT must be within 1..12")
    wait = ""
    if wait_for is not None:
        wait = f"""
deadline=$((SECONDS + 30))
while test "$(active_vt 2>/dev/null || true)" != {wait_for}; do
    if (( SECONDS >= deadline )); then
        printf 'restore-timeout-vt=%s\\n' "$(active_vt 2>/dev/null || true)"
        exit 70
    fi
    sleep 0.25
done
"""
    user = shlex.quote(username)
    return f"""set -eu
active_vt() {{
    name=$(cat /sys/class/tty/tty0/active)
    case "$name" in
        tty[1-9]|tty1[0-2]) printf '%s\\n' "$name" | sed 's/^tty//' ;;
        *) printf 'unexpected active VT: %s\\n' "$name" >&2; return 1 ;;
    esac
}}
{wait}active=$(active_vt)
session=$(loginctl show-user {user} -p Display --value)
test -n "$session"
session_vt=$(loginctl show-session "$session" -p VTNr --value)
session_type=$(loginctl show-session "$session" -p Type --value)
session_active=$(loginctl show-session "$session" -p Active --value)
target=$(systemctl is-active graphical.target)
gdm=$(systemctl is-active gdm.service)
printf 'active-vt=%s\\n' "$active"
printf 'graphical-session=%s\\n' "$session"
printf 'graphical-session-vt=%s\\n' "$session_vt"
printf 'graphical-session-type=%s\\n' "$session_type"
printf 'graphical-session-active=%s\\n' "$session_active"
printf 'graphical-target=%s\\n' "$target"
printf 'gdm-service=%s\\n' "$gdm"
test "$active" = "$session_vt"
test "$session_type" = wayland
test "$session_active" = yes
test "$target" = active
test "$gdm" = active
"""


def _tty6_probe_command() -> str:
    """Render a bounded probe of the character cells actually shown on tty6."""

    return r"""set -eu
active_vt() {
    name=$(cat /sys/class/tty/tty0/active)
    case "$name" in
        tty[1-9]|tty1[0-2]) printf '%s\n' "$name" | sed 's/^tty//' ;;
        *) printf 'unexpected active VT: %s\n' "$name" >&2; return 1 ;;
    esac
}
deadline=$((SECONDS + 30))
while :; do
    active=$(active_vt 2>/dev/null || true)
    if test "$active" = 6 && test -r /dev/vcs6 && \
       python3 -c "from pathlib import Path; raise SystemExit(0 if b'AnduinOS' in Path('/dev/vcs6').read_bytes() else 1)"; then
        break
    fi
    if (( SECONDS >= deadline )); then
        break
    fi
    sleep 0.25
done
active=$(active_vt 2>/dev/null || true)
printf 'active-vt=%s\n' "$active"
printf 'vcs-device=/dev/vcs6\n'
python3 - <<'PY'
import hashlib
import json
from pathlib import Path

raw = Path('/dev/vcs6').read_bytes()
text = raw.decode('ascii', errors='replace').replace('\x00', ' ')
print(f'vcs-bytes={len(raw)}')
print(f'vcs-sha256={hashlib.sha256(raw).hexdigest()}')
print('vcs-text-json=' + json.dumps(text, ensure_ascii=True))
if 'AnduinOS' not in text:
    raise SystemExit(71)
if 'ubuntu' in text.casefold():
    raise SystemExit(72)
PY
test "$active" = 6
"""


def _cpu_z_download_command() -> str:
    """Render the pinned public CPU-Z download and file-contract probe."""

    archive = shlex.quote(_CPU_Z_ARCHIVE)
    member = shlex.quote(_CPU_Z_MEMBER)
    url = shlex.quote(_CPU_Z_URL)
    archive_sha = shlex.quote(_CPU_Z_ARCHIVE_SHA256)
    member_sha = shlex.quote(_CPU_Z_MEMBER_SHA256)
    handler = shlex.quote(_CPU_Z_HANDLER)
    return f"""set -euo pipefail
command -v curl
command -v unzip
command -v exe-thumbnailer
command -v xdg-mime
printf 'cpu-z-stage=preflight\n'
if flatpak info com.usebottles.bottles >/dev/null 2>&1; then
    printf 'bottles=installed\n'
    exit 81
fi
downloads=$HOME/Downloads
install -d -m 0755 "$downloads"
archive="$downloads"/{archive}
member="$downloads"/{member}
printf 'cpu-z-archive-preexisting=%s\n' "$(test -e "$archive" && echo yes || echo no)"
printf 'cpu-z-member-preexisting=%s\n' "$(test -e "$member" && echo yes || echo no)"
test ! -e "$archive" || exit 82
test ! -e "$member" || exit 83
printf 'cpu-z-stage=download\n'
curl --fail --location --silent --show-error --retry 3 \
    --proto '=https' --tlsv1.2 --output "$archive" \
    --write-out 'cpu-z-http-code=%{{http_code}}\n' {url}
archive_digest=$(sha256sum "$archive" | awk '{{print $1}}')
printf 'cpu-z-archive-sha256=%s\n' "$archive_digest"
test "$archive_digest" = {archive_sha} || exit 84
printf 'cpu-z-stage=extract\n'
unzip -p "$archive" {member} > "$member"
chmod 0644 "$archive" "$member"
member_digest=$(sha256sum "$member" | awk '{{print $1}}')
member_size=$(stat -c %s "$member")
printf 'cpu-z-member-sha256=%s\n' "$member_digest"
printf 'cpu-z-member-size=%s\n' "$member_size"
test "$member_digest" = {member_sha} || exit 85
test "$member_size" -eq {_CPU_Z_MEMBER_SIZE} || exit 86
test "$(dd if="$member" bs=1 count=2 status=none)" = MZ || exit 87
printf 'cpu-z-stage=mime-dispatch\n'
mime_type=$(xdg-mime query filetype "$member")
handler_name=$(xdg-mime query default "$mime_type")
printf 'cpu-z-mime=%s\n' "$mime_type"
printf 'cpu-z-handler=%s\n' "$handler_name"
case "$mime_type" in
    application/vnd.microsoft.portable-executable|application/x-msdownload) ;;
    *) exit 88 ;;
esac
test "$handler_name" = {handler} || exit 89
printf 'cpu-z-version=%s\n' {_CPU_Z_VERSION!r}
printf 'cpu-z-url=%s\n' {url}
printf 'cpu-z-archive=%s\n' {archive}
printf 'cpu-z-member=%s\n' {member}
printf 'bottles=absent\n'
printf 'public-cpu-z=downloaded-and-verified\n'
"""


def _spotify_public_catalog_command() -> str:
    """Render the public Flathub refresh and exact Spotify catalog probe."""

    remote = shlex.quote(_SPOTIFY_REMOTE)
    remote_url = shlex.quote(_SPOTIFY_REMOTE_URL)
    app_id = shlex.quote(_SPOTIFY_APP_ID)
    arch = shlex.quote(_SPOTIFY_ARCH)
    expected_ref = shlex.quote(_SPOTIFY_REF)
    return f"""set -uo pipefail
export LC_ALL=C
fail_spotify_public() {{
    printf 'spotify-public-failure-reason=%s\n' "$2"
    printf 'spotify-public-failure-class=%s\n' "$1"
    exit "$3"
}}
printf 'spotify-public-stage=preflight\n'
command -v flatpak >/dev/null 2>&1 || \
    fail_spotify_public product-regression flatpak-missing 81
printf 'flatpak-version=%s\n' "$(flatpak --version)"
remotes=$(flatpak remotes --system --show-disabled --columns=name,url,options 2>&1) || {{
    printf 'spotify-public-remotes-error=%s\n' "$remotes"
    fail_spotify_public product-regression remote-list-failed 82
}}
printf 'spotify-public-remotes=%s\n' "$remotes"
remote_count=$(printf '%s\n' "$remotes" | awk -F '\t' '$1 == "flathub" {{ count++ }} END {{ print count + 0 }}')
observed_url=$(printf '%s\n' "$remotes" | awk -F '\t' '$1 == "flathub" {{ print $2 }}')
printf 'spotify-public-remote-count=%s\n' "$remote_count"
printf 'spotify-public-remote-url=%s\n' "$observed_url"
test "$remote_count" -eq 1 || \
    fail_spotify_public product-regression flathub-remote-count 83
test "$observed_url" = {remote_url} || \
    fail_spotify_public product-regression flathub-remote-url 84
printf 'spotify-public-stage=appstream-refresh\n'
if ! timeout --signal=TERM 600 flatpak update --appstream --system \
    --noninteractive {remote}; then
    fail_spotify_public external-catalog appstream-refresh-failed 85
fi
printf 'spotify-public-appstream-refresh=passed\n'
printf 'spotify-public-stage=remote-resolution\n'
if ! spotify_ref=$(timeout --signal=TERM 180 flatpak remote-info --system \
    --arch={arch} --show-ref {remote} {app_id} 2>&1); then
    printf 'spotify-public-remote-info-error=%s\n' "$spotify_ref"
    fail_spotify_public external-catalog spotify-ref-unavailable 86
fi
if ! spotify_commit=$(timeout --signal=TERM 180 flatpak remote-info --system \
    --arch={arch} --show-commit {remote} {app_id} 2>&1); then
    printf 'spotify-public-remote-info-error=%s\n' "$spotify_commit"
    fail_spotify_public external-catalog spotify-commit-unavailable 87
fi
printf 'spotify-public-ref=%s\n' "$spotify_ref"
printf 'spotify-public-commit=%s\n' "$spotify_commit"
test "$spotify_ref" = {expected_ref} || \
    fail_spotify_public external-catalog spotify-ref-mismatch 88
printf 'spotify-public-stage=cached-appstream-contract\n'
cached_entry=$(flatpak remote-ls --system --cached --app --arch={arch} \
    --columns=application,ref,arch,branch,origin {remote} 2>&1 | \
    awk -F '\t' '$1 == "com.spotify.Client" {{ print; count++ }} END {{ if (count != 1) exit 1 }}') || {{
    printf 'spotify-public-cached-error=%s\n' "$cached_entry"
    fail_spotify_public external-catalog spotify-cached-entry-missing 89
}}
printf 'spotify-public-cached-entry=%s\n' "$cached_entry"
printf 'spotify-public-app-id=%s\n' {app_id}
printf 'spotify-public-remote=%s\n' {remote}
printf 'spotify-public-arch=%s\n' {arch}
printf 'spotify-public-failure-class=none\n'
printf 'spotify-public-catalog=current-and-resolved\n'
"""


def _wechat_install_command() -> str:
    """Render the current native WeChat Flatpak installation contract."""

    remote = shlex.quote(_SPOTIFY_REMOTE)
    remote_url = shlex.quote(_SPOTIFY_REMOTE_URL)
    app_id = shlex.quote(_WECHAT_APP_ID)
    arch = shlex.quote(_WECHAT_ARCH)
    expected_ref = shlex.quote(_WECHAT_REF)
    return f"""set -uo pipefail
export LC_ALL=C
fail_wechat() {{
    printf 'wechat-failure-reason=%s\n' "$2"
    printf 'wechat-failure-class=%s\n' "$1"
    exit "$3"
}}
printf 'wechat-stage=preflight\n'
command -v flatpak >/dev/null 2>&1 || \
    fail_wechat product-regression flatpak-missing 81
if flatpak info --system {app_id} >/dev/null 2>&1; then
    printf 'wechat-preinstalled=yes\n'
    fail_wechat product-regression unexpected-preinstalled-app 82
fi
printf 'wechat-preinstalled=no\n'
remotes=$(flatpak remotes --system --show-disabled --columns=name,url 2>&1) || {{
    printf 'wechat-remotes-error=%s\n' "$remotes"
    fail_wechat product-regression remote-list-failed 83
}}
remote_count=$(printf '%s\n' "$remotes" | awk -F '\t' '$1 == "flathub" {{ count++ }} END {{ print count + 0 }}')
observed_url=$(printf '%s\n' "$remotes" | awk -F '\t' '$1 == "flathub" {{ print $2 }}')
printf 'wechat-remote-count=%s\n' "$remote_count"
printf 'wechat-remote-url=%s\n' "$observed_url"
test "$remote_count" -eq 1 || \
    fail_wechat product-regression flathub-remote-count 84
test "$observed_url" = {remote_url} || \
    fail_wechat product-regression flathub-remote-url 85
printf 'wechat-stage=catalog-refresh\n'
if ! timeout --signal=TERM 600 flatpak update --appstream --system \
    --noninteractive {remote}; then
    fail_wechat external-catalog appstream-refresh-failed 86
fi
if ! remote_ref=$(timeout --signal=TERM 180 flatpak remote-info --system \
    --arch={arch} --show-ref {remote} {app_id} 2>&1); then
    printf 'wechat-remote-info-error=%s\n' "$remote_ref"
    fail_wechat external-catalog wechat-ref-unavailable 87
fi
if ! remote_commit=$(timeout --signal=TERM 180 flatpak remote-info --system \
    --arch={arch} --show-commit {remote} {app_id} 2>&1); then
    printf 'wechat-remote-info-error=%s\n' "$remote_commit"
    fail_wechat external-catalog wechat-commit-unavailable 88
fi
printf 'wechat-remote-ref=%s\n' "$remote_ref"
printf 'wechat-remote-commit=%s\n' "$remote_commit"
test "$remote_ref" = {expected_ref} || \
    fail_wechat external-catalog wechat-ref-mismatch 89
printf 'wechat-stage=install\n'
if ! timeout --signal=TERM 1200 flatpak install --system --noninteractive \
    --assumeyes --arch={arch} {remote} {app_id}; then
    fail_wechat external-artifact flatpak-install-failed 90
fi
# Third-party bwrap/extra-data helpers may write diagnostics without a trailing
# newline. Start a fresh protocol record instead of weakening the key parser.
printf '\nwechat-install-command=passed\n'
installed_ref=$(flatpak info --system --arch={arch} --show-ref {app_id} 2>&1) || \
    fail_wechat product-regression installed-ref-missing 91
installed_commit=$(flatpak info --system --arch={arch} --show-commit {app_id} 2>&1) || \
    fail_wechat product-regression installed-commit-missing 92
installed_origin=$(flatpak info --system --arch={arch} --show-origin {app_id} 2>&1) || \
    fail_wechat product-regression installed-origin-missing 93
installed_location=$(flatpak info --system --arch={arch} --show-location {app_id} 2>&1) || \
    fail_wechat product-regression installed-location-missing 94
printf 'wechat-installed-ref=%s\n' "$installed_ref"
printf 'wechat-installed-commit=%s\n' "$installed_commit"
printf 'wechat-installed-origin=%s\n' "$installed_origin"
printf 'wechat-installed-location=%s\n' "$installed_location"
test "$installed_ref" = "$remote_ref" || \
    fail_wechat product-regression installed-ref-mismatch 95
test "$installed_commit" = "$remote_commit" || \
    fail_wechat product-regression installed-commit-mismatch 96
test "$installed_origin" = {remote} || \
    fail_wechat product-regression installed-origin-mismatch 97
desktop=/var/lib/flatpak/exports/share/applications/com.tencent.WeChat.desktop
desktop_resolved=$(readlink -f "$desktop" 2>/dev/null || true)
printf 'wechat-desktop=%s\n' "$desktop"
printf 'wechat-desktop-resolved=%s\n' "$desktop_resolved"
test -s "$desktop_resolved" || \
    fail_wechat product-regression desktop-export-missing 98
grep -Eq '^Exec=.*flatpak run .*com[.]tencent[.]WeChat' "$desktop_resolved" || \
    fail_wechat product-regression desktop-exec-invalid 99
printf 'wechat-app-id=%s\n' {app_id}
printf 'wechat-arch=%s\n' {arch}
printf 'wechat-failure-class=none\n'
printf 'wechat-install=current-and-verified\n'
"""


def _nextcloud_ppa_source_probe_command() -> str:
    """Render a fail-closed probe of the source created by software-properties."""

    return r"""set -euo pipefail
codename=$(. /etc/os-release; printf '%s' "$VERSION_CODENAME")
test -n "$codename"
EXPECTED_CODENAME="$codename" python3 - <<'PY'
import os
import re
from pathlib import Path

needle = 'ppa.launchpadcontent.net/nextcloud-devs/client/ubuntu'
root = Path('/etc/apt/sources.list.d')
matches = [
    path
    for path in sorted(root.iterdir())
    if path.is_file() and needle in path.read_text(encoding='utf-8', errors='replace')
]
print(f'os-release-codename={os.environ["EXPECTED_CODENAME"]}')
print(f'source-count={len(matches)}')
if len(matches) != 1:
    raise SystemExit(81)
path = matches[0]
text = path.read_text(encoding='utf-8', errors='replace')
codename = os.environ['EXPECTED_CODENAME']
uri = re.search(r'(?m)^URIs:\s*(\S+)', text)
suite = re.search(r'(?m)^Suites:\s*(\S+)', text)
if uri is None or suite is None:
    legacy = re.search(
        r'(?m)^deb(?:\s+\[[^]]+\])?\s+(\S+)\s+(\S+)\s+',
        text,
    )
    if legacy is not None:
        uri = uri or legacy
        suite = suite or legacy
        uri_value = legacy.group(1)
        suite_value = legacy.group(2)
    else:
        uri_value = ''
        suite_value = ''
else:
    uri_value = uri.group(1)
    suite_value = suite.group(1)
signed = bool(
    re.search(r'(?mi)^Signed-By:', text)
    or re.search(r'(?i)\bsigned-by=', text)
)
print(f'source-path={path}')
print(f'source-uri={uri_value}')
print(f'source-suite={suite_value}')
print(f'source-signed-by={"yes" if signed else "no"}')
if (
    needle not in uri_value
    or suite_value != codename
    or not signed
):
    raise SystemExit(82)
PY
index_uri=$(apt-get indextargets --format '$(URI)' |
    grep -F 'ppa.launchpadcontent.net/nextcloud-devs/client/ubuntu' |
    sed -n '1p')
test -n "$index_uri"
printf 'apt-index-uri=%s\n' "$index_uri"
"""


def _validate_graphical_vt_evidence(
    output: str,
    returncode: int,
    *,
    expected_vt: int | None = None,
) -> int:
    if returncode != 0:
        raise TestFailure(
            "The graphical VT/session probe failed:\n" + output[-8000:]
        )
    try:
        active = int(_last_value(output, "active-vt"))
        session_vt = int(_last_value(output, "graphical-session-vt"))
    except ValueError as error:
        raise TestFailure("The graphical VT probe returned a non-numeric VT") from error
    if not 1 <= active <= 12 or session_vt != active:
        raise TestFailure(
            f"The active VT {active} does not own the graphical session VT {session_vt}"
        )
    if expected_vt is not None and active != expected_vt:
        raise TestFailure(
            f"The harness returned to tty{active}, expected tty{expected_vt}"
        )
    expected = {
        "graphical-session-type": "wayland",
        "graphical-session-active": "yes",
        "graphical-target": "active",
        "gdm-service": "active",
    }
    for key, value in expected.items():
        if _last_value(output, key) != value:
            raise TestFailure(f"The restored graphical contract lost {key}={value}")
    return active


def _validate_tty6_evidence(output: str, returncode: int) -> dict[str, object]:
    if returncode != 0:
        raise TestFailure(
            "tty6 did not display the AnduinOS login banner:\n" + output[-8000:]
        )
    if _last_value(output, "active-vt") != "6":
        raise TestFailure("Ctrl+Alt+F6 did not make tty6 active")
    if _last_value(output, "vcs-device") != "/dev/vcs6":
        raise TestFailure("The tty6 probe did not read the kernel VT screen buffer")
    try:
        size = int(_last_value(output, "vcs-bytes"))
        text = json.loads(_last_value(output, "vcs-text-json"))
    except (ValueError, json.JSONDecodeError) as error:
        raise TestFailure("tty6 returned malformed screen-buffer evidence") from error
    digest = _last_value(output, "vcs-sha256")
    if size <= 0 or re.fullmatch(r"[0-9a-f]{64}", digest) is None:
        raise TestFailure("tty6 returned an empty or unhashed screen buffer")
    if not isinstance(text, str) or "AnduinOS" not in text:
        raise TestFailure("The visible tty6 character cells did not contain AnduinOS")
    if "ubuntu" in text.casefold():
        raise TestFailure("The visible tty6 character cells leaked Ubuntu branding")
    return {"active_vt": 6, "bytes": size, "sha256": digest, "text": text}


def _validate_nextcloud_ppa_evidence(
    output: str,
    returncode: int,
    username: str,
) -> dict[str, str]:
    if returncode != 0:
        raise TestFailure(
            "The public Nextcloud PPA command or source verification failed:\n"
            + output[-12000:]
        )
    expected = {
        "invoking-user": username,
        "command": "sudo add-apt-repository -y ppa:nextcloud-devs/client",
        "repository-command": "passed",
        "source-count": "1",
        "source-signed-by": "yes",
        "nextcloud-ppa-sudo-policy": "removed",
    }
    observed = {key: _last_value(output, key) for key in expected}
    for key, value in expected.items():
        if observed[key] != value:
            raise TestFailure(
                f"The Nextcloud PPA contract returned {key}={observed[key]!r}, "
                f"expected {value!r}"
            )
    codename = _last_value(output, "os-release-codename")
    suite = _last_value(output, "source-suite")
    if not re.fullmatch(r"[a-z][a-z0-9-]*", codename) or suite != codename:
        raise TestFailure(
            f"The PPA suite {suite!r} does not match VERSION_CODENAME={codename!r}"
        )
    source_path = _last_value(output, "source-path")
    if (
        not source_path.startswith("/etc/apt/sources.list.d/")
        or not source_path.endswith((".list", ".sources"))
    ):
        raise TestFailure("The PPA was not represented by a supported APT source file")
    source_uri = _last_value(output, "source-uri")
    index_uri = _last_value(output, "apt-index-uri")
    needle = "ppa.launchpadcontent.net/nextcloud-devs/client/ubuntu"
    if needle not in source_uri or needle not in index_uri:
        raise TestFailure("The installed APT source/index belongs to an unrelated PPA")
    return {
        **observed,
        "codename": codename,
        "source_path": source_path,
        "source_uri": source_uri,
        "index_uri": index_uri,
    }


def _validate_spotify_public_catalog_evidence(
    output: str,
    returncode: int,
) -> dict[str, str]:
    """Accept only a freshly resolved exact Spotify ref from official Flathub."""

    if returncode != 0:
        try:
            classification = _last_value(
                output,
                "spotify-public-failure-class",
            )
            reason = _last_value(output, "spotify-public-failure-reason")
        except TestFailure as error:
            raise TestFailure(
                "The public Spotify catalog probe failed without a valid "
                f"classification (exit {returncode}):\n{output[-12000:]}"
            ) from error
        if classification not in {"external-catalog", "product-regression"}:
            raise TestFailure(
                "The public Spotify catalog probe returned an unknown failure "
                f"class {classification!r}"
            )
        raise TestFailure(
            f"public Spotify catalog failure ({classification}, {reason}, "
            f"exit {returncode}):\n{output[-12000:]}"
        )

    expected = {
        "spotify-public-remote-count": "1",
        "spotify-public-remote-url": _SPOTIFY_REMOTE_URL,
        "spotify-public-appstream-refresh": "passed",
        "spotify-public-ref": _SPOTIFY_REF,
        "spotify-public-app-id": _SPOTIFY_APP_ID,
        "spotify-public-remote": _SPOTIFY_REMOTE,
        "spotify-public-arch": _SPOTIFY_ARCH,
        "spotify-public-failure-class": "none",
        "spotify-public-catalog": "current-and-resolved",
    }
    observed = {key: _last_value(output, key) for key in expected}
    for key, value in expected.items():
        if observed[key] != value:
            raise TestFailure(
                f"The public Spotify contract returned {key}={observed[key]!r}, "
                f"expected {value!r}"
            )
    commit = _last_value(output, "spotify-public-commit")
    if re.fullmatch(r"[0-9a-f]{64}", commit) is None:
        raise TestFailure("The public Spotify ref did not expose a valid commit")
    cached_entry = _last_value(output, "spotify-public-cached-entry")
    expected_entry = "\t".join(
        (
            _SPOTIFY_APP_ID,
            _SPOTIFY_REF,
            _SPOTIFY_ARCH,
            "stable",
            _SPOTIFY_REMOTE,
        )
    )
    if cached_entry != expected_entry:
        raise TestFailure(
            "The refreshed local AppStream cache does not contain exactly the "
            "public Spotify stable ref"
        )
    version = _last_value(output, "flatpak-version")
    if not version.startswith("Flatpak "):
        raise TestFailure("The Spotify catalog probe did not identify Flatpak")
    return {
        **observed,
        "commit": commit,
        "cached_entry": cached_entry,
        "flatpak_version": version,
    }


def _validate_wechat_install_evidence(
    output: str,
    returncode: int,
) -> dict[str, str]:
    """Require the resolved current WeChat ref and its exported launcher."""

    if returncode != 0:
        classification = _safe_failure_class(
            output,
            "wechat-failure-class",
            {"external-catalog", "external-artifact", "product-regression"},
        )
        try:
            reason = _last_value(output, "wechat-failure-reason")
        except TestFailure:
            reason = "malformed-failure-evidence"
        raise TestFailure(
            f"WeChat installation failure ({classification}, {reason}, "
            f"exit {returncode}):\n{output[-16000:]}"
        )

    expected = {
        "wechat-preinstalled": "no",
        "wechat-remote-count": "1",
        "wechat-remote-url": _SPOTIFY_REMOTE_URL,
        "wechat-remote-ref": _WECHAT_REF,
        "wechat-install-command": "passed",
        "wechat-installed-ref": _WECHAT_REF,
        "wechat-installed-origin": _SPOTIFY_REMOTE,
        "wechat-desktop": (
            "/var/lib/flatpak/exports/share/applications/"
            "com.tencent.WeChat.desktop"
        ),
        "wechat-app-id": _WECHAT_APP_ID,
        "wechat-arch": _WECHAT_ARCH,
        "wechat-failure-class": "none",
        "wechat-install": "current-and-verified",
    }
    observed = {key: _last_value(output, key) for key in expected}
    for key, value in expected.items():
        if observed[key] != value:
            raise TestFailure(
                f"The WeChat install contract returned {key}={observed[key]!r}, "
                f"expected {value!r}"
            )
    remote_commit = _last_value(output, "wechat-remote-commit")
    installed_commit = _last_value(output, "wechat-installed-commit")
    if (
        re.fullmatch(r"[0-9a-f]{64}", remote_commit) is None
        or installed_commit != remote_commit
    ):
        raise TestFailure(
            "The installed WeChat deployment does not match the resolved public commit"
        )
    location = _last_value(output, "wechat-installed-location")
    resolved_desktop = _last_value(output, "wechat-desktop-resolved")
    if (
        not location.startswith("/var/lib/flatpak/app/com.tencent.WeChat/")
        or not resolved_desktop.startswith(location.rstrip("/") + "/")
        or not resolved_desktop.endswith("/export/share/applications/com.tencent.WeChat.desktop")
    ):
        raise TestFailure("WeChat's desktop export is outside its verified deployment")
    return {
        **observed,
        "commit": remote_commit,
        "location": location,
        "resolved_desktop": resolved_desktop,
    }


def _validate_cpu_z_download_evidence(
    output: str,
    returncode: int,
) -> dict[str, object]:
    if returncode != 0:
        raise TestFailure(
            "The pinned public CPU-Z download or file contract failed "
            f"with exit {returncode}:\n"
            + output[-12000:]
        )
    expected = {
        "cpu-z-http-code": "200",
        "cpu-z-archive-preexisting": "no",
        "cpu-z-member-preexisting": "no",
        "cpu-z-version": _CPU_Z_VERSION,
        "cpu-z-url": _CPU_Z_URL,
        "cpu-z-archive": _CPU_Z_ARCHIVE,
        "cpu-z-archive-sha256": _CPU_Z_ARCHIVE_SHA256,
        "cpu-z-member": _CPU_Z_MEMBER,
        "cpu-z-member-sha256": _CPU_Z_MEMBER_SHA256,
        "cpu-z-member-size": str(_CPU_Z_MEMBER_SIZE),
        "cpu-z-handler": _CPU_Z_HANDLER,
        "bottles": "absent",
        "public-cpu-z": "downloaded-and-verified",
    }
    observed = {key: _last_value(output, key) for key in expected}
    for key, value in expected.items():
        if observed[key] != value:
            raise TestFailure(
                f"The public CPU-Z contract returned {key}={observed[key]!r}, "
                f"expected {value!r}"
            )
    mime_type = _last_value(output, "cpu-z-mime")
    if mime_type not in _CPU_Z_MIMES:
        raise TestFailure(
            f"The official CPU-Z PE received unsupported MIME type {mime_type!r}"
        )
    return {
        **observed,
        "mime_type": mime_type,
        "member_size": int(observed["cpu-z-member-size"]),
    }


def _validate_distinct_boot_ids(before: str, after: str) -> None:
    if not before or not after or before == after:
        raise TestFailure("Ordinary reboot did not produce a distinct boot ID")


def _json_object(output: str) -> dict[str, object]:
    """Parse a CLI JSON object while rejecting ambiguous mixed output."""

    try:
        value = json.loads(output.strip())
    except json.JSONDecodeError as error:
        raise TestFailure(f"Snapshot CLI returned malformed JSON: {error}") from error
    if not isinstance(value, dict):
        raise TestFailure("Snapshot CLI did not return one JSON object")
    return value


def _validate_rime_evidence(path: Path, expected: str) -> None:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise TestFailure(f"Rime evidence is unavailable or malformed: {error}") from error
    if not isinstance(value, dict) or set(value) != {"expected", "observed", "exact"}:
        raise TestFailure("Rime evidence has an invalid shape")
    if (
        value["expected"] != expected
        or value["observed"] != expected
        or value["exact"] is not True
    ):
        raise TestFailure(
            f"Rime evidence does not prove exact committed text {expected!r}: {value!r}"
        )


def _validate_rollback_health(output: str) -> None:
    required = {
        "docker=absent",
        "root-sentinel=absent",
        "home-sentinel=present",
        "dpkg=ok",
        "apt=ok",
        "boot-artifacts=ok",
        "btrfs-default-subvolume=unchanged",
        "btrfs-staging-roots=absent",
        "recovery-grubenv=empty",
        "confirm-service=success",
        "recovery-pending=absent",
        "rollback-history=confirmed",
        "deployments-ready=target-and-fallback",
        "deployment-roots=verified",
        "active-root=selected-target",
        "snapshot-state=ok",
        "rollback-health=ok",
    }
    observed = {line.strip() for line in output.splitlines()}
    missing = sorted(required - observed)
    if missing:
        raise TestFailure(
            "Rollback evidence is missing required successful oracles: "
            + ", ".join(missing)
        )


def _validate_account_record(output: str, username: str) -> None:
    required = {
        f"account={username}",
        "passwd=present",
        "standard-user=yes",
        "password=usable",
    }
    observed = {line.strip() for line in output.splitlines()}
    missing = sorted(required - observed)
    if missing:
        raise TestFailure(
            "The GNOME-created account record is incomplete: " + ", ".join(missing)
        )


def _validate_account_creation_events(output: str) -> None:
    """Require the real two-stage GNOME Accounts creation workflow.

    Passwords are deliberately absent from this transcript.  The observable
    contract is the semantic route through the UI: choose the explicit
    password policy, advance the details page with Next, submit the password
    page with Add, and observe the created user in Settings.
    """

    events: list[dict[str, object]] = []
    for line in output.splitlines():
        try:
            value = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            events.append(value)

    def index_of(**required: object) -> int:
        for index, event in enumerate(events):
            if all(event.get(key) == value for key, value in required.items()):
                return index
        description = ", ".join(f"{key}={value!r}" for key, value in required.items())
        raise TestFailure(
            "GNOME account creation missed a required semantic UI event: "
            + description
        )

    opened = index_of(
        event="focused-activation",
        target="add_user",
        method="localized-mnemonic",
    )
    radio = index_of(event="set-radio", target="set_password_now")
    details = index_of(
        event="focused-activation",
        target="next",
        method="localized-mnemonic",
    )
    initial = index_of(event="qmp-secret", request="accounts-initial-password")
    confirmation = index_of(
        event="qmp-secret",
        request="accounts-initial-confirmation",
    )
    accepted = index_of(event="password-pair-accepted", context="account-create")
    password = index_of(
        event="focused-activation",
        target="add",
        method="atspi-action",
    )
    password_event = events[password]
    if _normalized_accessible_label(password_event.get("accessible_name")) not in {
        "add",
        "添加",
    }:
        raise TestFailure(
            "GNOME account creation did not activate the exact final Add control"
        )
    if password_event.get("action") not in {"click", "activate", "press"}:
        raise TestFailure(
            "GNOME account creation did not use a real accessible button action"
        )
    if not isinstance(password_event.get("mnemonic_owner_count"), int) or int(
        password_event["mnemonic_owner_count"]
    ) < 2:
        raise TestFailure(
            "GNOME account creation did not prove the duplicate mnemonic was avoided"
        )
    created = index_of(event="user-created")
    if not opened < radio < details < initial < confirmation < accepted < password < created:
        raise TestFailure(
            "GNOME account creation events are out of order; expected "
            "Add User, password policy, Next, both secret requests, password "
            "acceptance, Add, then the created user"
        )


def _normalized_accessible_label(value: object) -> str:
    if not isinstance(value, str):
        return ""
    return re.sub(r"\([A-Za-z]\)", "", value).rstrip(" .…").strip().casefold()


def _validate_graphical_login(output: str, username: str) -> None:
    required = {
        f"graphical-user={username}",
        f"session-name={username}",
        "session-class=user",
        "session-type=wayland",
        "session-active=yes",
        "session-remote=no",
        f"home-owner={username}",
    }
    observed = {line.strip() for line in output.splitlines()}
    missing = sorted(required - observed)
    if missing:
        raise TestFailure(
            "The graphical login evidence is incomplete: " + ", ".join(missing)
        )


def _validate_gdm_login_events(output: str, account: str, full_name: str) -> None:
    events: list[dict[str, object]] = []
    for line in output.splitlines():
        try:
            value = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            events.append(value)

    def locate(**required: object) -> int:
        for index, event in enumerate(events):
            if all(event.get(key) == value for key, value in required.items()):
                return index
        description = ", ".join(f"{key}={value!r}" for key, value in required.items())
        raise TestFailure("GDM login missed a required UI event: " + description)

    target = locate(event="gdm-user-target", account=account)
    selected = locate(event="gdm-user-selected", account=account)
    selection = events[selected]
    if _normalized_accessible_label(selection.get("accessible_name")) not in {
        account.casefold(),
        full_name.casefold(),
    }:
        raise TestFailure("GDM selected an unrelated accessible user label")
    method = selection.get("method")
    if method not in {
        "atspi-action",
        "qmp-atspi-bounds",
        "qmp-atspi-bounds-keyboard",
    }:
        raise TestFailure("GDM user selection was not derived from semantic AT-SPI data")
    selection_attempts = selection.get("selection_attempts")
    if (
        not isinstance(selection_attempts, int)
        or isinstance(selection_attempts, bool)
        or not 1 <= selection_attempts <= 3
    ):
        raise TestFailure("GDM user selection reported an invalid retry count")
    if method == "atspi-action":
        if selection_attempts != 1:
            raise TestFailure("GDM semantic action reported an invalid attempt count")
        click = locate(event="gdm-user-action", account=account)
        action = events[click]
        if action.get("action") not in {"click", "activate", "press"}:
            raise TestFailure("GDM user selection used an unrelated AT-SPI action")
        if action.get("owner_role") not in {"button", "list item"}:
            raise TestFailure("GDM user selection action did not belong to a user tile")
        keyboard = click
    else:
        bounds = selection.get("bounds")
        if (
            not isinstance(bounds, list)
            or len(bounds) != 4
            or any(not isinstance(value, (int, float)) for value in bounds)
            or bounds[0] < 0
            or bounds[1] < 0
            or bounds[2] < 2
            or bounds[3] < 2
        ):
            raise TestFailure("GDM semantic pointer selection has invalid AT-SPI bounds")
        click = locate(event="qmp-click", request="gdm-select-user")
        selection_clicks = [
            event
            for event in events
            if event.get("event") == "qmp-click"
            and event.get("target") == account
            and isinstance(event.get("attempt"), int)
        ]
        if [event.get("attempt") for event in selection_clicks] != list(
            range(1, selection_attempts + 1)
        ):
            raise TestFailure(
                "GDM user selection retries were not derived afresh in order"
            )
        if method == "qmp-atspi-bounds-keyboard":
            keyboard = locate(
                event="qmp-key",
                request="gdm-select-user-submit",
                key="ret",
            )
            keyboard_event = events[keyboard]
            if (
                keyboard_event.get("target") != account
                or keyboard_event.get("attempt") != selection_attempts
            ):
                raise TestFailure(
                    "GDM keyboard activation was not bound to the selected account"
                )
        else:
            keyboard = click
    prompt = locate(event="gdm-password-prompt", account=account)
    prompt_event = events[prompt]
    if (
        prompt_event.get("display_name") != full_name
        or prompt_event.get("cancel_controls") != 1
        or prompt_event.get("account_label_present") is not True
        or prompt_event.get("editable_exposed") is not False
        or prompt_event.get("selection_attempts") != selection_attempts
    ):
        raise TestFailure("GDM did not prove the selected user's hidden password prompt")
    if not target < click <= keyboard < prompt < selected:
        raise TestFailure("GDM semantic user selection events are out of order")
    password = locate(event="qmp-secret", request="gdm-password")
    submitted = locate(
        event="qmp-key",
        request="gdm-password-submit",
        key="ret",
    )
    if not target < click < prompt < selected < password < submitted:
        raise TestFailure(
            "GDM login events are out of order; expected user selection, "
            "password entry, then submission"
        )


def _validate_password_fingerprint_change(before: str, after: str) -> None:
    valid = lambda value: len(value) == 64 and all(  # noqa: E731
        character in "0123456789abcdef" for character in value
    )
    if not valid(before) or not valid(after):
        raise TestFailure("Password fingerprints are malformed")
    if before == after:
        raise TestFailure("GNOME Settings did not change the password hash")


def _validate_password_change_events(output: str) -> None:
    """Require the real GNOME password dialog's authenticated workflow."""

    events: list[dict[str, object]] = []
    for line in output.splitlines():
        try:
            value = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            events.append(value)

    def locate(**required: object) -> int:
        for index, event in enumerate(events):
            if all(event.get(key) == value for key, value in required.items()):
                return index
        description = ", ".join(
            f"{key}={value!r}" for key, value in required.items()
        )
        raise TestFailure(
            "GNOME password change missed a required UI event: " + description
        )

    authenticated_events = [
        (index, event)
        for index, event in enumerate(events)
        if event.get("event") == "current-password-authenticated"
    ]
    if len(authenticated_events) != 1:
        raise TestFailure(
            "GNOME password change must prove exactly one current-password "
            "authentication transition"
        )
    authenticated, authentication = authenticated_events[0]
    tab_count = authentication.get("tab_count")
    if not isinstance(tab_count, int) or isinstance(tab_count, bool) or not (
        0 <= tab_count < 12
    ):
        raise TestFailure(
            "GNOME password change reported an invalid focus-search attempt"
        )
    current_request = f"accounts-current-password-attempt-{tab_count}"
    current_focus = locate(
        event="secret-focus",
        request=current_request,
        method="gnome-dialog-tab-search",
    )
    current_secret = locate(event="qmp-secret", request=current_request)
    new_focus = locate(
        event="secret-focus",
        request="accounts-new-password",
        method="gnome-dialog-focus-chain",
    )
    new_secret = locate(event="qmp-secret", request="accounts-new-password")
    confirmation_focus = locate(
        event="secret-focus",
        request="accounts-new-confirmation",
        method="gnome-dialog-focus-chain",
    )
    confirmation_secret = locate(
        event="qmp-secret",
        request="accounts-new-confirmation",
    )
    accepted = locate(event="password-pair-accepted", context="account-change")
    submitted = locate(
        event="focused-activation",
        target="change",
        method="atspi-action",
    )
    submission = events[submitted]
    if _normalized_accessible_label(submission.get("accessible_name")) not in {
        "change",
        "更改",
    }:
        raise TestFailure(
            "GNOME password change did not activate the exact modal Change control"
        )
    if submission.get("action") not in {"click", "activate", "press"}:
        raise TestFailure(
            "GNOME password change did not use a real accessible button action"
        )
    changed = locate(event="password-changed")
    if not (
        current_focus
        < current_secret
        < authenticated
        < new_focus
        < new_secret
        < confirmation_focus
        < confirmation_secret
        < accepted
        < submitted
        < changed
    ):
        raise TestFailure(
            "GNOME password change events are out of order; expected current "
            "authentication, both replacement secrets, password acceptance, "
            "the exact modal submission, then completion"
        )


def _validate_gdm_user_events(output: str, original: str, secondary: str) -> None:
    events = []
    for line in output.splitlines():
        try:
            value = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict) and value.get("event") == "gdm-users":
            events.append(value)
    if len(events) != 1:
        raise TestFailure("GDM audit did not produce one user-list event")
    accounts = events[0].get("accounts")
    if not isinstance(accounts, list) or set(accounts) != {original, secondary}:
        raise TestFailure(
            f"GDM audit returned the wrong accounts: {accounts!r}"
        )


def _validate_gdm_cursor_contract(output: str) -> None:
    required = {
        "cursor-theme='Fluent-dark-cursors'",
        "cursor-size=32",
        "gdm-brand-asset=present",
    }
    observed = {line.strip() for line in output.splitlines()}
    missing = sorted(required - observed)
    package = any(line.startswith("gdm-brand-package=ii ") for line in observed)
    if missing or not package:
        detail = missing + ([] if package else ["gdm-brand-package=ii …"])
        raise TestFailure(
            "The GDM branding/cursor contract is incomplete: " + ", ".join(detail)
        )


def _join_contract_outputs(*outputs: str) -> str:
    """Keep serial command outputs as separate line-oriented evidence."""

    return "\n".join(output.strip("\n") for output in outputs if output.strip("\n"))


def _event_objects(output: str, kind: str) -> list[dict[str, object]]:
    values: list[dict[str, object]] = []
    for line in output.splitlines():
        try:
            value = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict) and value.get("event") == kind:
            values.append(value)
    return values


def _all_event_objects(output: str) -> list[dict[str, object]]:
    values: list[dict[str, object]] = []
    for line in output.splitlines():
        try:
            value = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict) and isinstance(value.get("event"), str):
            values.append(value)
    return values


def _one_event(
    events: list[dict[str, object]],
    *,
    context: str,
    **required: object,
) -> tuple[int, dict[str, object]]:
    matches = [
        (index, value)
        for index, value in enumerate(events)
        if all(value.get(key) == expected for key, expected in required.items())
    ]
    if len(matches) != 1:
        detail = ", ".join(f"{key}={value!r}" for key, value in required.items())
        raise TestFailure(
            f"{context} requires exactly one semantic event ({detail}); "
            f"observed {len(matches)}"
        )
    return matches[0]


def _validate_alt_tab_events(output: str) -> None:
    events = _all_event_objects(output)
    before, before_event = _one_event(
        events,
        context="Alt+Tab",
        event="shortcut-focus",
        shortcut="alt-tab",
        phase="before",
    )
    forward, _ = _one_event(
        events,
        context="Alt+Tab",
        event="qmp-key",
        request="shortcut-alt-tab-forward",
        key="alt-tab",
    )
    after, after_event = _one_event(
        events,
        context="Alt+Tab",
        event="shortcut-focus",
        shortcut="alt-tab",
        phase="after",
    )
    restore_key, _ = _one_event(
        events,
        context="Alt+Tab",
        event="qmp-key",
        request="shortcut-alt-tab-restore",
        key="alt-tab",
    )
    restored, restored_event = _one_event(
        events,
        context="Alt+Tab",
        event="shortcut-focus",
        shortcut="alt-tab",
        phase="restored",
    )
    fixtures = {
        "AnduinOS Shortcut Window Alpha",
        "AnduinOS Shortcut Window Beta",
    }
    first = before_event.get("window")
    second = after_event.get("window")
    final = restored_event.get("window")
    if {first, second} != fixtures or first == second or final != first:
        raise TestFailure(
            "Alt+Tab did not switch between both fixed fixture windows and restore focus"
        )
    if not before < forward < after < restore_key < restored:
        raise TestFailure("Alt+Tab focus transitions are out of order")


def _validate_super_tab_events(output: str) -> None:
    events = _all_event_objects(output)
    before, _ = _one_event(
        events, context="Super+Tab", event="overview", phase="before", visible=False
    )
    show_key, _ = _one_event(
        events,
        context="Super+Tab",
        event="qmp-key",
        request="shortcut-super-tab-show",
        key="meta_l-tab",
    )
    shown, shown_event = _one_event(
        events, context="Super+Tab", event="overview", phase="shown", visible=True
    )
    nodes = shown_event.get("nodes")
    if not isinstance(nodes, list) or not nodes:
        raise TestFailure("Super+Tab did not expose the semantic Overview panel")
    hide_key, _ = _one_event(
        events,
        context="Super+Tab",
        event="qmp-key",
        request="shortcut-super-tab-hide",
        key="meta_l-tab",
    )
    restored, _ = _one_event(
        events,
        context="Super+Tab",
        event="overview",
        phase="restored",
        visible=False,
    )
    if not before < show_key < shown < hide_key < restored:
        raise TestFailure("Super+Tab Overview transitions are out of order")


def _validate_initial_overview_events(output: str) -> None:
    events = _all_event_objects(output)
    _, value = _one_event(
        events,
        context="Initial Overview",
        event="initial-overview",
        phase="post-login",
    )
    if value.get("visible") is not False or value.get("overview_nodes") != []:
        raise TestFailure("GNOME Overview was visible automatically after login")
    markers = value.get("shell_ready_markers")
    if not isinstance(markers, list) or not markers:
        raise TestFailure(
            "Initial Overview absence was observed before GNOME Shell became accessible"
        )
    stable = value.get("stable_observations")
    if not isinstance(stable, int) or isinstance(stable, bool) or stable < 8:
        raise TestFailure(
            "Initial Overview absence was not stable for eight observations"
        )


def _validate_super_i_events(output: str) -> None:
    events = _all_event_objects(output)
    key, _ = _one_event(
        events,
        context="Super+I",
        event="qmp-key",
        request="shortcut-super-i",
        key="meta_l-i",
    )
    opened, value = _one_event(
        events,
        context="Super+I",
        event="shortcut-window",
        shortcut="super-i",
        focused=True,
    )
    application = value.get("application")
    if not isinstance(application, str) or not any(
        token in application.casefold()
        for token in ("gnome-control-center", "settings", "设置")
    ):
        raise TestFailure("Super+I focused an unrelated application")
    if not key < opened:
        raise TestFailure("Super+I reported Settings before the physical shortcut")


def _validate_settings_about_events(output: str) -> dict[str, object]:
    events = _all_event_objects(output)
    _, value = _one_event(
        events,
        context="GNOME Settings About branding",
        event="settings-about-branding",
    )
    application = value.get("application")
    operating_system = value.get("operating_system")
    bounds = value.get("bounds")
    assets = value.get("assets")
    if not isinstance(application, str) or not any(
        token in application.casefold()
        for token in ("gnome-control-center", "settings", "设置")
    ):
        raise TestFailure("The About branding probe observed an unrelated application")
    if (
        not isinstance(operating_system, str)
        or "anduinos" not in operating_system.casefold()
        or "ubuntu" in operating_system.casefold()
    ):
        raise TestFailure("GNOME Settings did not visibly identify AnduinOS")
    if (
        value.get("page") != "about"
        or value.get("coordinate_space") != "window"
        or not isinstance(value.get("logo_name"), str)
        or value.get("logo_role") not in {"image", "icon"}
        or not isinstance(bounds, list)
        or len(bounds) != 4
        or any(
            isinstance(item, bool) or not isinstance(item, (int, float))
            for item in bounds
        )
        or bounds[0] < 0
        or bounds[1] < 0
        or bounds[2] < 100
        or bounds[3] < 20
    ):
        raise TestFailure("GNOME Settings returned no usable semantic About logo")
    expected_assets = {
        "/usr/share/pixmaps/ubuntu-logo-text.svg",
        "/usr/share/pixmaps/ubuntu-logo-text-dark.svg",
    }
    if not isinstance(assets, list) or len(assets) != 2:
        raise TestFailure("GNOME Settings returned no complete About asset pair")
    observed_assets: set[str] = set()
    for asset in assets:
        if not isinstance(asset, dict):
            raise TestFailure("GNOME Settings returned malformed About asset evidence")
        path = asset.get("path")
        digest = asset.get("sha256")
        rendered = asset.get("rendered_template")
        markers = asset.get("brand_markers")
        if (
            not isinstance(path, str)
            or not isinstance(digest, str)
            or re.fullmatch(r"[0-9a-f]{64}", digest) is None
            or not isinstance(rendered, str)
            or not rendered.startswith("/")
            or markers != ["ANDUINOS", "anduinos"]
        ):
            raise TestFailure(
                "GNOME Settings About asset has no verifiable AnduinOS identity"
            )
        observed_assets.add(path)
    if observed_assets != expected_assets:
        raise TestFailure("GNOME Settings used an unexpected About logo asset pair")
    return value


def _validate_localization_zh_cn_events(output: str) -> None:
    events = _all_event_objects(output)
    _, value = _one_event(
        events,
        context="Simplified Chinese desktop localization",
        event="localization-zh-cn",
    )
    expected = {
        "settings_labels": {"关于", "操作系统"},
        "desktop_labels": {"主目录", "回收站"},
        "arcmenu_labels": {"已固定", "所有应用程序"},
    }
    for field, required in expected.items():
        observed = value.get(field)
        if not isinstance(observed, list) or not required <= set(observed):
            raise TestFailure(
                f"Simplified Chinese localization is incomplete for {field}: "
                f"{observed!r}"
            )


def _validate_swapcontrol_events(output: str) -> dict[str, object]:
    events = _all_event_objects(output)
    _, value = _one_event(
        events,
        context="Swap Control dashboard",
        event="swapcontrol-dashboard",
    )
    application = value.get("application")
    markers = value.get("markers")
    labels = value.get("observed_labels")
    bounds = value.get("bounds")
    if (
        not isinstance(application, str)
        or "swapcontrol" not in application.casefold()
        or value.get("page") != "dashboard"
        or markers != ["dashboard", "memory-overview", "swap", "zram"]
        or not isinstance(labels, dict)
        or set(labels) != set(markers)
        or any(not isinstance(label, str) or not label for label in labels.values())
        or value.get("authentication")
        not in {"authenticated", "not-present"}
        or not isinstance(value.get("accessibility_focus"), bool)
        or value.get("coordinate_space") != "window"
        or not isinstance(bounds, list)
        or len(bounds) != 4
        or any(
            isinstance(item, bool) or not isinstance(item, (int, float))
            for item in bounds
        )
        or bounds[2] < 640
        or bounds[3] < 400
    ):
        raise TestFailure("Swap Control did not expose its real dashboard surface")
    _, authentication = _one_event(
        events,
        context="Swap Control authentication",
        event="swapcontrol-authentication",
        outcome=value["authentication"],
    )
    if value["authentication"] == "authenticated":
        _one_event(
            events,
            context="Swap Control authentication focus",
            event="secret-focus",
            request="swapcontrol-auth-password",
            target="password",
            method="polkit-initial-password-focus",
        )
        _one_event(
            events,
            context="Swap Control authentication secret",
            event="qmp-secret",
            request="swapcontrol-auth-password",
        )
        _one_event(
            events,
            context="Swap Control authentication submission",
            event="qmp-key",
            request="swapcontrol-auth-submit",
            key="ret",
        )
    return value


def _validate_thumbnail_events(
    output: str,
    filename: str,
    username: str,
) -> dict[str, object]:
    events = _all_event_objects(output)
    _, value = _one_event(
        events,
        context=f"Nautilus thumbnail for {filename}",
        event="file-thumbnail",
        filename=filename,
    )
    expected_uri = f"file:///home/{username}/Downloads/{filename}"
    cache_path = value.get("cache_path")
    visible = value.get("visible_nodes")
    if (
        value.get("uri") != expected_uri
        or not isinstance(cache_path, str)
        or re.fullmatch(
            rf"/home/{re.escape(username)}/\.cache/thumbnails/"
            r"(?:normal|large|x-large|xx-large)/[0-9a-f]{32}\.png",
            cache_path,
        )
        is None
        or isinstance(value.get("cache_size"), bool)
        or not isinstance(value.get("cache_size"), int)
        or value["cache_size"] <= 128
        or not isinstance(visible, list)
        or not visible
        or not any(
            isinstance(item, dict) and item.get("name") == filename
            for item in visible
        )
    ):
        raise TestFailure(f"Nautilus returned invalid thumbnail evidence for {filename}")
    return value


def _validate_cpu_z_events(output: str, username: str) -> dict[str, object]:
    events = _all_event_objects(output)
    thumbnail_index, _ = _one_event(
        events,
        context="public CPU-Z thumbnail",
        event="file-thumbnail",
        filename=_CPU_Z_MEMBER,
    )
    thumbnail = _validate_thumbnail_events(output, _CPU_Z_MEMBER, username)
    opened_index, opened = _one_event(
        events,
        context="public CPU-Z Nautilus activation",
        event="nautilus-open",
        filename=_CPU_Z_MEMBER,
    )
    launcher_index, launcher = _one_event(
        events,
        context="public CPU-Z EXE Runner",
        event="cpu-z-public-recommendation",
        filename=_CPU_Z_MEMBER,
        application="AnduinOS Windows EXE Runner",
        bottles_installed=False,
    )
    observed = opened.get("observed")
    allowed = {
        "Installing CPU-Z?",
        "正在安装 CPU-Z？",
    }
    processes = launcher.get("runner_processes")
    if observed not in allowed:
        raise TestFailure(
            "The real CPU-Z file opened an unrelated desktop surface: "
            f"{observed!r}"
        )
    if (
        not isinstance(processes, list)
        or not processes
        or not all(
            isinstance(value, str)
            and "anduinos-exe-runner" in value
            and _CPU_Z_MEMBER in value
            for value in processes
        )
    ):
        raise TestFailure("The CPU-Z launcher event has no real handler process")
    if launcher.get("heading") not in allowed:
        raise TestFailure("The CPU-Z native recommendation has the wrong heading")
    reasons = {
        "CPU-X is a native Linux application that perfectly mirrors CPU-Z in functionality and interface, without the need for Windows sandboxing.",
        "CPU-X 是一款原生 Linux 应用程序，在功能和界面方面完美复刻了 CPU-Z，且无需依赖 Windows 沙盒环境。",
    }
    if launcher.get("reason") not in reasons:
        raise TestFailure("The CPU-Z recommendation did not explain the native alternative")
    controls = launcher.get("controls")
    if not isinstance(controls, dict) or set(controls) != {
        "cancel",
        "force_run",
        "cpux_get",
    }:
        raise TestFailure("The CPU-Z recommendation omitted a required action")
    allowed_names = {
        "cancel": {"Cancel", "取消"},
        "force_run": {"Force Run Anyway", "仍要强制运行"},
        "cpux_get": {"Get CPU-X", "获取 CPU-X"},
    }
    for key, names in allowed_names.items():
        value = controls.get(key)
        if (
            not isinstance(value, dict)
            or value.get("name") not in names
            or value.get("role") not in {"button", "push button"}
            or value.get("enabled") is not True
            or value.get("showing") is not True
        ):
            raise TestFailure(f"The CPU-Z recommendation action {key!r} is unusable")
    if not thumbnail_index < opened_index < launcher_index:
        raise TestFailure(
            "CPU-Z evidence is out of order; preview must precede desktop dispatch"
        )
    return thumbnail


def _validate_image_open_events(output: str) -> dict[str, object]:
    events = _all_event_objects(output)
    _, value = _one_event(
        events,
        context="Loupe image fixture",
        event="image-opened",
        filename="AnduinOS-Image.png",
    )
    application = value.get("application")
    visible = value.get("visible_names")
    if (
        not isinstance(application, str)
        or not any(
            token in application.casefold()
            for token in ("loupe", "image viewer", "图像查看器")
        )
        or value.get("process_running") is not True
        or not isinstance(visible, list)
        or not visible
    ):
        raise TestFailure("Loupe did not return a real visible image window")
    return value


def _validate_video_open_events(output: str) -> dict[str, object]:
    events = _all_event_objects(output)
    _, value = _one_event(
        events,
        context="Celluloid video fixture",
        event="video-opened",
        filename="AnduinOS-Video.mp4",
    )
    application = value.get("application")
    destination = value.get("mpris_destination")
    position = value.get("position_microseconds")
    if (
        not isinstance(application, str)
        or "celluloid" not in application.casefold()
        or not isinstance(destination, str)
        or not destination.startswith("org.mpris.MediaPlayer2.")
        or "celluloid" not in destination.casefold()
        or isinstance(position, bool)
        or not isinstance(position, int)
        or position <= 100_000
        or value.get("metadata_identifies_fixture") is not True
        or value.get("playback_status") not in {"Playing", "Paused"}
    ):
        raise TestFailure("Celluloid did not play the exact video fixture")
    return value


def _validate_deb_software_events(output: str) -> dict[str, object]:
    events = _all_event_objects(output)
    _, value = _one_event(
        events,
        context="GNOME Software local DEB",
        event="deb-software",
        filename="anduinos-acceptance-fixture_1.0_all.deb",
    )
    application = value.get("application")
    details = value.get("detail_names")
    if (
        not isinstance(application, str)
        or not any(
            token in application.casefold() for token in ("software", "软件")
        )
        or not isinstance(details, list)
        or not details
        or value.get("package_installed") is not False
    ):
        raise TestFailure("GNOME Software did not expose the harmless DEB safely")
    return value


def _validate_chinese_editor_events(output: str) -> dict[str, object]:
    events = _all_event_objects(output)
    _, value = _one_event(
        events,
        context="GNOME Text Editor Chinese fixture",
        event="chinese-editor",
        filename="AnduinOS-Chinese.txt",
    )
    expected = "变角次亮采之门"
    application = value.get("application")
    if (
        not isinstance(application, str)
        or not any(
            token in application.casefold()
            for token in ("gnome-text-editor", "text editor", "文本编辑器")
        )
        or value.get("expected") != expected
        or value.get("observed") != expected
        or value.get("character_count") != len(expected)
        or value.get("utf8_sha256")
        != hashlib.sha256((expected + "\n").encode("utf-8")).hexdigest()
        or value.get("implicit_trailing_newline") is not True
        or value.get("process_running") is not True
        or value.get("saved") is not True
    ):
        raise TestFailure(
            "GNOME Text Editor did not preserve the exact normalized Chinese text"
        )
    save_events = [
        event
        for event in events
        if event.get("event") == "qmp-click"
        and event.get("request") == "chinese-editor-save-menu-row"
        and event.get("target") == "Save"
        and event.get("anchor") == "fixed-1280x800-framebuffer"
        and event.get("framebuffer") == [1280, 800]
        and event.get("button") == "left"
    ]
    if len(save_events) != 1:
        raise TestFailure("GNOME Text Editor Save menu row was not clicked")
    for index, _character in enumerate(expected):
        required = (
            ("qmp-key", f"chinese-editor-unicode-{index}-start", "ctrl-shift-u"),
            ("qmp-text", f"chinese-editor-unicode-{index}-codepoint", None),
            ("qmp-key", f"chinese-editor-unicode-{index}-commit", "ret"),
        )
        for event_name, request, key in required:
            matches = [
                event
                for event in events
                if event.get("event") == event_name
                and event.get("request") == request
                and (key is None or event.get("key") == key)
            ]
            if len(matches) != 1:
                raise TestFailure(
                    "GNOME Text Editor Unicode text was not delivered by host input"
                )
    return value


def _validate_super_u_events(output: str) -> None:
    events = _all_event_objects(output)
    before, before_event = _one_event(
        events,
        context="Super+U",
        event="network-stats",
        phase="before",
        visible=False,
    )
    show_key, _ = _one_event(
        events,
        context="Super+U",
        event="qmp-key",
        request="shortcut-super-u-show",
        key="meta_l-u",
    )
    shown, shown_event = _one_event(
        events,
        context="Super+U",
        event="network-stats",
        phase="shown",
        visible=True,
    )
    hide_key, _ = _one_event(
        events,
        context="Super+U",
        event="qmp-key",
        request="shortcut-super-u-hide",
        key="meta_l-u",
    )
    restored, restored_event = _one_event(
        events,
        context="Super+U",
        event="network-stats",
        phase="restored",
        visible=False,
    )
    inactive = {"INITIALIZED", "INACTIVE", "DISABLED"}
    active = {"ACTIVE", "ENABLED"}
    if before_event.get("state") not in inactive:
        raise TestFailure("Network Stats did not begin inactive")
    if shown_event.get("state") not in active:
        raise TestFailure("Super+U did not activate Network Stats")
    if not isinstance(shown_event.get("nodes"), list) or not shown_event["nodes"]:
        raise TestFailure("Super+U produced no visible semantic Network Stats node")
    if restored_event.get("state") not in inactive:
        raise TestFailure("A second Super+U did not restore Network Stats")
    if not before < show_key < shown < hide_key < restored:
        raise TestFailure("Super+U Network Stats transitions are out of order")


def _validate_screenshot_shortcut_events(output: str) -> dict[str, object]:
    events = _all_event_objects(output)
    open_key, _ = _one_event(
        events,
        context="Super+Shift+S",
        event="qmp-key",
        request="shortcut-screenshot-open",
        key="meta_l-shift-s",
    )
    interface, ui = _one_event(
        events,
        context="Super+Shift+S",
        event="screenshot-ui",
        visible=True,
    )
    modes = ui.get("modes")
    if (
        not isinstance(modes, list)
        or len(modes) != 3
        or any(not isinstance(mode, str) or not mode for mode in modes)
        or ui.get("completion") != "focused-default-action"
    ):
        raise TestFailure("The screenshot interface did not expose all three modes")
    capture_key, _ = _one_event(
        events,
        context="Super+Shift+S",
        event="qmp-key",
        request="shortcut-screenshot-capture",
        key="ret",
    )
    created, result = _one_event(
        events,
        context="Super+Shift+S",
        event="screenshot-created",
        png_signature=True,
    )
    path = result.get("path")
    size = result.get("size")
    if (
        not isinstance(path, str)
        or not path.startswith("/")
        or not path.casefold().endswith(".png")
        or isinstance(size, bool)
        or not isinstance(size, int)
        or size <= 1024
    ):
        raise TestFailure("The screenshot shortcut returned invalid PNG metadata")
    if not open_key < interface < capture_key < created:
        raise TestFailure("Super+Shift+S capture events are out of order")
    return result


def _validate_start_button_events(output: str) -> dict[str, object]:
    events = _all_event_objects(output)
    button, value = _one_event(
        events,
        context="Start button",
        event="start-button",
    )
    bounds = value.get("bounds")
    rendered_size = value.get("rendered_size")
    digest = value.get("asset_sha256")
    if (
        not isinstance(bounds, list)
        or len(bounds) != 4
        or any(
            isinstance(item, bool) or not isinstance(item, (int, float))
            for item in bounds
        )
        or not isinstance(value.get("bounds_usable"), bool)
        or not isinstance(rendered_size, list)
        or len(rendered_size) != 2
        or any(
            isinstance(item, bool) or not isinstance(item, int) or item < 16
            for item in rendered_size
        )
        or not isinstance(digest, str)
        or re.fullmatch(r"[0-9a-f]{64}", digest) is None
        or not isinstance(value.get("asset"), str)
        or value["asset"]
        != "/usr/share/gnome-shell/extensions/arcmenu@arcmenu.com/icons/anduinos-logo.svg"
        or not isinstance(value.get("rendered_template"), str)
        or not str(value["rendered_template"]).startswith("/")
    ):
        raise TestFailure("The Start button did not identify a valid rendered asset")
    key, _ = _one_event(
        events,
        context="Start button",
        event="qmp-key",
        request="start-button-open",
        key="meta_l",
    )
    shown, menu = _one_event(
        events,
        context="Start button",
        event="start-menu",
        phase="shown",
        overview_visible=False,
    )
    markers = menu.get("markers")
    if (
        not isinstance(markers, list)
        or "已固定" not in markers
        or "所有应用程序" not in markers
        or not isinstance(menu.get("marker_roles"), list)
    ):
        raise TestFailure("Super did not expose ArcMenu's semantic menu markers")
    escape, _ = _one_event(
        events,
        context="Start button",
        event="qmp-key",
        request="start-button-close",
        key="esc",
    )
    restored, _ = _one_event(
        events,
        context="Start button",
        event="start-menu",
        phase="restored",
        visible=False,
    )
    if not button < key < shown < escape < restored:
        raise TestFailure("Start button menu transitions are out of order")
    return value


def _validate_start_button_contract(
    output: str,
    event: dict[str, object],
) -> None:
    asset = event.get("asset")
    digest = event.get("asset_sha256")
    if not isinstance(asset, str) or not isinstance(digest, str):
        raise TestFailure("The Start button event has no installed asset identity")
    required = {
        f"menu-button-icon='{asset}'",
        f"{digest}  {asset}",
    }
    lines = {line.strip() for line in output.splitlines() if line.strip()}
    if not required.issubset(lines):
        raise TestFailure(
            "ArcMenu configuration and the rendered Start asset do not share "
            "one exact installed identity"
        )
    sizes = [
        line.split("=", 1)[1]
        for line in lines
        if line.startswith("menu-button-icon-size=")
    ]
    try:
        valid_size = len(sizes) == 1 and 16 <= float(sizes[0]) <= 64
    except ValueError:
        valid_size = False
    if not valid_size:
        raise TestFailure("ArcMenu returned an invalid Start icon size contract")


def _validate_panel_pin_initial_events(output: str) -> dict[str, object]:
    events = _all_event_objects(output)
    opened, _ = _one_event(
        events,
        context="Panel pin",
        event="qmp-key",
        request="panel-pin-search-open",
        key="meta_l",
    )
    typed, _ = _one_event(
        events,
        context="Panel pin",
        event="qmp-text",
        request="panel-pin-search-text",
    )
    result, search = _one_event(
        events,
        context="Panel pin",
        event="start-search-result",
        query="AnduinOS Panel Acceptance Fixture",
        accessible_name="AnduinOS Panel Acceptance Fixture",
        application="gnome-shell",
    )
    # GNOME 50 exposes ArcMenu's actionable St search actor as `text` even
    # though the guest resolved a real Atspi.Action ancestor.  Do not infer
    # actionability from that lossy role alone: the exact Shell owner/name and
    # the subsequently observed menu, physical-key activation, launcher, and
    # session persistence form the behavioral oracle.
    if search.get("role") not in {
        "button",
        "menu item",
        "list item",
        "label",
        "text",
    }:
        raise TestFailure("Panel pin search result has an unsupported Shell role")
    if search.get("stable_observations") != 4:
        raise TestFailure("Panel pin used an unstable ArcMenu search result")
    focused, _ = _one_event(
        events,
        context="Panel pin",
        event="search-entry-focus",
        query="AnduinOS Panel Acceptance Fixture",
        role="text",
        application="gnome-shell",
        focused=True,
    )
    context_plan, _ = _one_event(
        events,
        context="Panel pin",
        event="search-result-context",
        target="AnduinOS Panel Acceptance Fixture",
        query="AnduinOS Panel Acceptance Fixture",
        application="gnome-shell",
        focused=True,
        method="search-entry-popup-menu",
    )
    context, _ = _one_event(
        events,
        context="Panel pin",
        event="qmp-key",
        request="panel-pin-context",
        key="shift-f10",
    )
    plan, activated = _validate_context_menu_keyboard(
        events,
        context="Panel pin",
        target="taskbar_pin",
        localized="添加到任务栏",
        request_prefix="panel-pin-action",
    )
    pinned, pinned_event = _one_event(
        events,
        context="Panel pin",
        event="panel-pinned",
        application="AnduinOS Panel Acceptance Fixture",
        menu_label="添加到任务栏",
        launcher_name="AnduinOS Panel Acceptance Fixture",
    )
    if pinned_event.get("launcher_role") not in {"button", "toggle button"}:
        raise TestFailure("Panel pin produced no semantic taskbar launcher")
    if not (
        opened
        < typed
        < result
        < focused
        < context_plan
        < context
        < plan
        < activated
        < pinned
    ):
        raise TestFailure("Panel pin UI events are out of order")
    return pinned_event


def _validate_panel_pin_persisted_events(output: str) -> dict[str, object]:
    events = _all_event_objects(output)
    _, persisted = _one_event(
        events,
        context="Panel pin persistence",
        event="panel-pinned-after-login",
        application="AnduinOS Panel Acceptance Fixture",
        launcher_name="AnduinOS Panel Acceptance Fixture",
        visible=True,
    )
    if persisted.get("launcher_role") not in {"button", "toggle button"}:
        raise TestFailure("The recreated Shell exposed no fixture launcher")
    return persisted


def _validate_panel_pin_roundtrip(
    initial: dict[str, object],
    persisted: dict[str, object],
    *,
    before_session: str,
    after_session: str,
) -> None:
    if not before_session or not after_session or before_session == after_session:
        raise TestFailure("Panel pin was not verified across a fresh Shell session")
    if (
        initial.get("application") != persisted.get("application")
        or initial.get("launcher_name") != persisted.get("launcher_name")
        or persisted.get("visible") is not True
    ):
        raise TestFailure("The pinned launcher did not persist across Shell recreation")


def _validate_panel_remove_events(output: str) -> None:
    events = _all_event_objects(output)
    context, click_event = _one_event(
        events,
        context="Panel remove",
        event="qmp-click",
        request="panel-remove-context",
        button="right",
    )
    if click_event.get("target") != "AnduinOS Panel Acceptance Fixture":
        raise TestFailure("Panel remove right-clicked an unrelated launcher")
    plan, activated = _validate_context_menu_keyboard(
        events,
        context="Panel remove",
        target="taskbar_unpin",
        localized="从任务栏中移除",
        request_prefix="panel-remove-action",
    )
    removed, value = _one_event(
        events,
        context="Panel remove",
        event="panel-removed",
        application="AnduinOS Panel Acceptance Fixture",
        localized_label="从任务栏中移除",
        launcher_visible=False,
    )
    if (
        not context < plan < activated < removed
        or value.get("launcher_visible") is not False
    ):
        raise TestFailure("The localized panel action did not remove the launcher")


def _validate_indicator_fixture_process(
    value: object,
    context: str,
) -> dict[str, object]:
    if not isinstance(value, dict) or set(value) != {
        "pid",
        "uid",
        "start_time_ticks",
        "command",
    }:
        raise TestFailure(f"{context} returned malformed fixture process fields")
    for key in ("pid", "start_time_ticks"):
        if not isinstance(value.get(key), int) or int(value[key]) <= 1:
            raise TestFailure(f"{context} returned invalid {key}")
    if not isinstance(value.get("uid"), int) or int(value["uid"]) < 0:
        raise TestFailure(f"{context} returned an invalid uid")
    if (
        not isinstance(value.get("command"), str)
        or not str(value["command"]).endswith("indicator_fixture.py")
    ):
        raise TestFailure(f"{context} belongs to an unrelated process")
    return value


def _validate_appindicator_roundtrip_events(output: str) -> dict[str, object]:
    events = _all_event_objects(output)
    baseline_index, baseline = _one_event(
        events,
        context="AppIndicator roundtrip",
        event="appindicator-baseline",
        visible=True,
    )
    close_index, _ = _one_event(
        events,
        context="AppIndicator roundtrip",
        event="qmp-key",
        request="appindicator-close-window",
        key="alt-f4",
    )
    hidden_index, hidden = _one_event(
        events,
        context="AppIndicator roundtrip",
        event="appindicator-hidden",
        window_visible=False,
    )
    click_index, click_event = _one_event(
        events,
        context="AppIndicator roundtrip",
        event="spice-double-click",
        request="appindicator-restore-window",
        target="AnduinOS Acceptance Indicator",
        button="left",
        application="gnome-shell",
        clicks=2,
    )
    restored_index, restored = _one_event(
        events,
        context="AppIndicator roundtrip",
        event="appindicator-restored",
        same_process=True,
        visible=True,
    )
    before_process = _validate_indicator_fixture_process(
        baseline.get("process"), "AppIndicator baseline"
    )
    hidden_process = _validate_indicator_fixture_process(
        hidden.get("process"), "hidden AppIndicator fixture"
    )
    restored_process = _validate_indicator_fixture_process(
        restored.get("process"), "restored AppIndicator fixture"
    )
    for observed in (hidden_process, restored_process):
        if (
            observed["pid"] != before_process["pid"]
            or observed["start_time_ticks"] != before_process["start_time_ticks"]
        ):
            raise TestFailure("AppIndicator roundtrip did not preserve the same process")
    for event_value, expected_visible in ((baseline, True), (restored, True)):
        window = event_value.get("window")
        if (
            not isinstance(window, dict)
            or window.get("accessible_name")
            != "AnduinOS Indicator Fixture Window"
            or window.get("role") != "frame"
        ):
            raise TestFailure("AppIndicator did not expose the real GTK fixture window")
        if event_value.get("visible") is not expected_visible:
            raise TestFailure("AppIndicator returned the wrong window visibility")
    indicator = hidden.get("indicator")
    if not isinstance(indicator, dict):
        raise TestFailure("GNOME Shell exposed no AppIndicator details")
    bounds = indicator.get("bounds")
    screen = indicator.get("screen")
    if (
        indicator.get("accessible_name") != "AnduinOS Acceptance Indicator"
        or indicator.get("application") != "gnome-shell"
        or indicator.get("lower_right") is not True
        or not isinstance(bounds, list)
        or len(bounds) != 4
        or not isinstance(screen, list)
        or len(screen) != 2
        or any(
            isinstance(item, bool) or not isinstance(item, (int, float))
            for item in bounds + screen
        )
    ):
        raise TestFailure(
            "GNOME Shell AppIndicator lacks trusted lower-right tray geometry"
        )
    x, y, width, height = bounds
    screen_right, screen_bottom = screen
    if (
        width < 2
        or height < 2
        or x + width / 2 < screen_right * 0.65
        or y + height / 2 < screen_bottom * 0.75
    ):
        raise TestFailure("GNOME Shell AppIndicator is outside the lower-right tray")
    if click_event.get("target") != indicator.get("accessible_name"):
        raise TestFailure("Host input restored an unrelated Shell control")
    if not baseline_index < close_index < hidden_index < click_index < restored_index:
        raise TestFailure("AppIndicator roundtrip evidence is out of order")
    return {
        "process": before_process,
        "indicator": indicator,
        "window": restored["window"],
    }


def _validate_desktop_shortcut_events(output: str) -> None:
    events = _all_event_objects(output)
    opened, _ = _one_event(
        events,
        context="Desktop shortcut",
        event="qmp-key",
        request="desktop-shortcut-search-open",
        key="meta_l",
    )
    typed, _ = _one_event(
        events,
        context="Desktop shortcut",
        event="qmp-text",
        request="desktop-shortcut-search-text",
    )
    result, search = _one_event(
        events,
        context="Desktop shortcut",
        event="start-search-result",
        query="AnduinOS Panel Acceptance Fixture",
        accessible_name="AnduinOS Panel Acceptance Fixture",
        application="gnome-shell",
    )
    if search.get("stable_observations") != 4:
        raise TestFailure("Desktop shortcut used an unstable ArcMenu search result")
    focused, _ = _one_event(
        events,
        context="Desktop shortcut",
        event="search-entry-focus",
        query="AnduinOS Panel Acceptance Fixture",
        role="text",
        application="gnome-shell",
        focused=True,
    )
    context_plan, _ = _one_event(
        events,
        context="Desktop shortcut",
        event="search-result-context",
        target="AnduinOS Panel Acceptance Fixture",
        query="AnduinOS Panel Acceptance Fixture",
        application="gnome-shell",
        focused=True,
        method="search-entry-popup-menu",
    )
    context, _ = _one_event(
        events,
        context="Desktop shortcut",
        event="qmp-key",
        request="desktop-shortcut-context",
        key="shift-f10",
    )
    plan, activated = _validate_context_menu_keyboard(
        events,
        context="Desktop shortcut",
        target="desktop_shortcut_create",
        localized="创建桌面快捷方式",
        request_prefix="desktop-shortcut-action",
    )
    double_click, double_event = _one_event(
        events,
        context="Desktop shortcut",
        event="spice-double-click",
        request="desktop-shortcut-launch",
        button="left",
        clicks=2,
        positioning_clicks=1,
    )
    bounds = double_event.get("bounds")
    if (
        double_event.get("role") != "label"
        or double_event.get("target") != "AnduinOS Panel Acceptance Fixture"
        or double_event.get("accessible_name")
        != "AnduinOS Panel Acceptance Fixture"
        or double_event.get("application") != "gjs"
        or not isinstance(double_event.get("double_click_time_ms"), int)
        or not 100 <= double_event["double_click_time_ms"] <= 5000
        or not isinstance(bounds, list)
        or len(bounds) != 4
        or any(isinstance(value, bool) or not isinstance(value, int) for value in bounds)
        or bounds[2] < 8
        or bounds[3] < 8
    ):
        raise TestFailure("The desktop double-click did not target DING's label hit area")
    launched, value = _one_event(
        events,
        context="Desktop shortcut",
        event="desktop-shortcut",
        application="AnduinOS Panel Acceptance Fixture",
        localized_label="创建桌面快捷方式",
        executable=True,
        trusted=True,
        visible=True,
    )
    path = value.get("path")
    windows = value.get("launched_windows")
    if (
        not isinstance(path, str)
        or not path.startswith("/")
        or not path.endswith("/com.anduinos.AcceptancePanelFixture.desktop")
        or windows != ["AnduinOS Panel Fixture Window"]
    ):
        raise TestFailure("The visible desktop shortcut did not launch the fixture")
    if not (
        opened
        < typed
        < result
        < focused
        < context_plan
        < context
        < plan
        < activated
        < double_click
        < launched
    ):
        raise TestFailure("Desktop shortcut UI events are out of order")


def _validate_desktop_icon_events(output: str) -> None:
    events = _all_event_objects(output)
    _, value = _one_event(
        events,
        context="Default desktop icons",
        event="desktop-default-icons",
    )
    icons = value.get("icons")
    if not isinstance(icons, list) or len(icons) != 2:
        raise TestFailure("Default desktop icon evidence is incomplete")
    by_name = {
        item.get("name"): item for item in icons if isinstance(item, dict)
    }
    if set(by_name) != {"主目录", "回收站"}:
        raise TestFailure("The localized Home and Trash desktop icons are not both visible")
    for name_value, item in by_name.items():
        bounds = item.get("bounds")
        if (
            item.get("role") != "label"
            or item.get("application") != "gjs"
            or not isinstance(bounds, list)
            or len(bounds) != 4
            or any(
                isinstance(component, bool) or not isinstance(component, int)
                for component in bounds
            )
            or bounds[2] < 8
            or bounds[3] < 8
        ):
            raise TestFailure(f"Desktop icon {name_value!r} has no usable DING label")
    frame = value.get("desktop_frame")
    if (
        not isinstance(frame, dict)
        or frame.get("role") != "frame"
        or frame.get("application") != "gjs"
        or not str(frame.get("name", "")).startswith("Desktop Icons")
    ):
        raise TestFailure("DING's desktop frame was not positively identified")
    stable = value.get("stable_observations")
    if not isinstance(stable, int) or isinstance(stable, bool) or stable < 4:
        raise TestFailure("Default desktop icons were not stable for four observations")


def _validate_desktop_terminal_events(output: str) -> None:
    events = _all_event_objects(output)
    context, context_value = _one_event(
        events,
        context="Desktop terminal",
        event="qmp-click",
        request="desktop-background-context",
        target="desktop-background",
        button="right",
    )
    bounds = context_value.get("bounds")
    if (
        context_value.get("role") != "frame"
        or context_value.get("application") != "gjs"
        or not isinstance(bounds, list)
        or len(bounds) != 4
    ):
        raise TestFailure("Desktop context click did not target DING's desktop frame")
    activated, action = _one_event(
        events,
        context="Desktop terminal",
        event="click",
        target="desktop_open_terminal",
    )
    if action.get("accessible_name") not in {
        "Open in Terminal",
        "在终端中打开",
        "打开终端",
    }:
        raise TestFailure("DING did not expose its Open in Terminal action")
    opened, terminal = _one_event(
        events,
        context="Desktop terminal",
        event="desktop-terminal",
        phase="opened",
        visible=True,
    )
    application = terminal.get("application")
    windows = terminal.get("windows")
    directory = terminal.get("directory")
    if (
        not isinstance(application, str)
        or "ptyxis" not in application.casefold()
        or not isinstance(windows, list)
        or not windows
        or not isinstance(directory, str)
        or not directory.startswith("/")
        or Path(directory).name not in {"Desktop", "桌面"}
    ):
        raise TestFailure("Desktop context action did not open Ptyxis in the desktop")
    close_key, _ = _one_event(
        events,
        context="Desktop terminal",
        event="qmp-key",
        request="desktop-terminal-close",
        key="alt-f4",
    )
    closed, _ = _one_event(
        events,
        context="Desktop terminal",
        event="desktop-terminal",
        phase="closed",
        visible=False,
    )
    if not context < activated < opened < close_key < closed:
        raise TestFailure("Desktop terminal UI events are out of order")


def _validate_context_menu_keyboard(
    events: list[dict[str, object]],
    *,
    context: str,
    target: str,
    localized: str,
    request_prefix: str,
) -> tuple[int, int]:
    plan_index, plan = _one_event(
        events,
        context=context,
        event="context-menu-plan",
        target=target,
        accessible_name=localized,
        focus_origin="menu-actor",
    )
    items = plan.get("items")
    target_index = plan.get("target_index")
    down_presses = plan.get("down_presses")
    if (
        not isinstance(items, list)
        or not items
        or not isinstance(target_index, int)
        or isinstance(target_index, bool)
        or not 0 <= target_index < len(items)
        or items[target_index] != localized
        or down_presses != target_index + 1
    ):
        raise TestFailure(f"{context} reported an invalid live menu order")

    previous = plan_index
    for number in range(1, down_presses + 1):
        key_index, _ = _one_event(
            events,
            context=context,
            event="qmp-key",
            request=f"{request_prefix}-down-{number}",
            key="down",
        )
        if key_index <= previous:
            raise TestFailure(f"{context} keyboard navigation is out of order")
        previous = key_index
    return_index, _ = _one_event(
        events,
        context=context,
        event="qmp-key",
        request=f"{request_prefix}-activate",
        key="ret",
    )
    activated_index, activated = _one_event(
        events,
        context=context,
        event="context-menu-activated",
        target=target,
        accessible_name=localized,
        method="qmp-keyboard",
        down_presses=down_presses,
    )
    if not previous < return_index < activated_index:
        raise TestFailure(f"{context} did not activate the planned menu item")
    return plan_index, activated_index


def _validate_spotify_store_events(output: str) -> None:
    events = _all_event_objects(output)
    opened, _ = _one_event(
        events,
        context="Spotify search",
        event="qmp-key",
        request="spotify-search-open",
        key="meta_l",
    )
    typed, _ = _one_event(
        events,
        context="Spotify search",
        event="qmp-text",
        request="spotify-search-text",
    )
    result, search = _one_event(
        events,
        context="Spotify search",
        event="start-search-result",
        query="Spotify",
        accessible_name="Spotify",
        application="gnome-shell",
    )
    if search.get("stable_observations") != 4:
        raise TestFailure("Spotify used an unstable ArcMenu search result")
    focused, _ = _one_event(
        events,
        context="Spotify search",
        event="search-entry-focus",
        query="Spotify",
        role="text",
        application="gnome-shell",
        focused=True,
    )
    activated, activation = _one_event(
        events,
        context="Spotify search",
        event="spotify-result-activated",
        accessible_name="Spotify",
        method="qmp-keyboard",
    )
    activation_key, _ = _one_event(
        events,
        context="Spotify search",
        event="qmp-key",
        request="spotify-result-activate",
        key="ret",
    )
    if activation.get("role") not in {
        "button",
        "menu item",
        "list item",
        "label",
        "text",
    }:
        raise TestFailure("Spotify search activated an unrelated result role")
    details, store = _one_event(
        events,
        context="Spotify search",
        event="spotify-store",
        visible=True,
    )
    application = store.get("application")
    names = store.get("detail_names")
    if (
        not isinstance(application, str)
        or not any(
            token in application.casefold()
            for token in ("gnome-software", "software", "软件")
        )
        or not isinstance(names, list)
        or not any(isinstance(name, str) and name.casefold() == "spotify" for name in names)
    ):
        raise TestFailure("Spotify did not open its real Software details page")
    if not opened < typed < result < focused < activation_key < activated < details:
        raise TestFailure("Spotify search and Software navigation are out of order")


def _validate_wechat_process(value: object, context: str) -> dict[str, object]:
    if not isinstance(value, dict):
        raise TestFailure(f"{context} did not report a process identity object")
    required = {
        "pid",
        "namespace_pid",
        "uid",
        "start_time_ticks",
        "command",
        "executable",
    }
    if set(value) != required:
        raise TestFailure(f"{context} returned malformed process fields")
    for key in ("pid", "namespace_pid", "start_time_ticks"):
        if not isinstance(value.get(key), int) or int(value[key]) <= 1:
            raise TestFailure(f"{context} returned an invalid {key}")
    if not isinstance(value.get("uid"), int) or int(value["uid"]) < 0:
        raise TestFailure(f"{context} returned an invalid uid")
    for key in ("command", "executable"):
        if not isinstance(value.get(key), str) or not value[key]:
            raise TestFailure(f"{context} returned malformed {key}")
    identity = f"{value['command']} {value['executable']}".casefold()
    if "wechat" not in identity and "微信" not in identity:
        raise TestFailure(f"{context} belongs to an unrelated process")
    return value


def _validate_wechat_x11_window(value: object, context: str) -> dict[str, object]:
    if not isinstance(value, dict):
        raise TestFailure(f"{context} did not report an X11 window object")
    required = {
        "id",
        "title",
        "classes",
        "pid",
        "state",
        "map_state",
        "visible",
        "x",
        "y",
        "width",
        "height",
    }
    if set(value) != required:
        raise TestFailure(f"{context} returned malformed X11 fields")
    identifier = value.get("id")
    title = value.get("title")
    classes = value.get("classes")
    if not isinstance(identifier, str) or re.fullmatch(r"0x[0-9a-f]+", identifier) is None:
        raise TestFailure(f"{context} returned an invalid X11 window ID")
    if not isinstance(title, str) or not isinstance(classes, list) or not all(
        isinstance(item, str) for item in classes
    ):
        raise TestFailure(f"{context} returned malformed X11 identity")
    identity = " ".join((title, *classes)).casefold()
    if "wechat" not in identity and "微信" not in identity:
        raise TestFailure(f"{context} belongs to an unrelated X11 client")
    for key in ("pid", "x", "y", "width", "height"):
        if not isinstance(value.get(key), int):
            raise TestFailure(f"{context} returned non-numeric X11 {key}")
    if (
        int(value["pid"]) <= 1
        or int(value["x"]) < 0
        or int(value["y"]) < 0
        or int(value["width"]) < 200
        or int(value["height"]) < 250
        or value.get("map_state") != "IsViewable"
        or value.get("visible") is not True
        or not isinstance(value.get("state"), str)
    ):
        raise TestFailure(f"{context} is not a plausible mapped WeChat window")
    return value


def _validate_wechat_install_events(output: str) -> dict[str, object]:
    events = _all_event_objects(output)
    opened, _ = _one_event(
        events,
        context="WeChat ArcMenu launch",
        event="qmp-key",
        request="wechat-search-open",
        key="meta_l",
    )
    typed, _ = _one_event(
        events,
        context="WeChat ArcMenu launch",
        event="qmp-text",
        request="wechat-search-text",
    )
    result, search = _one_event(
        events,
        context="WeChat ArcMenu launch",
        event="start-search-result",
        query="WeChat",
        accessible_name="WeChat",
        application="gnome-shell",
    )
    if search.get("stable_observations") != 4:
        raise TestFailure("WeChat used an unstable ArcMenu search result")
    focused, _ = _one_event(
        events,
        context="WeChat ArcMenu launch",
        event="search-entry-focus",
        query="WeChat",
        application="gnome-shell",
        focused=True,
    )
    activation, _ = _one_event(
        events,
        context="WeChat ArcMenu launch",
        event="qmp-key",
        request="wechat-result-activate",
        key="ret",
    )
    launched, event_value = _one_event(
        events,
        context="WeChat ArcMenu launch",
        event="wechat-installed-launched",
        search_result="WeChat",
        activation_method="qmp-keyboard",
        application=_WECHAT_APP_ID,
        observation="ewmh-x11",
        visible=True,
    )
    process = _validate_wechat_process(
        event_value.get("process"),
        "launched WeChat",
    )
    main_window = _validate_wechat_x11_window(
        event_value.get("main_window"),
        "launched WeChat",
    )
    windows = event_value.get("windows")
    if not isinstance(windows, list) or main_window not in windows:
        raise TestFailure("WeChat's main window is absent from the EWMH window set")
    if process["namespace_pid"] != main_window["pid"]:
        raise TestFailure("WeChat's EWMH PID was not mapped to its process namespace")
    if not opened < typed < result < focused < activation < launched:
        raise TestFailure("WeChat ArcMenu launch evidence is out of order")
    return {
        "application": _WECHAT_APP_ID,
        "main_window": main_window,
        "process": process,
    }


def _validate_wechat_tray_events(output: str) -> dict[str, object]:
    events = _all_event_objects(output)
    baseline_index, baseline = _one_event(
        events,
        context="WeChat tray roundtrip",
        event="wechat-tray-baseline",
    )
    close_index, _ = _one_event(
        events,
        context="WeChat tray roundtrip",
        event="qmp-key",
        request="wechat-close-to-tray",
        key="alt-f4",
    )
    indicator_index, indicator_event = _one_event(
        events,
        context="WeChat tray roundtrip",
        event="wechat-indicator",
        visible=True,
    )
    click_index, click_event = _one_event(
        events,
        context="WeChat tray roundtrip",
        event="spice-double-click",
        request="wechat-indicator-restore",
        target="WeChat AppIndicator",
        button="left",
        clicks=2,
    )
    restored_index, restored_event = _one_event(
        events,
        context="WeChat tray roundtrip",
        event="wechat-tray-restored",
        same_process=True,
        visible=True,
    )
    before = _validate_wechat_process(
        baseline.get("process"),
        "WeChat before tray minimization",
    )
    hidden = _validate_wechat_process(
        indicator_event.get("process"),
        "WeChat while represented by AppIndicator",
    )
    restored = _validate_wechat_process(
        restored_event.get("process"),
        "WeChat after AppIndicator restoration",
    )
    for observed in (hidden, restored):
        if (
            observed["pid"] != before["pid"]
            or observed["start_time_ticks"] != before["start_time_ticks"]
        ):
            raise TestFailure("WeChat tray roundtrip did not preserve the same process")
    baseline_window = _validate_wechat_x11_window(
        baseline.get("main_window"),
        "WeChat before tray minimization",
    )
    restored_window = _validate_wechat_x11_window(
        restored_event.get("main_window"),
        "WeChat after AppIndicator restoration",
    )
    if (
        before["namespace_pid"] != baseline_window["pid"]
        or restored["namespace_pid"] != restored_window["pid"]
    ):
        raise TestFailure("WeChat tray windows do not belong to the preserved process")
    indicator = indicator_event.get("indicator")
    if not isinstance(indicator, dict) or indicator.get("application") != "gnome-shell":
        raise TestFailure("WeChat indicator was not rendered by GNOME Shell")
    bounds = indicator.get("bounds")
    screen = indicator.get("screen")
    if (
        indicator.get("lower_right") is not True
        or not isinstance(bounds, list)
        or len(bounds) != 4
        or not isinstance(screen, list)
        or len(screen) != 2
        or any(not isinstance(item, (int, float)) for item in bounds + screen)
    ):
        raise TestFailure("WeChat indicator lacks lower-right screen geometry")
    x, y, width, height = bounds
    screen_right, screen_bottom = screen
    if (
        width < 2
        or height < 2
        or x + width / 2 < screen_right * 0.65
        or y + height / 2 < screen_bottom * 0.75
    ):
        raise TestFailure("WeChat AppIndicator is outside the lower-right tray")
    if click_event.get("application") != "gnome-shell":
        raise TestFailure("WeChat AppIndicator restoration did not click GNOME Shell")
    if not baseline_index < close_index < indicator_index < click_index < restored_index:
        raise TestFailure("WeChat tray roundtrip evidence is out of order")
    return {
        "process": before,
        "indicator": indicator,
        "application": restored_event.get("application"),
        "baseline_window": baseline_window,
        "main_window": restored_window,
    }


def _validate_theme_selection(output: str, expected: str) -> None:
    events = _event_objects(output, "theme-selected")
    if len(events) != 1:
        raise TestFailure("Theme selection did not produce one semantic result event")
    event_value = events[0]
    wanted_scheme = "prefer-dark" if expected == "dark" else "default"
    if event_value.get("expected") != expected:
        raise TestFailure("Theme selector reported the wrong requested appearance")
    if event_value.get("color_scheme") != wanted_scheme:
        raise TestFailure(
            "Theme selector did not apply the expected interface color scheme"
        )
    label = event_value.get("localized_label")
    if not isinstance(label, str) or "暗色样式" not in label:
        raise TestFailure(
            "The Chinese GNOME Shell session did not expose a localized theme label"
        )
    transitions = event_value.get("transitions")
    if not isinstance(transitions, list) or not transitions or transitions[-1] != wanted_scheme:
        raise TestFailure("Theme selector evidence contains no real final transition")
    menu_events = _event_objects(output, "theme-menu")
    observed_transitions = [event.get("transition") for event in menu_events]
    if observed_transitions != transitions:
        raise TestFailure(
            "Theme selector did not expose the real Shell menu for every transition"
        )
    if any(
        event.get("method") not in {"opened", "already-open"}
        for event in menu_events
    ):
        raise TestFailure("Theme selector reported an unsupported Shell menu state")


def _validate_theme_marker(output: str, expected: str) -> None:
    events = _event_objects(output, "theme-marker")
    if len(events) != 1:
        raise TestFailure("Theme fixture did not produce one semantic marker event")
    observed = events[0].get("observed")
    if not isinstance(observed, str) or expected not in observed:
        raise TestFailure(
            f"Theme fixture marker is wrong: expected {expected!r}, got {observed!r}"
        )
    if expected.startswith("FIREFOX "):
        if observed != expected:
            raise TestFailure("Firefox did not expose the exact web-page theme marker")
        application = events[0].get("application")
        if not isinstance(application, str) or "firefox" not in application.casefold():
            raise TestFailure("Firefox marker was not owned by the real browser")


def _validate_same_fixture_process(before: int, after: int, framework: str) -> None:
    if before <= 1 or after <= 1 or before != after:
        raise TestFailure(
            f"{framework} fixture restarted during the live theme transition: "
            f"{before} -> {after}"
        )
