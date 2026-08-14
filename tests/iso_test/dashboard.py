"""Dependency-free live dashboard for the acceptance matrix."""

from __future__ import annotations

import os
import shutil
import sys
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import TextIO


@dataclass
class CaseView:
    identifier: str
    state: str = "pending"
    phase: str = "Waiting to start"
    started_at: float | None = None
    seconds: float | None = None
    error: str = ""


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
        stream: TextIO = sys.stdout,
        live: bool | None = None,
        refresh_seconds: float = 1.0,
    ):
        self.cases = {item: CaseView(item) for item in identifiers}
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

    def start(self) -> None:
        with self._lock:
            if self._started:
                return
            self._started = True
            if self.live:
                self.stream.write("\x1b[?25l")
                self._render_locked()
            else:
                self._write_plain_header()
                for case in self.cases.values():
                    self._write_plain(case)
            self.stream.flush()
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
            case.state = "running"
            case.phase = "Starting disposable virtual machine"
            case.started_at = time.monotonic()
            self._changed(case)

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

    def close(self) -> None:
        if self._closed:
            return
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=self.refresh_seconds + 1)
        with self._lock:
            if self.live:
                self._render_locked()
                self.stream.write("\x1b[?25h\n")
            else:
                passed = sum(item.state == "passed" for item in self.cases.values())
                failed = sum(item.state == "failed" for item in self.cases.values())
                pending = sum(item.state == "pending" for item in self.cases.values())
                self.stream.write(
                    f"\nAcceptance summary: {passed}/{len(self.cases)} passed, "
                    f"{failed} failed, {pending} not started\n"
                    f"Artifacts: {self.artifacts}\n"
                )
            self.stream.flush()
            self._closed = True

    def _changed(self, case: CaseView) -> None:
        if self.live:
            self._render_locked()
        else:
            self._write_plain(case)
        self.stream.flush()

    def _refresh_loop(self) -> None:
        while not self._stop.wait(self.refresh_seconds):
            with self._lock:
                self._render_locked()
                self.stream.flush()

    def _render_locked(self) -> None:
        width = max(72, min(150, shutil.get_terminal_size((110, 30)).columns))
        inner = width - 2
        case_width = min(45, max(30, width // 3))
        state_width = 15
        time_width = 10
        phase_width = inner - case_width - state_width - time_width - 7
        elapsed = _duration(time.monotonic() - self.started_at)
        passed = sum(item.state == "passed" for item in self.cases.values())
        failed = sum(item.state == "failed" for item in self.cases.values())
        completed = passed + failed
        bar_width = min(34, max(18, width - 70))
        filled = round(bar_width * completed / max(1, len(self.cases)))
        bar = "█" * filled + "░" * (bar_width - filled)

        lines = [
            "┌" + "─" * inner + "┐",
            _boxed(" AnduinOS ISO Acceptance ", inner, align="center"),
            "├" + "─" * inner + "┤",
            _boxed(f" ISO: {_fit(self.iso.name, inner - 6)}", inner),
            _boxed(
                f" Arch: {self.architecture}   Cases: {len(self.cases)}   "
                f"Elapsed: {elapsed}",
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
        lines.extend(
            [
                "├" + "─" * inner + "┤",
                _boxed(
                    f" Progress [{bar}] {completed}/{len(self.cases)}   "
                    f"✓ {passed}   ✗ {failed}",
                    inner,
                ),
                _boxed(f" Artifacts: {_fit(str(self.artifacts), inner - 12)}", inner),
                "└" + "─" * inner + "┘",
            ]
        )
        self.stream.write("\x1b[2J\x1b[H" + "\n".join(lines) + "\n")

    def _case_duration(self, case: CaseView) -> str:
        if case.seconds is not None:
            return _duration(case.seconds)
        if case.started_at is not None:
            return _duration(time.monotonic() - case.started_at)
        return "--:--"

    def _write_plain_header(self) -> None:
        self.stream.write(
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
        self.stream.write(
            f"[{elapsed}] {icon} {label:<11} {case.identifier} "
            f"({duration}) — {phase}\n"
        )


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
