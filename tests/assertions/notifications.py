"""Offline Live desktop quiet-start contract, including Shell-native notices."""

from __future__ import annotations

import json
import shlex
from pathlib import Path

from framework.errors import TestFailure


REPORT = '/tmp/anduinos-live-notifications.json'
OBSERVER = '/tmp/anduinos-live-notifications.mjs'
PROMPT_PROBE = '/tmp/anduinos-shell-prompt.py'


def _wait_shell_prompt(console, evidence: Path, prompt: str, text: str = '', *,
                       timeout: int = 15, check: bool = True) -> bool:
    result = console.run(f"""
uid=$(id -u live)
runuser -u live -- env XDG_RUNTIME_DIR="/run/user/$uid" \\
    DBUS_SESSION_BUS_ADDRESS="unix:path=/run/user/$uid/bus" \\
    python3 {PROMPT_PROBE} {shlex.quote(prompt)} --text {shlex.quote(text)} --timeout {timeout}
""", timeout=timeout + 15, check=False)
    with (evidence / 'live-notifications-ui.jsonl').open('a', encoding='utf-8') as stream:
        stream.write(result.stdout.strip() + '\n')
    # The serial channel also carries GTK/AT-SPI stderr. Preserve warnings in
    # evidence, but parse the probe's JSON line rather than the whole stream.
    reports = []
    for line in result.stdout.splitlines():
        try:
            item = json.loads(line)
        except (ValueError, TypeError):
            continue
        if isinstance(item, dict) and 'ready' in item:
            reports.append(item)
    report = reports[0] if len(reports) == 1 else {}
    ready = (result.returncode == 0 and isinstance(report, dict) and report.get('ready') is True and
             report.get('expected_prompt') == prompt and report.get('expected_text') == text)
    if not ready and check:
        raise TestFailure(f'Live notification UI not ready: {prompt}; see UI evidence')
    return ready


def validate_quiet_start(report: object) -> None:
    """Missing/incomplete observation is a failure, never an empty tray pass."""
    if not isinstance(report, dict):
        raise TestFailure('Notification observer returned an invalid report')
    if report.get('error') or report.get('complete') is not True:
        raise TestFailure(f'Notification observation failed: {report}')
    seconds = report.get('seconds')
    if isinstance(seconds, bool) or not isinstance(seconds, (int, float)) or not 10 <= seconds < 60:
        raise TestFailure(f'Notification observation did not cover 10 seconds: {seconds}')
    notifications = report.get('notifications')
    if not isinstance(notifications, list):
        raise TestFailure('Notification inventory is missing')
    # The observer resolves this one message through the guest's Software
    # catalog, so the exception does not depend on the Live desktop language.
    allowed = report.get('software_update_check_notice')
    allowed = allowed if isinstance(allowed, dict) else {}
    expected = (allowed.get('title'), allowed.get('body'))
    translated = all(isinstance(value, str) and value for value in expected)
    unexpected = [notice for notice in notifications if not (
        translated and isinstance(notice, dict)
        and notice.get('app_id') == 'org.gnome.Software'
        and (notice.get('title'), notice.get('body')) == expected
    )]
    if unexpected:
        raise TestFailure('Offline Live startup produced notifications: ' + json.dumps(
            unexpected, ensure_ascii=False))


