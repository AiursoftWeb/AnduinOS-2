"""Taskbar, desktop, start-menu, and shell integration evidence oracles."""

import re
from pathlib import Path

from framework.errors import TestFailure
from .events import _all_event_objects, _one_event


def _validate_start_button_events(output: str) -> dict[str, object]:
    events = _all_event_objects(output)
    button, value = _one_event(
        events,
        context="Start button",
        event="start-button",
    )
    bounds = value.get("bounds")
    rendered_size = value.get("rendered_size")
    digest = value.get("asset_sha256")
    if (
        not isinstance(bounds, list)
        or len(bounds) != 4
        or any(
            isinstance(item, bool) or not isinstance(item, (int, float))
            for item in bounds
        )
        or not isinstance(value.get("bounds_usable"), bool)
        or not isinstance(rendered_size, list)
        or len(rendered_size) != 2
        or any(
            isinstance(item, bool) or not isinstance(item, int) or item < 16
            for item in rendered_size
        )
        or not isinstance(digest, str)
        or re.fullmatch(r"[0-9a-f]{64}", digest) is None
        or not isinstance(value.get("asset"), str)
        or value["asset"]
        != "/usr/share/gnome-shell/extensions/arcmenu@arcmenu.com/icons/anduinos-logo.svg"
        or not isinstance(value.get("rendered_template"), str)
        or not str(value["rendered_template"]).startswith("/")
    ):
        raise TestFailure("The Start button did not identify a valid rendered asset")
    key, _ = _one_event(
        events,
        context="Start button",
        event="qmp-key",
        request="start-button-open",
        key="meta_l",
    )
    shown, menu = _one_event(
        events,
        context="Start button",
        event="start-menu",
        phase="shown",
        overview_visible=False,
    )
    markers = menu.get("markers")
    if (
        not isinstance(markers, list)
        or "已固定" not in markers
        or "所有应用程序" not in markers
        or not isinstance(menu.get("marker_roles"), list)
    ):
        raise TestFailure("Super did not expose ArcMenu's semantic menu markers")
    escape, _ = _one_event(
        events,
        context="Start button",
        event="qmp-key",
        request="start-button-close",
        key="esc",
    )
    restored, _ = _one_event(
        events,
        context="Start button",
        event="start-menu",
        phase="restored",
        visible=False,
    )
    if not button < key < shown < escape < restored:
        raise TestFailure("Start button menu transitions are out of order")
    return value


def _validate_start_button_contract(
    output: str,
    event: dict[str, object],
) -> None:
    asset = event.get("asset")
    digest = event.get("asset_sha256")
    if not isinstance(asset, str) or not isinstance(digest, str):
        raise TestFailure("The Start button event has no installed asset identity")
    required = {
        f"menu-button-icon='{asset}'",
        f"{digest}  {asset}",
    }
    lines = {line.strip() for line in output.splitlines() if line.strip()}
    if not required.issubset(lines):
        raise TestFailure(
            "ArcMenu configuration and the rendered Start asset do not share "
            "one exact installed identity"
        )
    sizes = [
        line.split("=", 1)[1]
        for line in lines
        if line.startswith("menu-button-icon-size=")
    ]
    try:
        valid_size = len(sizes) == 1 and 16 <= float(sizes[0]) <= 64
    except ValueError:
        valid_size = False
    if not valid_size:
        raise TestFailure("ArcMenu returned an invalid Start icon size contract")


