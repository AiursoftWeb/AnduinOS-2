"""Desktop session, shortcut, localization, and file evidence oracles."""

import hashlib
import re

from framework.errors import TestFailure
from .catalog import _CPU_Z_MEMBER
from .events import _all_event_objects, _one_event


def _validate_alt_tab_events(output: str) -> None:
    events = _all_event_objects(output)
    before, before_event = _one_event(
        events,
        context="Alt+Tab",
        event="shortcut-focus",
        shortcut="alt-tab",
        phase="before",
    )
    forward, _ = _one_event(
        events,
        context="Alt+Tab",
        event="qmp-key",
        request="shortcut-alt-tab-forward",
        key="alt-tab",
    )
    after, after_event = _one_event(
        events,
        context="Alt+Tab",
        event="shortcut-focus",
        shortcut="alt-tab",
        phase="after",
    )
    restore_key, _ = _one_event(
        events,
        context="Alt+Tab",
        event="qmp-key",
        request="shortcut-alt-tab-restore",
        key="alt-tab",
    )
    restored, restored_event = _one_event(
        events,
        context="Alt+Tab",
        event="shortcut-focus",
        shortcut="alt-tab",
        phase="restored",
    )
    fixtures = {
        "AnduinOS Shortcut Window Alpha",
        "AnduinOS Shortcut Window Beta",
    }
    first = before_event.get("window")
    second = after_event.get("window")
    final = restored_event.get("window")
    if {first, second} != fixtures or first == second or final != first:
        raise TestFailure(
            "Alt+Tab did not switch between both fixed fixture windows and restore focus"
        )
    if not before < forward < after < restore_key < restored:
        raise TestFailure("Alt+Tab focus transitions are out of order")


def _validate_super_tab_events(output: str) -> None:
    events = _all_event_objects(output)
    before, _ = _one_event(
        events, context="Super+Tab", event="overview", phase="before", visible=False
    )
    show_key, _ = _one_event(
        events,
        context="Super+Tab",
        event="qmp-key",
        request="shortcut-super-tab-show",
        key="meta_l-tab",
    )
    shown, shown_event = _one_event(
        events, context="Super+Tab", event="overview", phase="shown", visible=True
    )
    nodes = shown_event.get("nodes")
    if not isinstance(nodes, list) or not nodes:
        raise TestFailure("Super+Tab did not expose the semantic Overview panel")
    hide_key, _ = _one_event(
        events,
        context="Super+Tab",
        event="qmp-key",
        request="shortcut-super-tab-hide",
        key="meta_l-tab",
    )
    restored, _ = _one_event(
        events,
        context="Super+Tab",
        event="overview",
        phase="restored",
        visible=False,
    )
    if not before < show_key < shown < hide_key < restored:
        raise TestFailure("Super+Tab Overview transitions are out of order")


def _validate_initial_overview_events(output: str) -> None:
    events = _all_event_objects(output)
    _, value = _one_event(
        events,
        context="Initial Overview",
        event="initial-overview",
        phase="post-login",
    )
    if value.get("visible") is not False or value.get("overview_nodes") != []:
        raise TestFailure("GNOME Overview was visible automatically after login")
    markers = value.get("shell_ready_markers")
    if not isinstance(markers, list) or not markers:
        raise TestFailure(
            "Initial Overview absence was observed before GNOME Shell became accessible"
        )
    stable = value.get("stable_observations")
    if not isinstance(stable, int) or isinstance(stable, bool) or stable < 8:
        raise TestFailure(
            "Initial Overview absence was not stable for eight observations"
        )


def _validate_super_i_events(output: str) -> None:
    events = _all_event_objects(output)
    key, _ = _one_event(
        events,
        context="Super+I",
        event="qmp-key",
        request="shortcut-super-i",
        key="meta_l-i",
    )
    opened, value = _one_event(
        events,
        context="Super+I",
        event="shortcut-window",
        shortcut="super-i",
        focused=True,
    )
    application = value.get("application")
    if not isinstance(application, str) or not any(
        token in application.casefold()
        for token in ("gnome-control-center", "settings", "设置")
    ):
        raise TestFailure("Super+I focused an unrelated application")
    if not key < opened:
        raise TestFailure("Super+I reported Settings before the physical shortcut")


