"""Strict host/guest semantic input protocol and installer transcript checks."""

from .shared import *  # noqa: F403


def _is_gnome_extension_entry(entry) -> bool:
    component = entry.component_text
    return bool(
        re.search(r"(^|[|/])gnome-shell($|[|/])", component, re.IGNORECASE)
        or re.search(r"\b(extension|JS ERROR)\b", entry.message, re.IGNORECASE)
    )


def _scenario_json(scenario: Scenario) -> dict[str, object]:
    value = asdict(scenario)
    value["architectures"] = [item.value for item in scenario.architectures]
    for key in ("firmware", "network", "filesystem", "ssh"):
        value[key] = value[key].value
    return value


_SUPPORTED_GUEST_QMP_KEYS = frozenset(
    {
        "tab",
        "spc",
        "ret",
        "down",
        "up",
        "alt-tab",
        "alt-f4",
        "ctrl-shift-u",
        "meta_l-tab",
        "meta_l-d",
        "meta_l-i",
        "meta_l-u",
        "meta_l-shift-s",
        "meta_l",
        "esc",
        "shift-f10",
        "shift-tab",
    }
)

# HMP ``sendkey`` acknowledges queueing the event, not GTK processing it.  A
# semantic sequence such as End, Up, Up, Up, Return can otherwise be injected
# in less than two milliseconds and race the guest's menu selection updates.
# Keep this pacing on the host so a stalled guest can never falsely claim that
# it consumed an input event.
_GUEST_QMP_KEY_SETTLE_SECONDS = 0.20

# A pointer request can reveal a GTK popover whose follow-up keyboard requests
# are already buffered in the serial transcript.  QMP only confirms that the
# mouse event was queued; without host-side pacing, those keys can be delivered
# before GTK has mapped and focused the new menu.  Keep this separate from the
# guest's observations so one delayed transcript read cannot collapse a real
# click-then-navigate workflow into a burst of simultaneous input.
_GUEST_QMP_CLICK_SETTLE_SECONDS = 0.50


def _guest_qmp_key_supported(key: str) -> bool:
    return key in _SUPPORTED_GUEST_QMP_KEYS or re.fullmatch(
        r"alt-[a-z]", key
    ) is not None