def _validate_panel_pin_initial_events(output: str) -> dict[str, object]:
    events = _all_event_objects(output)
    opened, _ = _one_event(
        events,
        context="Panel pin",
        event="qmp-key",
        request="panel-pin-search-open",
        key="meta_l",
    )
    typed, _ = _one_event(
        events,
        context="Panel pin",
        event="qmp-text",
        request="panel-pin-search-text",
    )
    result, search = _one_event(
        events,
        context="Panel pin",
        event="start-search-result",
        query="AnduinOS Panel Acceptance Fixture",
        accessible_name="AnduinOS Panel Acceptance Fixture",
        application="gnome-shell",
    )
    # GNOME 50 exposes ArcMenu's actionable St search actor as `text` even
    # though the guest resolved a real Atspi.Action ancestor.  Do not infer
    # actionability from that lossy role alone: the exact Shell owner/name and
    # the subsequently observed menu, physical-key activation, launcher, and
    # session persistence form the behavioral oracle.
    if search.get("role") not in {
        "button",
        "menu item",
        "list item",
        "label",
        "text",
    }:
        raise TestFailure("Panel pin search result has an unsupported Shell role")
    if search.get("stable_observations") != 4:
        raise TestFailure("Panel pin used an unstable ArcMenu search result")
    focused, _ = _one_event(
        events,
        context="Panel pin",
        event="search-entry-focus",
        query="AnduinOS Panel Acceptance Fixture",
        role="text",
        application="gnome-shell",
        focused=True,
    )
    context_plan, _ = _one_event(
        events,
        context="Panel pin",
        event="search-result-context",
        target="AnduinOS Panel Acceptance Fixture",
        query="AnduinOS Panel Acceptance Fixture",
        application="gnome-shell",
        focused=True,
        method="search-entry-popup-menu",
    )
    context, _ = _one_event(
        events,
        context="Panel pin",
        event="qmp-key",
        request="panel-pin-context",
        key="shift-f10",
    )
    plan, activated = _validate_context_menu_keyboard(
        events,
        context="Panel pin",
        target="taskbar_pin",
        localized="添加到任务栏",
        request_prefix="panel-pin-action",
    )
    pinned, pinned_event = _one_event(
        events,
        context="Panel pin",
        event="panel-pinned",
        application="AnduinOS Panel Acceptance Fixture",
        menu_label="添加到任务栏",
        launcher_name="AnduinOS Panel Acceptance Fixture",
    )
    if pinned_event.get("launcher_role") not in {"button", "toggle button"}:
        raise TestFailure("Panel pin produced no semantic taskbar launcher")
    if not (
        opened
        < typed
        < result
        < focused
        < context_plan
        < context
        < plan
        < activated
        < pinned
    ):
        raise TestFailure("Panel pin UI events are out of order")
    return pinned_event


def _validate_panel_pin_persisted_events(output: str) -> dict[str, object]:
    events = _all_event_objects(output)
    _, persisted = _one_event(
        events,
        context="Panel pin persistence",
        event="panel-pinned-after-login",
        application="AnduinOS Panel Acceptance Fixture",
        launcher_name="AnduinOS Panel Acceptance Fixture",
        visible=True,
    )
    if persisted.get("launcher_role") not in {"button", "toggle button"}:
        raise TestFailure("The recreated Shell exposed no fixture launcher")
    return persisted


def _validate_panel_pin_roundtrip(
    initial: dict[str, object],
    persisted: dict[str, object],
    *,
    before_session: str,
    after_session: str,
) -> None:
    if not before_session or not after_session or before_session == after_session:
        raise TestFailure("Panel pin was not verified across a fresh Shell session")
    if (
        initial.get("application") != persisted.get("application")
        or initial.get("launcher_name") != persisted.get("launcher_name")
        or persisted.get("visible") is not True
    ):
        raise TestFailure("The pinned launcher did not persist across Shell recreation")


def _validate_panel_remove_events(output: str) -> None:
    events = _all_event_objects(output)
    context, click_event = _one_event(
        events,
        context="Panel remove",
        event="qmp-click",
        request="panel-remove-context",
        button="right",
    )
    if click_event.get("target") != "AnduinOS Panel Acceptance Fixture":
        raise TestFailure("Panel remove right-clicked an unrelated launcher")
    plan, activated = _validate_context_menu_keyboard(
        events,
        context="Panel remove",
        target="taskbar_unpin",
        localized="从任务栏中移除",
        request_prefix="panel-remove-action",
    )
    removed, value = _one_event(
        events,
        context="Panel remove",
        event="panel-removed",
        application="AnduinOS Panel Acceptance Fixture",
        localized_label="从任务栏中移除",
        launcher_visible=False,
    )
    if (
        not context < plan < activated < removed
        or value.get("launcher_visible") is not False
    ):
        raise TestFailure("The localized panel action did not remove the launcher")


