"""Coexistence must fail closed, including wrong-root and firmware fallback."""

import copy
import importlib.util
import json
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from types import ModuleType, SimpleNamespace
from unittest.mock import Mock, patch

from assertions.coexistence import (
    assert_preserved, installation_parts, parse_snapshot, validate_boot_identity,
    validate_rejection_events, vendor_entry,
)
from business.install import ScenarioRunner, scenario_check_ids
from business.install.coexistence import (
    chainload_selection_script, coexistence_check_ids, mounted_root_script,
)
from framework.errors import ConfigurationError, TestFailure
from framework.model import Architecture, StorageMode, TestMatrix, _load_scenario
from framework.serial import CommandResult
from framework.storage import DiskStorage


ROOT = Path(__file__).parents[1]


def partition(number, fstype, size_gib, fs_uuid):
    return {
        "path": f"/dev/vda{number}", "uuid": fs_uuid,
        "partuuid": f"00000000-0000-4000-8000-{number:012d}", "fstype": fstype,
        "sha256": "a" * 64,
        "geometry": {"node": f"/dev/vda{number}", "start": number * 2048,
                     "size": size_gib * 1024**3 // 512},
    }


def snapshot():
    parts = [partition(1, "vfat", 1, "AAAA-0001"),
             partition(2, "btrfs", 50, "00000000-0000-4000-8000-100000000002"),
             partition(3, "swap", 3, "00000000-0000-4000-8000-100000000003")]
    return {"partitions": parts, "table": {"sectorsize": 512, "partitions": [p["geometry"] for p in parts]},
            "gpt_head": "head", "gpt_tail": "tail",
            "nvram": "BootCurrent: 0001\nBootOrder: 0001,0000\n" + entry("0001", parts[0])}


def entry(number, esp):
    return f"Boot{number}* AnduinOS\tHD(1,GPT,{esp['partuuid']},0x800,0x200000)/File(\\EFI\\AnduinOS\\shimx64.efi)\n"


def second_install(first):
    result = copy.deepcopy(first)
    added = [partition(4, "vfat", 1, "BBBB-0002"),
             partition(5, "btrfs", 50, "00000000-0000-4000-8000-100000000005"),
             partition(6, "swap", 3, "00000000-0000-4000-8000-100000000006")]
    result["partitions"].extend(added)
    result["table"]["partitions"].extend(p["geometry"] for p in added)
    result.update(gpt_head="changed-head", gpt_tail="changed-tail")
    result["nvram"] = first["nvram"].replace("BootOrder: 0001,0000", "BootOrder: 0002,0001,0000") + entry("0002", added[0])
    return result


class CoexistenceOracleTests(unittest.TestCase):
    def test_shared_rejection_requires_dialog_disabled_next_and_no_advance(self):
        good = [{"event": "coexistence-esp-conflict-dialog"},
                {"event": "coexistence-esp-rejected", "next_enabled": False, "stage": "advanced-storage"}]
        render = lambda events: "\n".join(json.dumps(item) for item in events)
        validate_rejection_events(render(good))
        bad = [[], good[:1], good[1:], good * 2,
               [good[0], {**good[1], "next_enabled": True}],
               [good[0], {**good[1], "stage": "user"}],
               good + [{"event": "installation-complete"}],
               good + [{"event": "page", "page": "user"}],
               good + [{"event": "page", "page": "progress"}]]
        for events in bad:
            with self.subTest(events=events), self.assertRaises(TestFailure):
                validate_rejection_events(render(events))

    def test_rejected_plan_preserves_partition_bytes_gpt_and_nvram(self):
        before = snapshot()
        assert_preserved(before, copy.deepcopy(before), rejected=True)
        faults = (
            lambda v: v["partitions"].pop(),
            lambda v: v["partitions"][0].update(sha256="b" * 64),
            lambda v: v["partitions"][1].update(sha256="b" * 64),
            lambda v: v["partitions"][2].update(sha256="b" * 64),
            lambda v: v["partitions"][1]["geometry"].update(size=1),
            lambda v: v["partitions"][1].update(uuid="wrong"),
            lambda v: v.update(gpt_head="changed"),
            lambda v: v.update(gpt_tail="changed"),
            lambda v: v.update(nvram=v["nvram"].replace("BootOrder: 0001,0000", "BootOrder: 0000,0001")),
        )
        for fault in faults:
            changed = copy.deepcopy(before)
            fault(changed)
            with self.subTest(after=changed), self.assertRaises(TestFailure):
                assert_preserved(before, changed, rejected=True)
        missing = copy.deepcopy(before)
        missing["partitions"][0]["sha256"] = None
        with self.assertRaises(TestFailure):
            assert_preserved(missing, missing, rejected=True)

    def test_independent_allows_only_new_partitions_and_new_firmware_entry(self):
        before = snapshot()
        after = second_install(before)
        assert_preserved(before, after, rejected=False)
        a = installation_parts(before)
        b = installation_parts(after, excluded=[p["path"] for p in before["partitions"]])
        self.assertNotEqual(a["vfat"]["uuid"], b["vfat"]["uuid"])
        self.assertEqual("0002", vendor_entry(after["nvram"], b["vfat"]))
        after["nvram"] = after["nvram"].replace(entry("0001", a["vfat"]), "")
        with self.assertRaises(TestFailure):
            assert_preserved(before, after, rejected=False)

    def test_independent_rejects_deactivated_or_unscheduled_original_entry(self):
        before = snapshot()
        good = second_install(before)
        for old, new in (
            ("Boot0001* AnduinOS", "Boot0001  AnduinOS"),
            ("BootOrder: 0002,0001,0000", "BootOrder: 0002,0000"),
            ("BootOrder: 0002,0001,0000", "BootOrder: 0002,0000,0001"),
            ("BootOrder: 0002,0001,0000", "BootOrder: 0002,0001,0001,0000"),
            ("BootOrder: 0002,0001,0000", "BootOrder: invalid"),
            ("BootOrder: 0002,0001,0000\n", ""),
        ):
            bad = copy.deepcopy(good)
            bad["nvram"] = bad["nvram"].replace(old, new)
            with self.subTest(mutation=new), self.assertRaises(TestFailure):
                assert_preserved(before, bad, rejected=False)

    def test_vendor_entry_must_be_active_and_unambiguous(self):
        evidence = snapshot()
        esp = evidence["partitions"][0]
        for nvram in (
            evidence["nvram"].replace("Boot0001*", "Boot0001 "),
            evidence["nvram"] + entry("0001", esp),
        ):
            with self.subTest(nvram=nvram), self.assertRaises(TestFailure):
                vendor_entry(nvram, esp)

    def test_snapshot_rejects_missing_duplicate_and_ambiguous_evidence(self):
        before = snapshot()
        encode = lambda value: "COEXISTENCE_JSON=" + json.dumps(value)
        self.assertEqual(before, parse_snapshot(encode(before)))
        for key in ("uuid", "partuuid", "path"):
            for value in (None, before["partitions"][0][key]):
                bad = copy.deepcopy(before)
                bad["partitions"][1][key] = value
                with self.subTest(key=key, value=value), self.assertRaises(TestFailure):
                    parse_snapshot(encode(bad))
        for output in ("", encode(before) + "\n" + encode(before)):
            with self.assertRaises(TestFailure):
                parse_snapshot(output)

    def test_layout_cannot_consume_the_spare_space_or_omit_swap(self):
        before = snapshot()
        installation_parts(before)
        for index in (0, 1):
            bad = copy.deepcopy(before)
            bad["partitions"][index]["geometry"]["size"] += 2048
            with self.assertRaises(TestFailure):
                installation_parts(bad)
        before["partitions"].pop()
        with self.assertRaises(TestFailure):
            installation_parts(before)

    def test_chain_boot_requires_a_root_and_esp_but_b_bootcurrent(self):
        initial = snapshot()
        both = second_install(initial)
        a = installation_parts(initial)
        b = installation_parts(both, excluded=[p["path"] for p in initial["partitions"]])
        output = (f"ROOT_UUID={a['btrfs']['uuid']}\nESP_UUID={a['vfat']['uuid']}\nHOSTNAME=test-a\n"
                  + both["nvram"].replace("BootCurrent: 0001", "BootCurrent: 0002"))
        validate_boot_identity(output, a["btrfs"], a["vfat"], "test-a", b["vfat"])
        for bad in (output.replace("BootCurrent: 0002", "BootCurrent: 0001"),
                    output.replace(a["btrfs"]["uuid"], b["btrfs"]["uuid"]),
                    output.replace("ESP_UUID=AAAA-0001", "ESP_UUID=BBBB-0002"),
                    output.replace("HOSTNAME=test-a", "HOSTNAME=test-b"),
                    output + "ROOT_UUID=unexpected\n"):
            with self.subTest(output=bad), self.assertRaises(TestFailure):
                validate_boot_identity(bad, a["btrfs"], a["vfat"], "test-a", b["vfat"])

    def test_generated_shell_and_one_shot_selection_use_real_entry(self):
        a = installation_parts(snapshot())
        selection = chainload_selection_script(a)
        self.assertIn("next_entry=AnduinOS (other installation)", selection)
        self.assertNotIn("efibootmgr -n", selection)
        self.assertNotIn("linux /", selection)
        self.assertIn("43_anduinos_linux", selection)
        script = mounted_root_script(a["btrfs"], selection)
        result = subprocess.run(("bash", "-n"), input=script, text=True, capture_output=True)
        self.assertEqual(0, result.returncode, result.stderr)
        with self.assertRaises(TestFailure):
            mounted_root_script({"uuid": "$(unsafe)"}, "true")
        a["vfat"]["uuid"] = "';unsafe"
        with self.assertRaises(TestFailure):
            chainload_selection_script(a)


class CoexistenceWiringTests(unittest.TestCase):
    def setUp(self):
        self.matrix = TestMatrix.load(ROOT / "cases/install.json")
        self.cases = [s for s in self.matrix.scenarios if s.storage_mode.coexistence]

    def test_default_matrix_includes_both_modes_and_all_checks_are_unique(self):
        self.assertEqual(2, len(self.cases))
        for case in self.cases:
            self.assertIn(case, self.matrix.select(Architecture.AMD64))
            self.assertEqual(112, case.disk_gib)
            checks = scenario_check_ids(case)
            self.assertEqual(len(checks), len(set(checks)))
            self.assertIn("installed-contracts", checks)
            self.assertIn("coexistence.a-preserved", checks)

    def test_unsupported_matrix_combinations_are_rejected(self):
        raw = json.loads((ROOT / "cases/install.json").read_text())
        case = next(c for c in raw["cases"] if c.get("storage_mode") == "coexistence-shared-esp")
        for mutation in ({"disk_gib": 50}, {"architectures": ["arm64"]}, {"network": "online"},
                         {"live_mode": "persistent"}, {"automatic_login": True},
                         {"filesystem": "ext4", "snapshots_manager": False}):
            with self.subTest(mutation=mutation), self.assertRaises(ConfigurationError):
                _load_scenario({**case, **mutation})

    def test_two_installs_do_not_raise_or_inherit_single_install_ram_limit(self):
        runner = ScenarioRunner.__new__(ScenarioRunner)
        ramdisk = DiskStorage(Path("/example/ramdisk"), "ramdisk", "unit", qcow_limit_bytes=12 * 1024**3)
        runner.options = SimpleNamespace(disk_storage=ramdisk, artifacts_root=Path("/example/results"))
        for case in self.cases:
            storage = runner._scenario_disk_storage(case)
            self.assertFalse(storage.is_ramdisk)
            self.assertEqual(Path("/example/results"), storage.root)
            self.assertIsNone(storage.qcow_limit_bytes)
        normal = next(s for s in self.matrix.scenarios if not s.storage_mode.coexistence)
        self.assertIs(ramdisk, runner._scenario_disk_storage(normal))

    def test_both_workflows_execute_all_declared_checks(self):
        for scenario in self.cases:
            with self.subTest(scenario=scenario.id), tempfile.TemporaryDirectory() as temporary:
                runner = ScenarioRunner.__new__(ScenarioRunner)
                runner.defaults = self.matrix.defaults
                runner.check_status = None
                runner._check_details = {}
                runner._check_states = {scenario.id: dict.fromkeys(scenario_check_ids(scenario), "pending")}
                first = snapshot()
                shared = scenario.storage_mode is StorageMode.COEXISTENCE_SHARED_ESP
                after = copy.deepcopy(first) if shared else second_install(first)
                initial = copy.deepcopy(first)
                for part in initial["partitions"]:
                    part["sha256"] = None
                runner._coexistence_snapshot = Mock(side_effect=[initial, first, after])
                def baseline(*_args, **_kwargs):
                    for check in scenario_check_ids(scenario):
                        if check not in coexistence_check_ids(scenario) or check == "coexistence.package-versions":
                            runner._emit_check(scenario.id, check, "passed", "baseline mock")
                    return object()
                runner._run_live_phase = Mock(side_effect=baseline)
                runner._run_target_phase = Mock()
                runner._coexistence_live = Mock()
                runner._run_installer_driver = Mock()
                runner._coexistence_arm = Mock()
                runner._coexistence_boot = Mock()
                runner._assert_live_cleanup = Mock()
                vm = Mock()
                vm.serial.run.return_value = CommandResult("chainload selection", 0)
                with patch("business.install.coexistence._power_off"):
                    runner._run_coexistence(vm, scenario, Path(temporary))
                runner._assert_check_completion(scenario)
                self.assertEqual({"coexistence_stage": "a"}, runner._run_live_phase.call_args.kwargs["config_overrides"])
                expected = "b-shared" if shared else "b-separate"
                self.assertEqual(expected, runner._run_installer_driver.call_args.kwargs["config_overrides"]["coexistence_stage"])
                self.assertEqual(1 if shared else 2, runner._coexistence_boot.call_count)
                last = runner._coexistence_boot.call_args.args
                self.assertEqual(first["partitions"][0]["uuid"], last[1]["vfat"]["uuid"])
                self.assertEqual("AAAA-0001" if shared else "BBBB-0002", last[2]["uuid"])

    def test_older_iso_fails_with_recorded_package_versions(self):
        runner = ScenarioRunner.__new__(ScenarioRunner)
        vm = Mock()
        vm.serial.run.return_value = CommandResult("installer=2.0.4-1\ntoolkit=2.0.4-1", 1)
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary)
            with self.assertRaisesRegex(TestFailure, "rebuild the ISO"):
                runner._assert_coexistence_versions(vm, path)
            self.assertIn("installer=2.0.4-1", (path / "package-versions.txt").read_text())


