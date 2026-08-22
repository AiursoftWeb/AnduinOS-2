"""WeChat process, X11 window, and AppIndicator behavior."""

from .core import *  # noqa: F403
from .shell import _open_arcmenu_search


def _wechat_instances() -> list[dict[str, object]]:
    result = subprocess.run(
        (
            "flatpak",
            "ps",
            "--columns=instance,pid,child-pid,application,arch,branch,active,background",
        ),
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
    )
    if result.returncode != 0:
        raise UiFailure("Could not enumerate the running WeChat Flatpak: " + result.stdout)
    instances = []
    for raw_line in result.stdout.splitlines():
        fields = raw_line.split("\t")
        if len(fields) != 8 or fields[3] != "com.tencent.WeChat":
            continue
        try:
            pid = int(fields[1])
            child_pid = int(fields[2])
        except ValueError as error:
            raise UiFailure(f"WeChat returned malformed Flatpak PIDs: {raw_line!r}") from error
        instances.append(
            {
                "instance": fields[0],
                "pid": pid,
                "child_pid": child_pid,
                "application": fields[3],
                "arch": fields[4],
                "branch": fields[5],
                "active": fields[6],
                "background": fields[7],
            }
        )
    return instances


def _wechat_process_identity(namespace_pid: int) -> dict[str, object]:
    """Record a stable host PID identity for WeChat's proprietary X11 client.

    WeChat daemonizes inside its Flatpak sandbox.  Depending on Flatpak and the
    application build, ``flatpak ps`` can stop advertising that sandbox even
    while its mapped X11 client and tray process remain alive.  EWMH gives us
    the actual client PID; the kernel start time then lets the tray test prove
    that the same process survived rather than merely observing PID reuse.
    """

    if namespace_pid <= 1:
        # PID 2 is normal for a daemonized Flatpak client, so only PID 0/1 are
        # intrinsically impossible application identities here.
        raise UiFailure(
            f"WeChat returned an invalid X11 namespace PID: {namespace_pid!r}"
        )
    current_uid = os.getuid()
    matches = []
    for proc in Path("/proc").iterdir():
        if not proc.name.isdigit():
            continue
        try:
            status = (proc / "status").read_text(encoding="utf-8")
            uid_match = re.search(r"^Uid:\s+(\d+)", status, flags=re.MULTILINE)
            nspid_match = re.search(r"^NSpid:\s+([0-9\t ]+)$", status, flags=re.MULTILINE)
            if uid_match is None or nspid_match is None:
                continue
            namespace_ids = [int(item) for item in nspid_match.group(1).split()]
            if int(uid_match.group(1)) != current_uid or namespace_ids[-1] != namespace_pid:
                continue
            stat = (proc / "stat").read_text(encoding="utf-8")
            command = (proc / "cmdline").read_bytes().replace(b"\0", b" ").decode(
                "utf-8", errors="replace"
            ).strip()
            comm = (proc / "comm").read_text(encoding="utf-8").strip()
            try:
                executable = os.readlink(proc / "exe")
            except OSError:
                executable = ""
        except (FileNotFoundError, ProcessLookupError, PermissionError, OSError):
            continue
        identity = f"{command} {comm} {executable}".casefold()
        if "wechat" not in identity and "微信" not in identity:
            continue
        closing = stat.rfind(")")
        fields = stat[closing + 1 :].split() if closing >= 0 else []
        if len(fields) <= 19:
            continue
        matches.append(
            {
                "pid": int(proc.name),
                "namespace_pid": namespace_pid,
                "uid": current_uid,
                "start_time_ticks": int(fields[19]),
                "command": command or comm,
                "executable": executable or comm,
            }
        )
    if len(matches) != 1:
        raise UiFailure(
            "Could not map WeChat's X11 namespace PID to exactly one host "
            f"process: namespace_pid={namespace_pid}, matches={matches!r}"
        )
    return matches[0]


