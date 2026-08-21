"""Dependency-free live dashboard for the acceptance matrix."""

from __future__ import annotations

import errno
import os
import shutil
import sys
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping, TextIO


@dataclass
class CheckView:
    identifier: str
    state: str = "pending"
    detail: str = "Waiting to start"
    started_at: float | None = None
    seconds: float | None = None


@dataclass
class SuiteView:
    identifier: str
    state: str = "pending"
    phase: str = "Waiting for installation base"
    started_at: float | None = None
    seconds: float | None = None
    error: str = ""
    checks: dict[str, CheckView] | None = None


@dataclass
class CaseView:
    identifier: str
    state: str = "pending"
    phase: str = "Waiting to start"
    started_at: float | None = None
    seconds: float | None = None
    error: str = ""
    checks: dict[str, CheckView] | None = None
    suites: dict[str, SuiteView] | None = None


class AcceptanceDashboard:
    """Render test state live on a TTY and as transitions everywhere else."""

    _STYLE = {
        "pending": ("○", "NOT STARTED", "\x1b[2;37m"),
        "running": ("●", "RUNNING", "\x1b[1;36m"),
        "passed": ("✓", "PASSED", "\x1b[1;32m"),
        "failed": ("✗", "FAILED", "\x1b[1;31m"),
    }

    def __init__(
        self,
        identifiers: tuple[str, ...],
        *,
        iso: Path,
        architecture: str,
        artifacts: Path,
        checks: Mapping[str, tuple[str, ...]] | None = None,
        suites: Mapping[str, Mapping[str, tuple[str, ...]]] | None = None,
        stream: TextIO = sys.stdout,
        live: bool | None = None,
        refresh_seconds: float = 1.0,
    ):
        declared_checks = checks or {}
        declared_suites = suites or {}
        unknown = set(declared_checks) - set(identifiers)
        unknown.update(set(declared_suites) - set(identifiers))
        if unknown:
            raise ValueError(
                "Checks were declared for unknown case(s): "
                + ", ".join(sorted(unknown))
            )
        self.cases = {
            item: CaseView(
                item,
                checks={
                    check: CheckView(check)
                    for check in declared_checks.get(item, ())
                },
                suites={
                    suite: SuiteView(
                        suite,
                        checks={check: CheckView(check) for check in suite_checks},
                    )
                    for suite, suite_checks in declared_suites.get(item, {}).items()
                },
            )
            for item in identifiers
        }
        self.iso = iso
        self.architecture = architecture
        self.artifacts = artifacts
        self.stream = stream
        self.refresh_seconds = refresh_seconds
        terminal_columns = shutil.get_terminal_size((110, 30)).columns
        supports_live = (
            bool(getattr(stream, "isatty", lambda: False)())
            and os.environ.get("TERM", "") != "dumb"
            and terminal_columns >= 72
        )
        self.live = supports_live if live is None else live
        self.color = "NO_COLOR" not in os.environ
        self.started_at = time.monotonic()
        self._lock = threading.RLock()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._started = False
        self._closed = False
        self._active_identifier: str | None = None
        self._active_suite: str | None = None
        self._output_available = True

    def start(self) -> None:
        with self._lock:
            if self._started:
                return
            self._started = True
            if self.live:
                self._write_output("\x1b[?25l")
                self._render_locked()
            else:
                self._write_plain_header()
                for case in self.cases.values():
                    self._write_plain(case)
            self._flush_output()
        if self.live:
            self._thread = threading.Thread(
                target=self._refresh_loop,
                name="acceptance-dashboard",
                daemon=True,
            )
            self._thread.start()

    def begin(self, identifier: str) -> None:
        with self._lock:
            case = self.cases[identifier]
            self._active_identifier = identifier
            self._active_suite = None
            case.state = "running"
            case.phase = "Starting disposable virtual machine"
            case.started_at = time.monotonic()
            self._changed(case)
            if not self.live:
                for check in (case.checks or {}).values():
                    self._write_plain_check(case, check)
                self._flush_output()

    def begin_suite(self, identifier: str, suite_identifier: str) -> None:
        with self._lock:
            case = self.cases[identifier]
            suite = self._suite(case, suite_identifier)
            self._active_identifier = identifier
            self._active_suite = suite_identifier
            suite.state = "running"
            suite.phase = "Creating disposable overlay"
            suite.started_at = time.monotonic()
            self._changed_suite(case, suite)
            if not self.live:
                for check in (suite.checks or {}).values():
                    self._write_plain_suite_check(case, suite, check)
                self._flush_output()

    def suite_phase(
        self,
        identifier: str,
        suite_identifier: str,
        message: str,
    ) -> None:
        with self._lock:
            case = self.cases[identifier]
            suite = self._suite(case, suite_identifier)
            if suite.state == "pending":
                suite.state = "running"
                suite.started_at = time.monotonic()
            if suite.phase == message:
                return
            suite.phase = message
            self._changed_suite(case, suite)

    def suite_check(
        self,
        identifier: str,
        suite_identifier: str,
        check_identifier: str,
        state: str,
        detail: str = "",
    ) -> None:
        if state not in self._STYLE:
            raise ValueError(f"Unknown feature check state: {state}")
        with self._lock:
            case = self.cases[identifier]
            suite = self._suite(case, suite_identifier)
            try:
                check = (suite.checks or {})[check_identifier]
            except KeyError as error:
                raise ValueError(
                    f"{suite_identifier}: undeclared feature check "
                    f"{check_identifier!r}"
                ) from error
            now = time.monotonic()
            if state == "running" and check.started_at is None:
                check.started_at = now
            if state in {"passed", "failed"}:
                if check.started_at is None:
                    check.started_at = now
                check.seconds = now - check.started_at
            check.state = state
            if detail:
                check.detail = detail
            elif state == "passed":
                check.detail = "All assertions passed"
            self._changed_suite_check(case, suite, check)

    def complete_suite(
        self,
        identifier: str,
        suite_identifier: str,
        status: str,
        seconds: float,
        error: str = "",
    ) -> None:
        with self._lock:
            case = self.cases[identifier]
            suite = self._suite(case, suite_identifier)
            suite.state = status
            suite.seconds = seconds
            suite.error = error
            suite.phase = "All checks passed" if status == "passed" else error
            for check in (suite.checks or {}).values():
                if check.state == "running":
                    check.state = "failed"
                    check.seconds = max(
                        0.0,
                        time.monotonic() - (check.started_at or time.monotonic()),
                    )
                    check.detail = error or "Suite stopped during this check"
            self._changed_suite(case, suite)

    def check(
        self,
        identifier: str,
        check_identifier: str,
        state: str,
        detail: str = "",
    ) -> None:
        """Record one real assertion boundary within an installation case."""

        if state not in self._STYLE:
            raise ValueError(f"Unknown check state: {state}")
        with self._lock:
            case = self.cases[identifier]
            checks = case.checks or {}
            try:
                check = checks[check_identifier]
            except KeyError as error:
                raise ValueError(
                    f"{identifier}: undeclared check event {check_identifier!r}"
                ) from error
            now = time.monotonic()
            if state == "running" and check.started_at is None:
                check.started_at = now
            if state in {"passed", "failed"}:
                if check.started_at is None:
                    check.started_at = now
                check.seconds = now - check.started_at
            check.state = state
            if detail:
                check.detail = detail
            elif state == "passed":
                check.detail = "All assertions passed"
            self._changed_check(case, check)

    def phase(self, identifier: str, message: str) -> None:
        with self._lock:
            case = self.cases[identifier]
            if case.state == "pending":
                case.state = "running"
                case.started_at = time.monotonic()
            if case.phase == message:
                return
            case.phase = message
            self._changed(case)

    def complete(
        self,
        identifier: str,
        status: str,
        seconds: float,
        error: str = "",
    ) -> None:
        with self._lock:
            case = self.cases[identifier]
            case.state = status
            case.seconds = seconds
            case.error = error
            case.phase = "All assertions passed" if status == "passed" else error
            for check in (case.checks or {}).values():
                if check.state == "running":
                    check.state = "failed"
                    check.seconds = max(
                        0.0,
                        time.monotonic() - (check.started_at or time.monotonic()),
                    )
                    check.detail = error or "Scenario stopped during this check"
            self._changed(case)

    def check_results(self, identifier: str) -> list[dict[str, object]]:
        """Return the same child verdicts shown by the dashboard."""

        with self._lock:
            return [
                {
                    "id": check.identifier,
                    "status": check.state,
                    "seconds": check.seconds,
                    "detail": check.detail,
                }
                for check in (self.cases[identifier].checks or {}).values()
            ]

    def case_result(self, identifier: str) -> dict[str, object]:
        """Return the parent verdict exactly as rendered by the dashboard."""

        with self._lock:
            case = self.cases[identifier]
            return {
                "id": case.identifier,
                "status": case.state,
                "seconds": case.seconds,
                "detail": case.phase,
                "error": case.error,
                "checks": self.check_results(identifier),
            }

    def suite_results(self, identifier: str) -> list[dict[str, object]]:
        with self._lock:
            return [
                {
                    "id": suite.identifier,
                    "status": suite.state,
                    "seconds": suite.seconds,
                    "detail": suite.phase,
                    "checks": [
                        {
                            "id": check.identifier,
                            "status": check.state,
                            "seconds": check.seconds,
                            "detail": check.detail,
                        }
                        for check in (suite.checks or {}).values()
                    ],
                }
                for suite in (self.cases[identifier].suites or {}).values()
            ]

    def close(self) -> None:
        if self._closed:
            return
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=self.refresh_seconds + 1)
        with self._lock:
            if self.live:
                self._render_locked()
                self._write_output("\x1b[?25h\n")
            else:
                passed = sum(item.state == "passed" for item in self.cases.values())
                failed = sum(item.state == "failed" for item in self.cases.values())
                pending = sum(item.state == "pending" for item in self.cases.values())
                suites = tuple(
                    suite
                    for case in self.cases.values()
                    for suite in (case.suites or {}).values()
                )
                self._write_output(
                    f"\nInstallation scenarios: {passed}/{len(self.cases)} passed, "
                    f"{failed} failed, {pending} not started\n"
                )
                if suites:
                    suites_passed = sum(item.state == "passed" for item in suites)
                    suites_failed = sum(item.state == "failed" for item in suites)
                    suites_pending = sum(item.state == "pending" for item in suites)
                    self._write_output(
                        f"Feature suites: {suites_passed}/{len(suites)} passed, "
                        f"{suites_failed} failed, {suites_pending} not started\n"
                    )
                self._write_output(f"Artifacts: {self.artifacts}\n")
            self._flush_output()
            self._closed = True

    def _changed(self, case: CaseView) -> None:
        if self.live:
            self._render_locked()
        else:
            self._write_plain(case)
        self._flush_output()

    def _changed_check(self, case: CaseView, check: CheckView) -> None:
        if self.live:
            self._render_locked()
        else:
            self._write_plain_check(case, check)
        self._flush_output()

    def _changed_suite(self, case: CaseView, suite: SuiteView) -> None:
        if self.live:
            self._render_locked()
        else:
            self._write_plain_suite(case, suite)
        self._flush_output()

    def _changed_suite_check(
        self,
        case: CaseView,
        suite: SuiteView,
        check: CheckView,
    ) -> None:
        if self.live:
            self._render_locked()
        else:
            self._write_plain_suite_check(case, suite, check)
        self._flush_output()

    @staticmethod
    def _suite(case: CaseView, identifier: str) -> SuiteView:
        try:
            return (case.suites or {})[identifier]
        except KeyError as error:
            raise ValueError(
                f"{case.identifier}: undeclared feature suite {identifier!r}"
            ) from error

    def _refresh_loop(self) -> None:
        while not self._stop.wait(self.refresh_seconds):
            with self._lock:
                self._render_locked()
                self._flush_output()

    def _render_locked(self) -> None:
        terminal = shutil.get_terminal_size((110, 30))
        width = max(72, min(150, terminal.columns))
        inner = width - 2
        case_width = min(45, max(30, width // 3))
        state_width = 15
        time_width = 10
        phase_width = inner - case_width - state_width - time_width - 7
        elapsed = _duration(time.monotonic() - self.started_at)
        all_suites = tuple(
            suite
            for case in self.cases.values()
            for suite in (case.suites or {}).values()
        )
        all_work = (*self.cases.values(), *all_suites)
        passed = sum(item.state == "passed" for item in all_work)
        failed = sum(item.state == "failed" for item in all_work)
        completed = passed + failed
        progress_total = len(all_work)
        bar_width = min(34, max(18, width - 70))
        filled = round(bar_width * completed / max(1, len(all_work)))
        bar = "█" * filled + "░" * (bar_width - filled)

        active = (
            self.cases.get(self._active_identifier)
            if self._active_identifier is not None
            else None
        )
        active_suite = (
            self._suite(active, self._active_suite)
            if active is not None and self._active_suite is not None
            else None
        )
        compact = bool(
            active is not None
            and (active.checks or active_suite is not None)
            and terminal.lines < len(self.cases) + 18
        )

        if compact:
            lines = [
                "┌" + "─" * inner + "┐",
                _boxed(" AnduinOS ISO Acceptance ", inner, align="center"),
                "├" + "─" * inner + "┤",
                _boxed(
                    _fit(
                        f" ISO: {self.iso.name}   Arch: {self.architecture}   "
                        f"Cases: {len(self.cases)}   Suites: {len(all_suites)}   "
                        f"Elapsed: {elapsed}",
                        inner,
                    ),
                    inner,
                ),
                "├" + "─" * inner + "┤",
            ]
        else:
            lines = [
                "┌" + "─" * inner + "┐",
                _boxed(" AnduinOS ISO Acceptance ", inner, align="center"),
                "├" + "─" * inner + "┤",
                _boxed(f" ISO: {_fit(self.iso.name, inner - 6)}", inner),
                _boxed(
                    f" Arch: {self.architecture}   Cases: {len(self.cases)}   "
                    f"Suites: {len(all_suites)}   Elapsed: {elapsed}",
                    inner,
                ),
                "├" + "─" * inner + "┤",
                _boxed(
                    f"  STATE{' ' * (state_width - 7)} "
                    f"CASE{' ' * (case_width - 4)} "
                    f"TIME{' ' * (time_width - 4)} PHASE",
                    inner,
                ),
                "├" + "─" * inner + "┤",
            ]
        for case in self.cases.values():
            icon, label, color = self._STYLE[case.state]
            state = f"{icon} {label}".ljust(state_width)
            if self.color:
                state = f"{color}{state}\x1b[0m"
            duration = self._case_duration(case)
            phase = case.phase or ""
            row = (
                f" {state} {_fit(case.identifier, case_width):<{case_width}} "
                f"{duration:>{time_width}} {_fit(phase, phase_width)}"
            )
            lines.append(_boxed(row, inner, visible_ansi=self.color))
        if active_suite is not None:
            visible_suites = tuple((active.suites or {}).values())
            lines.extend(
                [
                    "├" + "─" * inner + "┤",
                    _boxed(f" Feature suites — {active.identifier}", inner),
                ]
            )
            for suite in visible_suites:
                icon, label, color = self._STYLE[suite.state]
                state = f"{icon} {label}".ljust(state_width)
                if self.color:
                    state = f"{color}{state}\x1b[0m"
                row = (
                    f"   {state} {_fit(suite.identifier, case_width):<{case_width}} "
                    f"{_fit(suite.phase, max(1, inner - state_width - case_width - 6))}"
                )
                lines.append(_boxed(row, inner, visible_ansi=self.color))
            checks = tuple((active_suite.checks or {}).values())
            check_owner = active_suite.identifier
        elif active is not None and active.checks:
            checks = tuple(active.checks.values())
            check_owner = active.identifier
        else:
            checks = ()
            check_owner = ""
        if checks:
            completed_checks = sum(
                item.state in {"passed", "failed"} for item in checks
            )
            fixed_rows = 11 if compact else 15
            suite_rows = (
                len(active.suites or {}) + 2 if active_suite is not None else 0
            )
            maximum = max(
                1,
                terminal.lines - len(self.cases) - fixed_rows - suite_rows,
            )
            visible, first, last = _check_window(checks, maximum)
            lines.extend(
                [
                    "├" + "─" * inner + "┤",
                    _boxed(
                        f" Checks — {_fit(check_owner, max(1, inner - 34))} "
                        f"({completed_checks}/{len(checks)} complete; "
                        f"showing {first}-{last})",
                        inner,
                    ),
                ]
            )
            check_name_width = min(38, max(24, width // 3))
            check_detail_width = inner - state_width - check_name_width - 6
            for check in visible:
                icon, label, color = self._STYLE[check.state]
                state = f"{icon} {label}".ljust(state_width)
                if self.color:
                    state = f"{color}{state}\x1b[0m"
                row = (
                    f"   {state} "
                    f"{_fit(check.identifier, check_name_width):<{check_name_width}} "
                    f"{_fit(check.detail, check_detail_width)}"
                )
                lines.append(_boxed(row, inner, visible_ansi=self.color))
        lines.extend(
            [
                "├" + "─" * inner + "┤",
                _boxed(
                    f" Progress [{bar}] {completed}/{progress_total}   "
                    f"✓ {passed}   ✗ {failed}",
                    inner,
                ),
                _boxed(f" Artifacts: {_fit(str(self.artifacts), inner - 12)}", inner),
                "└" + "─" * inner + "┘",
            ]
        )
        self._write_output("\x1b[2J\x1b[H" + "\n".join(lines) + "\n")

    def _case_duration(self, case: CaseView) -> str:
        if case.seconds is not None:
            return _duration(case.seconds)
        if case.started_at is not None:
            return _duration(time.monotonic() - case.started_at)
        return "--:--"

    def _write_plain_header(self) -> None:
        self._write_output(
            "AnduinOS ISO Acceptance\n"
            f"ISO: {self.iso}\n"
            f"Architecture: {self.architecture}\n"
            f"Cases: {len(self.cases)}\n"
        )

    def _write_plain(self, case: CaseView) -> None:
        icon, label, _color = self._STYLE[case.state]
        elapsed = _duration(time.monotonic() - self.started_at)
        duration = self._case_duration(case)
        phase = case.phase.replace("\n", " | ")
        self._write_output(
            f"[{elapsed}] {icon} {label:<11} {case.identifier} "
            f"({duration}) — {phase}\n"
        )

    def _write_plain_check(self, case: CaseView, check: CheckView) -> None:
        icon, label, _color = self._STYLE[check.state]
        elapsed = _duration(time.monotonic() - self.started_at)
        duration = self._check_duration(check)
        detail = check.detail.replace("\n", " | ")
        self._write_output(
            f"[{elapsed}]   {icon} {label:<11} {case.identifier} / "
            f"{check.identifier} ({duration}) — {detail}\n"
        )

    def _write_plain_suite(self, case: CaseView, suite: SuiteView) -> None:
        icon, label, _color = self._STYLE[suite.state]
        elapsed = _duration(time.monotonic() - self.started_at)
        duration = self._suite_duration(suite)
        phase = suite.phase.replace("\n", " | ")
        self._write_output(
            f"[{elapsed}]   {icon} {label:<11} {case.identifier} / "
            f"{suite.identifier} ({duration}) — {phase}\n"
        )

    def _write_plain_suite_check(
        self,
        case: CaseView,
        suite: SuiteView,
        check: CheckView,
    ) -> None:
        icon, label, _color = self._STYLE[check.state]
        elapsed = _duration(time.monotonic() - self.started_at)
        duration = self._check_duration(check)
        detail = check.detail.replace("\n", " | ")
        self._write_output(
            f"[{elapsed}]     {icon} {label:<11} {case.identifier} / "
            f"{suite.identifier} / {check.identifier} ({duration}) — {detail}\n"
        )

    def _write_output(self, value: str) -> None:
        if not self._output_available:
            return
        try:
            self.stream.write(value)
        except OSError as error:
            if error.errno not in {errno.EBADF, errno.EIO, errno.EPIPE}:
                raise
            # A disconnected terminal must not replace the actual assertion,
            # interrupt, or native-crash result.  State and JSON evidence keep
            # progressing; only further presentation is disabled.
            self._output_available = False
            self._stop.set()

    def _flush_output(self) -> None:
        if not self._output_available:
            return
        try:
            self.stream.flush()
        except OSError as error:
            if error.errno not in {errno.EBADF, errno.EIO, errno.EPIPE}:
                raise
            self._output_available = False
            self._stop.set()

    @staticmethod
    def _suite_duration(suite: SuiteView) -> str:
        if suite.seconds is not None:
            return _duration(suite.seconds)
        if suite.started_at is not None:
            return _duration(time.monotonic() - suite.started_at)
        return "--:--"

    @staticmethod
    def _check_duration(check: CheckView) -> str:
        if check.seconds is not None:
            return _duration(check.seconds)
        if check.started_at is not None:
            return _duration(time.monotonic() - check.started_at)
        return "--:--"


def _duration(seconds: float) -> str:
    total = max(0, int(seconds))
    hours, remainder = divmod(total, 3600)
    minutes, secs = divmod(remainder, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{secs:02d}"
    return f"{minutes:02d}:{secs:02d}"


def _fit(value: object, width: int) -> str:
    text = str(value).replace("\n", " ")
    if len(text) <= width:
        return text
    if width <= 1:
        return text[:width]
    return text[: width - 1] + "…"


def _check_window(
    checks: tuple[CheckView, ...],
    maximum: int,
) -> tuple[tuple[CheckView, ...], int, int]:
    """Keep the running check visible without overflowing a small terminal."""

    maximum = max(1, min(maximum, len(checks)))
    focus = next(
        (index for index, item in enumerate(checks) if item.state == "running"),
        next(
            (index for index, item in enumerate(checks) if item.state == "failed"),
            next(
                (index for index, item in enumerate(checks) if item.state == "pending"),
                len(checks) - 1,
            ),
        ),
    )
    start = max(0, min(focus - maximum // 2, len(checks) - maximum))
    end = start + maximum
    return checks[start:end], start + 1, end


def _boxed(
    value: str,
    inner: int,
    *,
    align: str = "left",
    visible_ansi: bool = False,
) -> str:
    visible = len(value)
    if visible_ansi:
        visible -= value.count("\x1b[0m") * 4
        for code in ("\x1b[2;37m", "\x1b[1;36m", "\x1b[1;32m", "\x1b[1;31m"):
            visible -= value.count(code) * len(code)
    padding = max(0, inner - visible)
    if align == "center":
        left = padding // 2
        right = padding - left
        return "│" + " " * left + value + " " * right + "│"
    return "│" + value + " " * padding + "│"
