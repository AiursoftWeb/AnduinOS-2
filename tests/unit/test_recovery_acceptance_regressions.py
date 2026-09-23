"""Regression checks for real acceptance failures, without booting a VM."""

import ast
import inspect
import io
import json
import os
from pathlib import Path
import runpy
import subprocess
import tempfile
import textwrap
import unittest
from unittest.mock import Mock, patch
from types import SimpleNamespace
import xml.etree.ElementTree as ET

from business.acceptance import _blocked_suite_result
from business.desktop.context import (_LOCAL_ARCMENU_SEARCH_CHECKS,
    _LOCAL_SEARCH_DRIVER_MODES, _SOFTWARE_SEARCH_DRIVER_MODES)
from business.desktop.runner import FeatureSuiteRunner
from business.desktop.lifecycle import _revert_checkpoint_probe_command
from business.install.phases import InstallationPhases
from business.install.journal import JournalChecks
from framework.dashboard import AcceptanceDashboard
from framework.dashboard_render import render_dashboard
from framework.reporting import write_junit_report
from framework.errors import TestFailure
from framework.model import Architecture

ROOT = Path(__file__).resolve().parents[1]


class AcceptanceRegressionTests(unittest.TestCase):
    def test_power_loss_revert_reads_this_boot_and_durable_history(self):
        command = _revert_checkpoint_probe_command()
        self.assertIn("journalctl -b -t dracut-pre-mount", command)
        self.assertIn("grep -Fx 'SNAPSHOTS-MANAGER-CHECKPOINT reverted-recorded'", command)
        self.assertIn("rollback-history/*.json", command)
        self.assertIn("reverted-history=verified", command)
        self.assertNotIn("wait_for_text", command)

    def test_power_loss_observation_changes_only_the_recovery_entry(self):
        transform = runpy.run_path(str(ROOT / "assertions/guest/recovery_power_loss.py"))["instrument"]
        normal = "  linux /boot/vmlinuz root=UUID=test ro quiet splash\n"
        recovery = "  linux /recovery/vmlinuz root=UUID=test ro anduinos.btrfs_snapshots_manager=id\n"
        original = normal + recovery + "  initrd /recovery/initrd\n"
        for arch, tty in (("amd64", "ttyS0"), ("arm64", "ttyAMA0")):
            with self.subTest(arch=arch):
                changed = transform(original, arch)
                self.assertTrue(changed.startswith(normal))
                self.assertIn(f" console={tty},115200 systemd.mask=", changed)
                self.assertNotIn("debug_shell", changed)
                self.assertEqual(original, transform(changed, arch, restore=True))
                self.assertEqual(normal, transform(normal, arch, restore=True))

    def test_power_loss_observation_rejects_missing_ambiguous_or_modified_entry(self):
        transform = runpy.run_path(str(ROOT / "assertions/guest/recovery_power_loss.py"))["instrument"]
        recovery = " linux /kernel anduinos.btrfs_snapshots_manager=id\n"
        for content in ("", recovery * 2, recovery.rstrip() + " console=tty0\n",
                        recovery.rstrip() + " systemd.mask=anything.service\n"):
            with self.subTest(content=content), self.assertRaises(ValueError):
                transform(content, "amd64")
        with self.assertRaises(ValueError):
            transform(recovery, "other")

    def test_factory_round_progress_uses_the_declared_parent_suite(self):
        for round_name, repeated in (("factory-reset-repeat-preserve", True),
                                     ("factory-reset-repeat-erase", True),
                                     ("factory-reset-preserve-home", False)):
            with self.subTest(round=round_name), tempfile.TemporaryDirectory() as directory:
                artifacts = Path(directory)
                registered = "factory-reset-repeat" if repeated else round_name
                dashboard = AcceptanceDashboard(("base",), iso=Path("image.iso"),
                    architecture="amd64", artifacts=artifacts, stream=io.StringIO(), live=False,
                    suites={"base": {registered: ("recovery-check",)}})
                runner = object.__new__(FeatureSuiteRunner)
                runner.username, runner.password = "tester", "fixture-only"
                runner.driver = Mock()
                runner._prepare_power_control = Mock(return_value=Path("unused-key"))
                seen = []
                def phase(case, suite, description):
                    dashboard.suite_phase(case, suite, description)
                    seen.append(suite)
                    raise RuntimeError("stop before reboot")
                runner.phase_callback = phase
                vm = Mock()
                vm.serial.run.return_value = SimpleNamespace(stdout=(
                    'factory-workload={"version":"v","sha256":"hash"}\n'
                    'factory-root-id=root\nfactory-home-id=home\npersonal-snapshot-id=personal\n'))
                base = SimpleNamespace(scenario=SimpleNamespace(id="base"))
                with patch("business.desktop.lifecycle._run_with_qmp_key_requests",
                           return_value=SimpleNamespace(stdout="armed", returncode=0)), \
                     patch("business.desktop.lifecycle._retrieve_tree"), \
                     patch("business.desktop.lifecycle._retrieve_file"):
                    with self.assertRaisesRegex(RuntimeError, "stop before reboot"):
                        runner._exercise_factory_reset(vm, base, artifacts, suite_id=round_name,
                            erase_home=round_name.endswith("erase"), interrupt_after_apply=False,
                            workloads=[] if repeated else None)
                self.assertEqual([registered], seen)

    def test_localization_requires_sharing_readiness_before_action_cursor(self):
        for healthy in (True, False):
            with self.subTest(healthy=healthy):
                runner = object.__new__(FeatureSuiteRunner)
                runner._prepare_shell_fixture = Mock(return_value="/run/fixture")
                runner._stabilize_sharing_service = Mock(
                    side_effect=None if healthy else TestFailure("sharing not ready"))
                runner._journal_cursors = Mock(side_effect=RuntimeError("cursor reached"))
                order = Mock()
                order.attach_mock(runner._stabilize_sharing_service, "ready")
                order.attach_mock(runner._journal_cursors, "cursor")
                vm, artifacts = Mock(), Path("unused-artifacts")
                with self.assertRaisesRegex(RuntimeError if healthy else TestFailure,
                                            "cursor reached" if healthy else "sharing not ready"):
                    runner._run_shell_driver(vm, Mock(), artifacts,
                                             mode="localization-zh-cn", validator=Mock())
                runner._stabilize_sharing_service.assert_called_once_with(vm, artifacts)
                self.assertEqual(["ready", "cursor"] if healthy else ["ready"],
                                 [call[0] for call in order.mock_calls])

    def test_snapshot_rows_deduplicate_objects_not_titles(self):
        source = (ROOT / "assertions/guest/ui/files.py").read_text()
        node = next(node for node in ast.parse(source).body
                    if isinstance(node, ast.FunctionDef) and node.name == "_snapshot_rows")
        class Row:
            def __init__(self, title="baseline", kind="list item", visible=True):
                self.title, self.kind, self.visible = title, kind, visible
        first, second = Row(), Row()
        nodes = [first, first, Row(kind="label"), Row(visible=False), Row("other")]
        scope = dict(visible_nodes=lambda: nodes, name=lambda row: row.title,
                     role=lambda row: row.kind, showing=lambda row: row.visible)
        exec(compile(ast.Module(body=[node], type_ignores=[]), "snapshot-rows", "exec"), scope)
        self.assertEqual([first], scope["_snapshot_rows"]("baseline"))
        nodes.append(second)
        self.assertEqual([first, second], scope["_snapshot_rows"]("baseline"))

    def test_gnome_clocks_workload_removes_only_the_fixture_package(self):
        prepare = runpy.run_path(str(ROOT / "assertions/guest/factory_reset_workload.py"))["prepare"]
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            store = root / "store"
            baseline = store / "deployments/factory/root/usr/bin/gnome-clocks"
            baseline.parent.mkdir(parents=True)
            baseline.write_text("fixture gnome-clocks")
            current = root / "gnome-clocks"
            current.write_text("fixture gnome-clocks")
            home = root / "home/tester/workload"
            home.parent.mkdir(parents=True)

            def command(*args):
                if args == ("dpkg", "--remove", "gnome-clocks"):
                    current.unlink()
                    return "Removing gnome-clocks"
                if args[0] == "dpkg-query":
                    return "install ok installed" if "-f=${Status}" in args else "test-version"
                return ""

            commands = Mock(side_effect=command)
            def guest_path(value):
                return current if str(value) == "/usr/bin/gnome-clocks" else Path(value)

            with patch.dict(prepare.__globals__, STORE=store, Path=guest_path, run=commands,
                            shutil=SimpleNamespace(which=Mock(return_value=None)),
                            subprocess=SimpleNamespace(run=Mock(return_value=SimpleNamespace(stdout="")))), \
                 patch("os.chown"):
                workload = prepare(home, "factory")
            self.assertFalse(current.exists())
            self.assertEqual("test-version", workload["version"])
            commands.assert_any_call("dpkg", "--no-act", "--remove", "gnome-clocks")
            commands.assert_any_call("dpkg", "--remove", "gnome-clocks")
            calls = [call.args for call in commands.call_args_list]
            self.assertLess(calls.index(("dpkg", "--no-act", "--remove", "gnome-clocks")),
                            calls.index(("dpkg", "--remove", "gnome-clocks")))
            manager_query = ("dpkg-query", "-W", "-f=${Status}", "anduinos-btrfs-snapshots-manager")
            self.assertEqual(2, calls.count(manager_query))
            self.assertLess(calls.index(manager_query), calls.index(("dpkg", "--remove", "gnome-clocks")))
            self.assertEqual(manager_query, calls[-3])
            commands.assert_any_call("apt-get", "check")
            for call in commands.call_args_list:
                self.assertNotIn("--force-depends", call.args)
                self.assertNotIn("autoremove", call.args)
                if call.args[0] == "apt-get":
                    self.assertEqual(("apt-get", "check"), call.args)
            self.assertTrue(workload["files"])
            for path, content in workload["files"].items():
                self.assertEqual(content, Path(path).read_text())

    def test_gnome_clocks_dependency_conflict_stops_before_mutation(self):
        prepare = runpy.run_path(str(ROOT / "assertions/guest/factory_reset_workload.py"))["prepare"]
        def command(*args):
            if args == ("dpkg", "--no-act", "--remove", "gnome-clocks"):
                raise subprocess.CalledProcessError(1, args, "dependency conflict")
            return "install ok installed" if "-f=${Status}" in args else "test-version"
        commands = Mock(side_effect=command)
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory) / "untouched-home"
            with patch.dict(prepare.__globals__, run=commands, digest=lambda _: "checksum"):
                with self.assertRaises(subprocess.CalledProcessError):
                    prepare(home, "factory")
            self.assertFalse(home.exists())
        self.assertNotIn(("dpkg", "--remove", "gnome-clocks"),
                         [call.args for call in commands.call_args_list])

    def test_recovery_gui_launches_use_the_graphical_user_manager(self):
        for method in (FeatureSuiteRunner._exercise_btrfs_rollback,
                       FeatureSuiteRunner._exercise_factory_reset,
                       FeatureSuiteRunner._exercise_btrfs_home_rollback):
            with self.subTest(method=method.__name__):
                tree = ast.parse(textwrap.dedent(inspect.getsource(method)))
                calls = [node for node in ast.walk(tree) if isinstance(node, ast.Call)
                         and isinstance(node.func, ast.Name) and node.func.id == "_desktop_command"]
                self.assertEqual(1, len(calls))
                managed = next((item.value for item in calls[0].keywords
                                if item.arg == "managed"), None)
                self.assertIsInstance(managed, ast.Constant)
                self.assertIs(managed.value, True)

    def test_home_journey_uses_gui_and_real_boot_without_replacing_root(self):
        runner = object.__new__(FeatureSuiteRunner)
        runner.framework_root = ROOT
        runner.username, runner.password = "tester", "fixture-only"
        runner.options = SimpleNamespace(boot_timeout_seconds=60)
        runner.driver = Mock()
        runner._prepare_power_control = Mock(return_value=Path("control-key"))
        runner._wait_for_power_transition = Mock()
        runner._ssh_eventually = Mock(return_value="tester")
        runner._ssh = Mock(side_effect=lambda _vm, _key, command, **_: (
            "home-only-recovery=verified" if command.endswith(" verify") else "ok"))
        runner._login_home_gdm = Mock(return_value="tester\n")
        vm = Mock()
        vm.serial.run.return_value = SimpleNamespace(stdout="{}")
        order = Mock()
        order.attach_mock(runner._prepare_power_control, "control")
        order.attach_mock(vm.serial.run, "guest")
        order.attach_mock(vm.start, "start")
        order.attach_mock(runner._ssh, "ssh")
        order.attach_mock(runner._ssh_eventually, "eventually")
        order.attach_mock(runner._login_home_gdm, "login")
        with tempfile.TemporaryDirectory() as directory, \
             patch("business.desktop.home_recovery._run_with_qmp_key_requests",
                   return_value=SimpleNamespace(stdout="armed", returncode=0)) as gui, \
             patch("business.desktop.home_recovery._retrieve_tree"), \
             patch("business.desktop.home_recovery.time.sleep"):
            runner._exercise_btrfs_home_rollback(vm, object(), Path(directory))
        self.assertIn("home-restore-arm", gui.call_args.args[1])
        self.assertIn("systemd-run --user --wait --pipe", gui.call_args.args[1])
        self.assertNotIn(runner.password, gui.call_args.args[1])
        vm.start.assert_called_once_with(attach_iso=False, phase="home-rollback-apply")
        runner._login_home_gdm.assert_called_once_with(
            vm, Path("control-key"), timeout=60)
        calls = order.mock_calls
        control = next(i for i, call in enumerate(calls) if call[0] == "control")
        prepare = next(i for i, call in enumerate(calls)
                       if call[0] == "guest" and " prepare tester" in call.args[0])
        boot = next(i for i, call in enumerate(calls) if call[0] == "start")
        verify = next(i for i, call in enumerate(calls)
                      if call[0] == "ssh" and call.args[2].endswith(" verify"))
        login = next(i for i, call in enumerate(calls) if call[0] == "login")
        self.assertLess(control, prepare)
        self.assertLess(prepare, boot)
        self.assertLess(boot, verify)
        self.assertLess(login, verify)

    def test_home_gdm_login_retries_without_serial_console(self):
        runner = object.__new__(FeatureSuiteRunner)
        runner.username, runner.password = "tester", "fixture-only"
        runner._ssh = Mock(side_effect=["", "tester\n"])
        vm = Mock()
        with patch("business.desktop.home_recovery.time.sleep"):
            graphical = runner._login_home_gdm(vm, Path("key"), timeout=30)
        self.assertEqual("tester\n", graphical)
        self.assertEqual(2, runner._ssh.call_count)
        self.assertIn("loginctl list-sessions", runner._ssh.call_args.args[2])
        vm.qmp.type_text.assert_called_once_with("fixture-only", interval=0.06)
        self.assertEqual(2, vm.qmp.send_key.call_count)

    def test_factory_browsing_follows_real_desktop_login(self):
        source = inspect.getsource(FeatureSuiteRunner._exercise_factory_reset)
        self.assertLess(source.index("_login_gdm("), source.index('verify += " verify --workloads "'))

    def test_ghex_is_local_launch_and_store_suites_remain_real(self):
        self.assertIn("app.ghex-install", _LOCAL_ARCMENU_SEARCH_CHECKS)
        self.assertIn("public-ghex-install", _LOCAL_SEARCH_DRIVER_MODES)
        self.assertNotIn("public-ghex-install", _SOFTWARE_SEARCH_DRIVER_MODES)
        self.assertIn("shell-spotify-store", _SOFTWARE_SEARCH_DRIVER_MODES)
        self.assertNotIn("store.spotify-public", _LOCAL_ARCMENU_SEARCH_CHECKS)
        # Isolation runs before login and is asserted around each local probe.
        boot = inspect.getsource(FeatureSuiteRunner._boot_overlay)
        self.assertLess(boot.index("self._configure_local_search_provider_isolation("),
                        boot.index("_login_gdm("))

    def test_blocked_suite_is_not_a_product_failure_or_a_pass(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            dashboard = AcceptanceDashboard(("base",), iso=Path("image.iso"),
                architecture="amd64", artifacts=root, stream=io.StringIO(), live=False,
                suites={"base": {"recovery": ("home-check",)}})
            dashboard.begin("base")
            dashboard.complete("base", "failed", 1, "Logo not observed")
            blocked = _blocked_suite_result("recovery", "base", root, "Not run: base failed")
            dashboard.complete_suite("base", "recovery", blocked.status, 0, blocked.error)
            record = dashboard.suite_results("base")[0]
            self.assertEqual("blocked", record["status"])
            self.assertEqual("blocked", record["checks"][0]["status"])
            self.assertEqual(0, record["checks"][0]["seconds"])
            dashboard.color = False
            frame = render_dashboard(dashboard, os.terminal_size((160, 32)))
            self.assertIn("BLOCKED", frame)
            self.assertIn("✗ 1 · ⊘ 1", frame)
            self.assertTrue((blocked.artifacts / "blocked.txt").is_file())
            output = root / "junit.xml"
            write_junit_report({"feature_suites": [record]}, output)
            xml = ET.parse(output)
            self.assertEqual("0", xml.getroot().get("failures"))
            self.assertEqual("2", xml.getroot().get("errors"))
            self.assertEqual("BlockedByPrerequisite", xml.find(".//error").get("type"))

    def test_passive_boot_precedes_feature_instrumentation(self):
        source = inspect.getsource(InstallationPhases._run_target_phase)
        self.assertIn("prepare_overlay_base and not scenario.desktop_contracts", source)
        self.assertLess(source.index("self._assert_passive_plymouth_boot("),
                        source.index("self._prepare_feature_base_after_passive("))
        self.assertLess(source.index("if desktop_failures:"),
                        source.index("self._prepare_feature_base_after_passive("))

    def test_feature_preparation_mount_script_is_valid_and_separate(self):
        runner = object.__new__(InstallationPhases)
        runner.status = Mock()
        runner.architecture = Architecture.AMD64
        runner.defaults = object()
        runner._boot_live_session = Mock()
        runner._live_grub_entry = Mock(return_value=object())
        runner._assert_live_cleanup = Mock()
        vm = SimpleNamespace(serial=Mock())
        vm.serial.run.return_value = SimpleNamespace(stdout="prepared")
        scenario = SimpleNamespace(id="base", filesystem=SimpleNamespace(value="btrfs"))
        with tempfile.TemporaryDirectory() as directory, \
             patch("business.install.phases.scenario_live_region", return_value=object()), \
             patch("business.install.phases._power_off") as poweroff:
            runner._prepare_feature_base_after_passive(vm, scenario, Path(directory))
        script = vm.serial.run.call_args.args[0]
        result = subprocess.run(["bash", "-n"], input=script, text=True, capture_output=True)
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertIn('test "$(printf', script)
        self.assertIn("subvol=@root", script)
        self.assertIn("systemd.debug_shell=", script)
        self.assertEqual("feature-base-preparation", runner._boot_live_session.call_args.kwargs["phase"])
        poweroff.assert_called_once_with(vm)

    def test_missing_logo_remains_failure_and_preserves_last_frame(self):
        runner = object.__new__(JournalChecks)
        runner.status = Mock()
        runner.architecture = Architecture.AMD64
        runner.options = SimpleNamespace(boot_timeout_seconds=10)
        vm = Mock(running=True)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "plymouth-watermark.png").write_bytes(b"fixture")
            probe = root / "plymouth-probe.png"
            probe.write_bytes(b"last frame")
            vm.screenshot.return_value = probe
            with patch("business.install.journal.time.monotonic", side_effect=[0, 0, 1, 20]), \
                 patch("business.install.journal.time.sleep"), \
                 patch("business.install.journal.plymouth_match", return_value={"matched": False}):
                with self.assertRaisesRegex(TestFailure, "never displayed"):
                    runner._assert_passive_plymouth_boot(vm, SimpleNamespace(id="base"), root)
            self.assertEqual(b"last frame", (root / "plymouth-last-frame.png").read_bytes())
            self.assertFalse(json.loads((root / "plymouth-analysis.json").read_text())["matched"])
            vm.stop.assert_called_once()


class HomeOutcomeTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        root = Path(self.temporary.name)
        self.home = root / "home"
        self.folder = self.home / "tester/anduinos-acceptance-home-only"
        self.folder.mkdir(parents=True)
        for name in ("edited.txt", "deleted.txt"):
            (self.folder / name).write_text("baseline\n")
        self.store = root / "store"
        (self.store / "rollback-history").mkdir(parents=True)
        self.record = {"schema_version": 5, "home_only": True, "reset_home": True,
            "phase": "confirmed", "failure": None, "factory_home_snapshot_id": "target",
            "fallback_home_snapshot_id": "safety"}
        self.history = self.store / "rollback-history/record.json"
        self.history.write_text(json.dumps(self.record))
        for identifier, filename, text in (("target", "deleted.txt", "baseline\n"),
                                          ("safety", "new.txt", "new user data\n")):
            saved = self.store / "personal/snapshots" / identifier / "home" / self.folder.relative_to(self.home)
            saved.mkdir(parents=True)
            (saved / filename).write_text(text)
        marker = root / "system-marker"
        marker.write_text("system change must survive\n")
        boot = root / "boot-id"
        boot.write_text("new-boot")
        state = root / "state.json"
        state.write_text(json.dumps({"user": "tester", "folder": str(self.folder), "target": "target",
            "root_uuid": "same-root", "dpkg": "unchanged", "boot_id": "previous-boot",
            "uid": os.getuid(), "gid": os.getgid()}))
        self.verify = runpy.run_path(str(ROOT / "assertions/guest/home_rollback_workload.py"))["verify"]
        self.commands = Mock(return_value='[{"name":"deleted.txt"},{"name":"new.txt"}]')
        self.environment = {"HOME": self.home, "STORE": self.store, "STATE": state,
            "MARKER": marker, "BOOT_ID": boot, "root_uuid": lambda: "same-root",
            "digest": lambda _: "unchanged", "run": self.commands}

    def check(self):
        with patch.dict(self.verify.__globals__, self.environment), patch("sys.stdout", new_callable=io.StringIO):
            self.verify()

    def test_healthy_home_recovery_checks_both_histories_as_owner(self):
        self.check()
        self.assertEqual(2, self.commands.call_count)
        self.assertEqual(("runuser", "-u", "tester", "--"), self.commands.call_args.args[:4])
        self.assertIn("systemd-run", self.commands.call_args.args)
        self.assertIn(f"XDG_RUNTIME_DIR=/run/user/{os.getuid()}", self.commands.call_args.args)

    def test_system_rollback_is_not_mistaken_for_home_only(self):
        self.environment["root_uuid"] = lambda: "replaced-root"
        with self.assertRaisesRegex(RuntimeError, "replaced the system"):
            self.check()

    def test_missing_reboot_is_rejected(self):
        self.environment["BOOT_ID"].write_text("previous-boot")
        with self.assertRaisesRegex(RuntimeError, "did not reboot"):
            self.check()

    def test_changed_packages_are_rejected(self):
        self.environment["digest"] = lambda _: "different"
        with self.assertRaisesRegex(RuntimeError, "Package database"):
            self.check()

    def test_leftover_current_file_is_rejected(self):
        (self.folder / "new.txt").touch()
        with self.assertRaisesRegex(RuntimeError, "survived rollback"):
            self.check()

    def test_history_must_be_browsable_not_just_present(self):
        self.commands.return_value = "[]"
        with self.assertRaisesRegex(RuntimeError, "not browsable"):
            self.check()

    def test_failed_or_wrong_scope_transaction_is_rejected(self):
        for change in ({"home_only": False}, {"phase": "reverted"}, {"failure": "failed"},
                       {"fallback_home_snapshot_id": None}):
            with self.subTest(change=change):
                self.history.write_text(json.dumps(self.record | change))
                with self.assertRaises(RuntimeError):
                    self.check()