def _validate_settings_about_events(output: str) -> dict[str, object]:
    events = _all_event_objects(output)
    _, value = _one_event(
        events,
        context="GNOME Settings About branding",
        event="settings-about-branding",
    )
    application = value.get("application")
    operating_system = value.get("operating_system")
    bounds = value.get("bounds")
    assets = value.get("assets")
    if not isinstance(application, str) or not any(
        token in application.casefold()
        for token in ("gnome-control-center", "settings", "设置")
    ):
        raise TestFailure("The About branding probe observed an unrelated application")
    if (
        not isinstance(operating_system, str)
        or "anduinos" not in operating_system.casefold()
        or "ubuntu" in operating_system.casefold()
    ):
        raise TestFailure("GNOME Settings did not visibly identify AnduinOS")
    if (
        value.get("page") != "about"
        or value.get("coordinate_space") != "window"
        or not isinstance(value.get("logo_name"), str)
        or value.get("logo_role") not in {"image", "icon"}
        or not isinstance(bounds, list)
        or len(bounds) != 4
        or any(
            isinstance(item, bool) or not isinstance(item, (int, float))
            for item in bounds
        )
        or bounds[0] < 0
        or bounds[1] < 0
        or bounds[2] < 100
        or bounds[3] < 20
    ):
        raise TestFailure("GNOME Settings returned no usable semantic About logo")
    expected_assets = {
        "/usr/share/pixmaps/ubuntu-logo-text.svg",
        "/usr/share/pixmaps/ubuntu-logo-text-dark.svg",
    }
    if not isinstance(assets, list) or len(assets) != 2:
        raise TestFailure("GNOME Settings returned no complete About asset pair")
    observed_assets: set[str] = set()
    for asset in assets:
        if not isinstance(asset, dict):
            raise TestFailure("GNOME Settings returned malformed About asset evidence")
        path = asset.get("path")
        digest = asset.get("sha256")
        rendered = asset.get("rendered_template")
        markers = asset.get("brand_markers")
        if (
            not isinstance(path, str)
            or not isinstance(digest, str)
            or re.fullmatch(r"[0-9a-f]{64}", digest) is None
            or not isinstance(rendered, str)
            or not rendered.startswith("/")
            or markers != ["ANDUINOS", "anduinos"]
        ):
            raise TestFailure(
                "GNOME Settings About asset has no verifiable AnduinOS identity"
            )
        observed_assets.add(path)
    if observed_assets != expected_assets:
        raise TestFailure("GNOME Settings used an unexpected About logo asset pair")
    return value


def _validate_localization_zh_cn_events(output: str) -> None:
    events = _all_event_objects(output)
    _, value = _one_event(
        events,
        context="Simplified Chinese desktop localization",
        event="localization-zh-cn",
    )
    expected = {
        "settings_labels": {"关于", "操作系统"},
        "desktop_labels": {"主目录", "回收站"},
        "arcmenu_labels": {"已固定", "所有应用程序"},
    }
    for field, required in expected.items():
        observed = value.get(field)
        if not isinstance(observed, list) or not required <= set(observed):
            raise TestFailure(
                f"Simplified Chinese localization is incomplete for {field}: "
                f"{observed!r}"
            )


def _validate_swapcontrol_events(output: str) -> dict[str, object]:
    events = _all_event_objects(output)
    _, value = _one_event(
        events,
        context="Swap Control dashboard",
        event="swapcontrol-dashboard",
    )
    application = value.get("application")
    markers = value.get("markers")
    labels = value.get("observed_labels")
    bounds = value.get("bounds")
    if (
        not isinstance(application, str)
        or "swapcontrol" not in application.casefold()
        or value.get("page") != "dashboard"
        or markers != ["dashboard", "memory-overview", "swap", "zram"]
        or not isinstance(labels, dict)
        or set(labels) != set(markers)
        or any(not isinstance(label, str) or not label for label in labels.values())
        or value.get("authentication")
        not in {"authenticated", "not-present"}
        or not isinstance(value.get("accessibility_focus"), bool)
        or value.get("coordinate_space") != "window"
        or not isinstance(bounds, list)
        or len(bounds) != 4
        or any(
            isinstance(item, bool) or not isinstance(item, (int, float))
            for item in bounds
        )
        or bounds[2] < 640
        or bounds[3] < 400
    ):
        raise TestFailure("Swap Control did not expose its real dashboard surface")
    _, authentication = _one_event(
        events,
        context="Swap Control authentication",
        event="swapcontrol-authentication",
        outcome=value["authentication"],
    )
    if value["authentication"] == "authenticated":
        _one_event(
            events,
            context="Swap Control authentication focus",
            event="secret-focus",
            request="swapcontrol-auth-password",
            target="password",
            method="polkit-initial-password-focus",
        )
        _one_event(
            events,
            context="Swap Control authentication secret",
            event="qmp-secret",
            request="swapcontrol-auth-password",
        )
        _one_event(
            events,
            context="Swap Control authentication submission",
            event="qmp-key",
            request="swapcontrol-auth-submit",
            key="ret",
        )
    return value


