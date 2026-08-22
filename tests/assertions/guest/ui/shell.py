"""ArcMenu, taskbar, desktop shortcut, terminal, and store behavior."""

from .core import *  # noqa: F403
from .installer import wait_application
from .shell_common import *  # noqa: F403


def _open_arcmenu_search(value: str, request: str) -> tuple[object, object, object]:
    _open_arcmenu(f"{request}-open")
    event("qmp-text", request=f"{request}-text")
    deadline = time.monotonic() + 90
    candidates = []
    stable_signature = None
    stable_observations = 0
    focus_diagnostic_emitted = False
    while time.monotonic() < deadline:
        candidates = [
            item
            for item in visible_nodes()
            if owning_application(item) == "gnome-shell"
            and name(item).casefold() == value.casefold()
            and role(item) in {"button", "menu item", "list item", "label"}
        ]
        actionable_candidates = []
        for item in candidates:
            try:
                action = actionable(item)
            except UiFailure:
                continue
            actionable_candidates.append((item, action))
        if len(actionable_candidates) == 1:
            semantic, target = actionable_candidates[0]
            # GNOME Shell 50 exposes SearchEntry's inner ClutterText as one
            # anonymous focused `text` node.  It does not implement GTK's
            # EditableText interface and its Atspi.Text contents are empty.
            # The preceding physical QMP text stream establishes what was
            # entered; the unique focused Shell text node proves that the
            # source-defined popup-menu receiver still owns keyboard focus.
            search_entries = [
                item
                for item in visible_nodes()
                if owning_application(item) == "gnome-shell"
                and role(item) == "text"
                and has_state(item, Atspi.StateType.FOCUSED)
            ]
            if len(search_entries) != 1:
                if not focus_diagnostic_emitted:
                    diagnostic = []
                    for item in visible_nodes():
                        item_text = accessible_text(item)
                        if (
                            has_state(item, Atspi.StateType.FOCUSED)
                            or item_text == value
                            or name(item) == value
                        ):
                            diagnostic.append(
                                {
                                    "name": name(item),
                                    "role": role(item),
                                    "text": item_text,
                                    "application": owning_application(item),
                                    "focused": has_state(
                                        item,
                                        Atspi.StateType.FOCUSED,
                                    ),
                                }
                            )
                    event(
                        "search-focus-diagnostic",
                        query=value,
                        candidates=diagnostic,
                    )
                    focus_diagnostic_emitted = True
                stable_signature = None
                stable_observations = 0
                time.sleep(0.25)
                continue
            search_entry = search_entries[0]
            try:
                bounds = semantic.get_extents(Atspi.CoordType.SCREEN)
                signature = (
                    name(semantic),
                    role(target),
                    bounds.x,
                    bounds.y,
                    bounds.width,
                    bounds.height,
                )
            except Exception:
                signature = (name(semantic), role(target))
            if signature == stable_signature:
                stable_observations += 1
            else:
                stable_signature = signature
                stable_observations = 1
            # Remote providers can replace ArcMenu's top-result actor while
            # the first result is already visible.  Four identical semantic
            # observations span 750 ms and prevent Shift+F10 from racing that
            # replacement without relying on a fixed post-search sleep.
            if stable_observations < 4:
                time.sleep(0.25)
                continue
            event(
                "start-search-result",
                query=value,
                accessible_name=name(semantic),
                role=role(target),
                application=owning_application(target),
                stable_observations=stable_observations,
            )
            event(
                "search-entry-focus",
                query=value,
                accessible_name=name(search_entry),
                accessible_text=accessible_text(search_entry),
                role=role(search_entry),
                application=owning_application(search_entry),
                focused=True,
            )
            return semantic, target, search_entry
        if len(actionable_candidates) > 1:
            raise UiFailure(
                f"ArcMenu search returned multiple actionable exact results for {value!r}"
            )
        time.sleep(0.25)
    raise UiFailure(
        f"ArcMenu search returned no actionable exact result for {value!r}; "
        f"candidates={[(role(item), name(item)) for item in candidates]!r}"
    )