def _run_with_qmp_key_requests(
    vm: QemuVm,
    command: str,
    *,
    timeout: float,
    secret_text: str | None = None,
    secret_texts: dict[str, str] | None = None,
    text_inputs: dict[str, str] | None = None,
    request_trace: Path | None = None,
):
    """Run a serial command while serving semantic keyboard requests via QMP."""

    assert vm.serial is not None and vm.qmp is not None
    transcript = vm.serial.transcript
    offset = transcript.stat().st_size if transcript.exists() else 0
    partial = ""
    handled: set[str] = set()

    def record_request(**values: object) -> None:
        if request_trace is None:
            return
        request_trace.parent.mkdir(parents=True, exist_ok=True)
        with request_trace.open("a", encoding="utf-8") as stream:
            stream.write(
                json.dumps(
                    {"event": "host-qmp-request", **values},
                    ensure_ascii=False,
                )
                + "\n"
            )

    def serve_transcript() -> None:
        nonlocal offset, partial
        if not transcript.exists():
            return
        with transcript.open("rb") as stream:
            stream.seek(offset)
            chunk = stream.read()
            offset = stream.tell()
        if not chunk:
            return
        partial += chunk.decode("utf-8", errors="replace").replace("\r", "")
        lines = partial.split("\n")
        partial = lines.pop()
        for line in lines:
            double_click_request = _parse_spice_double_click_request(line)
            if double_click_request is not None:
                identifier, x_px, y_px, bounds, double_click_time_ms = (
                    double_click_request
                )
                if identifier in handled:
                    continue
                handled.add(identifier)
                started = time.monotonic_ns()
                try:
                    vm.qmp.validate_pointer_bounds(x_px, y_px, bounds)
                    with SpiceInputClient(vm.spice_socket) as pointer:
                        pointer.double_click_pointer_pixels(
                            x_px,
                            y_px,
                            double_click_time_ms=double_click_time_ms,
                        )
                except BaseException as error:
                    record_request(
                        request=identifier,
                        kind="double-click",
                        x_px=x_px,
                        y_px=y_px,
                        button="left",
                        clicks=2,
                        positioning_clicks=1,
                        double_click_time_ms=double_click_time_ms,
                        input_transport="spice-vdagent",
                        completed=False,
                        duration_ms=round(
                            (time.monotonic_ns() - started) / 1_000_000,
                            3,
                        ),
                        error=f"{type(error).__name__}: {error}",
                    )
                    raise
                record_request(
                    request=identifier,
                    kind="double-click",
                    x_px=x_px,
                    y_px=y_px,
                    button="left",
                    clicks=2,
                    positioning_clicks=1,
                    double_click_time_ms=double_click_time_ms,
                    input_transport="spice-vdagent",
                    client_mouse_mode=2,
                    position_coupled_to_press=True,
                    completed=True,
                    duration_ms=round(
                        (time.monotonic_ns() - started) / 1_000_000,
                        3,
                    ),
                )
                continue
            click_request = _parse_qmp_click_request(line)
            if click_request is not None:
                identifier, x_px, y_px, button = click_request
                if identifier in handled:
                    continue
                handled.add(identifier)
                started = time.monotonic_ns()
                try:
                    vm.qmp.click_pointer_pixels(
                        x_px,
                        y_px,
                        button=button,
                    )
                    time.sleep(_GUEST_QMP_CLICK_SETTLE_SECONDS)
                except BaseException as error:
                    record_request(
                        request=identifier,
                        kind="click",
                        x_px=x_px,
                        y_px=y_px,
                        button=button,
                        completed=False,
                        duration_ms=round(
                            (time.monotonic_ns() - started) / 1_000_000,
                            3,
                        ),
                        error=f"{type(error).__name__}: {error}",
                    )
                    raise
                record_request(
                    request=identifier,
                    kind="click",
                    x_px=x_px,
                    y_px=y_px,
                    button=button,
                    settle_ms=round(_GUEST_QMP_CLICK_SETTLE_SECONDS * 1000),
                    completed=True,
                    duration_ms=round(
                        (time.monotonic_ns() - started) / 1_000_000,
                        3,
                    ),
                )
                continue
            secret_request = _parse_qmp_secret_request(line)
            if secret_request is not None:
                if secret_request in handled:
                    continue
                supplied = _resolve_qmp_secret(
                    secret_request,
                    secret_text=secret_text,
                    secret_texts=secret_texts,
                )
                handled.add(secret_request)
                vm.qmp.type_text(supplied, interval=0.06)
                continue
            text_request = _parse_qmp_text_request(line)
            if text_request is not None:
                if text_request in handled:
                    continue
                if text_inputs is None or text_request not in text_inputs:
                    raise TestFailure(
                        f"Guest requested text {text_request!r}, but no value was supplied"
                    )
                value = text_inputs[text_request]
                if not isinstance(value, str) or not value:
                    raise TestFailure(
                        f"Guest text request {text_request!r} resolved to an invalid value"
                    )
                handled.add(text_request)
                vm.qmp.type_text(value, interval=0.06)
                continue
            request = _parse_qmp_key_request(line)
            if request is None:
                continue
            identifier, key = request
            if identifier in handled:
                continue
            if not _guest_qmp_key_supported(key):
                raise TestFailure(f"Guest requested unsupported QMP key: {key!r}")
            handled.add(identifier)
            started = time.monotonic_ns()
            try:
                vm.qmp.send_key(key)
                time.sleep(_GUEST_QMP_KEY_SETTLE_SECONDS)
            except BaseException as error:
                record_request(
                    request=identifier,
                    kind="key",
                    key=key,
                    input_transport="qmp-hmp",
                    completed=False,
                    duration_ms=round(
                        (time.monotonic_ns() - started) / 1_000_000,
                        3,
                    ),
                    error=f"{type(error).__name__}: {error}",
                )
                raise
            record_request(
                request=identifier,
                kind="key",
                key=key,
                input_transport="qmp-hmp",
                settle_ms=round(_GUEST_QMP_KEY_SETTLE_SECONDS * 1000),
                completed=True,
                duration_ms=round(
                    (time.monotonic_ns() - started) / 1_000_000,
                    3,
                ),
            )

    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(
            vm.serial.run,
            command,
            timeout=timeout,
            check=False,
        )
        while not future.done():
            serve_transcript()
            time.sleep(0.05)
        result = future.result()
        # The guest may emit its final request and exit between the loop's
        # done() check and the next transcript read. Drain once after joining
        # the command so terminal QMP requests cannot be silently lost.
        serve_transcript()
        return result


def _parse_spice_double_click_request(
    line: str,
) -> tuple[str, float, float, tuple[int, int, int, int], int] | None:
    """Parse one semantic two-press gesture at an AT-SPI-derived pixel."""

    start = line.find('{"event": "spice-double-click"')
    if start < 0:
        return None
    try:
        request = json.loads(line[start:])
    except json.JSONDecodeError:
        return None
    identifier = request.get("request")
    x = request.get("x_px")
    y = request.get("y_px")
    clicks = request.get("clicks")
    positioning_clicks = request.get("positioning_clicks")
    double_click_time_ms = request.get("double_click_time_ms")
    button = request.get("button")
    bounds = request.get("bounds")
    if not isinstance(identifier, str) or not identifier:
        return None
    if (
        isinstance(x, bool)
        or isinstance(y, bool)
        or not isinstance(x, (int, float))
        or not isinstance(y, (int, float))
        or float(x) < 0.0
        or float(y) < 0.0
        or clicks != 2
        or positioning_clicks != 1
        or isinstance(double_click_time_ms, bool)
        or not isinstance(double_click_time_ms, int)
        or not 100 <= double_click_time_ms <= 5000
        or button != "left"
        or not isinstance(bounds, list)
        or len(bounds) != 4
        or any(isinstance(value, bool) or not isinstance(value, int) for value in bounds)
        or min(bounds) < 0
        or bounds[2] < 2
        or bounds[3] < 2
    ):
        return None
    typed_bounds = (bounds[0], bounds[1], bounds[2], bounds[3])
    expected_x = bounds[0] + bounds[2] / 2
    expected_y = bounds[1] + bounds[3] / 2
    if abs(float(x) - expected_x) > 0.001 or abs(float(y) - expected_y) > 0.001:
        return None
    return identifier, float(x), float(y), typed_bounds, double_click_time_ms


