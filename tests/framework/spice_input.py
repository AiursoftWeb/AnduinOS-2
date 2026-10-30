"""Synchronous SPICE absolute-pointer input for desktop acceptance tests."""

from __future__ import annotations

import time
from pathlib import Path

from .errors import ConfigurationError, ProtocolError


_POINTER_MAPPING_SETTLE_SECONDS = 1.0


_SET1_KEYS = {
    **dict(zip("1234567890", range(0x02, 0x0C), strict=True)),
    **dict(
        zip(
            "qwertyuiop",
            (0x10, 0x11, 0x12, 0x13, 0x14, 0x15, 0x16, 0x17, 0x18, 0x19),
            strict=True,
        )
    ),
    **dict(
        zip(
            "asdfghjkl",
            (0x1E, 0x1F, 0x20, 0x21, 0x22, 0x23, 0x24, 0x25, 0x26),
            strict=True,
        )
    ),
    **dict(
        zip(
            "zxcvbnm",
            (0x2C, 0x2D, 0x2E, 0x2F, 0x30, 0x31, 0x32),
            strict=True,
        )
    ),
    " ": 0x39,
    "-": 0x0C,
    "=": 0x0D,
    ";": 0x27,
    ",": 0x33,
    ".": 0x34,
    "/": 0x35,
}
_SET1_SHIFTED_KEYS = {"_": 0x0C, ":": 0x27, "@": 0x03}
_SET1_NAMED_KEYS = {"esc": 0x01, "ret": 0x1C, "c": 0x2E}


