"""Fast self-tests for the QEMU acceptance harness itself."""

from __future__ import annotations

import base64
import hashlib
import io
import json
import os
import re
import runpy
import select
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
import threading
import time
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, call, patch

from PIL import Image, ImageDraw

from iso_test.base import PromotedBase, discard_overlay
from iso_test.errors import ConfigurationError, ProtocolError, TestFailure
from iso_test.assertions import (
    RELEASE_CONTRACT_CHECKS,
    _assert_release_contracts,
    _validate_passwordless_sudo_evidence,
    assert_installed_region,
    assert_live_region,
    assert_passwordless_sudo_behavior,
    assert_release_contract,
)
from iso_test.dashboard import AcceptanceDashboard
from iso_test.cli import (
    _materialize_case_results,
    _materialize_suite_results,
    _termination_as_interrupt,
    _validate_disk_retention,
)
from iso_test.firmware import FirmwareSelection
from iso_test.feature_model import FeatureSuiteRegistry, TestProfile
from iso_test.feature_runner import (
    FeatureSuiteRunner,
    _SHELL_DRIVER_CHECKS,
    _validate_account_record,
    _validate_account_creation_events,
    _validate_alt_tab_events,
    _validate_desktop_shortcut_events,
    _validate_desktop_icon_events,
    _validate_desktop_terminal_events,
    _validate_distinct_boot_ids,
    _validate_deb_software_events,
    _validate_gdm_cursor_contract,
    _validate_gdm_login_events,
    _validate_gdm_user_events,
    _validate_graphical_vt_evidence,
    _validate_graphical_login,
    _validate_initial_overview_events,
    _validate_localization_zh_cn_events,
    _validate_nextcloud_ppa_evidence,
    _validate_spotify_public_catalog_evidence,
    _validate_chinese_editor_events,
    _validate_cpu_z_download_evidence,
    _validate_cpu_z_events,
    _validate_image_open_events,
    _validate_password_change_events,
    _validate_password_fingerprint_change,
    _validate_panel_pin_initial_events,
    _validate_panel_pin_persisted_events,
    _validate_panel_pin_roundtrip,
    _validate_panel_remove_events,
    _validate_appindicator_roundtrip_events,
    _validate_rime_evidence,
    _validate_rollback_health,
    _validate_screenshot_shortcut_events,
    _validate_settings_about_events,
    _validate_swapcontrol_events,
    _validate_same_fixture_process,
    _validate_search_provider_preflight,
    _validate_theme_marker,
    _validate_theme_selection,
    _validate_tty6_evidence,
    _validate_thumbnail_events,
    _validate_super_i_events,
    _validate_super_tab_events,
    _validate_super_u_events,
    _validate_video_open_events,
    _validate_spotify_store_events,
    _validate_wechat_install_evidence,
    _validate_wechat_install_events,
    _validate_wechat_tray_events,
    _validate_start_button_contract,
    _validate_start_button_events,
    _graphical_vt_probe_command,
    _join_contract_outputs,
    _cpu_z_download_command,
    _nextcloud_ppa_source_probe_command,
    _spotify_public_catalog_command,
    _wechat_install_command,
    _tty6_probe_command,
)
from iso_test.grub import (
    _ArmGraphicalGrubCommandLine,
    _GraphicalGrubMenuEditor,
    InstalledBootFiles,
    boot_iso_with_debug_shell,
    debug_kernel_arguments,
    render_installed_grub_instrumentation,
    render_installed_grub_restoration,
    uses_graphical_grub_synchronization,
)
from iso_test.fixtures import _build_pe, build_file_integration_fixtures
from iso_test.iso import _parse_live_entries
from iso_test.model import (
    Architecture,
    Filesystem,
    Firmware,
    Network,
    SshPolicy,
    TestMatrix,
)
from iso_test.qemu import QemuConfig, QemuVm, _file_size_limiter
from iso_test.qmp import QmpClient, _ppm_dimensions
from iso_test.reporting import write_junit_report
from iso_test.visual import (
    grub_editor_left_cursor_y,
    grub_editor_layout,
    grub_frame_difference,
    grub_menu_layout,
)
from iso_test.spice_input import SpiceInputClient
from iso_test.runner import (
    _GRAPHICAL_USER_SCRIPT,
    _SUPPORTED_GUEST_QMP_KEYS,
    ScenarioRunner,
    scenario_check_ids,
    _assert_guest_ssh_stopped,
    _desktop_command,
    _guest_qmp_key_supported,
    _is_gnome_extension_entry,
    _parse_qmp_click_request,
    _parse_spice_double_click_request,
    _parse_qmp_key_request,
    _parse_qmp_secret_request,
    _parse_qmp_text_request,
    _resolve_qmp_secret,
    _run_with_qmp_key_requests,
    _ssh_login,
    _power_off,
    _validate_appimage_fixture_contract,
    _validate_appimage_blocked_events,
    _validate_windows_executable_fixture_contract,
    _validate_windows_executable_open_events,
    _validate_windows_executable_thumbnail_events,
    _validate_installer_output,
    _validate_installed_region_ui_events,
    _validate_mok_lifecycle_evidence,
    _validate_target_boot_integrity,
)
from iso_test.serial import CommandResult, SerialConsole, _fatal_kernel_marker
from iso_test.storage import (
    GIB,
    DiskStorage,
    assert_capacity,
    assert_disk_storage_ready,
    cleanup_disk_storage,
    prepare_disk_storage,
    select_disk_storage,
)
from iso_test.supervisor import (
    FAULT_LOG_ENV,
    _cleanup_persistent_disks,
    run_supervised_worker,
    supervised_main,
)
from iso_test.visual import (
    assert_cpu_z_thumbnail,
    assert_font_fixture,
    assert_fixture_quadrants,
    assert_pointer_motion,
    assert_settings_about_logo,
    assert_start_button_logo,
    assert_swapcontrol_green,
    assert_theme_transition,
    assert_wechat_login_window,
    plymouth_match,
)
from iso_test.wifi import (
    WIFI_LAB_SSID,
    WifiLab,
    _installed_reconnect_script,
    _live_profile_script,
    assert_secret_absent,
    validate_reconnect_evidence,
)


ROOT = Path(__file__).parent


class MatrixTests(unittest.TestCase):
    def test_matrix_has_the_intended_eleven_unique_scenarios(self):
        matrix = TestMatrix.load(ROOT / "matrix.json")
        self.assertEqual(11, len(matrix.scenarios))
        self.assertEqual(11, len({item.id for item in matrix.scenarios}))
        self.assertEqual(
            {
                "bios-offline-btrfs",
                "bios-online-btrfs",
                "bios-online-ext4",
                "uefi-nosb-offline-btrfs",
                "uefi-nosb-online-btrfs-ssh-enabled",
                "uefi-nosb-online-btrfs-ssh-toggle",
                "uefi-nosb-offline-ext4",
                "uefi-nosb-wifi-btrfs",
                "uefi-sb-offline-btrfs",
                "uefi-sb-online-btrfs",
                "uefi-sb-online-ext4",
            },
            {item.id for item in matrix.scenarios},
        )
        self.assertEqual(11, len(matrix.select(Architecture.AMD64)))
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
        self.assertEqual(3, sum(item.rime for item in scenarios))
        self.assertEqual(1, sum(item.passwordless_sudo for item in scenarios))
        self.assertEqual(1, sum(item.automatic_login for item in scenarios))
        self.assertEqual(1, sum(item.desktop_release_gate for item in scenarios))
        release_case = next(item for item in scenarios if item.desktop_release_gate)
        self.assertEqual("uefi-nosb-online-btrfs-ssh-enabled", release_case.id)
        self.assertTrue(release_case.rime)
        self.assertTrue(release_case.passwordless_sudo)
        self.assertTrue(release_case.automatic_login)
        self.assertEqual(
            "Simplified Chinese (China Mainland)", matrix.defaults.live_grub_entry
        )
        self.assertEqual("zh_CN.UTF-8", matrix.defaults.live_locale)
        self.assertEqual("Asia/Shanghai", matrix.defaults.live_timezone)

    def test_wifi_release_gate_is_amd64_local_only(self):
        raw = json.loads((ROOT / "matrix.json").read_text(encoding="utf-8"))
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
        matrix = TestMatrix.load(ROOT / "matrix.json")
        with self.assertRaises(ConfigurationError):
            matrix.select(Architecture.AMD64, ("does-not-exist",))

    def test_passwordless_sudo_is_a_required_boolean(self):
        raw = json.loads((ROOT / "matrix.json").read_text(encoding="utf-8"))
        for invalid in (None, 0, 1, "true"):
            candidate = json.loads(json.dumps(raw))
            candidate["cases"][0]["passwordless_sudo"] = invalid
            with tempfile.TemporaryDirectory() as directory:
                path = Path(directory) / "matrix.json"
                path.write_text(json.dumps(candidate), encoding="utf-8")
                with self.assertRaises(ConfigurationError):
                    TestMatrix.load(path)

    def test_feature_registry_selects_real_profiles_and_verified_sources(self):
        matrix = TestMatrix.load(ROOT / "matrix.json")
        registry = FeatureSuiteRegistry.load(ROOT / "feature-suites.json", matrix)
        release = registry.select(Architecture.AMD64, TestProfile.RELEASE_GATE)
        nightly = registry.select(Architecture.AMD64, TestProfile.NIGHTLY_ONLINE)
        input_suite = next(item for item in release if item.id == "input-and-appearance")
        shell_suite = next(item for item in release if item.id == "shell-shortcuts")
        panel_suite = next(
            item for item in release if item.id == "shell-panel-taskbar"
        )
        desktop_suite = next(
            item for item in release if item.id == "shell-desktop-shortcut"
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
                "accounts-gdm",
                "desktop-theme",
                "shell-shortcuts",
                "shell-start-menu",
                "shell-panel-taskbar",
                "shell-desktop-shortcut",
                "shell-spotify-store",
            ),
            tuple(item.id for item in release),
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
            tuple(item.id for item in nightly),
        )
        public = next(item for item in nightly if item.id == "public-ecosystem")
        self.assertEqual(
            (
                "files.cpuz-thumbnail-and-open",
                "apt.nextcloud-client-ppa",
                "store.spotify-public",
            ),
            public.checks,
        )
        wechat = next(item for item in nightly if item.id == "public-wechat")
        self.assertEqual(
            ("app.wechat-install",),
            wechat.checks,
        )
        registry.validate_sources(
            release,
            matrix,
            Architecture.AMD64,
            {"bios-online-btrfs", "uefi-nosb-online-btrfs-ssh-toggle"},
        )
        registry.validate_sources(
            nightly,
            matrix,
            Architecture.AMD64,
            {
                "bios-online-btrfs",
                "uefi-nosb-online-btrfs-ssh-toggle",
            },
        )
        with self.assertRaisesRegex(ConfigurationError, "no installation base"):
            registry.validate_sources(
                release,
                matrix,
                Architecture.AMD64,
                {"bios-offline-btrfs"},
            )

    def test_platform_lab_cannot_succeed_without_an_executable_runner(self):
        matrix = TestMatrix.load(ROOT / "matrix.json")
        registry = FeatureSuiteRegistry.load(ROOT / "feature-suites.json", matrix)

        with self.assertRaisesRegex(
            ConfigurationError,
            "platform-lab has no executable platform runner configured",
        ):
            registry.select(Architecture.AMD64, TestProfile.PLATFORM_LAB)

    def test_every_declared_feature_check_has_an_executable_method(self):
        matrix = TestMatrix.load(ROOT / "matrix.json")
        registry = FeatureSuiteRegistry.load(ROOT / "feature-suites.json", matrix)
        declared = {check for suite in registry.suites for check in suite.checks}
        self.assertEqual(declared, set(FeatureSuiteRunner.IMPLEMENTATION_METHODS))
        for method in FeatureSuiteRunner.IMPLEMENTATION_METHODS.values():
            self.assertTrue(callable(getattr(FeatureSuiteRunner, method, None)), method)


