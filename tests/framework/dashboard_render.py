"""Read-only responsive presentation of installation and feature verdicts."""

from __future__ import annotations

import re
import time
import unicodedata
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .dashboard import AcceptanceDashboard, CaseView


_ANSI = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")
_WIDE_COLUMNS = 120


def case_state(case: CaseView) -> str:
    """Aggregate for display only; never overwrite the installation verdict."""
    suites = tuple((case.suites or {}).values())
    if case.state == "failed" or any(suite.state == "failed" for suite in suites):
        return "failed"
    if any(suite.state == "blocked" for suite in suites):
        return "blocked"
    if case.state != "passed":
        return case.state
    return "passed" if all(suite.state == "passed" for suite in suites) else "running"


def _plain(value: object) -> str:
    text = _ANSI.sub("", str(value))
    return "".join(" " if unicodedata.category(char).startswith("C") else char
                   for char in text)


def _char_width(char: str) -> int:
    if unicodedata.combining(char):
        return 0
    return 2 if unicodedata.east_asian_width(char) in {"W", "F"} else 1


def display_width(text: str) -> int:
    return sum(_char_width(char) for char in _ANSI.sub("", text))


def _fit(value: object, width: int) -> str:
    text = _plain(value)
    if display_width(text) <= width:
        return text
    result = ""
    used = 0
    for char in text:
        size = _char_width(char)
        if used + size > width - 1:
            break
        result += char
        used += size
    return result + "…" if width > 0 else ""


def _cell(value: object, width: int, color: str = "", selected: bool = False) -> str:
    text = _fit(value, width)
    text += " " * max(0, width - display_width(text))
    if color:
        return color + ("\x1b[7m" if selected else "") + text + "\x1b[0m"
    return text