def _x11_wechat_windows() -> list[dict[str, object]]:
    """Read proprietary WeChat windows from EWMH without requiring AT-SPI."""

    environment = os.environ.copy()
    environment["LC_ALL"] = "C"
    authority = environment.get("XAUTHORITY", "")
    if not authority or not Path(authority).is_file():
        runtime = Path(environment.get("XDG_RUNTIME_DIR", ""))
        candidates = sorted(
            runtime.glob(".mutter-Xwaylandauth.*"),
            key=lambda item: item.stat().st_mtime_ns,
            reverse=True,
        ) if runtime.is_dir() else []
        if not candidates:
            raise UiFailure(
                "Could not discover the active Mutter Xwayland authorization cookie"
            )
        authority = str(candidates[0])
    environment["XAUTHORITY"] = authority
    root = subprocess.run(
        ("xprop", "-root", "_NET_CLIENT_LIST"),
        env=environment,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
    )
    if root.returncode != 0:
        raise UiFailure("Could not query X11 client windows: " + root.stdout)
    identifiers = re.findall(r"0x[0-9a-fA-F]+", root.stdout)
    windows = []
    for identifier in identifiers:
        properties = subprocess.run(
            (
                "xprop",
                "-id",
                identifier,
                "_NET_WM_NAME",
                "WM_NAME",
                "WM_CLASS",
                "_NET_WM_PID",
                "_NET_WM_STATE",
            ),
            env=environment,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            check=False,
        )
        if properties.returncode != 0:
            continue
        title_matches = re.findall(
            r"^(?:_NET_WM_NAME|WM_NAME).*?=\s*\"(.*)\"$",
            properties.stdout,
            flags=re.MULTILINE,
        )
        title = next((item for item in title_matches if item), "")
        class_match = re.search(
            r'^WM_CLASS.*?=\s*"([^"]*)",\s*"([^"]*)"$',
            properties.stdout,
            flags=re.MULTILINE,
        )
        classes = list(class_match.groups()) if class_match else []
        identity = " ".join((title, *classes)).casefold()
        if "wechat" not in identity and "微信" not in identity:
            continue
        pid_match = re.search(
            r"^_NET_WM_PID.*?=\s*(\d+)$",
            properties.stdout,
            flags=re.MULTILINE,
        )
        state_match = re.search(
            r"^_NET_WM_STATE.*?=\s*(.*)$",
            properties.stdout,
            flags=re.MULTILINE,
        )
        geometry = subprocess.run(
            ("xwininfo", "-id", identifier),
            env=environment,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            check=False,
        )
        if geometry.returncode != 0:
            continue
        values = {}
        for key, pattern in {
            "x": r"Absolute upper-left X:\s*(-?\d+)",
            "y": r"Absolute upper-left Y:\s*(-?\d+)",
            "width": r"Width:\s*(\d+)",
            "height": r"Height:\s*(\d+)",
        }.items():
            match = re.search(pattern, geometry.stdout)
            if match is None:
                break
            values[key] = int(match.group(1))
        if len(values) != 4:
            continue
        map_match = re.search(r"Map State:\s*(\S+)", geometry.stdout)
        map_state = map_match.group(1) if map_match else ""
        state = state_match.group(1).strip() if state_match else ""
        windows.append(
            {
                "id": identifier.lower(),
                "title": title,
                "classes": classes,
                "pid": int(pid_match.group(1)) if pid_match else 0,
                "state": state,
                "map_state": map_state,
                "visible": (
                    map_state == "IsViewable"
                    and "_NET_WM_STATE_HIDDEN" not in state
                ),
                **values,
            }
        )
    return windows


def _wait_wechat_x11_window(timeout: float = 180) -> tuple[dict[str, object], list[dict[str, object]]]:
    deadline = time.monotonic() + timeout
    windows = []
    while time.monotonic() < deadline:
        windows = _x11_wechat_windows()
        visible = [item for item in windows if item["visible"]]
        if visible:
            main = max(visible, key=lambda item: int(item["width"]) * int(item["height"]))
            if int(main["width"]) >= 200 and int(main["height"]) >= 250:
                return main, windows
        time.sleep(0.5)
    raise UiFailure(f"WeChat exposed no mapped X11 main window: {windows!r}")


def exercise_wechat_install(evidence: Path) -> None:
    """Launch the installed native WeChat from ArcMenu and observe its window."""

    dismiss_initial_setup()
    semantic, target, _search_entry = _open_arcmenu_search(
        "WeChat",
        "wechat-search",
    )
    result_name = name(semantic)
    result_role = role(target)
    event("qmp-key", request="wechat-result-activate", key="ret")
    main_window, windows = _wait_wechat_x11_window(timeout=180)
    process = _wechat_process_identity(int(main_window["pid"]))
    flatpak_instances = _wechat_instances()
    dump_accessibility(evidence / "wechat-shell-and-desktop.txt")
    event(
        "wechat-installed-launched",
        search_result=result_name,
        result_role=result_role,
        activation_method="qmp-keyboard",
        application="com.tencent.WeChat",
        observation="ewmh-x11",
        main_window=main_window,
        windows=windows,
        process=process,
        flatpak_instances=flatpak_instances,
        visible=True,
    )