class FeatureSuiteSchedulingTests(unittest.TestCase):
    @staticmethod
    def _runner(*, fail_fast: bool):
        runner = object.__new__(FeatureSuiteRunner)
        runner.fail_fast = fail_fast
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
        runner = self._runner(fail_fast=False)
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

    def test_fail_fast_stops_before_the_next_declared_check(self):
        runner = self._runner(fail_fast=True)
        runner._run_check = Mock(side_effect=TestFailure("first defect"))
        vm, base, suite = self._context()

        with tempfile.TemporaryDirectory() as directory, self.assertRaisesRegex(
            TestFailure,
            "first defect",
        ):
            runner._run_declared_checks(vm, base, suite, Path(directory))

        runner._run_check.assert_called_once()
        self.assertEqual(
            {"first.check": "failed", "second.check": "pending"},
            runner._states,
        )

    def test_dead_guest_stops_even_without_fail_fast(self):
        runner = self._runner(fail_fast=False)
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
        runner = self._runner(fail_fast=False)
        runner._run_check = Mock(side_effect=ProtocolError("serial corrupt"))
        vm, base, suite = self._context()

        with tempfile.TemporaryDirectory() as directory, self.assertRaisesRegex(
            ProtocolError,
            "serial corrupt",
        ):
            runner._run_declared_checks(vm, base, suite, Path(directory))

        runner._run_check.assert_called_once()


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

    def test_fail_fast_reporting_keeps_pending_cases_and_suites(self):
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
    def test_release_gate_declares_every_runtime_child_check(self):
        matrix = TestMatrix.load(ROOT / "matrix.json")
        scenario = next(item for item in matrix.scenarios if item.desktop_release_gate)
        checks = scenario_check_ids(scenario)
        self.assertEqual(len(checks), len(set(checks)))
        for identifier in (
            "regional.grub-contract",
            "live-boot",
            "regional.grub-live-propagation",
            "installer-ui",
            "target-boot-files",
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

    def test_sudo_check_id_tracks_each_installation_choice(self):
        matrix = TestMatrix.load(ROOT / "matrix.json")
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
        matrix = TestMatrix.load(ROOT / "matrix.json")
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

    def test_smoke_plan_only_declares_the_check_it_executes(self):
        matrix = TestMatrix.load(ROOT / "matrix.json")
        self.assertEqual(
            ("live-boot",),
            scenario_check_ids(matrix.scenarios[0], smoke_only=True),
        )

    def test_wifi_plan_declares_credential_migration_boundary(self):
        matrix = TestMatrix.load(ROOT / "matrix.json")
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
        matrix = TestMatrix.load(ROOT / "matrix.json")
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


class WifiMigrationOracleTests(unittest.TestCase):
    _UUID = "a356839e-2ef2-4f56-abb0-294873676e41"

    def _good_evidence(self):
        return {
            "schema_version": 1,
            "auto_reconnected": True,
            "ssid": WIFI_LAB_SSID,
            "uuid": self._UUID,
            "device": "wlan0",
            "ipv4": "10.77.0.42/24",
            "gateway_reachable": True,
            "ethernet_carrier": "down",
            "profile_path": f"/etc/netplan/90-NM-{self._UUID}.yaml",
            "profile_regular": True,
            "profile_symlink": False,
            "profile_uid": 0,
            "profile_gid": 0,
            "profile_mode": "0600",
            "netplan_mapping": "valid",
        }

    def test_good_reconnect_evidence_passes(self):
        validate_reconnect_evidence(
            self._good_evidence(),
            expected_ssid=WIFI_LAB_SSID,
            expected_uuid=self._UUID,
        )

    def test_generated_wifi_guest_scripts_are_valid_bash(self):
        password = "unit-test-wifi-password"
        scripts = (
            WifiLab(password=password)._setup_script(),
            _live_profile_script(WIFI_LAB_SSID, "wlan0"),
            _installed_reconnect_script(WIFI_LAB_SSID, self._UUID),
        )
        self.assertNotIn(password, scripts[0].splitlines()[0])
        for script in scripts:
            result = subprocess.run(
                ("bash", "-n"),
                input=script,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=False,
            )
            self.assertEqual(0, result.returncode, result.stderr)

    def test_fault_injection_rejects_every_wifi_safety_boundary(self):
        faults = {
            "did-not-autoconnect": {"auto_reconnected": False},
            "wrong-ssid": {"ssid": "Evil-Twin"},
            "wrong-uuid": {"uuid": "b356839e-2ef2-4f56-abb0-294873676e41"},
            "no-dhcp": {"ipv4": "192.0.2.42/24"},
            "gateway-dead": {"gateway_reachable": False},
            "ethernet-fallback": {"ethernet_carrier": "up"},
            "wrong-profile": {"profile_path": "/etc/netplan/wrong.yaml"},
            "profile-symlink": {"profile_symlink": True},
            "profile-not-regular": {"profile_regular": False},
            "profile-owner": {"profile_uid": 1000},
            "profile-group": {"profile_gid": 1000},
            "profile-mode": {"profile_mode": "0644"},
            "mapping-invalid": {"netplan_mapping": "invalid"},
        }
        for label, mutation in faults.items():
            with self.subTest(label=label):
                evidence = self._good_evidence()
                evidence.update(mutation)
                with self.assertRaises(TestFailure):
                    validate_reconnect_evidence(
                        evidence,
                        expected_ssid=WIFI_LAB_SSID,
                        expected_uuid=self._UUID,
                    )

    def test_wifi_secret_artifact_audit_detects_chunk_boundary_leak(self):
        secret = "0123456789abcdef0123456789abcdef"
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            clean = root / "clean.bin"
            clean.write_bytes(b"safe evidence")
            assert_secret_absent(root, secret)
            leaked = root / "serial.log"
            leaked.write_bytes(
                b"A" * (1024 * 1024 - 7)
                + secret.encode("ascii")
                + b"tail"
            )
            with self.assertRaisesRegex(TestFailure, "serial.log"):
                assert_secret_absent(root, secret)

    def test_wifi_secret_artifact_audit_handles_one_byte_secrets(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "clean.bin").write_bytes(b"safe evidence")
            assert_secret_absent(root, "Z")
            (root / "leaked.bin").write_bytes(b"safe evidenceZ")
            with self.assertRaisesRegex(TestFailure, "leaked.bin"):
                assert_secret_absent(root, "Z")


class BootContractTests(unittest.TestCase):
    _GOOD_KERNEL_HASH = "a" * 64

    def test_debug_tty_is_architecture_specific(self):
        self.assertIn("ttyS0", debug_kernel_arguments(Architecture.AMD64))
        self.assertIn("ttyAMA0", debug_kernel_arguments(Architecture.ARM64))
        self.assertIn("systemd.debug_shell", debug_kernel_arguments(Architecture.ARM64))

    def test_grub_synchronization_follows_the_available_console(self):
        self.assertTrue(uses_graphical_grub_synchronization(Architecture.AMD64))
        self.assertFalse(uses_graphical_grub_synchronization(Architecture.ARM64))

    def test_live_region_failure_preserves_observed_values_before_rejecting(self):
        console = Mock()
        console.run.return_value = CommandResult(
            "localectl-status=0\n"
            "timedatectl-status=0\n"
            "system-locale=C.UTF-8\n"
            "timezone=Etc/UTC\n",
            1,
        )
        with tempfile.TemporaryDirectory() as directory:
            evidence = Path(directory)
            with self.assertRaisesRegex(TestFailure, "live-locale-timezone"):
                assert_live_region(
                    console,
                    "zh_CN.UTF-8",
                    "Asia/Shanghai",
                    evidence,
                )
            self.assertIn(
                "system-locale=C.UTF-8",
                (evidence / "live-locale-timezone.txt").read_text(
                    encoding="utf-8"
                ),
            )
        script = console.run.call_args.args[0]
        self.assertNotIn("set -e", script)
        self.assertLess(
            script.index("printf 'system-locale="),
            script.index('test "$system_locale"'),
        )

    def test_live_region_waits_for_a_real_non_gdm_wayland_session(self):
        console = Mock()
        console.run.return_value = CommandResult("", 0)
        with tempfile.TemporaryDirectory() as directory:
            assert_live_region(
                console,
                "zh_CN.UTF-8",
                "Asia/Shanghai",
                Path(directory),
            )
        script = console.run.call_args.args[0]
        self.assertIn("session_deadline=$((SECONDS + 120))", script)
        self.assertIn("while (( SECONDS < session_deadline ))", script)
        self.assertIn("gdm-greeter", script)
        self.assertIn("test -S \"$runtime/bus\"", script)
        self.assertIn('for candidate in "$runtime"/wayland-[0-9]*', script)
        self.assertIn('test -S "$candidate" || continue', script)
        self.assertIn('pgrep -n -u "$uid" -x gnome-shell', script)
        self.assertIn('tr \'\\0\' \'\\n\' < "/proc/$pid/environ"', script)
        self.assertIn('test "$session_ready" = true || status=1', script)
        self.assertNotIn("pgrep -n -f '/usr/bin/gnome-shell'", script)
        self.assertEqual(150, console.run.call_args.kwargs["timeout"])

    def test_live_region_uses_the_requested_session_timeout_with_headroom(self):
        console = Mock()
        console.run.return_value = CommandResult("", 0)
        with tempfile.TemporaryDirectory() as directory:
            assert_live_region(
                console,
                "zh_CN.UTF-8",
                "Asia/Shanghai",
                Path(directory),
                session_timeout_seconds=300,
            )
        self.assertIn(
            "session_deadline=$((SECONDS + 300))",
            console.run.call_args.args[0],
        )
        self.assertEqual(330, console.run.call_args.kwargs["timeout"])

    def test_installed_region_requires_configuration_and_real_gnome_process(self):
        console = Mock()
        console.run.return_value = CommandResult("", 0)
        with tempfile.TemporaryDirectory() as directory:
            evidence = Path(directory)
            assert_installed_region(
                console,
                "anduinostest",
                "zh_CN.UTF-8",
                "Asia/Shanghai",
                evidence,
            )
            self.assertTrue(
                (evidence / "installed-locale-timezone-session.txt").is_file()
            )
        script = console.run.call_args.args[0]
        self.assertIn("/etc/default/locale", script)
        self.assertIn("timedatectl show -p Timezone --value", script)
        self.assertIn('pgrep -n -u "$uid" -x gnome-shell', script)
        self.assertIn("/proc/$session_pid/environ", script)
        self.assertNotIn('test "$session_lang" = zh_CN.UTF-8', script)
        self.assertNotIn('test "$session_language" = zh_CN:zh', script)
        self.assertNotIn("dbus-run-session", script)

    def test_installed_region_ui_oracle_requires_real_localized_ding(self):
        passing = json.dumps(
            {
                "event": "installed-region-zh-cn",
                "desktop_labels": ["主目录", "回收站"],
                "desktop_frame": {
                    "name": "Desktop Icons 1",
                    "role": "frame",
                    "application": "gjs",
                    "bounds": [0, 0, 1280, 752],
                },
            },
            ensure_ascii=False,
        )
        _validate_installed_region_ui_events(passing)
        faults = (
            passing.replace("回收站", "Trash"),
            passing.replace('"application": "gjs"', '"application": "fixture"'),
            passing.replace("1280, 752", "320, 200"),
            passing + "\n" + passing,
        )
        for broken in faults:
            with self.subTest(broken=broken):
                with self.assertRaises(TestFailure):
                    _validate_installed_region_ui_events(broken)

    def test_arm_grub_gates_graphical_commands_then_proves_pl011_handoff(self):
        console = Mock()
        qmp = Mock()

        with (
            patch("iso_test.grub.SpiceInputClient") as input_client,
            patch("iso_test.grub._ArmGraphicalGrubCommandLine") as controller,
        ):
            keyboard = input_client.return_value
            command_line = controller.return_value
            boot_iso_with_debug_shell(
                qmp,
                console,
                Architecture.ARM64,
                firmware_delay=0,
                menu_entry_index=2,
                kernel_arguments=(
                    "boot=casper",
                    "locale=zh_CN.UTF-8",
                    "quiet",
                    "splash",
                    "---",
                ),
                spice_socket=Path("/test/spice.sock"),
            )

        command_line.open.assert_called_once_with(timeout=120)
        self.assertEqual(
            [
                call(
                    "linux /casper/vmlinuz boot=casper locale=zh_CN.UTF-8"
                    + debug_kernel_arguments(Architecture.ARM64),
                    timeout=120,
                ),
                call("initrd /casper/initrd", timeout=120),
            ],
            command_line.submit.call_args_list,
        )
        command_line.boot.assert_called_once_with()
        command_line.close.assert_called_once_with()
        console.wait_for_text.assert_called_once_with(
            "BdsDxe: starting Boot", timeout=120
        )
        console.wait_for_kernel_console.assert_called_once_with(timeout=120)
        input_client.assert_called_once_with(Path("/test/spice.sock"), timeout=30)
        keyboard.connect.assert_called_once_with(require_agent=False)
        keyboard.close.assert_called_once_with()
        controller.assert_called_once_with(qmp, keyboard)

    def test_arm_grub_missing_banner_sends_no_command_or_gpu(self):
        console = Mock()
        console.wait_for_text.side_effect = ProtocolError("injected missing banner")
        qmp = Mock()

        with (
            patch("iso_test.grub.SpiceInputClient") as input_client,
            self.assertRaisesRegex(ProtocolError, "injected missing banner"),
        ):
            boot_iso_with_debug_shell(
                qmp,
                console,
                Architecture.ARM64,
                firmware_delay=0,
                menu_entry_index=0,
                spice_socket=Path("/test/spice.sock"),
            )

        input_client.assert_not_called()
        qmp.assert_not_called()

    def test_arm_qemu_uses_neoverse_and_virtio_scsi(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            code = root / "code.fd"
            variables = root / "vars.fd"
            code.touch()
            variables.touch()
            config = QemuConfig(
                architecture=Architecture.ARM64,
                firmware=Firmware.UEFI_NO_SECURE_BOOT,
                network=Network.ONLINE,
                memory_mib=4096,
                cpus=2,
                disk_gib=20,
                ssh_forward_port=2222,
                iso=root / "test.iso",
                disk=root / "target.qcow2",
                variables=variables,
                firmware_selection=FirmwareSelection(code, variables),
                artifacts=root / "artifacts",
                qemu_binary="qemu-system-aarch64",
                acceleration="tcg,thread=multi",
            )
            vm = QemuVm(config)
            vm._runtime = tempfile.TemporaryDirectory(prefix="anduinos-unit-")
            try:
                rendered = " ".join(vm.command(attach_iso=True))
            finally:
                vm._runtime.cleanup()
                vm._runtime = None
            self.assertIn("neoverse-n1", rendered)
            self.assertNotIn("-cpu max", rendered)
            self.assertIn("virtio-scsi-pci", rendered)
            self.assertIn("scsi-cd", rendered)
            self.assertIn("spicevmc,id=vdagent,name=vdagent", rendered)
            self.assertIn("com.redhat.spice.0", rendered)
            self.assertIn("virtio-gpu-pci,id=video0", rendered)
            self.assertNotIn("grubserial", rendered)
            self.assertNotIn("pci-serial", rendered)

    def test_arm_grub_requires_private_spice_input(self):
        with self.assertRaisesRegex(ProtocolError, "private SPICE"):
            boot_iso_with_debug_shell(
                Mock(),
                Mock(),
                Architecture.ARM64,
                firmware_delay=0,
                menu_entry_index=0,
                spice_socket=None,
            )

    def test_arm_grub_framebuffer_failure_blocks_all_commands(self):
        qmp = Mock()
        qmp.screendump.side_effect = ProtocolError("injected framebuffer failure")
        keyboard = Mock()
        command_line = _ArmGraphicalGrubCommandLine(qmp, keyboard)
        try:
            with self.assertRaisesRegex(ProtocolError, "injected framebuffer"):
                command_line.open(timeout=1)
        finally:
            command_line.close()
        self.assertEqual(
            [call("esc"), call("c")],
            keyboard.send_boot_key.call_args_list,
        )
        keyboard.type_boot_text.assert_not_called()

    def test_q35_does_not_add_a_second_i8042_controller(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config = QemuConfig(
                architecture=Architecture.AMD64,
                firmware=Firmware.BIOS,
                network=Network.ONLINE,
                memory_mib=4096,
                cpus=2,
                disk_gib=20,
                ssh_forward_port=2222,
                iso=root / "test.iso",
                disk=root / "target.qcow2",
                variables=None,
                firmware_selection=None,
                artifacts=root / "artifacts",
                qemu_binary="qemu-system-x86_64",
                acceleration="tcg,thread=multi",
            )
            vm = QemuVm(config)
            vm._runtime = tempfile.TemporaryDirectory(prefix="anduinos-unit-")
            try:
                command = vm.command(attach_iso=True)
            finally:
                vm._runtime.cleanup()
                vm._runtime = None
        self.assertNotIn("i8042", command)
        self.assertIn("usb-kbd,bus=xhci.0", command)

    def test_qemu_screenshot_retains_lossless_png_and_removes_raw_ppm(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            vm = QemuVm(SimpleNamespace(artifacts=root))

            def screendump(destination):
                Image.new("RGB", (64, 32), (12, 34, 56)).save(
                    destination,
                    format="PPM",
                )

            vm.qmp = SimpleNamespace(screendump=screendump)
            screenshot = vm.screenshot("desktop-boundary")

            self.assertEqual(root / "desktop-boundary.png", screenshot)
            self.assertTrue(screenshot.is_file())
            self.assertFalse((root / ".desktop-boundary.capture.ppm").exists())
            self.assertFalse((root / "desktop-boundary.ppm").exists())
            with Image.open(screenshot) as image:
                self.assertEqual((64, 32), image.size)
                self.assertEqual((12, 34, 56), image.getpixel((0, 0)))

    @patch("iso_test.qemu.subprocess.run")
    def test_feature_disk_is_a_qcow2_overlay_with_an_absolute_backing_file(self, run):
        run.return_value = subprocess.CompletedProcess([], 0, stdout="")
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            backing = root / "verified-base.qcow2"
            backing.write_bytes(b"base")
            config = QemuConfig(
                architecture=Architecture.AMD64,
                firmware=Firmware.BIOS,
                network=Network.ONLINE,
                memory_mib=4096,
                cpus=2,
                disk_gib=40,
                ssh_forward_port=2222,
                iso=root / "test.iso",
                disk=root / "suite" / "overlay.qcow2",
                variables=None,
                firmware_selection=None,
                artifacts=root / "artifacts",
                qemu_binary="qemu-system-x86_64",
                acceleration="tcg,thread=multi",
                backing_disk=backing,
            )
            QemuVm(config).create_disk()
        command = run.call_args.args[0]
        self.assertEqual("qemu-img", command[0])
        self.assertIn("-F", command)
        self.assertIn("-b", command)
        self.assertEqual(str(backing.resolve()), command[command.index("-b") + 1])


    def test_qmp_cleanup_failure_cannot_skip_qemu_reaping(self):
        vm = QemuVm(SimpleNamespace())
        qmp = _FaultyQmp()
        process = _ReapProcess()
        serial = _FaultyClose()
        log = _FaultyClose()
        runtime = _FaultyRuntime()
        vm.qmp = qmp
        vm.process = process
        vm.serial = serial
        vm._log = log
        vm._runtime = runtime

        vm.stop()

        self.assertTrue(qmp.close_attempted)
        self.assertTrue(process.waited)
        self.assertTrue(serial.close_attempted)
        self.assertTrue(log.close_attempted)
        self.assertTrue(runtime.cleanup_attempted)
        self.assertIsNone(vm.qmp)
        self.assertIsNone(vm.process)
        self.assertIsNone(vm.serial)
        self.assertIsNone(vm._runtime)

    def test_vm_transition_flushes_the_target_before_qmp_quit(self):
        events = []
        serial = Mock()
        serial.run.side_effect = lambda *args, **kwargs: events.append("guest-sync")
        qmp = Mock()
        qmp.flush_block_device.side_effect = (
            lambda *args, **kwargs: events.append("block-flush")
        )
        qmp.quit.side_effect = lambda: events.append("qmp-quit")
        vm = SimpleNamespace(
            serial=serial,
            qmp=qmp,
            wait=Mock(side_effect=lambda _timeout: events.append("qemu-exit")),
            stop=Mock(side_effect=lambda: events.append("cleanup")),
        )

        _power_off(vm)

        self.assertEqual(
            ["guest-sync", "block-flush", "qmp-quit", "qemu-exit", "cleanup"],
            events,
        )
        qmp.flush_block_device.assert_called_once_with("target")

    def test_failed_target_flush_is_a_visible_failure_and_still_cleans_up(self):
        vm = SimpleNamespace(
            serial=Mock(),
            qmp=Mock(),
            wait=Mock(),
            stop=Mock(),
        )
        vm.qmp.flush_block_device.side_effect = ProtocolError(
            "injected block flush failure"
        )

        with self.assertRaisesRegex(ProtocolError, "injected block flush failure"):
            _power_off(vm)

        vm.qmp.quit.assert_not_called()
        vm.stop.assert_called_once_with()

    def test_target_boot_integrity_rejects_a_copied_kernel_bit_flip(self):
        passing = "\n".join(
            (
                f"ANDUINOS_TARGET_KERNEL_SHA256={self._GOOD_KERNEL_HASH}",
                f"ANDUINOS_ISO_KERNEL_SHA256={self._GOOD_KERNEL_HASH}",
                "ANDUINOS_INITRD_CHECK=ok",
            )
        )
        _validate_target_boot_integrity(passing)

        corrupted = passing.replace(
            f"ANDUINOS_TARGET_KERNEL_SHA256={self._GOOD_KERNEL_HASH}",
            f"ANDUINOS_TARGET_KERNEL_SHA256={'b' * 64}",
        )
        with self.assertRaisesRegex(TestFailure, "differs byte-for-byte"):
            _validate_target_boot_integrity(corrupted)

    @patch("iso_test.base._check_qcow2", return_value={"corruptions": 0})
    def test_immutable_base_oracle_rejects_a_same_size_bit_flip(self, _check):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            disk = root / "target.qcow2"
            original = b"qcow2-base-contents"
            corrupted = b"qcow2-base-contentz"
            self.assertEqual(len(original), len(corrupted))
            disk.write_bytes(original)
            disk.chmod(0o400)
            disk_stat = disk.stat()
            scenario = TestMatrix.load(ROOT / "matrix.json").scenarios[0]
            base = PromotedBase(
                identity="test-base",
                architecture=Architecture.AMD64,
                scenario=scenario,
                disk=disk,
                variables=None,
                config=SimpleNamespace(),
                boot_files=InstalledBootFiles("/boot/vmlinuz", "/boot/initrd"),
                disk_sha256=hashlib.sha256(original).hexdigest(),
                disk_size_bytes=disk_stat.st_size,
                disk_mtime_ns=disk_stat.st_mtime_ns,
                variables_sha256=None,
                variables_size_bytes=None,
                variables_mtime_ns=None,
                manifest=root / "manifest.json",
                lock_path=root / "base.lock",
            )

            evidence = base.verify_integrity()
            self.assertEqual(base.disk_sha256, evidence["disk_sha256"])

            disk.chmod(0o600)
            disk.write_bytes(corrupted)
            os.utime(
                disk,
                ns=(disk.stat().st_atime_ns, disk_stat.st_mtime_ns),
            )
            disk.chmod(0o400)
            with self.assertRaisesRegex(TestFailure, "content changed"):
                base.verify_integrity()

    def test_promoted_base_cleanup_discards_disk_and_uefi_variables(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            disk = root / "target.qcow2"
            variables = root / "uefi-vars.fd"
            lock = root / "base.lock"
            disk.write_bytes(b"promoted disk")
            variables.write_bytes(b"promoted firmware state")
            lock.write_text("", encoding="utf-8")
            scenario = TestMatrix.load(ROOT / "matrix.json").scenarios[0]
            base = PromotedBase(
                identity="cleanup-base",
                architecture=Architecture.AMD64,
                scenario=scenario,
                disk=disk,
                variables=variables,
                config=SimpleNamespace(),
                boot_files=InstalledBootFiles("/boot/vmlinuz", "/boot/initrd"),
                disk_sha256="0" * 64,
                disk_size_bytes=disk.stat().st_size,
                disk_mtime_ns=disk.stat().st_mtime_ns,
                variables_sha256="1" * 64,
                variables_size_bytes=variables.stat().st_size,
                variables_mtime_ns=variables.stat().st_mtime_ns,
                manifest=root / "manifest.json",
                lock_path=lock,
            )

            base.cleanup()

            self.assertFalse(disk.exists())
            self.assertFalse(variables.exists())
            self.assertFalse(lock.exists())

    def test_iso_boot_uses_the_exact_selected_grub_region(self):
        grub = "\n".join(
            f'''menuentry "Language {index}" {{
 linux /casper/vmlinuz boot=casper locale=l{index}_XX.UTF-8 timezone=Zone/{index} systemd.timezone=Zone/{index} nopersistent quiet splash ---
}}'''
            for index in range(28)
        )
        entries = _parse_live_entries(grub)
        self.assertEqual(28, len(entries))
        self.assertEqual("l2_XX.UTF-8", entries[2].locale)
        self.assertEqual("Zone/2", entries[2].timezone)

    def test_iso_rejects_a_partial_regional_menu(self):
        with self.assertRaises(ConfigurationError):
            _parse_live_entries(
                '''menuentry "Only one" {
 linux /casper/vmlinuz boot=casper locale=en_US.UTF-8 timezone=Etc/UTC systemd.timezone=Etc/UTC
}'''
            )

    def test_cpu_z_fixture_has_the_product_validated_pe_shape(self):
        with tempfile.TemporaryDirectory() as directory:
            destination = Path(directory) / "cpu-z.exe"
            _build_pe(destination)
            content = destination.read_bytes()
            self.assertEqual(b"MZ", content[:2])
            offset = int.from_bytes(content[60:64], "little")
            self.assertGreaterEqual(offset, 64)
            self.assertEqual(b"PE\0\0", content[offset : offset + 4])
            self.assertIn(b".rsrc\0\0\0", content)
            self.assertIn(b"\x89PNG\r\n\x1a\n", content)
            thumbnailer = shutil.which("exe-thumbnailer")
            if thumbnailer is not None:
                thumbnail = Path(directory) / "cpu-z.png"
                generated = subprocess.run(
                    (thumbnailer, "-s", "256", str(destination), str(thumbnail)),
                    check=False,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                )
                self.assertEqual(0, generated.returncode, generated.stdout)
                assert_cpu_z_thumbnail(
                    thumbnail,
                    Path(directory) / "cpu-z-thumbnail-analysis.json",
                )

    def test_file_integration_fixtures_are_deterministic_and_harmless(self):
        digests = []
        for _iteration in range(2):
            with tempfile.TemporaryDirectory() as directory:
                fixtures = build_file_integration_fixtures(Path(directory))
                paths = (
                    fixtures.image,
                    fixtures.video,
                    fixtures.deb,
                    fixtures.text,
                )
                digests.append(
                    tuple(hashlib.sha256(path.read_bytes()).hexdigest() for path in paths)
                )
                with Image.open(fixtures.image) as image:
                    self.assertEqual((320, 240), image.size)
                self.assertGreater(fixtures.video.stat().st_size, 1024)
                fields = subprocess.run(
                    (
                        "dpkg-deb",
                        "--field",
                        str(fixtures.deb),
                        "Package",
                        "Version",
                        "Architecture",
                    ),
                    check=True,
                    stdout=subprocess.PIPE,
                    text=True,
                ).stdout.splitlines()
                self.assertEqual(
                    [
                        "Package: anduinos-acceptance-fixture",
                        "Version: 1.0",
                        "Architecture: all",
                    ],
                    fields,
                )
                control_tar = subprocess.run(
                    ("dpkg-deb", "--ctrl-tarfile", str(fixtures.deb)),
                    check=True,
                    stdout=subprocess.PIPE,
                ).stdout
                members = subprocess.run(
                    ("tar", "-tf", "-"),
                    input=control_tar,
                    check=True,
                    stdout=subprocess.PIPE,
                ).stdout.decode().splitlines()
                self.assertEqual({"./", "./control"}, set(members))
        self.assertEqual(digests[0], digests[1])

    def test_installed_grub_instrumentation_is_byte_for_byte_reversible(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            grub = root / "boot/grub"
            grub.mkdir(parents=True)
            config = grub / "grub.cfg"
            original = (
                "set default=0\n"
                "menuentry 'AnduinOS' {\n"
                "  linux /boot/vmlinuz root=UUID=test ro quiet splash\n"
                "  initrd /boot/initrd.img\n"
                "}\n"
            )
            config.write_text(original, encoding="utf-8")
            subprocess.run(
                ("grub-editenv", str(grub / "grubenv"), "create"),
                check=True,
            )
            environment = os.environ | {"mountpoint": str(root)}
            instrument = subprocess.run(
                ("bash", "-c", render_installed_grub_instrumentation(
                    Architecture.AMD64,
                    mounted_target=True,
                )),
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                env=environment,
                check=False,
            )
            self.assertEqual(0, instrument.returncode, instrument.stdout)
            self.assertIn("systemd.debug_shell=ttyS0", config.read_text())
            self.assertTrue(config.with_name("grub.cfg.anduinos-acceptance-original").is_file())
            restore = subprocess.run(
                ("bash", "-c", render_installed_grub_restoration(mounted_target=True)),
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                env=environment,
                check=False,
            )
            self.assertEqual(0, restore.returncode, restore.stdout)
            self.assertEqual(original, config.read_text(encoding="utf-8"))
            self.assertIn("byte-for-byte-restored=yes", restore.stdout)


class FeatureOracleTests(unittest.TestCase):
    @staticmethod
    def _events(*values):
        return "\n".join(json.dumps(value) for value in values)

    def test_extension_journal_filter_cannot_ignore_shell_js_errors(self):
        self.assertTrue(
            _is_gnome_extension_entry(
                SimpleNamespace(
                    component_text="gnome-shell|/usr/bin/gnome-shell",
                    message="JS ERROR: extension exploded",
                )
            )
        )
        self.assertTrue(
            _is_gnome_extension_entry(
                SimpleNamespace(
                    component_text="unknown",
                    message="Extension example@test raised an exception",
                )
            )
        )
        self.assertFalse(
            _is_gnome_extension_entry(
                SimpleNamespace(
                    component_text="NetworkManager",
                    message="link became ready",
                )
            )
        )

    @staticmethod
    def _context_action_events(target, label, request_prefix, items, target_index):
        down_presses = target_index + 1
        return [
            {
                "event": "context-menu-plan",
                "target": target,
                "accessible_name": label,
                "items": items,
                "target_index": target_index,
                "down_presses": down_presses,
                "focus_origin": "menu-actor",
            },
            *[
                {
                    "event": "qmp-key",
                    "request": f"{request_prefix}-down-{number}",
                    "key": "down",
                }
                for number in range(1, down_presses + 1)
            ],
            {
                "event": "qmp-key",
                "request": f"{request_prefix}-activate",
                "key": "ret",
            },
            {
                "event": "context-menu-activated",
                "target": target,
                "accessible_name": label,
                "method": "qmp-keyboard",
                "down_presses": down_presses,
            },
        ]

    @staticmethod
    def _graphical_vt_output(vt: int = 2) -> str:
        return "\n".join(
            (
                f"active-vt={vt}",
                "graphical-session=3",
                f"graphical-session-vt={vt}",
                "graphical-session-type=wayland",
                "graphical-session-active=yes",
                "graphical-target=active",
                "gdm-service=active",
            )
        )

    @staticmethod
    def _tty6_output(text: str = "AnduinOS 2.0.1 host tty6 login:") -> str:
        return "\n".join(
            (
                "active-vt=6",
                "vcs-device=/dev/vcs6",
                f"vcs-bytes={len(text)}",
                "vcs-sha256=" + "a" * 64,
                "vcs-text-json=" + json.dumps(text),
            )
        )

    def test_tty6_oracle_accepts_the_active_kernel_screen_buffer(self):
        evidence = _validate_tty6_evidence(self._tty6_output(), 0)
        self.assertEqual(6, evidence["active_vt"])
        self.assertIn("AnduinOS", evidence["text"])
        self.assertEqual(
            2,
            _validate_graphical_vt_evidence(self._graphical_vt_output(), 0),
        )

    def test_tty6_oracle_rejects_wrong_vt_and_ubuntu_branding(self):
        with self.assertRaisesRegex(TestFailure, "Ctrl\\+Alt\\+F6"):
            _validate_tty6_evidence(
                self._tty6_output().replace("active-vt=6", "active-vt=5"),
                0,
            )
        with self.assertRaisesRegex(TestFailure, "Ubuntu branding"):
            _validate_tty6_evidence(
                self._tty6_output("AnduinOS Ubuntu tty6 login:"),
                0,
            )
        with self.assertRaisesRegex(TestFailure, "expected tty2"):
            _validate_graphical_vt_evidence(
                self._graphical_vt_output(3),
                0,
                expected_vt=2,
            )

    def test_tty6_guest_probes_are_bash_syntax_checked(self):
        for command in (
            _graphical_vt_probe_command("acceptance user"),
            _graphical_vt_probe_command("acceptance user", wait_for=2),
            _tty6_probe_command(),
        ):
            result = subprocess.run(
                ("bash", "-n"),
                input=command,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                check=False,
            )
            self.assertEqual(0, result.returncode, result.stdout)
            self.assertIn("/sys/class/tty/tty0/active", command)
            self.assertNotIn("fgconsole", command)
        with self.assertRaises(ValueError):
            _graphical_vt_probe_command("acceptance", wait_for=13)

    def test_tty6_exercise_sends_both_real_vt_chords(self):
        runner = object.__new__(FeatureSuiteRunner)
        runner.username = "acceptance"
        runner._journal_cursors = Mock(return_value={"system": "s", "user": "u"})
        runner._assert_scoped_journal = Mock()
        before = CommandResult(self._graphical_vt_output(), 0)
        tty6 = CommandResult(self._tty6_output(), 0)
        restored = CommandResult(self._graphical_vt_output(), 0)
        serial = Mock()
        serial.run.side_effect = (before, tty6, restored)
        qmp = Mock()
        vm = SimpleNamespace(serial=serial, qmp=qmp, screenshot=Mock())
        base = SimpleNamespace()
        with tempfile.TemporaryDirectory() as directory:
            with patch("iso_test.feature_runner._graphical_user", return_value="acceptance"):
                runner._exercise_tty6_branding(vm, base, Path(directory))
        self.assertEqual(
            [call("ctrl-alt-f6"), call("ctrl-alt-f2")],
            qmp.send_key.call_args_list,
        )
        runner._assert_scoped_journal.assert_called_once()

    def test_tty6_exercise_restores_graphics_after_a_branding_failure(self):
        runner = object.__new__(FeatureSuiteRunner)
        runner.username = "acceptance"
        runner._journal_cursors = Mock(return_value={"system": "s", "user": "u"})
        runner._assert_scoped_journal = Mock()
        before = CommandResult(self._graphical_vt_output(), 0)
        failed = CommandResult("active-vt=6\nvcs-device=/dev/vcs6", 71)
        restored = CommandResult(self._graphical_vt_output(), 0)
        serial = Mock()
        serial.run.side_effect = (before, failed, restored)
        qmp = Mock()
        vm = SimpleNamespace(serial=serial, qmp=qmp, screenshot=Mock())
        with tempfile.TemporaryDirectory() as directory:
            with patch("iso_test.feature_runner._graphical_user", return_value="acceptance"):
                with self.assertRaisesRegex(TestFailure, "login banner"):
                    runner._exercise_tty6_branding(
                        vm,
                        SimpleNamespace(),
                        Path(directory),
                    )
        self.assertEqual(
            [call("ctrl-alt-f6"), call("ctrl-alt-f2")],
            qmp.send_key.call_args_list,
        )
        runner._assert_scoped_journal.assert_not_called()

    def test_nextcloud_ppa_oracle_requires_the_real_signed_suite_and_index(self):
        passing = "\n".join(
            (
                "invoking-user=anduinostest",
                "command=sudo add-apt-repository -y ppa:nextcloud-devs/client",
                "repository-command=passed",
                "os-release-codename=resolute",
                "source-count=1",
                "source-path=/etc/apt/sources.list.d/nextcloud-devs-ubuntu-client-resolute.sources",
                "source-uri=https://ppa.launchpadcontent.net/nextcloud-devs/client/ubuntu/",
                "source-suite=resolute",
                "source-signed-by=yes",
                "apt-index-uri=https://ppa.launchpadcontent.net/nextcloud-devs/client/ubuntu/dists/resolute/main/binary-amd64/Packages",
                "nextcloud-ppa-sudo-policy=removed",
            )
        )
        evidence = _validate_nextcloud_ppa_evidence(
            passing,
            0,
            "anduinostest",
        )
        self.assertEqual("resolute", evidence["codename"])
        for broken, message in (
            (passing.replace("source-signed-by=yes", "source-signed-by=no"), "signed"),
            (passing.replace("source-suite=resolute", "source-suite=questing"), "suite"),
            (
                passing.replace(
                    "apt-index-uri=https://ppa.launchpadcontent.net/nextcloud-devs/client/ubuntu",
                    "apt-index-uri=https://example.invalid/unrelated",
                ),
                "unrelated",
            ),
        ):
            with self.subTest(message=message):
                with self.assertRaises(TestFailure):
                    _validate_nextcloud_ppa_evidence(
                        broken,
                        0,
                        "anduinostest",
                    )
        with self.assertRaisesRegex(TestFailure, "command or source"):
            _validate_nextcloud_ppa_evidence(passing, 1, "anduinostest")

    def test_public_cpu_z_download_and_desktop_oracles_fail_closed(self):
        passing_download = "\n".join(
            (
                "cpu-z-http-code=200",
                "cpu-z-archive-preexisting=no",
                "cpu-z-member-preexisting=no",
                "cpu-z-version=2.20.2",
                "cpu-z-url=https://download.cpuid.com/cpu-z/cpu-z_2.20.2-en.zip",
                "cpu-z-archive=cpu-z_2.20.2-en.zip",
                "cpu-z-archive-sha256="
                "320e073a6f387464ac3faac5f010b5fe70e31fab30745883d023c8372e80f3c5",
                "cpu-z-member=cpuz_x64.exe",
                "cpu-z-member-sha256="
                "e1b0eda853641b75fa1a890e7811bc19b3be0ece0494c60f03d34247b7650126",
                "cpu-z-member-size=7428328",
                "cpu-z-mime=application/vnd.microsoft.portable-executable",
                "cpu-z-handler=com.anduinos.ExeRunner.desktop",
                "bottles=absent",
                "public-cpu-z=downloaded-and-verified",
            )
        )
        download = _validate_cpu_z_download_evidence(passing_download, 0)
        self.assertEqual(7_428_328, download["member_size"])
        alternate = _validate_cpu_z_download_evidence(
            passing_download.replace(
                "application/vnd.microsoft.portable-executable",
                "application/x-msdownload",
            ),
            0,
        )
        self.assertEqual("application/x-msdownload", alternate["mime_type"])
        for broken in (
            passing_download.replace("320e073a", "020e073a", 1),
            passing_download.replace(
                "com.anduinos.ExeRunner.desktop", "unrelated.desktop"
            ),
            passing_download.replace("bottles=absent", "bottles=installed"),
            passing_download.replace(
                "application/vnd.microsoft.portable-executable",
                "application/octet-stream",
            ),
        ):
            with self.assertRaises(TestFailure):
                _validate_cpu_z_download_evidence(broken, 0)
        with self.assertRaisesRegex(TestFailure, "download or file contract"):
            _validate_cpu_z_download_evidence(passing_download, 22)

        events = self._events(
            {
                "event": "file-thumbnail",
                "filename": "cpuz_x64.exe",
                "uri": "file:///home/anduinostest/Downloads/cpuz_x64.exe",
                "cache_path": (
                    "/home/anduinostest/.cache/thumbnails/large/"
                    + "a" * 32
                    + ".png"
                ),
                "cache_size": 4096,
                "visible_nodes": [
                    {"name": "cpuz_x64.exe", "role": "table row"}
                ],
            },
            {
                "event": "nautilus-open",
                "filename": "cpuz_x64.exe",
                "activation_method": "selected-item-qmp-enter",
                "observed": "Installing CPU-Z?",
            },
            {
                "event": "cpu-z-public-recommendation",
                "filename": "cpuz_x64.exe",
                "application": "AnduinOS Windows EXE Runner",
                "heading": "Installing CPU-Z?",
                "reason": (
                    "CPU-X is a native Linux application that perfectly mirrors "
                    "CPU-Z in functionality and interface, without the need for "
                    "Windows sandboxing."
                ),
                "controls": {
                    "cancel": {
                        "name": "Cancel",
                        "role": "button",
                        "enabled": True,
                        "showing": True,
                    },
                    "force_run": {
                        "name": "Force Run Anyway",
                        "role": "button",
                        "enabled": True,
                        "showing": True,
                    },
                    "cpux_get": {
                        "name": "Get CPU-X",
                        "role": "button",
                        "enabled": True,
                        "showing": True,
                    },
                },
                "bottles_installed": False,
                "runner_processes": [
                    "123 /usr/bin/python3 /usr/bin/anduinos-exe-runner "
                    "/home/anduinostest/Downloads/cpuz_x64.exe"
                ],
            },
        )
        desktop = _validate_cpu_z_events(events, "anduinostest")
        self.assertEqual(4096, desktop["cache_size"])
        with self.assertRaisesRegex(TestFailure, "unrelated desktop surface"):
            _validate_cpu_z_events(
                events.replace(
                    "Installing CPU-Z?",
                    "Unrelated Application",
                    1,
                ),
                "anduinostest",
            )

    def test_public_spotify_catalog_probe_and_classification_fail_closed(self):
        passing = "\n".join(
            (
                "flatpak-version=Flatpak 1.16.6",
                "spotify-public-remote-count=1",
                "spotify-public-remote-url=https://dl.flathub.org/repo/",
                "spotify-public-appstream-refresh=passed",
                "spotify-public-ref=app/com.spotify.Client/x86_64/stable",
                "spotify-public-commit=" + "a" * 64,
                "spotify-public-cached-entry="
                "com.spotify.Client\tapp/com.spotify.Client/x86_64/stable\t"
                "x86_64\tstable\tflathub",
                "spotify-public-app-id=com.spotify.Client",
                "spotify-public-remote=flathub",
                "spotify-public-arch=x86_64",
                "spotify-public-failure-class=none",
                "spotify-public-catalog=current-and-resolved",
            )
        )
        evidence = _validate_spotify_public_catalog_evidence(passing, 0)
        self.assertEqual("a" * 64, evidence["commit"])
        for broken in (
            passing.replace("https://dl.flathub.org/repo/", "http://example.invalid/"),
            passing.replace("com.spotify.Client/x86_64/stable", "unrelated/x86_64/stable", 1),
            passing.replace("a" * 64, "not-a-commit"),
            passing.replace("x86_64\tstable\tflathub", "x86_64\tstable\tunrelated"),
        ):
            with self.subTest(broken=broken[-120:]):
                with self.assertRaises(TestFailure):
                    _validate_spotify_public_catalog_evidence(broken, 0)

        for classification in ("external-catalog", "product-regression"):
            failure = "\n".join(
                (
                    "spotify-public-failure-reason=appstream-refresh-failed",
                    f"spotify-public-failure-class={classification}",
                )
            )
            with self.subTest(classification=classification):
                with self.assertRaisesRegex(TestFailure, classification):
                    _validate_spotify_public_catalog_evidence(failure, 85)
        with self.assertRaisesRegex(TestFailure, "without a valid classification"):
            _validate_spotify_public_catalog_evidence("network failed", 1)

        probe = _spotify_public_catalog_command()
        syntax = subprocess.run(
            ("bash", "-n"),
            input=probe,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            check=False,
        )
        self.assertEqual(0, syntax.returncode, syntax.stdout)
        self.assertIn("flatpak update --appstream --system", probe)
        self.assertIn("flatpak remote-info --system", probe)
        self.assertIn("flatpak remote-ls --system --cached", probe)
        self.assertIn("https://dl.flathub.org/repo/", probe)
        self.assertNotIn("/home/anduin", probe)

        source = Path("tests/iso_test/feature_runner.py").read_text(encoding="utf-8")
        body = source.split("def _exercise_spotify_public(", 1)[1].split(
            "def _exercise_nextcloud_ppa(", 1
        )[0]
        self.assertNotIn("set_link", body)
        self.assertIn("store.spotify-public", _SHELL_DRIVER_CHECKS)
        self.assertIn("systemctl --user stop gnome-software.service", body)
        self.assertIn('mode="shell-spotify-store"', body)

    def test_public_wechat_install_and_tray_oracles_fail_closed(self):
        commit = "b" * 64
        location = (
            "/var/lib/flatpak/app/com.tencent.WeChat/x86_64/stable/" + commit
        )
        passing_install = "\n".join(
            (
                "wechat-preinstalled=no",
                "wechat-remote-count=1",
                "wechat-remote-url=https://dl.flathub.org/repo/",
                "wechat-remote-ref=app/com.tencent.WeChat/x86_64/stable",
                f"wechat-remote-commit={commit}",
                "wechat-install-command=passed",
                "wechat-installed-ref=app/com.tencent.WeChat/x86_64/stable",
                f"wechat-installed-commit={commit}",
                "wechat-installed-origin=flathub",
                f"wechat-installed-location={location}",
                "wechat-desktop=/var/lib/flatpak/exports/share/applications/"
                "com.tencent.WeChat.desktop",
                f"wechat-desktop-resolved={location}/export/share/applications/"
                "com.tencent.WeChat.desktop",
                "wechat-app-id=com.tencent.WeChat",
                "wechat-arch=x86_64",
                "wechat-failure-class=none",
                "wechat-install=current-and-verified",
            )
        )
        install_evidence = _validate_wechat_install_evidence(passing_install, 0)
        self.assertEqual(commit, install_evidence["commit"])
        for broken in (
            passing_install.replace("wechat-preinstalled=no", "wechat-preinstalled=yes"),
            passing_install.replace(commit, "c" * 64, 1),
            passing_install.replace("wechat-installed-origin=flathub", "wechat-installed-origin=other"),
            passing_install.replace(
                f"wechat-desktop-resolved={location}",
                "wechat-desktop-resolved=/tmp/untrusted",
            ),
        ):
            with self.subTest(broken=broken[-160:]):
                with self.assertRaises(TestFailure):
                    _validate_wechat_install_evidence(broken, 0)
        for classification in (
            "external-catalog",
            "external-artifact",
            "product-regression",
        ):
            failure = "\n".join(
                (
                    "wechat-failure-reason=flatpak-install-failed",
                    f"wechat-failure-class={classification}",
                )
            )
            with self.subTest(classification=classification):
                with self.assertRaisesRegex(TestFailure, classification):
                    _validate_wechat_install_evidence(failure, 90)

        process = {
            "pid": 5010,
            "namespace_pid": 5011,
            "uid": 1000,
            "start_time_ticks": 987654,
            "command": "/app/extra/wechat/WeChatAppEx",
            "executable": "/app/extra/wechat/WeChatAppEx",
        }
        wechat_window = {
            "id": "0x2a00007",
            "title": "微信",
            "classes": ["wechat", "WeChat"],
            "pid": 5011,
            "state": "",
            "map_state": "IsViewable",
            "visible": True,
            "x": 500,
            "y": 185,
            "width": 280,
            "height": 382,
        }
        launch_events = self._events(
            {
                "event": "qmp-key",
                "request": "wechat-search-open",
                "key": "meta_l",
            },
            {"event": "qmp-text", "request": "wechat-search-text"},
            {
                "event": "start-search-result",
                "query": "WeChat",
                "accessible_name": "WeChat",
                "application": "gnome-shell",
                "stable_observations": 4,
            },
            {
                "event": "search-entry-focus",
                "query": "WeChat",
                "application": "gnome-shell",
                "focused": True,
            },
            {
                "event": "qmp-key",
                "request": "wechat-result-activate",
                "key": "ret",
            },
            {
                "event": "wechat-installed-launched",
                "search_result": "WeChat",
                "activation_method": "qmp-keyboard",
                "application": "com.tencent.WeChat",
                "observation": "ewmh-x11",
                "main_window": wechat_window,
                "windows": [wechat_window],
                "process": process,
                "visible": True,
            },
        )
        launch = _validate_wechat_install_events(launch_events)
        self.assertEqual(5010, launch["process"]["pid"])
        with self.assertRaisesRegex(TestFailure, "unrelated process"):
            _validate_wechat_install_events(
                launch_events.replace(
                    "/app/extra/wechat/WeChatAppEx",
                    "/usr/bin/unrelated",
                )
            )

        hidden = dict(process)
        tray_events = self._events(
            {
                "event": "wechat-tray-baseline",
                "application": "com.tencent.WeChat",
                "main_window": wechat_window,
                "windows": [wechat_window],
                "process": process,
            },
            {
                "event": "qmp-key",
                "request": "wechat-close-to-tray",
                "key": "alt-f4",
            },
            {
                "event": "wechat-indicator",
                "process": hidden,
                "indicator": {
                    "accessible_name": "WeChat",
                    "target_name": "WeChat",
                    "role": "button",
                    "application": "gnome-shell",
                    "bounds": [1100, 760, 24, 24],
                    "screen": [1280, 800],
                    "lower_right": True,
                },
                "visible": True,
            },
            {
                "event": "spice-double-click",
                "request": "wechat-indicator-restore",
                "target": "WeChat AppIndicator",
                "button": "left",
                "application": "gnome-shell",
                "clicks": 2,
            },
            {
                "event": "wechat-tray-restored",
                "application": "com.tencent.WeChat",
                "main_window": wechat_window,
                "windows": [wechat_window],
                "process": process,
                "same_process": True,
                "visible": True,
            },
        )
        tray = _validate_wechat_tray_events(tray_events)
        self.assertEqual(987654, tray["process"]["start_time_ticks"])
        with self.assertRaisesRegex(TestFailure, "same process"):
            _validate_wechat_tray_events(
                tray_events.replace('"start_time_ticks": 987654', '"start_time_ticks": 987655', 1)
            )
        with self.assertRaisesRegex(TestFailure, "lower-right"):
            _validate_wechat_tray_events(
                tray_events.replace('"lower_right": true', '"lower_right": false')
            )

        probe = _wechat_install_command()
        syntax = subprocess.run(
            ("bash", "-n"),
            input=probe,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            check=False,
        )
        self.assertEqual(0, syntax.returncode, syntax.stdout)
        self.assertIn("flatpak install --system --noninteractive", probe)
        self.assertIn("com.tencent.WeChat", probe)
        self.assertIn("flatpak remote-info --system", probe)
        self.assertIn("printf '\nwechat-install-command=passed\n'", probe)
        self.assertNotIn("/home/anduin", probe)
        driver = (ROOT / "guest" / "atspi_driver.py").read_text(encoding="utf-8")
        self.assertIn('"public-wechat-install"', driver)
        self.assertIn('"public-wechat-tray"', driver)
        self.assertIn("exercise_wechat_install(args.evidence)", driver)
        self.assertIn("exercise_wechat_tray(args.evidence)", driver)
        self.assertIn("def _wechat_process_identity", driver)
        self.assertIn('"start_time_ticks": int(fields[19])', driver)
        self.assertNotIn("def _one_wechat_instance", driver)
        self.assertIn('runtime.glob(".mutter-Xwaylandauth.*")', driver)
        self.assertIn('environment["XAUTHORITY"] = authority', driver)
        self.assertIn("app.wechat-install", _SHELL_DRIVER_CHECKS)
        self.assertNotIn("app.wechat-tray", _SHELL_DRIVER_CHECKS)

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            good = Image.new("RGB", (1280, 800), (20, 30, 45))
            draw = ImageDraw.Draw(good)
            left = int(wechat_window["x"])
            top = int(wechat_window["y"])
            width = int(wechat_window["width"])
            height = int(wechat_window["height"])
            draw.rectangle(
                (left, top, left + width - 1, top + height - 1),
                fill="white",
            )
            qr_left = left + round(width * 0.15)
            qr_top = top + round(height * 0.10)
            qr_right = left + round(width * 0.85)
            qr_bottom = top + round(height * 0.62)
            cell = 5
            for y in range(qr_top, qr_bottom, cell):
                for x in range(qr_left, qr_right, cell):
                    if ((x - qr_left) // cell + (y - qr_top) // cell) % 2 == 0:
                        draw.rectangle(
                            (x, y, min(x + cell - 1, qr_right), min(y + cell - 1, qr_bottom)),
                            fill="black",
                        )
            draw.rectangle(
                (left + 80, top + 250, left + 200, top + 270),
                fill=(0, 210, 80),
            )
            good_path = root / "wechat.png"
            good.save(good_path)
            assert_wechat_login_window(
                good_path,
                root / "wechat.json",
                {"main_window": wechat_window},
            )
            generic = Image.new("RGB", (1280, 800), "white")
            generic_path = root / "generic.png"
            generic.save(generic_path)
            with self.assertRaisesRegex(TestFailure, "QR login UI"):
                assert_wechat_login_window(
                    generic_path,
                    root / "generic.json",
                    {"main_window": wechat_window},
                )

    def test_public_cpu_z_probe_is_portable_and_thumbnail_is_content_specific(self):
        probe = _cpu_z_download_command()
        syntax = subprocess.run(
            ("bash", "-n"),
            input=probe,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            check=False,
        )
        self.assertEqual(0, syntax.returncode, syntax.stdout)
        self.assertIn("https://download.cpuid.com/cpu-z/", probe)
        self.assertIn("sha256sum", probe)
        self.assertIn("xdg-mime query default", probe)
        self.assertIn("application/x-msdownload", probe)
        self.assertIn("application/vnd.microsoft.portable-executable", probe)
        self.assertIn("flatpak info com.usebottles.bottles", probe)
        self.assertNotIn("/home/anduin", probe)

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            good = Image.new("RGB", (256, 256), (52, 18, 116))
            draw = ImageDraw.Draw(good)
            draw.rounded_rectangle((52, 52, 204, 204), radius=12, fill="white")
            draw.rectangle((75, 75, 181, 181), fill=(52, 18, 116))
            draw.rounded_rectangle((100, 100, 156, 156), radius=10, fill="white")
            good_path = root / "cpu-z.png"
            good.save(good_path)
            assert_cpu_z_thumbnail(good_path, root / "cpu-z.json")

            generic = root / "generic.png"
            Image.new("RGB", (256, 256), (52, 18, 116)).save(generic)
            with self.assertRaisesRegex(TestFailure, "white/purple artwork"):
                assert_cpu_z_thumbnail(generic, root / "generic.json")

        driver = (ROOT / "guest" / "atspi_driver.py").read_text(encoding="utf-8")
        self.assertIn('"public-cpuz-file"', driver)
        self.assertIn("verify_public_cpuz_file(args.filename, args.evidence)", driver)

    def test_local_pe_thumbnail_and_open_have_independent_oracles(self):
        cache = (
            "/home/anduinostest/.cache/thumbnails/large/"
            "0123456789abcdef0123456789abcdef.png"
        )
        thumbnail_output = json.dumps(
            {
                "event": "file-thumbnail",
                "filename": "cpu-z.exe",
                "uri": "file:///home/anduinostest/Downloads/cpu-z.exe",
                "cache_path": cache,
                "cache_size": 4096,
                "visible_nodes": [{"name": "cpu-z.exe", "role": "table row"}],
            }
        )
        evidence = _validate_windows_executable_thumbnail_events(
            thumbnail_output,
            "anduinostest",
        )
        self.assertEqual(cache, evidence["cache_path"])
        with self.assertRaisesRegex(TestFailure, "thumbnail event"):
            _validate_windows_executable_thumbnail_events(
                "",
                "anduinostest",
            )

        open_event = json.dumps(
            {
                "event": "nautilus-open",
                "filename": "cpu-z.exe",
                "activation_method": "host-spice-double-click",
                "observed": "CPU-Z has a native alternative",
            }
        )
        recommendation = json.dumps(
            {
                "event": "cpu-z-recommendation",
                "application": "AnduinOS Windows EXE Runner",
            }
        )
        _validate_windows_executable_open_events(
            "\n".join((open_event, recommendation))
        )
        with self.assertRaisesRegex(TestFailure, "out of order"):
            _validate_windows_executable_open_events(
                "\n".join((recommendation, open_event))
            )

    def test_nextcloud_ppa_exercise_uses_a_narrow_temporary_sudo_policy(self):
        source = Path("tests/iso_test/feature_runner.py").read_text(encoding="utf-8")
        body = source.split("def _exercise_nextcloud_ppa(", 1)[1].split(
            "def _graphical_session_id(",
            1,
        )[0]
        self.assertIn(r"ppa\:nextcloud-devs/client", body)
        self.assertIn(
            "sudo -n /usr/bin/add-apt-repository -y ",
            body,
        )
        self.assertIn("finally:", body)
        self.assertIn("rm -f", body)
        self.assertNotIn("sudo -S", body)
        probe = _nextcloud_ppa_source_probe_command()
        syntax = subprocess.run(
            ("bash", "-n"),
            input=probe,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            check=False,
        )
        self.assertEqual(0, syntax.returncode, syntax.stdout)
        self.assertIn("print(f'source-uri={uri_value}')", probe)
        self.assertNotIn("source-uri=https://", probe)
        self.assertNotIn("grep -F -m1", probe)
        self.assertIn("sed -n '1p'", probe)

    def test_alt_tab_oracle_rejects_unchanged_focus(self):
        passing = self._events(
            {
                "event": "shortcut-focus",
                "shortcut": "alt-tab",
                "phase": "before",
                "window": "AnduinOS Shortcut Window Beta",
            },
            {
                "event": "qmp-key",
                "request": "shortcut-alt-tab-forward",
                "key": "alt-tab",
            },
            {
                "event": "shortcut-focus",
                "shortcut": "alt-tab",
                "phase": "after",
                "window": "AnduinOS Shortcut Window Alpha",
            },
            {
                "event": "qmp-key",
                "request": "shortcut-alt-tab-restore",
                "key": "alt-tab",
            },
            {
                "event": "shortcut-focus",
                "shortcut": "alt-tab",
                "phase": "restored",
                "window": "AnduinOS Shortcut Window Beta",
            },
        )
        _validate_alt_tab_events(passing)
        with self.assertRaisesRegex(TestFailure, "both fixed fixture windows"):
            _validate_alt_tab_events(
                passing.replace(
                    "AnduinOS Shortcut Window Alpha",
                    "AnduinOS Shortcut Window Beta",
                )
            )

    def test_super_tab_oracle_rejects_missing_overview(self):
        passing = self._events(
            {"event": "overview", "phase": "before", "visible": False},
            {
                "event": "qmp-key",
                "request": "shortcut-super-tab-show",
                "key": "meta_l-tab",
            },
            {
                "event": "overview",
                "phase": "shown",
                "visible": True,
                "nodes": [["panel", "概览"]],
            },
            {
                "event": "qmp-key",
                "request": "shortcut-super-tab-hide",
                "key": "meta_l-tab",
            },
            {"event": "overview", "phase": "restored", "visible": False},
        )
        _validate_super_tab_events(passing)
        lines = passing.splitlines()
        shown = json.loads(lines[2])
        shown["nodes"] = []
        lines[2] = json.dumps(shown)
        with self.assertRaisesRegex(TestFailure, "semantic Overview"):
            _validate_super_tab_events("\n".join(lines))

    def test_initial_overview_oracle_rejects_visible_or_unproven_absence(self):
        passing = self._events(
            {
                "event": "initial-overview",
                "phase": "post-login",
                "visible": False,
                "stable_observations": 8,
                "overview_nodes": [],
                "shell_ready_markers": [["push button", "ArcMenu"]],
            }
        )
        _validate_initial_overview_events(passing)
        for mutation, message in (
            ({"visible": True}, "visible automatically"),
            ({"shell_ready_markers": []}, "before GNOME Shell"),
            ({"stable_observations": 1}, "eight observations"),
        ):
            value = json.loads(passing)
            value.update(mutation)
            with self.assertRaisesRegex(TestFailure, message):
                _validate_initial_overview_events(json.dumps(value))

    def test_initial_overview_guest_probe_is_observation_only(self):
        source = (ROOT / "guest" / "atspi_driver.py").read_text(encoding="utf-8")
        body = source.split("def assert_initial_overview_hidden", 1)[1].split(
            "def exercise_super_tab", 1
        )[0]
        self.assertIn('_wait_shell_named("start_button", True', body)
        self.assertIn("_overview_nodes()", body)
        self.assertNotIn("dismiss_initial_setup", body)
        self.assertNotIn('event("qmp-key"', body)

    def test_default_desktop_icon_oracle_rejects_incomplete_or_fake_icons(self):
        passing = self._events(
            {
                "event": "desktop-default-icons",
                "stable_observations": 4,
                "icons": [
                    {
                        "name": "主目录",
                        "role": "label",
                        "application": "gjs",
                        "bounds": [48, 40, 64, 22],
                    },
                    {
                        "name": "回收站",
                        "role": "label",
                        "application": "gjs",
                        "bounds": [48, 152, 64, 22],
                    },
                ],
                "desktop_frame": {
                    "name": "Desktop Icons 1",
                    "role": "frame",
                    "application": "gjs",
                    "bounds": [0, 0, 1280, 752],
                },
            }
        )
        _validate_desktop_icon_events(passing)
        mutations = (
            (lambda value: value["icons"].pop(), "incomplete"),
            (lambda value: value["icons"][0].update(application="gnome-shell"), "DING"),
            (lambda value: value.update(stable_observations=1), "four observations"),
            (lambda value: value["desktop_frame"].update(role="panel"), "desktop frame"),
        )
        for mutate, message in mutations:
            value = json.loads(passing)
            mutate(value)
            with self.assertRaisesRegex(TestFailure, message):
                _validate_desktop_icon_events(json.dumps(value, ensure_ascii=False))

    def test_desktop_terminal_oracle_rejects_wrong_target_or_application(self):
        passing = self._events(
            {
                "event": "qmp-click",
                "request": "desktop-background-context",
                "target": "desktop-background",
                "button": "right",
                "role": "frame",
                "application": "gjs",
                "bounds": [0, 0, 1280, 752],
            },
            {
                "event": "click",
                "target": "desktop_open_terminal",
                "accessible_name": "Open in Terminal",
                "actions": ["click"],
            },
            {
                "event": "desktop-terminal",
                "phase": "opened",
                "visible": True,
                "application": "ptyxis",
                "windows": [["ptyxis", "frame", "Desktop"]],
                "directory": "/home/anduinostest/Desktop",
            },
            {
                "event": "qmp-key",
                "request": "desktop-terminal-close",
                "key": "alt-f4",
            },
            {
                "event": "desktop-terminal",
                "phase": "closed",
                "visible": False,
            },
        )
        _validate_desktop_terminal_events(passing)
        mutations = (
            (0, "target", "主目录", "exactly one semantic event"),
            (0, "application", "gnome-shell", "target DING"),
            (1, "accessible_name", "Delete", "Open in Terminal"),
            (2, "application", "org.gnome.Nautilus", "open Ptyxis"),
            (2, "directory", "/tmp", "in the desktop"),
        )
        for index, key, replacement, message in mutations:
            values = [json.loads(line) for line in passing.splitlines()]
            values[index][key] = replacement
            output = "\n".join(json.dumps(value) for value in values)
            with self.assertRaisesRegex(TestFailure, message):
                _validate_desktop_terminal_events(output)

    def test_desktop_background_probe_uses_ding_frame_not_fixed_coordinates(self):
        source = (ROOT / "guest" / "atspi_driver.py").read_text(encoding="utf-8")
        body = source.split("def exercise_desktop_terminal", 1)[1].split(
            "def _desktop_fixture_click_target", 1
        )[0]
        self.assertIn("frames = _desktop_frames()", body)
        self.assertIn("request_node_click(", body)
        self.assertIn('semantic_target="desktop-background"', body)
        self.assertNotRegex(body, r"x_px\s*=|y_px\s*=")

    def test_super_i_oracle_rejects_an_unrelated_window(self):
        passing = self._events(
            {
                "event": "qmp-key",
                "request": "shortcut-super-i",
                "key": "meta_l-i",
            },
            {
                "event": "shortcut-window",
                "shortcut": "super-i",
                "application": "gnome-control-center",
                "window": "设置",
                "focused": True,
            },
        )
        _validate_super_i_events(passing)
        with self.assertRaisesRegex(TestFailure, "unrelated application"):
            _validate_super_i_events(passing.replace("gnome-control-center", "firefox"))

    def test_super_u_oracle_rejects_a_non_restored_extension(self):
        passing = self._events(
            {
                "event": "network-stats",
                "phase": "before",
                "state": "INITIALIZED",
                "visible": False,
            },
            {
                "event": "qmp-key",
                "request": "shortcut-super-u-show",
                "key": "meta_l-u",
            },
            {
                "event": "network-stats",
                "phase": "shown",
                "state": "ACTIVE",
                "visible": True,
                "nodes": [["label", "↑ 1 KB/s"]],
            },
            {
                "event": "qmp-key",
                "request": "shortcut-super-u-hide",
                "key": "meta_l-u",
            },
            {
                "event": "network-stats",
                "phase": "restored",
                "state": "INACTIVE",
                "visible": False,
            },
        )
        _validate_super_u_events(passing)
        lines = passing.splitlines()
        lines[-1] = lines[-1].replace("INACTIVE", "ACTIVE")
        with self.assertRaisesRegex(TestFailure, "restore Network Stats"):
            _validate_super_u_events("\n".join(lines))

    def test_screenshot_shortcut_oracle_rejects_a_fake_png(self):
        passing = self._events(
            {
                "event": "qmp-key",
                "request": "shortcut-screenshot-open",
                "key": "meta_l-shift-s",
            },
            {
                "event": "screenshot-ui",
                "visible": True,
                "modes": ["选区", "屏幕", "窗口"],
                "completion": "focused-default-action",
            },
            {
                "event": "qmp-key",
                "request": "shortcut-screenshot-capture",
                "key": "ret",
            },
            {
                "event": "screenshot-created",
                "path": "/home/user/Pictures/Screenshot.png",
                "size": 4096,
                "png_signature": True,
            },
        )
        result = _validate_screenshot_shortcut_events(passing)
        self.assertEqual("/home/user/Pictures/Screenshot.png", result["path"])
        missing_mode = passing.replace(
            '["\\u9009\\u533a", "\\u5c4f\\u5e55", "\\u7a97\\u53e3"]',
            '["\\u9009\\u533a", "\\u5c4f\\u5e55"]',
        )
        with self.assertRaisesRegex(TestFailure, "all three modes"):
            _validate_screenshot_shortcut_events(missing_mode)
        with self.assertRaisesRegex(TestFailure, "png_signature=True"):
            _validate_screenshot_shortcut_events(
                passing.replace('"png_signature": true', '"png_signature": false')
            )

    def test_start_button_oracle_rejects_a_non_anduinos_render(self):
        asset = (
            "/usr/share/gnome-shell/extensions/arcmenu@arcmenu.com/icons/"
            "anduinos-logo.svg"
        )
        digest = "a" * 64
        passing = self._events(
            {
                "event": "start-button",
                "accessible_name": "显示应用",
                "role": "toggle button",
                "bounds": [10, 10, 30, 30],
                "bounds_usable": True,
                "asset": asset,
                "asset_sha256": digest,
                "rendered_template": "/tmp/start-button-installed-logo.png",
                "rendered_size": [20, 20],
            },
            {
                "event": "qmp-key",
                "request": "start-button-open",
                "key": "meta_l",
            },
            {
                "event": "start-menu",
                "phase": "shown",
                "markers": ["已固定", "所有应用程序"],
                "marker_roles": ["label"],
                "overview_visible": False,
            },
            {
                "event": "qmp-key",
                "request": "start-button-close",
                "key": "esc",
            },
            {"event": "start-menu", "phase": "restored", "visible": False},
        )
        event = _validate_start_button_events(passing)
        _validate_start_button_contract(
            "\n".join(
                (
                    f"menu-button-icon='{asset}'",
                    f"custom-menu-button-icon='{asset}'",
                    "menu-button-icon-size=34",
                    f"{digest}  {asset}",
                )
            ),
            event,
        )
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            template = Image.new("RGBA", (20, 20), (0, 0, 0, 0))
            draw = ImageDraw.Draw(template)
            draw.rectangle((5, 2, 14, 17), fill=(62, 141, 245, 255))
            draw.rectangle((2, 6, 17, 13), fill=(53, 124, 244, 255))
            template_path = root / "logo.png"
            template.save(template_path)
            good = Image.new("RGB", (80, 100), (28, 28, 32))
            good.paste(template, (15, 15), template)
            good.paste(template, (30, 72), template)
            good_path = root / "good.png"
            good.save(good_path)
            assert_start_button_logo(
                good_path,
                template_path,
                [10, 10, 30, 30],
                root / "good.json",
            )
            assert_start_button_logo(
                good_path,
                template_path,
                [0, 0, 0, 0],
                root / "good-fallback.json",
            )
            bad = Image.new("RGB", (80, 100), (28, 28, 32))
            ImageDraw.Draw(bad).rectangle((15, 15, 34, 34), fill=(220, 40, 40))
            bad_path = root / "bad.png"
            bad.save(bad_path)
            with self.assertRaisesRegex(
                TestFailure, "did not match|contains no AnduinOS-blue"
            ):
                assert_start_button_logo(
                    bad_path,
                    template_path,
                    [10, 10, 30, 30],
                    root / "bad.json",
                )

    def test_localization_oracle_requires_chinese_on_three_desktop_surfaces(self):
        passing = self._events(
            {
                "event": "localization-zh-cn",
                "settings_labels": ["关于", "操作系统"],
                "desktop_labels": ["主目录", "回收站"],
                "arcmenu_labels": ["已固定", "所有应用程序"],
            }
        )
        _validate_localization_zh_cn_events(passing)
        for field, missing in (
            ("settings_labels", "操作系统"),
            ("desktop_labels", "回收站"),
            ("arcmenu_labels", "所有应用程序"),
        ):
            value = json.loads(passing)
            value[field].remove(missing)
            with self.subTest(field=field), self.assertRaisesRegex(
                TestFailure,
                field,
            ):
                _validate_localization_zh_cn_events(json.dumps(value))

    def test_settings_about_oracle_requires_visible_anduinos_identity(self):
        assets = [
            {
                "path": "/usr/share/pixmaps/ubuntu-logo-text.svg",
                "sha256": "a" * 64,
                "brand_markers": ["ANDUINOS", "anduinos"],
                "rendered_template": "/tmp/settings-about-light-logo.png",
            },
            {
                "path": "/usr/share/pixmaps/ubuntu-logo-text-dark.svg",
                "sha256": "b" * 64,
                "brand_markers": ["ANDUINOS", "anduinos"],
                "rendered_template": "/tmp/settings-about-dark-logo.png",
            },
        ]
        passing = self._events(
            {
                "event": "settings-about-branding",
                "application": "设置",
                "page": "about",
                "operating_system": "AnduinOS 2.0.1",
                # GNOME 50 exposes GtkPicture as an unnamed AT-SPI image even
                # when the UI resource supplies alternative-text.
                "logo_name": "",
                "logo_role": "image",
                "coordinate_space": "window",
                "bounds": [100, 80, 400, 82],
                "assets": assets,
            }
        )
        event = _validate_settings_about_events(passing)
        self.assertEqual("AnduinOS 2.0.1", event["operating_system"])
        with self.assertRaisesRegex(TestFailure, "identify AnduinOS"):
            _validate_settings_about_events(
                passing.replace("AnduinOS 2.0.1", "Ubuntu 26.10")
            )
        with self.assertRaisesRegex(TestFailure, "semantic About logo"):
            _validate_settings_about_events(
                passing.replace("[100, 80, 400, 82]", "[0, 0, 0, 0]")
            )
        with self.assertRaisesRegex(TestFailure, "verifiable AnduinOS identity"):
            _validate_settings_about_events(
                passing.replace(
                    '["ANDUINOS", "anduinos"]', '["Ubuntu", "ubuntu"]', 1
                )
            )

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            light = Image.new("RGBA", (80, 20), (0, 0, 0, 0))
            draw = ImageDraw.Draw(light)
            draw.rectangle((2, 2, 17, 17), fill=(53, 124, 244, 255))
            draw.rectangle((22, 4, 76, 16), fill=(60, 60, 60, 255))
            dark = Image.new("RGBA", (80, 20), (0, 0, 0, 0))
            draw = ImageDraw.Draw(dark)
            draw.rectangle((2, 2, 17, 17), fill=(53, 124, 244, 255))
            draw.rectangle((22, 4, 76, 16), fill=(245, 245, 245, 255))
            light_path = root / "light.png"
            dark_path = root / "dark.png"
            light.save(light_path)
            dark.save(dark_path)
            screen = Image.new("RGB", (160, 100), (245, 245, 245))
            screen.paste(light, (40, 30), light)
            good_path = root / "good.png"
            screen.save(good_path)
            assert_settings_about_logo(
                good_path,
                [light_path, dark_path],
                [30, 20, 100, 40],
                root / "good.json",
            )
            bad_path = root / "bad.png"
            Image.new("RGB", (160, 100), (245, 245, 245)).save(bad_path)
            with self.assertRaisesRegex(TestFailure, "matched neither"):
                assert_settings_about_logo(
                    bad_path,
                    [light_path, dark_path],
                    [30, 20, 100, 40],
                    root / "bad.json",
                )

        driver = (ROOT / "guest" / "atspi_driver.py").read_text(encoding="utf-8")
        about = driver.split("def exercise_settings_about_branding", 1)[1].split(
            "def _extension_state", 1
        )[0]
        self.assertIn('"gnome-control-center",\n            "system",\n            "about"', about)
        self.assertIn("get_extents(Atspi.CoordType.WINDOW)", about)
        self.assertIn("GdkPixbuf.Pixbuf.new_from_file_at_scale", about)
        self.assertNotIn("qmp-click", about)
        runner = (ROOT / "iso_test" / "feature_runner.py").read_text(
            encoding="utf-8"
        )
        self.assertIn('("pkill", "-f", "(^|/)gnome-control-center( |$)")', runner)
        self.assertNotIn('("pkill", "-x", "gnome-control-center")', runner)

    def test_swapcontrol_oracle_requires_real_green_dashboard(self):
        passing = self._events(
            {
                "event": "secret-focus",
                "request": "swapcontrol-auth-password",
                "target": "password",
                "method": "polkit-initial-password-focus",
            },
            {
                "event": "qmp-secret",
                "request": "swapcontrol-auth-password",
            },
            {
                "event": "qmp-key",
                "request": "swapcontrol-auth-submit",
                "key": "ret",
            },
            {
                "event": "swapcontrol-authentication",
                "outcome": "authenticated",
            },
            {
                "event": "swapcontrol-dashboard",
                "application": "swapcontrol-gtk",
                "page": "dashboard",
                "markers": ["dashboard", "memory-overview", "swap", "zram"],
                "observed_labels": {
                    "dashboard": "仪表板",
                    "memory-overview": "内存概览",
                    "swap": "虚拟内存",
                    "zram": "压缩内存段",
                },
                "authentication": "authenticated",
                "accessibility_focus": False,
                "coordinate_space": "window",
                "bounds": [0, 0, 1100, 650],
            }
        )
        event = _validate_swapcontrol_events(passing)
        self.assertEqual("dashboard", event["page"])
        with self.assertRaisesRegex(TestFailure, "real dashboard"):
            _validate_swapcontrol_events(
                passing.replace('"zram"', '"unrelated"', 1)
            )

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            good = Image.new("RGB", (200, 120), (35, 35, 35))
            ImageDraw.Draw(good).rectangle((40, 20, 119, 99), fill=(42, 170, 75))
            good_path = root / "good.png"
            good.save(good_path)
            assert_swapcontrol_green(good_path, root / "good.json")

            bad_path = root / "bad.png"
            Image.new("RGB", (200, 120), (90, 90, 90)).save(bad_path)
            with self.assertRaisesRegex(TestFailure, "green dashboard"):
                assert_swapcontrol_green(bad_path, root / "bad.json")

        driver = (ROOT / "guest" / "atspi_driver.py").read_text(encoding="utf-8")
        self.assertIn('"swapcontrol-green"', driver)
        self.assertIn("exercise_swapcontrol_green(args.evidence)", driver)

    def test_file_integration_oracles_require_content_and_real_applications(self):
        thumbnail = self._events(
            {
                "event": "file-thumbnail",
                "filename": "AnduinOS-Image.png",
                "uri": "file:///home/anduinostest/Downloads/AnduinOS-Image.png",
                "cache_path": (
                    "/home/anduinostest/.cache/thumbnails/large/"
                    + "a" * 32
                    + ".png"
                ),
                "cache_size": 4096,
                "visible_nodes": [
                    {"name": "AnduinOS-Image.png", "role": "table row"}
                ],
            }
        )
        value = _validate_thumbnail_events(
            thumbnail,
            "AnduinOS-Image.png",
            "anduinostest",
        )
        self.assertEqual(4096, value["cache_size"])
        with self.assertRaisesRegex(TestFailure, "invalid thumbnail"):
            _validate_thumbnail_events(
                thumbnail.replace('"cache_size": 4096', '"cache_size": 0'),
                "AnduinOS-Image.png",
                "anduinostest",
            )

        image = self._events(
            {
                "event": "image-opened",
                "filename": "AnduinOS-Image.png",
                "application": "loupe",
                "process_running": True,
                "visible_names": ["AnduinOS-Image.png"],
            }
        )
        _validate_image_open_events(image)
        with self.assertRaisesRegex(TestFailure, "real visible image"):
            _validate_image_open_events(
                image.replace('"process_running": true', '"process_running": false')
            )

        video = self._events(
            {
                "event": "video-opened",
                "filename": "AnduinOS-Video.mp4",
                "application": "celluloid",
                "mpris_destination": "org.mpris.MediaPlayer2.celluloid.instance1",
                "playback_status": "Playing",
                "position_microseconds": 500000,
                "metadata_identifies_fixture": True,
            }
        )
        _validate_video_open_events(video)
        with self.assertRaisesRegex(TestFailure, "exact video"):
            _validate_video_open_events(
                video.replace("500000", "0")
            )

        deb = self._events(
            {
                "event": "deb-software",
                "filename": "anduinos-acceptance-fixture_1.0_all.deb",
                "application": "软件",
                "detail_names": ["AnduinOS Acceptance Fixture"],
                "package_installed": False,
            }
        )
        _validate_deb_software_events(deb)
        with self.assertRaisesRegex(TestFailure, "harmless DEB safely"):
            _validate_deb_software_events(
                deb.replace('"package_installed": false', '"package_installed": true')
            )

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            good = Image.new("RGB", (160, 120), (0, 0, 0))
            draw = ImageDraw.Draw(good)
            draw.rectangle((0, 0, 79, 59), fill=(235, 45, 55))
            draw.rectangle((80, 0, 159, 59), fill=(45, 210, 90))
            draw.rectangle((0, 60, 79, 119), fill=(45, 100, 235))
            draw.rectangle((80, 60, 159, 119), fill=(245, 210, 40))
            good_path = root / "good.png"
            good.save(good_path)
            assert_fixture_quadrants(good_path, root / "good.json")
            contaminated = Image.new("RGB", (400, 220), (28, 28, 32))
            draw = ImageDraw.Draw(contaminated)
            draw.rectangle((260, 0, 399, 219), fill=(35, 95, 220))
            draw.rectangle((20, 20, 119, 99), fill=(235, 45, 55))
            draw.rectangle((120, 20, 219, 99), fill=(45, 210, 90))
            draw.rectangle((20, 100, 119, 179), fill=(45, 100, 235))
            draw.rectangle((120, 100, 219, 179), fill=(245, 210, 40))
            contaminated_path = root / "contaminated.png"
            contaminated.save(contaminated_path)
            assert_fixture_quadrants(
                contaminated_path,
                root / "contaminated.json",
            )
            bad_path = root / "bad.png"
            Image.new("RGB", (160, 120), (128, 128, 128)).save(bad_path)
            with self.assertRaisesRegex(TestFailure, "content quadrants"):
                assert_fixture_quadrants(bad_path, root / "bad.json")

    def test_chinese_editor_oracle_requires_exact_saved_utf8_and_host_save(self):
        expected = "变角次亮采之门"
        unicode_input = []
        for index, _character in enumerate(expected):
            unicode_input.extend(
                (
                    {
                        "event": "qmp-key",
                        "request": f"chinese-editor-unicode-{index}-start",
                        "key": "ctrl-shift-u",
                    },
                    {
                        "event": "qmp-text",
                        "request": f"chinese-editor-unicode-{index}-codepoint",
                    },
                    {
                        "event": "qmp-key",
                        "request": f"chinese-editor-unicode-{index}-commit",
                        "key": "ret",
                    },
                )
            )
        passing = self._events(
            *unicode_input,
            {
                "event": "text-editor-action",
                "purpose": "main-menu",
                "accessible_name": "主菜单",
                "actions": ["click"],
            },
            {
                "event": "qmp-click",
                "request": "chinese-editor-save-menu-row",
                "target": "Save",
                "anchor": "fixed-1280x800-framebuffer",
                "x_px": 852,
                "y_px": 364,
                "button": "left",
                "framebuffer": [1280, 800],
            },
            {
                "event": "chinese-editor",
                "filename": "AnduinOS-Chinese.txt",
                "application": "文本编辑器",
                "expected": expected,
                "observed": expected,
                "menu_accessible_name": "主菜单",
                "save_accessible_name": "Save menu row",
                "character_count": len(expected),
                "utf8_sha256": hashlib.sha256(
                    (expected + "\n").encode("utf-8")
                ).hexdigest(),
                "implicit_trailing_newline": True,
                "process_running": True,
                "saved": True,
            },
        )
        _validate_chinese_editor_events(passing)
        with self.assertRaisesRegex(TestFailure, "exact normalized Chinese"):
            _validate_chinese_editor_events(
                passing.replace(
                    json.dumps(expected),
                    json.dumps("变角次亮采之问"),
                    1,
                )
            )
        with self.assertRaisesRegex(TestFailure, "Save menu row"):
            _validate_chinese_editor_events(
                passing.replace('"target": "Save"', '"target": "Save As"')
            )
        with self.assertRaisesRegex(TestFailure, "Unicode text"):
            _validate_chinese_editor_events(
                passing.replace('"key": "ctrl-shift-u"', '"key": "spc"', 1)
            )

    def test_panel_pin_oracle_rejects_missing_session_persistence(self):
        initial_output = self._events(
            {
                "event": "qmp-key",
                "request": "panel-pin-search-open",
                "key": "meta_l",
            },
            {"event": "qmp-text", "request": "panel-pin-search-text"},
            {
                "event": "start-search-result",
                "query": "AnduinOS Panel Acceptance Fixture",
                "accessible_name": "AnduinOS Panel Acceptance Fixture",
                "role": "text",
                "application": "gnome-shell",
                "stable_observations": 4,
            },
            {
                "event": "search-entry-focus",
                "query": "AnduinOS Panel Acceptance Fixture",
                "role": "text",
                "application": "gnome-shell",
                "focused": True,
            },
            {
                "event": "search-result-context",
                "target": "AnduinOS Panel Acceptance Fixture",
                "query": "AnduinOS Panel Acceptance Fixture",
                "application": "gnome-shell",
                "focused": True,
                "method": "search-entry-popup-menu",
            },
            {
                "event": "qmp-key",
                "request": "panel-pin-context",
                "key": "shift-f10",
            },
            *self._context_action_events(
                "taskbar_pin",
                "添加到任务栏",
                "panel-pin-action",
                [
                    "新建窗口",
                    "创建桌面快捷方式",
                    "添加到任务栏",
                    "固定到开始菜单",
                    "应用详细信息",
                ],
                2,
            ),
            {
                "event": "panel-pinned",
                "application": "AnduinOS Panel Acceptance Fixture",
                "menu_label": "添加到任务栏",
                "launcher_name": "AnduinOS Panel Acceptance Fixture",
                "launcher_role": "button",
            },
        )
        persisted_output = self._events(
            {
                "event": "panel-pinned-after-login",
                "application": "AnduinOS Panel Acceptance Fixture",
                "launcher_name": "AnduinOS Panel Acceptance Fixture",
                "launcher_role": "button",
                "visible": True,
            }
        )
        initial = _validate_panel_pin_initial_events(initial_output)
        with self.assertRaisesRegex(TestFailure, "unstable ArcMenu"):
            _validate_panel_pin_initial_events(
                initial_output.replace('"stable_observations": 4', '"stable_observations": 1')
            )
        persisted = _validate_panel_pin_persisted_events(persisted_output)
        _validate_panel_pin_roundtrip(
            initial,
            persisted,
            before_session="2",
            after_session="4",
        )
        with self.assertRaisesRegex(TestFailure, "fresh Shell session"):
            _validate_panel_pin_roundtrip(
                initial,
                persisted,
                before_session="2",
                after_session="2",
            )

    def test_panel_remove_oracle_rejects_an_unlocalized_action(self):
        passing = self._events(
            {
                "event": "qmp-click",
                "request": "panel-remove-context",
                "target": "AnduinOS Panel Acceptance Fixture",
                "button": "right",
            },
            *self._context_action_events(
                "taskbar_unpin",
                "从任务栏中移除",
                "panel-remove-action",
                ["新建窗口", "从任务栏中移除"],
                1,
            ),
            {
                "event": "panel-removed",
                "application": "AnduinOS Panel Acceptance Fixture",
                "localized_label": "从任务栏中移除",
                "launcher_visible": False,
            },
        )
        _validate_panel_remove_events(passing)
        unlocalized = []
        for line in passing.splitlines():
            value = json.loads(line)
            if value.get("accessible_name") == "从任务栏中移除":
                value["accessible_name"] = "Unpin"
            if value.get("localized_label") == "从任务栏中移除":
                value["localized_label"] = "Unpin"
            unlocalized.append(json.dumps(value))
        with self.assertRaisesRegex(TestFailure, "exactly one semantic event"):
            _validate_panel_remove_events("\n".join(unlocalized))

    def test_appindicator_oracle_requires_lower_right_same_process_roundtrip(self):
        process = {
            "pid": 5010,
            "uid": 1000,
            "start_time_ticks": 987654,
            "command": "python3 /usr/local/lib/anduinos-acceptance-shell/indicator_fixture.py",
        }
        window = {
            "accessible_name": "AnduinOS Indicator Fixture Window",
            "role": "frame",
            "application": "python3",
        }
        passing = self._events(
            {
                "event": "appindicator-baseline",
                "window": window,
                "process": process,
                "visible": True,
            },
            {
                "event": "qmp-key",
                "request": "appindicator-close-window",
                "key": "alt-f4",
            },
            {
                "event": "appindicator-hidden",
                "indicator": {
                    "accessible_name": "AnduinOS Acceptance Indicator",
                    "target_name": "AnduinOS Acceptance Indicator",
                    "role": "menu",
                    "application": "gnome-shell",
                    "bounds": [2104, 1392, 48, 48],
                    "screen": [2560, 1440],
                    "lower_right": True,
                },
                "process": process,
                "window_visible": False,
            },
            {
                "event": "spice-double-click",
                "request": "appindicator-restore-window",
                "target": "AnduinOS Acceptance Indicator",
                "button": "left",
                "application": "gnome-shell",
                "clicks": 2,
            },
            {
                "event": "appindicator-restored",
                "window": window,
                "process": process,
                "same_process": True,
                "visible": True,
            },
        )
        value = _validate_appindicator_roundtrip_events(passing)
        self.assertEqual(5010, value["process"]["pid"])
        with self.assertRaisesRegex(TestFailure, "same process"):
            _validate_appindicator_roundtrip_events(
                passing.replace('"start_time_ticks": 987654', '"start_time_ticks": 987655', 1)
            )
        with self.assertRaisesRegex(TestFailure, "lower-right"):
            _validate_appindicator_roundtrip_events(
                passing.replace('"lower_right": true', '"lower_right": false')
            )

        fixture = (ROOT / "guest/indicator_fixture.py").read_text(encoding="utf-8")
        self.assertIn("org.kde.StatusNotifierItem", fixture)
        self.assertIn("com.canonical.dbusmenu", fixture)
        self.assertIn("RegisterStatusNotifierItem", fixture)
        self.assertNotIn("AyatanaAppIndicator", fixture)
        self.assertNotIn("AppIndicator3", fixture)

    def test_desktop_shortcut_oracle_rejects_an_untrusted_launcher(self):
        passing = self._events(
            {
                "event": "qmp-key",
                "request": "desktop-shortcut-search-open",
                "key": "meta_l",
            },
            {"event": "qmp-text", "request": "desktop-shortcut-search-text"},
            {
                "event": "start-search-result",
                "query": "AnduinOS Panel Acceptance Fixture",
                "accessible_name": "AnduinOS Panel Acceptance Fixture",
                "application": "gnome-shell",
                "stable_observations": 4,
            },
            {
                "event": "search-entry-focus",
                "query": "AnduinOS Panel Acceptance Fixture",
                "role": "text",
                "application": "gnome-shell",
                "focused": True,
            },
            {
                "event": "search-result-context",
                "target": "AnduinOS Panel Acceptance Fixture",
                "query": "AnduinOS Panel Acceptance Fixture",
                "application": "gnome-shell",
                "focused": True,
                "method": "search-entry-popup-menu",
            },
            {
                "event": "qmp-key",
                "request": "desktop-shortcut-context",
                "key": "shift-f10",
            },
            *self._context_action_events(
                "desktop_shortcut_create",
                "创建桌面快捷方式",
                "desktop-shortcut-action",
                [
                    "新建窗口",
                    "创建桌面快捷方式",
                    "添加到任务栏",
                    "固定到开始菜单",
                    "应用详细信息",
                ],
                1,
            ),
            {
                "event": "spice-double-click",
                "request": "desktop-shortcut-launch",
                "target": "AnduinOS Panel Acceptance Fixture",
                "accessible_name": "AnduinOS Panel Acceptance Fixture",
                "role": "label",
                "application": "gjs",
                "button": "left",
                "clicks": 2,
                "positioning_clicks": 1,
                "double_click_time_ms": 400,
                "x_px": 64.0,
                "y_px": 344.0,
                "bounds": [9, 323, 110, 42],
            },
            {
                "event": "desktop-shortcut",
                "application": "AnduinOS Panel Acceptance Fixture",
                "localized_label": "创建桌面快捷方式",
                "path": "/home/user/桌面/com.anduinos.AcceptancePanelFixture.desktop",
                "executable": True,
                "trusted": True,
                "visible": True,
                "launched_windows": [
                    "AnduinOS Panel Fixture Window",
                ],
            },
        )
        _validate_desktop_shortcut_events(passing)
        with self.assertRaisesRegex(TestFailure, "unstable ArcMenu"):
            _validate_desktop_shortcut_events(
                passing.replace('"stable_observations": 4', '"stable_observations": 1')
            )
        with self.assertRaisesRegex(TestFailure, "exactly one semantic event"):
            _validate_desktop_shortcut_events(
                passing.replace('"trusted": true', '"trusted": false')
            )

        with self.assertRaisesRegex(TestFailure, "exactly one semantic event"):
            _validate_desktop_shortcut_events(
                passing.replace('"clicks": 2', '"clicks": 1')
            )

        with self.assertRaisesRegex(TestFailure, "label hit area"):
            _validate_desktop_shortcut_events(
                passing.replace('"role": "label"', '"role": "filler"')
            )

    def test_spotify_store_oracle_rejects_an_unrelated_details_page(self):
        passing = self._events(
            {
                "event": "qmp-key",
                "request": "spotify-search-open",
                "key": "meta_l",
            },
            {"event": "qmp-text", "request": "spotify-search-text"},
            {
                "event": "start-search-result",
                "query": "Spotify",
                "accessible_name": "Spotify",
                "role": "text",
                "application": "gnome-shell",
                "stable_observations": 4,
            },
            {
                "event": "search-entry-focus",
                "query": "Spotify",
                "role": "text",
                "application": "gnome-shell",
                "focused": True,
            },
            {
                "event": "qmp-key",
                "request": "spotify-result-activate",
                "key": "ret",
            },
            {
                "event": "spotify-result-activated",
                "accessible_name": "Spotify",
                "role": "text",
                "method": "qmp-keyboard",
            },
            {
                "event": "spotify-store",
                "application": "gnome-software",
                "detail_names": ["Spotify"],
                "visible": True,
            },
        )
        _validate_spotify_store_events(passing)
        with self.assertRaisesRegex(TestFailure, "unstable ArcMenu"):
            _validate_spotify_store_events(
                passing.replace('"stable_observations": 4', '"stable_observations": 1')
            )
        with self.assertRaisesRegex(TestFailure, "real Software details page"):
            _validate_spotify_store_events(
                passing.replace('"application": "gnome-software"', '"application": "firefox"')
            )

    def test_account_creation_oracle_rejects_the_wrong_details_action(self):
        passing = "\n".join(
            json.dumps(event, ensure_ascii=False)
            for event in (
                {
                    "event": "focused-activation",
                    "target": "add_user",
                    "method": "localized-mnemonic",
                },
                {"event": "set-radio", "target": "set_password_now"},
                {
                    "event": "focused-activation",
                    "target": "next",
                    "method": "localized-mnemonic",
                },
                {
                    "event": "qmp-secret",
                    "request": "accounts-initial-password",
                },
                {
                    "event": "qmp-secret",
                    "request": "accounts-initial-confirmation",
                },
                {
                    "event": "password-pair-accepted",
                    "context": "account-create",
                },
                {
                    "event": "focused-activation",
                    "target": "add",
                    "accessible_name": "添加(A)",
                    "method": "atspi-action",
                    "action": "click",
                    "mnemonic": "alt-a",
                    "mnemonic_owner_count": 2,
                },
                {"event": "user-created", "account": "second"},
            )
        )
        _validate_account_creation_events(passing)
        with self.assertRaisesRegex(TestFailure, "target='next'"):
            _validate_account_creation_events(
                passing.replace('"target": "next"', '"target": "add"', 1)
            )
        with self.assertRaisesRegex(
            TestFailure,
            "accounts-initial-confirmation",
        ):
            _validate_account_creation_events(
                "\n".join(
                    line
                    for line in passing.splitlines()
                    if "accounts-initial-confirmation" not in line
                )
            )
        with self.assertRaisesRegex(TestFailure, "password-pair-accepted"):
            _validate_account_creation_events(
                "\n".join(
                    line
                    for line in passing.splitlines()
                    if "password-pair-accepted" not in line
                )
            )
        with self.assertRaisesRegex(TestFailure, "localized-mnemonic"):
            _validate_account_creation_events(
                passing.replace("localized-mnemonic", "keyboard-focus", 1)
            )
        with self.assertRaisesRegex(TestFailure, "exact final Add"):
            _validate_account_creation_events(
                passing.replace("添加(A)", "添加用户(A)", 1)
            )
        with self.assertRaisesRegex(TestFailure, "accessible button action"):
            _validate_account_creation_events(
                passing.replace('"action": "click"', '"action": "copy"', 1)
            )
        with self.assertRaisesRegex(TestFailure, "duplicate mnemonic"):
            _validate_account_creation_events(
                passing.replace('"mnemonic_owner_count": 2', '"mnemonic_owner_count": 1')
            )

    def test_theme_selector_oracle_rejects_an_unlocalized_label(self):
        passing = json.dumps(
            {
                "event": "theme-menu",
                "transition": "prefer-dark",
                "method": "opened",
            },
            ensure_ascii=False,
        ) + "\n" + json.dumps(
            {
                "event": "theme-selected",
                "expected": "dark",
                "color_scheme": "prefer-dark",
                "localized_label": "暗色样式",
                "transitions": ["prefer-dark"],
            },
            ensure_ascii=False,
        )
        _validate_theme_selection(passing, "dark")
        with self.assertRaisesRegex(TestFailure, "localized theme label"):
            _validate_theme_selection(passing.replace("暗色样式", "Dark Style"), "dark")

    def test_theme_selector_oracle_requires_shells_default_light_state(self):
        passing = json.dumps(
            {
                "event": "theme-menu",
                "transition": "default",
                "method": "already-open",
            },
            ensure_ascii=False,
        ) + "\n" + json.dumps(
            {
                "event": "theme-selected",
                "expected": "light",
                "color_scheme": "default",
                "localized_label": "暗色样式",
                "transitions": ["default"],
            },
            ensure_ascii=False,
        )
        _validate_theme_selection(passing, "light")
        with self.assertRaisesRegex(TestFailure, "expected interface color scheme"):
            _validate_theme_selection(
                passing.replace('"default"', '"prefer-light"'),
                "light",
            )
        with self.assertRaisesRegex(TestFailure, "real Shell menu"):
            _validate_theme_selection(passing.split("\n", 1)[1], "light")

    def test_theme_marker_oracle_rejects_a_stale_firefox_page(self):
        passing = json.dumps(
            {
                "event": "theme-marker",
                "expected": "FIREFOX LIGHT",
                "observed": "FIREFOX LIGHT",
                "application": "firefox",
            }
        )
        _validate_theme_marker(passing, "FIREFOX LIGHT")
        with self.assertRaisesRegex(TestFailure, "marker is wrong"):
            _validate_theme_marker(
                passing.replace("FIREFOX LIGHT", "FIREFOX DARK"),
                "FIREFOX LIGHT",
            )
        with self.assertRaisesRegex(TestFailure, "real browser"):
            _validate_theme_marker(passing.replace("firefox", "text-editor"), "FIREFOX LIGHT")

    def test_live_theme_oracle_rejects_a_restarted_qt_fixture(self):
        _validate_same_fixture_process(42, 42, "Qt")
        with self.assertRaisesRegex(TestFailure, "restarted"):
            _validate_same_fixture_process(42, 84, "Qt")

    def test_account_record_oracle_rejects_an_administrator(self):
        passing = "\n".join(
            (
                "account=second",
                "passwd=present",
                "groups=second",
                "standard-user=yes",
                "password=usable",
            )
        )
        _validate_account_record(passing, "second")
        with self.assertRaisesRegex(TestFailure, "standard-user=yes"):
            _validate_account_record(
                passing.replace("standard-user=yes", "standard-user=no"), "second"
            )

    def test_graphical_login_oracle_rejects_a_non_wayland_session(self):
        passing = (
            "graphical-user=second\n"
            "session-id=8\n"
            "session-name=second\n"
            "session-class=user\n"
            "session-type=wayland\n"
            "session-active=yes\n"
            "session-remote=no\n"
            "home-owner=second\n"
        )
        _validate_graphical_login(passing, "second")
        with self.assertRaisesRegex(TestFailure, "session-type=wayland"):
            _validate_graphical_login(
                passing.replace("session-type=wayland", "session-type=tty"),
                "second",
            )
        with self.assertRaisesRegex(TestFailure, "session-class=user"):
            _validate_graphical_login(
                passing.replace("session-class=user", "session-class=manager"),
                "second",
            )

    def test_gdm_login_oracle_rejects_a_missing_password_submission(self):
        passing = "\n".join(
            json.dumps(event, ensure_ascii=False)
            for event in (
                {
                    "event": "gdm-user-target",
                    "account": "second",
                    "accessible_name": "Second User",
                    "role": "label",
                    "focused": False,
                    "attempt": 1,
                },
                {
                    "event": "qmp-click",
                    "request": "gdm-select-user",
                    "target": "second",
                    "accessible_name": "Second User",
                    "x_px": 220,
                    "y_px": 224,
                    "bounds": [100, 200, 240, 48],
                    "attempt": 1,
                },
                {
                    "event": "gdm-password-prompt",
                    "account": "second",
                    "display_name": "Second User",
                    "cancel_controls": 1,
                    "account_label_present": True,
                    "editable_exposed": False,
                    "selection_attempts": 1,
                },
                {
                    "event": "gdm-user-selected",
                    "account": "second",
                    "accessible_name": "Second User",
                    "method": "qmp-atspi-bounds",
                    "bounds": [100, 200, 240, 48],
                    "selection_attempts": 1,
                },
                {"event": "qmp-secret", "request": "gdm-password"},
                {
                    "event": "qmp-key",
                    "request": "gdm-password-submit",
                    "key": "ret",
                },
            )
        )
        _validate_gdm_login_events(passing, "second", "Second User")
        semantic_events = [json.loads(line) for line in passing.splitlines()]
        semantic_events[1] = {
            "event": "gdm-user-action",
            "account": "second",
            "accessible_name": "Second User",
            "owner_role": "button",
            "action": "click",
        }
        semantic_events[3]["method"] = "atspi-action"
        semantic_events[3]["bounds"] = []
        semantic_output = "\n".join(json.dumps(event) for event in semantic_events)
        _validate_gdm_login_events(
            semantic_output,
            "second",
            "Second User",
        )
        with self.assertRaisesRegex(TestFailure, "unrelated AT-SPI action"):
            _validate_gdm_login_events(
                semantic_output.replace('"action": "click"', '"action": "copy"'),
                "second",
                "Second User",
            )
        keyboard_events = [json.loads(line) for line in passing.splitlines()]
        keyboard_events.insert(
            2,
            {
                "event": "qmp-key",
                "request": "gdm-select-user-submit",
                "key": "ret",
                "target": "second",
                "attempt": 1,
            },
        )
        keyboard_events[4]["method"] = "qmp-atspi-bounds-keyboard"
        keyboard_output = "\n".join(json.dumps(event) for event in keyboard_events)
        _validate_gdm_login_events(keyboard_output, "second", "Second User")
        with self.assertRaisesRegex(TestFailure, "gdm-select-user-submit"):
            _validate_gdm_login_events(
                "\n".join(
                    line
                    for line in keyboard_output.splitlines()
                    if "gdm-select-user-submit" not in line
                ),
                "second",
                "Second User",
            )
        with self.assertRaisesRegex(TestFailure, "gdm-password-submit"):
            _validate_gdm_login_events(
                "\n".join(
                    line
                    for line in passing.splitlines()
                    if "gdm-password-submit" not in line
                ),
                "second",
                "Second User",
            )
        with self.assertRaisesRegex(TestFailure, "semantic AT-SPI"):
            _validate_gdm_login_events(
                passing.replace("qmp-atspi-bounds", "hard-coded-coordinate"),
                "second",
                "Second User",
            )
        with self.assertRaisesRegex(TestFailure, "invalid AT-SPI bounds"):
            _validate_gdm_login_events(
                passing.replace("[100, 200, 240, 48]", "[100, 200, 0, 0]"),
                "second",
                "Second User",
            )
        with self.assertRaisesRegex(TestFailure, "hidden password prompt"):
            _validate_gdm_login_events(
                passing.replace('"cancel_controls": 1', '"cancel_controls": 0'),
                "second",
                "Second User",
            )
        with self.assertRaisesRegex(TestFailure, "invalid retry count"):
            _validate_gdm_login_events(
                passing.replace('"selection_attempts": 1', '"selection_attempts": 4'),
                "second",
                "Second User",
            )

    def test_gdm_identity_probe_retries_until_the_live_greeter_exists(self):
        runner = object.__new__(FeatureSuiteRunner)
        console = Mock()
        console.run.side_effect = (
            CommandResult("", 1),
            CommandResult("gdm-greeter\n", 0),
        )
        vm = SimpleNamespace(serial=console)
        with patch("iso_test.feature_runner.time.sleep"):
            self.assertEqual("gdm-greeter", runner._gdm_user(vm))
        probe = console.run.call_args_list[0].args[0]
        self.assertLess(probe.index("gdm-greeter"), probe.index(" gdm;"))
        self.assertIn('test -S "$runtime/bus"', probe)
        self.assertIn("wayland-[0-9]*", probe)

    def test_password_change_oracle_rejects_an_unchanged_hash(self):
        before = "a" * 64
        _validate_password_fingerprint_change(before, "b" * 64)
        with self.assertRaisesRegex(TestFailure, "did not change"):
            _validate_password_fingerprint_change(before, before)

    def test_password_change_ui_oracle_rejects_missing_authentication(self):
        passing = "\n".join(
            json.dumps(event, ensure_ascii=False)
            for event in (
                {
                    "event": "secret-focus",
                    "request": "accounts-current-password-attempt-3",
                    "method": "gnome-dialog-tab-search",
                },
                {
                    "event": "qmp-secret",
                    "request": "accounts-current-password-attempt-3",
                },
                {"event": "current-password-authenticated", "tab_count": 3},
                {
                    "event": "secret-focus",
                    "request": "accounts-new-password",
                    "method": "gnome-dialog-focus-chain",
                },
                {"event": "qmp-secret", "request": "accounts-new-password"},
                {
                    "event": "secret-focus",
                    "request": "accounts-new-confirmation",
                    "method": "gnome-dialog-focus-chain",
                },
                {"event": "qmp-secret", "request": "accounts-new-confirmation"},
                {"event": "password-pair-accepted", "context": "account-change"},
                {
                    "event": "focused-activation",
                    "target": "change",
                    "accessible_name": "更改(A)",
                    "method": "atspi-action",
                    "action": "click",
                },
                {"event": "password-changed"},
            )
        )
        _validate_password_change_events(passing)
        without_authentication = "\n".join(
            line
            for line in passing.splitlines()
            if "current-password-authenticated" not in line
        )
        with self.assertRaisesRegex(TestFailure, "exactly one"):
            _validate_password_change_events(without_authentication)
        lines = passing.splitlines()
        out_of_order = "\n".join((*lines[:-2], lines[-1], lines[-2]))
        with self.assertRaisesRegex(TestFailure, "out of order"):
            _validate_password_change_events(out_of_order)
        with self.assertRaisesRegex(TestFailure, "exact modal Change"):
            _validate_password_change_events(passing.replace("更改(A)", "更改头像"))

    def test_gdm_user_oracle_rejects_a_missing_original_account(self):
        passing = json.dumps(
            {"event": "gdm-users", "accounts": ["first", "second"], "count": 2}
        )
        _validate_gdm_user_events(passing, "first", "second")
        with self.assertRaisesRegex(TestFailure, "wrong accounts"):
            _validate_gdm_user_events(
                json.dumps(
                    {"event": "gdm-users", "accounts": ["second"], "count": 1}
                ),
                "first",
                "second",
            )

    def test_gdm_cursor_contract_rejects_a_default_cursor(self):
        passing = "\n".join(
            (
                "cursor-theme='Fluent-dark-cursors'",
                "cursor-size=32",
                "gdm-brand-package=ii  2.0.0",
                "gdm-brand-asset=present",
            )
        )
        _validate_gdm_cursor_contract(passing)
        with self.assertRaisesRegex(TestFailure, "cursor-theme"):
            _validate_gdm_cursor_contract(
                passing.replace("Fluent-dark-cursors", "Adwaita")
            )

    def test_gdm_contract_keeps_serial_outputs_on_distinct_lines(self):
        self.assertEqual(
            "cursor-theme='Fluent-dark-cursors'\n"
            "cursor-size=32\n"
            "gdm-brand-package=ii  2.0.0\n"
            "gdm-brand-asset=present",
            _join_contract_outputs(
                "cursor-theme='Fluent-dark-cursors'\ncursor-size=32",
                "gdm-brand-package=ii  2.0.0\ngdm-brand-asset=present",
            ),
        )

    def test_ordinary_reboot_oracle_rejects_a_reused_boot_id(self):
        _validate_distinct_boot_ids("first", "second")
        with self.assertRaisesRegex(TestFailure, "distinct boot ID"):
            _validate_distinct_boot_ids("same", "same")

    def test_rime_oracle_rejects_wrong_committed_text(self):
        with tempfile.TemporaryDirectory() as directory:
            evidence = Path(directory) / "rime.json"
            evidence.write_text(
                '{"expected":"你好","observed":"你号","exact":false}\n',
                encoding="utf-8",
            )
            with self.assertRaisesRegex(TestFailure, "exact committed text"):
                _validate_rime_evidence(evidence, "你好")
            evidence.write_text(
                '{"expected":"你好","observed":"你好","exact":true}\n',
                encoding="utf-8",
            )
            _validate_rime_evidence(evidence, "你好")

    def test_btrfs_oracle_rejects_a_surviving_root_sentinel(self):
        passing = "\n".join(
            (
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
            )
        )
        _validate_rollback_health(passing)
        with self.assertRaisesRegex(TestFailure, "root-sentinel=absent"):
            _validate_rollback_health(
                passing.replace("root-sentinel=absent", "root-sentinel=present")
            )

    def test_btrfs_postboot_health_uses_fixed_privileged_helpers(self):
        command = FeatureSuiteRunner._rollback_health_command(
            "/etc/root-sentinel",
            "/home/user/home-sentinel",
            "11111111-1111-4111-8111-111111111111",
        )
        self.assertIn(
            "sudo -n /usr/local/sbin/anduinos-acceptance-package-health",
            command,
        )
        self.assertIn(
            "sudo -n /usr/local/sbin/anduinos-acceptance-boot-health",
            command,
        )
        self.assertIn(
            "sudo -n /usr/local/sbin/anduinos-acceptance-rollback-state",
            command,
        )
        self.assertNotIn("apt-get check", command)
        self.assertNotIn("grub-script-check", command)

    def test_btrfs_postboot_waits_until_graphical_boot_is_really_ready(self):
        command = FeatureSuiteRunner._graphical_boot_ready_command()
        self.assertIn("graphical.target", command)
        self.assertIn("gdm", command)

        runner = object.__new__(FeatureSuiteRunner)
        runner._ssh = Mock(
            side_effect=(
                TestFailure("Feature SSH control failed with 3"),
                "graphical-ready\n",
            )
        )
        with patch("iso_test.feature_runner.time.sleep"):
            output = runner._ssh_eventually(
                SimpleNamespace(), Path("control-key"), command, timeout=60
            )
        self.assertEqual("graphical-ready\n", output)
        self.assertEqual(2, runner._ssh.call_count)

    def test_ordinary_reboot_reuses_the_graphical_boot_readiness_gate(self):
        source = (ROOT / "iso_test/feature_runner.py").read_text(encoding="utf-8")
        body = source.split("def _exercise_ordinary_reboot", 1)[1].split(
            "def _exercise_account_add_user", 1
        )[0]
        reboot_start = body.index('vm.start(attach_iso=False, phase="lifecycle-reboot")')
        post_reboot = body[reboot_start:]
        self.assertIn("self._graphical_boot_ready_command()", post_reboot)
        self.assertNotIn('key,\n            "true",', post_reboot)

    def test_snapshot_restore_confirmation_accepts_exact_locale_variants(self):
        source = (ROOT / "guest/atspi_driver.py").read_text(encoding="utf-8")
        body = source.split("def arm_snapshot_restore", 1)[1].split(
            "def verify_font_rendering", 1
        )[0]
        self.assertIn('f"Roll Back to {title}?"', body)
        self.assertIn('f"回滚到 {title}？"', body)
        self.assertIn("confirmation = find_candidates(", body)
        self.assertIn('"snapshot-rollback-confirmation"', body)

    def test_spotify_release_check_physically_drops_the_qemu_nic(self):
        runner = object.__new__(FeatureSuiteRunner)
        runner._run_shell_driver = Mock()
        serial = Mock()
        serial.run.return_value = SimpleNamespace(
            stdout=(
                "qmp-link=nic0-down\ninterface=enp1s0\n"
                "carrier=0\noperstate=down\n"
            )
        )
        qmp = Mock()
        vm = SimpleNamespace(qmp=qmp, serial=serial)
        base = SimpleNamespace(scenario=SimpleNamespace(id="bios-online-btrfs"))
        with tempfile.TemporaryDirectory() as directory:
            artifacts = Path(directory)
            runner._exercise_spotify_store(vm, base, artifacts)
            evidence = (artifacts / "spotify-network-isolation.txt").read_text()

        qmp.set_link.assert_called_once_with("nic0", up=False)
        self.assertIn("carrier=0", evidence)
        command = serial.run.call_args.args[0]
        self.assertIn("/sys/class/net", command)
        syntax = subprocess.run(
            ("bash", "-n"),
            input=command,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
        self.assertEqual(0, syntax.returncode, syntax.stderr)
        runner._run_shell_driver.assert_called_once()

    def test_btrfs_privileged_state_helper_is_valid_and_checks_recovery_invariants(self):
        commands = []

        def run(command, **_kwargs):
            commands.append(command)
            return SimpleNamespace(stdout="")

        runner = object.__new__(FeatureSuiteRunner)
        runner.username = "test-user"
        runner.btrfs_rollback_oracle = (
            Path(__file__).parent / "guest" / "btrfs_rollback_oracle.py"
        )
        runner._ssh_eventually = lambda *_args, **_kwargs: "ready"
        vm = SimpleNamespace(
            serial=SimpleNamespace(
                upload=lambda *_args, **_kwargs: None,
                run=run,
            )
        )
        with tempfile.TemporaryDirectory() as directory, patch(
            "iso_test.feature_runner.subprocess.run"
        ):
            runner._prepare_power_control(vm, Path(directory), "/run/feature")

        payload = commands[0]
        marker = (
            "cat > /usr/local/sbin/anduinos-acceptance-rollback-state "
            "<<'EOF'\n"
        )
        helper = payload.split(marker, 1)[1].split("\nEOF\n", 1)[0] + "\n"
        syntax = subprocess.run(
            ("bash", "-n"),
            input=helper,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            check=False,
        )
        self.assertEqual(0, syntax.returncode, syntax.stdout)
        for contract in (
            "btrfs subvolume get-default /",
            "@root\\.snapshots-manager-(old|new)-",
            "/boot/efi/EFI/anduinos/btrfs-snapshots-manager-grubenv",
            "anduinos-btrfs-snapshots-manager-confirm.service",
            "btrfs_rollback_oracle.py",
            '"$expected_target"',
        ):
            self.assertIn(contract, helper)
        self.assertNotIn("snapshots-manager-cli status", helper)

    def test_btrfs_protected_state_oracle_rejects_a_broken_fallback(self):
        target = "11111111-1111-4111-8111-111111111111"
        fallback = "22222222-2222-4222-8222-222222222222"
        target_snapshot = "33333333-3333-4333-8333-333333333333"
        fallback_snapshot = "44444444-4444-4444-8444-444444444444"
        digest = "a" * 64
        oracle = Path(__file__).parent / "guest" / "btrfs_rollback_oracle.py"

        def deployment(identifier, kind, snapshot):
            return {
                "schema_version": 1,
                "id": identifier,
                "parent_id": None,
                "kind": kind,
                "state": "ready",
                "created_at": "2026-08-18T00:00:00Z",
                "title": "Acceptance fixture",
                "reason": "Failure-injection fixture",
                "snapshot_uuid": snapshot,
                "snapshot_parent_uuid": None,
                "kernel_release": "7.0.0-test",
                "initramfs_sha256": digest,
                "boot_artifact_sha256": digest,
                "dpkg_status_sha256": digest,
                "mok_certificate_sha256": None,
                "pinned": False,
                "failure": None,
            }

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            store = root / "store"
            metadata = store / "metadata"
            history = store / "rollback-history"
            transactions = store / "transactions"
            target_root = store / "deployments" / target / "root"
            fallback_root = store / "deployments" / fallback / "root"
            current_root = root / "current-root"
            for path in (
                metadata,
                history,
                transactions,
                target_root,
                fallback_root,
                current_root,
            ):
                path.mkdir(parents=True, exist_ok=True)
            target_record = deployment(target, "manual", target_snapshot)
            fallback_record = deployment(fallback, "pre-rollback", fallback_snapshot)
            (metadata / f"{target}.json").write_text(
                json.dumps(target_record), encoding="utf-8"
            )
            fallback_path = metadata / f"{fallback}.json"
            fallback_path.write_text(json.dumps(fallback_record), encoding="utf-8")
            (history / "55555555-5555-4555-8555-555555555555.json").write_text(
                json.dumps(
                    {
                        "schema_version": 3,
                        "id": "55555555-5555-4555-8555-555555555555",
                        "target_deployment_id": target,
                        "fallback_deployment_id": fallback,
                        "phase": "confirmed",
                        "recovery_protocol_version": 2,
                        "root_filesystem_uuid": "66666666-6666-4666-8666-666666666666",
                        "kernel_release": "7.0.0-test",
                        "recovery_kernel_sha256": digest,
                        "recovery_initramfs_sha256": digest,
                        "recovery_confirm_sha256": digest,
                        "failure": None,
                    }
                ),
                encoding="utf-8",
            )
            fake_btrfs = root / "fake-btrfs"
            mapping = {
                str(target_root): target_snapshot,
                str(fallback_root): fallback_snapshot,
            }
            fake_btrfs.write_text(
                "#!/usr/bin/python3\n"
                "import sys\n"
                f"mapping = {mapping!r}\n"
                f"current = {str(current_root)!r}\n"
                f"parent = {target_snapshot!r}\n"
                "path = sys.argv[-1]\n"
                "if path in mapping:\n"
                "    print(f'UUID: {mapping[path]}')\n"
                "elif path == current:\n"
                "    print('UUID: 77777777-7777-4777-8777-777777777777')\n"
                "    print(f'Parent UUID: {parent}')\n"
                "else:\n"
                "    raise SystemExit(2)\n",
                encoding="utf-8",
            )
            fake_btrfs.chmod(0o755)
            command = (
                "python3",
                str(oracle),
                target,
                "--store-root",
                str(store),
                "--current-root",
                str(current_root),
                "--btrfs",
                str(fake_btrfs),
            )
            passing = subprocess.run(
                command,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                check=False,
            )
            self.assertEqual(0, passing.returncode, passing.stdout)
            self.assertIn("active-root=selected-target", passing.stdout)
            self.assertIn("snapshot-state=ok", passing.stdout)

            fallback_record["state"] = "broken"
            fallback_path.write_text(json.dumps(fallback_record), encoding="utf-8")
            failing = subprocess.run(
                command,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                check=False,
            )
            self.assertNotEqual(0, failing.returncode, failing.stdout)
            self.assertIn(f"deployment {fallback} is not ready", failing.stdout)

    def test_btrfs_oracle_rejects_uncleared_recovery_boot_state(self):
        passing = "\n".join(
            (
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
            )
        )
        _validate_rollback_health(passing)
        with self.assertRaisesRegex(TestFailure, "recovery-grubenv=empty"):
            _validate_rollback_health(
                passing.replace("recovery-grubenv=empty", "recovery-grubenv=armed")
            )

    def test_ssh_eventually_retries_a_forwarded_socket_handshake_timeout(self):
        runner = object.__new__(FeatureSuiteRunner)
        runner._ssh = Mock(
            side_effect=(
                subprocess.TimeoutExpired(("ssh", "true"), 15),
                TestFailure("connection reset during guest boot"),
                "ready\n",
            )
        )
        with patch("iso_test.feature_runner.time.sleep"):
            output = runner._ssh_eventually(
                SimpleNamespace(), Path("control-key"), "true", timeout=60
            )
        self.assertEqual("ready\n", output)
        self.assertEqual(3, runner._ssh.call_count)
        self.assertTrue(
            all(call.kwargs["timeout"] <= 15 for call in runner._ssh.call_args_list)
        )

    def test_stalled_btrfs_power_transition_retains_diagnostics(self):
        class Clock:
            now = 0.0

            @classmethod
            def monotonic(cls):
                return cls.now

            @classmethod
            def sleep(cls, seconds):
                cls.now += seconds

        runner = object.__new__(FeatureSuiteRunner)
        runner._ssh = lambda *_args, **_kwargs: "timer failed: inhibitor active"
        vm = SimpleNamespace(process=SimpleNamespace(poll=lambda: None))
        with tempfile.TemporaryDirectory() as directory:
            artifacts = Path(directory)
            with (
                patch("iso_test.feature_runner.time.monotonic", Clock.monotonic),
                patch("iso_test.feature_runner.time.sleep", Clock.sleep),
                self.assertRaisesRegex(TestFailure, "did not stop QEMU"),
            ):
                runner._wait_for_power_transition(
                    vm,
                    artifacts / "key",
                    artifacts,
                    "btrfs-rollback-reboot",
                    timeout=20,
                )
            evidence = (
                artifacts / "btrfs-rollback-reboot-diagnostics.txt"
            ).read_text(encoding="utf-8")
        self.assertIn("inhibitor active", evidence)

    def test_stalled_btrfs_power_transition_prefers_root_serial_diagnostics(self):
        class Clock:
            now = 0.0

            @classmethod
            def monotonic(cls):
                return cls.now

            @classmethod
            def sleep(cls, seconds):
                cls.now += seconds

        serial = SimpleNamespace(
            run=lambda *_args, **_kwargs: SimpleNamespace(
                stdout="42 shutdown.target start running"
            )
        )
        runner = object.__new__(FeatureSuiteRunner)
        runner._ssh = Mock(side_effect=AssertionError("SSH must not be preferred"))
        vm = SimpleNamespace(
            process=SimpleNamespace(poll=lambda: None),
            serial=serial,
        )
        with tempfile.TemporaryDirectory() as directory:
            artifacts = Path(directory)
            with (
                patch("iso_test.feature_runner.time.monotonic", Clock.monotonic),
                patch("iso_test.feature_runner.time.sleep", Clock.sleep),
                self.assertRaisesRegex(TestFailure, "did not stop QEMU"),
            ):
                runner._wait_for_power_transition(
                    vm,
                    artifacts / "key",
                    artifacts,
                    "btrfs-rollback-reboot",
                    timeout=20,
                )
            evidence = (
                artifacts / "btrfs-rollback-reboot-diagnostics.txt"
            ).read_text(encoding="utf-8")
        self.assertIn("root serial control channel", evidence)
        self.assertIn("shutdown.target", evidence)
        runner._ssh.assert_not_called()


class SshContractTests(unittest.TestCase):
    @patch("iso_test.runner.subprocess.run")
    def test_password_login_uses_forced_ephemeral_askpass(self, run):
        def complete(command, **options):
            environment = options["env"]
            askpass = Path(environment["SSH_ASKPASS"])
            self.assertTrue(askpass.is_file())
            self.assertTrue(askpass.stat().st_mode & 0o100)
            self.assertEqual("force", environment["SSH_ASKPASS_REQUIRE"])
            self.assertEqual(
                "AnduinOS-Test-123!",
                environment["ANDUINOS_ACCEPTANCE_SSH_PASSWORD"],
            )
            self.assertIn("NumberOfPasswordPrompts=1", " ".join(command))
            self.assertIn("-F /dev/null", " ".join(command))
            self.assertIn("ControlMaster=no", " ".join(command))
            self.assertIn("ControlPersist=no", " ".join(command))
            self.assertIn("ControlPath=none", " ".join(command))
            return __import__("subprocess").CompletedProcess(
                command,
                0,
                stdout="anduinostest\n",
            )

        run.side_effect = complete
        output = _ssh_login(
            2222,
            "anduinostest",
            "AnduinOS-Test-123!",
            should_succeed=True,
        )
        self.assertEqual("anduinostest\n", output)

    def test_gnome_off_requires_units_and_listener_to_stop(self):
        with tempfile.TemporaryDirectory() as directory:
            artifacts = Path(directory)
            console = _ResultConsole(
                CommandResult(
                    "ssh.socket enabled=disabled active=inactive\n"
                    "ssh.service enabled=disabled active=inactive\n"
                    "listeners=\n",
                    0,
                )
            )
            _assert_guest_ssh_stopped(console, artifacts)
            self.assertTrue(
                (artifacts / "installed-ssh-after-gnome-off.txt").is_file()
            )

    def test_gnome_off_rejects_a_remaining_listener(self):
        with tempfile.TemporaryDirectory() as directory:
            artifacts = Path(directory)
            console = _ResultConsole(
                CommandResult(
                    "ssh.socket enabled=disabled active=inactive\n"
                    "ssh.service enabled=disabled active=active\n"
                    "listeners=LISTEN 0 4096 0.0.0.0:22\n",
                    1,
                )
            )
            with self.assertRaises(TestFailure):
                _assert_guest_ssh_stopped(console, artifacts)


class InstallerTranscriptTests(unittest.TestCase):
    DRIVER_COMMAND = (
        "$ chroot /target ubuntu-drivers install --no-oem --package-list "
        "/run/anduinos-installer-drivers"
    )

    def test_online_driver_flow_requires_command_and_no_driver_result(self):
        _validate_installer_output(
            self.DRIVER_COMMAND
            + "\nAll the available drivers are already installed.\n",
            expects_driver_flow=True,
        )

    def test_online_driver_flow_rejects_a_green_step_without_command(self):
        with self.assertRaises(TestFailure):
            _validate_installer_output(
                "Install hardware drivers succeeded\n",
                expects_driver_flow=True,
            )

    def test_installer_transcript_rejects_fatal_markers(self):
        with self.assertRaises(TestFailure):
            _validate_installer_output(
                "Fatal step: install-bootloader\n",
                expects_driver_flow=False,
            )


class QmpSemanticKeyboardTests(unittest.TestCase):
    SEARCH_PROVIDER_PREFLIGHT = "\n".join(
        (
            "package=gnome-software version=50.0-1",
            "package=gnome-software-plugin-deb version=50.0-1",
            "package=packagekit version=1.3.4-3ubuntu1.1",
            "package=libpackagekit-glib2-18 version=1.3.4-3ubuntu1.1",
            "before_pid=2192 before_restarts=0 before_active=active",
            "(@as [],)",
            "after_pid=2192 after_restarts=0 after_active=active",
            "search-provider=ready pid=2192 restarts=0",
        )
    )

    def test_shell_search_provider_oracle_accepts_one_unchanged_process(self):
        _validate_search_provider_preflight(self.SEARCH_PROVIDER_PREFLIGHT, 0)

    def test_shell_search_provider_oracle_rejects_crash_then_restart(self):
        crashed = self.SEARCH_PROVIDER_PREFLIGHT.replace(
            "after_pid=2192 after_restarts=0",
            "after_pid=3791 after_restarts=1",
        ).replace(
            "search-provider=ready pid=2192 restarts=0",
            "search-provider=ready pid=3791 restarts=1",
        )
        with self.assertRaisesRegex(TestFailure, "crashed and restarted"):
            _validate_search_provider_preflight(crashed, 0)

    def test_shell_search_provider_oracle_rejects_missing_version_evidence(self):
        incomplete = self.SEARCH_PROVIDER_PREFLIGHT.replace(
            "package=packagekit version=1.3.4-3ubuntu1.1\n",
            "",
        )
        with self.assertRaisesRegex(TestFailure, "every installed package version"):
            _validate_search_provider_preflight(incomplete, 0)

    def test_shell_search_provider_preflight_rejects_an_unstable_service(self):
        runner = object.__new__(FeatureSuiteRunner)
        runner.username = "anduinostest"
        serial = Mock()
        serial.run.return_value = SimpleNamespace(
            returncode=1,
            stdout="search-provider=unstable\n",
        )
        vm = SimpleNamespace(serial=serial)
        with tempfile.TemporaryDirectory() as directory:
            artifacts = Path(directory)
            with self.assertRaisesRegex(TestFailure, "stable session state"):
                runner._stabilize_shell_search_provider(vm, artifacts)
            self.assertEqual(
                "search-provider=unstable\n\n",
                (artifacts / "shell-search-provider-preflight.txt").read_text(),
            )
        command = serial.run.call_args.args[0]
        self.assertIn("org.gnome.Shell.SearchProvider2.GetInitialResultSet", command)
        self.assertIn("MainPID", command)
        self.assertIn("NRestarts", command)
        self.assertIn("sleep 15", command)
        self.assertIn('test "$before_restarts" != 0', command)
        self.assertNotIn("for attempt in", command)

        source = Path("tests/iso_test/feature_runner.py").read_text(encoding="utf-8")
        body = source.split("def _run_shell_driver", 1)[1].split(
            "def _stabilize_shell_search_provider", 1
        )[0]
        self.assertLess(
            body.index("preflight_cursors = self._journal_cursors"),
            body.index("self._stabilize_shell_search_provider"),
        )
        self.assertLess(
            body.index("self._stabilize_shell_search_provider"),
            body.index('scope="shell-search-provider-preflight"'),
        )
        self.assertLess(
            body.index('scope="shell-search-provider-preflight"'),
            body.rindex("cursors = self._journal_cursors"),
        )

    def test_named_non_secret_text_request_is_strictly_parsed(self):
        self.assertEqual(
            "arcmenu-search-fixture",
            _parse_qmp_text_request(
                'serial: {"event": "qmp-text", '
                '"request": "arcmenu-search-fixture"}'
            ),
        )
        self.assertIsNone(
            _parse_qmp_text_request('{"event": "qmp-text", "request": ""}')
        )

    def test_qemu_block_flush_uses_the_open_named_node(self):
        client = QmpClient(Path("/unused-qmp-socket"))
        client.hmp = Mock(return_value="")

        client.flush_block_device("target")

        client.hmp.assert_called_once_with('qemu-io target "flush"')

    def test_qemu_block_flush_rejects_a_monitor_error(self):
        client = QmpClient(Path("/unused-qmp-socket"))
        client.hmp = Mock(return_value="Device 'target' not found")

        with self.assertRaisesRegex(ProtocolError, "failed to flush"):
            client.flush_block_device("target")

    def test_terminal_guest_requests_are_drained_after_the_command_exits(self):
        with tempfile.TemporaryDirectory() as directory:
            transcript = Path(directory) / "serial.log"
            transcript.touch()
            release = threading.Event()

            def finish_with_terminal_requests(*_args, **_kwargs):
                self.assertTrue(release.wait(timeout=1))
                with transcript.open("a", encoding="utf-8") as stream:
                    stream.write(
                        '{"event": "qmp-secret", "request": "tail-secret"}\n'
                        '{"event": "qmp-text", "request": "tail-text"}\n'
                        '{"event": "qmp-key", "request": "tail-submit", '
                        '"key": "ret"}\n'
                    )
                return CommandResult("", 0)

            serial = SimpleNamespace(
                transcript=transcript,
                run=finish_with_terminal_requests,
            )
            qmp = Mock()
            vm = SimpleNamespace(serial=serial, qmp=qmp)

            def release_during_poll(_seconds):
                release.set()
                threading.Event().wait(0.02)

            with patch("iso_test.runner.time.sleep", side_effect=release_during_poll):
                _run_with_qmp_key_requests(
                    vm,
                    "terminal-request-fixture",
                    timeout=1,
                    secret_texts={"tail-secret": "Tail-Secret-123!"},
                    text_inputs={"tail-text": "Spotify"},
                )

            self.assertEqual(
                [
                    call("Tail-Secret-123!", interval=0.06),
                    call("Spotify", interval=0.06),
                ],
                qmp.type_text.call_args_list,
            )
            qmp.send_key.assert_called_once_with("ret")

    def test_completed_host_click_is_written_to_the_request_trace(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            transcript = root / "serial.log"
            trace = root / "qmp-requests.jsonl"
            transcript.touch()
            clicked = threading.Event()

            def request_click(*_args, **_kwargs):
                with transcript.open("a", encoding="utf-8") as stream:
                    stream.write(
                        '{"event": "qmp-click", "request": "first-click", '
                        '"x_px": 64, "y_px": 312.5, "button": "left"}\n'
                    )
                self.assertTrue(clicked.wait(timeout=1))
                return CommandResult("", 0)

            serial = SimpleNamespace(transcript=transcript, run=request_click)
            qmp = Mock()
            qmp.click_pointer_pixels.side_effect = lambda *_args, **_kwargs: clicked.set()
            vm = SimpleNamespace(serial=serial, qmp=qmp)

            _run_with_qmp_key_requests(
                vm,
                "click-fixture",
                timeout=1,
                request_trace=trace,
            )

            qmp.click_pointer_pixels.assert_called_once_with(
                64.0,
                312.5,
                button="left",
            )
            records = [json.loads(line) for line in trace.read_text().splitlines()]
            self.assertEqual(1, len(records))
            self.assertEqual("first-click", records[0]["request"])
            self.assertEqual("click", records[0]["kind"])
            self.assertIs(True, records[0]["completed"])
            self.assertGreaterEqual(records[0]["duration_ms"], 0)

    def test_completed_host_key_is_written_to_the_request_trace(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            transcript = root / "serial.log"
            trace = root / "qmp-requests.jsonl"
            transcript.touch()
            delivered = threading.Event()

            def request_key(*_args, **_kwargs):
                with transcript.open("a", encoding="utf-8") as stream:
                    stream.write(
                        '{"event": "qmp-key", "request": "open-file-ret", '
                        '"key": "ret"}\n'
                    )
                self.assertTrue(delivered.wait(timeout=1))
                return CommandResult("", 0)

            serial = SimpleNamespace(transcript=transcript, run=request_key)
            qmp = Mock()
            qmp.send_key.side_effect = lambda *_args, **_kwargs: delivered.set()
            vm = SimpleNamespace(serial=serial, qmp=qmp)

            _run_with_qmp_key_requests(
                vm,
                "key-fixture",
                timeout=1,
                request_trace=trace,
            )

            qmp.send_key.assert_called_once_with("ret")
            records = [json.loads(line) for line in trace.read_text().splitlines()]
            self.assertEqual(1, len(records))
            self.assertEqual("open-file-ret", records[0]["request"])
            self.assertEqual("key", records[0]["kind"])
            self.assertEqual("ret", records[0]["key"])
            self.assertEqual("qmp-hmp", records[0]["input_transport"])
            self.assertIs(True, records[0]["completed"])

    def test_completed_host_double_click_is_written_to_the_request_trace(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            transcript = root / "serial.log"
            trace = root / "qmp-requests.jsonl"
            transcript.touch()
            clicked = threading.Event()

            def request_double_click(*_args, **_kwargs):
                with transcript.open("a", encoding="utf-8") as stream:
                    stream.write(
                        '{"event": "spice-double-click", '
                        '"request": "desktop-launch", '
                        '"x_px": 64, "y_px": 312.5, '
                        '"button": "left", "clicks": 2, '
                        '"positioning_clicks": 1, '
                        '"double_click_time_ms": 400, '
                        '"bounds": [4, 292, 120, 41]}\n'
                    )
                self.assertTrue(clicked.wait(timeout=1))
                return CommandResult("", 0)

            serial = SimpleNamespace(
                transcript=transcript,
                run=request_double_click,
            )
            qmp = Mock()
            vm = SimpleNamespace(
                serial=serial,
                qmp=qmp,
                spice_socket=Path("/run/qemu/spice.sock"),
            )

            with patch("iso_test.runner.SpiceInputClient") as client_type:
                pointer = client_type.return_value.__enter__.return_value
                pointer.double_click_pointer_pixels.side_effect = (
                    lambda *_args, **_kwargs: clicked.set()
                )
                _run_with_qmp_key_requests(
                    vm,
                    "double-click-fixture",
                    timeout=1,
                    request_trace=trace,
                )

            qmp.validate_pointer_bounds.assert_called_once_with(
                64.0, 312.5, (4, 292, 120, 41)
            )
            pointer.double_click_pointer_pixels.assert_called_once_with(
                64.0,
                312.5,
                double_click_time_ms=400,
            )
            records = [json.loads(line) for line in trace.read_text().splitlines()]
            self.assertEqual(1, len(records))
            self.assertEqual("desktop-launch", records[0]["request"])
            self.assertEqual("double-click", records[0]["kind"])
            self.assertEqual(2, records[0]["clicks"])
            self.assertEqual(1, records[0]["positioning_clicks"])
            self.assertEqual(400, records[0]["double_click_time_ms"])
            self.assertEqual("spice-vdagent", records[0]["input_transport"])
            self.assertEqual(2, records[0]["client_mouse_mode"])
            self.assertIs(True, records[0]["position_coupled_to_press"])
            self.assertIs(True, records[0]["completed"])

    def test_semantic_radio_navigation_supports_the_down_arrow(self):
        self.assertIn("down", _SUPPORTED_GUEST_QMP_KEYS)
        source = Path("tests/guest/atspi_driver.py").read_text(encoding="utf-8")
        radio_body = source.split("def set_radio(key: str)", 1)[1].split(
            "def dump_accessibility", 1
        )[0]
        self.assertIn('requested_key = "down"', radio_body)

    def test_wifi_password_focus_recovery_supports_reverse_tab(self):
        self.assertIn("shift-tab", _SUPPORTED_GUEST_QMP_KEYS)
        self.assertTrue(_guest_qmp_key_supported("shift-tab"))

    def test_text_editor_unicode_input_is_a_narrowly_supported_host_key(self):
        self.assertIn("ctrl-shift-u", _SUPPORTED_GUEST_QMP_KEYS)
        self.assertTrue(_guest_qmp_key_supported("ctrl-shift-u"))
        self.assertFalse(_guest_qmp_key_supported("s"))
        self.assertFalse(_guest_qmp_key_supported("ctrl-s"))
        self.assertFalse(_guest_qmp_key_supported("ctrl-shift-s"))

    def test_arcmenu_context_targets_result_before_keyboard_menu_navigation(self):
        source = Path("tests/guest/atspi_driver.py").read_text(encoding="utf-8")
        context_body = source.split("def request_search_result_context", 1)[1].split(
            "def activate_shell_context_action", 1
        )[0]
        self.assertIn('role(search_entry) != "text"', context_body)
        self.assertIn("Atspi.StateType.FOCUSED", context_body)
        self.assertIn('method="search-entry-popup-menu"', context_body)
        self.assertIn('key="shift-f10"', context_body)
        self.assertNotIn("request_node_click(", context_body)
        search_body = source.split("def _open_arcmenu_search", 1)[1].split(
            "def request_search_result_context", 1
        )[0]
        self.assertIn('role(item) == "text"', search_body)
        self.assertIn("stable_observations < 4", search_body)
        self.assertIn('"search-entry-focus"', search_body)
        activation_body = source.split("def activate_shell_context_action", 1)[
            1
        ].split("def exercise_start_button", 1)[0]
        self.assertIn('key="down"', activation_body)
        self.assertIn('key="ret"', activation_body)

    def test_localized_radio_mnemonic_is_narrowly_allowed(self):
        self.assertTrue(_guest_qmp_key_supported("alt-o"))
        self.assertTrue(_guest_qmp_key_supported("alt-f4"))
        self.assertFalse(_guest_qmp_key_supported("alt-f12"))
        self.assertFalse(_guest_qmp_key_supported("ctrl-alt-delete"))
        source = Path("tests/guest/atspi_driver.py").read_text(encoding="utf-8")
        self.assertIn('method="localized-mnemonic"', source)

    def test_absolute_pointer_uses_normalized_tablet_coordinates(self):
        client = QmpClient(Path("unused"))
        client.execute = Mock(return_value={})
        client.move_pointer_absolute(0.25, 0.75)
        client.execute.assert_called_once_with(
            "input-send-event",
            {
                "device": "video0",
                "events": [
                    {"type": "abs", "data": {"axis": "x", "value": 8192}},
                    {"type": "abs", "data": {"axis": "y", "value": 24575}},
                ]
            },
        )
        with self.assertRaisesRegex(Exception, "0..1"):
            client.move_pointer_absolute(-0.1, 0.5)

    @patch("iso_test.qmp.time.sleep")
    def test_pointer_click_moves_then_presses_and_releases_primary_button(self, sleep):
        client = QmpClient(Path("unused"))
        client.execute = Mock(return_value={})
        client.click_pointer_absolute(0.4, 0.6)
        self.assertEqual(3, client.execute.call_count)
        move, press, release = client.execute.call_args_list
        self.assertEqual("input-send-event", move.args[0])
        self.assertEqual(
            {
                "device": "video0",
                "events": [
                    {"type": "btn", "data": {"down": True, "button": "left"}}
                ],
            },
            press.args[1],
        )
        self.assertEqual(
            {
                "device": "video0",
                "events": [
                    {"type": "btn", "data": {"down": False, "button": "left"}}
                ],
            },
            release.args[1],
        )
        self.assertEqual(
            [((0.25,), {}), ((0.06,), {})],
            [(item.args, item.kwargs) for item in sleep.call_args_list],
        )

    def test_spice_pointer_double_click_emits_two_complete_gestures(self):
        client = SpiceInputClient.__new__(SpiceInputClient)
        client._inputs = Mock()
        client._run_for = Mock()

        client.double_click_pointer_pixels(
            64.0,
            312.5,
            double_click_time_ms=400,
        )

        self.assertEqual(
            [call(64, 312, 0, 0), call(64, 312, 0, 0), call(64, 312, 0, 0)],
            client._inputs.position.call_args_list,
        )
        self.assertEqual(3, client._inputs.button_press.call_count)
        self.assertEqual(3, client._inputs.button_release.call_count)
        self.assertEqual(
            [call(1, 0), call(1, 0), call(1, 0)],
            client._inputs.button_press.call_args_list,
        )
        self.assertEqual(
            [0.06, 0.06, 0.60, 0.06, 0.12, 0.06, 0.25],
            [item.args[0] for item in client._run_for.call_args_list],
        )

    def test_spice_pointer_connection_requires_the_guest_agent(self):
        client = SpiceInputClient.__new__(SpiceInputClient)
        client._main = Mock()
        client._main.get_property.side_effect = lambda name: {
            "mouse-mode": 2,
            "agent-connected": False,
        }[name]
        with self.assertRaisesRegex(ProtocolError, "guest agent"):
            client._require_agent()

    def test_spice_boot_keyboard_uses_strict_set1_scancodes_without_agent(self):
        client = SpiceInputClient.__new__(SpiceInputClient)
        client._inputs = Mock()
        client._run_for = Mock()

        client.type_boot_text("C_:/@", interval=0.01)
        client.send_boot_key("c")
        client.send_boot_key("ret")

        self.assertEqual(
            [call(0x2A), call(0x2A), call(0x2A), call(0x2A)],
            client._inputs.key_press.call_args_list,
        )
        self.assertEqual(
            [
                call(0x2E),
                call(0x0C),
                call(0x27),
                call(0x35),
                call(0x03),
                call(0x2E),
                call(0x1C),
            ],
            client._inputs.key_press_and_release.call_args_list,
        )
        self.assertEqual(
            [call(0x2A), call(0x2A), call(0x2A), call(0x2A)],
            client._inputs.key_release.call_args_list,
        )
        self.assertEqual(7, client._run_for.call_count)
        client._inputs.reset_mock()
        with self.assertRaisesRegex(ProtocolError, "Unsupported boot text"):
            client.type_boot_text("safe?")
        client._inputs.key_press_and_release.assert_not_called()
        with self.assertRaisesRegex(ProtocolError, "Unsupported boot key"):
            client.send_boot_key("f10")

    def test_spice_pointer_rejects_input_before_connection(self):
        client = SpiceInputClient.__new__(SpiceInputClient)
        client._inputs = None
        with self.assertRaisesRegex(ProtocolError, "not connected"):
            client.double_click_pointer_pixels(
                64.0,
                312.5,
                double_click_time_ms=400,
            )

    def test_spice_pointer_rejects_server_mouse_mode(self):
        client = SpiceInputClient.__new__(SpiceInputClient)
        client._main = Mock()
        client._main.get_property.return_value = 1
        with self.assertRaisesRegex(ProtocolError, "client mouse mode"):
            client._require_client_mouse_mode()

    @patch("iso_test.qmp.time.sleep")
    def test_pointer_context_click_uses_the_secondary_button(self, _sleep):
        client = QmpClient(Path("unused"))
        client.execute = Mock(return_value={})
        client.click_pointer_absolute(0.4, 0.6, button="right")
        press, release = client.execute.call_args_list[1:]
        self.assertEqual("right", press.args[1]["events"][0]["data"]["button"])
        self.assertEqual("right", release.args[1]["events"][0]["data"]["button"])
        with self.assertRaisesRegex(ProtocolError, "Unsupported pointer button"):
            client.click_pointer_absolute(0.4, 0.6, button="middle")

    def test_atspi_derived_pointer_request_is_strictly_parsed(self):
        line = (
            'serial-prefix {"event": "qmp-click", "request": "accounts-add-user", '
            '"target": "add_user", "x_px": 1183.5, "y_px": 776.0, '
            '"screen": [1282, 848]}'
        )
        self.assertEqual(
            ("accounts-add-user", 1183.5, 776.0, "left"),
            _parse_qmp_click_request(line),
        )
        self.assertEqual(
            ("taskbar-context", 640.0, 780.0, "right"),
            _parse_qmp_click_request(
                '{"event": "qmp-click", "request": "taskbar-context", '
                '"x_px": 640, "y_px": 780, "button": "right"}'
            ),
        )
        self.assertIsNone(
            _parse_qmp_click_request(
                '{"event": "qmp-click", "request": "desktop-launch", '
                '"x_px": 64, "y_px": 344, "click_count": 2}'
            ),
        )
        self.assertIsNone(
            _parse_qmp_click_request(
                '{"event": "qmp-click", "request": "off-screen", '
                '"x_px": -1, "y_px": 500}'
            )
        )
        self.assertIsNone(
            _parse_qmp_click_request(
                '{"event": "qmp-click", "request": "missing-y", "x_px": 500}'
            )
        )
        self.assertIsNone(
            _parse_qmp_click_request(
                '{"event": "qmp-click", "request": "bad-button", '
                '"x_px": 500, "y_px": 500, "button": "middle"}'
            )
        )
        self.assertIsNone(
            _parse_qmp_click_request(
                '{"event": "qmp-click", "request": "bad-count", '
                '"x_px": 500, "y_px": 500, "click_count": 3}'
            )
        )

    def test_atspi_double_click_request_requires_exactly_two_primary_clicks(self):
        valid = (
            'serial-prefix {"event": "spice-double-click", '
            '"request": "desktop-launch", "x_px": 64, "y_px": 312.5, '
            '"button": "left", "clicks": 2, '
            '"positioning_clicks": 1, "double_click_time_ms": 400, '
            '"bounds": [4, 292, 120, 41]}'
        )
        self.assertEqual(
            ("desktop-launch", 64.0, 312.5, (4, 292, 120, 41), 400),
            _parse_spice_double_click_request(valid),
        )
        self.assertIsNone(
            _parse_spice_double_click_request(
                valid.replace('"clicks": 2', '"clicks": 1')
            )
        )
        self.assertIsNone(
            _parse_spice_double_click_request(
                valid.replace('"button": "left"', '"button": "right"')
            )
        )
        self.assertIsNone(
            _parse_spice_double_click_request(
                valid.replace('"positioning_clicks": 1', '"positioning_clicks": 0')
            )
        )
        self.assertIsNone(
            _parse_spice_double_click_request(
                valid.replace('"x_px": 64', '"x_px": 63')
            )
        )

    def test_atspi_pixels_use_qemu_framebuffer_not_shell_stage_size(self):
        client = QmpClient(Path("unused"))
        client.framebuffer_size = Mock(return_value=(1280, 800))
        client.click_pointer_absolute = Mock()
        client.click_pointer_pixels(1183.5, 776.0)
        client.click_pointer_absolute.assert_called_once_with(
            1183.5 / 1280,
            776 / 800,
            button="left",
        )

        client.click_pointer_absolute.reset_mock()
        client.click_pointer_pixels(100, 200, button="right")
        client.click_pointer_absolute.assert_called_once_with(
            100 / 1280,
            200 / 800,
            button="right",
        )

        # Failure injection: the same Y coordinate would look valid against
        # GNOME Shell's reported 848-pixel stage, but must fail against the
        # real 700-pixel QEMU framebuffer.
        client.framebuffer_size = Mock(return_value=(1280, 700))
        with self.assertRaisesRegex(Exception, "outside the QEMU framebuffer"):
            client.click_pointer_pixels(1183.5, 776.0)

    def test_qemu_ppm_dimensions_reject_a_malformed_screendump(self):
        with tempfile.TemporaryDirectory() as directory:
            valid = Path(directory) / "valid.ppm"
            valid.write_bytes(b"P6\n# qemu\n1280 800\n255\n")
            self.assertEqual((1280, 800), _ppm_dimensions(valid))
            valid.write_bytes(b"not-a-ppm\n")
            with self.assertRaisesRegex(Exception, "invalid PPM header"):
                _ppm_dimensions(valid)

    def test_guest_keyboard_request_is_parsed_from_serial_prefix(self):
        self.assertEqual(
            ("drivers-2-spc", "spc"),
            _parse_qmp_key_request(
                'debug-prefix {"event": "qmp-key", '
                '"request": "drivers-2-spc", "key": "spc"}'
            ),
        )

    def test_unrelated_or_incomplete_serial_lines_are_ignored(self):
        self.assertIsNone(_parse_qmp_key_request('{"event": "page"}'))
        self.assertIsNone(
            _parse_qmp_key_request('{"event": "qmp-key", "key": "tab"}')
        )

    def test_semantic_file_activation_enter_request_is_parsed(self):
        self.assertEqual(
            ("open-fixture-ret", "ret"),
            _parse_qmp_key_request(
                '{"event": "qmp-key", "request": "open-fixture-ret", "key": "ret"}'
            ),
        )

    def test_nautilus_activation_never_trusts_an_atspi_action_return(self):
        source = Path("tests/guest/atspi_driver.py").read_text(encoding="utf-8")
        body = source.split("def _open_download_in_nautilus", 1)[1].split(
            "def verify_appimage_file", 1
        )[0]
        self.assertNotIn("Atspi.generate_mouse_event", body)
        self.assertNotIn("perform_action", body)
        self.assertIn("request_node_double_click", body)
        self.assertIn('method="selected-item-qmp-enter"', body)
        self.assertIn("bounds.x <= 0", body)
        self.assertIn("bounds.y <= 0", body)

    def test_secret_request_contains_no_secret_material(self):
        line = '{"event": "qmp-secret", "request": "polkit-password"}'
        self.assertEqual("polkit-password", _parse_qmp_secret_request(line))
        self.assertNotIn("AnduinOS-Test", line)

    def test_named_secret_requests_are_resolved_without_a_shared_password(self):
        values = {
            "current": "old-password",
            "replacement": "new-password",
        }
        self.assertEqual(
            "old-password",
            _resolve_qmp_secret("current", secret_text=None, secret_texts=values),
        )
        self.assertEqual(
            "new-password",
            _resolve_qmp_secret(
                "replacement", secret_text=None, secret_texts=values
            ),
        )
        with self.assertRaisesRegex(TestFailure, "missing"):
            _resolve_qmp_secret("missing", secret_text=None, secret_texts=values)


class SerialTransportTests(unittest.TestCase):
    def test_wait_for_shell_never_sends_a_probe_to_firmware_or_grub(self):
        with tempfile.TemporaryDirectory() as directory:
            transcript = Path(directory) / "serial.log"
            reader, writer = socket.socketpair()
            console = SerialConsole(Path("unused"), transcript, timeout=0.2)
            console._socket = reader
            console._log = transcript.open("ab", buffering=0)
            try:
                with self.assertRaisesRegex(
                    ProtocolError,
                    "no command was sent to firmware or GRUB",
                ):
                    console.wait_for_shell(timeout=0.2)
                readable, _, _ = select.select([writer], [], [], 0)
                self.assertEqual([], readable)
            finally:
                console.close()
                writer.close()

    def test_wait_for_shell_probes_only_after_kernel_console_marker(self):
        with tempfile.TemporaryDirectory() as directory:
            transcript = Path(directory) / "serial.log"
            reader, writer = socket.socketpair()
            console = SerialConsole(Path("unused"), transcript, timeout=2)
            console._socket = reader
            console._log = transcript.open("ab", buffering=0)
            server_failures = []
            received_commands = []

            def emulate_debug_shell():
                try:
                    readable, _, _ = select.select([writer], [], [], 0.1)
                    if readable:
                        raise AssertionError("shell probe arrived while GRUB owned serial")
                    writer.sendall(
                        b"[    0.015] Kernel command line: console=ttyS0,115200\n"
                    )
                    readable, _, _ = select.select([writer], [], [], 0.1)
                    if readable:
                        raise AssertionError(
                            "shell probe arrived before Bash owned serial"
                        )
                    writer.sendall(
                        b"servicename=debug-shell.service;type=service\n"
                    )
                    for _ in range(2):
                        command = bytearray()
                        while not command.endswith(b"\n"):
                            command.extend(writer.recv(65536))
                        received_commands.append(bytes(command))
                        token = re.search(
                            rb"__ANDUINOS_BEGIN_([0-9a-f]+)__",
                            bytes(command),
                        )
                        if token is None:
                            raise AssertionError("serial command marker is missing")
                        value = token.group(1)
                        writer.sendall(
                            b"__ANDUINOS_BEGIN_"
                            + value
                            + b"__\n\n__ANDUINOS_END_"
                            + value
                            + b"__:0\n"
                        )
                except BaseException as error:  # reported by the test thread
                    server_failures.append(error)

            thread = threading.Thread(target=emulate_debug_shell)
            thread.start()
            try:
                try:
                    # ARM boot consumes this passive boundary after leaving its
                    # PCI GRUB console. The shell handshake must remember it.
                    console.wait_for_kernel_console(timeout=2)
                    console.wait_for_shell(timeout=2)
                except ProtocolError:
                    thread.join(timeout=2)
                    if server_failures:
                        raise server_failures[0]
                    raise
                thread.join(timeout=2)
            finally:
                console.close()
                writer.close()
            self.assertFalse(thread.is_alive())
            self.assertEqual([], server_failures)
            self.assertEqual(2, len(received_commands))
            self.assertTrue(
                all(command.endswith(b"\r\n") for command in received_commands)
            )

    def test_bootloader_line_is_bounded_ascii_and_rejects_injection(self):
        with tempfile.TemporaryDirectory() as directory:
            transcript = Path(directory) / "serial.log"
            reader, writer = socket.socketpair()
            console = SerialConsole(Path("unused"), transcript, timeout=1)
            console._socket = reader
            console._log = transcript.open("ab", buffering=0)
            try:
                console.send_bootloader_line(
                    "linux /casper/vmlinuz locale=zh_CN.UTF-8 "
                    "console=ttyAMA0,115200 "
                    "systemd.mask=serial-getty@ttyAMA0.service"
                )
                self.assertEqual(
                    b"linux /casper/vmlinuz locale=zh_CN.UTF-8 "
                    b"console=ttyAMA0,115200 "
                    b"systemd.mask=serial-getty@ttyAMA0.service\n",
                    writer.recv(4096),
                )
                for unsafe in ("boot\nreboot", "boot; reboot", "x" * 4097, ""):
                    with self.subTest(value=unsafe[:20]):
                        with self.assertRaisesRegex(ProtocolError, "Unsafe"):
                            console.send_bootloader_line(unsafe)
                readable, _, _ = select.select([writer], [], [], 0)
                self.assertEqual([], readable)
            finally:
                console.close()
                writer.close()

    def test_quiet_boot_uses_debug_shell_unit_as_passive_handoff(self):
        with tempfile.TemporaryDirectory() as directory:
            transcript = Path(directory) / "serial.log"
            reader, writer = socket.socketpair()
            console = SerialConsole(Path("unused"), transcript, timeout=1)
            console._socket = reader
            console._log = transcript.open("ab", buffering=0)
            writer.sendall(
                b"GNU GRUB 2.14\nservicename=debug-shell.service;type=service\n"
            )
            try:
                console._wait_for_kernel_console(time.monotonic() + 1)
                self.assertTrue(console._debug_shell_ready)
                readable, _, _ = select.select([writer], [], [], 0)
                self.assertEqual([], readable)
            finally:
                console.close()
                writer.close()

    def test_kernel_fatal_oracle_catches_early_zstd_decompression_failure(self):
        self.assertEqual(
            "ZSTD-compressed data is corrupt",
            _fatal_kernel_marker(
                b"EFI stub: WARNING: Decompression failed: "
                b"ZSTD-compressed data is corrupt\n"
            ),
        )

    def test_kernel_oops_oracle_drains_the_following_call_trace(self):
        with tempfile.TemporaryDirectory() as directory:
            transcript = Path(directory) / "serial.log"
            reader, writer = socket.socketpair()
            console = SerialConsole(Path("unused"), transcript)
            console._socket = reader
            console._log = transcript.open("ab", buffering=0)
            released = threading.Event()

            def delayed_trace() -> None:
                # Reproduce a loaded VM where the header arrives well before
                # the diagnostic body.  The old 350 ms idle window discarded
                # precisely the RIP needed to triage a real guest Oops.
                time.sleep(0.5)
                writer.sendall(
                    b"protection fault\nRIP: 0010:test_fault+0x1/0x2\n"
                    b"Call Trace:\n test_caller+0x3/0x4\n---[ end trace ]---\n"
                )
                released.set()

            sender = threading.Thread(target=delayed_trace, daemon=True)
            sender.start()
            try:
                with self.assertRaisesRegex(TestFailure, "Call Trace"):
                    console._record_chunk(b"[  12.0] Oops: general ")
            finally:
                sender.join(timeout=2)
                console.close()
                writer.close()

            self.assertTrue(released.is_set())
            evidence = transcript.read_bytes()
            self.assertIn(b"Oops: general protection fault", evidence)
            self.assertIn(b"test_caller", evidence)

    def test_kernel_fatal_oracle_catches_split_soft_lockup_marker(self):
        first = b"watchdog: BUG: soft "
        second = b"lockup - CPU#3 stuck for 26s!"
        self.assertIsNone(_fatal_kernel_marker(first))
        self.assertEqual(
            "watchdog: BUG: soft lockup",
            _fatal_kernel_marker(first + second),
        )

    def test_kernel_fatal_oracle_catches_oops_before_watchdog_fallout(self):
        first = b"[   87.132877] Oo"
        second = b"ps: general protection fault [#1] SMP NOPTI\n"
        self.assertIsNone(_fatal_kernel_marker(first))
        self.assertEqual("Oops: ", _fatal_kernel_marker(first + second))

    def test_kernel_fatal_oracle_rejects_a_dead_acceptance_input_controller(self):
        self.assertEqual(
            "xHCI host controller not responding, assume dead",
            _fatal_kernel_marker(
                b"xhci_hcd 0000:00:04.0: xHCI host controller not responding, "
                b"assume dead\n"
            ),
        )

    def test_large_fixture_upload_handles_nonblocking_backpressure(self):
        left, right = socket.socketpair()
        left.setblocking(False)
        left.setsockopt(socket.SOL_SOCKET, socket.SO_SNDBUF, 4096)
        payload = b"A" * (2 * 1024 * 1024)
        received = bytearray()

        def consume():
            while len(received) < len(payload):
                chunk = right.recv(65536)
                if not chunk:
                    break
                received.extend(chunk)

        thread = threading.Thread(target=consume)
        thread.start()
        console = SerialConsole(Path("unused"), Path("unused"), timeout=10)
        console._socket = left
        try:
            console._send(payload)
            left.shutdown(socket.SHUT_WR)
            thread.join(timeout=10)
        finally:
            left.close()
            right.close()
        self.assertFalse(thread.is_alive())
        self.assertEqual(payload, bytes(received))

    def test_large_upload_is_split_into_confirmed_tty_sized_commands(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "fixture.AppImage"
            source.write_bytes(b"X" * (1024 * 1024))
            console = _UploadCaptureConsole()
            console.upload(source, "/tmp/fixture.AppImage", 0o755)
        self.assertGreater(len(console.scripts), 20)
        self.assertLess(max(map(len, console.scripts)), 70000)
        self.assertTrue(console.scripts[0].startswith(": > "))
        self.assertIn("chmod 755", console.scripts[-1])
        self.assertIn("mv ", console.scripts[-1])

    def test_download_retries_a_frame_contaminated_by_kernel_console_output(self):
        payload = bytes(range(256)) * 300
        with tempfile.TemporaryDirectory() as directory:
            destination = Path(directory) / "cursor.png"
            console = _DownloadCaptureConsole(payload, corrupt_first_chunk=True)
            self.assertTrue(console.download("/run/cursor.png", destination))
            self.assertEqual(payload, destination.read_bytes())
        self.assertGreater(console.chunk_calls, 4)
        self.assertEqual(1, console.corruptions_injected)

    def test_download_fails_closed_when_every_frame_is_contaminated(self):
        payload = b"cursor-plane" * 2048
        with tempfile.TemporaryDirectory() as directory:
            destination = Path(directory) / "cursor.png"
            console = _DownloadCaptureConsole(payload, corrupt_every_chunk=True)
            with self.assertRaisesRegex(
                ProtocolError, "uncorrupted serial download frame"
            ):
                console.download("/run/cursor.png", destination)
            self.assertFalse(destination.exists())


class VisualOracleTests(unittest.TestCase):
    def test_grub_top_menu_waits_for_three_stable_frames(self):
        editor = object.__new__(_GraphicalGrubMenuEditor)
        editor.qmp = Mock()
        editor.current_frame = None
        editor.capture = Mock(
            side_effect=[
                Path("painting.ppm"),
                Path("stable-1.ppm"),
                Path("stable-2.ppm"),
                Path("stable-3.ppm"),
            ]
        )
        ticks = iter(range(100))

        def layout(frame):
            return SimpleNamespace(
                visible_unselected_entries=3,
                highlight_center=(70 if frame.name == "painting.ppm" else 80),
            )

        def difference(first, second):
            return 200 if first.name == "painting.ppm" else 0

        with (
            patch("iso_test.grub.time.monotonic", side_effect=lambda: next(ticks)),
            patch("iso_test.grub.time.sleep"),
            patch("iso_test.grub.grub_menu_layout", side_effect=layout),
            patch("iso_test.grub.grub_frame_difference", side_effect=difference),
        ):
            editor.wait_for_top_menu(30)

        self.assertEqual(Path("stable-3.ppm"), editor.current_frame)

    def test_signed_grub_locale_menu_may_finish_after_ten_seconds(self):
        editor = object.__new__(_GraphicalGrubMenuEditor)
        editor.qmp = Mock()
        editor.current_frame = Path("top-menu.ppm")
        editor.capture = Mock(
            side_effect=[Path("top-menu.ppm")] * 12
            + [Path("locale-menu.ppm")]
        )
        ticks = iter(range(100))

        def layout(frame):
            return SimpleNamespace(
                visible_unselected_entries=(
                    8 if frame.name == "locale-menu.ppm" else 3
                )
            )

        with (
            patch("iso_test.grub.time.monotonic", side_effect=lambda: next(ticks)),
            patch("iso_test.grub.time.sleep"),
            patch("iso_test.grub.grub_menu_layout", side_effect=layout),
        ):
            editor.enter_language_submenu()

        editor.qmp.send_key.assert_called_once_with("ret")
        self.assertEqual(Path("locale-menu.ppm"), editor.current_frame)

    def test_grub_timeout_cancel_moves_and_restores_top_selection(self):
        editor = object.__new__(_GraphicalGrubMenuEditor)
        editor.qmp = Mock()
        editor.current_frame = Path("top.ppm")
        editor.capture = Mock(
            side_effect=[Path("top.ppm")] * 12
            + [Path("moved.ppm")]
            + [Path("moved.ppm")] * 12
            + [Path("restored.ppm")]
        )
        ticks = iter(range(100))

        def layout(frame):
            centers = {"top.ppm": 80, "moved.ppm": 100, "restored.ppm": 80}
            return SimpleNamespace(
                visible_unselected_entries=3,
                highlight_center=centers[frame.name],
            )

        with (
            patch("iso_test.grub.time.monotonic", side_effect=lambda: next(ticks)),
            patch("iso_test.grub.time.sleep"),
            patch("iso_test.grub.grub_menu_layout", side_effect=layout),
        ):
            editor.cancel_timeout()

        self.assertEqual(
            [call("down"), call("up")], editor.qmp.send_key.call_args_list
        )
        self.assertEqual(Path("restored.ppm"), editor.current_frame)

    def test_grub_editor_waits_for_stable_wrapped_command_content(self):
        editor = object.__new__(_GraphicalGrubMenuEditor)
        editor.qmp = Mock()
        editor.current_frame = Path("locale-menu.ppm")
        editor.capture = Mock(
            side_effect=[
                Path("partial-1.ppm"),
                Path("partial-2.ppm"),
                Path("full-1.ppm"),
                Path("full-2.ppm"),
                Path("full-3.ppm"),
            ]
        )
        ticks = iter(range(100))

        def layout(frame):
            return SimpleNamespace(
                visible_command_lines=(3 if frame.name.startswith("partial") else 5)
            )

        def difference(first, second):
            return 200 if first.name == "locale-menu.ppm" else 0

        with (
            patch("iso_test.grub.time.monotonic", side_effect=lambda: next(ticks)),
            patch("iso_test.grub.time.sleep"),
            patch("iso_test.grub.grub_editor_layout", side_effect=layout),
            patch("iso_test.grub.grub_frame_difference", side_effect=difference),
        ):
            editor.open_editor()

        editor.qmp.send_key.assert_called_once_with("e")
        self.assertEqual(Path("full-3.ppm"), editor.current_frame)

    def test_grub_editor_down_waits_for_delayed_cursor_motion(self):
        editor = object.__new__(_GraphicalGrubMenuEditor)
        editor.qmp = Mock()
        editor.current_frame = Path("editor.ppm")
        editor._editor_cursor_y = 80
        editor.capture = Mock(
            side_effect=[Path(f"waiting-{index}.ppm") for index in range(12)]
            + [Path("cursor-112.ppm")]
        )
        ticks = iter(range(100))

        with (
            patch("iso_test.grub.time.monotonic", side_effect=lambda: next(ticks)),
            patch("iso_test.grub.time.sleep"),
            patch("iso_test.grub.grub_editor_layout", return_value=SimpleNamespace()),
            patch(
                "iso_test.grub.grub_editor_left_cursor_y",
                side_effect=[None] * 12 + [112],
            ),
        ):
            editor.move_editor_cursor_down()

        editor.qmp.send_key.assert_called_once_with("down")
        self.assertEqual(112, editor._editor_cursor_y)
        self.assertEqual(Path("cursor-112.ppm"), editor.current_frame)

    def test_grub_editor_down_requires_a_pre_key_cursor_baseline(self):
        editor = object.__new__(_GraphicalGrubMenuEditor)
        editor.qmp = Mock()
        editor.current_frame = Path("editor.ppm")
        editor._editor_cursor_y = None
        editor.capture = Mock(
            side_effect=[Path("blink-off.ppm"), Path("baseline.ppm"), Path("moved.ppm")]
        )
        ticks = iter(range(100))

        with (
            patch("iso_test.grub.time.monotonic", side_effect=lambda: next(ticks)),
            patch("iso_test.grub.time.sleep"),
            patch("iso_test.grub.grub_editor_layout", return_value=SimpleNamespace()),
            patch(
                "iso_test.grub.grub_editor_left_cursor_y",
                side_effect=[None, 80, 112],
            ),
        ):
            editor.move_editor_cursor_down()

        editor.qmp.send_key.assert_called_once_with("down")
        self.assertEqual(112, editor._editor_cursor_y)

    def test_grub_editor_end_waits_for_left_cursor_to_disappear(self):
        editor = object.__new__(_GraphicalGrubMenuEditor)
        editor.qmp = Mock()
        editor.current_frame = Path("cursor-left.ppm")
        editor._editor_cursor_y = 151
        editor.capture = Mock(
            side_effect=[Path(f"waiting-{index}.ppm") for index in range(12)]
            + [Path("cursor-end.ppm")]
        )
        ticks = iter(range(100))

        with (
            patch("iso_test.grub.time.monotonic", side_effect=lambda: next(ticks)),
            patch("iso_test.grub.time.sleep"),
            patch("iso_test.grub.grub_editor_layout", return_value=SimpleNamespace()),
            patch(
                "iso_test.grub.grub_editor_left_cursor_y",
                side_effect=[151] * 12 + [None],
            ),
            patch(
                "iso_test.grub.grub_frame_difference",
                return_value=24,
            ),
        ):
            editor.move_editor_cursor_to_end()

        editor.qmp.send_key.assert_called_once_with("end")
        self.assertIsNone(editor._editor_cursor_y)
        self.assertEqual(Path("cursor-end.ppm"), editor.current_frame)

    def test_grub_verified_typing_waits_for_every_character_repaint(self):
        editor = object.__new__(_GraphicalGrubMenuEditor)
        editor.qmp = Mock()
        editor.current_frame = Path("start.ppm")
        editor._editor_cursor_y = None
        editor.capture = Mock(
            side_effect=[Path("space.ppm"), Path("letter.ppm")]
        )
        ticks = iter(range(100))

        with (
            patch("iso_test.grub.time.monotonic", side_effect=lambda: next(ticks)),
            patch("iso_test.grub.time.sleep"),
            patch("iso_test.grub.grub_editor_layout", return_value=SimpleNamespace()),
            patch("iso_test.grub.grub_frame_difference", return_value=24),
        ):
            editor.type_text_verified(" c")

        self.assertEqual(
            [call(" ", interval=0), call("c", interval=0)],
            editor.qmp.type_text.call_args_list,
        )
        self.assertEqual(Path("letter.ppm"), editor.current_frame)

    def test_grub_editor_oracle_requires_border_and_command_lines(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            frame = root / "editor.ppm"
            missing = root / "missing.ppm"
            crowded = root / "crowded-menu.ppm"
            cursor = root / "cursor.ppm"
            wrapped = root / "wrapped-editor.ppm"
            image = Image.new("RGB", (1280, 800), "black")
            draw = ImageDraw.Draw(image)
            draw.rectangle((12, 67, 1267, 675), outline=(190, 190, 190), width=2)
            draw.text((14, 82), "setparams 'Simplified Chinese'", fill="white")
            draw.text((80, 120), "set gfxpayload=auto", fill="white")
            draw.text((80, 140), "linux /casper/vmlinuz", fill="white")
            draw.text((80, 160), "initrd /casper/initrd", fill="white")
            image.save(frame)
            image_without_cursor = Image.new("RGB", (1280, 800), "black")
            ImageDraw.Draw(image_without_cursor).rectangle(
                (12, 67, 1267, 675),
                outline=(190, 190, 190),
                width=2,
            )
            image_without_cursor.save(missing)
            crowded_menu = Image.new("RGB", (1280, 800), "black")
            crowded_draw = ImageDraw.Draw(crowded_menu)
            crowded_draw.rectangle(
                (12, 67, 1267, 675), outline=(190, 190, 190), width=2
            )
            for index in range(20):
                crowded_draw.text(
                    (24, 82 + index * 24),
                    f"Locale entry {index}",
                    fill="white",
                )
            crowded_menu.save(crowded)
            layout = grub_editor_layout(frame)
            self.assertIsNotNone(layout)
            self.assertGreaterEqual(layout.visible_command_lines, 3)
            self.assertIsNone(grub_editor_layout(missing))
            self.assertIsNone(grub_editor_layout(crowded))
            wrapped_image = image.copy()
            wrapped_draw = ImageDraw.Draw(wrapped_image)
            wrapped_draw.text(
                (80, 180),
                "timezone=Asia/Shanghai nopersistent quiet splash ---",
                fill="white",
            )
            wrapped_image.save(wrapped)
            wrapped_layout = grub_editor_layout(wrapped)
            self.assertIsNotNone(wrapped_layout)
            self.assertEqual(5, wrapped_layout.visible_command_lines)
            cursor_image = image.copy()
            ImageDraw.Draw(cursor_image).rectangle(
                (16, 112, 23, 114), fill="white"
            )
            cursor_image.save(cursor)
            self.assertEqual(113, grub_editor_left_cursor_y(cursor))
            self.assertIsNone(grub_editor_left_cursor_y(frame))

    def test_grub_menu_oracle_requires_border_and_highlight(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            menu = root / "menu.ppm"
            editor = root / "editor.ppm"
            menu_image = Image.new("RGB", (640, 400), "black")
            draw = ImageDraw.Draw(menu_image)
            # This mirrors the signed GRUB text layout: its lower border is at
            # 85% of the screen, with help text below it.
            draw.rectangle((15, 50, 624, 340), outline=(190, 190, 190), width=2)
            draw.rectangle((18, 62, 621, 78), fill=(180, 180, 180))
            draw.text((22, 64), "*AnduinOS", fill="black")
            menu_image.save(menu)
            editor_image = Image.new("RGB", (640, 400), "black")
            ImageDraw.Draw(editor_image).rectangle(
                (15, 50, 624, 340),
                outline=(190, 190, 190),
                width=2,
            )
            editor_image.save(editor)
            self.assertIsNotNone(grub_menu_layout(menu))
            self.assertIsNone(grub_menu_layout(editor))

    def test_grub_ppm_reader_fails_closed_on_malformed_frames(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            truncated = root / "truncated.ppm"
            truncated.write_bytes(b"P6\n640 400\n255\n" + b"\0" * 10)
            with self.assertRaisesRegex(TestFailure, "Incomplete PPM screendump"):
                grub_menu_layout(truncated)

            trailing = root / "trailing.ppm"
            trailing.write_bytes(b"P6\n1 1\n255\n\0\0\0unexpected")
            with self.assertRaisesRegex(TestFailure, "Incomplete PPM screendump"):
                grub_menu_layout(trailing)

            huge = root / "huge.ppm"
            huge.write_bytes(b"P6\n16384 16384\n255\n")
            with self.assertRaisesRegex(TestFailure, "Unsafe PPM dimensions"):
                grub_menu_layout(huge)

            hostile_header = root / "hostile-header.ppm"
            hostile_header.write_bytes(b"P6\n" + b"9" * 33 + b" 1\n255\n")
            with self.assertRaisesRegex(TestFailure, "Unsafe PPM header token"):
                grub_menu_layout(hostile_header)

    def test_theme_transition_requires_a_visible_light_to_dark_repaint(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            light_path = root / "light.ppm"
            dark_path = root / "dark.ppm"
            light = Image.new("RGB", (800, 600), (245, 245, 245))
            dark = Image.new("RGB", (800, 600), (28, 30, 34))
            light.save(light_path)
            dark.save(dark_path)
            assert_theme_transition(light_path, dark_path, root / "theme.json")
            self.assertTrue((root / "theme.json").is_file())
            with self.assertRaisesRegex(TestFailure, "light frame"):
                assert_theme_transition(dark_path, dark_path, root / "same.json")
            with self.assertRaisesRegex(TestFailure, "dark frame"):
                assert_theme_transition(light_path, light_path, root / "reversed.json")

    def test_gdm_pointer_oracle_requires_motion_at_both_requested_positions(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            before = Image.new("RGB", (800, 600), "white")
            after = before.copy()
            ImageDraw.Draw(before).rectangle((190, 285, 209, 304), fill="black")
            ImageDraw.Draw(after).rectangle((590, 285, 609, 304), fill="black")
            before_path = root / "before.ppm"
            after_path = root / "after.ppm"
            before.save(before_path)
            after.save(after_path)
            assert_pointer_motion(before_path, after_path, root / "pointer.json")
            after.save(before_path)
            with self.assertRaisesRegex(TestFailure, "both GDM target positions"):
                assert_pointer_motion(before_path, after_path, root / "bad.json")

    def test_font_fixture_requires_green_pistol_and_visible_chinese(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            screenshot = root / "font.ppm"
            image = Image.new("RGB", (800, 600), "white")
            draw = ImageDraw.Draw(image)
            draw.rectangle((330, 100, 470, 230), fill=(20, 190, 80))
            draw.rectangle((250, 420, 550, 470), fill=(20, 20, 20))
            image.save(screenshot)
            assert_font_fixture(screenshot, root / "analysis.json")
            self.assertTrue((root / "analysis.json").is_file())

    def test_font_fixture_rejects_monochrome_pistol(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            screenshot = root / "font.ppm"
            image = Image.new("RGB", (800, 600), "white")
            ImageDraw.Draw(image).rectangle(
                (250, 420, 550, 470), fill=(20, 20, 20)
            )
            image.save(screenshot)
            with self.assertRaises(TestFailure):
                assert_font_fixture(screenshot, root / "analysis.json")

    def test_plymouth_oracle_finds_bottom_center_watermark(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            watermark = Image.new("RGBA", (120, 30), (0, 0, 0, 0))
            draw = ImageDraw.Draw(watermark)
            draw.rectangle((0, 0, 35, 29), fill=(20, 140, 240, 255))
            draw.rectangle((42, 5, 119, 24), fill=(255, 255, 255, 255))
            watermark_path = root / "watermark.png"
            watermark.save(watermark_path)
            frame = Image.new("RGB", (640, 480), "black")
            frame.paste(watermark, ((640 - 120) // 2, 420), watermark)
            frame_path = root / "frame.ppm"
            frame.save(frame_path)
            self.assertTrue(plymouth_match(frame_path, watermark_path)["matched"])

    def test_plymouth_oracle_rejects_unbranded_frame(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            watermark = Image.new("RGBA", (120, 30), (255, 255, 255, 255))
            watermark_path = root / "watermark.png"
            watermark.save(watermark_path)
            frame_path = root / "frame.ppm"
            Image.new("RGB", (640, 480), "black").save(frame_path)
            self.assertFalse(plymouth_match(frame_path, watermark_path)["matched"])


class ReleaseGateWiringTests(unittest.TestCase):
    def test_action_scoped_journal_is_real_in_base_and_overlay_drivers(self):
        runner = Path("tests/iso_test/runner.py").read_text(encoding="utf-8")
        base = runner.split("def _assert_action_scoped_journal(", 1)[1].split(
            "def _assert_journal_health(",
            1,
        )[0]
        self.assertIn('after_cursor=cursors["system"]', base)
        self.assertIn('after_cursor=cursors["user"]', base)
        self.assertIn('action_scope="installed-desktop-gate"', base)
        self.assertIn("if not verdict.passed", base)

        features = Path("tests/iso_test/feature_runner.py").read_text(
            encoding="utf-8"
        )
        shell_driver = features.split("def _run_shell_driver(", 1)[1].split(
            "def _stabilize_shell_search_provider(",
            1,
        )[0]
        file_driver = features.split("def _run_file_driver(", 1)[1].split(
            "def _exercise_image_thumbnail(",
            1,
        )[0]
        for body in (shell_driver, file_driver):
            self.assertIn("cursors = self._journal_cursors(vm)", body)
            self.assertIn("self._assert_scoped_journal(", body)

    def test_gdm_cursor_probe_restores_the_locked_security_policy(self):
        source = Path("tests/iso_test/feature_runner.py").read_text(encoding="utf-8")
        exercise = source.split("def _exercise_gdm_cursor(", 1)[1].split(
            "def _backup_gdm_screenshot_policy(",
            1,
        )[0]
        policy = source.split("def _set_gdm_screenshot_policy(", 1)[1].split(
            "def _capture_gdm_cursor_frame(",
            1,
        )[0]
        self.assertIn("finally:", exercise)
        self.assertIn("capture_enabled=False", exercise)
        self.assertIn('cmp -s \\"$backup/settings\\" \\"$settings\\"', policy)
        self.assertIn('cmp -s \\"$backup/locks\\" \\"$locks\\"', policy)
        self.assertIn("restored-lockdown=true", policy)

    def test_gdm_contract_reads_the_real_greeter_dconf_profile(self):
        source = Path("tests/iso_test/feature_runner.py").read_text(encoding="utf-8")
        helper = source.split("def _gdm_gsettings_get(", 1)[1].split(
            "def _capture_gdm_cursor_frame(",
            1,
        )[0]
        self.assertIn('"DCONF_PROFILE=gdm"', helper)
        self.assertIn('"gsettings"', helper)
        self.assertIn("_gdm_gsettings_get(", source)

    def test_gdm_cursor_uses_shell_capture_with_the_cursor_plane(self):
        source = Path("tests/iso_test/feature_runner.py").read_text(encoding="utf-8")
        body = source.split("def _capture_gdm_cursor_frame(", 1)[1].split(
            "def _exercise_theme_selector(",
            1,
        )[0]
        self.assertIn("gdm_screenshot_client.py", body)
        self.assertIn("_retrieve_file", body)
        self.assertNotIn("vm.screenshot", body)

    def test_gdm_screenshot_client_fails_closed_without_trusted_name_or_capture(self):
        fixture = runpy.run_path("tests/guest/gdm_screenshot_client.py")
        with self.assertRaisesRegex(RuntimeError, "trusted screenshot sender"):
            fixture["_require_primary_owner"](2)
        with self.assertRaisesRegex(RuntimeError, "capture failed"):
            fixture["_require_screenshot_reply"](
                False, "/tmp/frame.png", "/tmp/frame.png"
            )
        with self.assertRaisesRegex(RuntimeError, "unexpected screenshot path"):
            fixture["_require_screenshot_reply"](
                True, "/tmp/wrong.png", "/tmp/frame.png"
            )

    def test_gdm_screenshot_client_uses_and_releases_shell_allowlisted_name(self):
        fixture = Path("tests/guest/gdm_screenshot_client.py").read_text(
            encoding="utf-8"
        )
        runner = Path("tests/iso_test/feature_runner.py").read_text(encoding="utf-8")
        self.assertIn('TRUSTED_NAME = "org.gnome.SettingsDaemon.MediaKeys"', fixture)
        self.assertIn("DBUS_REQUEST_NAME_FLAGS_DO_NOT_QUEUE", fixture)
        self.assertIn('"RequestName"', fixture)
        self.assertIn('"ReleaseName"', fixture)
        self.assertIn("finally:", fixture)
        self.assertIn("org.gnome.SettingsDaemon.MediaKeys.target", runner)
        self.assertIn("media-keys-restored=active", runner)

    def test_firefox_theme_fixture_disables_first_run_ui_and_forces_atspi(self):
        source = Path("tests/iso_test/feature_runner.py").read_text(encoding="utf-8")
        body = source.split("def _exercise_firefox_theme(", 1)[1].split(
            "def _prepare_theme_fixture(",
            1,
        )[0]
        for preference in (
            'browser.aboutwelcome.enabled\\\", false',
            'browser.preonboarding.enabled\\\", false',
            'trailhead.firstrun.didSeeAboutWelcome\\\", true',
            'termsofuse.bypassNotification\\\", true',
            'termsofuse.acceptedVersion\\\", 999',
            'accessibility.force_disabled\\\", -1',
        ):
            self.assertIn(preference, body)

    def test_qt_theme_fixture_keeps_the_normal_platform_integration(self):
        source = Path("tests/iso_test/feature_runner.py").read_text(encoding="utf-8")
        body = source.split("def _exercise_qt_theme(", 1)[1].split(
            "def _exercise_firefox_theme(",
            1,
        )[0]
        self.assertNotIn("--no-install-recommends", body)
        self.assertIn("python3-pyqt6", body)
        self.assertIn("qt6-gtk-platformtheme", body)
        self.assertIn("qt6-qpa-plugins", body)
        self.assertNotIn("QT_QPA_PLATFORMTHEME", body)
        self.assertNotIn("QT_STYLE_OVERRIDE", body)

        fixture = Path("tests/guest/qt_theme_fixture.py").read_text(encoding="utf-8")
        self.assertIn("application.paletteChanged.connect", fixture)
        self.assertIn("QPalette.ColorRole.Window", fixture)
        self.assertNotIn("setPalette", fixture)
        self.assertNotIn("setStyleSheet", fixture)

    def test_accounts_driver_treats_password_policy_radio_as_a_toggle(self):
        source = Path("tests/guest/atspi_driver.py").read_text(encoding="utf-8")
        control_body = source.split("def control(key: str):", 1)[1].split(
            "def request_focused_activation", 1
        )[0]
        self.assertIn('"radio button"', control_body)

    def test_accounts_settings_log_is_private_to_each_graphical_user(self):
        source = Path("tests/guest/atspi_driver.py").read_text(encoding="utf-8")
        body = source.split("def prepare_user_accounts(", 1)[1].split(
            "def authenticate_user_panel(", 1
        )[0]
        self.assertIn('os.environ.get("XDG_RUNTIME_DIR"', body)
        self.assertIn("os.getpid()", body)
        self.assertNotIn("/tmp/gnome-users.stdout", body)

    def test_accounts_evidence_is_separated_across_graphical_users(self):
        source = Path("tests/iso_test/feature_runner.py").read_text(encoding="utf-8")
        for directory in (
            "evidence/account-create",
            "evidence/account-change-password",
            "evidence/gdm-audit",
            "evidence/gdm-{label}",
        ):
            self.assertIn(directory, source)

        account_body = source.split("def _exercise_account_add_user(", 1)[1].split(
            "def _exercise_gdm_branding(", 1
        )[0]
        self.assertNotIn('f"{remote}/evidence",', account_body)

    def test_password_row_uses_verified_keyboard_activation(self):
        source = Path("tests/guest/atspi_driver.py").read_text(encoding="utf-8")
        body = source.split("def change_own_password(", 1)[1].split(
            "def dynamic_user_node(", 1
        )[0]
        self.assertIn("request_focused_activation(", body)
        self.assertIn('"accounts-open-change-password"', body)
        self.assertNotIn('click("password"', body)
        self.assertNotIn("request_semantic_pointer_click(", body)
        self.assertIn("discover_current_password_focus()", body)
        self.assertIn("request_dialog_secret(", body)
        self.assertIn("accounts-change-password-submit", body)
        self.assertNotIn('click("change"', body)
        focus_search = source.split(
            "def discover_current_password_focus(", 1
        )[1].split("def request_dialog_secret(", 1)[0]
        self.assertIn("gnome-dialog-tab-search", focus_search)
        self.assertIn('enabled(editable_control("new_password"', focus_search)
        self.assertIn('event("current-password-authenticated"', focus_search)
        self.assertNotIn("qmp-click", focus_search)
        dialog_secret = source.split("def request_dialog_secret(", 1)[1].split(
            "def wait_absent(", 1
        )[0]
        self.assertIn("gnome-dialog-focus-chain", dialog_secret)
        self.assertIn('key="tab"', dialog_secret)
        self.assertNotIn("grab_focus", dialog_secret)
        delivery = source.split("def _request_secret_delivery(", 1)[1].split(
            "def request_secret(", 1
        )[0]
        self.assertIn("get_character_count()", delivery)
        self.assertIn("Secret input did not reach field", delivery)

    def test_installer_failure_path_preserves_the_executor_transcript(self):
        source = Path("tests/guest/atspi_driver.py").read_text(encoding="utf-8")
        install = source.split("def install(", 1)[1].split(
            "def prepare_secure_shell(", 1
        )[0]
        failed = install.split('if find_optional("failed"', 1)[1].split(
            'if find_optional("complete"', 1
        )[0]
        self.assertIn("save_executor_output()", failed)
        self.assertIn('evidence / "installer-output.txt"', install)
        self.assertIn('click("save_log")', install)

    def test_graphical_user_probe_excludes_display_manager_accounts(self):
        self.assertIn("gdm-greeter", _GRAPHICAL_USER_SCRIPT)
        self.assertIn("/usr/sbin/nologin", _GRAPHICAL_USER_SCRIPT)
        self.assertIn("/bin/false", _GRAPHICAL_USER_SCRIPT)

    def test_desktop_command_quotes_nested_shell_in_both_lifecycle_modes(self):
        payload = """set -euo pipefail
value=$(printf '%s\\n' \"nested quotes\")
test \"$value\" = 'nested quotes'
"""
        for managed in (False, True):
            command = _desktop_command(
                "anduinostest",
                ("bash", "-lc", payload),
                managed=managed,
            )
            parsed = subprocess.run(
                ("bash", "-n"),
                input=command,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=False,
            )
            self.assertEqual(0, parsed.returncode, parsed.stderr)
            self.assertIn("nested quotes", command)

    def test_installed_release_script_contains_every_declared_command_contract(self):
        with tempfile.TemporaryDirectory() as directory:
            console = _CaptureConsole()
            _assert_release_contracts(console, "anduinostest", Path(directory))
            script = "\n".join(console.scripts)
        self.assertEqual(len(RELEASE_CONTRACT_CHECKS), len(console.scripts))
        self.assertIn("fs.inotify.max_user_instances", script)
        self.assertIn("get_ptyxis_setting range", script)
        self.assertIn("get_ptyxis_setting get", script)
        self.assertIn("(uint32 80, uint32 24)", script)
        self.assertIn("xdg-mime query default", script)
        self.assertIn("org.gnome.Loupe.desktop", script)
        self.assertIn("io.github.celluloid_player.Celluloid.desktop", script)
        self.assertIn("gnome-software-local-file-packagekit.desktop", script)
        self.assertNotIn("com.anduinos.AppImageRunner.desktop", script)
        self.assertNotIn("com.anduinos.ExeRunner.desktop", script)
        self.assertIn("why_output=$(why", script)
        self.assertIn("Noto Sans CJK SC", script)
        self.assertIn("Twemoji", script)
        self.assertIn("/etc/alternatives/default.plymouth", script)

    def test_release_contracts_have_independent_scripts_and_evidence(self):
        with tempfile.TemporaryDirectory() as directory:
            evidence = Path(directory)
            scripts = {}
            for identifier in RELEASE_CONTRACT_CHECKS:
                console = _CaptureConsole()
                assert_release_contract(
                    console,
                    "anduinostest",
                    evidence,
                    identifier,
                )
                self.assertEqual(1, len(console.scripts))
                scripts[identifier] = console.scripts[0]
                expected = evidence / (identifier.replace(".", "-") + ".txt")
                self.assertTrue(expected.is_file())

        self.assertIn(
            "fs.inotify.max_user_instances",
            scripts["system.inotify-max-user-instances"],
        )
        ptyxis_script = scripts["terminal.ptyxis-initial-size"]
        self.assertIn("runuser -u anduinostest", ptyxis_script)
        self.assertIn("HOME=/home/anduinostest", ptyxis_script)
        self.assertIn("GSETTINGS_BACKEND=dconf", ptyxis_script)
        self.assertIn("dpkg-query -W", ptyxis_script)
        self.assertIn("anduinos-dconf-defaults", ptyxis_script)
        self.assertIn("gsettings \"$@\" org.gnome.Ptyxis window-size", ptyxis_script)
        self.assertIn("test \"$ptyxis_type\" = 'type (uu)'", ptyxis_script)
        self.assertIn(
            "test \"$ptyxis_size\" = '(uint32 80, uint32 24)'",
            ptyxis_script,
        )
        self.assertIn("xdg-mime query default", scripts["desktop.mime-defaults"])
        self.assertIn("why_output=$(why", scripts["command.why-placeholder"])
        self.assertIn("Twemoji", scripts["font.selection-contracts"])
        self.assertIn(
            "/etc/alternatives/default.plymouth",
            scripts["boot.plymouth-theme-selection"],
        )
        with tempfile.TemporaryDirectory() as directory, self.assertRaisesRegex(
            ValueError,
            "Unknown release contract",
        ):
            assert_release_contract(
                _CaptureConsole(),
                "anduinostest",
                Path(directory),
                "invented.contract",
            )

    def test_independent_file_contracts_accept_native_appimage_and_pe_handler(self):
        _validate_appimage_fixture_contract(
            "appimage-mime=application/vnd.appimage\n"
            "appimage-default=\n"
            "appimage-runner-present=no\n"
            "appimage-mode=755\n"
            "appimage-blocked-mode=644\n"
        )
        _validate_windows_executable_fixture_contract(
            "pe-mime=application/vnd.microsoft.portable-executable\n"
            "pe-default=com.anduinos.ExeRunner.desktop\n"
        )

    def test_appimage_contract_rejects_obsolete_runner_without_pe_evidence(
        self,
    ):
        with self.assertRaisesRegex(
            TestFailure,
            "unexpectedly depends on a MIME handler",
        ):
            _validate_appimage_fixture_contract(
                "appimage-mime=application/vnd.appimage\n"
                "appimage-default=com.anduinos.AppImageRunner.desktop\n"
                "appimage-runner-present=yes\n"
                "appimage-mode=755\n"
                "appimage-blocked-mode=644\n"
            )

    def test_appimage_contract_rejects_erased_execution_boundary(self):
        with self.assertRaisesRegex(TestFailure, "negative AppImage fixture"):
            _validate_appimage_fixture_contract(
                "appimage-mime=application/vnd.appimage\n"
                "appimage-default=\n"
                "appimage-runner-present=no\n"
                "appimage-mode=755\n"
                "appimage-blocked-mode=755\n"
            )

    def test_non_executable_appimage_requires_unique_blocked_runtime_event(self):
        passing = json.dumps(
            {
                "event": "nautilus-open-blocked",
                "filename": "AnduinOS-Blocked.AppImage",
                "activation_method": "selected-item-qmp-enter",
                "executable": False,
                "fixture_window_visible": False,
                "process_running": False,
            }
        ) + "\n"
        _validate_appimage_blocked_events(passing)
        with self.assertRaisesRegex(TestFailure, "execution boundary"):
            _validate_appimage_blocked_events(
                passing.replace('"process_running": false', '"process_running": true')
            )

    def test_non_executable_appimage_uses_retrievable_writable_evidence_tree(self):
        source = Path("tests/iso_test/runner.py").read_text(encoding="utf-8")
        self.assertIn('f"{remote_root}/evidence/blocked"', source)
        self.assertNotIn("evidence-blocked", source)

    def test_non_executable_appimage_does_not_count_nautilus_select_as_execution(
        self,
    ):
        source = Path("tests/guest/atspi_driver.py").read_text(encoding="utf-8")
        self.assertIn("executable.samefile(target_resolved)", source)
        self.assertIn("argument_zero.samefile(target_resolved)", source)
        self.assertIn("referencing_processes=referencing_processes", source)
        self.assertNotIn("if filename_bytes in value:\n                process_running", source)

    def test_pe_contract_fault_injection_does_not_require_appimage_evidence(self):
        with self.assertRaisesRegex(
            TestFailure,
            "CPU-Z PE default handler is missing or incorrect: <none>",
        ):
            _validate_windows_executable_fixture_contract(
                "pe-mime=application/vnd.microsoft.portable-executable\n"
                "pe-default=\n"
            )

    def test_desktop_gate_calls_every_implemented_runtime_check(self):
        source = Path("tests/iso_test/runner.py").read_text(encoding="utf-8")
        for method in (
            "_exercise_font_rendering",
            "_exercise_appimage_open",
            "_exercise_windows_executable_open",
            "_assert_gnome_extensions",
            "_exercise_dynamic_resolution",
            "_assert_journal_health",
            "_assert_passive_plymouth_boot",
        ):
            self.assertGreaterEqual(source.count(f"self.{method}("), 1, method)

    def test_appimage_failure_cannot_mask_windows_executable_check(self):
        runner = object.__new__(ScenarioRunner)
        events = []
        runner._check_details = {}
        runner._emit_check = (
            lambda scenario, check, state, detail: events.append(
                (scenario, check, state, detail)
            )
        )
        failures = []
        windows_executable_ran = False

        def fail_appimage():
            raise TestFailure("injected AppImage native activation failure")

        def pass_windows_executable():
            nonlocal windows_executable_ran
            windows_executable_ran = True

        with tempfile.TemporaryDirectory() as directory:
            artifacts = Path(directory)
            scenario = SimpleNamespace(id="desktop-gate")
            runner._collect_gate_failure(
                scenario,
                "files.appimage-open",
                fail_appimage,
                failures,
                artifacts,
            )
            runner._collect_gate_failure(
                scenario,
                "files.exe-open-fixture",
                pass_windows_executable,
                failures,
                artifacts,
            )
            persisted = (artifacts / "gate-failures.txt").read_text(
                encoding="utf-8"
            )

        self.assertTrue(windows_executable_ran)
        self.assertEqual(1, len(failures))
        self.assertIn("injected AppImage native activation failure", persisted)
        self.assertIn(
            ("desktop-gate", "files.exe-open-fixture", "passed", "All assertions passed"),
            events,
        )

    @patch("iso_test.runner.assert_release_contract")
    def test_failed_installed_contract_collects_every_sibling_then_blocks(self, contract):
        runner = object.__new__(ScenarioRunner)
        runner.defaults = SimpleNamespace(username="anduinostest")
        runner._check_details = {}
        events = []
        runner._emit_check = (
            lambda scenario, check, state, detail: events.append(
                (scenario, check, state, detail)
            )
        )
        contract.side_effect = [
            None,
            TestFailure("injected invalid Ptyxis dconf value"),
            *([None] * (len(RELEASE_CONTRACT_CHECKS) - 2)),
        ]
        vm = SimpleNamespace(serial=object())
        scenario = SimpleNamespace(id="bios-offline-btrfs")

        with tempfile.TemporaryDirectory() as directory, self.assertRaisesRegex(
            TestFailure,
            "(?s)Installed-system release contracts failed.*invalid Ptyxis dconf value",
        ):
            runner._assert_installed_release_contracts(
                vm,
                scenario,
                Path(directory),
            )

        self.assertEqual(len(RELEASE_CONTRACT_CHECKS), contract.call_count)
        self.assertEqual(
            list(RELEASE_CONTRACT_CHECKS),
            [call.args[3] for call in contract.call_args_list],
        )
        states = {check: state for _scenario, check, state, _detail in events}
        self.assertEqual("failed", states["terminal.ptyxis-initial-size"])
        for identifier in RELEASE_CONTRACT_CHECKS:
            if identifier != "terminal.ptyxis-initial-size":
                self.assertEqual("passed", states[identifier])

    def test_passed_and_failed_target_disks_are_discarded_by_default(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            runner = object.__new__(ScenarioRunner)
            runner.options = SimpleNamespace(
                keep_passed_disk=False,
                keep_failed_disk=False,
                disk_storage=DiskStorage(root, "filesystem", "unit test"),
            )
            for passed in (True, False):
                disk = root / "target.qcow2"
                variables = root / "uefi-vars.fd"
                disk.write_bytes(b"disposable")
                variables.write_bytes(b"disposable firmware state")
                vm = SimpleNamespace(
                    running=False,
                    config=SimpleNamespace(disk=disk, variables=variables),
                )
                runner._finalize_disk(vm, root, passed=passed)
                self.assertFalse(disk.exists())
                self.assertFalse(variables.exists())
                evidence = (root / "target-disk-retention.txt").read_text(
                    encoding="utf-8"
                )
                self.assertIn("discarded", evidence)
                self.assertIn("passed" if passed else "failed", evidence)

    def test_explicit_single_debug_disk_can_be_retained(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            disk = root / "target.qcow2"
            variables = root / "uefi-vars.fd"
            disk.write_bytes(b"debug")
            variables.write_bytes(b"debug firmware state")
            runner = object.__new__(ScenarioRunner)
            runner.options = SimpleNamespace(
                keep_passed_disk=False,
                keep_failed_disk=True,
                disk_storage=DiskStorage(root, "filesystem", "unit test"),
            )
            vm = SimpleNamespace(
                running=False,
                config=SimpleNamespace(disk=disk, variables=variables),
            )
            runner._finalize_disk(vm, root, passed=False)
            self.assertTrue(disk.exists())
            self.assertTrue(variables.exists())
            self.assertIn(
                "retained",
                (root / "target-disk-retention.txt").read_text(encoding="utf-8"),
            )

    def test_feature_overlay_cleanup_discards_its_uefi_variables(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            backing = root / "base.qcow2"
            disk = root / "suite" / "overlay.qcow2"
            variables = root / "artifacts" / "uefi-vars.fd"
            backing.write_bytes(b"immutable base")
            disk.parent.mkdir()
            disk.write_bytes(b"overlay")
            variables.parent.mkdir()
            variables.write_bytes(b"overlay firmware state")
            vm = SimpleNamespace(
                stop=Mock(),
                config=SimpleNamespace(
                    backing_disk=backing,
                    disk=disk,
                    variables=variables,
                ),
            )

            discard_overlay(vm)

            vm.stop.assert_called_once_with()
            self.assertFalse(disk.exists())
            self.assertFalse(variables.exists())
            self.assertTrue(backing.exists())

    @patch("iso_test.runner.assert_disk_storage_ready")
    def test_keyboard_interrupt_stops_vm_and_discards_partial_disk(self, _capacity):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            disk = root / "interrupt" / "target.qcow2"
            vm = _CleanupVm(disk)
            runner = object.__new__(ScenarioRunner)
            runner.options = SimpleNamespace(
                artifacts_root=root,
                disk_storage=DiskStorage(root, "filesystem", "unit test"),
                disk_gib=40,
                memory_mib=8192,
                free_space_reserve_gib=10,
                smoke_only=False,
                keep_passed_disk=False,
                keep_failed_disk=False,
            )
            runner._create_vm = lambda _scenario, _artifacts: vm
            runner._write_manifest = lambda *_args: None

            def interrupt(*_args, **_kwargs):
                raise KeyboardInterrupt

            runner._run_live_phase = interrupt
            interrupted_scenario = SimpleNamespace(
                id="interrupt",
                network=Network.OFFLINE,
                mok_enrollment=False,
                passwordless_sudo=False,
                automatic_login=False,
                desktop_release_gate=False,
                snapshots_manager=False,
                ssh=SshPolicy.DISABLED,
            )
            with self.assertRaises(KeyboardInterrupt):
                runner.run(interrupted_scenario)
            self.assertTrue(vm.stopped)
            self.assertFalse(disk.exists())
            self.assertIn(
                "failed target disk discarded",
                (root / "interrupt" / "target-disk-retention.txt").read_text(
                    encoding="utf-8"
                ),
            )


class HostStorageSafetyTests(unittest.TestCase):
    def test_supervisor_enables_python_native_fault_tracebacks_by_default(self):
        with tempfile.TemporaryDirectory() as directory:
            artifacts = Path(directory) / "new-artifacts"
            with patch(
                "iso_test.supervisor.run_supervised_worker",
                return_value=0,
            ) as run:
                result = supervised_main(
                    Path("tests/run.py"),
                    ["--artifacts", str(artifacts)],
                )
        self.assertEqual(0, result)
        environment = run.call_args.kwargs["environment"]
        self.assertEqual("1", environment["PYTHONFAULTHANDLER"])

    def test_native_worker_crash_reclaims_separate_session_and_disk(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            artifacts = root / "artifacts"
            fault_log = root / ".worker-fault.log"
            child_pid = root / "separate-child.pid"
            helper = root / "crashing-worker.py"
            helper.write_text(
                "\n".join(
                    (
                        "import os, resource, signal, subprocess, sys",
                        "from pathlib import Path",
                        "from iso_test.process_lifecycle import parent_death_preexec",
                        "from iso_test.supervisor import configure_worker_fault_handler",
                        "resource.setrlimit(resource.RLIMIT_CORE, (0, 0))",
                        "configure_worker_fault_handler()",
                        "artifacts = Path(sys.argv[1])",
                        "pid_file = Path(sys.argv[2])",
                        "disk = artifacts / 'case' / 'target.qcow2'",
                        "disk.parent.mkdir(parents=True)",
                        "disk.write_bytes(b'disposable guest')",
                        "(artifacts / 'durable-evidence.txt').write_text('keep\\n')",
                        "child = subprocess.Popen(",
                        "    ('sleep', '60'),",
                        "    start_new_session=True,",
                        "    preexec_fn=parent_death_preexec(),",
                        ")",
                        "pid_file.write_text(str(child.pid))",
                        "os.kill(os.getpid(), signal.SIGSEGV)",
                    )
                )
                + "\n",
                encoding="utf-8",
            )
            environment = os.environ.copy()
            environment["PYTHONPATH"] = str(Path(__file__).resolve().parent)
            environment[FAULT_LOG_ENV] = str(fault_log)
            error = io.StringIO()
            with patch("sys.stderr", error):
                result = run_supervised_worker(
                    (sys.executable, str(helper), str(artifacts), str(child_pid)),
                    environment=environment,
                    artifacts=artifacts,
                    artifacts_preexisting=False,
                    workspace_token="a" * 16,
                    retain_disks=False,
                    fault_log=fault_log,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
            self.assertEqual(128 + signal.SIGSEGV, result)
            self.assertIn("SIGSEGV", error.getvalue())
            self.assertFalse((artifacts / "case" / "target.qcow2").exists())
            self.assertEqual(
                "keep\n",
                (artifacts / "durable-evidence.txt").read_text(encoding="utf-8"),
            )
            crash = (artifacts / "worker-fault.log").read_text(encoding="utf-8")
            self.assertIn("Fatal Python error: Segmentation fault", crash)
            self.assertIn("crashing-worker.py", crash)
            pid = int(child_pid.read_text(encoding="ascii"))
            deadline = time.monotonic() + 5
            while Path(f"/proc/{pid}").exists() and time.monotonic() < deadline:
                time.sleep(0.05)
            self.assertFalse(
                Path(f"/proc/{pid}").exists(),
                "parent-death signal left a separate-session child alive",
            )

    def test_supervisor_never_cleans_a_preexisting_artifact_root(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            disk = root / "case" / "target.qcow2"
            disk.parent.mkdir()
            disk.write_bytes(b"user-owned preexisting disk")
            _cleanup_persistent_disks(root, preexisting=True)
            self.assertEqual(b"user-owned preexisting disk", disk.read_bytes())

    @patch("iso_test.storage.shutil.disk_usage")
    def test_capacity_budgets_the_full_virtual_disk_and_reserve(self, disk_usage):
        disk_usage.return_value = SimpleNamespace(free=55 * GIB)
        with tempfile.TemporaryDirectory() as directory:
            capacity = assert_capacity(Path(directory), 40, 10)
        self.assertEqual(50 * GIB, capacity.required_bytes)
        self.assertEqual(55 * GIB, capacity.free_bytes)

    @patch("iso_test.storage.shutil.disk_usage")
    def test_capacity_fails_before_qemu_when_host_space_is_low(self, disk_usage):
        disk_usage.return_value = SimpleNamespace(free=21 * GIB)
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(
                ConfigurationError,
                r"21\.0 GiB is free.*requires 50\.0 GiB",
            ):
                assert_capacity(Path(directory), 40, 10)

    @patch("iso_test.storage.shutil.disk_usage")
    @patch("iso_test.storage._filesystem_type", return_value="tmpfs")
    @patch("iso_test.storage._read_mem_available", return_value=32 * GIB)
    def test_auto_selects_and_cleans_safe_generic_tmpfs(
        self,
        _memory,
        _filesystem,
        disk_usage,
    ):
        disk_usage.return_value = SimpleNamespace(free=12 * GIB)
        with tempfile.TemporaryDirectory() as directory:
            candidate = Path(directory)
            with patch(
                "iso_test.storage._ramdisk_candidates",
                return_value=(candidate,),
            ):
                storage = select_disk_storage(
                    Path("/persistent/results/run"),
                    memory_mib=8192,
                )
            self.assertTrue(storage.is_ramdisk)
            self.assertEqual(12 * GIB, storage.qcow_limit_bytes)
            self.assertEqual(candidate, storage.root.parents[1])
            prepare_disk_storage(storage)
            (storage.root / "case").mkdir()
            (storage.root / "case" / "target.qcow2").write_bytes(b"guest")
            cleanup_disk_storage(storage)
            self.assertFalse(storage.root.exists())

    @patch("iso_test.storage.shutil.disk_usage")
    @patch("iso_test.storage._filesystem_type", return_value="tmpfs")
    @patch("iso_test.storage._read_mem_available", return_value=23 * GIB)
    def test_ramdisk_recheck_budgets_hard_qcow_limit_not_whole_mount(
        self,
        _memory,
        _filesystem,
        disk_usage,
    ):
        disk_usage.return_value = SimpleNamespace(free=15 * GIB)
        storage = DiskStorage(
            Path("/dev/shm/private/run"),
            "ramdisk",
            "unit test",
            memory_available_bytes=23 * GIB,
            ramdisk_free_bytes=15 * GIB,
            qcow_limit_bytes=12 * GIB,
        )
        capacity = assert_disk_storage_ready(
            storage,
            disk_gib=40,
            filesystem_reserve_gib=10,
            memory_mib=8192,
        )
        self.assertEqual(12 * GIB, capacity.required_bytes)

    def test_qemu_child_file_size_limit_is_enforced_by_kernel(self):
        with tempfile.TemporaryDirectory() as directory:
            destination = Path(directory) / "too-large"
            result = subprocess.run(
                (
                    "python3",
                    "-c",
                    "from pathlib import Path; "
                    f"Path({str(destination)!r}).write_bytes(b'x' * 2097152)",
                ),
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=False,
                preexec_fn=_file_size_limiter(1024 * 1024),
            )
        self.assertNotEqual(0, result.returncode)

    @patch("iso_test.storage._read_mem_available", return_value=16 * GIB)
    def test_auto_falls_back_when_available_memory_is_not_above_threshold(
        self,
        _memory,
    ):
        artifacts = Path("/persistent/results/run")
        storage = select_disk_storage(artifacts, memory_mib=8192)
        self.assertFalse(storage.is_ramdisk)
        self.assertEqual(artifacts, storage.root)
        self.assertIn("not above", storage.reason)

    @patch("iso_test.storage.shutil.disk_usage")
    @patch("iso_test.storage._filesystem_type", return_value="tmpfs")
    @patch("iso_test.storage._read_mem_available", return_value=64 * GIB)
    def test_ci_sized_tmpfs_falls_back_to_filesystem(
        self,
        _memory,
        _filesystem,
        disk_usage,
    ):
        disk_usage.return_value = SimpleNamespace(free=64 * 1024**2)
        with tempfile.TemporaryDirectory() as directory:
            with patch(
                "iso_test.storage._ramdisk_candidates",
                return_value=(Path(directory),),
            ):
                storage = select_disk_storage(
                    Path("/persistent/results/run"),
                    memory_mib=8192,
                )
        self.assertFalse(storage.is_ramdisk)
        self.assertIn("no writable tmpfs", storage.reason)

    @patch("iso_test.storage._read_mem_available", return_value=64 * GIB)
    def test_retained_debug_disk_always_uses_persistent_storage(self, _memory):
        artifacts = Path("/persistent/results/run")
        storage = select_disk_storage(
            artifacts,
            memory_mib=8192,
            retain_disk=True,
        )
        self.assertFalse(storage.is_ramdisk)
        self.assertIn("retention", storage.reason)

    @patch("iso_test.storage._read_mem_available", return_value=8 * GIB)
    def test_forced_ramdisk_fails_closed_when_memory_is_low(self, _memory):
        with self.assertRaisesRegex(ConfigurationError, "requested but unavailable"):
            select_disk_storage(
                Path("/persistent/results/run"),
                memory_mib=8192,
                mode="ramdisk",
            )

    def test_retention_requires_exactly_one_explicit_case(self):
        unsafe = SimpleNamespace(
            keep_passed_disk=False,
            keep_failed_disk=True,
            cases=[],
        )
        with self.assertRaisesRegex(ConfigurationError, "exactly one explicit"):
            _validate_disk_retention(unsafe, (object(), object()))
        safe = SimpleNamespace(
            keep_passed_disk=False,
            keep_failed_disk=True,
            cases=["one"],
        )
        _validate_disk_retention(safe, (object(),))

    def test_sigterm_is_converted_to_cleanup_interrupt_and_restored(self):
        original = signal.getsignal(signal.SIGTERM)
        with _termination_as_interrupt():
            handler = signal.getsignal(signal.SIGTERM)
            self.assertTrue(callable(handler))
            with self.assertRaises(KeyboardInterrupt):
                handler(signal.SIGTERM, None)
        self.assertIs(original, signal.getsignal(signal.SIGTERM))


class _CleanupVm:
    def __init__(self, disk: Path):
        self.config = SimpleNamespace(disk=disk)
        self.running = False
        self.stopped = False

    def create_disk(self):
        self.config.disk.parent.mkdir(parents=True, exist_ok=True)
        self.config.disk.write_bytes(b"partial guest")
        self.running = True

    def stop(self):
        self.running = False
        self.stopped = True


class _FaultyQmp:
    def __init__(self):
        self.close_attempted = False

    def quit(self):
        raise RuntimeError("injected QMP failure")

    def close(self):
        self.close_attempted = True
        raise RuntimeError("injected QMP close failure")


class _ReapProcess:
    def __init__(self):
        self.returncode = None
        self.waited = False

    def poll(self):
        return self.returncode

    def wait(self, timeout):
        self.waited = True
        self.returncode = 0
        return 0


class _FaultyClose:
    def __init__(self):
        self.close_attempted = False

    def close(self):
        self.close_attempted = True
        raise OSError("injected close failure")


class _FaultyRuntime:
    def __init__(self):
        self.cleanup_attempted = False

    def cleanup(self):
        self.cleanup_attempted = True
        raise OSError("injected runtime cleanup failure")


class _ResultConsole:
    def __init__(self, result):
        self.result = result

    def run(self, *_args, **_options):
        return self.result


class _CaptureConsole:
    def __init__(self):
        self.scripts = []

    def run(self, script, **_options):
        self.scripts.append(script)
        return CommandResult("", 0)


class _UploadCaptureConsole(SerialConsole):
    def __init__(self):
        self.scripts = []

    def run(self, script, **_options):
        self.scripts.append(script)
        return CommandResult("", 0)


class _DownloadCaptureConsole(SerialConsole):
    def __init__(
        self,
        payload: bytes,
        *,
        corrupt_first_chunk: bool = False,
        corrupt_every_chunk: bool = False,
    ):
        self.payload = payload
        self.corrupt_first_chunk = corrupt_first_chunk
        self.corrupt_every_chunk = corrupt_every_chunk
        self.chunk_calls = 0
        self.corruptions_injected = 0

    def run(self, script, **_options):
        meta = re.search(r"token=(__ANDUINOS_DOWNLOAD_META_[0-9a-f]+__)", script)
        if meta is not None:
            token = meta.group(1)
            digest = hashlib.sha256(self.payload).hexdigest()
            return CommandResult(
                f"{token}:present:{len(self.payload)}:{digest}", 0
            )
        chunk = re.search(
            r"offset=([0-9]+)\ncount=([0-9]+)\n"
            r"token=(__ANDUINOS_DOWNLOAD_CHUNK_[0-9a-f]+__)",
            script,
        )
        if chunk is None:
            raise AssertionError(f"Unexpected download command: {script}")
        offset = int(chunk.group(1))
        count = int(chunk.group(2))
        token = chunk.group(3)
        value = self.payload[offset : offset + count]
        encoded = base64.b64encode(value).decode("ascii")
        digest = hashlib.sha256(value).hexdigest()
        self.chunk_calls += 1
        corrupt = self.corrupt_every_chunk or (
            self.corrupt_first_chunk and self.corruptions_injected == 0
        )
        if corrupt:
            self.corruptions_injected += 1
            midpoint = len(encoded) // 2
            encoded = (
                encoded[:midpoint]
                + "[  117.261164] xhci_hcd: host controller died\n"
                + encoded[midpoint:]
            )
        return CommandResult(f"{token}:{offset}:{digest}:{encoded}", 0)


if __name__ == "__main__":
    unittest.main()
