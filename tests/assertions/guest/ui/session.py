"""GNOME session shortcuts, branding, localization, and appearance."""

from .core import *  # noqa: F403
from .installer import wait_application
from .shell_common import (
    _close_arcmenu,
    _desktop_default_icon_snapshot,
    _open_arcmenu,
    _overview_nodes,
    _wait_shell_named,
    NETWORK_STATS_UUID,
    SHELL_WINDOW_ALPHA,
    SHELL_WINDOW_BETA,
)


def _focused_in(node) -> bool:
    return has_state(node, Atspi.StateType.FOCUSED) or has_state(
        node, Atspi.StateType.ACTIVE
    ) or any(
        has_state(item, Atspi.StateType.FOCUSED)
        or has_state(item, Atspi.StateType.ACTIVE)
        for item in walk(node, maximum=1000)
    )


def _fixture_focus() -> str:
    for item in visible_nodes():
        if name(item) in {SHELL_WINDOW_ALPHA, SHELL_WINDOW_BETA} and _focused_in(item):
            return name(item)
    return ""


def _wait_fixture_focus(expected: str, timeout: float = 30) -> None:
    deadline = time.monotonic() + timeout
    last = ""
    while time.monotonic() < deadline:
        last = _fixture_focus()
        if last == expected:
            return
        time.sleep(0.1)
    raise UiFailure(f"Fixture focus is {last!r}, expected {expected!r}")


def _wait_any_fixture_focus(timeout: float = 30) -> str:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        focused = _fixture_focus()
        if focused in {SHELL_WINDOW_ALPHA, SHELL_WINDOW_BETA}:
            return focused
        time.sleep(0.1)
    raise UiFailure("Neither deterministic shortcut fixture window received focus")


def exercise_alt_tab(evidence: Path) -> None:
    dismiss_initial_setup()
    find(SHELL_WINDOW_ALPHA, timeout=60)
    find(SHELL_WINDOW_BETA, timeout=60)
    before = _wait_any_fixture_focus()
    after = SHELL_WINDOW_ALPHA if before == SHELL_WINDOW_BETA else SHELL_WINDOW_BETA
    event("shortcut-focus", shortcut="alt-tab", phase="before", window=before)
    event("qmp-key", request="shortcut-alt-tab-forward", key="alt-tab")
    _wait_fixture_focus(after)
    event("shortcut-focus", shortcut="alt-tab", phase="after", window=after)
    dump_accessibility(evidence / "alt-tab-other-window-focused.txt")
    event("qmp-key", request="shortcut-alt-tab-restore", key="alt-tab")
    _wait_fixture_focus(before)
    event("shortcut-focus", shortcut="alt-tab", phase="restored", window=before)


def _wait_overview(visible: bool, timeout: float = 30) -> list[tuple[str, str]]:
    deadline = time.monotonic() + timeout
    nodes: list[tuple[str, str]] = []
    while time.monotonic() < deadline:
        nodes = _overview_nodes()
        if bool(nodes) is visible:
            return nodes
        time.sleep(0.1)
    raise UiFailure(
        f"Overview visibility did not become {visible}; panel nodes={nodes!r}"
    )


def assert_initial_overview_hidden(evidence: Path) -> None:
    # This is deliberately an observation-only check.  In particular, do not
    # dismiss Initial Setup or send Escape/Super: either action could hide an
    # Overview that the product incorrectly opened after login.
    markers = _wait_shell_named("start_button", True, timeout=60)
    observations = 0
    overview_nodes: list[tuple[str, str]] = []
    while observations < 8:
        overview_nodes = _overview_nodes()
        if overview_nodes:
            dump_accessibility(evidence / "initial-overview-visible.txt")
            event(
                "initial-overview",
                phase="post-login",
                visible=True,
                stable_observations=observations,
                overview_nodes=overview_nodes,
                shell_ready_markers=[(role(item), name(item)) for item in markers],
            )
            raise UiFailure("GNOME Overview opened automatically after login")
        observations += 1
        time.sleep(0.25)
    dump_accessibility(evidence / "initial-desktop-accessibility.txt")
    event(
        "initial-overview",
        phase="post-login",
        visible=False,
        stable_observations=observations,
        overview_nodes=[],
        shell_ready_markers=[(role(item), name(item)) for item in markers],
    )


def exercise_super_tab(evidence: Path) -> None:
    dismiss_initial_setup()
    _wait_overview(False, timeout=10)
    event("overview", phase="before", visible=False)
    event("qmp-key", request="shortcut-super-tab-show", key="meta_l-tab")
    nodes = _wait_overview(True)
    event("overview", phase="shown", visible=True, nodes=nodes)
    dump_accessibility(evidence / "super-tab-overview-shown.txt")
    event("qmp-key", request="shortcut-super-tab-hide", key="meta_l-tab")
    _wait_overview(False)
    event("overview", phase="restored", visible=False)