def _validate_indicator_fixture_process(
    value: object,
    context: str,
) -> dict[str, object]:
    if not isinstance(value, dict) or set(value) != {
        "pid",
        "uid",
        "start_time_ticks",
        "command",
    }:
        raise TestFailure(f"{context} returned malformed fixture process fields")
    for key in ("pid", "start_time_ticks"):
        if not isinstance(value.get(key), int) or int(value[key]) <= 1:
            raise TestFailure(f"{context} returned invalid {key}")
    if not isinstance(value.get("uid"), int) or int(value["uid"]) < 0:
        raise TestFailure(f"{context} returned an invalid uid")
    if (
        not isinstance(value.get("command"), str)
        or not str(value["command"]).endswith("indicator_fixture.py")
    ):
        raise TestFailure(f"{context} belongs to an unrelated process")
    return value


def _validate_appindicator_roundtrip_events(output: str) -> dict[str, object]:
    events = _all_event_objects(output)
    baseline_index, baseline = _one_event(
        events,
        context="AppIndicator roundtrip",
        event="appindicator-baseline",
        visible=True,
    )
    close_index, _ = _one_event(
        events,
        context="AppIndicator roundtrip",
        event="qmp-key",
        request="appindicator-close-window",
        key="alt-f4",
    )
    hidden_index, hidden = _one_event(
        events,
        context="AppIndicator roundtrip",
        event="appindicator-hidden",
        window_visible=False,
    )
    click_index, click_event = _one_event(
        events,
        context="AppIndicator roundtrip",
        event="spice-double-click",
        request="appindicator-restore-window",
        target="AnduinOS Acceptance Indicator",
        button="left",
        application="gnome-shell",
        clicks=2,
    )
    restored_index, restored = _one_event(
        events,
        context="AppIndicator roundtrip",
        event="appindicator-restored",
        same_process=True,
        visible=True,
    )
    before_process = _validate_indicator_fixture_process(
        baseline.get("process"), "AppIndicator baseline"
    )
    hidden_process = _validate_indicator_fixture_process(
        hidden.get("process"), "hidden AppIndicator fixture"
    )
    restored_process = _validate_indicator_fixture_process(
        restored.get("process"), "restored AppIndicator fixture"
    )
    for observed in (hidden_process, restored_process):
        if (
            observed["pid"] != before_process["pid"]
            or observed["start_time_ticks"] != before_process["start_time_ticks"]
        ):
            raise TestFailure("AppIndicator roundtrip did not preserve the same process")
    for event_value, expected_visible in ((baseline, True), (restored, True)):
        window = event_value.get("window")
        if (
            not isinstance(window, dict)
            or window.get("accessible_name")
            != "AnduinOS Indicator Fixture Window"
            or window.get("role") != "frame"
        ):
            raise TestFailure("AppIndicator did not expose the real GTK fixture window")
        if event_value.get("visible") is not expected_visible:
            raise TestFailure("AppIndicator returned the wrong window visibility")
    indicator = hidden.get("indicator")
    if not isinstance(indicator, dict):
        raise TestFailure("GNOME Shell exposed no AppIndicator details")
    bounds = indicator.get("bounds")
    screen = indicator.get("screen")
    if (
        indicator.get("accessible_name") != "AnduinOS Acceptance Indicator"
        or indicator.get("application") != "gnome-shell"
        or indicator.get("lower_right") is not True
        or not isinstance(bounds, list)
        or len(bounds) != 4
        or not isinstance(screen, list)
        or len(screen) != 2
        or any(
            isinstance(item, bool) or not isinstance(item, (int, float))
            for item in bounds + screen
        )
    ):
        raise TestFailure(
            "GNOME Shell AppIndicator lacks trusted lower-right tray geometry"
        )
    x, y, width, height = bounds
    screen_right, screen_bottom = screen
    if (
        width < 2
        or height < 2
        or x + width / 2 < screen_right * 0.65
        or y + height / 2 < screen_bottom * 0.75
    ):
        raise TestFailure("GNOME Shell AppIndicator is outside the lower-right tray")
    if click_event.get("target") != indicator.get("accessible_name"):
        raise TestFailure("Host input restored an unrelated Shell control")
    if not baseline_index < close_index < hidden_index < click_index < restored_index:
        raise TestFailure("AppIndicator roundtrip evidence is out of order")
    return {
        "process": before_process,
        "indicator": indicator,
        "window": restored["window"],
    }


