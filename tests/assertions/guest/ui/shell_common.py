"""Shared ArcMenu and desktop-surface discovery primitives."""

from .core import *  # noqa: F403

SHELL_WINDOW_ALPHA = "AnduinOS Shortcut Window Alpha"
SHELL_WINDOW_BETA = "AnduinOS Shortcut Window Beta"
NETWORK_STATS_UUID = "network-stats@gnome.noroadsleft.xyz"
PANEL_FIXTURE_NAME = "AnduinOS Panel Acceptance Fixture"
PANEL_WINDOW_TITLE = "AnduinOS Panel Fixture Window"


def _overview_nodes() -> list[tuple[str, str]]:
    candidates = {value.casefold() for value in aliases("overview_panel")}
    return [
        (role(item), name(item))
        for item in visible_nodes()
        if owning_application(item) == "gnome-shell"
        and role(item) == "panel"
        and name(item).casefold() in candidates
    ]


def _visible_shell_named(key: str) -> list:
    candidates = {value.casefold() for value in aliases(key)}
    return [
        item
        for item in visible_nodes()
        if owning_application(item) == "gnome-shell"
        and name(item).casefold() in candidates
    ]


def _wait_shell_named(key: str, present: bool, timeout: float = 30) -> list:
    deadline = time.monotonic() + timeout
    nodes = []
    while time.monotonic() < deadline:
        nodes = _visible_shell_named(key)
        if bool(nodes) is present:
            return nodes
        time.sleep(0.1)
    raise UiFailure(
        f"GNOME Shell node {key!r} visibility did not become {present}; "
        f"nodes={[(role(item), name(item)) for item in nodes]!r}"
    )


def _arcmenu_markers() -> list:
    pinned = _visible_shell_named("arcmenu_pinned")
    all_apps = _visible_shell_named("arcmenu_all_apps")
    return [*pinned, *all_apps] if pinned and all_apps else []


def _wait_arcmenu(present: bool, timeout: float = 30) -> list:
    deadline = time.monotonic() + timeout
    nodes = []
    while time.monotonic() < deadline:
        nodes = _arcmenu_markers()
        if bool(nodes) is present:
            return nodes
        time.sleep(0.1)
    raise UiFailure(
        f"ArcMenu visibility did not become {present}; "
        f"markers={[(role(item), name(item)) for item in nodes]!r}"
    )


def _open_arcmenu(request: str) -> list:
    _wait_arcmenu(False, timeout=5)
    event("qmp-key", request=request, key="meta_l")
    nodes = _wait_arcmenu(True)
    if _overview_nodes():
        raise UiFailure("Super opened GNOME Overview instead of ArcMenu")
    event(
        "start-menu",
        phase="shown",
        markers=sorted({name(item) for item in nodes}),
        marker_roles=sorted({role(item) for item in nodes}),
        overview_visible=False,
    )
    return nodes


def _visible_shell_result(value: str) -> list:
    folded = value.casefold()
    return [
        item
        for item in visible_nodes()
        if owning_application(item) == "gnome-shell"
        and name(item).casefold() == folded
    ]


def _close_arcmenu(request: str, search_result: str = "") -> None:
    """Close both ArcMenu's search view and its ordinary main view.

    Search mode hides the pinned/all-apps markers used by _wait_arcmenu.
    Treating their absence as a closed menu leaves the search entry in front of
    the desktop. Escape can first return search to the main view and only then
    close ArcMenu, so observe both surfaces and allow a bounded second press.
    """

    for attempt in range(2):
        markers = _arcmenu_markers()
        results = _visible_shell_result(search_result) if search_result else []
        if not markers and not results:
            return
        key_request = request if attempt == 0 else f"{request}-main"
        event("qmp-key", request=key_request, key="esc")
        previous = (
            tuple(sorted((role(item), name(item)) for item in markers)),
            tuple(sorted((role(item), name(item)) for item in results)),
        )
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            markers = _arcmenu_markers()
            results = (
                _visible_shell_result(search_result) if search_result else []
            )
            current = (
                tuple(sorted((role(item), name(item)) for item in markers)),
                tuple(sorted((role(item), name(item)) for item in results)),
            )
            if not markers and not results:
                return
            if current != previous:
                break
            time.sleep(0.1)
    markers = _arcmenu_markers()
    results = _visible_shell_result(search_result) if search_result else []
    if markers or results:
        raise UiFailure(
            "ArcMenu remained visible after bounded Escape handling; "
            f"markers={[(role(item), name(item)) for item in markers]!r}, "
            f"results={[(role(item), name(item)) for item in results]!r}"
        )
