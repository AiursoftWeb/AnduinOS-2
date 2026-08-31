"""Configuration, scheduling, dashboard, and policy tests."""

from unit.support import *  # noqa: F403
class MatrixTests(unittest.TestCase):
    def test_matrix_has_the_intended_twelve_unique_scenarios(self):
        matrix = TestMatrix.load(ROOT / "cases/install.json")
        self.assertEqual(12, len(matrix.scenarios))
        self.assertEqual(12, len({item.id for item in matrix.scenarios}))
        self.assertEqual(
            {
                "bios-offline-btrfs",
                "bios-online-btrfs",
                "bios-online-ext4",
                "uefi-nosb-offline-btrfs",
                "uefi-nosb-online-btrfs-ssh-enabled",
                "uefi-nosb-online-btrfs-ssh-toggle",
                "uefi-nosb-online-btrfs-japanese-live-chinese-rime",
                "uefi-nosb-offline-ext4",
                "uefi-nosb-wifi-btrfs",
                "uefi-sb-offline-btrfs",
                "uefi-sb-online-btrfs",
                "uefi-sb-online-ext4",
            },
            {item.id for item in matrix.scenarios},
        )
        self.assertEqual(12, len(matrix.select(Architecture.AMD64)))
        self.assertEqual(7, len(matrix.select(Architecture.ARM64)))

        scenarios = matrix.scenarios
        self.assertEqual(3, sum(item.firmware is Firmware.BIOS for item in scenarios))
        self.assertEqual(
            3,
            sum(item.firmware is Firmware.UEFI_SECURE_BOOT for item in scenarios),
        )
        self.assertEqual(3, sum(item.filesystem is Filesystem.EXT4 for item in scenarios))
        self.assertEqual(1, sum(item.ssh is SshPolicy.ENABLED for item in scenarios))
        self.assertEqual(1, sum(item.ssh is SshPolicy.TOGGLE for item in scenarios))
        self.assertEqual(4, sum(item.network is Network.OFFLINE for item in scenarios))
        self.assertEqual(1, sum(item.network is Network.WIFI for item in scenarios))
        self.assertEqual(4, sum(item.rime for item in scenarios))
        self.assertEqual(1, sum(item.passwordless_sudo for item in scenarios))
        self.assertEqual(1, sum(item.automatic_login for item in scenarios))
        self.assertEqual(1, sum(item.desktop_contracts for item in scenarios))
        persistent = [
            item for item in scenarios if item.live_mode is LiveMode.PERSISTENT
        ]
        self.assertEqual(1, len(persistent))
        self.assertEqual(
            (Architecture.AMD64, Architecture.ARM64),
            persistent[0].architectures,
        )
        self.assertEqual("uefi-nosb-offline-btrfs", persistent[0].id)
        desktop_case = next(item for item in scenarios if item.desktop_contracts)
        self.assertEqual("uefi-nosb-online-btrfs-ssh-enabled", desktop_case.id)
        self.assertTrue(desktop_case.rime)
        self.assertTrue(desktop_case.passwordless_sudo)
        self.assertTrue(desktop_case.automatic_login)
        self.assertEqual(
            "Simplified Chinese (China Mainland)", matrix.defaults.live_grub_entry
        )
        self.assertEqual("zh_CN.UTF-8", matrix.defaults.live_locale)
        self.assertEqual("Asia/Shanghai", matrix.defaults.live_timezone)
        self.assertEqual("us", matrix.defaults.live_keyboard)
        japanese = next(
            item
            for item in scenarios
            if item.id
            == "uefi-nosb-online-btrfs-japanese-live-chinese-rime"
        )
        self.assertEqual(
            LiveRegion(
                grub_entry="Japanese",
                locale="ja_JP.UTF-8",
                timezone="Asia/Tokyo",
                keyboard="jp",
            ),
            japanese.live_region,
        )
        self.assertEqual(
            japanese.live_region,
            scenario_live_region(matrix.defaults, japanese),
        )
        ordinary = next(item for item in scenarios if item.live_region is None)
        self.assertEqual(
            LiveRegion(
                grub_entry="Simplified Chinese (China Mainland)",
                locale="zh_CN.UTF-8",
                timezone="Asia/Shanghai",
                keyboard="us",
            ),
            scenario_live_region(matrix.defaults, ordinary),
        )

    def test_wifi_acceptance_is_amd64_local_only(self):
        raw = json.loads((ROOT / "cases/install.json").read_text(encoding="utf-8"))
        wifi = next(item for item in raw["cases"] if item["network"] == "wifi")
        for mutation in (
            {"architectures": ["arm64"]},
            {"online_features": True},
            {"rime": True},
        ):
            candidate = json.loads(json.dumps(raw))
            selected = next(
                item for item in candidate["cases"] if item["network"] == "wifi"
            )
            selected.update(mutation)
            with tempfile.TemporaryDirectory() as directory:
                path = Path(directory) / "matrix.json"
                path.write_text(json.dumps(candidate), encoding="utf-8")
                with self.assertRaises(ConfigurationError):
                    TestMatrix.load(path)

    def test_unknown_case_is_rejected(self):
        matrix = TestMatrix.load(ROOT / "cases/install.json")
        with self.assertRaises(ConfigurationError):
            matrix.select(Architecture.AMD64, ("does-not-exist",))

    def test_passwordless_sudo_is_a_required_boolean(self):
        raw = json.loads((ROOT / "cases/install.json").read_text(encoding="utf-8"))
        for invalid in (None, 0, 1, "true"):
            candidate = json.loads(json.dumps(raw))
            candidate["cases"][0]["passwordless_sudo"] = invalid
            with tempfile.TemporaryDirectory() as directory:
                path = Path(directory) / "matrix.json"
                path.write_text(json.dumps(candidate), encoding="utf-8")
                with self.assertRaises(ConfigurationError):
                    TestMatrix.load(path)

    def test_live_mode_is_required_and_strict(self):
        raw = json.loads((ROOT / "cases/install.json").read_text(encoding="utf-8"))
        for invalid in (None, "", "ram", "Persistent"):
            candidate = json.loads(json.dumps(raw))
            candidate["cases"][0]["live_mode"] = invalid
            with tempfile.TemporaryDirectory() as directory:
                path = Path(directory) / "matrix.json"
                path.write_text(json.dumps(candidate), encoding="utf-8")
                with self.assertRaises(ConfigurationError):
                    TestMatrix.load(path)

    def test_feature_registry_selects_every_suite_and_validates_sources(self):
        matrix = TestMatrix.load(ROOT / "cases/install.json")
        registry = FeatureSuiteRegistry.load(ROOT / "cases/desktop.json", matrix)
        suites = registry.select(Architecture.AMD64)
        input_suite = next(item for item in suites if item.id == "input-and-appearance")
        shell_suite = next(item for item in suites if item.id == "shell-shortcuts")
        panel_suite = next(
            item for item in suites if item.id == "shell-panel-taskbar"
        )
        desktop_suite = next(
            item for item in suites if item.id == "shell-desktop-shortcut"
        )
        self.assertEqual(
            (
                "input.super-space-rime",
                "input.utf8-chinese-text",
                "appearance.swapcontrol-green",
            ),
            input_suite.checks,
        )
        self.assertIn("tty.tty6-branding", shell_suite.checks)
        self.assertEqual(
            (
                "panel.pin-application",
                "panel.remove-menu-localized",
                "shell.appindicator-roundtrip",
            ),
            panel_suite.checks,
        )
        self.assertEqual(
            (
                "terminal.ptyxis-initial-size",
                "desktop.icons-visible",
                "desktop.context-menu-terminal",
                "desktop.create-shortcut",
            ),
            desktop_suite.checks,
        )
        self.assertEqual(
            (
                "input-and-appearance",
                "system-lifecycle",
                "file-integration",
                "btrfs-rollback",
                "accounts-gdm",
                "desktop-theme",
                "shell-shortcuts",
                "shell-start-menu",
                "shell-panel-taskbar",
                "shell-desktop-shortcut",
                "shell-spotify-store",
                "public-ecosystem",
                "public-wechat",
            ),
            tuple(item.id for item in suites),
        )
        public = next(item for item in suites if item.id == "public-ecosystem")
        self.assertEqual(
            (
                "files.cpuz-thumbnail-and-open",
                "apt.nextcloud-client-ppa",
                "store.spotify-public",
            ),
            public.checks,
        )
        wechat = next(item for item in suites if item.id == "public-wechat")
        self.assertEqual(
            ("app.wechat-install",),
            wechat.checks,
        )
        registry.validate_sources(
            suites,
            matrix,
            Architecture.AMD64,
            {
                "bios-online-btrfs",
                "uefi-nosb-online-btrfs-ssh-toggle",
            },
        )
        with self.assertRaisesRegex(ConfigurationError, "no installation base"):
            registry.validate_sources(
                suites,
                matrix,
                Architecture.AMD64,
                {"bios-offline-btrfs"},
            )

    def test_every_declared_feature_check_has_an_executable_method(self):
        matrix = TestMatrix.load(ROOT / "cases/install.json")
        registry = FeatureSuiteRegistry.load(ROOT / "cases/desktop.json", matrix)
        declared = {check for suite in registry.suites for check in suite.checks}
        self.assertEqual(declared, set(FeatureSuiteRunner.IMPLEMENTATION_METHODS))
        for method in FeatureSuiteRunner.IMPLEMENTATION_METHODS.values():
            self.assertTrue(callable(getattr(FeatureSuiteRunner, method, None)), method)


