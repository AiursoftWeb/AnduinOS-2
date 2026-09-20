"""Public Flatpak installation and GHex desktop-launch contracts."""

import ast
import copy
import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

from assertions.desktop.system import _ghex_install_command, _validate_ghex_install_evidence
from assertions.desktop.applications import _validate_ghex_install_events
from framework.errors import TestFailure
from business.desktop.applications import PublicApplicationChecks


APP = "org.gnome.GHex"
ROOT = Path(__file__).resolve().parents[1]


class GhexAcceptanceTests(unittest.TestCase):
    def test_launch_and_post_launch_failures_remain_failures_but_are_distinguished(self):
        for stage in ("launch", "invalid-evidence", "post-launch"):
            with self.subTest(stage=stage), tempfile.TemporaryDirectory() as directory:
                runner, vm = PublicApplicationChecks(), Mock()
                vm.serial.run.return_value = SimpleNamespace(
                    stdout=self.evidence(self.installation()), returncode=0)
                def driver(*args, **kwargs):
                    if stage == "launch":
                        raise TestFailure("window absent")
                    events = self.events()
                    if stage == "invalid-evidence":
                        events[-1]["windows"] = []
                    kwargs["validator"](self.event_text(events))
                    raise TestFailure("journal blocker")
                runner._run_shell_driver = Mock(side_effect=driver)
                with self.assertRaises(TestFailure):
                    runner._exercise_ghex_install(vm, Mock(), Path(directory))
                phase = "post-launch" if stage == "post-launch" else "launch"
                self.assertEqual(f"classification={phase}-check-failed\nphase={phase}\n",
                                 (Path(directory) / "ghex-classification.txt").read_text())

    def test_flatpak_ps_accepts_omitted_trailing_status_columns(self):
        source = ROOT / "assertions/guest/ui/applications.py"
        tree = ast.parse(source.read_text())
        function = next(item for item in tree.body if isinstance(item, ast.FunctionDef)
                        and item.name == "_flatpak_instances")
        process = Mock()
        namespace = dict(os=os, subprocess=process, UiFailure=RuntimeError)
        exec(compile(ast.Module(body=[function], type_ignores=[]), str(source), "exec"), namespace)
        identity = f"123\t200\t201\t{APP}\tx86_64\tstable"
        for suffix, active, background in (("", "", ""), ("\t🗸", "🗸", ""),
                                           ("\t\t🗸", "", "🗸"), ("\t\t", "", "")):
            with self.subTest(suffix=suffix):
                process.run.return_value = SimpleNamespace(returncode=0, stdout=identity + suffix + "\n")
                instances = namespace["_flatpak_instances"](APP)
                self.assertEqual([dict(instance="123", pid=200, child_pid=201,
                                       application=APP, arch="x86_64", branch="stable",
                                       active=active, background=background)], instances)
        for output in ("", identity.replace(APP, "org.example.Other"),
                       identity.rsplit("\t", 1)[0], identity + "\ta\tb\textra"):
            with self.subTest(output=output):
                process.run.return_value = SimpleNamespace(returncode=0, stdout=output)
                self.assertEqual([], namespace["_flatpak_instances"](APP))
        process.run.return_value = SimpleNamespace(returncode=0, stdout=identity.replace("\t200\t", "\tbad\t"))
        with self.assertRaisesRegex(RuntimeError, "malformed PIDs"):
            namespace["_flatpak_instances"](APP)
        process.run.return_value = SimpleNamespace(returncode=1, stdout="enumeration failed")
        with self.assertRaisesRegex(RuntimeError, "Could not enumerate"):
            namespace["_flatpak_instances"](APP)

    def installation(self):
        digest = "a" * 64
        ref = f"app/{APP}/x86_64/stable"
        location = f"/var/lib/flatpak/{ref}/{digest}"
        fields = {
            "preinstalled": "no", "remote-count": "1",
            "remote-url": "https://dl.flathub.org/repo/", "remote-ref": ref,
            "remote-commit": digest, "install-command": "passed",
            "installed-ref": ref, "installed-commit": digest,
            "installed-origin": "flathub", "installed-location": location,
            "desktop": f"/var/lib/flatpak/exports/share/applications/{APP}.desktop",
            "desktop-resolved": f"{location}/export/share/applications/{APP}.desktop",
            "app-id": APP, "arch": "x86_64", "failure-class": "none",
            "install": "current-and-verified", "installed-version": "50.3",
        }
        return fields

    @staticmethod
    def evidence(fields):
        return "\n".join(f"ghex-{key}={value}" for key, value in fields.items())

    def test_fresh_installation_verifies_identity_commit_and_launcher(self):
        fields = self.installation()
        result = _validate_ghex_install_evidence(self.evidence(fields), 0)
        self.assertEqual("a" * 64, result["commit"])
        self.assertEqual("50.3", result["version"])
        for key, value in (
            ("preinstalled", "yes"), ("installed-origin", "other"),
            ("installed-ref", "app/com.tencent.WeChat/x86_64/stable"),
            ("installed-commit", "b" * 64), ("arch", "aarch64"),
            ("desktop-resolved", f"/tmp/export/share/applications/{APP}.desktop"),
        ):
            with self.subTest(key=key), self.assertRaises(TestFailure):
                _validate_ghex_install_evidence(self.evidence({**fields, key: value}), 0)
        with self.assertRaises(TestFailure):
            _validate_ghex_install_evidence(self.evidence({**fields, "installed-version": ""}), 0)
        with self.assertRaises(TestFailure):
            _validate_ghex_install_evidence(self.evidence(fields), 90)

    def test_installer_does_not_repair_sources_or_substitute_a_deb(self):
        command = _ghex_install_command()
        result = subprocess.run(["bash", "-n"], input=command, text=True, capture_output=True)
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertIn(APP, command)
        self.assertIn("flatpak install --system --noninteractive", command)
        self.assertIn("installed-commit-mismatch", command)
        self.assertNotIn("com.tencent.WeChat", command)
        self.assertNotIn("remote-add", command)
        self.assertNotIn("apt install", command)

    def events(self):
        return [
            dict(event="ghex-launch-baseline", running=False),
            dict(event="qmp-key", request="ghex-search-open", key="meta_l"),
            dict(event="qmp-text", request="ghex-search-text"),
            dict(event="start-search-result", query="GHex", accessible_name="GHex",
                 application="gnome-shell", stable_observations=4),
            dict(event="search-entry-focus", query="GHex", application="gnome-shell", focused=True),
            dict(event="qmp-key", request="ghex-result-activate", key="ret"),
            dict(event="ghex-installed-launched", application=APP, search_result="GHex",
                 activation_method="qmp-keyboard", observation="atspi+flatpak", visible=True,
                 stable_observations=4,
                 windows=[dict(title="GHex", role="frame", application="ghex",
                               visible=True, bounds=[10, 10, 800, 600], controls=8)],
                 flatpak_instances=[dict(instance="123", application=APP, arch="x86_64",
                                        branch="stable", pid=200, child_pid=201)]),
        ]

    @staticmethod
    def event_text(events):
        return "\n".join(json.dumps(event) for event in events)

    def test_real_menu_launch_requires_window_and_flatpak(self):
        events = self.events()
        _validate_ghex_install_events(self.event_text(events))
        for field, value in (("windows", []), ("flatpak_instances", []),
                             ("visible", False), ("stable_observations", 1),
                             ("activation_method", "command-line")):
            broken = copy.deepcopy(events)
            broken[-1][field] = value
            with self.subTest(field=field), self.assertRaises(TestFailure):
                _validate_ghex_install_events(self.event_text(broken))
        for title in ("GHex Error", "GHex failed", "GHex 错误"):
            broken = copy.deepcopy(events)
            broken[-1]["windows"][0]["title"] = title
            with self.subTest(title=title), self.assertRaises(TestFailure):
                _validate_ghex_install_events(self.event_text(broken))
        for value in ("com.tencent.WeChat", "org.gnome.TextEditor"):
            broken = copy.deepcopy(events)
            broken[-1]["flatpak_instances"][0]["application"] = value
            with self.assertRaises(TestFailure):
                _validate_ghex_install_events(self.event_text(broken))
        with self.assertRaises(TestFailure):
            _validate_ghex_install_events(self.event_text(events[1:] + events[:1]))

    def test_guest_waits_for_stable_window_and_instance(self):
        source = ROOT / "assertions/guest/ui/applications.py"
        tree = ast.parse(source.read_text())
        function = next(item for item in tree.body if isinstance(item, ast.FunctionDef)
                        and item.name == "exercise_ghex_install")
        window = self.events()[-1]["windows"]
        instance = self.events()[-1]["flatpak_instances"]
        clock = iter(range(200))
        namespace = dict(
            Path=Path, UiFailure=RuntimeError,
            time=SimpleNamespace(monotonic=lambda: next(clock), sleep=Mock()),
            dismiss_initial_setup=Mock(), _ghex_windows=Mock(side_effect=[[], [], window, window, window, window]),
            _flatpak_instances=Mock(side_effect=[[], [], instance, instance, instance, instance]),
            _open_arcmenu_search=Mock(return_value=(object(), object(), object())),
            name=Mock(return_value="GHex"), event=Mock(), dump_accessibility=Mock(),
        )
        exec(compile(ast.Module(body=[function], type_ignores=[]), str(source), "exec"), namespace)
        namespace["exercise_ghex_install"](Path("/unused-test-evidence"))
        self.assertEqual(4, namespace["event"].call_args.kwargs["stable_observations"])
        namespace["_ghex_windows"] = Mock(return_value=[])
        namespace["_flatpak_instances"] = Mock(return_value=[])
        namespace["time"] = SimpleNamespace(monotonic=lambda: next(clock), sleep=Mock())
        with self.assertRaisesRegex(RuntimeError, "stable window"):
            namespace["exercise_ghex_install"](Path("/unused-test-evidence"))