def _desktop_fixture_path() -> Path:
    result = subprocess.run(
        ("xdg-user-dir", "DESKTOP"),
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    desktop = result.stdout.strip()
    if result.returncode != 0 or not desktop:
        raise UiFailure(f"Could not locate the desktop directory: {result.stdout!r}")
    return Path(desktop) / "com.anduinos.AcceptancePanelFixture.desktop"


def _wait_desktop_fixture_node(timeout: float = 60):
    deadline = time.monotonic() + timeout
    candidates = []
    while time.monotonic() < deadline:
        candidates = [
            item
            for item in visible_nodes()
            if owning_application(item) == "gjs"
            and role(item) == "label"
            and name(item) == PANEL_FIXTURE_NAME
        ]
        for item in candidates:
            try:
                bounds = item.get_extents(Atspi.CoordType.SCREEN)
                if bounds.width >= 8 and bounds.height >= 8:
                    return item
            except Exception:
                continue
        time.sleep(0.25)
    raise UiFailure(
        "DING did not expose the created desktop fixture icon; "
        f"candidates={[(role(item), name(item)) for item in candidates]!r}"
    )


def _desktop_frames() -> list:
    return [
        item
        for item in visible_nodes()
        if owning_application(item) == "gjs"
        and role(item) == "frame"
        and name(item).startswith("Desktop Icons")
    ]


def _visible_desktop_blockers() -> list[tuple[str, str, str]]:
    blockers = []
    for item in visible_nodes():
        item_role = role(item)
        application = owning_application(item)
        if item_role not in {"frame", "window", "dialog"}:
            continue
        if application in {"gjs", "gnome-shell"}:
            continue
        blockers.append((application, item_role, name(item)))
    return sorted(set(blockers))


def _ensure_desktop_foreground(request: str) -> None:
    """Expose DING before asking the host to click its screen rectangle."""

    frames = _desktop_frames()
    if len(frames) != 1:
        raise UiFailure(f"Expected one DING desktop frame, observed {len(frames)}")
    before = _visible_desktop_blockers()
    shortcut_sent = bool(before)
    if shortcut_sent:
        event("qmp-key", request=request, key="meta_l-d")
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline and _visible_desktop_blockers():
            time.sleep(0.1)
    after = _visible_desktop_blockers()
    if after:
        raise UiFailure(
            "Super+D did not expose an unobstructed DING desktop; "
            f"blockers={after!r}"
        )
    event(
        "desktop-foreground",
        request=request,
        shortcut_sent=shortcut_sent,
        blockers_before=[list(item) for item in before],
        blockers_after=[],
        ding_frames=len(_desktop_frames()),
    )


def _desktop_default_icon_snapshot() -> tuple[object, list[dict[str, object]]]:
    frames = _desktop_frames()
    if len(frames) != 1:
        raise UiFailure(f"Expected one DING desktop frame, observed {len(frames)}")
    expected = {"主目录", "回收站"}
    nodes = [
        item
        for item in visible_nodes()
        if owning_application(item) == "gjs"
        and role(item) == "label"
        and name(item) in expected
    ]
    if len(nodes) != 2 or {name(item) for item in nodes} != expected:
        raise UiFailure(
            "DING did not expose exactly one localized Home and Trash label"
        )
    icons = []
    for item in sorted(nodes, key=name):
        bounds = item.get_extents(Atspi.CoordType.SCREEN)
        if min(bounds.x, bounds.y, bounds.width, bounds.height) < 0:
            raise UiFailure(f"Desktop icon {name(item)!r} has invalid bounds")
        icons.append(
            {
                "name": name(item),
                "role": role(item),
                "application": owning_application(item),
                "bounds": [bounds.x, bounds.y, bounds.width, bounds.height],
            }
        )
    return frames[0], icons


def verify_default_desktop_icons(evidence: Path) -> None:
    dismiss_initial_setup()
    deadline = time.monotonic() + 60
    stable_signature = None
    stable_observations = 0
    frame = None
    icons: list[dict[str, object]] = []
    while time.monotonic() < deadline:
        try:
            frame, icons = _desktop_default_icon_snapshot()
        except UiFailure:
            stable_signature = None
            stable_observations = 0
            time.sleep(0.25)
            continue
        signature = tuple(
            (item["name"], tuple(item["bounds"])) for item in icons
        )
        if signature == stable_signature:
            stable_observations += 1
        else:
            stable_signature = signature
            stable_observations = 1
        if stable_observations >= 4:
            break
        time.sleep(0.25)
    if frame is None or stable_observations < 4:
        raise UiFailure("Default desktop icons did not become stably visible")
    frame_bounds = frame.get_extents(Atspi.CoordType.SCREEN)
    dump_accessibility(evidence / "default-desktop-icons.txt")
    event(
        "desktop-default-icons",
        stable_observations=stable_observations,
        icons=icons,
        desktop_frame={
            "name": name(frame),
            "role": role(frame),
            "application": owning_application(frame),
            "bounds": [
                frame_bounds.x,
                frame_bounds.y,
                frame_bounds.width,
                frame_bounds.height,
            ],
        },
    )
__all__ = tuple(name for name in globals() if not name.startswith("__"))