def _validate_thumbnail_events(
    output: str,
    filename: str,
    username: str,
) -> dict[str, object]:
    events = _all_event_objects(output)
    _, value = _one_event(
        events,
        context=f"Nautilus thumbnail for {filename}",
        event="file-thumbnail",
        filename=filename,
    )
    expected_uri = f"file:///home/{username}/Downloads/{filename}"
    cache_path = value.get("cache_path")
    visible = value.get("visible_nodes")
    if (
        value.get("uri") != expected_uri
        or not isinstance(cache_path, str)
        or re.fullmatch(
            rf"/home/{re.escape(username)}/\.cache/thumbnails/"
            r"(?:normal|large|x-large|xx-large)/[0-9a-f]{32}\.png",
            cache_path,
        )
        is None
        or isinstance(value.get("cache_size"), bool)
        or not isinstance(value.get("cache_size"), int)
        or value["cache_size"] <= 128
        or not isinstance(visible, list)
        or not visible
        or not any(
            isinstance(item, dict) and item.get("name") == filename
            for item in visible
        )
    ):
        raise TestFailure(f"Nautilus returned invalid thumbnail evidence for {filename}")
    return value


def _validate_cpu_z_events(output: str, username: str) -> dict[str, object]:
    events = _all_event_objects(output)
    thumbnail_index, _ = _one_event(
        events,
        context="public CPU-Z thumbnail",
        event="file-thumbnail",
        filename=_CPU_Z_MEMBER,
    )
    thumbnail = _validate_thumbnail_events(output, _CPU_Z_MEMBER, username)
    opened_index, opened = _one_event(
        events,
        context="public CPU-Z Nautilus activation",
        event="nautilus-open",
        filename=_CPU_Z_MEMBER,
    )
    launcher_index, launcher = _one_event(
        events,
        context="public CPU-Z EXE Runner",
        event="cpu-z-public-recommendation",
        filename=_CPU_Z_MEMBER,
        application="AnduinOS Windows EXE Runner",
        bottles_installed=False,
    )
    observed = opened.get("observed")
    allowed = {
        "Installing CPU-Z?",
        "正在安装 CPU-Z？",
    }
    processes = launcher.get("runner_processes")
    if observed not in allowed:
        raise TestFailure(
            "The real CPU-Z file opened an unrelated desktop surface: "
            f"{observed!r}"
        )
    if (
        not isinstance(processes, list)
        or not processes
        or not all(
            isinstance(value, str)
            and "anduinos-exe-runner" in value
            and _CPU_Z_MEMBER in value
            for value in processes
        )
    ):
        raise TestFailure("The CPU-Z launcher event has no real handler process")
    if launcher.get("heading") not in allowed:
        raise TestFailure("The CPU-Z native recommendation has the wrong heading")
    reasons = {
        "CPU-X is a native Linux application that perfectly mirrors CPU-Z in functionality and interface, without the need for Windows sandboxing.",
        "CPU-X 是一款原生 Linux 应用程序，在功能和界面方面完美复刻了 CPU-Z，且无需依赖 Windows 沙盒环境。",
    }
    if launcher.get("reason") not in reasons:
        raise TestFailure("The CPU-Z recommendation did not explain the native alternative")
    controls = launcher.get("controls")
    if not isinstance(controls, dict) or set(controls) != {
        "cancel",
        "force_run",
        "cpux_get",
    }:
        raise TestFailure("The CPU-Z recommendation omitted a required action")
    allowed_names = {
        "cancel": {"Cancel", "取消"},
        "force_run": {"Force Run Anyway", "仍要强制运行"},
        "cpux_get": {"Get CPU-X", "获取 CPU-X"},
    }
    for key, names in allowed_names.items():
        value = controls.get(key)
        if (
            not isinstance(value, dict)
            or value.get("name") not in names
            or value.get("role") not in {"button", "push button"}
            or value.get("enabled") is not True
            or value.get("showing") is not True
        ):
            raise TestFailure(f"The CPU-Z recommendation action {key!r} is unusable")
    if not thumbnail_index < opened_index < launcher_index:
        raise TestFailure(
            "CPU-Z evidence is out of order; preview must precede desktop dispatch"
        )
    return thumbnail