def _window(items, count: int, focus: int | None = None):
    if not items:
        return (), 0, 0
    count = max(1, min(count, len(items)))
    if focus is None:
        focus = next((i for state in ("running", "failed", "pending")
                      for i, item in enumerate(items) if item.state == state), len(items) - 1)
    start = max(0, min(focus - count // 2, len(items) - count))
    return items[start:start + count], start + 1, start + count


def _pad(rows: list[str], width: int, height: int) -> list[str]:
    return rows[:height] + [" " * width] * max(0, height - len(rows))


def _color(dashboard, state):
    return dashboard._STYLE[state][2] if dashboard.color else ""


def _case_panel(dashboard, width: int, height: int) -> list[str]:
    cases = tuple(dashboard.cases.values())
    focus = next((i for i, case in enumerate(cases)
                  if case.identifier == dashboard._active_identifier), 0)
    compact = height < 4
    visible, first, last = _window(cases, height - 1 if compact else (height - 2) // 2, focus)
    rows = [_cell(" Installation cases · overall status", width)]
    if not compact:
        rows.append(_cell(f" Showing {first}-{last}/{len(cases)} · install + assigned suites", width))
    for case in visible:
        state = case_state(case)
        selected = case.identifier == dashboard._active_identifier
        icon = dashboard._STYLE[state][0]
        color = _color(dashboard, state)
        suites = tuple((case.suites or {}).values())
        passed = sum(suite.state == "passed" for suite in suites)
        progress = f"{passed}/{len(suites)}" if suites else "—"
        install = {"pending": "WAIT", "running": "RUN", "passed": "OK", "failed": "FAIL"}[case.state]
        stage = {"pending": "NOT STARTED", "failed": "FAILED", "passed": "ALL PASSED", "blocked": "BLOCKED"}.get(state)
        if stage is None:
            stage = "INSTALLING" if case.state != "passed" else "TESTING"
        prefix = f"{'▶' if selected else ' '} {icon} "
        if compact:
            rows.append(_cell(f"{prefix}{stage} · {case.identifier}", width, color, selected))
        else:
            rows.append(_cell(f"{prefix}{case.identifier}", width, color, selected))
            rows.append(_cell(f"    {stage} · Install {install} · Suites {progress}", width, color, selected))
    return _pad(rows, width, height)


def _suite_panel(dashboard, active, width: int, height: int) -> list[str]:
    name = active.identifier if active is not None else "waiting"
    rows = [_cell(f" Feature suites — {name}", width)]
    suites = tuple((active.suites or {}).values()) if active is not None else ()
    if not suites:
        message = " No feature suites assigned" if active else " Waiting for an installation case"
        if active is not None and active.error:
            message = " Installation failed: " + active.error
        rows.append(_cell(message, width, _color(dashboard, active.state) if active else ""))
        if active is not None:
            rows.append(_cell(" " + active.phase, width, _color(dashboard, active.state)))
        return _pad(rows, width, height)
    focus = next((i for i, suite in enumerate(suites)
                  if suite.identifier == dashboard._active_suite), None)
    compact = height < 4
    visible, first, last = _window(suites, height - (1 if compact else 2), focus)
    passed = sum(suite.state == "passed" for suite in suites)
    if not compact:
        rows.append(_cell(f" {passed}/{len(suites)} passed · showing {first}-{last}", width))
    for suite in visible:
        icon, label, _ = dashboard._STYLE[suite.state]
        if suite.state == "pending":
            label = "QUEUED" if active.state == "passed" else "WAIT BASE"
        checks = tuple((suite.checks or {}).values())
        done = sum(check.state in {"passed", "failed"} for check in checks)
        suffix = f"{label} {done}/{len(checks)}"
        name_width = max(1, width - len(suffix) - 6)
        name = _fit(suite.identifier, name_width)
        name += " " * max(0, name_width - display_width(name))
        rows.append(_cell(f" {icon} {name}  {suffix}", width, _color(dashboard, suite.state)))
    return _pad(rows, width, height)


def _check_panel(dashboard, active, suite, width: int, height: int) -> list[str]:
    owner = suite if suite is not None else active
    checks = tuple((owner.checks or {}).values()) if owner is not None else ()
    name = owner.identifier if owner is not None else "waiting"
    rows = [_cell(f" Checks — {name}", width)]
    if not checks:
        detail = " FAILED: " + owner.error if owner is not None and owner.error else " Waiting for checks"
        rows.append(_cell(detail, width))
        return _pad(rows, width, height)
    compact = height < 4
    visible, first, last = _window(checks, height - 1 if compact else (height - 2) // 2)
    done = sum(check.state in {"passed", "failed"} for check in checks)
    if not compact:
        detail = (f" {dashboard._STYLE[owner.state][1]}: " + owner.error if owner.error
                  else f" {done}/{len(checks)} complete · showing {first}-{last}")
        rows.append(_cell(detail, width, _color(dashboard, owner.state) if owner.error else ""))
    for check in visible:
        icon, label, _ = dashboard._STYLE[check.state]
        color = _color(dashboard, check.state)
        rows.append(_cell(f" {icon} {check.identifier}", width, color))
        if not compact:
            rows.append(_cell(f"   {label}: {check.detail}", width, color))
    return _pad(rows, width, height)


def render_dashboard(dashboard: AcceptanceDashboard, terminal) -> str:
    """Render a single bounded frame without mutating any execution state."""
    width = max(1, min(180, terminal.columns))
    inner = width - 2
    active = dashboard.cases.get(dashboard._active_identifier)
    suite = ((active.suites or {}).get(dashboard._active_suite)
             if active is not None else None)
    all_suites = tuple(suite for case in dashboard.cases.values()
                       for suite in (case.suites or {}).values())
    work = (*dashboard.cases.values(), *all_suites)
    passed = sum(item.state == "passed" for item in work)
    failed = sum(item.state == "failed" for item in work)
    blocked = sum(item.state == "blocked" for item in work)
    elapsed = max(0, int(time.monotonic() - dashboard.started_at))
    minutes, seconds = divmod(elapsed, 60)
    clock = f"{minutes}:{seconds:02d}"
    if width < 40 or terminal.lines < 18:
        # There is not room for three bordered panels. Keep a safe, useful
        # summary until the terminal is enlarged instead of scrolling it.
        focus = suite if suite is not None else active
        checks = tuple((focus.checks or {}).values()) if focus is not None else ()
        visible, _, _ = _window(checks, 1)
        summary = ["AnduinOS ISO Acceptance", "Enlarge terminal for three panels",
                   f"Case: {active.identifier if active else 'waiting'}",
                   f"Suite: {suite.identifier if suite else 'none'}",
                   f"Check: {visible[0].identifier if visible else 'waiting'}",
                   f"Progress {passed + failed + blocked}/{len(work)} · ✓ {passed} · ✗ {failed} · ⊘ {blocked} · {clock}",
                   f"Artifacts: {dashboard.artifacts}"]
        return "\n".join(_fit(line, width) for line in summary[:max(1, terminal.lines - 1)])
    body_height = terminal.lines - 10
    lines = ["┌" + "─" * inner + "┐",
             "│" + _cell(" AnduinOS ISO Acceptance", inner) + "│",
             "│" + _cell(f" ISO: {dashboard.iso.name}", inner) + "│",
             "│" + _cell(f" Arch: {dashboard.architecture} · Cases: {len(dashboard.cases)} · Suites: {len(all_suites)}", inner) + "│"]
    if width >= _WIDE_COLUMNS:
        left = max(46, min(64, inner * 2 // 5))
        right = inner - left - 1
        suite_count = len(active.suites or {}) if active is not None else 0
        top_height = min(max(3, suite_count + 2), max(3, body_height // 2))
        bottom_height = body_height - top_height - 1
        left_rows = _case_panel(dashboard, left, body_height)
        top = _suite_panel(dashboard, active, right, top_height)
        bottom = _check_panel(dashboard, active, suite, right, bottom_height)
        lines.append("├" + "─" * left + "┬" + "─" * right + "┤")
        for index, row in enumerate(left_rows):
            if index == top_height:
                lines.append("│" + row + "├" + "─" * right + "┤")
            else:
                detail = top[index] if index < top_height else bottom[index - top_height - 1]
                lines.append("│" + row + "│" + detail + "│")
        lines.append("├" + "─" * left + "┴" + "─" * right + "┤")
    else:
        # Stack the same panels; window each list around its active item.
        case_height = max(2, min(2 + 2 * len(dashboard.cases), (body_height - 2) // 3))
        suite_count = len(active.suites or {}) if active is not None else 0
        suite_height = max(2, min(2 + suite_count, (body_height - case_height - 2) // 2))
        check_height = body_height - case_height - suite_height - 2
        for rows in (_case_panel(dashboard, inner, case_height),
                     _suite_panel(dashboard, active, inner, suite_height),
                     _check_panel(dashboard, active, suite, inner, check_height)):
            lines.append("├" + "─" * inner + "┤")
            lines.extend("│" + row + "│" for row in rows)
        lines.append("├" + "─" * inner + "┤")
    complete = passed + failed + blocked
    bar_width = max(0, min(24, inner - 65))
    filled = round(bar_width * complete / max(1, len(work)))
    bar = "[" + "█" * filled + "░" * (bar_width - filled) + "] " if bar_width else ""
    lines.extend([
        "│" + _cell(f" Progress {bar}{complete}/{len(work)} · ✓ {passed} · ✗ {failed} · ⊘ {blocked} · Elapsed {clock}", inner) + "│",
        "│" + _cell(f" Artifacts: {dashboard.artifacts}", inner) + "│",
        "└" + "─" * inner + "┘",
    ])
    return "\n".join(lines)