def _validate_desktop_shortcut_events(output: str) -> None:
    events = _all_event_objects(output)
    opened, _ = _one_event(
        events,
        context="Desktop shortcut",
        event="qmp-key",
        request="desktop-shortcut-search-open",
        key="meta_l",
    )
    typed, _ = _one_event(
        events,
        context="Desktop shortcut",
        event="qmp-text",
        request="desktop-shortcut-search-text",
    )
    result, search = _one_event(
        events,
        context="Desktop shortcut",
        event="start-search-result",
        query="AnduinOS Panel Acceptance Fixture",
        accessible_name="AnduinOS Panel Acceptance Fixture",
        application="gnome-shell",
    )
    if search.get("stable_observations") != 4:
        raise TestFailure("Desktop shortcut used an unstable ArcMenu search result")
    focused, _ = _one_event(
        events,
        context="Desktop shortcut",
        event="search-entry-focus",
        query="AnduinOS Panel Acceptance Fixture",
        role="text",
        application="gnome-shell",
        focused=True,
    )
    context_plan, _ = _one_event(
        events,
        context="Desktop shortcut",
        event="search-result-context",
        target="AnduinOS Panel Acceptance Fixture",
        query="AnduinOS Panel Acceptance Fixture",
        application="gnome-shell",
        focused=True,
        method="search-entry-popup-menu",
    )
    context, _ = _one_event(
        events,
        context="Desktop shortcut",
        event="qmp-key",
        request="desktop-shortcut-context",
        key="shift-f10",
    )
    pointer, activated = _validate_context_menu_pointer(
        events,
        context="Desktop shortcut",
        target="desktop_shortcut_create",
        localized="创建桌面快捷方式",
        request_prefix="desktop-shortcut-action",
    )
    visible, _ = _one_event(
        events,
        context="Desktop shortcut",
        event="desktop-shortcut-visible",
        accessible_name="AnduinOS Panel Acceptance Fixture",
        role="label",
        application="gjs",
    )
    foreground, foreground_event = _one_event(
        events,
        context="Desktop shortcut",
        event="desktop-foreground",
        request="desktop-shortcut-show-desktop",
        blockers_after=[],
        ding_frames=1,
    )
    if not isinstance(foreground_event.get("shortcut_sent"), bool):
        raise TestFailure("Desktop shortcut foreground evidence is malformed")
    focus, focus_event = _one_event(
        events,
        context="Desktop shortcut",
        event="qmp-click",
        request="desktop-shortcut-focus",
        target="desktop-background",
        button="left",
    )
    if (
        focus_event.get("role") != "frame"
        or focus_event.get("application") != "gjs"
        or not isinstance(focus_event.get("bounds"), list)
        or len(focus_event["bounds"]) != 4
    ):
        raise TestFailure("Desktop shortcut did not focus DING's desktop frame")
    ding_text, _ = _one_event(
        events,
        context="Desktop shortcut",
        event="qmp-text",
        request="desktop-shortcut-ding-search-text",
    )
    search_accept, _ = _one_event(
        events,
        context="Desktop shortcut",
        event="qmp-key",
        request="desktop-shortcut-ding-search-accept",
        key="ret",
    )
    launch, _ = _one_event(
        events,
        context="Desktop shortcut",
        event="qmp-key",
        request="desktop-shortcut-launch",
        key="ret",
    )
    bounds = focus_event.get("bounds")
    if (
        not isinstance(bounds, list)
        or len(bounds) != 4
        or any(
            isinstance(value, bool) or not isinstance(value, (int, float))
            for value in bounds
        )
        or bounds[2] < 100
        or bounds[3] < 100
    ):
        raise TestFailure("DING's desktop frame has unusable screen geometry")
    launched, value = _one_event(
        events,
        context="Desktop shortcut",
        event="desktop-shortcut",
        application="AnduinOS Panel Acceptance Fixture",
        localized_label="创建桌面快捷方式",
        executable=True,
        trusted=True,
        visible=True,
        activation="ding-keyboard-find",
    )
    path = value.get("path")
    windows = value.get("launched_windows")
    if (
        not isinstance(path, str)
        or not path.startswith("/")
        or not path.endswith("/com.anduinos.AcceptancePanelFixture.desktop")
        or windows != ["AnduinOS Panel Fixture Window"]
    ):
        raise TestFailure("The visible desktop shortcut did not launch the fixture")
    if not (
        opened
        < typed
        < result
        < focused
        < context_plan
        < context
        < pointer
        < activated
        < visible
        < foreground
        < focus
        < ding_text
        < search_accept
        < launch
        < launched
    ):
        raise TestFailure("Desktop shortcut UI events are out of order")