def _validate_image_open_events(output: str) -> dict[str, object]:
    events = _all_event_objects(output)
    _, value = _one_event(
        events,
        context="Loupe image fixture",
        event="image-opened",
        filename="AnduinOS-Image.png",
    )
    application = value.get("application")
    visible = value.get("visible_names")
    if (
        not isinstance(application, str)
        or not any(
            token in application.casefold()
            for token in ("loupe", "image viewer", "图像查看器")
        )
        or value.get("process_running") is not True
        or not isinstance(visible, list)
        or not visible
    ):
        raise TestFailure("Loupe did not return a real visible image window")
    return value


def _validate_video_open_events(output: str) -> dict[str, object]:
    events = _all_event_objects(output)
    _, value = _one_event(
        events,
        context="Celluloid video fixture",
        event="video-opened",
        filename="AnduinOS-Video.mp4",
    )
    application = value.get("application")
    destination = value.get("mpris_destination")
    position = value.get("position_microseconds")
    if (
        not isinstance(application, str)
        or "celluloid" not in application.casefold()
        or not isinstance(destination, str)
        or not destination.startswith("org.mpris.MediaPlayer2.")
        or "celluloid" not in destination.casefold()
        or isinstance(position, bool)
        or not isinstance(position, int)
        or position <= 100_000
        or value.get("metadata_identifies_fixture") is not True
        or value.get("playback_status") not in {"Playing", "Paused"}
    ):
        raise TestFailure("Celluloid did not play the exact video fixture")
    return value


def _validate_deb_software_events(output: str) -> dict[str, object]:
    events = _all_event_objects(output)
    _, value = _one_event(
        events,
        context="GNOME Software local DEB",
        event="deb-software",
        filename="anduinos-acceptance-fixture_1.0_all.deb",
    )
    application = value.get("application")
    details = value.get("detail_names")
    if (
        not isinstance(application, str)
        or not any(
            token in application.casefold() for token in ("software", "软件")
        )
        or not isinstance(details, list)
        or not details
        or value.get("package_installed") is not False
    ):
        raise TestFailure("GNOME Software did not expose the harmless DEB safely")
    return value


def _validate_chinese_editor_events(output: str) -> dict[str, object]:
    events = _all_event_objects(output)
    _, value = _one_event(
        events,
        context="GNOME Text Editor Chinese fixture",
        event="chinese-editor",
        filename="AnduinOS-Chinese.txt",
    )
    expected = "变角次亮采之门"
    application = value.get("application")
    if (
        not isinstance(application, str)
        or not any(
            token in application.casefold()
            for token in ("gnome-text-editor", "text editor", "文本编辑器")
        )
        or value.get("expected") != expected
        or value.get("observed") != expected
        or value.get("character_count") != len(expected)
        or value.get("utf8_sha256")
        != hashlib.sha256((expected + "\n").encode("utf-8")).hexdigest()
        or value.get("implicit_trailing_newline") is not True
        or not 1 <= value.get("save_attempts", 0) <= 3
        or value.get("process_running") is not True
        or value.get("saved") is not True
    ):
        raise TestFailure(
            "GNOME Text Editor did not preserve the exact normalized Chinese text"
        )
    save_events = [
        event
        for event in events
        if event.get("event") == "qmp-click"
        and event.get("request") == "chinese-editor-save-menu-row"
        and event.get("target") == "Save"
        and event.get("anchor") == "fixed-1280x800-framebuffer"
        and event.get("framebuffer") == [1280, 800]
        and event.get("button") == "left"
    ]
    if not 1 <= len(save_events) <= 3:
        raise TestFailure("GNOME Text Editor Save menu row was not clicked")
    if [event.get("attempt") for event in save_events] != list(
        range(1, len(save_events) + 1)
    ) or value.get("save_attempts") != len(save_events):
        raise TestFailure("GNOME Text Editor Save retries were not bounded and ordered")
    for index, _character in enumerate(expected):
        required = (
            ("qmp-key", f"chinese-editor-unicode-{index}-start", "ctrl-shift-u"),
            ("qmp-text", f"chinese-editor-unicode-{index}-codepoint", None),
            ("qmp-key", f"chinese-editor-unicode-{index}-commit", "ret"),
        )
        for event_name, request, key in required:
            matches = [
                event
                for event in events
                if event.get("event") == event_name
                and event.get("request") == request
                and (key is None or event.get("key") == key)
            ]
            if len(matches) != 1:
                raise TestFailure(
                    "GNOME Text Editor Unicode text was not delivered by host input"
                )
    return value