def request_search_result_context(
    search_entry,
    request: str,
    semantic_target: str,
) -> None:
    """Open ArcMenu's top-result menu through its source-defined key path."""

    if (
        owning_application(search_entry) != "gnome-shell"
        or role(search_entry) != "text"
        or not has_state(search_entry, Atspi.StateType.FOCUSED)
    ):
        raise UiFailure("ArcMenu search entry lost keyboard focus")
    # ArcMenu's SearchEntry source owns a `popup-menu` handler which resolves
    # searchResults.getTopResult() and calls popupMenu() on that exact actor.
    # Shift+F10 therefore exercises the same extension-owned path as a user's
    # context-menu key while avoiding GNOME Shell's horizontally shifted
    # accessibility coordinates for grid result labels.
    event(
        "search-result-context",
        target=semantic_target,
        query=semantic_target,
        application="gnome-shell",
        focused=True,
        method="search-entry-popup-menu",
    )
    event(
        "qmp-key",
        request=f"{request}-context",
        key="shift-f10",
    )


def activate_shell_context_action(key: str, request: str) -> str:
    """Activate one exact visible Shell menu item with physical keyboard input."""

    node = _wait_shell_named(key, True)[0]
    localized = name(node)
    target = actionable(node)
    items: list[str] = []
    target_index = -1
    levels: list[list[str]] = []
    current = target
    for _depth in range(8):
        try:
            parent = current.get_parent()
        except Exception:
            break
        if parent is None:
            break
        candidate_items: list[str] = []
        candidate_index = -1
        for sibling in children(parent):
            if not showing(sibling):
                continue
            labels = [
                name(item)
                for item in walk(sibling, maximum=80)
                if showing(item) and name(item)
            ]
            if not labels:
                continue
            candidate_items.append(labels[0])
            if any(value == localized for value in labels):
                candidate_index = len(candidate_items) - 1
        levels.append(candidate_items)
        if candidate_index >= 0 and len(candidate_items) >= 2:
            items = candidate_items
            target_index = candidate_index
            break
        current = parent
    if target_index < 0 or len(items) < 2:
        raise UiFailure(
            f"Could not derive context-menu order for {localized!r}; "
            f"ancestor_levels={levels!r}"
        )

    # PopupMenuManager gives the menu actor focus. Its first Down moves focus
    # to the first visible item, and PopupMenuItem then wraps physical arrow
    # navigation. Derive the number of presses from the live accessible menu
    # order, then activate with Return; no private extension API or coordinates.
    down_presses = target_index + 1
    event(
        "context-menu-plan",
        target=key,
        accessible_name=localized,
        items=items,
        target_index=target_index,
        down_presses=down_presses,
        focus_origin="menu-actor",
    )
    for index in range(down_presses):
        event(
            "qmp-key",
            request=f"{request}-down-{index + 1}",
            key="down",
        )
    event("qmp-key", request=f"{request}-activate", key="ret")
    _wait_shell_named(key, False)
    event(
        "context-menu-activated",
        target=key,
        accessible_name=localized,
        method="qmp-keyboard",
        down_presses=down_presses,
    )
    return localized


def activate_shell_context_action_pointer(key: str, request: str) -> str:
    """Click one semantically identified Shell menu item with QEMU input."""

    node = _wait_shell_named(key, True)[0]
    localized = name(node)
    request_shell_click(key, f"{request}-click")
    _wait_shell_named(key, False)
    event(
        "context-menu-activated",
        target=key,
        accessible_name=localized,
        method="qmp-pointer",
    )
    return localized