def _validate_desktop_icon_events(output: str) -> None:
    events = _all_event_objects(output)
    _, value = _one_event(
        events,
        context="Default desktop icons",
        event="desktop-default-icons",
    )
    icons = value.get("icons")
    if not isinstance(icons, list) or len(icons) != 2:
        raise TestFailure("Default desktop icon evidence is incomplete")
    by_name = {
        item.get("name"): item for item in icons if isinstance(item, dict)
    }
    if set(by_name) != {"主目录", "回收站"}:
        raise TestFailure("The localized Home and Trash desktop icons are not both visible")
    for name_value, item in by_name.items():
        bounds = item.get("bounds")
        if (
            item.get("role") != "label"
            or item.get("application") != "gjs"
            or not isinstance(bounds, list)
            or len(bounds) != 4
            or any(
                isinstance(component, bool) or not isinstance(component, int)
                for component in bounds
            )
            or bounds[2] < 8
            or bounds[3] < 8
        ):
            raise TestFailure(f"Desktop icon {name_value!r} has no usable DING label")
    frame = value.get("desktop_frame")
    if (
        not isinstance(frame, dict)
        or frame.get("role") != "frame"
        or frame.get("application") != "gjs"
        or not str(frame.get("name", "")).startswith("Desktop Icons")
    ):
        raise TestFailure("DING's desktop frame was not positively identified")
    stable = value.get("stable_observations")
    if not isinstance(stable, int) or isinstance(stable, bool) or stable < 4:
        raise TestFailure("Default desktop icons were not stable for four observations")


