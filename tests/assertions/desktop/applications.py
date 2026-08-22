"""WeChat and cross-toolkit theme evidence oracles."""

import re

from framework.errors import TestFailure
from .catalog import _WECHAT_APP_ID
from .events import _all_event_objects, _event_objects, _one_event


def _validate_wechat_process(value: object, context: str) -> dict[str, object]:
    if not isinstance(value, dict):
        raise TestFailure(f"{context} did not report a process identity object")
    required = {
        "pid",
        "namespace_pid",
        "uid",
        "start_time_ticks",
        "command",
        "executable",
    }
    if set(value) != required:
        raise TestFailure(f"{context} returned malformed process fields")
    for key in ("pid", "namespace_pid", "start_time_ticks"):
        if not isinstance(value.get(key), int) or int(value[key]) <= 1:
            raise TestFailure(f"{context} returned an invalid {key}")
    if not isinstance(value.get("uid"), int) or int(value["uid"]) < 0:
        raise TestFailure(f"{context} returned an invalid uid")
    for key in ("command", "executable"):
        if not isinstance(value.get(key), str) or not value[key]:
            raise TestFailure(f"{context} returned malformed {key}")
    identity = f"{value['command']} {value['executable']}".casefold()
    if "wechat" not in identity and "微信" not in identity:
        raise TestFailure(f"{context} belongs to an unrelated process")
    return value


def _validate_wechat_x11_window(value: object, context: str) -> dict[str, object]:
    if not isinstance(value, dict):
        raise TestFailure(f"{context} did not report an X11 window object")
    required = {
        "id",
        "title",
        "classes",
        "pid",
        "state",
        "map_state",
        "visible",
        "x",
        "y",
        "width",
        "height",
    }
    if set(value) != required:
        raise TestFailure(f"{context} returned malformed X11 fields")
    identifier = value.get("id")
    title = value.get("title")
    classes = value.get("classes")
    if not isinstance(identifier, str) or re.fullmatch(r"0x[0-9a-f]+", identifier) is None:
        raise TestFailure(f"{context} returned an invalid X11 window ID")
    if not isinstance(title, str) or not isinstance(classes, list) or not all(
        isinstance(item, str) for item in classes
    ):
        raise TestFailure(f"{context} returned malformed X11 identity")
    identity = " ".join((title, *classes)).casefold()
    if "wechat" not in identity and "微信" not in identity:
        raise TestFailure(f"{context} belongs to an unrelated X11 client")
    for key in ("pid", "x", "y", "width", "height"):
        if not isinstance(value.get(key), int):
            raise TestFailure(f"{context} returned non-numeric X11 {key}")
    if (
        int(value["pid"]) <= 1
        or int(value["x"]) < 0
        or int(value["y"]) < 0
        or int(value["width"]) < 200
        or int(value["height"]) < 250
        or value.get("map_state") != "IsViewable"
        or value.get("visible") is not True
        or not isinstance(value.get("state"), str)
    ):
        raise TestFailure(f"{context} is not a plausible mapped WeChat window")
    return value


def _validate_wechat_install_events(output: str) -> dict[str, object]:
    events = _all_event_objects(output)
    opened, _ = _one_event(
        events,
        context="WeChat ArcMenu launch",
        event="qmp-key",
        request="wechat-search-open",
        key="meta_l",
    )
    typed, _ = _one_event(
        events,
        context="WeChat ArcMenu launch",
        event="qmp-text",
        request="wechat-search-text",
    )
    result, search = _one_event(
        events,
        context="WeChat ArcMenu launch",
        event="start-search-result",
        query="WeChat",
        accessible_name="WeChat",
        application="gnome-shell",
    )
    if search.get("stable_observations") != 4:
        raise TestFailure("WeChat used an unstable ArcMenu search result")
    focused, _ = _one_event(
        events,
        context="WeChat ArcMenu launch",
        event="search-entry-focus",
        query="WeChat",
        application="gnome-shell",
        focused=True,
    )
    activation, _ = _one_event(
        events,
        context="WeChat ArcMenu launch",
        event="qmp-key",
        request="wechat-result-activate",
        key="ret",
    )
    launched, event_value = _one_event(
        events,
        context="WeChat ArcMenu launch",
        event="wechat-installed-launched",
        search_result="WeChat",
        activation_method="qmp-keyboard",
        application=_WECHAT_APP_ID,
        observation="ewmh-x11",
        visible=True,
    )
    process = _validate_wechat_process(
        event_value.get("process"),
        "launched WeChat",
    )
    main_window = _validate_wechat_x11_window(
        event_value.get("main_window"),
        "launched WeChat",
    )
    windows = event_value.get("windows")
    if not isinstance(windows, list) or main_window not in windows:
        raise TestFailure("WeChat's main window is absent from the EWMH window set")
    if process["namespace_pid"] != main_window["pid"]:
        raise TestFailure("WeChat's EWMH PID was not mapped to its process namespace")
    if not opened < typed < result < focused < activation < launched:
        raise TestFailure("WeChat ArcMenu launch evidence is out of order")
    return {
        "application": _WECHAT_APP_ID,
        "main_window": main_window,
        "process": process,
    }