def assert_live_notifications_quiet(console, qmp, evidence: Path) -> None:
    """Inventory existing startup notifications, then observe additions for 10s.

    Looking Glass loads a diagnostic module in the actual user Shell without
    enabling unsafe D-Bus Eval, restarting Shell, or disabling any extension.
    It closes itself before the idle observation; notifications are not cleared.
    """
    fixture = Path(__file__).resolve().parents[1] / 'fixtures/live_notifications.mjs'
    before = console.run(r"""
set -euo pipefail
uid=$(id -u live)
pid=$(pgrep -u "$uid" -x gnome-shell)
test -n "$pid"
test -S "/run/user/$uid/bus"
# QMP typing is physical US input. Fail rather than silently changing the
# Live keyboard whose regional propagation is verified independently.
# Shell can exist before its first-login regional initialization has populated
# input sources. Wait only for that empty startup state; never rewrite it or
# tolerate a populated, incorrect layout.
for attempt in $(seq 1 30); do
    sources=$(runuser -u live -- env XDG_RUNTIME_DIR="/run/user/$uid" \
        DBUS_SESSION_BUS_ADDRESS="unix:path=/run/user/$uid/bus" \
        gsettings get org.gnome.desktop.input-sources sources)
    case "$sources" in '@a(ss) []'|'[]') sleep 1 ;; *) break ;; esac
done
printf 'shell-pid=%s\ninput-sources=%s\n' "$pid" "$sources"
# Chinese Live also carries libpinyin; require the initial US source rather
# than incorrectly rejecting additional, legitimate input methods.
[[ "$sources" == "[('xkb', 'us')"* ]]
for iface in /sys/class/net/*; do
    test "$(basename "$iface")" = lo && continue
    carrier=$(cat "$iface/carrier" 2>/dev/null || true)
    test "$carrier" != 1
done
test ! -e /tmp/anduinos-live-notifications.json
""", check=False)
    (evidence / 'live-notifications-session.txt').write_text(before.stdout, encoding='utf-8')
    if before.returncode:
        raise TestFailure('Offline Live notification prerequisites failed; see session evidence')
    try:
        console.upload(fixture, OBSERVER, 0o644)
        console.upload(fixture.with_name('shell_prompt.py'), PROMPT_PROBE, 0o644)
        # A running Shell process does not prove its shortcut handler is ready.
        # Retry opening the empty dialog, never blindly submit a JS expression
        # to whatever happens to own keyboard focus during Live startup.
        for _ in range(3):
            qmp.send_key('esc')
            qmp.send_key('alt-f2', hold_ms=150)
            if _wait_shell_prompt(console, evidence, 'run-dialog', timeout=5, check=False):
                break
        else:
            raise TestFailure('Live Run dialog never became ready; see UI evidence')
        qmp.type_text('lg', interval=0.15)
        _wait_shell_prompt(console, evidence, 'run-dialog', 'lg')
        qmp.send_key('ret')
        _wait_shell_prompt(console, evidence, 'looking-glass')
        expression = f'import("file://{OBSERVER}")'
        qmp.type_text(expression, interval=0.05)
        _wait_shell_prompt(console, evidence, 'looking-glass', expression)
        qmp.send_key('ret')
        result = console.run(f"""
set -euo pipefail
for attempt in $(seq 1 40); do
    if test -f {REPORT} && python3 -c 'import json; r=json.load(open("{REPORT}")); exit(0 if r.get("complete") or r.get("error") else 1)' ; then
        cat {REPORT}
        exit 0
    fi
    sleep 1
done
echo 'Live notification observer never completed' >&2
exit 1
""", timeout=50, check=False)
        (evidence / 'live-notifications-observer.txt').write_text(result.stdout, encoding='utf-8')
        if result.returncode:
            raise TestFailure('Live notification observer never completed; see evidence')
        try:
            report = json.loads(result.stdout.strip())
        except (ValueError, TypeError) as error:
            raise TestFailure('Invalid notification observer JSON; see evidence') from error
        (evidence / 'live-notifications.json').write_text(
            json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
        after = console.run('pgrep -u "$(id -u live)" -x gnome-shell').stdout.strip()
        if f'shell-pid={after}\n' not in before.stdout:
            raise TestFailure('Live GNOME Shell restarted during notification observation')
        validate_quiet_start(report)
    finally:
        try:
            qmp.send_key('esc')
        finally:
            console.run(f'rm -f {OBSERVER} {REPORT} {PROMPT_PROBE}', check=False)