def _validate_super_u_events(output: str) -> None:
    events = _all_event_objects(output)
    before, before_event = _one_event(
        events,
        context="Super+U",
        event="network-stats",
        phase="before",
        visible=False,
    )
    show_key, _ = _one_event(
        events,
        context="Super+U",
        event="qmp-key",
        request="shortcut-super-u-show",
        key="meta_l-u",
    )
    shown, shown_event = _one_event(
        events,
        context="Super+U",
        event="network-stats",
        phase="shown",
        visible=True,
    )
    hide_key, _ = _one_event(
        events,
        context="Super+U",
        event="qmp-key",
        request="shortcut-super-u-hide",
        key="meta_l-u",
    )
    restored, restored_event = _one_event(
        events,
        context="Super+U",
        event="network-stats",
        phase="restored",
        visible=False,
    )
    inactive = {"INITIALIZED", "INACTIVE", "DISABLED"}
    active = {"ACTIVE", "ENABLED"}
    if before_event.get("state") not in inactive:
        raise TestFailure("Network Stats did not begin inactive")
    if shown_event.get("state") not in active:
        raise TestFailure("Super+U did not activate Network Stats")
    if not isinstance(shown_event.get("nodes"), list) or not shown_event["nodes"]:
        raise TestFailure("Super+U produced no visible semantic Network Stats node")
    if restored_event.get("state") not in inactive:
        raise TestFailure("A second Super+U did not restore Network Stats")
    if not before < show_key < shown < hide_key < restored:
        raise TestFailure("Super+U Network Stats transitions are out of order")


def _validate_screenshot_shortcut_events(output: str) -> dict[str, object]:
    events = _all_event_objects(output)
    open_key, _ = _one_event(
        events,
        context="Super+Shift+S",
        event="qmp-key",
        request="shortcut-screenshot-open",
        key="meta_l-shift-s",
    )
    interface, ui = _one_event(
        events,
        context="Super+Shift+S",
        event="screenshot-ui",
        visible=True,
    )
    modes = ui.get("modes")
    if (
        not isinstance(modes, list)
        or len(modes) != 3
        or any(not isinstance(mode, str) or not mode for mode in modes)
        or ui.get("completion") != "focused-default-action"
    ):
        raise TestFailure("The screenshot interface did not expose all three modes")
    capture_key, _ = _one_event(
        events,
        context="Super+Shift+S",
        event="qmp-key",
        request="shortcut-screenshot-capture",
        key="ret",
    )
    created, result = _one_event(
        events,
        context="Super+Shift+S",
        event="screenshot-created",
        png_signature=True,
    )
    path = result.get("path")
    size = result.get("size")
    if (
        not isinstance(path, str)
        or not path.startswith("/")
        or not path.casefold().endswith(".png")
        or isinstance(size, bool)
        or not isinstance(size, int)
        or size <= 1024
    ):
        raise TestFailure("The screenshot shortcut returned invalid PNG metadata")
    if not open_key < interface < capture_key < created:
        raise TestFailure("Super+Shift+S capture events are out of order")
    return result


__all__ = tuple(name for name in globals() if name.startswith("_"))