def _validate_wechat_tray_events(output: str) -> dict[str, object]:
    events = _all_event_objects(output)
    baseline_index, baseline = _one_event(
        events,
        context="WeChat tray roundtrip",
        event="wechat-tray-baseline",
    )
    close_index, _ = _one_event(
        events,
        context="WeChat tray roundtrip",
        event="qmp-key",
        request="wechat-close-to-tray",
        key="alt-f4",
    )
    indicator_index, indicator_event = _one_event(
        events,
        context="WeChat tray roundtrip",
        event="wechat-indicator",
        visible=True,
    )
    click_index, click_event = _one_event(
        events,
        context="WeChat tray roundtrip",
        event="spice-double-click",
        request="wechat-indicator-restore",
        target="WeChat AppIndicator",
        button="left",
        clicks=2,
    )
    restored_index, restored_event = _one_event(
        events,
        context="WeChat tray roundtrip",
        event="wechat-tray-restored",
        same_process=True,
        visible=True,
    )
    before = _validate_wechat_process(
        baseline.get("process"),
        "WeChat before tray minimization",
    )
    hidden = _validate_wechat_process(
        indicator_event.get("process"),
        "WeChat while represented by AppIndicator",
    )
    restored = _validate_wechat_process(
        restored_event.get("process"),
        "WeChat after AppIndicator restoration",
    )
    for observed in (hidden, restored):
        if (
            observed["pid"] != before["pid"]
            or observed["start_time_ticks"] != before["start_time_ticks"]
        ):
            raise TestFailure("WeChat tray roundtrip did not preserve the same process")
    baseline_window = _validate_wechat_x11_window(
        baseline.get("main_window"),
        "WeChat before tray minimization",
    )
    restored_window = _validate_wechat_x11_window(
        restored_event.get("main_window"),
        "WeChat after AppIndicator restoration",
    )
    if (
        before["namespace_pid"] != baseline_window["pid"]
        or restored["namespace_pid"] != restored_window["pid"]
    ):
        raise TestFailure("WeChat tray windows do not belong to the preserved process")
    indicator = indicator_event.get("indicator")
    if not isinstance(indicator, dict) or indicator.get("application") != "gnome-shell":
        raise TestFailure("WeChat indicator was not rendered by GNOME Shell")
    bounds = indicator.get("bounds")
    screen = indicator.get("screen")
    if (
        indicator.get("lower_right") is not True
        or not isinstance(bounds, list)
        or len(bounds) != 4
        or not isinstance(screen, list)
        or len(screen) != 2
        or any(not isinstance(item, (int, float)) for item in bounds + screen)
    ):
        raise TestFailure("WeChat indicator lacks lower-right screen geometry")
    x, y, width, height = bounds
    screen_right, screen_bottom = screen
    if (
        width < 2
        or height < 2
        or x + width / 2 < screen_right * 0.65
        or y + height / 2 < screen_bottom * 0.75
    ):
        raise TestFailure("WeChat AppIndicator is outside the lower-right tray")
    if click_event.get("application") != "gnome-shell":
        raise TestFailure("WeChat AppIndicator restoration did not click GNOME Shell")
    if not baseline_index < close_index < indicator_index < click_index < restored_index:
        raise TestFailure("WeChat tray roundtrip evidence is out of order")
    return {
        "process": before,
        "indicator": indicator,
        "application": restored_event.get("application"),
        "baseline_window": baseline_window,
        "main_window": restored_window,
    }


def _validate_theme_selection(output: str, expected: str) -> None:
    events = _event_objects(output, "theme-selected")
    if len(events) != 1:
        raise TestFailure("Theme selection did not produce one semantic result event")
    event_value = events[0]
    wanted_scheme = "prefer-dark" if expected == "dark" else "default"
    if event_value.get("expected") != expected:
        raise TestFailure("Theme selector reported the wrong requested appearance")
    if event_value.get("color_scheme") != wanted_scheme:
        raise TestFailure(
            "Theme selector did not apply the expected interface color scheme"
        )
    label = event_value.get("localized_label")
    if not isinstance(label, str) or "暗色样式" not in label:
        raise TestFailure(
            "The Chinese GNOME Shell session did not expose a localized theme label"
        )
    transitions = event_value.get("transitions")
    if not isinstance(transitions, list) or not transitions or transitions[-1] != wanted_scheme:
        raise TestFailure("Theme selector evidence contains no real final transition")
    menu_events = _event_objects(output, "theme-menu")
    observed_transitions = [event.get("transition") for event in menu_events]
    if observed_transitions != transitions:
        raise TestFailure(
            "Theme selector did not expose the real Shell menu for every transition"
        )
    if any(
        event.get("method") not in {"opened", "already-open"}
        for event in menu_events
    ):
        raise TestFailure("Theme selector reported an unsupported Shell menu state")


def _validate_theme_marker(output: str, expected: str) -> None:
    events = _event_objects(output, "theme-marker")
    if len(events) != 1:
        raise TestFailure("Theme fixture did not produce one semantic marker event")
    observed = events[0].get("observed")
    if not isinstance(observed, str) or expected not in observed:
        raise TestFailure(
            f"Theme fixture marker is wrong: expected {expected!r}, got {observed!r}"
        )
    if expected.startswith("FIREFOX "):
        if observed != expected:
            raise TestFailure("Firefox did not expose the exact web-page theme marker")
        application = events[0].get("application")
        if not isinstance(application, str) or "firefox" not in application.casefold():
            raise TestFailure("Firefox marker was not owned by the real browser")


def _validate_same_fixture_process(before: int, after: int, framework: str) -> None:
    if before <= 1 or after <= 1 or before != after:
        raise TestFailure(
            f"{framework} fixture restarted during the live theme transition: "
            f"{before} -> {after}"
        )


__all__ = tuple(name for name in globals() if name.startswith("_"))
