"""Fail-closed notification regression and offline matrix wiring."""

import importlib.util
import json
import shlex
import subprocess
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from assertions.notifications import (
    _wait_shell_prompt, assert_live_notifications_quiet, validate_quiet_start,
)
from business.install import scenario_check_ids
from framework.errors import TestFailure
from framework.model import Network, TestMatrix
from framework.qmp import _key_name
from framework.serial import CommandResult


def quiet_report():
    return dict(complete=True, seconds=10.01, notifications=[], error=None)


def ready_prompt(prompt, text=''):
    return CommandResult(json.dumps(dict(ready=True, expected_prompt=prompt, expected_text=text)), 0)


def prompt_results():
    return [ready_prompt('run-dialog'), ready_prompt('run-dialog', 'lg'),
            ready_prompt('looking-glass'), ready_prompt(
                'looking-glass', 'import("file:///tmp/anduinos-live-notifications.mjs")')]


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

    def test_unrecognized_notifications_still_fail_in_other_languages(self):
        report = quiet_report()
        report['notifications'] = [{'title': '更新提醒'}]
        with self.assertRaisesRegex(TestFailure, '更新提醒'):
            validate_quiet_start(report)

    def test_only_software_update_check_reminder_is_allowed_in_each_language(self):
        for title, body in (
            ('Updates Are Out of Date', 'Please check for available updates'),
            ('更新已过期', '请检查可用更新'),
        ):
            for phase in ('existing', 'new'):
                with self.subTest(title=title, phase=phase):
                    report = quiet_report()
                    report['software_update_check_notice'] = dict(title=title, body=body)
                    report['notifications'] = [dict(
                        app_id='org.gnome.Software', phase=phase, title=title, body=body)]
                    validate_quiet_start(report)

    def test_software_exception_does_not_hide_other_apps_or_other_messages(self):
        expected = dict(title='Updates Are Out of Date',
                        body='Please check for available updates')
        allowed = dict(app_id='org.gnome.Software', **expected)
        for change in (
            dict(app_id='other.application'), dict(app_id=''),
            dict(title='Critical Updates Ready to Install'),
            dict(body='An unexpected error occurred'),
            dict(title=''), dict(body=''),
        ):
            with self.subTest(change=change), self.assertRaises(TestFailure):
                report = quiet_report()
                report['software_update_check_notice'] = expected
                report['notifications'] = [allowed, dict(allowed, **change)]
                validate_quiet_start(report)

    def test_missing_or_invalid_translation_metadata_does_not_allow_notifications(self):
        for metadata in (None, {}, [], dict(title='', body=''),
                         dict(title='Updates Are Out of Date', body=None)):
            with self.subTest(metadata=metadata), self.assertRaises(TestFailure):
                report = quiet_report()
                report['software_update_check_notice'] = metadata
                report['notifications'] = [dict(
                    app_id='org.gnome.Software', title='Updates Are Out of Date',
                    body='Please check for available updates')]
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
            *prompt_results(),
            CommandResult(json.dumps(report), rc),
            CommandResult(pid, 0),
            CommandResult('', 0),
        ]
        qmp = Mock()
        with tempfile.TemporaryDirectory() as directory:
            evidence = Path(directory)
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
        self.assertIn('for attempt in $(seq 1 30)', script)
        self.assertIn("'@a(ss) []'|'[]') sleep 1", script)
        self.assertNotIn('gsettings set', script)
        guard = next(line for line in script.splitlines() if line.startswith('[[ "$sources"'))
        for sources, expected in (
            ("[('xkb', 'us')]", 0),
            ("[('xkb', 'us'), ('ibus', 'libpinyin')]", 0),
            ("[('xkb', 'de')]", 1),
            ("[('ibus', 'libpinyin'), ('xkb', 'us')]", 1),
            ("@a(ss) []", 1),
            ("[]", 1),
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

    def test_dialog_open_is_retried_only_after_a_failed_readiness_probe(self):
        console = Mock()
        console.run.side_effect = [
            CommandResult('shell-pid=42\n', 0),
            CommandResult('{"ready":false}', 1),
            *prompt_results(),
            CommandResult(json.dumps(quiet_report()), 0),
            CommandResult('42', 0), CommandResult('', 0),
        ]
        qmp = Mock()
        with tempfile.TemporaryDirectory() as directory:
            assert_live_notifications_quiet(console, qmp, Path(directory))
        self.assertEqual(2, sum(call.args[0] == 'alt-f2' for call in qmp.send_key.call_args_list))
        self.assertEqual(2, qmp.type_text.call_count)

    def test_unready_dialog_fails_without_typing_and_retains_ui_evidence(self):
        console = Mock()
        console.run.side_effect = [CommandResult('shell-pid=42\n', 0),
                                  *[CommandResult('{"ready":false}', 1)] * 3,
                                  CommandResult('', 0)]
        qmp = Mock()
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(TestFailure, 'Run dialog never became ready'):
                assert_live_notifications_quiet(console, qmp, Path(directory))
            self.assertEqual(3, len((Path(directory) / 'live-notifications-ui.jsonl').read_text().splitlines()))
        qmp.type_text.assert_not_called()
        self.assertIn('anduinos-shell-prompt.py', console.run.call_args_list[-1].args[0])

    def test_missing_looking_glass_never_sends_javascript_to_run_dialog(self):
        console = Mock()
        console.run.side_effect = [CommandResult('shell-pid=42\n', 0),
                                  *prompt_results()[:2],
                                  ready_prompt('run-dialog', 'lg'), CommandResult('', 0)]
        qmp = Mock()
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(TestFailure, 'UI not ready: looking-glass'):
                assert_live_notifications_quiet(console, qmp, Path(directory))
        qmp.type_text.assert_called_once_with('lg', interval=0.15)

    def test_corrupt_typed_expression_is_never_submitted(self):
        console = Mock()
        console.run.side_effect = [CommandResult('shell-pid=42\n', 0),
                                  *prompt_results()[:3],
                                  ready_prompt('looking-glass', 'imprt('), CommandResult('', 0)]
        qmp = Mock()
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(TestFailure, 'UI not ready: looking-glass'):
                assert_live_notifications_quiet(console, qmp, Path(directory))
        self.assertEqual(1, sum(call.args[0] == 'ret' for call in qmp.send_key.call_args_list))

    def test_invalid_prompt_report_never_passes(self):
        for output in ('not json', '[]', '{"ready":true}',
                       json.dumps(dict(ready=True, expected_prompt='run-dialog', expected_text='wrong'))):
            with self.subTest(output=output), tempfile.TemporaryDirectory() as directory:
                console = Mock()
                console.run.return_value = CommandResult(output, 0)
                self.assertFalse(_wait_shell_prompt(console, Path(directory), 'looking-glass', check=False))

    def test_prompt_report_allows_stderr_warnings_but_not_ambiguous_reports(self):
        report = json.dumps(dict(ready=True, expected_prompt='run-dialog', expected_text='lg'))
        for output, rc, expected in (
            ('dbind-WARNING: cache not ready\n' + report + '\n', 0, True),
            (report + '\nwarning after report\n', 0, True),
            (report + '\n' + report, 0, False),
            ('warning only', 0, False),
            (report, 1, False),
        ):
            with self.subTest(output=output, rc=rc), tempfile.TemporaryDirectory() as directory:
                console = Mock()
                console.run.return_value = CommandResult(output, rc)
                self.assertEqual(expected, _wait_shell_prompt(
                    console, Path(directory), 'run-dialog', 'lg', check=False))

    def test_observer_timeout_is_not_a_quiet_pass(self):
        with self.assertRaisesRegex(TestFailure, 'never completed'):
            self.exercise({}, rc=1)

    def test_failure_retains_notification_evidence_and_cleans_up(self):
        report = dict(quiet_report(), notifications=[{'title': 'Unexpected startup notice'}])
        console = Mock()
        console.run.side_effect = [
            CommandResult('shell-pid=42\n', 0),
            *prompt_results(),
            CommandResult(json.dumps(report), 0),
            CommandResult('42', 0),
            CommandResult('', 0),
        ]
        with tempfile.TemporaryDirectory() as directory:
            evidence = Path(directory)
            with self.assertRaises(TestFailure):
                assert_live_notifications_quiet(console, Mock(), evidence)
            self.assertEqual(report, json.loads((evidence / 'live-notifications.json').read_text()))
        self.assertIn('rm -f ', console.run.call_args_list[-1].args[0])


class ShellPromptTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        spec = importlib.util.spec_from_file_location(
            'shell_prompt', Path(__file__).parents[1] / 'fixtures/shell_prompt.py')
        cls.probe = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cls.probe)

    def test_accessibility_detector_requires_real_prompt_context_and_focus(self):
        class Node:
            def __init__(self, role='panel', name='', children=(), *, focused=False):
                self.role, self.name, self.children = role, name, list(children)
                self.parent = None
                self.states = {'showing'} | ({'focused', 'editable'} if focused else set())
                for child in self.children:
                    child.parent = self

            def get_child_count(self): return len(self.children)
            def get_child_at_index(self, index): return self.children[index]
            def get_parent(self): return self.parent
            def get_role(self): return self.role
            def get_name(self): return self.name
            def get_state_set(self): return SimpleNamespace(contains=self.states.__contains__)

        atspi = SimpleNamespace(
            StateType=SimpleNamespace(SHOWING='showing', DEFUNCT='defunct',
                                      FOCUSED='focused', EDITABLE='editable'),
            Role=SimpleNamespace(TEXT='text', LABEL='label', DIALOG='dialog', PUSH_BUTTON='button'),
            Text=SimpleNamespace(get_text=lambda node, start, end: node.name),
        )
        def shell_context(*, dialog=False, title='Run a Command', buttons=True, focused=True):
            entry = Node('text', children=(), focused=focused)
            area = Node(children=[Node('label', title if dialog else '>>> '), Node(children=[entry])])
            shell = Node(children=[
                Node(children=[Node('button' if buttons else 'label', name)
                               for name in ('Evaluator', 'Windows', 'Extensions')]),
                Node('dialog' if dialog else 'panel', children=[area]),
            ])
            return shell

        for options, expected in (({}, 'looking-glass'), ({'dialog': True}, 'run-dialog'),
                                  ({'buttons': False}, None), ({'dialog': True, 'title': 'Other dialog'}, None),
                                  ({'focused': False}, None)):
            with self.subTest(options=options), patch.object(self.probe, 'shell_language', return_value=['C']):
                snapshot = self.probe.prompt_snapshot(shell_context(**options), atspi)
                self.assertEqual(expected, snapshot['entries'][0]['prompt'] if snapshot['entries'] else None)

        with patch.object(self.probe, 'shell_language', return_value=['zh_CN']), \
                patch.object(self.probe.gettext, 'translation') as translation:
            translation.return_value.gettext.return_value = '运行一个命令'
            snapshot = self.probe.prompt_snapshot(shell_context(dialog=True, title='运行一个命令'), atspi)
            self.assertTrue(self.probe.matches_prompt(snapshot, 'run-dialog', ''))
            translation.assert_called_once_with('gnome-shell', languages=['zh_CN'], fallback=True)

    def test_wrong_focus_partial_text_and_ambiguous_entries_are_not_ready(self):
        entry = dict(prompt='looking-glass', text='import("fixture")')
        for entries in ([], [dict(entry, prompt='run-dialog')],
                        [dict(entry, prompt=None)], [dict(entry, text='imprt(')], [entry, entry]):
            with self.subTest(entries=entries):
                self.assertFalse(self.probe.matches_prompt(dict(entries=entries), 'looking-glass', entry['text']))

    def test_delayed_window_and_focus_are_polled_until_ready(self):
        time = [0.0]
        states = iter([dict(entries=[]), dict(entries=[dict(prompt='run-dialog', text='lg')]),
                       dict(entries=[dict(prompt='looking-glass', text='')])])
        with patch.object(self.probe, 'matches_prompt', wraps=self.probe.matches_prompt) as matches:
            result = self.probe.wait_for_prompt(
                lambda: next(states), 'looking-glass', '', 5,
                clock=lambda: time[0], sleep=lambda delay: time.__setitem__(0, time[0] + delay))
        self.assertTrue(result['ready'])
        self.assertEqual(3, matches.call_count)

    def test_wrong_window_times_out_instead_of_assuming_readiness(self):
        time = [0.0]
        result = self.probe.wait_for_prompt(
            lambda: dict(entries=[dict(prompt='run-dialog', text='lg')]), 'looking-glass', '', 1,
            clock=lambda: time[0], sleep=lambda delay: time.__setitem__(0, time[0] + delay))
        self.assertFalse(result['ready'])