def _lower_right_indicator(
    accepted_name,
) -> tuple[object, dict[str, object]] | None:
    candidates: dict[tuple[int, int, int, int], tuple[object, dict[str, object]]] = {}
    shell_bounds = []
    for item in visible_nodes():
        if owning_application(item) != "gnome-shell":
            continue
        try:
            bounds = item.get_extents(Atspi.CoordType.SCREEN)
        except Exception:
            continue
        if bounds.width >= 2 and bounds.height >= 2 and bounds.x >= 0 and bounds.y >= 0:
            shell_bounds.append(bounds)
        if not accepted_name(name(item)):
            continue
        try:
            # The AppIndicator extension exposes the rendered tray icon itself
            # as the semantic ``menu`` node.  Some GNOME Shell versions do not
            # attach an AT-SPI Action interface to that node, so ``actionable``
            # would walk upward to the full-screen Wayland surface and replace
            # the icon's real geometry with the surface geometry.  Host input
            # does not require an AT-SPI action: click the exact named node and
            # preserve its component rectangle as the visual oracle.
            if not item.is_component():
                continue
            target = item
            target_bounds = item.get_extents(Atspi.CoordType.SCREEN)
        except Exception:
            continue
        values = (
            target_bounds.x,
            target_bounds.y,
            target_bounds.width,
            target_bounds.height,
        )
        if min(values) < 0 or target_bounds.width < 2 or target_bounds.height < 2:
            continue
        candidates[values] = (
            target,
            {
                "accessible_name": name(item),
                "target_name": name(target),
                "role": role(target),
                "application": owning_application(target),
                "bounds": list(values),
            },
        )
    if not candidates or not shell_bounds:
        return None
    screen_right = max(item.x + item.width for item in shell_bounds)
    screen_bottom = max(item.y + item.height for item in shell_bounds)
    lower_right = []
    for target, details in candidates.values():
        x, y, width, height = details["bounds"]
        center_x = x + width / 2
        center_y = y + height / 2
        if center_x >= screen_right * 0.65 and center_y >= screen_bottom * 0.75:
            details["screen"] = [screen_right, screen_bottom]
            details["lower_right"] = True
            lower_right.append((target, details))
    if len(lower_right) != 1:
        return None
    return lower_right[0]


def _wechat_indicator() -> tuple[object, dict[str, object]] | None:
    return _lower_right_indicator(
        lambda value: any(
            token in value.casefold() for token in ("wechat", "微信")
        )
    )


INDICATOR_FIXTURE_WINDOW = "AnduinOS Indicator Fixture Window"
INDICATOR_FIXTURE_TITLE = "AnduinOS Acceptance Indicator"


def _indicator_fixture_window():
    matches_found = [
        item
        for item in visible_nodes()
        if name(item) == INDICATOR_FIXTURE_WINDOW and role(item) == "frame"
    ]
    return matches_found[0] if len(matches_found) == 1 else None


def _wait_indicator_fixture_window(timeout: float = 60):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        window = _indicator_fixture_window()
        if window is not None:
            return window
        time.sleep(0.25)
    raise UiFailure("The AppIndicator fixture window did not become visible")


def _indicator_fixture_process() -> dict[str, object]:
    matches_found = []
    for proc in Path("/proc").iterdir():
        if not proc.name.isdigit():
            continue
        try:
            status = (proc / "status").read_text(encoding="utf-8")
            uid_match = re.search(r"^Uid:\s+(\d+)", status, flags=re.MULTILINE)
            if uid_match is None or int(uid_match.group(1)) != os.getuid():
                continue
            command = (proc / "cmdline").read_bytes().replace(b"\0", b" ").decode(
                "utf-8", errors="replace"
            ).strip()
            if not command.endswith("indicator_fixture.py"):
                continue
            stat = (proc / "stat").read_text(encoding="utf-8")
        except (FileNotFoundError, ProcessLookupError, PermissionError, OSError):
            continue
        closing = stat.rfind(")")
        fields = stat[closing + 1 :].split() if closing >= 0 else []
        if len(fields) <= 19:
            continue
        matches_found.append(
            {
                "pid": int(proc.name),
                "uid": os.getuid(),
                "start_time_ticks": int(fields[19]),
                "command": command,
            }
        )
    if len(matches_found) != 1:
        raise UiFailure(
            "Expected exactly one AppIndicator fixture process, found "
            f"{matches_found!r}"
        )
    return matches_found[0]