class CoexistenceProbeTests(unittest.TestCase):
    def test_guest_probe_records_gpt_geometry_without_sfdisk(self):
        spec = importlib.util.spec_from_file_location("coexistence_probe", ROOT / "assertions/guest/coexistence_probe.py")
        probe = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(probe)
        tree = {"blockdevices": [{
            "name": "/dev/vda", "serial": "ANDUINOS-TEST-TARGET",
            "children": [{
                "name": "/dev/vda1", "type": "part", "uuid": "ABCD-1234",
                "partuuid": "11111111-1111-1111-1111-111111111111",
                "parttype": "c12a7328-f81f-11d2-ba4b-00a0c93ec93b",
                "fstype": "vfat", "mountpoints": [None],
            }],
        }]}
        def command(*args):
            if args[0] == "lsblk" and "-Jbp" in args:
                return json.dumps(tree)
            if args[0] == "lsblk":
                return "gpt 22222222-2222-2222-2222-222222222222"
            if args[:2] == ("blockdev", "--getss"):
                return "512"
            if args[:2] == ("blockdev", "--getsize64"):
                return str(4 * 1024**3)
            if args[0] == "efibootmgr":
                return "BootOrder: 0001"
            raise AssertionError(f"Unexpected command: {args}")

        with patch.object(probe, "output", side_effect=command), patch.object(
            probe.Path, "read_text", side_effect=["2048", "2097152"]
        ), patch.object(probe, "digest", return_value="a" * 64):
            result = probe.snapshot(())
        self.assertEqual(2048, result["partitions"][0]["geometry"]["start"])
        self.assertEqual(2097152, result["partitions"][0]["geometry"]["size"])
        self.assertEqual(result["partitions"][0]["geometry"], result["table"]["partitions"][0])

    def test_guest_probe_rejects_a_foreign_disk_before_reading_bytes(self):
        spec = importlib.util.spec_from_file_location("coexistence_probe", ROOT / "assertions/guest/coexistence_probe.py")
        probe = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(probe)
        for tree in ({"serial": "OTHER-DISK"}, {"serial": "ANDUINOS-TEST-TARGET", "children": [{"mountpoints": ["/target"]}]}):
            with self.subTest(tree=tree), patch.object(probe, "output", return_value=json.dumps({"blockdevices": [tree]})), patch.object(probe, "digest") as digest:
                with self.assertRaises(RuntimeError):
                    probe.snapshot(())
                digest.assert_not_called()