def _parse_qmp_click_request(
    line: str,
) -> tuple[str, float, float, str] | None:
    """Parse a guest request to click an AT-SPI-derived screen pixel."""

    start = line.find('{"event": "qmp-click"')
    if start < 0:
        return None
    try:
        request = json.loads(line[start:])
    except json.JSONDecodeError:
        return None
    identifier = request.get("request")
    x = request.get("x_px")
    y = request.get("y_px")
    button = request.get("button", "left")
    if not isinstance(identifier, str) or not identifier:
        return None
    if (
        isinstance(x, bool)
        or isinstance(y, bool)
        or not isinstance(x, (int, float))
        or not isinstance(y, (int, float))
    ):
        return None
    pixel_x = float(x)
    pixel_y = float(y)
    if pixel_x < 0.0 or pixel_y < 0.0:
        return None
    if button not in {"left", "right"}:
        return None
    # A single-click request must remain a single click.  The dedicated
    # The dedicated SPICE double-click protocol sends exactly two complete
    # primary-button gestures after a rendered hover acknowledgement.
    if "click_count" in request:
        return None
    return identifier, pixel_x, pixel_y, button


def _parse_qmp_key_request(line: str) -> tuple[str, str] | None:
    start = line.find('{"event": "qmp-key"')
    if start < 0:
        return None
    try:
        request = json.loads(line[start:])
    except json.JSONDecodeError:
        return None
    identifier = request.get("request")
    key = request.get("key")
    if not isinstance(identifier, str) or not identifier:
        return None
    if not isinstance(key, str) or not key:
        return None
    return identifier, key


def _parse_qmp_text_request(line: str) -> str | None:
    """Parse a named, non-secret deterministic text-input request."""

    start = line.find('{"event": "qmp-text"')
    if start < 0:
        return None
    try:
        request = json.loads(line[start:])
    except json.JSONDecodeError:
        return None
    identifier = request.get("request")
    if not isinstance(identifier, str) or not identifier:
        return None
    return identifier


def _parse_qmp_secret_request(line: str) -> str | None:
    """Parse an opaque request whose secret value never crosses the guest log."""

    start = line.find('{"event": "qmp-secret"')
    if start < 0:
        return None
    try:
        request = json.loads(line[start:])
    except json.JSONDecodeError:
        return None
    identifier = request.get("request")
    if not isinstance(identifier, str) or not identifier:
        return None
    return identifier


def _resolve_qmp_secret(
    request: str,
    *,
    secret_text: str | None,
    secret_texts: dict[str, str] | None,
) -> str:
    """Resolve an opaque guest request without putting its value in logs."""

    if secret_texts is not None and request in secret_texts:
        value = secret_texts[request]
    else:
        value = secret_text
    if value is None:
        raise TestFailure(
            f"Guest requested secret {request!r}, but no value was supplied"
        )
    if not value:
        raise TestFailure(f"Guest secret {request!r} must not be empty")
    return value


def _validate_installer_output(output: str, expects_driver_flow: bool) -> None:
    """Validate the executor transcript exposed by the real GTK output tab."""

    if not output.strip():
        raise TestFailure("Installer executor output is empty")
    folded = output.casefold()
    fatal_markers = (
        "traceback (most recent call last)",
        "fatal step",
        "installation failed",
    )
    for marker in fatal_markers:
        if marker in folded:
            raise TestFailure(
                f"Installer executor output contains fatal marker: {marker}"
            )
    if not expects_driver_flow:
        return
    command = (
        "ubuntu-drivers install --no-oem --package-list "
        "/run/anduinos-installer-drivers"
    )
    if command not in output:
        raise TestFailure(
            "Online scenario did not execute the ubuntu-drivers install flow"
        )
    no_driver_messages = (
        "all the available drivers are already installed.",
        "all available drivers are already installed.",
    )
    if not any(message in folded for message in no_driver_messages):
        raise TestFailure(
            "QEMU driver flow did not report that no additional driver is needed"
        )


__all__ = tuple(name for name in globals() if not name.startswith("__"))