class SpiceInputClient:
    """Drive the guest's real SPICE/vdagent tablet at guest pixel coordinates."""

    def __init__(self, socket_path: Path, timeout: float = 10.0) -> None:
        self.socket_path = socket_path
        self.timeout = timeout
        self._session = None
        self._inputs = None
        self._main = None
        self._glib = None
        self._spice = None
        self._channel_error = ""

    @staticmethod
    def _bindings():
        try:
            import gi

            gi.require_version("SpiceClientGLib", "2.0")
            from gi.repository import GLib, GObject, SpiceClientGLib
        except (ImportError, ValueError) as error:
            raise ConfigurationError(
                "SPICE pointer input requires gir1.2-spiceclientglib-2.0"
            ) from error
        return GLib, GObject, SpiceClientGLib

    @classmethod
    def validate_dependencies(cls) -> None:
        """Fail before the matrix starts when the SPICE GI binding is absent."""

        cls._bindings()

    def connect(self, *, require_agent: bool = True) -> None:
        """Connect for desktop pointer input or firmware keyboard bootstrap."""

        if not self.socket_path.is_socket():
            raise ProtocolError(f"SPICE socket is unavailable: {self.socket_path}")
        GLib, GObject, Spice = self._bindings()
        self._glib = GLib
        self._spice = Spice
        session = Spice.Session.new()
        # Headless input/cursor observers never play or record host audio.
        session.set_property("enable-audio", False)
        session.set_property("unix-path", str(self.socket_path))
        loop = GLib.MainLoop()

        def ready() -> bool:
            if not require_agent:
                return self._inputs is not None
            return (
                self._inputs is not None
                and self._main is not None
                and self._main.get_property("mouse-mode") == 2
                and self._main.get_property("agent-connected") is True
            )

        def main_mouse_update(_channel, *_details) -> None:
            if ready():
                loop.quit()

        def channel_event(channel, event) -> None:
            if event == Spice.ChannelEvent.OPENED:
                if isinstance(channel, Spice.InputsChannel):
                    self._inputs = channel
                elif isinstance(channel, Spice.MainChannel):
                    self._main = channel
                    channel.request_mouse_mode(2)
                if ready():
                    loop.quit()
            elif event in {
                Spice.ChannelEvent.ERROR_CONNECT,
                Spice.ChannelEvent.ERROR_TLS,
                Spice.ChannelEvent.ERROR_LINK,
                Spice.ChannelEvent.ERROR_AUTH,
                Spice.ChannelEvent.ERROR_IO,
            }:
                self._channel_error = f"SPICE channel event {int(event)}"
                loop.quit()

        def channel_new(_session, channel) -> None:
            GObject.Object.connect(channel, "channel-event", channel_event)
            if isinstance(channel, Spice.MainChannel):
                GObject.Object.connect(
                    channel,
                    "main-mouse-update",
                    main_mouse_update,
                )
                GObject.Object.connect(
                    channel,
                    "notify::agent-connected",
                    main_mouse_update,
                )
            if isinstance(channel, Spice.InputsChannel):
                channel.connect()

        GObject.Object.connect(session, "channel-new", channel_new)
        if not session.connect():
            raise ProtocolError("SPICE session rejected the connection request")
        timed_out = False

        def connection_timeout() -> bool:
            nonlocal timed_out
            timed_out = True
            loop.quit()
            return False

        timeout_source = GLib.timeout_add(
            max(1, round(self.timeout * 1000)),
            connection_timeout,
        )
        loop.run()
        if not timed_out:
            GLib.source_remove(timeout_source)
        if self._inputs is None:
            session.disconnect()
            detail = self._channel_error or "inputs channel did not open"
            raise ProtocolError(f"SPICE pointer connection failed: {detail}")
        if require_agent:
            try:
                self._require_agent()
                self._require_client_mouse_mode()
                self._settle_pointer_mapping()
            except ProtocolError:
                session.disconnect()
                raise
        self._session = session

    def send_boot_key(self, key: str) -> None:
        """Send one US set-1 key without depending on the guest agent."""

        if self._inputs is None:
            raise ProtocolError("SPICE boot keyboard is not connected")
        try:
            scancode = _SET1_NAMED_KEYS[key]
        except KeyError as error:
            raise ProtocolError(f"Unsupported boot key: {key!r}") from error
        self._inputs.key_press_and_release(scancode)
        self._run_for(0.06)

    def type_boot_text(self, value: str, *, interval: float = 0.03) -> None:
        """Type the fixed GRUB terminal bootstrap with strict scan codes."""

        if self._inputs is None:
            raise ProtocolError("SPICE boot keyboard is not connected")
        encoded: list[tuple[int, bool]] = []
        for character in value:
            uppercase = "A" <= character <= "Z"
            shifted = character in _SET1_SHIFTED_KEYS or uppercase
            try:
                scancode = (
                    _SET1_SHIFTED_KEYS[character]
                    if character in _SET1_SHIFTED_KEYS
                    else _SET1_KEYS[
                        character.lower() if uppercase else character
                    ]
                )
            except KeyError as error:
                raise ProtocolError(
                    f"Unsupported boot text character: {character!r}"
                ) from error
            encoded.append((scancode, shifted))
        for scancode, shifted in encoded:
            if shifted:
                self._inputs.key_press(0x2A)
            self._inputs.key_press_and_release(scancode)
            if shifted:
                self._inputs.key_release(0x2A)
            self._run_for(interval)

    def _require_agent(self) -> None:
        connected = (
            False
            if self._main is None
            else bool(self._main.get_property("agent-connected"))
        )
        if not connected:
            raise ProtocolError(
                "SPICE pointer connection failed: guest agent did not become ready"
            )

    def _require_client_mouse_mode(self) -> None:
        mode = None if self._main is None else self._main.get_property("mouse-mode")
        if mode != 2:
            raise ProtocolError(
                "SPICE pointer connection did not enter client mouse mode "
                f"(mode={mode!r})"
            )

    def _settle_pointer_mapping(self) -> None:
        """Drain the vdagent display-map handshake before the first pointer packet."""

        # ``agent-connected`` becomes true before spice-vdagent has necessarily
        # finished mapping the guest connector to the SPICE display.  Sending
        # the first absolute position in that window can be acknowledged by the
        # channel and still be discarded by the agent.  Keep pumping GLib long
        # enough for that first mapping exchange, then fail closed if either
        # readiness property changed while the events were being processed.
        self._run_for(_POINTER_MAPPING_SETTLE_SECONDS)
        self._require_agent()
        self._require_client_mouse_mode()

    def close(self) -> None:
        if self._session is not None:
            self._session.disconnect()
            self._run_for(0.05)
        self._inputs = None
        self._main = None
        self._session = None

    def move_pointer_pixels(self, x: float, y: float) -> None:
        if self._inputs is None:
            raise ProtocolError("SPICE pointer is not connected")
        if x < 0 or y < 0:
            raise ProtocolError("SPICE pointer coordinates must be non-negative")
        self._inputs.position(round(x), round(y), 0, 0)
        self._run_for(0.05)

    def double_click_pointer_pixels(
        self,
        x: float,
        y: float,
        *,
        double_click_time_ms: int,
    ) -> None:
        """Position once, then emit a real two-click activation through SPICE.

        A newly opened SPICE client can make the guest agent refresh monitor
        mapping while the first pointer packet is in flight.  One harmless
        positioning click establishes the real guest cursor location.  Waiting
        longer than the guest's own configured double-click interval keeps it
        out of the activation count; the following two presses are the actual
        user-visible double-click contract.
        """

        if self._inputs is None:
            raise ProtocolError("SPICE pointer is not connected")
        if not 100 <= double_click_time_ms <= 5000:
            raise ProtocolError("SPICE double-click interval is outside safe bounds")
        rounded_x = round(x)
        rounded_y = round(y)

        self._primary_click(rounded_x, rounded_y, release_drain=0.06)
        self._run_for((double_click_time_ms + 200) / 1000)
        for index in range(2):
            self._primary_click(
                rounded_x,
                rounded_y,
                release_drain=0.12 if index == 0 else 0.25,
            )

    def _primary_click(self, x: int, y: int, *, release_drain: float) -> None:
        """Send one position/press/release sequence on the ordered input channel."""

        assert self._inputs is not None
        # Re-send the absolute position immediately before every press.  QMP
        # owns coordinate validation, so the input-only SPICE client need not
        # open a display channel and renegotiate the guest's resolution.
        self._inputs.position(x, y, 0, 0)
        self._inputs.button_press(1, 0)
        self._run_for(0.06)
        self._inputs.button_release(1, 0)
        self._run_for(release_drain)

    def _run_for(self, seconds: float) -> None:
        if self._glib is None:
            time.sleep(seconds)
            return
        loop = self._glib.MainLoop()
        self._glib.timeout_add(
            max(1, round(seconds * 1000)),
            lambda: (loop.quit(), False)[1],
        )
        loop.run()

    def __enter__(self) -> "SpiceInputClient":
        self.connect()
        return self

    def __exit__(self, _kind, _value, _traceback) -> None:
        self.close()