def _validate_desktop_terminal_events(output: str) -> None:
    events = _all_event_objects(output)
    foreground, foreground_event = _one_event(
        events,
        context="Desktop terminal",
        event="desktop-foreground",
        request="desktop-terminal-show-desktop",
        blockers_after=[],
        ding_frames=1,
    )
    if not isinstance(foreground_event.get("shortcut_sent"), bool):
        raise TestFailure("Desktop terminal foreground evidence is malformed")
    context, context_value = _one_event(
        events,
        context="Desktop terminal",
        event="qmp-click",
        request="desktop-background-context",
        target="desktop-background",
        button="right",
    )
    bounds = context_value.get("bounds")
    if (
        context_value.get("role") != "frame"
        or context_value.get("application") != "gjs"
        or not isinstance(bounds, list)
        or len(bounds) != 4
    ):
        raise TestFailure("Desktop context click did not target DING's desktop frame")
    if context <= foreground:
        raise TestFailure("Desktop terminal clicked before DING was unobstructed")
    plan_index, plan = _one_event(
        events,
        context="Desktop terminal",
        event="desktop-context-menu-plan",
        target="desktop_open_terminal",
        package="gnome-shell-extension-desktop-icons-ng-anduinos",
        focus_origin="first-menu-row",
        atspi_rows_exposed=False,
    )
    if (
        not re.fullmatch(
            r"2\.0\.2-1\+resolute(?:-addon)?",
            str(plan.get("package_version", "")),
        )
        or plan.get("action_tail")
        != [
            "open-in-terminal-desktop",
            "change-background",
            "show-settings",
            "display-settings",
        ]
        or plan.get("up_presses") != 4
        or not str(plan.get("source", "")).endswith(
            "/ding@rastersoft.com/app/desktopMenu.js"
        )
    ):
        raise TestFailure(
            "Desktop terminal reported an unvalidated DING keyboard plan"
        )
    if plan_index <= context:
        raise TestFailure("Desktop terminal planned navigation before opening the menu")
    previous = plan_index
    for number in range(1, 5):
        key_index, _ = _one_event(
            events,
            context="Desktop terminal",
            event="qmp-key",
            request=f"desktop-terminal-menu-up-{number}",
            key="up",
        )
        if key_index <= previous:
            raise TestFailure("Desktop terminal menu navigation is out of order")
        previous = key_index
    activate, _ = _one_event(
        events,
        context="Desktop terminal",
        event="qmp-key",
        request="desktop-terminal-menu-activate",
        key="ret",
    )
    if activate <= previous:
        raise TestFailure("Desktop terminal did not activate its validated menu row")
    opened, terminal = _one_event(
        events,
        context="Desktop terminal",
        event="desktop-terminal",
        phase="opened",
        visible=True,
    )
    application = terminal.get("application")
    windows = terminal.get("windows")
    directory = terminal.get("directory")
    observed_cwds = terminal.get("observed_cwds")
    if (
        not isinstance(application, str)
        or "ptyxis" not in application.casefold()
        or not isinstance(windows, list)
        or not windows
        or not isinstance(directory, str)
        or not directory.startswith("/")
        or Path(directory).name not in {"Desktop", "桌面"}
        or not isinstance(observed_cwds, list)
        or directory not in observed_cwds
        or terminal.get("activation")
        != "desktop-context-menu-versioned-keyboard"
    ):
        raise TestFailure("Desktop context action did not open Ptyxis in the desktop")
    close_key, _ = _one_event(
        events,
        context="Desktop terminal",
        event="qmp-key",
        request="desktop-terminal-close",
        key="alt-f4",
    )
    closed, _ = _one_event(
        events,
        context="Desktop terminal",
        event="desktop-terminal",
        phase="closed",
        visible=False,
    )
    if not activate < opened < close_key < closed:
        raise TestFailure("Desktop terminal UI events are out of order")


def _validate_context_menu_pointer(
    events: list[dict[str, object]],
    *,
    context: str,
    target: str,
    localized: str,
    request_prefix: str,
) -> tuple[int, int]:
    pointer_index, pointer = _one_event(
        events,
        context=context,
        event="qmp-click",
        request=f"{request_prefix}-click",
        target=target,
        accessible_name=localized,
        button="left",
    )
    bounds = pointer.get("bounds")
    if (
        not isinstance(bounds, list)
        or len(bounds) != 4
        or any(
            isinstance(component, bool) or not isinstance(component, int)
            for component in bounds
        )
        or bounds[2] < 2
        or bounds[3] < 2
    ):
        raise TestFailure(f"{context} returned unusable menu-item bounds")
    activated_index, _ = _one_event(
        events,
        context=context,
        event="context-menu-activated",
        target=target,
        accessible_name=localized,
        method="qmp-pointer",
    )
    if pointer_index >= activated_index:
        raise TestFailure(f"{context} pointer activation is out of order")
    return pointer_index, activated_index