def exercise_start_button(evidence: Path) -> None:
    dismiss_initial_setup()
    asset = Path(
        "/usr/share/gnome-shell/extensions/arcmenu@arcmenu.com/icons/"
        "anduinos-logo.svg"
    )
    schema_dir = (
        "/usr/share/gnome-shell/extensions/arcmenu@arcmenu.com/schemas"
    )
    schema = "org.gnome.shell.extensions.arcmenu"
    configured = {}
    for key in ("menu-button-icon",):
        result = subprocess.run(
            ("gsettings", "--schemadir", schema_dir, "get", schema, key),
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )
        configured[key] = result.stdout.strip().strip("'")
        if result.returncode != 0 or configured[key] != str(asset):
            raise UiFailure(
                f"ArcMenu {key} does not select the shipped AnduinOS logo: "
                f"{result.stdout!r}"
            )
    size_result = subprocess.run(
        (
            "gsettings",
            "--schemadir",
            schema_dir,
            "get",
            schema,
            "menu-button-icon-size",
        ),
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    try:
        icon_size = round(float(size_result.stdout.strip()))
    except ValueError as error:
        raise UiFailure(
            f"ArcMenu returned an invalid icon size: {size_result.stdout!r}"
        ) from error
    if size_result.returncode != 0 or not 16 <= icon_size <= 64 or not asset.is_file():
        raise UiFailure("The configured AnduinOS Start asset is unavailable")

    # Render the exact installed SVG through the guest's production
    # GdkPixbuf loader.  The host later template-matches this image against a
    # QEMU screendump of the real panel, proving the asset was painted rather
    # than merely configured.
    gi.require_version("GdkPixbuf", "2.0")
    from gi.repository import GdkPixbuf

    template = evidence / "start-button-installed-logo.png"
    pixbuf = GdkPixbuf.Pixbuf.new_from_file_at_scale(
        str(asset), icon_size, icon_size, True
    )
    if not pixbuf.savev(str(template), "png", [], []):
        raise UiFailure("Could not render the installed AnduinOS Start asset")
    nodes = _visible_shell_named("start_button")
    if len(nodes) != 1:
        dump_accessibility(evidence / "start-button-missing.txt")
        raise UiFailure(f"Expected one visible Start button, observed {len(nodes)}")
    target = nodes[0]
    try:
        bounds = target.get_extents(Atspi.CoordType.SCREEN)
    except Exception as error:
        raise UiFailure(f"Could not read Start button bounds: {error}")
    bounds_usable = (
        min(bounds.x, bounds.y) >= 0
        and min(bounds.width, bounds.height) >= 16
    )
    event(
        "start-button",
        accessible_name=name(target),
        role=role(target),
        bounds=[bounds.x, bounds.y, bounds.width, bounds.height],
        bounds_usable=bounds_usable,
        asset=str(asset),
        asset_sha256=hashlib.sha256(asset.read_bytes()).hexdigest(),
        rendered_template=str(template),
        rendered_size=[pixbuf.get_width(), pixbuf.get_height()],
    )
    _open_arcmenu("start-button-open")
    dump_accessibility(evidence / "start-menu-open.txt")
    _close_arcmenu("start-button-close")
    event("start-menu", phase="restored", visible=False)


def _wait_taskbar_fixture(present: bool, timeout: float = 45):
    deadline = time.monotonic() + timeout
    nodes = []
    while time.monotonic() < deadline:
        nodes = [
            item
            for item in visible_nodes()
            if owning_application(item) == "gnome-shell"
            and name(item) == PANEL_FIXTURE_NAME
            and role(item) in {"button", "toggle button"}
        ]
        if bool(nodes) is present:
            if present and len(nodes) != 1:
                raise UiFailure("Taskbar exposes an ambiguous fixture launcher")
            return nodes[0] if nodes else None
        time.sleep(0.1)
    raise UiFailure(
        f"Fixture taskbar launcher visibility did not become {present}; count={len(nodes)}"
    )


def exercise_panel_pin(evidence: Path) -> None:
    dismiss_initial_setup()
    if _wait_taskbar_fixture(False, timeout=5) is not None:
        raise UiFailure("Fixture unexpectedly began pinned to the taskbar")
    _semantic, _target, search_entry = _open_arcmenu_search(
        PANEL_FIXTURE_NAME,
        "panel-pin-search",
    )
    request_search_result_context(search_entry, "panel-pin", PANEL_FIXTURE_NAME)
    item = _wait_shell_named("taskbar_pin", True)[0]
    localized = name(item)
    if localized not in {"Pin to Dash", "添加到任务栏"}:
        raise UiFailure(f"Unexpected taskbar pin label: {localized!r}")
    activated = activate_shell_context_action("taskbar_pin", "panel-pin-action")
    if activated != localized:
        raise UiFailure("Taskbar action identity changed before activation")
    _close_arcmenu("panel-pin-close")
    launcher = _wait_taskbar_fixture(True)
    dump_accessibility(evidence / "fixture-pinned-to-taskbar.txt")
    event(
        "panel-pinned",
        application=PANEL_FIXTURE_NAME,
        menu_label=localized,
        launcher_name=name(launcher),
        launcher_role=role(launcher),
    )


def exercise_panel_pin_persisted(evidence: Path) -> None:
    """Prove the launcher survived destruction and recreation of GNOME Shell."""

    dismiss_initial_setup()
    launcher = _wait_taskbar_fixture(True, timeout=60)
    dump_accessibility(evidence / "fixture-pinned-after-login.txt")
    event(
        "panel-pinned-after-login",
        application=PANEL_FIXTURE_NAME,
        launcher_name=name(launcher),
        launcher_role=role(launcher),
        visible=True,
    )


def exercise_panel_remove(evidence: Path) -> None:
    dismiss_initial_setup()
    launcher = _wait_taskbar_fixture(True)
    request_node_click(launcher, "panel-remove-context", button="right")
    item = _wait_shell_named("taskbar_unpin", True)[0]
    localized = name(item)
    if localized != "从任务栏中移除":
        raise UiFailure(
            "Chinese taskbar context menu did not expose '从任务栏中移除': "
            f"{localized!r}"
        )
    dump_accessibility(evidence / "taskbar-remove-menu.txt")
    activated = activate_shell_context_action(
        "taskbar_unpin",
        "panel-remove-action",
    )
    if activated != localized:
        raise UiFailure("Taskbar remove action identity changed before activation")
    _wait_taskbar_fixture(False)
    event(
        "panel-removed",
        application=PANEL_FIXTURE_NAME,
        localized_label=localized,
        launcher_visible=False,
    )
def _terminal_windows() -> list[tuple[str, str, str]]:
    values = []
    for item in visible_nodes():
        application = owning_application(item)
        if "ptyxis" not in application.casefold():
            continue
        if role(item) not in {"frame", "window", "dialog"}:
            continue
        values.append((application, role(item), name(item)))
    return values


def _desktop_terminal_keyboard_plan(evidence: Path) -> int:
    """Validate the exact DING menu whose inaccessible GTK row we navigate."""

    package = "gnome-shell-extension-desktop-icons-ng-anduinos"
    version_result = subprocess.run(
        ("dpkg-query", "-W", "-f=${Version}", package),
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    version = version_result.stdout.strip()
    if version_result.returncode != 0 or not re.fullmatch(
        r"2\.0\.2-1\+resolute(?:-addon)?", version
    ):
        raise UiFailure(
            "DING keyboard fallback is not validated for installed version "
            f"{version!r}"
        )
    source_path = Path(
        "/usr/share/gnome-shell/extensions/"
        "ding@rastersoft.com/app/desktopMenu.js"
    )
    source = source_path.read_text(encoding="utf-8")
    menu_body = source.split("async _createDesktopBackgroundMenu()", 1)[-1].split(
        "return menuContainer", 1
    )[0]
    actions = re.findall(
        r"_newMenuElement\([^,]+,\s*[\"']([^\"']+)[\"']",
        menu_body,
    )
    expected_tail = [
        "open-in-terminal-desktop",
        "change-background",
        "show-settings",
        "display-settings",
    ]
    if actions[-4:] != expected_tail:
        raise UiFailure(
            "DING desktop menu order changed; semantic keyboard fallback must "
            f"be reviewed: {actions!r}"
        )
    dump_accessibility(evidence / "desktop-context-menu-atspi.txt")
    exposed = [
        [role(item), name(item)]
        for item in visible_nodes()
        if owning_application(item) == "gjs"
        and name(item).casefold()
        in {value.casefold() for value in aliases("desktop_open_terminal")}
    ]
    if exposed:
        raise UiFailure(
            "DING now exposes Open in Terminal through AT-SPI; replace the "
            f"versioned keyboard fallback with semantic pointer input: {exposed!r}"
        )
    # GTK focuses the first row when the popup opens.  Up wraps to the final
    # row; three more presses traverse the exact source-validated tail to the
    # desired action.  The observed Ptyxis child CWD below remains the product
    # oracle, so an input/focus drift fails closed.
    up_presses = len(expected_tail)
    event(
        "desktop-context-menu-plan",
        target="desktop_open_terminal",
        package=package,
        package_version=version,
        source=str(source_path),
        action_tail=expected_tail,
        focus_origin="first-menu-row",
        up_presses=up_presses,
        atspi_rows_exposed=False,
    )
    return up_presses


def _ptyxis_descendant_cwds() -> list[str]:
    process_rows = subprocess.run(
        ("ps", "-eo", "pid=,ppid=,comm="),
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    if process_rows.returncode != 0:
        raise UiFailure(f"Could not inspect Ptyxis processes: {process_rows.stdout}")
    parents: dict[int, int] = {}
    names: dict[int, str] = {}
    for raw_line in process_rows.stdout.splitlines():
        fields = raw_line.split(None, 2)
        if len(fields) != 3:
            continue
        try:
            pid, ppid = int(fields[0]), int(fields[1])
        except ValueError:
            continue
        parents[pid] = ppid
        names[pid] = fields[2]
    roots = {pid for pid, value in names.items() if "ptyxis" in value.casefold()}
    descendants = set(roots)
    changed = True
    while changed:
        changed = False
        for pid, ppid in parents.items():
            if ppid in descendants and pid not in descendants:
                descendants.add(pid)
                changed = True
    values = set()
    for pid in descendants - roots:
        try:
            values.add(str(Path(f"/proc/{pid}/cwd").resolve(strict=True)))
        except (FileNotFoundError, PermissionError, OSError):
            continue
    return sorted(values)


def exercise_desktop_terminal(evidence: Path) -> None:
    dismiss_initial_setup()
    _ensure_desktop_foreground("desktop-terminal-show-desktop")
    deadline = time.monotonic() + 60
    frames = []
    while time.monotonic() < deadline:
        frames = _desktop_frames()
        if len(frames) == 1:
            break
        time.sleep(0.25)
    if len(frames) != 1:
        raise UiFailure(f"Expected one DING desktop frame, observed {len(frames)}")
    request_node_click(
        frames[0],
        "desktop-background-context",
        button="right",
        semantic_target="desktop-background",
    )
    up_presses = _desktop_terminal_keyboard_plan(evidence)
    for number in range(1, up_presses + 1):
        event(
            "qmp-key",
            request=f"desktop-terminal-menu-up-{number}",
            key="up",
        )
    event("qmp-key", request="desktop-terminal-menu-activate", key="ret")
    deadline = time.monotonic() + 60
    windows: list[tuple[str, str, str]] = []
    while time.monotonic() < deadline:
        windows = _terminal_windows()
        if windows:
            break
        time.sleep(0.25)
    if not windows:
        raise UiFailure("DING Open in Terminal did not create a visible Ptyxis window")
    desktop_directory = str(_desktop_fixture_path().parent.resolve())
    deadline = time.monotonic() + 30
    observed_cwds: list[str] = []
    while time.monotonic() < deadline:
        observed_cwds = _ptyxis_descendant_cwds()
        if desktop_directory in observed_cwds:
            break
        time.sleep(0.25)
    if desktop_directory not in observed_cwds:
        raise UiFailure(
            "Ptyxis opened without a shell rooted in the desktop directory; "
            f"observed_cwds={observed_cwds!r}"
        )
    dump_accessibility(evidence / "desktop-terminal-opened.txt")
    event(
        "desktop-terminal",
        phase="opened",
        visible=True,
        application=windows[0][0],
        windows=windows,
        activation="desktop-context-menu-versioned-keyboard",
        directory=desktop_directory,
        observed_cwds=observed_cwds,
    )
    event("qmp-key", request="desktop-terminal-close", key="alt-f4")
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline and _terminal_windows():
        time.sleep(0.25)
    if _terminal_windows():
        raise UiFailure("Ptyxis remained visible after Alt+F4")
    event("desktop-terminal", phase="closed", visible=False)


def exercise_desktop_shortcut(evidence: Path) -> None:
    dismiss_initial_setup()
    destination = _desktop_fixture_path()
    destination.unlink(missing_ok=True)
    _semantic, _target, search_entry = _open_arcmenu_search(
        PANEL_FIXTURE_NAME,
        "desktop-shortcut-search",
    )
    request_search_result_context(
        search_entry,
        "desktop-shortcut",
        PANEL_FIXTURE_NAME,
    )
    item = _wait_shell_named("desktop_shortcut_create", True)[0]
    localized = name(item)
    if localized != "创建桌面快捷方式":
        raise UiFailure(
            "Chinese ArcMenu did not expose '创建桌面快捷方式': "
            f"{localized!r}"
        )
    activated = activate_shell_context_action_pointer(
        "desktop_shortcut_create",
        "desktop-shortcut-action",
    )
    if activated != localized:
        raise UiFailure("Desktop shortcut action identity changed before activation")
    _close_arcmenu(
        "desktop-shortcut-close",
        search_result=PANEL_FIXTURE_NAME,
    )
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline and not destination.is_file():
        time.sleep(0.1)
    if not destination.is_file() or not os.access(destination, os.X_OK):
        raise UiFailure("ArcMenu did not create an executable desktop shortcut")
    metadata = subprocess.run(
        ("gio", "info", "-a", "metadata::trusted", str(destination)),
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    if metadata.returncode != 0 or "metadata::trusted: true" not in metadata.stdout:
        raise UiFailure(
            "Created desktop shortcut is not trusted: " + metadata.stdout
        )
    icon = _wait_desktop_fixture_node()
    dump_accessibility(evidence / "desktop-shortcut-visible.txt")
    event(
        "desktop-shortcut-visible",
        accessible_name=name(icon),
        role=role(icon),
        application=owning_application(icon),
    )
    _ensure_desktop_foreground("desktop-shortcut-show-desktop")
    frames = _desktop_frames()
    if len(frames) != 1:
        raise UiFailure(f"Expected one DING desktop frame, observed {len(frames)}")
    request_node_click(
        frames[0],
        "desktop-shortcut-focus",
        semantic_target="desktop-background",
    )
    # DING 93 exposes the icon's accessible identity correctly, but reports
    # every desktop label at screen coordinate (0, 0).  Do not turn that GTK
    # accessibility defect into a bogus click on the Home icon.  Exercise
    # DING's own keyboard find workflow: typing opens Find Files on Desktop,
    # the first Return accepts the selected match, and the second opens it.
    # The real fixture window below is still the authoritative launch oracle.
    event(
        "qmp-text",
        request="desktop-shortcut-ding-search-text",
    )
    event(
        "qmp-key",
        request="desktop-shortcut-ding-search-accept",
        key="ret",
    )
    event(
        "qmp-key",
        request="desktop-shortcut-launch",
        key="ret",
    )
    find(PANEL_WINDOW_TITLE, timeout=60)
    event(
        "desktop-shortcut",
        application=PANEL_FIXTURE_NAME,
        localized_label=localized,
        path=str(destination),
        executable=True,
        trusted=True,
        visible=True,
        launched_windows=[PANEL_WINDOW_TITLE],
        activation="ding-keyboard-find",
    )


def exercise_spotify_store(evidence: Path) -> None:
    dismiss_initial_setup()
    semantic, target, _search_entry = _open_arcmenu_search(
        "Spotify",
        "spotify-search",
    )
    result_name = name(semantic)
    result_role = role(target)
    event("qmp-key", request="spotify-result-activate", key="ret")
    software_application = wait_application(
        ("gnome-software", "Software", "软件"), timeout=120
    )
    event(
        "spotify-result-activated",
        accessible_name=result_name,
        role=result_role,
        method="qmp-keyboard",
    )
    deadline = time.monotonic() + 120
    spotify_nodes = []
    while time.monotonic() < deadline:
        spotify_nodes = [
            item
            for item in visible_nodes()
            if "spotify" in name(item).casefold()
            and any(
                token in owning_application(item).casefold()
                for token in ("gnome-software", "software", "软件")
            )
        ]
        if spotify_nodes:
            break
        time.sleep(0.5)
    if not spotify_nodes:
        dump_accessibility(evidence / "spotify-store-missing.txt")
        raise UiFailure("GNOME Software did not open a Spotify details page")
    dump_accessibility(evidence / "spotify-store-details.txt")
    event(
        "spotify-store",
        application=software_application,
        detail_names=sorted({name(item) for item in spotify_nodes if name(item)}),
        visible=True,
    )
__all__ = tuple(name for name in globals() if not name.startswith("__"))
