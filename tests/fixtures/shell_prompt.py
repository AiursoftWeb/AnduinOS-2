"""Read-only AT-SPI handshake before typing into GNOME Shell's debug UI."""

from __future__ import annotations

import argparse
import gettext
import json
import time
from pathlib import Path


def walk(node, maximum=5000):
    stack = [node]
    for _ in range(maximum):
        if not stack:
            return
        current = stack.pop()
        yield current
        stack.extend(reversed([
            child for index in range(min(maximum, max(0, current.get_child_count())))
            if (child := current.get_child_at_index(index)) is not None
        ]))


def shell_language(shell):
    # The root serial shell's locale need not match the graphical session.
    environ = Path(f'/proc/{shell.get_process_id()}/environ').read_bytes()
    values = dict(item.split(b'=', 1) for item in environ.split(b'\0') if b'=' in item)
    for key in ('LANGUAGE', 'LC_ALL', 'LC_MESSAGES', 'LANG'):
        value = values.get(key.encode(), b'').decode()
        if value:
            return value.split(':')
    return ['C']


def prompt_snapshot(shell, atspi):
    def showing(node):
        states = node.get_state_set()
        return states.contains(atspi.StateType.SHOWING) and not states.contains(
            atspi.StateType.DEFUNCT)

    nodes = [node for node in walk(shell) if showing(node)]
    run_title = gettext.translation('gnome-shell', languages=shell_language(shell),
                                    fallback=True).gettext('Run a Command')
    names = {node.get_name() for node in nodes}
    buttons = {node.get_name() for node in nodes if node.get_role() == atspi.Role.PUSH_BUTTON}
    tabs_visible = {'Evaluator', 'Windows', 'Extensions'} <= buttons
    entries = []
    for node in nodes:
        states = node.get_state_set()
        if (node.get_role() != atspi.Role.TEXT or
                not states.contains(atspi.StateType.FOCUSED) or
                not states.contains(atspi.StateType.EDITABLE)):
            continue
        ancestors = []
        ancestor = node.get_parent()
        for _ in range(20):
            if ancestor is None:
                break
            ancestors.append(ancestor)
            ancestor = ancestor.get_parent()
        dialogs = [parent for parent in ancestors if parent.get_role() == atspi.Role.DIALOG]
        in_run_dialog = any(
            child.get_name() == run_title
            for dialog in dialogs for child in walk(dialog) if showing(child)
        )
        # Looking Glass's untranslated evaluator prompt is next to its entry,
        # not a label elsewhere in the desktop or in a command result.
        entry_area = node.get_parent().get_parent()
        evaluator_entry = any(
            child.get_role() == atspi.Role.LABEL and child.get_name().strip() == '>>>'
            for child in walk(entry_area, maximum=30) if showing(child)
        )
        prompt = None
        if in_run_dialog:
            prompt = 'run-dialog'
        elif not dialogs and tabs_visible and evaluator_entry:
            prompt = 'looking-glass'
        entries.append(dict(prompt=prompt, text=atspi.Text.get_text(node, 0, -1)))
    return dict(entries=entries, visible_names=sorted(name for name in names if name)[:80])


def matches_prompt(snapshot, prompt, text):
    entries = snapshot.get('entries', [])
    return len(entries) == 1 and entries[0] == dict(prompt=prompt, text=text)


def wait_for_prompt(snapshot, prompt, text, timeout, *, clock=time.monotonic, sleep=time.sleep):
    deadline = clock() + timeout
    state = {}
    while clock() < deadline:
        state = snapshot()
        if matches_prompt(state, prompt, text):
            return dict(ready=True, expected_prompt=prompt, expected_text=text, **state)
        sleep(0.1)
    return dict(ready=False, expected_prompt=prompt, expected_text=text, **state)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('prompt', choices=('run-dialog', 'looking-glass'))
    parser.add_argument('--text', default='')
    parser.add_argument('--timeout', type=float, default=15)
    args = parser.parse_args()

    import gi
    gi.require_version('Atspi', '2.0')
    from gi.repository import Atspi
    Atspi.set_timeout(1000, 1000)

    def snapshot():
        try:
            for app in Atspi.get_desktop(0):
                if app.get_name() == 'gnome-shell':
                    return prompt_snapshot(app, Atspi)
            return dict(entries=[], error='GNOME Shell accessibility not ready')
        except Exception as error:
            return dict(entries=[], error=str(error))

    report = wait_for_prompt(snapshot, args.prompt, args.text, args.timeout)
    print(json.dumps(report, ensure_ascii=False))
    return 0 if report['ready'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
