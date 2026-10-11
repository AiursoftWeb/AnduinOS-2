"""Keep the ISO driver aligned with the keyboard-before-password wizard."""

import ast
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock


class InstallerKeyboardOrderTests(unittest.TestCase):
    def test_network_and_input_methods_follow_keyboard_confirmation(self):
        source = Path(__file__).parents[1] / 'assertions/guest/ui/installer.py'
        tree = ast.parse(source.read_text())
        function = next(node for node in tree.body
                        if isinstance(node, ast.FunctionDef) and node.name == 'install')
        for network in ('offline', 'online', 'wifi'):
            with self.subTest(network=network), tempfile.TemporaryDirectory() as directory:
                events = []

                def wait_page(page, *_args):
                    events.append(('page', page))
                    if page == 'disk':
                        raise StopIteration  # Only exercise the non-destructive prefix.

                namespace = {
                    'Path': SimpleNamespace(home=lambda: Path(directory)),
                    'launch_installer': Mock(),
                    'choose_chinese': Mock(),
                    'click': lambda key: events.append(('click', key)),
                    'find_candidates': Mock(),
                    'matches': lambda *_args: False,
                    'wait_page': wait_page,
                    'connect_wifi_from_installer': lambda *_args: events.append(('wifi', 'password')),
                    'assert_toggle': lambda key, **_kwargs: events.append(('toggle', key)),
                    'set_toggle': Mock(),
                    'find': Mock(),
                    'ALIASES': {'keyboard': ('Keyboard',), 'firmware_complete': ('Complete',)},
                }
                exec(compile(ast.Module(body=[function], type_ignores=[]), str(source), 'exec'), namespace)
                with self.assertRaises(StopIteration):
                    namespace['install'](
                        {'firmware': 'bios', 'network': network,
                         'rime': network == 'online', 'online_features': False},
                        Path(directory))
                keyboard = events.index(('page', 'keyboard'))
                software = events.index(('page', 'software'))
                self.assertEqual(events[keyboard + 1], ('click', 'next'))
                self.assertLess(keyboard, software)
                self.assertLess(software, events.index(('toggle', 'rime')))
                if network != 'online':
                    self.assertLess(keyboard, events.index(('page', 'network')))
                if network == 'wifi':
                    self.assertLess(keyboard, events.index(('wifi', 'password')))
