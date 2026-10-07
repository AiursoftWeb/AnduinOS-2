"""Fail-closed notification regression and offline matrix wiring."""

import json
import shlex
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from assertions.notifications import assert_live_notifications_quiet, validate_quiet_start
from business.install import scenario_check_ids
from framework.errors import TestFailure
from framework.model import Network, TestMatrix
from framework.qmp import _key_name
from framework.serial import CommandResult


def quiet_report():
    return dict(complete=True, seconds=10.01, notifications=[], error=None)


class LiveNotificationTests(unittest.TestCase):
    def test_empty_completed_observation_passes(self):
        validate_quiet_start(quiet_report())

    def test_existing_and_new_notifications_both_fail(self):
        for phase in ('existing', 'new'):
            report = quiet_report()
            report['notifications'] = [{
                'phase': phase, 'title': 'Dash to Panel has been updated!',
                'body': 'You are now running version 74.',
            }]
            with self.subTest(phase=phase), self.assertRaisesRegex(TestFailure, 'Dash to Panel'):
                validate_quiet_start(report)

    def test_notifications_are_not_filtered_by_title_or_language(self):
        report = quiet_report()
        report['notifications'] = [{'title': '更新提醒'}]
        with self.assertRaisesRegex(TestFailure, '更新提醒'):
            validate_quiet_start(report)

    def test_missing_incomplete_failed_or_short_observer_never_passes(self):
        for report in (None, [], {}, {'complete': False}, {'complete': True},
                       dict(quiet_report(), error='API unavailable'),
                       dict(quiet_report(), seconds=9.99),
                       dict(quiet_report(), seconds=True),
                       dict(quiet_report(), seconds=float('nan')),
                       dict(quiet_report(), seconds=float('inf')),
                       dict(quiet_report(), seconds=60),
                       dict(quiet_report(), notifications=None)):
            with self.subTest(report=report), self.assertRaises(TestFailure):
                validate_quiet_start(report)

    def test_exactly_offline_cases_declare_the_check_before_installer(self):
        matrix = TestMatrix.load(Path(__file__).parents[1] / 'cases/install.json')
        for scenario in matrix.scenarios:
            checks = scenario_check_ids(scenario)
            with self.subTest(case=scenario.id):
                self.assertEqual(scenario.network is Network.OFFLINE,
                                 'live.offline-no-notifications' in checks)
                if scenario.network is Network.OFFLINE:
                    self.assertLess(checks.index('live.offline-no-notifications'),
                                    checks.index('installer-ui'))

    def test_import_expression_can_be_typed_by_qmp(self):
        for character in 'import("file:///tmp/anduinos-live-notifications.mjs")':
            self.assertTrue(_key_name(character))

    def exercise(self, report, *, rc=0, pid='42'):
        console = Mock()
        console.run.side_effect = [
            CommandResult("shell-pid=42\ninput-sources=[('xkb', 'us')]\n", 0),
            CommandResult(json.dumps(report), rc),
            CommandResult(pid, 0),
            CommandResult('', 0),
        ]
        qmp = Mock()
        with tempfile.TemporaryDirectory() as directory:
            evidence = Path(directory)
            with patch('assertions.notifications.time.sleep'):
                assert_live_notifications_quiet(console, qmp, evidence)
            self.assertEqual(report, json.loads((evidence / 'live-notifications.json').read_text()))
        return console, qmp

    def test_observation_uses_real_shell_and_cleans_temporary_files(self):
        console, qmp = self.exercise(quiet_report())
        self.assertIn('import("file://', qmp.type_text.call_args_list[-1].args[0])
        self.assertIn('rm -f /tmp/anduinos-live-notifications.mjs',
                      console.run.call_args_list[-1].args[0])
        self.assertEqual('esc', qmp.send_key.call_args_list[-1].args[0])

    def test_shell_restart_is_not_a_quiet_pass(self):
        with self.assertRaisesRegex(TestFailure, 'restarted'):
            self.exercise(quiet_report(), pid='43')

    def test_us_keyboard_allows_chinese_input_method_without_changing_sources(self):
        console, _qmp = self.exercise(quiet_report())
        script = console.run.call_args_list[0].args[0]
        guard = next(line for line in script.splitlines() if line.startswith('[[ "$sources"'))
        for sources, expected in (
            ("[('xkb', 'us')]", 0),
            ("[('xkb', 'us'), ('ibus', 'libpinyin')]", 0),
            ("[('xkb', 'de')]", 1),
            ("[('ibus', 'libpinyin'), ('xkb', 'us')]", 1),
        ):
            with self.subTest(sources=sources):
                result = subprocess.run(
                    ['bash', '-c', f'sources={shlex.quote(sources)}\n{guard}'],
                    capture_output=True, check=False,
                )
                self.assertEqual(expected, result.returncode)

    def test_prerequisite_failure_is_recorded_without_touching_desktop(self):
        console = Mock()
        console.run.return_value = CommandResult('input-sources=wrong\n', 1)
        qmp = Mock()
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(TestFailure, 'prerequisites'):
                assert_live_notifications_quiet(console, qmp, Path(directory))
            self.assertIn('wrong', (Path(directory) / 'live-notifications-session.txt').read_text())
        console.upload.assert_not_called()
        qmp.send_key.assert_not_called()

    def test_observer_timeout_is_not_a_quiet_pass(self):
        with self.assertRaisesRegex(TestFailure, 'never completed'):
            self.exercise({}, rc=1)

    def test_failure_retains_notification_evidence_and_cleans_up(self):
        report = dict(quiet_report(), notifications=[{'title': 'Unexpected startup notice'}])
        console = Mock()
        console.run.side_effect = [
            CommandResult('shell-pid=42\n', 0),
            CommandResult(json.dumps(report), 0),
            CommandResult('42', 0),
            CommandResult('', 0),
        ]
        with tempfile.TemporaryDirectory() as directory:
            evidence = Path(directory)
            with patch('assertions.notifications.time.sleep'), self.assertRaises(TestFailure):
                assert_live_notifications_quiet(console, Mock(), evidence)
            self.assertEqual(report, json.loads((evidence / 'live-notifications.json').read_text()))
        self.assertIn('rm -f ', console.run.call_args_list[-1].args[0])
