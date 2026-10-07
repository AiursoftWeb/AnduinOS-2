"""Offline Live desktop quiet-start contract, including Shell-native notices."""

from __future__ import annotations

import json
import time
from pathlib import Path

from framework.errors import TestFailure


REPORT = '/tmp/anduinos-live-notifications.json'
OBSERVER = '/tmp/anduinos-live-notifications.mjs'


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
    if notifications:
        raise TestFailure('Offline Live startup produced notifications: ' + json.dumps(
            notifications, ensure_ascii=False))


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
sources=$(runuser -u live -- env XDG_RUNTIME_DIR="/run/user/$uid" \
    DBUS_SESSION_BUS_ADDRESS="unix:path=/run/user/$uid/bus" \
    gsettings get org.gnome.desktop.input-sources sources)
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
    console.upload(fixture, OBSERVER, 0o644)
    try:
        qmp.send_key('esc')
        qmp.send_key('alt-f2', hold_ms=150)
        time.sleep(1)
        qmp.type_text('lg', interval=0.15)
        qmp.send_key('ret')
        time.sleep(1)
        qmp.type_text(f'import("file://{OBSERVER}")', interval=0.05)
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
            console.run(f'rm -f {OBSERVER} {REPORT}', check=False)