def _validate_context_menu_keyboard(
    events: list[dict[str, object]],
    *,
    context: str,
    target: str,
    localized: str,
    request_prefix: str,
) -> tuple[int, int]:
    plan_index, plan = _one_event(
        events,
        context=context,
        event="context-menu-plan",
        target=target,
        accessible_name=localized,
        focus_origin="menu-actor",
    )
    items = plan.get("items")
    target_index = plan.get("target_index")
    down_presses = plan.get("down_presses")
    if (
        not isinstance(items, list)
        or not items
        or not isinstance(target_index, int)
        or isinstance(target_index, bool)
        or not 0 <= target_index < len(items)
        or items[target_index] != localized
        or down_presses != target_index + 1
    ):
        raise TestFailure(f"{context} reported an invalid live menu order")

    previous = plan_index
    for number in range(1, down_presses + 1):
        key_index, _ = _one_event(
            events,
            context=context,
            event="qmp-key",
            request=f"{request_prefix}-down-{number}",
            key="down",
        )
        if key_index <= previous:
            raise TestFailure(f"{context} keyboard navigation is out of order")
        previous = key_index
    return_index, _ = _one_event(
        events,
        context=context,
        event="qmp-key",
        request=f"{request_prefix}-activate",
        key="ret",
    )
    activated_index, activated = _one_event(
        events,
        context=context,
        event="context-menu-activated",
        target=target,
        accessible_name=localized,
        method="qmp-keyboard",
        down_presses=down_presses,
    )
    if not previous < return_index < activated_index:
        raise TestFailure(f"{context} did not activate the planned menu item")
    return plan_index, activated_index


def _validate_spotify_store_events(output: str) -> None:
    events = _all_event_objects(output)
    opened, _ = _one_event(
        events,
        context="Spotify search",
        event="qmp-key",
        request="spotify-search-open",
        key="meta_l",
    )
    typed, _ = _one_event(
        events,
        context="Spotify search",
        event="qmp-text",
        request="spotify-search-text",
    )
    result, search = _one_event(
        events,
        context="Spotify search",
        event="start-search-result",
        query="Spotify",
        accessible_name="Spotify",
        application="gnome-shell",
    )
    if search.get("stable_observations") != 4:
        raise TestFailure("Spotify used an unstable ArcMenu search result")
    focused, _ = _one_event(
        events,
        context="Spotify search",
        event="search-entry-focus",
        query="Spotify",
        role="text",
        application="gnome-shell",
        focused=True,
    )
    activated, activation = _one_event(
        events,
        context="Spotify search",
        event="spotify-result-activated",
        accessible_name="Spotify",
        method="qmp-keyboard",
    )
    activation_key, _ = _one_event(
        events,
        context="Spotify search",
        event="qmp-key",
        request="spotify-result-activate",
        key="ret",
    )
    if activation.get("role") not in {
        "button",
        "menu item",
        "list item",
        "label",
        "text",
    }:
        raise TestFailure("Spotify search activated an unrelated result role")
    details, store = _one_event(
        events,
        context="Spotify search",
        event="spotify-store",
        visible=True,
    )
    application = store.get("application")
    names = store.get("detail_names")
    if (
        not isinstance(application, str)
        or not any(
            token in application.casefold()
            for token in ("gnome-software", "software", "软件")
        )
        or not isinstance(names, list)
        or not any(isinstance(name, str) and name.casefold() == "spotify" for name in names)
    ):
        raise TestFailure("Spotify did not open its real Software details page")
    if not opened < typed < result < focused < activation_key < activated < details:
        raise TestFailure("Spotify search and Software navigation are out of order")


__all__ = tuple(name for name in globals() if name.startswith("_"))