class SpiceCursorObserver(SpiceInputClient):
    """Observe the hardware cursor separately from the guest framebuffer.

    A QMP screendump and some Shell screenshots omit the hardware cursor
    plane. SPICE supplies that plane to viewers separately. Server mouse mode
    is essential here: positions must come from the guest, not from coordinates
    the test asked a client-side cursor to display.
    """

    def __init__(self, socket_path: Path, timeout: float = 10.0) -> None:
        super().__init__(socket_path, timeout)
        self._cursor = None
        self._position = None
        self._hotspot = (0, 0)
        self._visible = False
        self._moves = 0

    def connect(self, *, require_agent: bool = False) -> None:
        super().connect(require_agent=False)
        _, GObject, Spice = self._bindings()

        def channel_new(_session, channel) -> None:
            # Open the display transport as a viewer would, without audio or
            # changing monitor geometry. Cursor events alone can precede the
            # first guest display update.
            if isinstance(channel, Spice.DisplayChannel):
                channel.connect()
            if isinstance(channel, Spice.CursorChannel):
                GObject.Object.connect(channel, "cursor-set", self._cursor_set)
                GObject.Object.connect(channel, "cursor-move", self._cursor_move)
                GObject.Object.connect(channel, "cursor-hide", self._cursor_hide)
                GObject.Object.connect(channel, "cursor-reset", self._cursor_reset)
                channel.connect()

        try:
            GObject.Object.connect(self._session, "channel-new", channel_new)
            for channel in self._session.get_channels():
                channel_new(self._session, channel)
            deadline = time.monotonic() + self.timeout
            while self._main is None and time.monotonic() < deadline:
                self._run_for(0.05)
            if self._main is None:
                raise ProtocolError("SPICE cursor observation has no main channel")
            self._main.request_mouse_mode(1)
            while self._main.get_property("mouse-mode") != 1:
                if time.monotonic() >= deadline or self._channel_error:
                    raise ProtocolError("SPICE cursor did not enter server mouse mode")
                self._run_for(0.05)
        except Exception:
            self.close()
            raise

    def _cursor_set(self, _channel, width, height, hot_x, hot_y, pointer) -> None:
        import ctypes
        from PIL import Image

        self._cursor = None
        self._visible = False
        if not (pointer and 0 < width <= 512 and 0 < height <= 512):
            self._channel_error = "Invalid SPICE cursor dimensions or pixel buffer"
            return
        if not (0 <= hot_x < width and 0 <= hot_y < height):
            self._channel_error = "Invalid SPICE cursor hotspot"
            return
        # GI exposes a borrowed pointer. Copy within the callback, before SPICE
        # can release its storage; never retain the pointer itself.
        pixels = ctypes.string_at(pointer, width * height * 4)
        self._cursor = Image.frombytes("RGBA", (width, height), pixels)
        self._hotspot = (hot_x, hot_y)
        self._visible = True

    def _cursor_move(self, _channel, x, y) -> None:
        self._position = (x, y)
        self._moves += 1
        self._visible = True

    def _cursor_hide(self, _channel) -> None:
        self._visible = False
        self._position = None

    def _cursor_reset(self, channel) -> None:
        self._cursor_hide(channel)
        self._cursor = None

    def observe_move(self, move, x: int, y: int) -> None:
        """Require a fresh server event after sending real QMP pointer input."""

        previous = self._moves
        move()
        deadline = time.monotonic() + self.timeout
        while time.monotonic() < deadline:
            self._run_for(0.05)
            if self._channel_error:
                raise ProtocolError(self._channel_error)
            if self._main.get_property("mouse-mode") != 1:
                raise ProtocolError("SPICE cursor left server mouse mode")
            if (
                self._moves > previous
                and self._visible
                and self._position is not None
                and abs(self._position[0] - x) <= 2
                and abs(self._position[1] - y) <= 2
                and self._cursor is not None
                and self._cursor.getchannel("A").getbbox() is not None
            ):
                return
        raise ProtocolError(
            f"Guest cursor did not visibly move to {(x, y)}; "
            f"observed={self._position}, visible={self._visible}"
        )

    def save_view(self, framebuffer: Path, destination: Path) -> None:
        """Keep raw planes and metadata alongside the reconstructed viewer image."""

        import json
        from PIL import Image

        if not self._visible or self._cursor is None or self._position is None:
            raise ProtocolError("No visible guest cursor to capture")
        sprite = destination.with_suffix(".cursor.png")
        self._cursor.save(sprite)
        metadata = {
            "framebuffer": str(framebuffer),
            "cursor": str(sprite),
            "position": self._position,
            "hotspot": self._hotspot,
            "mouse_mode": self._main.get_property("mouse-mode"),
            "move_events": self._moves,
        }
        destination.with_suffix(".json").write_text(
            json.dumps(metadata, indent=2) + "\n", encoding="utf-8"
        )
        with Image.open(framebuffer) as raw:
            view = raw.convert("RGBA")
        view.alpha_composite(
            self._cursor,
            (self._position[0] - self._hotspot[0],
             self._position[1] - self._hotspot[1]),
        )
        view.convert("RGB").save(destination)
