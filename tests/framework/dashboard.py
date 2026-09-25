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
    phase: str = "Waiting to start"
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
    suites: dict[str, SuiteView] | None = None


class AcceptanceDashboard:
    """Render test state live on a TTY and as transitions everywhere else."""

    _STYLE = {
        "pending": ("○", "NOT STARTED", "\x1b[2;37m"),
        "running": ("●", "RUNNING", "\x1b[1;36m"),
        "passed": ("✓", "PASSED", "\x1b[1;32m"),
        "failed": ("✗", "FAILED", "\x1b[1;31m"),
        "blocked": ("⊘", "BLOCKED", "\x1b[1;33m"),
    }

    def __init__(
        self,
        identifiers: tuple[str, ...],
        *,
        iso: Path,
        architecture: str,
        artifacts: Path,
        suites: Mapping[str, Mapping[str, tuple[str, ...]]] | None = None,
        stream: TextIO = sys.stdout,
        live: bool | None = None,
        refresh_seconds: float = 1.0,
    ):
        if len(identifiers) != len(set(identifiers)):
            raise ValueError("Acceptance case identifiers must be unique")
        declared_suites = suites or {}
        unknown = set(declared_suites) - set(identifiers)
        if unknown:
            raise ValueError(
                "Checks were declared for unknown case(s): "
                + ", ".join(sorted(unknown))
            )
        missing = set(identifiers) - set(declared_suites)
        if missing:
            raise ValueError("Cases have no declared suites: " + ", ".join(sorted(missing)))
        for case_id, suite_map in declared_suites.items():
            if not suite_map:
                raise ValueError(f"{case_id}: at least one suite is required")
            for suite_id, check_ids in suite_map.items():
                if not check_ids or len(check_ids) != len(set(check_ids)):
                    raise ValueError(f"{case_id}/{suite_id}: checks must be nonempty and unique")
        self.cases = {
            item: CaseView(
                item,
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

    def begin_suite(self, identifier: str, suite_identifier: str) -> None:
        with self._lock:
            case = self.cases[identifier]
            suite = self._suite(case, suite_identifier)
            self._active_identifier = identifier
            self._active_suite = suite_identifier
            suite.state = "running"
            suite.phase = "Starting suite"
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
                    f"{suite_identifier}: undeclared check "
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
            if self._active_identifier == identifier:
                self._active_suite = suite_identifier
            suite.state = status
            suite.seconds = seconds
            suite.error = error
            suite.phase = "All checks passed" if status == "passed" else error
            for check in (suite.checks or {}).values():
                if status == "blocked" and check.state == "pending":
                    check.state = "blocked"
                    check.seconds = 0.0
                    check.detail = error or "Not run: prerequisite failed"
                if check.state == "running":
                    check.state = "failed"
                    check.seconds = max(
                        0.0,
                        time.monotonic() - (check.started_at or time.monotonic()),
                    )
                    check.detail = error or "Suite stopped during this check"
            self._changed_suite(case, suite)

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
            self._changed(case)

    def case_result(self, identifier: str) -> dict[str, object]:
        """Return the aggregate case verdict and its declared suites."""

        with self._lock:
            case = self.cases[identifier]
            from .dashboard_render import case_state

            status = case_state(case)
            child_error = next((suite.error for suite in (case.suites or {}).values()
                                if suite.state in {"failed", "blocked"} and suite.error), "")
            return {
                "id": case.identifier,
                "status": status,
                "seconds": case.seconds,
                "detail": case.error or child_error or case.phase,
                "error": case.error or child_error,
                "suites": self.suite_results(identifier),
            }

    def suite_results(self, identifier: str) -> list[dict[str, object]]:
        with self._lock:
            return [
                {
                    "id": suite.identifier,
                    "status": suite.state,
                    "seconds": suite.seconds,
                    "detail": suite.phase,
                    "error": suite.error,
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
                from .dashboard_render import case_state

                passed = sum(case_state(item) == "passed" for item in self.cases.values())
                failed = sum(case_state(item) == "failed" for item in self.cases.values())
                pending = sum(case_state(item) == "pending" for item in self.cases.values())
                suites = tuple(
                    suite
                    for case in self.cases.values()
                    for suite in (case.suites or {}).values()
                )
                self._write_output(
                    f"\nAcceptance cases: {passed}/{len(self.cases)} passed, "
                    f"{failed} failed, {pending} not started\n"
                )
                if suites:
                    suites_passed = sum(item.state == "passed" for item in suites)
                    suites_failed = sum(item.state == "failed" for item in suites)
                    suites_pending = sum(item.state == "pending" for item in suites)
                    suites_blocked = sum(item.state == "blocked" for item in suites)
                    self._write_output(
                        f"Suites: {suites_passed}/{len(suites)} passed, "
                        f"{suites_failed} failed, {suites_blocked} blocked, {suites_pending} not started\n"
                    )
                checks = tuple(check for suite in suites
                               for check in (suite.checks or {}).values())
                if checks:
                    checks_passed = sum(check.state == "passed" for check in checks)
                    checks_failed = sum(check.state == "failed" for check in checks)
                    checks_blocked = sum(check.state == "blocked" for check in checks)
                    self._write_output(
                        f"Checks: {checks_passed}/{len(checks)} passed, "
                        f"{checks_failed} failed, {checks_blocked} blocked\n"
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
                f"{case.identifier}: undeclared suite {identifier!r}"
            ) from error

    def _refresh_loop(self) -> None:
        while not self._stop.wait(self.refresh_seconds):
            with self._lock:
                self._render_locked()
                self._flush_output()

    def _render_locked(self) -> None:
        from .dashboard_render import render_dashboard

        terminal = shutil.get_terminal_size((110, 30))
        frame = render_dashboard(self, terminal)
        self._write_output("\x1b[2J\x1b[H" + frame + "\n")

    def _case_duration(self, case: CaseView) -> str:
        if case.seconds is not None:
            return _duration(case.seconds)
        if case.started_at is not None:
            return _duration(time.monotonic() - case.started_at)
        return "--:--"

    def _write_plain_header(self) -> None:
        suites = sum(len(case.suites or {}) for case in self.cases.values())
        checks = sum(len(suite.checks or {}) for case in self.cases.values()
                     for suite in (case.suites or {}).values())
        self._write_output(
            "AnduinOS ISO Acceptance\n"
            f"ISO: {self.iso}\n"
            f"Architecture: {self.architecture}\n"
            f"Acceptance cases: {len(self.cases)}\n"
            f"Suites: {suites}\n"
            f"Checks: {checks}\n"
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
