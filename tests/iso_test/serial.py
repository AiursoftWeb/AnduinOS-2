"""Marker-based command protocol over a QEMU serial socket."""

from __future__ import annotations

import base64
import os
import re
import select
import socket
import time
import uuid
from dataclasses import dataclass
from pathlib import Path

from .errors import ProtocolError, TestFailure


_ANSI_ESCAPE = re.compile(rb"\x1b(?:\[[0-?]*[ -/]*[@-~]|\][^\x07]*(?:\x07|\x1b\\))")


@dataclass(frozen=True)
class CommandResult:
    stdout: str
    returncode: int


class SerialConsole:
    """Talk to the ephemeral root debug shell enabled by the harness."""

    def __init__(self, path: Path, transcript: Path, timeout: float = 120.0):
        self.path = path
        self.transcript = transcript
        self.timeout = timeout
        self._socket: socket.socket | None = None
        self._buffer = bytearray()
        self._log = None

    def connect(self) -> None:
        self.transcript.parent.mkdir(parents=True, exist_ok=True)
        self._log = self.transcript.open("ab", buffering=0)
        deadline = time.monotonic() + self.timeout
        last_error: OSError | None = None
        while time.monotonic() < deadline:
            try:
                connection = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
                connection.connect(str(self.path))
                connection.setblocking(False)
                self._socket = connection
                return
            except OSError as error:
                last_error = error
                time.sleep(0.1)
        raise ProtocolError(f"Cannot connect to serial socket: {last_error}")

    def close(self) -> None:
        if self._socket is not None:
            self._socket.close()
            self._socket = None
        if self._log is not None:
            self._log.close()
            self._log = None

    def wait_for_shell(self, timeout: float | None = None) -> None:
        """Synchronize without depending on a localized shell prompt."""

        deadline = time.monotonic() + (timeout or self.timeout)
        while time.monotonic() < deadline:
            try:
                result = self.run("true", timeout=min(10.0, deadline - time.monotonic()))
            except ProtocolError:
                self._buffer.clear()
                time.sleep(0.5)
                continue
            if result.returncode == 0:
                self.run(
                    "stty -echo -onlcr < /dev/tty; export LANG=C LC_ALL=C",
                    timeout=10,
                )
                return
        raise ProtocolError("Timed out waiting for the systemd debug shell")

    def wait_for_text(self, value: str, timeout: float) -> None:
        """Wait for an exact guest/firmware token and consume through it."""

        needle = value.encode("utf-8")
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            index = self._buffer.find(needle)
            if index >= 0:
                del self._buffer[: index + len(needle)]
                return
            if self._socket is None:
                raise ProtocolError("Serial socket is not connected")
            ready, _, _ = select.select(
                [self._socket], [], [], min(0.5, deadline - time.monotonic())
            )
            if not ready:
                continue
            chunk = self._socket.recv(65536)
            if not chunk:
                raise ProtocolError("Serial connection closed unexpectedly")
            if self._log is not None:
                self._log.write(chunk)
            self._buffer.extend(chunk)
        raise ProtocolError(f"Timed out waiting for serial text: {value!r}")

    def run(
        self,
        script: str,
        *,
        timeout: float | None = None,
        check: bool = True,
    ) -> CommandResult:
        """Run an arbitrary shell script without shell-quoting it on the wire."""

        token = uuid.uuid4().hex
        start = f"__ANDUINOS_BEGIN_{token}__"
        end = f"__ANDUINOS_END_{token}__"
        payload = base64.b64encode(script.encode("utf-8")).decode("ascii")
        command = (
            f"printf '{start}\\n'; "
            f"printf '%s' '{payload}' | base64 -d | /bin/bash; "
            f"rc=$?; printf '\\n{end}:%s\\n' \"$rc\"\n"
        )
        self._send(command.encode("ascii"))
        raw = self._read_until(
            re.compile(re.escape(end.encode("ascii")) + rb":([0-9]+)"),
            timeout or self.timeout,
        )
        clean = _ANSI_ESCAPE.sub(b"", raw).replace(b"\r", b"")
        start_index = clean.rfind(start.encode("ascii"))
        match = re.search(re.escape(end.encode("ascii")) + rb":([0-9]+)", clean)
        if start_index < 0 or match is None:
            raise ProtocolError("Serial command markers were not returned")
        output_start = start_index + len(start)
        stdout = clean[output_start:match.start()].strip(b"\n").decode(
            "utf-8", errors="replace"
        )
        returncode = int(match.group(1))
        result = CommandResult(stdout=stdout, returncode=returncode)
        if check and returncode != 0:
            raise TestFailure(
                f"Guest command failed with {returncode}: {script.splitlines()[0]}\n"
                f"{stdout}"
            )
        return result

    def upload(self, source: Path, destination: str, mode: int = 0o600) -> None:
        temporary = f"{destination}.tmp-{os.getpid()}"
        self.run(f": > '{temporary}'")
        with source.open("rb") as stream:
            while chunk := stream.read(48 * 1024):
                data = base64.b64encode(chunk).decode("ascii")
                self.run(
                    f"printf '%s' '{data}' | base64 -d >> '{temporary}'"
                )
        self.run(
            "set -e\n"
            f"chmod {mode:o} '{temporary}'\n"
            f"mv '{temporary}' '{destination}'"
        )

    def _send(self, value: bytes) -> None:
        if self._socket is None:
            raise ProtocolError("Serial socket is not connected")
        remaining = memoryview(value)
        deadline = time.monotonic() + self.timeout
        while remaining:
            wait = deadline - time.monotonic()
            if wait <= 0:
                raise ProtocolError(
                    f"Timed out writing {len(value)} bytes to serial socket"
                )
            try:
                _, writable, _ = select.select(
                    [], [self._socket], [], min(0.5, wait)
                )
                if not writable:
                    continue
                sent = self._socket.send(remaining)
            except BlockingIOError:
                continue
            except OSError as error:
                raise ProtocolError(
                    f"Cannot write to serial socket: {error}"
                ) from error
            if sent <= 0:
                raise ProtocolError("Serial socket closed while writing")
            remaining = remaining[sent:]

    def _read_until(self, pattern: re.Pattern[bytes], timeout: float) -> bytes:
        if self._socket is None:
            raise ProtocolError("Serial socket is not connected")
        deadline = time.monotonic() + max(0.1, timeout)
        while time.monotonic() < deadline:
            if pattern.search(self._buffer):
                result = bytes(self._buffer)
                self._buffer.clear()
                return result
            ready, _, _ = select.select(
                [self._socket], [], [], min(0.5, deadline - time.monotonic())
            )
            if not ready:
                continue
            chunk = self._socket.recv(65536)
            if not chunk:
                raise ProtocolError("Serial connection closed unexpectedly")
            if self._log is not None:
                self._log.write(chunk)
            self._buffer.extend(chunk)
        tail = _ANSI_ESCAPE.sub(b"", bytes(self._buffer[-4096:])).decode(
            "utf-8", errors="replace"
        )
        raise ProtocolError(f"Timed out waiting for serial response; tail:\n{tail}")