class FeatureSuiteSchedulingTests(unittest.TestCase):
    @staticmethod
    def _runner():
        runner = object.__new__(FeatureSuiteRunner)
        runner._states = {"first.check": "pending", "second.check": "pending"}
        runner.check_callback = None
        return runner

    @staticmethod
    def _context():
        vm = SimpleNamespace(running=True)
        base = SimpleNamespace(scenario=SimpleNamespace(id="source-case"))
        suite = SimpleNamespace(
            id="feature-suite",
            checks=("first.check", "second.check"),
        )
        return vm, base, suite

    def test_healthy_guest_continues_after_product_assertion_by_default(self):
        runner = self._runner()
        runner._run_check = Mock(side_effect=(TestFailure("first defect"), None))
        vm, base, suite = self._context()

        with tempfile.TemporaryDirectory() as directory, self.assertRaisesRegex(
            TestFailure,
            "1 declared check.*first defect",
        ):
            runner._run_declared_checks(vm, base, suite, Path(directory))

        self.assertEqual(2, runner._run_check.call_count)
        self.assertEqual(
            {"first.check": "failed", "second.check": "passed"},
            runner._states,
        )

    def test_dead_guest_stops_remaining_checks(self):
        runner = self._runner()
        vm, base, suite = self._context()

        def stop_guest(*_args):
            vm.running = False
            raise TestFailure("guest stopped")

        runner._run_check = Mock(side_effect=stop_guest)
        with tempfile.TemporaryDirectory() as directory, self.assertRaisesRegex(
            TestFailure,
            "guest stopped",
        ):
            runner._run_declared_checks(vm, base, suite, Path(directory))

        runner._run_check.assert_called_once()

    def test_protocol_failure_is_never_downgraded_to_a_product_assertion(self):
        runner = self._runner()
        runner._run_check = Mock(side_effect=ProtocolError("serial corrupt"))
        vm, base, suite = self._context()

        with tempfile.TemporaryDirectory() as directory, self.assertRaisesRegex(
            ProtocolError,
            "serial corrupt",
        ):
            runner._run_declared_checks(vm, base, suite, Path(directory))

        runner._run_check.assert_called_once()

    def test_overlay_manifest_writer_has_the_runtime_call_signature(self):
        runner = self._runner()
        base = SimpleNamespace(
            scenario=SimpleNamespace(id="source-case"),
            identity="verified-base",
            disk=Path("base.qcow2"),
        )
        suite = SimpleNamespace(id="desktop-suite", checks=("first.check",))
        vm = SimpleNamespace(config=SimpleNamespace(disk=Path("overlay.qcow2")))
        with tempfile.TemporaryDirectory() as directory:
            artifacts = Path(directory)
            runner._write_manifest(base, suite, vm, artifacts)
            manifest = json.loads(
                (artifacts / "suite-manifest.json").read_text(encoding="utf-8")
            )
        self.assertEqual("desktop-suite", manifest["suite"])
        self.assertEqual("verified-base", manifest["base_identity"])