def exercise_appindicator_roundtrip(evidence: Path) -> None:
    """Hide one real GTK window to SNI and restore it through host input."""

    dismiss_initial_setup()
    window = _wait_indicator_fixture_window()
    before = _indicator_fixture_process()
    event(
        "appindicator-baseline",
        window={
            "accessible_name": name(window),
            "role": role(window),
            "application": owning_application(window),
        },
        process=before,
        visible=True,
    )
    event("qmp-key", request="appindicator-close-window", key="alt-f4")
    deadline = time.monotonic() + 60
    indicator = None
    hidden = None
    while time.monotonic() < deadline:
        try:
            hidden = _indicator_fixture_process()
        except UiFailure:
            hidden = None
        indicator = _lower_right_indicator(
            lambda value: value == INDICATOR_FIXTURE_TITLE
        )
        if (
            _indicator_fixture_window() is None
            and hidden is not None
            and hidden["pid"] == before["pid"]
            and hidden["start_time_ticks"] == before["start_time_ticks"]
            and indicator is not None
        ):
            break
        time.sleep(0.25)
    else:
        dump_accessibility(evidence / "appindicator-hide-failure.txt")
        raise UiFailure(
            "The GTK fixture did not hide to one lower-right AppIndicator while "
            f"preserving its process: before={before!r}, hidden={hidden!r}, "
            f"indicator={indicator!r}"
        )
    assert indicator is not None and hidden is not None
    target, details = indicator
    event(
        "appindicator-hidden",
        indicator=details,
        process=hidden,
        window_visible=False,
    )
    request_node_double_click(
        target,
        "appindicator-restore-window",
        semantic_target=INDICATOR_FIXTURE_TITLE,
    )
    restored_window = _wait_indicator_fixture_window()
    restored = _indicator_fixture_process()
    if (
        restored["pid"] != before["pid"]
        or restored["start_time_ticks"] != before["start_time_ticks"]
    ):
        raise UiFailure(
            "AppIndicator activation replaced the fixture process: "
            f"before={before!r}, restored={restored!r}"
        )
    dump_accessibility(evidence / "appindicator-restored.txt")
    event(
        "appindicator-restored",
        window={
            "accessible_name": name(restored_window),
            "role": role(restored_window),
            "application": owning_application(restored_window),
        },
        process=restored,
        same_process=True,
        visible=True,
    )


def exercise_wechat_tray(evidence: Path) -> None:
    """Close WeChat to AppIndicator, then restore the same X11 process."""

    before_window, before_windows = _wait_wechat_x11_window(timeout=30)
    before = _wechat_process_identity(int(before_window["pid"]))
    event(
        "wechat-tray-baseline",
        application="com.tencent.WeChat",
        main_window=before_window,
        windows=before_windows,
        process=before,
        flatpak_instances=_wechat_instances(),
    )
    event("qmp-key", request="wechat-close-to-tray", key="alt-f4")
    deadline = time.monotonic() + 90
    indicator = None
    after_close = None
    while time.monotonic() < deadline:
        try:
            after_close = _wechat_process_identity(int(before["pid"]))
        except UiFailure:
            after_close = None
        frames_gone = not any(item["visible"] for item in _x11_wechat_windows())
        indicator = _wechat_indicator()
        if (
            after_close is not None
            and after_close["pid"] == before["pid"]
            and after_close["start_time_ticks"] == before["start_time_ticks"]
            and frames_gone
            and indicator is not None
        ):
            break
        time.sleep(0.5)
    else:
        dump_accessibility(evidence / "wechat-indicator-missing.txt")
        raise UiFailure(
            "WeChat did not minimize to one lower-right AppIndicator while "
            f"preserving its X11 process: before={before!r}, "
            f"after={after_close!r}, indicator={indicator!r}"
        )
    assert indicator is not None and after_close is not None
    target, indicator_details = indicator
    dump_accessibility(evidence / "wechat-indicator-visible.txt")
    event(
        "wechat-indicator",
        process=after_close,
        flatpak_instances=_wechat_instances(),
        indicator=indicator_details,
        visible=True,
    )
    request_node_double_click(
        target,
        "wechat-indicator-restore",
        semantic_target="WeChat AppIndicator",
    )
    restored_window, restored_windows = _wait_wechat_x11_window(timeout=90)
    restored = _wechat_process_identity(int(restored_window["pid"]))
    if (
        restored["pid"] != before["pid"]
        or restored["start_time_ticks"] != before["start_time_ticks"]
    ):
        raise UiFailure(
            "WeChat AppIndicator launched a different process instead of restoring "
            f"the original: before={before!r}, restored={restored!r}"
        )
    dump_accessibility(evidence / "wechat-window-restored.txt")
    event(
        "wechat-tray-restored",
        application="com.tencent.WeChat",
        main_window=restored_window,
        windows=restored_windows,
        process=restored,
        flatpak_instances=_wechat_instances(),
        same_process=True,
        visible=True,
    )
__all__ = tuple(name for name in globals() if not name.startswith("__"))
