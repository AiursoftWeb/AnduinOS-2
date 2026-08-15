"""Regression tests for balanced, fail-closed journal classification."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from iso_test.errors import ConfigurationError, TestFailure
from iso_test.journal import (
    JournalEntry,
    JournalPolicy,
    merge_journal_entries,
    parse_journal_jsonl,
    render_guest_collection_script,
    render_verdict,
)
from iso_test.runner import ScenarioRunner
from iso_test.serial import CommandResult


ROOT = Path(__file__).parent
POLICY_PATH = ROOT / "journal-policy.json"
VERSIONS = {
    "gdm3": "50.1-0ubuntu0.1",
    "gnome-settings-daemon": "50.0-1ubuntu1",
    "mutter-common": "50.1-0ubuntu2.2",
}


def scenario(**overrides):
    values = {
        "automatic_login": True,
        "desktop_release_gate": True,
        "rime": True,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def entry(
    message: str,
    component: str,
    *,
    priority: int = 4,
    cursor: str = "cursor-1",
    scope: str = "system",
) -> JournalEntry:
    return JournalEntry(
        cursor=cursor,
        timestamp="1786780000000000",
        priority=priority,
        message=message,
        identifiers=(component,),
        scopes=(scope,),
    )


class JournalPolicyShapeTests(unittest.TestCase):
    def test_repository_policy_is_narrow_versioned_and_owned(self):
        policy = JournalPolicy.load(POLICY_PATH)
        self.assertEqual(
            {
                "gdm-autologin-keyring-locked",
                "gnome50-keyboard-null-variant",
                "gnome50-transient-stack-position",
            },
            {item.id for item in policy.known_diagnostics},
        )
        self.assertEqual(
            ("gdm3", "gnome-settings-daemon", "mutter-common"),
            policy.packages,
        )
        for item in policy.known_diagnostics:
            self.assertNotEqual("*", item.version_glob)
            self.assertTrue(item.owner)
            self.assertGreater(len(item.reason), 40)
            self.assertEqual(1, item.max_occurrences)
            self.assertNotIn(".*", item.message_regex)

    def test_invalid_or_unbounded_policy_is_rejected(self):
        raw = json.loads(POLICY_PATH.read_text(encoding="utf-8"))
        raw["known_diagnostics"][0]["max_occurrences"] = 0
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "policy.json"
            path.write_text(json.dumps(raw), encoding="utf-8")
            with self.assertRaisesRegex(ConfigurationError, "max_occurrences"):
                JournalPolicy.load(path)

    def test_guest_collection_is_structured_and_scope_specific(self):
        policy = JournalPolicy.load(POLICY_PATH)
        system = render_guest_collection_script(policy)
        user = render_guest_collection_script(policy, user=True)
        self.assertIn("journalctl -b --no-pager -o json", system)
        self.assertNotIn("journalctl --user", system)
        self.assertIn("journalctl --user -b --no-pager -o json", user)
        self.assertIn("ensure_ascii=False", system)


class JournalClassificationTests(unittest.TestCase):
    def setUp(self):
        self.policy = JournalPolicy.load(POLICY_PATH)

    def test_three_known_gnome50_diagnostics_are_reported_not_hidden(self):
        entries = (
            entry(
                "gkr-pam: couldn't unlock the login keyring.",
                "gdm-autologin]",
                priority=3,
                cursor="gdm",
            ),
            entry(
                "g_variant_unref: assertion 'value != NULL' failed",
                "gsd-keyboard",
                cursor="keyboard",
            ),
            entry(
                "meta_window_set_stack_position_no_sync: assertion "
                "'window->stack_position >= 0' failed",
                "gnome-shell",
                cursor="shell",
            ),
        )
        verdict = self.policy.classify(entries, scenario(), VERSIONS)
        self.assertTrue(verdict.passed)
        self.assertEqual(0, len(verdict.blockers))
        self.assertEqual(3, len(verdict.known_diagnostics))
        report = render_verdict(verdict)
        self.assertIn("Journal release verdict: PASS", report)
        self.assertIn("gdm-autologin-keyring-locked", report)

    def test_known_diagnostic_is_blocking_outside_its_exact_scenario(self):
        item = entry(
            "gkr-pam: couldn't unlock the login keyring.",
            "gdm-autologin]",
            priority=3,
        )
        verdict = self.policy.classify(
            (item,),
            scenario(automatic_login=False),
            VERSIONS,
        )
        self.assertFalse(verdict.passed)
        self.assertIn(
            "does not apply",
            verdict.blockers[0].reason,
        )

    def test_known_diagnostic_expires_when_package_version_changes(self):
        item = entry(
            "g_variant_unref: assertion 'value != NULL' failed",
            "gsd-keyboard",
        )
        versions = dict(VERSIONS, **{"gnome-settings-daemon": "51.0-1"})
        verdict = self.policy.classify((item,), scenario(), versions)
        self.assertFalse(verdict.passed)
        self.assertIn("allowed 50.*", verdict.blockers[0].reason)

    def test_known_diagnostic_budget_excess_is_a_blocker(self):
        items = tuple(
            entry(
                "g_variant_unref: assertion 'value != NULL' failed",
                "gsd-keyboard",
                cursor=f"keyboard-{number}",
            )
            for number in (1, 2)
        )
        verdict = self.policy.classify(items, scenario(), VERSIONS)
        self.assertFalse(verdict.passed)
        self.assertEqual(1, len(verdict.known_diagnostics))
        self.assertEqual("diagnostic-budget-exceeded", verdict.blockers[0].kind)

    def test_similar_but_unrecognized_error_cannot_use_exception(self):
        item = entry(
            "g_variant_unref: assertion 'different != NULL' failed",
            "gsd-keyboard",
        )
        verdict = self.policy.classify((item,), scenario(), VERSIONS)
        self.assertFalse(verdict.passed)
        self.assertEqual("unexpected-journal-error", verdict.blockers[0].kind)

    def test_unknown_priority_three_and_high_priority_segfault_block(self):
        entries = (
            entry(
                "Failed to initialize AnduinOS session",
                "anduinos-service",
                priority=3,
                cursor="priority-three",
            ),
            entry(
                "process segfault at 0000000000000000",
                "gnome-shell",
                priority=6,
                cursor="segfault",
            ),
        )
        verdict = self.policy.classify(entries, scenario(), VERSIONS)
        self.assertFalse(verdict.passed)
        self.assertEqual(2, len(verdict.blockers))

    def test_failed_system_and_user_units_always_block(self):
        verdict = self.policy.classify(
            (),
            scenario(),
            VERSIONS,
            failed_system_units=("broken.service loaded failed failed",),
            failed_user_units=("bad-user.service loaded failed failed",),
        )
        self.assertFalse(verdict.passed)
        self.assertEqual(
            ["failed-unit", "failed-unit"],
            [item.kind for item in verdict.blockers],
        )

    def test_duplicate_system_and_user_cursor_counts_once(self):
        system = entry(
            "g_variant_unref: assertion 'value != NULL' failed",
            "gsd-keyboard",
            scope="system",
        )
        user = entry(
            system.message,
            "gsd-keyboard",
            scope="user",
        )
        merged = merge_journal_entries((system, user))
        self.assertEqual(1, len(merged))
        self.assertEqual(("system", "user"), merged[0].scopes)
        verdict = self.policy.classify((system, user), scenario(), VERSIONS)
        self.assertTrue(verdict.passed)
        self.assertEqual(1, verdict.candidate_count)

    def test_malformed_json_evidence_fails_closed(self):
        with self.assertRaisesRegex(TestFailure, "Malformed system journal JSON"):
            parse_journal_jsonl("not-json", "system")

    def test_nonfatal_observation_does_not_block(self):
        item = entry(
            "Ordinary informational warning",
            "example",
            priority=5,
        )
        verdict = self.policy.classify((item,), scenario(), VERSIONS)
        self.assertTrue(verdict.passed)
        self.assertEqual(1, len(verdict.observations))


class JournalGateIntegrationTests(unittest.TestCase):
    def test_runner_keeps_known_diagnostics_as_visible_passing_evidence(self):
        raw_entries = "\n".join(
            json.dumps(
                {
                    "cursor": cursor,
                    "timestamp": "1786780000000000",
                    "priority": priority,
                    "message": message,
                    "identifiers": [component],
                }
            )
            for cursor, priority, component, message in (
                (
                    "gdm",
                    3,
                    "gdm-autologin]",
                    "gkr-pam: couldn't unlock the login keyring.",
                ),
                (
                    "keyboard",
                    4,
                    "gsd-keyboard",
                    "g_variant_unref: assertion 'value != NULL' failed",
                ),
                (
                    "shell",
                    4,
                    "gnome-shell",
                    "meta_window_set_stack_position_no_sync: assertion "
                    "'window->stack_position >= 0' failed",
                ),
            )
        )
        console = _JournalConsole(raw_entries)
        runner = object.__new__(ScenarioRunner)
        runner.defaults = SimpleNamespace(username="anduinostest")
        runner.journal_policy = JournalPolicy.load(POLICY_PATH)
        statuses = []
        runner.status = lambda case, message: statuses.append((case, message))
        vm = SimpleNamespace(serial=console)
        test_scenario = scenario()
        test_scenario.id = "journal-integration"

        with tempfile.TemporaryDirectory() as directory:
            artifacts = Path(directory)
            runner._assert_journal_health(vm, test_scenario, artifacts)
            verdict = json.loads(
                (artifacts / "installed-journal-verdict.json").read_text(
                    encoding="utf-8"
                )
            )
            self.assertTrue(verdict["passed"])
            self.assertEqual(3, verdict["summary"]["known_diagnostics"])
            self.assertEqual(0, verdict["summary"]["blockers"])
            self.assertTrue(
                (artifacts / "installed-journal-functional-health.txt").is_file()
            )
            self.assertEqual(
                json.loads(POLICY_PATH.read_text(encoding="utf-8")),
                json.loads(
                    (artifacts / "journal-policy.json").read_text(
                        encoding="utf-8"
                    )
                ),
            )
            self.assertIn(
                "KNOWN DIAGNOSTICS",
                (artifacts / "installed-system-journal-gate.txt").read_text(
                    encoding="utf-8"
                ),
            )
        self.assertTrue(any("0 blockers" in message for _, message in statuses))

    def test_runner_still_fails_an_unknown_error(self):
        raw = json.dumps(
            {
                "cursor": "unknown",
                "timestamp": "1786780000000000",
                "priority": 3,
                "message": "AnduinOS desktop service failed unexpectedly",
                "identifiers": ["anduinos-desktop"],
            }
        )
        console = _JournalConsole(raw)
        runner = object.__new__(ScenarioRunner)
        runner.defaults = SimpleNamespace(username="anduinostest")
        runner.journal_policy = JournalPolicy.load(POLICY_PATH)
        runner.status = lambda *_args: None
        vm = SimpleNamespace(serial=console)
        test_scenario = scenario()
        test_scenario.id = "journal-unknown"

        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(TestFailure, "1 unexpected"):
                runner._assert_journal_health(
                    vm,
                    test_scenario,
                    Path(directory),
                )


class _JournalConsole:
    def __init__(self, system_journal: str):
        self.system_journal = system_journal

    def run(self, script, *, timeout=None, check=True):
        del timeout, check
        if "journalctl --user -b --no-pager -o json" in script:
            return CommandResult("", 0)
        if "journalctl -b --no-pager -o json" in script:
            return CommandResult(self.system_journal, 0)
        if "systemctl --user --failed --no-legend --plain" in script:
            return CommandResult("", 0)
        if script == "systemctl --failed --no-legend --plain":
            return CommandResult("", 0)
        if "dpkg-query -W" in script:
            return CommandResult(
                "\n".join(f"{name}\t{version}" for name, version in VERSIONS.items()),
                0,
            )
        if "gnome-shell-pid=" in script:
            return CommandResult(
                "gnome-shell-pid=100\n"
                "gsd-keyboard-pid=101\n"
                "gnome-keyring-pid=102\n"
                "input-sources=[('xkb', 'us'), ('ibus', 'rime')]",
                0,
            )
        raise AssertionError(f"Unexpected journal integration script: {script[:160]}")


if __name__ == "__main__":
    unittest.main()