def _settings_focused() -> tuple[str, str] | None:
    for item in visible_nodes():
        application = owning_application(item)
        if not any(
            token in application.casefold()
            for token in ("gnome-control-center", "settings", "设置")
        ):
            continue
        if role(item) in {"frame", "window", "dialog"} and _focused_in(item):
            return application, name(item)
    return None


def exercise_super_i(evidence: Path) -> None:
    dismiss_initial_setup()
    event("qmp-key", request="shortcut-super-i", key="meta_l-i")
    deadline = time.monotonic() + 60
    observed = None
    while time.monotonic() < deadline:
        observed = _settings_focused()
        if observed is not None:
            break
        time.sleep(0.2)
    if observed is None:
        raise UiFailure("Super+I did not open a focused GNOME Settings window")
    dump_accessibility(evidence / "super-i-settings-focused.txt")
    event(
        "shortcut-window",
        shortcut="super-i",
        application=observed[0],
        window=observed[1],
        focused=True,
    )


def exercise_settings_about_branding(evidence: Path) -> None:
    """Open GNOME Settings' real About page and identify its painted logo."""

    dismiss_initial_setup()
    environment = [
        f"--setenv={key}={value}"
        for key in (
            "HOME",
            "XDG_RUNTIME_DIR",
            "DBUS_SESSION_BUS_ADDRESS",
            "WAYLAND_DISPLAY",
            "DISPLAY",
            "NO_AT_BRIDGE",
            "XDG_CURRENT_DESKTOP",
            "XDG_SESSION_DESKTOP",
            "DESKTOP_SESSION",
            "GDMSESSION",
        )
        if (value := os.environ.get(key)) is not None
    ]
    runtime_text = os.environ.get("XDG_RUNTIME_DIR", "")
    runtime = Path(runtime_text)
    if not runtime_text or not runtime.is_dir():
        raise UiFailure("The graphical user's XDG runtime directory is unavailable")
    unit = f"anduinos-acceptance-settings-about-{os.getpid()}"
    application_log = runtime / f"{unit}.log"
    application_log.unlink(missing_ok=True)
    launched = subprocess.run(
        [
            "systemd-run",
            "--user",
            f"--unit={unit}",
            "--collect",
            "--property=Type=exec",
            f"--property=StandardOutput=append:{application_log}",
            f"--property=StandardError=append:{application_log}",
            *environment,
            "--",
            "gnome-control-center",
            "system",
            "about",
        ],
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    if launched.returncode != 0:
        raise UiFailure(
            "Could not launch GNOME Settings About page: " + launched.stdout
        )
    application = wait_application(
        ("gnome-control-center", "Settings", "设置"), timeout=90
    )

    expected_names = {value.casefold() for value in aliases("system_logo")}
    about_names = {value.casefold() for value in aliases("about_page")}
    os_label_names = {value.casefold() for value in aliases("operating_system")}
    deadline = time.monotonic() + 60
    logo = None
    logo_bounds = None
    operating_system = ""
    while time.monotonic() < deadline:
        settings_nodes = [
            item
            for item in visible_nodes()
            if owning_application(item) == application
            or any(
                token in owning_application(item).casefold()
                for token in ("gnome-control-center", "settings", "设置")
            )
        ]
        visible_names = [name(item) for item in settings_nodes if name(item)]
        has_about = any(value.casefold() in about_names for value in visible_names)
        has_os_label = any(
            value.casefold() in os_label_names for value in visible_names
        )
        os_names = [value for value in visible_names if "anduinos" in value.casefold()]
        named_images = [
            item
            for item in settings_nodes
            if role(item) in {"image", "icon"}
            and name(item).casefold() in expected_names
        ]
        geometric_images = []
        for item in settings_nodes:
            if role(item) not in {"image", "icon"}:
                continue
            try:
                # Mutter/Wayland deliberately withholds global window
                # positions. WINDOW coordinates remain truthful and are paired
                # with a host-side full-frame asset search.
                bounds = item.get_extents(Atspi.CoordType.WINDOW)
            except Exception:
                continue
            if (
                min(bounds.x, bounds.y) >= 0
                and bounds.width >= 100
                and bounds.height >= 20
                and bounds.width >= bounds.height * 2
            ):
                geometric_images.append((item, bounds))
        candidates = named_images
        if len(candidates) != 1 and len(geometric_images) == 1:
            candidates = [geometric_images[0][0]]
        if has_about and has_os_label and os_names and len(candidates) == 1:
            logo = candidates[0]
            logo_bounds = logo.get_extents(Atspi.CoordType.WINDOW)
            operating_system = max(os_names, key=len)
            break
        time.sleep(0.25)
    if logo is None or logo_bounds is None:
        dump_accessibility(evidence / "settings-about-missing.txt")
        application_output = (
            application_log.read_text(encoding="utf-8", errors="replace")
            if application_log.exists()
            else ""
        )
        raise UiFailure(
            "GNOME Settings did not expose its About identity and system logo:\n"
            + application_output[-4000:]
        )

    gi.require_version("GdkPixbuf", "2.0")
    from gi.repository import GdkPixbuf

    assets = []
    for variant, asset in (
        ("light", Path("/usr/share/pixmaps/ubuntu-logo-text.svg")),
        ("dark", Path("/usr/share/pixmaps/ubuntu-logo-text-dark.svg")),
    ):
        if not asset.is_file():
            raise UiFailure(f"GNOME Settings About asset is missing: {asset}")
        source = asset.read_text(encoding="utf-8", errors="replace")
        markers = []
        if 'aria-label="ANDUINOS"' in source:
            markers.append("ANDUINOS")
        if 'export-batch-name="anduinos"' in source:
            markers.append("anduinos")
        if markers != ["ANDUINOS", "anduinos"]:
            raise UiFailure(f"About asset does not identify AnduinOS: {asset}")
        template = evidence / f"settings-about-{variant}-logo.png"
        pixbuf = GdkPixbuf.Pixbuf.new_from_file_at_scale(
            str(asset), logo_bounds.width, logo_bounds.height, True
        )
        if not pixbuf.savev(str(template), "png", [], []):
            raise UiFailure(f"Could not render GNOME Settings About asset: {asset}")
        assets.append(
            {
                "path": str(asset),
                "sha256": hashlib.sha256(asset.read_bytes()).hexdigest(),
                "brand_markers": markers,
                "rendered_template": str(template),
                "rendered_size": [pixbuf.get_width(), pixbuf.get_height()],
            }
        )
    dump_accessibility(evidence / "settings-about-visible.txt")
    event(
        "settings-about-branding",
        application=application,
        page="about",
        operating_system=operating_system,
        logo_name=name(logo),
        logo_role=role(logo),
        coordinate_space="window",
        bounds=[
            logo_bounds.x,
            logo_bounds.y,
            logo_bounds.width,
            logo_bounds.height,
        ],
        assets=assets,
    )


def exercise_localization_zh_cn(evidence: Path) -> None:
    """Observe Chinese text on Settings, DING, and ArcMenu in one real session."""

    # This leaves the real About page visible.  Its existing branding oracle
    # also proves that these labels belong to GNOME Settings rather than to a
    # synthetic test window; this check independently requires the Chinese
    # labels instead of accepting the English aliases used by the branding test.
    exercise_settings_about_branding(evidence)
    settings_names = sorted({name(item) for item in visible_nodes() if name(item)})
    settings_required = {"关于", "操作系统"}
    if not settings_required <= set(settings_names):
        dump_accessibility(evidence / "localization-settings-failed.txt")
        raise UiFailure(
            "GNOME Settings About is not localized to Simplified Chinese: "
            f"missing={sorted(settings_required - set(settings_names))!r}"
        )
    subprocess.run(
        ("pkill", "-f", "(^|/)gnome-control-center( |$)"),
        check=False,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    time.sleep(1)

    _frame, desktop_icons = _desktop_default_icon_snapshot()
    desktop_labels = sorted(item["name"] for item in desktop_icons)
    if desktop_labels != ["主目录", "回收站"]:
        raise UiFailure(
            "DING default icons are not localized to Simplified Chinese: "
            f"{desktop_labels!r}"
        )

    menu_nodes = _open_arcmenu("localization-start-menu-open")
    try:
        menu_labels = sorted({name(item) for item in menu_nodes})
        menu_required = {"已固定", "所有应用程序"}
        if not menu_required <= set(menu_labels):
            dump_accessibility(evidence / "localization-arcmenu-failed.txt")
            raise UiFailure(
                "ArcMenu is not localized to Simplified Chinese: "
                f"missing={sorted(menu_required - set(menu_labels))!r}"
            )
    finally:
        _close_arcmenu("localization-start-menu-close")

    dump_accessibility(evidence / "localization-zh-cn.txt")
    event(
        "localization-zh-cn",
        settings_labels=sorted(settings_required),
        desktop_labels=desktop_labels,
        arcmenu_labels=menu_labels,
    )


def observe_installed_region_zh_cn(evidence: Path) -> None:
    """Observe the already-running desktop without launching or changing UI."""

    frame, desktop_icons = _desktop_default_icon_snapshot()
    bounds = frame.get_extents(Atspi.CoordType.SCREEN)
    labels = sorted(item["name"] for item in desktop_icons)
    dump_accessibility(evidence / "installed-region-zh-cn.txt")
    event(
        "installed-region-zh-cn",
        desktop_labels=labels,
        desktop_frame={
            "name": name(frame),
            "role": role(frame),
            "application": owning_application(frame),
            "bounds": [bounds.x, bounds.y, bounds.width, bounds.height],
        },
    )


def exercise_swapcontrol_green(evidence: Path) -> None:
    """Launch Swap Control and expose its real default Dashboard to the host."""

    dismiss_initial_setup()
    environment = [
        f"--setenv={key}={value}"
        for key in (
            "HOME",
            "XDG_RUNTIME_DIR",
            "DBUS_SESSION_BUS_ADDRESS",
            "WAYLAND_DISPLAY",
            "DISPLAY",
            "NO_AT_BRIDGE",
            "XDG_CURRENT_DESKTOP",
            "XDG_SESSION_DESKTOP",
            "DESKTOP_SESSION",
            "GDMSESSION",
        )
        if (value := os.environ.get(key)) is not None
    ]
    unit = f"anduinos-acceptance-swapcontrol-{os.getpid()}"
    launched = subprocess.run(
        [
            "systemd-run",
            "--user",
            f"--unit={unit}",
            "--collect",
            "--property=Type=exec",
            *environment,
            "--",
            "swapcontrol-gtk",
        ],
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    if launched.returncode != 0:
        raise UiFailure("Could not launch Swap Control: " + launched.stdout)
    application = wait_application(
        ("swapcontrol-gtk", "Virtual Memory Control", "虚拟内存控制"),
        timeout=90,
    )
    authentication = "not-present"
    if find_optional("polkit", timeout=10) is not None:
        event(
            "secret-focus",
            request="swapcontrol-auth-password",
            target="password",
            method="polkit-initial-password-focus",
        )
        _request_secret_delivery(
            "password",
            "swapcontrol-auth-password",
            verify_character_count=False,
        )
        event("qmp-key", request="swapcontrol-auth-submit", key="ret")
        wait_absent("polkit", timeout=15)
        authentication = "authenticated"
    event("swapcontrol-authentication", outcome=authentication)
    marker_aliases = {
        "dashboard": {"Dashboard", "仪表板"},
        "memory-overview": {"Memory Overview", "内存概览"},
        "swap": {"Swap", "Virtual Memory", "虚拟内存"},
        "zram": {"Zram", "Compressed Memory Segments", "压缩内存段"},
    }
    deadline = time.monotonic() + 60
    observed: dict[str, str] = {}
    frame = None
    while time.monotonic() < deadline:
        nodes = [
            item
            for item in visible_nodes()
            if owning_application(item) == application
            or "swapcontrol" in owning_application(item).casefold()
        ]
        names = {name(item) for item in nodes if name(item)}
        observed = {
            marker: sorted(names & aliases)[0]
            for marker, aliases in marker_aliases.items()
            if names & aliases
        }
        frames = [
            item
            for item in nodes
            if role(item) in {"frame", "window"}
        ]
        if set(observed) == set(marker_aliases) and len(frames) == 1:
            frame = frames[0]
            break
        time.sleep(0.25)
    if frame is None:
        dump_accessibility(evidence / "swapcontrol-dashboard-missing.txt")
        raise UiFailure(
            "Swap Control did not expose its default Dashboard: "
            f"markers={observed!r}"
        )
    bounds = frame.get_extents(Atspi.CoordType.WINDOW)
    if bounds.width < 640 or bounds.height < 400:
        raise UiFailure(
            "Swap Control returned an implausible Dashboard window: "
            f"{bounds.width}x{bounds.height}"
        )
    dump_accessibility(evidence / "swapcontrol-dashboard-visible.txt")
    event(
        "swapcontrol-dashboard",
        application=application,
        page="dashboard",
        markers=sorted(observed),
        observed_labels=observed,
        authentication=authentication,
        accessibility_focus=_focused_in(frame),
        coordinate_space="window",
        bounds=[bounds.x, bounds.y, bounds.width, bounds.height],
    )


def _extension_state(identifier: str) -> str:
    result = subprocess.run(
        ("gnome-extensions", "show", identifier),
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        env={**os.environ, "LC_ALL": "C"},
    )
    if result.returncode != 0:
        raise UiFailure(f"Could not inspect extension {identifier}: {result.stdout}")
    match = re.search(r"^\s*State:\s*(\S+)", result.stdout, re.MULTILINE)
    if match is None:
        raise UiFailure(f"Extension state is absent: {result.stdout}")
    return match.group(1).upper()


def _network_stats_nodes() -> list[tuple[str, str]]:
    pattern = re.compile(r"(?:↕|↑|↓|Σ).*(?:bit|byte|[KMG]?B|/s)", re.IGNORECASE)
    return [
        (role(item), name(item))
        for item in visible_nodes()
        if owning_application(item) == "gnome-shell" and pattern.search(name(item))
    ]


def _wait_network_stats(active: bool, timeout: float = 45) -> tuple[str, list[tuple[str, str]]]:
    deadline = time.monotonic() + timeout
    last_state = ""
    nodes: list[tuple[str, str]] = []
    while time.monotonic() < deadline:
        last_state = _extension_state(NETWORK_STATS_UUID)
        nodes = _network_stats_nodes()
        active_states = {"ACTIVE", "ENABLED"}
        inactive_states = {"INITIALIZED", "INACTIVE", "DISABLED"}
        expected_states = active_states if active else inactive_states
        if last_state in expected_states and bool(nodes) is active:
            return last_state, nodes
        time.sleep(0.25)
    raise UiFailure(
        f"Network Stats active={active} was not visible; state={last_state}, nodes={nodes!r}"
    )


def exercise_super_u(evidence: Path) -> None:
    dismiss_initial_setup()
    before_state, _ = _wait_network_stats(False, timeout=15)
    event("network-stats", phase="before", state=before_state, visible=False)
    event("qmp-key", request="shortcut-super-u-show", key="meta_l-u")
    active_state, nodes = _wait_network_stats(True)
    event("network-stats", phase="shown", state=active_state, visible=True, nodes=nodes)
    dump_accessibility(evidence / "super-u-network-stats-shown.txt")
    event("qmp-key", request="shortcut-super-u-hide", key="meta_l-u")
    final_state, _ = _wait_network_stats(False)
    event("network-stats", phase="restored", state=final_state, visible=False)


def _pictures_directory() -> Path:
    result = subprocess.run(
        ("xdg-user-dir", "PICTURES"),
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    value = result.stdout.strip()
    if result.returncode != 0 or not value:
        raise UiFailure(f"Could not locate Pictures: {result.stdout!r}")
    return Path(value)


def _wait_screenshot_modes(timeout: float = 30) -> list[str]:
    expected = (
        {"selection", "选区"},
        {"screen", "屏幕"},
        {"window", "窗口"},
    )
    deadline = time.monotonic() + timeout
    last: list[str] = []
    while time.monotonic() < deadline:
        last = [
            name(item)
            for item in visible_nodes()
            if owning_application(item) == "gnome-shell"
            and role(item) == "label"
            and name(item)
        ]
        matched = [
            next((label for label in last if label.casefold() in names), "")
            for names in expected
        ]
        if all(matched):
            return matched
        time.sleep(0.1)
    raise UiFailure(
        "GNOME screenshot UI did not expose all three semantic modes; "
        f"labels={last!r}"
    )


def exercise_screenshot_shortcut(evidence: Path) -> None:
    dismiss_initial_setup()
    pictures = _pictures_directory()
    before = {str(path) for path in pictures.rglob("*.png")} if pictures.exists() else set()
    event("qmp-key", request="shortcut-screenshot-open", key="meta_l-shift-s")
    modes = _wait_screenshot_modes()
    dump_accessibility(evidence / "screenshot-ui-shown.txt")
    event(
        "screenshot-ui",
        visible=True,
        modes=modes,
        completion="focused-default-action",
    )
    event("qmp-key", request="shortcut-screenshot-capture", key="ret")
    deadline = time.monotonic() + 45
    created: list[Path] = []
    while time.monotonic() < deadline:
        current = list(pictures.rglob("*.png")) if pictures.exists() else []
        created = [path for path in current if str(path) not in before]
        if len(created) == 1 and created[0].stat().st_size > 1024:
            if created[0].read_bytes()[:8] == b"\x89PNG\r\n\x1a\n":
                break
        time.sleep(0.25)
    else:
        raise UiFailure(f"Screenshot shortcut created no unique valid PNG: {created!r}")
    result = {
        "path": str(created[0]),
        "size": created[0].stat().st_size,
        "png_signature": True,
    }
    (evidence / "screenshot-result.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    event("screenshot-created", **result)
__all__ = tuple(name for name in globals() if not name.startswith("__"))
