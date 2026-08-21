"""Small synchronous QEMU Machine Protocol client."""

from __future__ import annotations

import json
import re
import socket
import tempfile
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

    def flush_block_device(self, node: str) -> None:
        """Synchronously flush a named block node through QEMU's block layer."""

        if re.fullmatch(r"[A-Za-z0-9._-]+", node) is None:
            raise ProtocolError(f"Unsafe QEMU block node name: {node!r}")
        # QEMU 10.2 does not expose the historical blockdev-flush QMP command,
        # but its HMP qemu-io bridge executes the same synchronous `flush`
        # operation against the already-open named block node.
        response = self.hmp(f'qemu-io {node} "flush"')
        if response.strip():
            raise ProtocolError(
                f"QEMU failed to flush block node {node!r}: {response.strip()}"
            )

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

    def move_pointer_absolute(self, x: float, y: float) -> None:
        """Move the absolute tablet pointer using normalized coordinates."""

        if not 0.0 <= x <= 1.0 or not 0.0 <= y <= 1.0:
            raise ProtocolError("Absolute pointer coordinates must be within 0..1")
        maximum = 0x7FFF
        self.execute(
            "input-send-event",
            {
                # Route pointer events to the graphical console explicitly.
                # The VM also exposes a SPICE agent and multiple input
                # backends; QEMU's QMP contract otherwise considers every
                # unrouted console admissible.
                "device": "video0",
                "events": [
                    {
                        "type": "abs",
                        "data": {"axis": "x", "value": round(x * maximum)},
                    },
                    {
                        "type": "abs",
                        "data": {"axis": "y", "value": round(y * maximum)},
                    },
                ]
            },
        )

    def click_pointer_absolute(
        self,
        x: float,
        y: float,
        *,
        button: str = "left",
    ) -> None:
        """Click one validated tablet button at normalized coordinates."""

        if button not in {"left", "right"}:
            raise ProtocolError(f"Unsupported pointer button: {button!r}")

        self.move_pointer_absolute(x, y)
        # QMP acknowledges the emulated tablet report before Mutter has moved
        # the Wayland pointer.  A real VM trace showed that a 50 ms delay let
        # the first press hit the old position while its release hit the new
        # DING label.  Allow the compositor a bounded settle period before the
        # press; the final behavioral oracle still proves the intended target
        # received the click.
        time.sleep(0.25)
        self._click_pointer_button(button)

    def _click_pointer_button(self, button: str) -> None:
        """Send one held press/release pair, acknowledging both transitions."""

        for down in (True, False):
            self.execute(
                "input-send-event",
                {
                    "device": "video0",
                    "events": [
                        {
                            "type": "btn",
                            "data": {"down": down, "button": button},
                        }
                    ]
                },
            )
            if down:
                time.sleep(0.06)

    def framebuffer_size(self) -> tuple[int, int]:
        """Read the current display size from QEMU's own screendump."""

        with tempfile.NamedTemporaryFile(
            prefix="anduinos-qmp-framebuffer-",
            suffix=".ppm",
            delete=False,
        ) as stream:
            destination = Path(stream.name)
        try:
            self.screendump(destination)
            return _ppm_dimensions(destination)
        finally:
            destination.unlink(missing_ok=True)

    def click_pointer_pixels(
        self,
        x_px: float,
        y_px: float,
        *,
        button: str = "left",
    ) -> None:
        """Click an AT-SPI screen pixel using the real QEMU framebuffer size."""

        width, height = self.framebuffer_size()
        if not 0.0 <= x_px < width or not 0.0 <= y_px < height:
            raise ProtocolError(
                "AT-SPI pointer coordinates are outside the QEMU framebuffer: "
                f"({x_px}, {y_px}) not within {width}x{height}"
            )
        self.click_pointer_absolute(
            x_px / width,
            y_px / height,
            button=button,
        )

    def validate_pointer_bounds(
        self,
        x_px: float,
        y_px: float,
        bounds: tuple[int, int, int, int],
    ) -> tuple[int, int]:
        """Validate AT-SPI pixels against QEMU's actual framebuffer."""

        width, height = self.framebuffer_size()
        if not 0.0 <= x_px < width or not 0.0 <= y_px < height:
            raise ProtocolError(
                "AT-SPI pointer coordinates are outside the QEMU framebuffer: "
                f"({x_px}, {y_px}) not within {width}x{height}"
            )
        left, top, patch_width, patch_height = bounds
        if (
            min(bounds) < 0
            or patch_width < 2
            or patch_height < 2
            or left + patch_width > width
            or top + patch_height > height
        ):
            raise ProtocolError(
                f"AT-SPI hover bounds {bounds!r} are outside {width}x{height}"
            )
        return width, height

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

def _ppm_dimensions(path: Path) -> tuple[int, int]:
    """Parse the small ASCII header of a raw QEMU PPM screendump."""

    tokens: list[bytes] = []
    with path.open("rb") as stream:
        while len(tokens) < 4:
            line = stream.readline()
            if not line:
                break
            content = line.split(b"#", 1)[0]
            tokens.extend(content.split())
    if len(tokens) < 4 or tokens[0] != b"P6":
        raise ProtocolError("QEMU screendump has an invalid PPM header")
    try:
        width, height, maximum = map(int, tokens[1:4])
    except ValueError as error:
        raise ProtocolError("QEMU screendump has non-numeric dimensions") from error
    if width < 1 or height < 1 or maximum != 255:
        raise ProtocolError(
            f"QEMU screendump has invalid dimensions: {width}x{height}, max={maximum}"
        )
    return width, height


def _key_name(character: str) -> str:
    if character in _KEY_NAMES:
        return _KEY_NAMES[character]
    if "a" <= character <= "z" or "0" <= character <= "9":
        return character
    if "A" <= character <= "Z":
        return "shift-" + character.lower()
    raise ProtocolError(f"Cannot type unsupported character through QMP: {character!r}")
