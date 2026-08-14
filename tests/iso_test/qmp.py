"""Small synchronous QEMU Machine Protocol client."""

from __future__ import annotations

import json
import socket
import time
from pathlib import Path

from .errors import ProtocolError


_KEY_NAMES = {
    " ": "spc",
    "=": "equal",
    ",": "comma",
    ".": "dot",
    "/": "slash",
    "-": "minus",
    "_": "shift-minus",
    ":": "shift-semicolon",
    "!": "shift-1",
    "@": "shift-2",
    "$": "shift-4",
}


class QmpClient:
    def __init__(self, path: Path, timeout: float = 30.0):
        self.path = path
        self.timeout = timeout
        self._socket: socket.socket | None = None
        self._stream = None
        self.events: list[dict[str, object]] = []
        self._next_id = 1

    def connect(self) -> None:
        deadline = time.monotonic() + self.timeout
        last_error: OSError | None = None
        while time.monotonic() < deadline:
            try:
                connection = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
                connection.settimeout(self.timeout)
                connection.connect(str(self.path))
                self._socket = connection
                self._stream = connection.makefile("rwb", buffering=0)
                greeting = self._read_message(deadline)
                if "QMP" not in greeting:
                    raise ProtocolError("QMP greeting is missing")
                self.execute("qmp_capabilities")
                return
            except OSError as error:
                last_error = error
                time.sleep(0.1)
        raise ProtocolError(f"Cannot connect to QMP socket: {last_error}")

    def close(self) -> None:
        if self._stream is not None:
            self._stream.close()
            self._stream = None
        if self._socket is not None:
            self._socket.close()
            self._socket = None

    def execute(
        self,
        command: str,
        arguments: dict[str, object] | None = None,
    ) -> object:
        if self._stream is None:
            raise ProtocolError("QMP is not connected")
        identifier = self._next_id
        self._next_id += 1
        request: dict[str, object] = {"execute": command, "id": identifier}
        if arguments:
            request["arguments"] = arguments
        self._stream.write(json.dumps(request).encode("utf-8") + b"\n")
        deadline = time.monotonic() + self.timeout
        while True:
            response = self._read_message(deadline)
            if "event" in response:
                self.events.append(response)
                continue
            if response.get("id") != identifier:
                raise ProtocolError("QMP response ID does not match request")
            if "error" in response:
                raise ProtocolError(f"QMP {command} failed: {response['error']}")
            return response.get("return")

    def hmp(self, command: str) -> str:
        result = self.execute(
            "human-monitor-command",
            {"command-line": command},
        )
        return str(result or "")

    def send_key(self, key: str, hold_ms: int = 50) -> None:
        # HMP separates the optional hold time with whitespace. A comma is
        # parsed as part of the key name and silently returns an HMP error
        # string inside an otherwise successful QMP response.
        response = self.hmp(f"sendkey {key} {hold_ms}")
        if "invalid parameter" in response.casefold():
            raise ProtocolError(f"QEMU rejected key {key!r}: {response.strip()}")

    def type_text(
        self,
        value: str,
        interval: float = 0.12,
    ) -> None:
        for character in value:
            key = _key_name(character)
            # The release must happen before the next key. This matters for
            # shifted characters: overlapping events otherwise turn the next
            # word uppercase and GRUB receives a corrupted command line.
            self.send_key(key, hold_ms=5)
            if interval:
                time.sleep(interval)

    def set_link(self, name: str, *, up: bool) -> None:
        self.execute("set_link", {"name": name, "up": up})

    def screendump(self, destination: Path) -> None:
        destination.parent.mkdir(parents=True, exist_ok=True)
        self.execute("screendump", {"filename": str(destination)})

    def quit(self) -> None:
        try:
            self.execute("quit")
        except (ProtocolError, BrokenPipeError, ConnectionResetError):
            pass

    def _read_message(self, deadline: float) -> dict[str, object]:
        if self._stream is None or self._socket is None:
            raise ProtocolError("QMP is not connected")
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise ProtocolError("Timed out waiting for QMP response")
        self._socket.settimeout(remaining)
        line = self._stream.readline()
        if not line:
            raise ProtocolError("QMP connection closed unexpectedly")
        try:
            value = json.loads(line)
        except json.JSONDecodeError as error:
            raise ProtocolError("QMP returned invalid JSON") from error
        if not isinstance(value, dict):
            raise ProtocolError("QMP response is not an object")
        return value


def _key_name(character: str) -> str:
    if character in _KEY_NAMES:
        return _KEY_NAMES[character]
    if "a" <= character <= "z" or "0" <= character <= "9":
        return character
    if "A" <= character <= "Z":
        return "shift-" + character.lower()
    raise ProtocolError(f"Cannot type unsupported character through QMP: {character!r}")
