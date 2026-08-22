"""Desktop suite scheduling over immutable installed-system overlays."""

from .context import *  # noqa: F403
from .accounts import AccountChecks
from .applications import PublicApplicationChecks
from .input import InputChecks
from .lifecycle import LifecycleChecks
from .session import SessionChecks
from .shell import ShellChecks
from .theme import ThemeChecks


@dataclass(frozen=True)
class FeatureSuiteResult:
    id: str
    source_case: str
    status: str
    seconds: float
    artifacts: Path
    error: str = ""


class FeatureSuiteRunner(
    AccountChecks,
    PublicApplicationChecks,
    InputChecks,
    LifecycleChecks,
    SessionChecks,
    ShellChecks,
    ThemeChecks,
):
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
        phase_callback: Callable[[str, str, str], None] | None = None,
        check_callback: Callable[[str, str, str, str, str], None] | None = None,
    ) -> None:
        self.options = options
        self.username = username
        self.full_name = full_name
        self.password = password
        self.phase_callback = phase_callback or (lambda _case, _suite, _phase: None)
        self.check_callback = check_callback
        self.framework_root = Path(__file__).parents[2]
        self.driver = GuestUiDriver(self.framework_root / "assertions/guest")
        self.gdm_screenshot_client = (
            self.framework_root / "fixtures/gdm_screenshot_client.py"
        )
        self.btrfs_rollback_oracle = (
            self.framework_root / "assertions/guest/btrfs_rollback_oracle.py"
        )
        self.input_fixture = self.framework_root / "fixtures/input_fixture.py"
        self.shell_fixture = self.framework_root / "fixtures/shell_fixture.py"
        self.shell_desktop_fixture = (
            self.framework_root
            / "fixtures"
            / "com.anduinos.AcceptanceShellFixture.desktop"
        )
        self.panel_fixture = self.framework_root / "fixtures/panel_fixture.py"
        self.indicator_fixture = (
            self.framework_root / "fixtures/indicator_fixture.py"
        )
        self.panel_desktop_fixture = (
            self.framework_root
            / "fixtures"
            / "com.anduinos.AcceptancePanelFixture.desktop"
        )
        self.theme_fixture = self.framework_root / "fixtures/theme_fixture.py"
        self.qt_theme_fixture = self.framework_root / "fixtures/qt_theme_fixture.py"
        self.theme_web_fixture = self.framework_root / "fixtures/theme_fixture.html"
        self.journal_policy = JournalPolicy.load(
            self.framework_root / "assertions/journal-policy.json"
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
        """Run every independent check while the disposable guest is usable.

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
                if not vm.running:
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
