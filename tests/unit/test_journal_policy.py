"""Regression tests for balanced, fail-closed journal classification."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from framework.errors import ConfigurationError, TestFailure
from assertions.journal import (
    JournalEntry,
    JournalPolicy,
    merge_journal_entries,
    parse_journal_jsonl,
    render_guest_collection_script,
    render_verdict,
)
from business.install import ScenarioRunner
from framework.serial import CommandResult


ROOT = Path(__file__).parents[1]
POLICY_PATH = ROOT / "assertions/journal-policy.json"
VERSIONS = {
    "gdm3": "50.1-0ubuntu0.1",
    "gnome-shell-extension-desktop-icons-ng-anduinos": "2.0.2-2+resolute",
    "gnome-shell": "50.1-0ubuntu1.2",
    "gnome-settings-daemon": "50.0-1ubuntu1",
    "mutter-common": "50.1-0ubuntu2.2",
    "spice-vdagent": "0.23.0-1",
}

DASH_NULL_ICON = "\n".join(
    (
        'JS ERROR: TypeError: can\'t access property "ensure_style", firstIcon.icon is null',
        "_adjustIconSize@resource:///org/gnome/shell/ui/dash.js:602:9",
        "_redisplay@resource:///org/gnome/shell/ui/dash.js:791:14",
        "_runDeferredWork@resource:///org/gnome/shell/ui/main.js:986:31",
        "_runAllDeferredWork@resource:///org/gnome/shell/ui/main.js:995:25",
        "queueDeferredWork/_deferredTimeoutId<@resource:///org/gnome/shell/ui/main.js:1079:13",
        "_init/this.timeout_add_seconds_once/id<@resource:///org/gnome/gjs/modules/core/overrides/GLib.js:444:13",
        "@resource:///org/gnome/shell/ui/init.js:20:20",
    )
)


def scenario(**overrides):
    values = {
        "automatic_login": True,
        "desktop_contracts": True,
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
                "gnome50-gdm-media-keys-null-table",
                "gnome50-sharing-closed-dbus",
                "gnome50-transient-stack-position",
                "ding93-gtk422-transient-a11y-toplevel",
                "gnome50-hidden-dash-null-icon",
                "spice-vdagent-tty-switch-no-active-session",
            },
            {item.id for item in policy.known_diagnostics},
        )
        self.assertEqual(
            (
                "gdm3",
                "gnome-settings-daemon",
                "gnome-shell",
                "gnome-shell-extension-desktop-icons-ng-anduinos",
                "mutter-common",
                "spice-vdagent",
            ),
            policy.packages,
        )
        for item in policy.known_diagnostics:
            self.assertNotEqual("*", item.version_glob)
            self.assertTrue(item.owner)
            self.assertGreater(len(item.reason), 40)
            expected_budget = {
                "spice-vdagent-tty-switch-no-active-session": 16,
                "gnome50-sharing-closed-dbus": 2,
            }.get(item.id, 1)
            self.assertEqual(expected_budget, item.max_occurrences)
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

    def test_keyboard_diagnostic_applies_to_rime_feature_base(self):
        item = entry(
            "g_variant_unref: assertion 'value != NULL' failed",
            "gsd-keyboard",
        )
        accepted = self.policy.classify(
            (item,), scenario(desktop_contracts=False, rime=True), VERSIONS
        )
        no_rime = self.policy.classify(
            (item,), scenario(desktop_contracts=False, rime=False), VERSIONS
        )
        self.assertTrue(accepted.passed)
        self.assertEqual(
            "gnome50-keyboard-null-variant",
            accepted.known_diagnostics[0].rule_id,
        )
        self.assertFalse(no_rime.passed)

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

    def test_gdm_media_keys_diagnostic_is_manual_login_only_and_excludes_user(self):
        message = "g_hash_table_size: assertion 'hash_table != NULL' failed"
        greeter = entry(
            message,
            "gsd-media-keys|user@60578.service|"
            "org.gnome.SettingsDaemon.MediaKeys.service|"
            "/usr/libexec/gsd-media-keys",
        )
        user = entry(
            message,
            "gsd-media-keys|user@1000.service|"
            "org.gnome.SettingsDaemon.MediaKeys.service|"
            "/usr/libexec/gsd-media-keys",
        )
        accepted = self.policy.classify(
            (greeter,), scenario(automatic_login=False), VERSIONS
        )
        automatic = self.policy.classify(
            (greeter,), scenario(automatic_login=True), VERSIONS
        )
        installed_user = self.policy.classify(
            (user,), scenario(automatic_login=False), VERSIONS
        )
        self.assertTrue(accepted.passed)
        self.assertEqual(
            "gnome50-gdm-media-keys-null-table",
            accepted.known_diagnostics[0].rule_id,
        )
        self.assertFalse(automatic.passed)
        self.assertFalse(installed_user.passed)

    def test_sharing_diagnostic_is_exact_automatic_desktop_pair(self):
        message = (
            "g_dbus_connection_call_internal: assertion "
            "'G_IS_DBUS_CONNECTION (connection)' failed"
        )
        component = (
            "gsd-sharing|user@1000.service|"
            "org.gnome.SettingsDaemon.Sharing.service|/usr/libexec/gsd-sharing"
        )
        entries = (
            entry(message, component, cursor="sharing-1"),
            entry(message, component, cursor="sharing-2"),
        )
        accepted = self.policy.classify(entries, scenario(), VERSIONS)
        manual = self.policy.classify(
            entries, scenario(automatic_login=False), VERSIONS
        )
        excessive = self.policy.classify(
            (*entries, entry(message, component, cursor="sharing-3")),
            scenario(),
            VERSIONS,
        )
        self.assertTrue(accepted.passed)
        self.assertEqual(2, len(accepted.known_diagnostics))
        self.assertFalse(manual.passed)
        self.assertFalse(excessive.passed)
        self.assertEqual("diagnostic-budget-exceeded", excessive.blockers[0].kind)

    def test_ding_a11y_diagnostic_is_exact_versioned_and_budgeted(self):
        message = (
            "DING: (gjs:1766): Gdk-CRITICAL **: 00:07:12.605: "
            "gdk_wayland_toplevel_set_a11y_properties: assertion "
            "'GDK_IS_WAYLAND_TOPLEVEL (toplevel)' failed"
        )
        item = entry(message, "gnome-shell", priority=6)
        accepted = self.policy.classify((item,), scenario(), VERSIONS)
        changed = self.policy.classify(
            (
                entry(
                    message.replace("toplevel)'", "surface)'"),
                    "gnome-shell",
                    priority=6,
                ),
            ),
            scenario(),
            VERSIONS,
        )
        excessive = self.policy.classify(
            (item, entry(message, "gnome-shell", priority=6, cursor="cursor-2")),
            scenario(),
            VERSIONS,
        )
        expired = self.policy.classify(
            (item,),
            scenario(),
            dict(
                VERSIONS,
                **{
                    "gnome-shell-extension-desktop-icons-ng-anduinos": (
                        "2.0.2-3+resolute"
                    )
                },
            ),
        )
        self.assertTrue(accepted.passed)
        self.assertEqual(
            "ding93-gtk422-transient-a11y-toplevel",
            accepted.known_diagnostics[0].rule_id,
        )
        self.assertFalse(changed.passed)
        self.assertEqual("unexpected-journal-error", changed.blockers[0].kind)
        self.assertFalse(excessive.passed)
        self.assertEqual("diagnostic-budget-exceeded", excessive.blockers[0].kind)
        self.assertFalse(expired.passed)
        self.assertIn("allowed 2.0.2-[12]+resolute", expired.blockers[0].reason)

    def test_similar_but_unrecognized_error_cannot_use_exception(self):
        item = entry(
            "g_variant_unref: assertion 'different != NULL' failed",
            "gsd-keyboard",
        )
        verdict = self.policy.classify((item,), scenario(), VERSIONS)
        self.assertFalse(verdict.passed)
        self.assertEqual("unexpected-journal-error", verdict.blockers[0].kind)

    def test_spice_vdagent_diagnostic_is_only_known_during_the_tty6_action(self):
        item = entry(
            "Error getting active session: No data available",
            "spice-vdagentd.service",
            priority=3,
        )
        outside = self.policy.classify((item,), scenario(), VERSIONS)
        wrong_action = self.policy.classify(
            (item,),
            scenario(),
            VERSIONS,
            action_scope="shortcut-super-u",
        )
        during_switch = self.policy.classify(
            (item,),
            scenario(),
            VERSIONS,
            action_scope="tty6-branding",
        )
        self.assertFalse(outside.passed)
        self.assertFalse(wrong_action.passed)
        self.assertTrue(during_switch.passed)
        self.assertEqual(
            "spice-vdagent-tty-switch-no-active-session",
            during_switch.known_diagnostics[0].rule_id,
        )

    def test_hidden_dash_null_icon_is_only_known_for_exact_about_action(self):
        item = entry(DASH_NULL_ICON, "gnome-shell")
        outside = self.policy.classify((item,), scenario(), VERSIONS)
        wrong_action = self.policy.classify(
            (item,),
            scenario(),
            VERSIONS,
            action_scope="shortcut-super-i",
        )
        during_about = self.policy.classify(
            (item,),
            scenario(),
            VERSIONS,
            action_scope="settings-about-branding",
        )
        self.assertFalse(outside.passed)
        self.assertFalse(wrong_action.passed)
        self.assertTrue(during_about.passed)
        self.assertEqual(
            "gnome50-hidden-dash-null-icon",
            during_about.known_diagnostics[0].rule_id,
        )

    def test_hidden_dash_exception_still_fails_on_drift_count_or_version(self):
        item = entry(DASH_NULL_ICON, "gnome-shell")
        changed = entry(
            DASH_NULL_ICON.replace("firstIcon.icon is null", "firstIcon is null"),
            "gnome-shell",
        )
        action = {"action_scope": "settings-about-branding"}
        drifted = self.policy.classify((changed,), scenario(), VERSIONS, **action)
        excessive = self.policy.classify(
            (item, entry(DASH_NULL_ICON, "gnome-shell", cursor="cursor-2")),
            scenario(),
            VERSIONS,
            **action,
        )
        expired = self.policy.classify(
            (item,),
            scenario(),
            dict(VERSIONS, **{"gnome-shell": "51.0-1"}),
            **action,
        )
        self.assertFalse(drifted.passed)
        self.assertEqual("unexpected-journal-error", drifted.blockers[0].kind)
        self.assertFalse(excessive.passed)
        self.assertEqual("diagnostic-budget-exceeded", excessive.blockers[0].kind)
        self.assertFalse(expired.passed)
        self.assertIn("allowed 50.*", expired.blockers[0].reason)

    def test_spice_vdagent_tty_switch_budget_and_version_remain_fail_closed(self):
        items = tuple(
            entry(
                "Error getting active session: No data available",
                "spice-vdagentd.service",
                priority=3,
                cursor=f"spice-{number}",
            )
            for number in range(17)
        )
        excessive = self.policy.classify(
            items,
            scenario(),
            VERSIONS,
            action_scope="tty6-branding",
        )
        expired = self.policy.classify(
            (items[0],),
            scenario(),
            dict(VERSIONS, **{"spice-vdagent": "0.24.0-1"}),
            action_scope="tty6-branding",
        )
        self.assertFalse(excessive.passed)
        self.assertEqual(
            "diagnostic-budget-exceeded",
            excessive.blockers[0].kind,
        )
        self.assertFalse(expired.passed)
        self.assertIn("allowed 0.23.*", expired.blockers[0].reason)

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