class CoexistenceUiTests(unittest.TestCase):
    def setUp(self):
        # Load the real UI flow with just the AT-SPI transport replaced; no
        # host GTK session and no duplicated implementation of its branches.
        core = ModuleType("test_guest_ui.core")
        core.Path = Path
        core.re = re
        core.Atspi = SimpleNamespace(StateType=SimpleNamespace(EXPANDED="expanded"))
        core.name = lambda node: node.text
        core.role = lambda node: node.kind
        core.showing = lambda node: node.visible
        core.children = lambda node: node.kids
        core.has_state = lambda node, state: node.expanded
        # Advance virtual time so failure-path UI waits are instantaneous.
        core.time = SimpleNamespace(monotonic=Mock(side_effect=range(1000)), sleep=Mock())
        core.UiFailure = TestFailure
        for method in ("set_toggle", "click", "set_numeric_value", "click_button",
                       "dump_accessibility", "find", "event", "control",
                       "request_dialog_focused_activation", "wait_absent"):
            setattr(core, method, Mock())
        core.enabled = Mock(return_value=False)
        core.find_optional = Mock(return_value=None)
        installer = ModuleType("test_guest_ui.installer")
        installer.wait_page = Mock()
        self.module_patch = patch.dict(sys.modules, {
            "test_guest_ui.core": core, "test_guest_ui.installer": installer,
        })
        self.module_patch.start()
        self.addCleanup(self.module_patch.stop)
        spec = importlib.util.spec_from_file_location(
            "test_guest_ui.coexistence", ROOT / "assertions/guest/ui/coexistence.py",
        )
        self.ui = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.ui)
        self.select_new_esp = self.ui.select_new_esp
        self.ui.selected_esp_dropdown = Mock()
        self.ui.select_new_esp = Mock()
        self.core = core
        self.installer = installer

    def configure(self, stage):
        return self.ui.configure_coexistence(
            {"coexistence_stage": stage, "existing_esp_path": "/dev/vda1"}, Path("/evidence"),
        )

    def test_a_initializes_once_and_leaves_room_after_manual_layout(self):
        self.assertTrue(self.configure("a"))
        self.core.click.assert_any_call("initialize_gpt")
        self.core.click.assert_any_call("confirm_initialize_gpt")
        self.assertEqual([1024, 51200, 3072], [c.args[1] for c in self.core.set_numeric_value.call_args_list])
        self.installer.wait_page.assert_called_with("user")

    def test_b_independent_preserves_table_and_selects_a_new_esp(self):
        self.assertTrue(self.configure("b-separate"))
        self.assertNotIn("initialize_gpt", [c.args[0] for c in self.core.click.call_args_list])
        self.ui.select_new_esp.assert_called_once_with("/dev/vda1")
        self.assertEqual([1024, 51200, 3072], [c.args[1] for c in self.core.set_numeric_value.call_args_list])
        self.installer.wait_page.assert_called_with("user")

    def test_b_shared_does_not_create_esp_or_proceed_to_install(self):
        self.assertFalse(self.configure("b-shared"))
        self.assertNotIn("initialize_gpt", [c.args[0] for c in self.core.click.call_args_list])
        self.ui.select_new_esp.assert_not_called()
        self.assertEqual([51200, 3072], [c.args[1] for c in self.core.set_numeric_value.call_args_list])
        self.core.find.assert_any_call("separate_esp_required", timeout=90)
        self.installer.wait_page.assert_called_with("advanced_storage")

    def test_missing_rejection_dialog_fails(self):
        def find(key, **_kwargs):
            if key == "separate_esp_required":
                raise TestFailure("No rejection dialog")
        self.core.find.side_effect = find
        with self.assertRaisesRegex(TestFailure, "No rejection"):
            self.configure("b-shared")

    def test_enabled_next_after_rejection_fails(self):
        self.core.enabled.return_value = True
        with self.assertRaisesRegex(TestFailure, "Next remains enabled"):
            self.configure("b-shared")

    def test_unexpected_user_page_after_rejection_fails(self):
        self.core.find_optional.return_value = object()
        with self.assertRaisesRegex(TestFailure, "advanced past"):
            self.configure("b-shared")

    def test_unknown_stage_cannot_initialize_a_disk(self):
        with self.assertRaises(TestFailure):
            self.configure("unknown")
        self.core.click.assert_not_called()

    @staticmethod
    def node(text="", kind="label", *, kids=(), visible=True, expanded=False):
        return SimpleNamespace(text=text, kind=kind, kids=kids, visible=visible, expanded=expanded)

    def test_dropdown_display_ignores_hidden_options_and_rejects_open_popup(self):
        choice = self.node("Create a new ESP partition")
        old = self.node("Reuse /dev/vda1 (1 GiB)")
        combo = self.node(kind="combo box", kids=(old, self.node(kids=(choice,), visible=False)))
        self.assertEqual((old.text,), self.ui.dropdown_display_text(combo))
        combo.kids = (choice,)
        self.assertEqual((choice.text,), self.ui.dropdown_display_text(combo))
        combo.expanded = True
        self.assertEqual((), self.ui.dropdown_display_text(combo))
        combo.expanded = False
        combo.kids = (choice, self.node(kind="list box", kids=(choice,)))
        self.assertEqual((), self.ui.dropdown_display_text(combo))