class DashboardTests(unittest.TestCase):
    def test_closed_output_cannot_mask_the_real_test_state(self):
        class ClosedOutput:
            def isatty(self):
                return False

            def write(self, _value):
                raise OSError(5, "terminal disconnected")

            def flush(self):
                raise OSError(5, "terminal disconnected")

        with tempfile.TemporaryDirectory() as directory:
            dashboard = AcceptanceDashboard(
                ("case",),
                iso=Path(directory) / "test.iso",
                architecture="amd64",
                artifacts=Path(directory) / "artifacts",
                checks={"case": ("live-boot",)},
                stream=ClosedOutput(),
                live=False,
            )
            dashboard.start()
            dashboard.begin("case")
            dashboard.check("case", "live-boot", "failed", "original failure")
            dashboard.complete("case", "failed", 1.0, "original failure")
            dashboard.close()
        self.assertEqual(
            "failed", dashboard.check_results("case")[0]["status"]
        )

    def test_unexpected_output_error_still_fails_closed(self):
        class BrokenDiskOutput:
            def isatty(self):
                return False

            def write(self, _value):
                raise OSError(28, "no space left")

        with tempfile.TemporaryDirectory() as directory:
            dashboard = AcceptanceDashboard(
                ("case",),
                iso=Path(directory) / "test.iso",
                architecture="amd64",
                artifacts=Path(directory),
                stream=BrokenDiskOutput(),
                live=False,
            )
            with self.assertRaisesRegex(OSError, "no space left"):
                dashboard.start()

    def test_plain_dashboard_reports_all_state_transitions(self):
        stream = io.StringIO()
        with tempfile.TemporaryDirectory() as directory:
            dashboard = AcceptanceDashboard(
                ("first-case", "second-case"),
                iso=Path(directory) / "test-amd64.iso",
                architecture="amd64",
                artifacts=Path(directory) / "artifacts",
                checks={"first-case": ("live-boot", "journal.boot-and-idle")},
                stream=stream,
                live=False,
            )
            dashboard.start()
            dashboard.begin("first-case")
            dashboard.check(
                "first-case", "live-boot", "running", "Booting original ISO"
            )
            dashboard.check(
                "first-case", "live-boot", "passed", "Live GNOME is ready"
            )
            dashboard.check(
                "first-case",
                "journal.boot-and-idle",
                "passed",
                "0 blockers; 3 known diagnostics",
            )
            dashboard.phase("first-case", "Booting original ISO")
            dashboard.complete("first-case", "passed", 65.0)
            dashboard.close()
        output = stream.getvalue()
        self.assertIn("NOT STARTED", output)
        self.assertIn("RUNNING", output)
        self.assertIn("PASSED", output)
        self.assertIn("first-case", output)
        self.assertIn("second-case", output)
        self.assertIn("first-case / live-boot", output)
        self.assertIn("first-case / journal.boot-and-idle", output)
        self.assertIn("3 known diagnostics", output)
        self.assertIn("Installation scenarios: 1/2 passed", output)

    def test_plain_dashboard_summary_cannot_hide_a_failed_feature_suite(self):
        stream = io.StringIO()
        with tempfile.TemporaryDirectory() as directory:
            dashboard = AcceptanceDashboard(
                ("base",),
                iso=Path(directory) / "test-amd64.iso",
                architecture="amd64",
                artifacts=Path(directory),
                checks={"base": ("live-boot",)},
                suites={"base": {"desktop-theme": ("appearance.theme-qt",)}},
                live=False,
                stream=stream,
            )
            dashboard.start()
            dashboard.begin("base")
            dashboard.complete("base", "passed", 1.0)
            dashboard.begin_suite("base", "desktop-theme")
            dashboard.complete_suite(
                "base", "desktop-theme", "failed", 2.0, "Qt stayed light"
            )
            dashboard.close()
        output = stream.getvalue()
        self.assertIn("Installation scenarios: 1/1 passed, 0 failed", output)
        self.assertIn("Feature suites: 0/1 passed, 1 failed", output)

    def test_live_dashboard_renders_a_fixed_status_table(self):
        stream = io.StringIO()
        with tempfile.TemporaryDirectory() as directory:
            dashboard = AcceptanceDashboard(
                ("one",),
                iso=Path(directory) / "test-amd64.iso",
                architecture="amd64",
                artifacts=Path(directory) / "artifacts",
                checks={"one": ("live-boot", "files.exe-open-fixture")},
                stream=stream,
                live=True,
                refresh_seconds=60,
            )
            dashboard.start()
            dashboard.begin("one")
            dashboard.check("one", "live-boot", "passed", "Live GNOME is ready")
            dashboard.check(
                "one",
                "files.exe-open-fixture",
                "failed",
                "CPU-Z handler missing",
            )
            dashboard.complete("one", "failed", 2.0, "example failure")
            dashboard.close()
        output = stream.getvalue()
        self.assertIn("AnduinOS ISO Acceptance", output)
        self.assertIn("NOT STARTED", output)
        self.assertIn("RUNNING", output)
        self.assertIn("FAILED", output)
        self.assertIn("example failure", output)
        self.assertIn("Checks — one", output)
        self.assertIn("files.exe-open-fixture", output)
        self.assertIn("CPU-Z handler missing", output)

    def test_dashboard_rejects_an_undeclared_child_event(self):
        with tempfile.TemporaryDirectory() as directory:
            dashboard = AcceptanceDashboard(
                ("one",),
                iso=Path(directory) / "test-amd64.iso",
                architecture="amd64",
                artifacts=Path(directory) / "artifacts",
                checks={"one": ("live-boot",)},
                stream=io.StringIO(),
                live=False,
            )
            with self.assertRaisesRegex(ValueError, "undeclared check"):
                dashboard.check("one", "invented-check", "running")

    def test_dashboard_renders_install_suite_check_hierarchy(self):
        stream = io.StringIO()
        with tempfile.TemporaryDirectory() as directory:
            dashboard = AcceptanceDashboard(
                ("bios-online-btrfs",),
                iso=Path(directory) / "test-amd64.iso",
                architecture="amd64",
                artifacts=Path(directory) / "artifacts",
                checks={"bios-online-btrfs": ("installed-boot",)},
                suites={
                    "bios-online-btrfs": {
                        "input-and-appearance": ("input.super-space-rime",),
                    }
                },
                stream=stream,
                live=False,
            )
            dashboard.start()
            dashboard.begin("bios-online-btrfs")
            dashboard.complete("bios-online-btrfs", "passed", 1.0)
            dashboard.begin_suite("bios-online-btrfs", "input-and-appearance")
            dashboard.suite_check(
                "bios-online-btrfs",
                "input-and-appearance",
                "input.super-space-rime",
                "running",
            )
            dashboard.suite_check(
                "bios-online-btrfs",
                "input-and-appearance",
                "input.super-space-rime",
                "passed",
                "Exact Chinese text committed",
            )
            dashboard.complete_suite(
                "bios-online-btrfs", "input-and-appearance", "passed", 2.0
            )
            dashboard.close()
        output = stream.getvalue()
        self.assertIn("bios-online-btrfs / input-and-appearance", output)
        self.assertIn(
            "bios-online-btrfs / input-and-appearance / input.super-space-rime",
            output,
        )
        self.assertEqual(
            "passed",
            dashboard.suite_results("bios-online-btrfs")[0]["checks"][0]["status"],
        )

    def test_interrupted_reporting_keeps_pending_cases_and_suites(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            dashboard = AcceptanceDashboard(
                ("first", "second"),
                iso=Path("image.iso"),
                architecture="amd64",
                artifacts=root,
                checks={"first": ("first.check",), "second": ("second.check",)},
                suites={
                    "first": {
                        "failed-suite": ("failed.check",),
                        "pending-suite": ("pending.check",),
                    }
                },
                stream=io.StringIO(),
                live=False,
            )
            dashboard.begin("first")
            dashboard.check("first", "first.check", "failed", "injected defect")
            dashboard.complete("first", "failed", 1.25, "injected defect")
            dashboard.begin_suite("first", "failed-suite")
            dashboard.suite_check(
                "first", "failed-suite", "failed.check", "failed", "suite defect"
            )
            dashboard.complete_suite(
                "first", "failed-suite", "failed", 0.5, "suite defect"
            )
            actual_case = SimpleNamespace(
                id="first",
                artifacts=root / "first",
                error="injected defect",
            )
            actual_suite = SimpleNamespace(
                id="failed-suite",
                source_case="first",
                artifacts=root / "first" / "feature-suites" / "failed-suite",
                error="suite defect",
            )
            selected = (SimpleNamespace(id="first"), SimpleNamespace(id="second"))
            suites = (
                SimpleNamespace(
                    id="failed-suite", source_for=lambda _architecture: "first"
                ),
                SimpleNamespace(
                    id="pending-suite", source_for=lambda _architecture: "first"
                ),
            )

            case_records = _materialize_case_results(
                selected, (actual_case,), dashboard, root
            )
            suite_records = _materialize_suite_results(
                suites,
                (actual_suite,),
                dashboard,
                Architecture.AMD64,
                root,
            )

        self.assertEqual(
            ["failed", "pending"], [item["status"] for item in case_records]
        )
        self.assertEqual(
            ["failed", "pending"], [item["status"] for item in suite_records]
        )
        self.assertEqual("pending", case_records[1]["checks"][0]["status"])
        self.assertEqual("pending", suite_records[1]["checks"][0]["status"])

    def test_junit_marks_failed_and_not_started_work_as_non_passing(self):
        summary = {
            "results": [
                {
                    "id": "passed-case",
                    "status": "passed",
                    "seconds": 1.0,
                    "error": "",
                    "checks": [
                        {
                            "id": "passed.check",
                            "status": "passed",
                            "seconds": 0.5,
                            "detail": "proved",
                        }
                    ],
                },
                {
                    "id": "failed-case",
                    "status": "failed",
                    "seconds": 2.0,
                    "error": "broken installer",
                    "checks": [
                        {
                            "id": "failed.check",
                            "status": "failed",
                            "seconds": 0.25,
                            "detail": "bad package",
                        }
                    ],
                },
                {
                    "id": "pending-case",
                    "status": "pending",
                    "seconds": None,
                    "error": "",
                    "detail": "Waiting to start",
                    "checks": [
                        {
                            "id": "pending.check",
                            "status": "pending",
                            "seconds": None,
                            "detail": "Waiting to start",
                        }
                    ],
                },
            ],
            "feature_suites": [],
        }
        with tempfile.TemporaryDirectory() as directory:
            destination = Path(directory) / "junit.xml"
            write_junit_report(summary, destination)
            root = ET.parse(destination).getroot()

        self.assertEqual("6", root.get("tests"))
        self.assertEqual("2", root.get("failures"))
        self.assertEqual("2", root.get("errors"))
        pending = root.find(
            ".//testcase[@classname='installation.pending-case']"
            "[@name='pending.check']/error"
        )
        self.assertIsNotNone(pending)
        assert pending is not None
        self.assertEqual("IncompleteAcceptanceCheck", pending.get("type"))


class ScenarioCheckPlanTests(unittest.TestCase):
    def test_acceptance_declares_every_runtime_child_check(self):
        matrix = TestMatrix.load(ROOT / "cases/install.json")
        scenario = next(item for item in matrix.scenarios if item.desktop_contracts)
        checks = scenario_check_ids(scenario)
        self.assertEqual(len(checks), len(set(checks)))
        for identifier in (
            "regional.grub-contract",
            "live-boot",
            "live.identity-contract",
            "live.temporary-overlay",
            "regional.grub-live-propagation",
            "installer-ui",
            "target-boot-files",
            "boot.uefi-vendor-registration",
            "installed-boot",
            "installed-contracts",
            *RELEASE_CONTRACT_CHECKS,
            "sudo.passwordless-enabled",
            "login.autologin-enabled",
            "regional.installed-zh-cn",
            "theme.cursor-user-session",
            "render.twemoji-water-pistol",
            "files.appimage-open",
            "files.exe-thumbnail-fixture",
            "files.exe-open-fixture",
            "shell.extension-policy",
            "shell.extension-errors",
            "display.spice-resize",
            "snapshots-manager",
            "host-ssh",
            "journal.action-scoped",
            "journal.boot-and-idle",
            "boot.plymouth-anduinos-logo",
        ):
            self.assertIn(identifier, checks)

    def test_persistent_scenario_declares_reboot_overlay_check(self):
        matrix = TestMatrix.load(ROOT / "cases/install.json")
        scenario = next(
            item
            for item in matrix.scenarios
            if item.live_mode is LiveMode.PERSISTENT
        )
        checks = scenario_check_ids(scenario)
        self.assertIn("live.persistent-overlay", checks)
        self.assertNotIn("live.temporary-overlay", checks)

    def test_uefi_registration_gate_runs_before_first_target_boot(self):
        matrix = TestMatrix.load(ROOT / "cases/install.json")
        for scenario in matrix.scenarios:
            checks = scenario_check_ids(scenario)
            with self.subTest(scenario=scenario.id):
                if scenario.firmware.is_uefi:
                    self.assertIn("boot.uefi-vendor-registration", checks)
                    self.assertLess(
                        checks.index("target-boot-files"),
                        checks.index("boot.uefi-vendor-registration"),
                    )
                    self.assertLess(
                        checks.index("boot.uefi-vendor-registration"),
                        checks.index("installed-boot"),
                    )
                else:
                    self.assertNotIn("boot.uefi-vendor-registration", checks)

    def test_sudo_check_id_tracks_each_installation_choice(self):
        matrix = TestMatrix.load(ROOT / "cases/install.json")
        for scenario in matrix.scenarios:
            checks = scenario_check_ids(scenario)
            expected = (
                "sudo.passwordless-enabled"
                if scenario.passwordless_sudo
                else "sudo.password-required"
            )
            unexpected = (
                "sudo.password-required"
                if scenario.passwordless_sudo
                else "sudo.passwordless-enabled"
            )
            with self.subTest(scenario=scenario.id):
                self.assertIn(expected, checks)
                self.assertNotIn(unexpected, checks)

    def test_every_installation_scenario_declares_core_release_contracts(self):
        matrix = TestMatrix.load(ROOT / "cases/install.json")
        for scenario in matrix.scenarios:
            with self.subTest(scenario=scenario.id):
                checks = scenario_check_ids(scenario)
                installed_index = checks.index("installed-contracts")
                self.assertEqual(
                    RELEASE_CONTRACT_CHECKS,
                    checks[
                        installed_index + 1 :
                        installed_index + 1 + len(RELEASE_CONTRACT_CHECKS)
                    ],
                )

    def test_wifi_plan_declares_credential_migration_boundary(self):
        matrix = TestMatrix.load(ROOT / "cases/install.json")
        scenario = next(item for item in matrix.scenarios if item.network is Network.WIFI)
        checks = scenario_check_ids(scenario)
        self.assertIn("installer-ui", checks)
        self.assertIn("network.wifi-migration-hwsim", checks)
        self.assertLess(
            checks.index("installed-boot"),
            checks.index("network.wifi-migration-hwsim"),
        )
        self.assertLess(
            checks.index("network.wifi-migration-hwsim"),
            checks.index("installed-contracts"),
        )

    def test_secure_boot_plan_separates_mok_manager_from_final_enrollment(self):
        matrix = TestMatrix.load(ROOT / "cases/install.json")
        scenario = next(item for item in matrix.scenarios if item.mok_enrollment)
        checks = scenario_check_ids(scenario)
        self.assertLess(
            checks.index("mok-manager-workflow"), checks.index("installed-boot")
        )
        self.assertLess(checks.index("installed-boot"), checks.index("mok-enrollment"))
        self.assertLess(
            checks.index("mok-enrollment"), checks.index("installed-contracts")
        )

    def test_mok_lifecycle_oracle_rejects_every_security_boundary(self):
        fingerprint = "4CE5A1F8F3133BA702C86CC6E92C2271DCD9C1F3"
        pending = f"MOK_PENDING_FINGERPRINT={fingerprint}\n"
        enrolled = (
            "MOK_SECURE_BOOT=enabled\n"
            "MOK_PENDING=none\n"
            f"MOK_ENROLLED_FINGERPRINT={fingerprint}\n"
        )
        _validate_mok_lifecycle_evidence(pending, enrolled)
        faults = {
            "different-certificate": enrolled.replace(fingerprint, "A" * 40),
            "secure-boot-disabled": enrolled.replace("enabled", "disabled"),
            "still-pending": enrolled.replace("MOK_PENDING=none", "MOK_PENDING=present"),
            "malformed-fingerprint": enrolled.replace(fingerprint, "not-a-fingerprint"),
            "duplicate-enrolled-marker": enrolled
            + f"MOK_ENROLLED_FINGERPRINT={fingerprint}\n",
        }
        for label, broken in faults.items():
            with self.subTest(label=label):
                with self.assertRaises(TestFailure):
                    _validate_mok_lifecycle_evidence(pending, broken)

    def test_real_check_boundary_emits_running_and_passed(self):
        scenario = SimpleNamespace(id="child-events")
        events = []
        runner = object.__new__(ScenarioRunner)
        runner._check_details = {}
        runner._check_states = {
            scenario.id: {"journal.boot-and-idle": "pending"}
        }
        runner.check_status = lambda *event: events.append(event)

        with runner._check(scenario, "journal.boot-and-idle"):
            runner._check_note(
                scenario,
                "journal.boot-and-idle",
                "0 blockers; 3 known diagnostics",
            )

        self.assertEqual(
            "passed",
            runner._check_states[scenario.id]["journal.boot-and-idle"],
        )
        self.assertEqual(
            ["running", "running", "passed"],
            [event[2] for event in events],
        )
        self.assertEqual("0 blockers; 3 known diagnostics", events[-1][3])

    def test_scenario_cannot_pass_with_a_phantom_pending_check(self):
        scenario = SimpleNamespace(id="incomplete")
        runner = object.__new__(ScenarioRunner)
        runner._check_states = {
            scenario.id: {"live-boot": "passed", "installer-ui": "pending"}
        }
        with self.assertRaisesRegex(TestFailure, "installer-ui=pending"):
            runner._assert_check_completion(scenario)


class PasswordlessSudoContractTests(unittest.TestCase):
    def test_evidence_oracle_accepts_both_exact_outcomes(self):
        _validate_passwordless_sudo_evidence(
            "\n".join(
                (
                    "SUDO_CONTRACT_SELECTED=enabled",
                    "SUDO_CONTRACT_POLICY=valid",
                    "SUDO_CONTRACT_STATE=anduinostest",
                    "SUDO_CONTRACT_NONINTERACTIVE=root",
                )
            ),
            True,
            "anduinostest",
        )
        _validate_passwordless_sudo_evidence(
            "\n".join(
                (
                    "SUDO_CONTRACT_SELECTED=disabled",
                    "SUDO_CONTRACT_POLICY=absent",
                    "SUDO_CONTRACT_STATE=empty",
                    "SUDO_CONTRACT_NONINTERACTIVE=denied",
                )
            ),
            False,
            "anduinostest",
        )

    def test_evidence_oracle_rejects_every_security_boundary(self):
        passing = "\n".join(
            (
                "SUDO_CONTRACT_SELECTED=enabled",
                "SUDO_CONTRACT_POLICY=valid",
                "SUDO_CONTRACT_STATE=anduinostest",
                "SUDO_CONTRACT_NONINTERACTIVE=root",
            )
        )
        faults = (
            passing.replace("SELECTED=enabled", "SELECTED=disabled"),
            passing.replace("POLICY=valid", "POLICY=absent"),
            passing.replace("STATE=anduinostest", "STATE=another-user"),
            passing.replace("NONINTERACTIVE=root", "NONINTERACTIVE=denied"),
            passing + "\nSUDO_CONTRACT_POLICY=valid",
            passing.replace("SUDO_CONTRACT_POLICY=valid\n", ""),
        )
        for broken in faults:
            with self.subTest(broken=broken):
                with self.assertRaises(TestFailure):
                    _validate_passwordless_sudo_evidence(
                        broken,
                        True,
                        "anduinostest",
                    )

    def test_guest_probe_clears_cache_and_exercises_non_root_sudo(self):
        outcomes = (
            (
                True,
                "\n".join(
                    (
                        "SUDO_CONTRACT_SELECTED=enabled",
                        "SUDO_CONTRACT_POLICY=valid",
                        "SUDO_CONTRACT_STATE=anduinostest",
                        "SUDO_CONTRACT_NONINTERACTIVE=root",
                    )
                ),
            ),
            (
                False,
                "\n".join(
                    (
                        "SUDO_CONTRACT_SELECTED=disabled",
                        "SUDO_CONTRACT_POLICY=absent",
                        "SUDO_CONTRACT_STATE=empty",
                        "SUDO_CONTRACT_NONINTERACTIVE=denied",
                    )
                ),
            ),
        )
        enabled_script = ""
        for enabled, markers in outcomes:
            console = Mock()
            console.run.return_value = CommandResult(markers, 0)
            scenario = SimpleNamespace(passwordless_sudo=enabled)
            with tempfile.TemporaryDirectory() as directory:
                assert_passwordless_sudo_behavior(
                    console,
                    scenario,
                    "anduinostest",
                    Path(directory),
                )
            script = console.run.call_args.args[0]
            if enabled:
                enabled_script = script
            syntax = subprocess.run(
                ("bash", "-n"),
                input=script,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=False,
            )
            with self.subTest(enabled=enabled):
                self.assertEqual("", syntax.stderr)
                self.assertEqual(0, syntax.returncode)
                self.assertIn('runuser -u "$user" -- sudo -K', script)
                self.assertIn("sudo -n -p '' id -u", script)
                self.assertIn("visudo --check --file /etc/sudoers", script)
        self.assertIn("stat -c '%U:%G:%a' \"$policy\"", enabled_script)
