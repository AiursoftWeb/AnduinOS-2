#!/usr/bin/python3
"""Drive the real GTK installer and GNOME Settings through AT-SPI.

This file is copied into a running guest by the host harness.  It deliberately
uses only PyGObject and the AT-SPI GIR shipped in the production desktop.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import time
import unicodedata
from pathlib import Path

import gi

gi.require_version("Atspi", "2.0")
from gi.repository import Atspi, Gio


class UiFailure(RuntimeError):
    pass


ALIASES = {
    "next": ("Next", "下一步", "Continue Installation", "继续安装"),
    "skip": ("Skip", "跳过"),
    "welcome": ("Welcome to AnduinOS", "欢迎使用 AnduinOS"),
    "secure_boot": (
        "AnduinOS supports Secure Boot",
        "AnduinOS 支持安全启动",
    ),
    "network": ("Connect to the Internet", "连接到互联网"),
    "keyboard": ("Keyboard Layout", "键盘布局"),
    "software": ("Updates and Drivers", "更新和驱动程序"),
    "disk": ("Select Installation Disk", "选择安装磁盘"),
    "strategy": ("Choose Installation Method", "选择安装方式"),
    "user": ("User Account", "用户账户"),
    "advanced": ("Advanced Options", "高级选项"),
    "timezone": ("Select Timezone", "选择时区"),
    "summary": ("Ready to Install", "准备安装"),
    "install": ("Install", "安装"),
    "confirm": ("Erase Disk and Install", "擦除磁盘并安装"),
    "complete": ("Installation Complete", "安装完成"),
    "failed": ("Installation failed", "安装失败"),
    "output_tab": ("Output", "输出"),
    "complete_tab": ("Complete", "完成"),
    "copy_log": ("Copy Log", "复制日志"),
    "save_log": ("Save Log", "保存日志"),
    "connect": ("Connect", "连接"),
    "connected": ("Connected", "已连接"),
    "use_wps": ("Use WPS", "使用 WPS"),
    "rime": ("AnduinOS Rime",),
    "updates": (
        "Download and install system updates during installation",
        "在安装期间下载并安装系统更新",
    ),
    "drivers": (
        "Install third-party drivers for this device",
        "为此设备安装第三方驱动程序",
    ),
    "multimedia": (
        "Install extended multimedia format support",
        "安装扩展多媒体格式支持",
    ),
    "btrfs": ("Btrfs — recommended", "Btrfs — 推荐"),
    "ext4": ("ext4 — classic", "ext4 — 经典"),
    "full_name": ("Full Name", "全名"),
    "username": ("Username", "用户名"),
    "password": ("Password", "密码"),
    "confirm_password": ("Confirm Password", "确认密码"),
    "hostname": ("Computer Name", "计算机名称"),
    "ssh": (
        "Allow SSH login with the account password",
        "允许使用账户密码登录 SSH",
    ),
    "sudo": (
        "Run sudo commands without a password",
        "执行 sudo 命令时无需密码",
    ),
    "automatic_login": (
        "Log in to the desktop automatically",
        "自动登录桌面",
    ),
    "secure_shell": ("Secure Shell", "安全外壳", "安全 Shell"),
    "polkit": ("Authentication Required", "需要认证"),
    "offline_input": (
        "No Internet connection. Input methods cannot be installed.",
        "当前未连接互联网，无法安装输入法。",
    ),
    "offline_base": (
        "Requires an Internet connection. The base installation remains available when offline.",
        "需要互联网连接。基础安装在离线时仍可用。",
    ),
    "driver_step": ("Install hardware drivers", "安装硬件驱动程序"),
    "wifi_migration": (
        "Preserve connected Wi-Fi network",
        "保留已连接的 Wi-Fi 网络",
    ),
    "snapshots_manager": (
        "Disk Snapshots Manager",
        "Btrfs Snapshots Manager",
        "磁盘快照管理器",
    ),
    "snapshot_prepare_restart": ("Prepare and Restart", "准备并重启"),
    "snapshot_armed": (
        "Restart Required — Rollback Armed",
        "必须重启 — 回滚已就绪",
    ),
    "snapshot_restart_now": ("Restart Now", "立即重启"),
    "finish_setup": (
        "Start your AnduinOS journey",
        "开始您的 AnduinOS 之旅",
    ),
    "appimage_fixture": (
        "AnduinOS AppImage Acceptance Fixture",
        "A real Type-2 AppImage launched successfully.",
    ),
    "cpuz_recommendation": (
        "Checking Hardware & Benchmarks?",
        "正在检查硬件与基准测试？",
    ),
    "cpuz_installing": ("Installing CPU-Z?", "正在安装 CPU-Z？"),
    "cpuz_native_reason": (
        "CPU-X is a native Linux application that perfectly mirrors CPU-Z in functionality and interface, without the need for Windows sandboxing.",
        "CPU-X 是一款原生 Linux 应用程序，在功能和界面方面完美复刻了 CPU-Z，且无需依赖 Windows 沙盒环境。",
    ),
    "cpux_get": ("Get CPU-X", "获取 CPU-X"),
    "force_run": ("Force Run Anyway", "仍要强制运行"),
    "mission_center": ("Get Mission Center", "获取 Mission Center"),
    "users_panel": ("Users", "用户"),
    "about_page": ("About", "关于"),
    "operating_system": ("Operating System", "操作系统"),
    "system_logo": ("System Logo", "系统徽标", "系统标志", "系统 Logo"),
    "unlock": ("Unlock…", "Unlock", "解锁…", "解锁"),
    "add_user": ("Add User", "添加用户"),
    "add": ("Add", "添加"),
    "cancel": ("Cancel", "取消"),
    "set_password_now": ("Set password now", "现在设置密码"),
    "set_password_page": ("Set Password", "设置密码"),
    "change_password": ("Change Password", "更改密码"),
    "current_password": ("Current Password", "当前密码"),
    "new_password": ("New Password", "新密码"),
    "change": ("Change", "更改"),
    "system_menu": ("System", "系统"),
    "dark_style": ("Dark Style", "暗色样式"),
    "overview_panel": ("Overview", "概览"),
    "screenshot_capture": (
        "Take Screenshot",
        "Capture",
        "截图",
        "截取屏幕截图",
        "拍摄截图",
    ),
    "arcmenu_search": ("Search…", "Search...", "搜索…", "搜索...", "ArcMenuSearchEntry"),
    "arcmenu_pinned": ("Pinned", "已固定"),
    "arcmenu_all_apps": ("All Apps", "All Applications", "所有应用程序"),
    "start_button": ("Show Applications", "显示应用", "ArcMenu"),
    "taskbar_unpin": ("Unpin", "从任务栏中移除"),
    "taskbar_pin": ("Pin to Dash", "添加到任务栏"),
    "desktop_shortcut_create": ("Create Desktop Shortcut", "创建桌面快捷方式"),
    "desktop_open_terminal": (
        "Open in Terminal",
        "在终端中打开",
        "打开终端",
    ),
}


def event(kind: str, **values: object) -> None:
    print(json.dumps({"event": kind, **values}, ensure_ascii=False), flush=True)


def children(node):
    try:
        count = min(node.get_child_count(), 500)
    except Exception:
        return
    for index in range(max(0, count)):
        try:
            child = node.get_child_at_index(index)
        except Exception:
            continue
        if child is not None:
            yield child


def walk(node, maximum: int = 10000):
    stack = [node]
    seen = 0
    while stack and seen < maximum:
        current = stack.pop()
        seen += 1
        yield current
        stack.extend(reversed(list(children(current))))


def name(node) -> str:
    try:
        return (node.get_name() or "").strip()
    except Exception:
        return ""


def role(node) -> str:
    try:
        return node.get_role_name() or ""
    except Exception:
        return ""


def has_state(node, state) -> bool:
    try:
        return bool(node.get_state_set().contains(state))
    except Exception:
        return False


def showing(node) -> bool:
    return has_state(node, Atspi.StateType.SHOWING) and not has_state(
        node, Atspi.StateType.DEFUNCT
    )


def enabled(node) -> bool:
    # SENSITIVE reflects the GTK property used by the installer when network
    # choices are disabled. ENABLED may remain set on an insensitive checkbox.
    return has_state(node, Atspi.StateType.SENSITIVE)


def checked(node) -> bool:
    return has_state(node, Atspi.StateType.CHECKED) or has_state(
        node, Atspi.StateType.PRESSED
    )


def aliases(key: str) -> tuple[str, ...]:
    return ALIASES.get(key, (key,))


def semantic_name(value: str) -> str:
    """Normalize GTK mnemonic decoration without weakening label identity."""

    return re.sub(r"\([A-Za-z]\)", "", value).rstrip(" .…").strip().casefold()


def matches(node, candidates: tuple[str, ...]) -> bool:
    value = name(node).casefold()
    return bool(value) and any(item.casefold() in value for item in candidates)


def desktop():
    return Atspi.get_desktop(0)


def visible_nodes():
    return tuple(item for item in walk(desktop()) if showing(item))


def find(
    key: str,
    *,
    timeout: float = 30,
    require_enabled: bool = False,
    editable: bool = False,
):
    return find_candidates(
        aliases(key),
        label=key,
        timeout=timeout,
        require_enabled=require_enabled,
        editable=editable,
    )


def find_candidates(
    candidates: tuple[str, ...],
    *,
    label: str,
    timeout: float = 30,
    require_enabled: bool = False,
    editable: bool = False,
):
    """Find one exact semantic label from a caller-supplied variant set."""

    if not candidates or any(not item for item in candidates):
        raise UiFailure(f"Invalid semantic candidates for {label!r}")
    deadline = time.monotonic() + timeout
    last_names: list[str] = []
    while time.monotonic() < deadline:
        nodes = visible_nodes()
        last_names = [name(item) for item in nodes if name(item)][-80:]
        exact = tuple(item.casefold() for item in candidates)
        for exact_only in (True, False):
            for item in nodes:
                node_name = name(item).casefold()
                if exact_only:
                    matched = node_name in exact
                else:
                    matched = bool(node_name) and any(
                        candidate in node_name for candidate in exact
                    )
                if not matched:
                    continue
                if require_enabled and not enabled(item):
                    continue
                if editable:
                    try:
                        if not item.is_editable_text():
                            continue
                    except Exception:
                        continue
                return item
        time.sleep(0.25)
    raise UiFailure(
        f"Timed out waiting for {label!r} ({candidates!r}); visible={last_names!r}"
    )


def find_optional(key: str, timeout: float = 1.0):
    try:
        return find(key, timeout=timeout)
    except UiFailure:
        return None


def actionable(node):
    current = node
    for _ in range(8):
        try:
            if current.is_action() and action_count(current) > 0:
                return current
            current = current.get_parent()
        except Exception:
            break
        if current is None:
            break
    for candidate in walk(node, maximum=100):
        try:
            if candidate.is_action() and action_count(candidate) > 0:
                return candidate
        except Exception:
            continue
    raise UiFailure(f"No action is available for {name(node)!r} ({role(node)})")


def action_count(node) -> int:
    return node.get_n_actions()


def action_name(node, index: int) -> str:
    return node.get_action_name(index)


def perform_action(node, index: int) -> bool:
    try:
        return bool(node.do_action(index))
    except Exception:
        # GTK can invalidate and recreate a checkbox's accessible action
        # object while a navigation transition settles.  The caller must
        # refetch the visible object and verify state instead of treating the
        # stale proxy as a product failure.
        return False


def click(key: str, timeout: float = 30) -> None:
    deadline = time.monotonic() + timeout
    while True:
        node = find(key, timeout=max(0.25, deadline - time.monotonic()))
        target = actionable(node)
        if perform_action(target, 0):
            break
        if time.monotonic() >= deadline:
            raise UiFailure(f"AT-SPI action remained unavailable: {key!r}")
        time.sleep(0.25)
    actions = []
    try:
        actions = [action_name(target, index) for index in range(action_count(target))]
    except Exception:
        pass
    # The first action has already been invoked above. Installer controls use
    # one click action; keep the action list only as evidence.
    event("click", target=key, accessible_name=name(node), actions=actions)
    time.sleep(0.35)


def click_exact_name(value: str, timeout: float = 60) -> None:
    """Focus one exact dynamic row and activate it with real QEMU input."""

    deadline = time.monotonic() + timeout
    input_count = 0
    while time.monotonic() < deadline:
        candidates = [
            item
            for item in visible_nodes()
            if name(item) == value
        ]
        candidates.sort(
            key=lambda item: {
                "list item": 0,
                "table row": 1,
                "label": 2,
            }.get(role(item), 3)
        )
        for node in candidates:
            if focus_within(node):
                event(
                    "qmp-key",
                    request="installer-wifi-select-network",
                    key="ret",
                    target=value,
                    accessible_name=name(node),
                    role=role(node),
                    focused=True,
                    focus_inputs=input_count,
                )
                event(
                    "activate-exact",
                    accessible_name=value,
                    role=role(node),
                    method="semantic-focus-qemu-enter",
                )
                time.sleep(0.35)
                return
        if input_count >= 80:
            break
        event(
            "qmp-key",
            request=f"installer-wifi-focus-{input_count}",
            key="tab",
            target=value,
        )
        input_count += 1
        time.sleep(0.3)
    raise UiFailure(f"No focusable exact-name control appeared: {value!r}")


def set_text(key: str, value: str, *, occurrence: int = 0) -> None:
    candidates = aliases(key)
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        matches_found = []
        for item in visible_nodes():
            if not matches(item, candidates):
                continue
            try:
                if item.is_editable_text():
                    matches_found.append(item)
            except Exception:
                continue
        if len(matches_found) > occurrence:
            target = matches_found[occurrence]
            if not target.set_text_contents(value):
                raise UiFailure(f"Could not set text in {key!r}")
            event("set-text", target=key, length=len(value))
            time.sleep(0.15)
            return
        # GTK4 entries wrapped by the installer's label-above-field helper
        # are sometimes exposed as unnamed editable nodes. Accessibility
        # preserves their order, so bind the exact visible label to the first
        # following editable node, stopping at the next named form label.
        for index, item in enumerate(nodes := visible_nodes()):
            if not matches(item, candidates):
                continue
            for following in nodes[index + 1 : index + 8]:
                try:
                    if following.is_editable_text():
                        if not following.set_text_contents(value):
                            raise UiFailure(f"Could not set text in {key!r}")
                        event("set-text", target=key, length=len(value))
                        time.sleep(0.15)
                        return
                except UiFailure:
                    raise
                except Exception:
                    continue
        time.sleep(0.25)
    raise UiFailure(f"Editable field not found: {key!r}")


def editable_control(key: str, *, occurrence: int = 0, timeout: float = 30):
    """Return the editable associated with a visible semantic label."""

    candidates = aliases(key)
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        nodes = visible_nodes()
        direct = []
        for item in nodes:
            if not matches(item, candidates):
                continue
            try:
                if item.is_editable_text():
                    direct.append(item)
            except Exception:
                continue
        if len(direct) > occurrence:
            return direct[occurrence]
        for index, item in enumerate(nodes):
            if not matches(item, candidates):
                continue
            for following in nodes[index + 1 : index + 8]:
                try:
                    if following.is_editable_text():
                        return following
                except Exception:
                    continue
        time.sleep(0.25)
    raise UiFailure(f"Editable field not found: {key!r}")


def _request_secret_delivery(
    key: str,
    request: str,
    *,
    verify_character_count: bool = True,
    expected_character_count: int | None = None,
) -> None:
    event("qmp-secret", request=request)
    if not verify_character_count:
        # The host consumes QMP requests from the serial transcript in order
        # and types the complete secret synchronously before handling the next
        # pointer request. GNOME's password dialog hides even the character
        # count; its current-password authentication, enabled Change button,
        # and final PAM/hash checks are the stronger product-owned oracles.
        event("secret-requested", request=request, target=key)
        return
    # Protected entries do not reveal their contents, but GTK still exposes
    # the character count. This is both a secrecy-preserving delivery oracle
    # and a synchronization barrier: do not focus the next field until the
    # host has finished typing this secret through QMP.
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        target = editable_control(key, timeout=1)
        try:
            count = target.get_character_count() if target.is_text() else -1
        except Exception:
            count = -1
        delivered = (
            count == expected_character_count
            if expected_character_count is not None
            else count > 0
        )
        if expected_character_count is not None and count > expected_character_count:
            raise UiFailure(f"Secret input exceeded expected length for {key!r}")
        if delivered:
            event(
                "secret-delivered",
                request=request,
                target=key,
                character_count=count,
            )
            return
        time.sleep(0.1)
    raise UiFailure(f"Secret input did not reach field {key!r}")


def request_secret(key: str, request: str) -> None:
    """Focus one real password field, then request opaque QMP input."""

    target = editable_control(key)
    if not target.set_text_contents(""):
        raise UiFailure(f"Could not clear secret field {key!r}")
    # GTK4/Wayland can return False from grab_focus() and omit FOCUSED from a
    # password accessible even though the entry is focusable. Its localized
    # label still exposes GTK's real mnemonic (for example 密码(P)); use that
    # semantic route and verify afterwards that this exact password text
    # accessible received content. No secret is ever present in this event.
    mnemonic = re.search(r"\(([A-Za-z])\)", name(target))
    if mnemonic is not None:
        chord = f"alt-{mnemonic.group(1).lower()}"
        event(
            "qmp-key",
            request=f"{request}-focus-mnemonic-{chord}",
            key=chord,
        )
        event(
            "secret-focus",
            request=request,
            target=key,
            method="localized-mnemonic",
            mnemonic=chord,
        )
        time.sleep(0.35)
    else:
        # Retain a focus-state fallback for password forms without mnemonics.
        # The GNOME change-password dialog has a source-defined focus path and
        # deliberately uses request_dialog_secret() instead.
        try:
            target.grab_focus()
        except Exception:
            pass
        deadline = time.monotonic() + 30
        for index in range(80):
            target = editable_control(key, timeout=1)
            if has_state(target, Atspi.StateType.FOCUSED):
                event(
                    "secret-focus",
                    request=request,
                    target=key,
                    method="focused-state",
                    tab_count=index,
                )
                break
            event(
                "qmp-key",
                request=f"{request}-focus-{index}-tab",
                key="tab",
            )
            time.sleep(0.25)
            if time.monotonic() >= deadline:
                raise UiFailure(f"Could not focus secret field {key!r}")
        else:
            raise UiFailure(f"Could not focus secret field {key!r}")
    _request_secret_delivery(key, request)


def request_wifi_secret(request: str, expected_character_count: int) -> None:
    """Use the dialog's proven password focus, with one WPS fallback."""

    if not 8 <= expected_character_count <= 63:
        raise UiFailure("Wi-Fi secret length is outside WPA2-PSK limits")
    target = editable_control("password")
    if not target.set_text_contents(""):
        raise UiFailure("Could not clear Wi-Fi password field")
    deadline = time.monotonic() + 3
    while time.monotonic() < deadline:
        focused_passwords = []
        for candidate in visible_nodes():
            if not matches(candidate, aliases("password")):
                continue
            try:
                editable = candidate.is_editable_text()
            except Exception:
                editable = False
            if editable and has_state(candidate, Atspi.StateType.FOCUSED):
                focused_passwords.append(candidate)
        if len(focused_passwords) == 1:
            event(
                "secret-focus",
                request=request,
                target="password",
                method="initial-password-focus",
            )
            break
        if len(focused_passwords) > 1:
            raise UiFailure("Wi-Fi dialog exposed multiple focused password fields")
        wps = control("use_wps")
        if focus_within(wps):
            event(
                "qmp-key",
                request=f"{request}-focus-reverse-tab",
                key="shift-tab",
                source="use_wps",
                target="password",
            )
            event(
                "secret-focus",
                request=request,
                target="password",
                method="proven-wps-focus-reverse-tab",
            )
            time.sleep(0.35)
            break
        time.sleep(0.1)
    else:
        focused = [
            {"role": role(item), "name": name(item)}
            for item in visible_nodes()
            if has_state(item, Atspi.StateType.FOCUSED)
        ]
        raise UiFailure(
            "Wi-Fi dialog exposed no safe password focus route: "
            f"{focused!r}"
        )
    _request_secret_delivery(
        "password",
        request,
        expected_character_count=expected_character_count,
    )


def discover_current_password_focus(max_attempts: int = 12) -> None:
    """Find the protected current-password entry by its authentication effect."""

    for attempt in range(max_attempts):
        target = editable_control("current_password")
        if not target.set_text_contents(""):
            raise UiFailure("Could not clear the current-password field")
        request = f"accounts-current-password-attempt-{attempt}"
        event(
            "secret-focus",
            request=request,
            target="current_password",
            method="gnome-dialog-tab-search",
            tab_count=attempt,
        )
        _request_secret_delivery(
            "current_password",
            request,
            verify_character_count=False,
        )
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline:
            if enabled(editable_control("new_password", timeout=1)):
                event("current-password-authenticated", tab_count=attempt)
                return
            time.sleep(0.1)
        event(
            "qmp-key",
            request=f"accounts-current-password-search-{attempt}-tab",
            key="tab",
        )
        time.sleep(0.25)
    raise UiFailure("GNOME did not accept the current account password")


def request_dialog_secret(key: str, request: str, *, tab_count: int) -> None:
    """Advance from a proven password-field focus and submit one secret."""

    target = editable_control(key)
    if not target.set_text_contents(""):
        raise UiFailure(f"Could not clear secret field {key!r}")
    for index in range(tab_count):
        event(
            "qmp-key",
            request=f"{request}-focus-{index}-tab",
            key="tab",
        )
    event(
        "secret-focus",
        request=request,
        target=key,
        method="gnome-dialog-focus-chain",
        tab_count=tab_count,
    )
    _request_secret_delivery(key, request, verify_character_count=False)


def wait_absent(key: str, timeout: float = 30) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if find_optional(key, timeout=0.25) is None:
            return
        time.sleep(0.25)
    raise UiFailure(f"{key!r} remained visible")


def control(key: str):
    candidates = aliases(key)
    controls = tuple(
        item
        for item in visible_nodes()
        if role(item)
        in {
            "check box",
            "radio button",
            "toggle button",
            "switch",
            "button",
        }
    )
    expected = {semantic_name(candidate) for candidate in candidates}
    # Exact semantic labels must win before the historical substring fallback.
    # In GNOME Users, ``Add`` and the underlying ``Add User`` are visible at
    # the same time and share Alt+A. Returning the first substring match would
    # silently operate the wrong control while claiming target="add".
    for exact_only in (True, False):
        for item in controls:
            observed = tuple(
                semantic_name(name(candidate))
                for candidate in walk(item, maximum=200)
                if name(candidate)
            )
            if exact_only:
                matched = any(value in expected for value in observed)
            else:
                matched = any(
                    candidate in value
                    for value in observed
                    for candidate in expected
                    if candidate
                )
            if matched:
                return item
    return actionable(find(key))


def control_mnemonic(node) -> tuple[str, str] | None:
    source = next(
        (
            name(item)
            for item in walk(node, maximum=100)
            if re.search(r"\(([A-Za-z])\)", name(item))
        ),
        "",
    )
    match = re.search(r"\(([A-Za-z])\)", source)
    if match is None:
        return None
    return source, f"alt-{match.group(1).lower()}"


def mnemonic_owner_count(chord: str) -> int:
    owners = 0
    for item in visible_nodes():
        if role(item) not in {
            "check box",
            "radio button",
            "toggle button",
            "switch",
            "button",
        }:
            continue
        mnemonic = control_mnemonic(item)
        if mnemonic is not None and mnemonic[1] == chord:
            owners += 1
    return owners


def perform_named_activation(node) -> str | None:
    for index in range(action_count(node)):
        observed = action_name(node, index)
        if observed.casefold() not in {"click", "activate", "press"}:
            continue
        if perform_action(node, index):
            return observed
    return None


def request_focused_activation(key: str, request: str, timeout: float = 30) -> None:
    """Activate a GTK4 button through its verified keyboard focus.

    GNOME Control Center's Wayland accessibility bridge exposes some button
    labels with clipboard actions and reports component coordinates relative
    to the widget rather than the screen.  Neither is a trustworthy click
    oracle.  Tab through the real focus chain, observe the exact semantic
    button receiving focus, and only then ask QMP to press Enter.
    """

    target = control(key)
    mnemonic = control_mnemonic(target)
    if mnemonic is not None:
        mnemonic_source, chord = mnemonic
        owner_count = mnemonic_owner_count(chord)
    else:
        mnemonic_source, chord, owner_count = "", "", 0
    if mnemonic is not None and owner_count == 1:
        event(
            "qmp-key",
            request=f"{request}-mnemonic-{chord}",
            key=chord,
        )
        time.sleep(0.5)
        event(
            "focused-activation",
            target=key,
            accessible_name=mnemonic_source,
            method="localized-mnemonic",
            mnemonic=chord,
        )
        return

    if mnemonic is not None and owner_count > 1:
        if not enabled(target):
            raise UiFailure(f"Button is disabled: {key}")
        activated = perform_named_activation(target)
        if activated is not None:
            time.sleep(0.5)
            event(
                "focused-activation",
                target=key,
                accessible_name=mnemonic_source,
                method="atspi-action",
                action=activated,
                mnemonic=chord,
                mnemonic_owner_count=owner_count,
            )
            return

    deadline = time.monotonic() + timeout
    for index in range(80):
        target = control(key)
        if not enabled(target):
            raise UiFailure(f"Button is disabled: {key}")
        focused = has_state(target, Atspi.StateType.FOCUSED) or any(
            has_state(item, Atspi.StateType.FOCUSED)
            for item in walk(target, maximum=100)
        )
        requested_key = "ret" if focused else "tab"
        event(
            "qmp-key",
            request=f"{request}-{index}-{requested_key}",
            key=requested_key,
        )
        if requested_key == "ret":
            time.sleep(0.5)
            event(
                "focused-activation",
                target=key,
                accessible_name=name(target),
                method="keyboard-focus",
                tab_count=index,
            )
            return
        time.sleep(0.25)
        if time.monotonic() >= deadline:
            break
    raise UiFailure(f"Button did not receive keyboard focus: {key!r}")


def owning_application(node) -> str:
    current = node
    last = ""
    for _ in range(30):
        current_name = name(current)
        if current_name:
            last = current_name
        try:
            parent = current.get_parent()
        except Exception:
            break
        if parent is None or role(parent) == "desktop frame":
            break
        current = parent
    return last


def shell_control(key: str, *, timeout: float = 30):
    """Find an exact semantic control owned by GNOME Shell."""

    deadline = time.monotonic() + timeout
    candidates = tuple(value.casefold() for value in aliases(key))
    last: list[tuple[str, str]] = []
    while time.monotonic() < deadline:
        last = []
        for item in visible_nodes():
            if owning_application(item) != "gnome-shell":
                continue
            item_name = name(item)
            if item_name:
                last.append((role(item), item_name))
            if item_name.casefold() not in candidates:
                continue
            if key == "dark_style":
                return control(key)
            return item
        time.sleep(0.25)
    raise UiFailure(
        f"GNOME Shell did not expose {key!r}; visible shell nodes={last[-80:]!r}"
    )


def request_shell_click(
    key: str,
    request: str,
    *,
    timeout: float = 30,
    button: str = "left",
) -> None:
    """Ask the host tablet to click a verified GNOME Shell screen rectangle."""

    target = shell_control(key, timeout=timeout)
    try:
        bounds = target.get_extents(Atspi.CoordType.SCREEN)
    except Exception as error:
        raise UiFailure(f"Could not read GNOME Shell bounds for {key!r}: {error}")
    values = (bounds.x, bounds.y, bounds.width, bounds.height)
    if min(values) < 0 or bounds.width < 2 or bounds.height < 2:
        raise UiFailure(f"GNOME Shell returned unusable bounds for {key!r}: {values!r}")

    right = 0
    bottom = 0
    for item in visible_nodes():
        if owning_application(item) != "gnome-shell":
            continue
        try:
            extents = item.get_extents(Atspi.CoordType.SCREEN)
        except Exception:
            continue
        if min(extents.x, extents.y, extents.width, extents.height) < 0:
            continue
        if extents.width > 100000 or extents.height > 100000:
            continue
        right = max(right, extents.x + extents.width)
        bottom = max(bottom, extents.y + extents.height)
    if right < 320 or bottom < 240:
        raise UiFailure(
            f"Could not derive the GNOME Shell screen size: {right}x{bottom}"
        )
    x_px = bounds.x + bounds.width / 2
    y_px = bounds.y + bounds.height / 2
    if not 0 <= x_px <= right or not 0 <= y_px <= bottom:
        raise UiFailure(f"GNOME Shell click is out of range: {x_px}, {y_px}")
    event(
        "qmp-click",
        request=request,
        target=key,
        accessible_name=name(target),
        # Preserve the AT-SPI screen pixel position.  GNOME Shell's root
        # accessible can include an invisible stage margin (observed as
        # 1282x848 for a 1280x800 framebuffer), so normalizing against that
        # root would click above the bottom panel.  The host owns the QEMU
        # tablet and normalizes these pixels against a fresh screendump.
        x_px=round(x_px, 3),
        y_px=round(y_px, 3),
        button=button,
        screen=[right, bottom],
        bounds=list(values),
    )


def request_node_click(
    target,
    request: str,
    *,
    button: str = "left",
    semantic_target: str = "",
) -> None:
    """Click one exact semantic node, including non-Shell desktop icons."""

    try:
        bounds = target.get_extents(Atspi.CoordType.SCREEN)
    except Exception as error:
        raise UiFailure(f"Could not read semantic node bounds: {error}")
    values = (bounds.x, bounds.y, bounds.width, bounds.height)
    if min(values) < 0 or bounds.width < 2 or bounds.height < 2:
        raise UiFailure(f"Semantic node returned unusable bounds: {values!r}")
    if button not in {"left", "right"}:
        raise UiFailure("Unsupported semantic pointer request")
    target_name = semantic_target or name(target)
    event(
        "qmp-click",
        request=request,
        target=target_name,
        accessible_name=name(target),
        role=role(target),
        application=owning_application(target),
        x_px=round(bounds.x + bounds.width / 2, 3),
        y_px=round(bounds.y + bounds.height / 2, 3),
        button=button,
        bounds=list(values),
    )


def request_node_double_click(
    target,
    request: str,
    *,
    semantic_target: str = "",
) -> None:
    """Request one host-timed two-press gesture on a semantic node."""

    try:
        bounds = target.get_extents(Atspi.CoordType.SCREEN)
    except Exception as error:
        raise UiFailure(f"Could not read semantic node bounds: {error}")
    values = (bounds.x, bounds.y, bounds.width, bounds.height)
    if min(values) < 0 or bounds.width < 2 or bounds.height < 2:
        raise UiFailure(f"Semantic node returned unusable bounds: {values!r}")
    double_click_time_ms = Gio.Settings.new(
        "org.gnome.desktop.peripherals.mouse"
    ).get_int("double-click")
    if not 100 <= double_click_time_ms <= 5000:
        raise UiFailure(
            "GNOME returned an unsafe double-click interval: "
            f"{double_click_time_ms} ms"
        )
    event(
        "spice-double-click",
        request=request,
        target=semantic_target or name(target),
        accessible_name=name(target),
        role=role(target),
        application=owning_application(target),
        x_px=round(bounds.x + bounds.width / 2, 3),
        y_px=round(bounds.y + bounds.height / 2, 3),
        button="left",
        clicks=2,
        positioning_clicks=1,
        double_click_time_ms=double_click_time_ms,
        bounds=list(values),
    )


def accessible_text(node) -> str:
    """Read one AT-SPI text node without treating its name as its contents."""

    try:
        if not node.is_text():
            return ""
        count = node.get_character_count()
        if count < 0:
            return ""
        return (node.get_text(0, count) or "").strip()
    except Exception:
        return ""


def interface_color_scheme() -> str:
    result = subprocess.run(
        ("gsettings", "get", "org.gnome.desktop.interface", "color-scheme"),
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    value = result.stdout.strip().strip("'")
    if result.returncode != 0 or value not in {"default", "prefer-light", "prefer-dark"}:
        raise UiFailure(f"Could not read the desktop color scheme: {result.stdout!r}")
    return value


def set_desktop_theme(expected: str, evidence: Path) -> None:
    """Use the real localized GNOME Shell selector to choose light or dark."""

    if expected not in {"light", "dark"}:
        raise UiFailure(f"Unsupported expected theme: {expected!r}")
    # GNOME Shell's binary Dark Style control writes ``prefer-dark`` when on
    # and ``default`` when off.  ``prefer-light`` is a valid portal value but
    # is not the state produced by this real Shell control.
    desired = "prefer-dark" if expected == "dark" else "default"
    current = interface_color_scheme()
    # Even if a previous test left the requested state selected, exercise the
    # real selector by visiting the opposite state and returning.  This keeps
    # the behavioral oracle independent of image defaults and test order.
    transitions = [desired]
    if current == desired:
        transitions = ["default" if desired == "prefer-dark" else "prefer-dark", desired]

    observed_label = ""
    for index, transition in enumerate(transitions):
        try:
            selector = shell_control("dark_style", timeout=0.5)
            event(
                "theme-menu",
                transition=transition,
                method="already-open",
            )
        except UiFailure:
            request_shell_click(
                "system_menu",
                f"theme-system-menu-{expected}-{index}",
            )
            selector = shell_control("dark_style", timeout=15)
            event(
                "theme-menu",
                transition=transition,
                method="opened",
            )
        observed_label = next(
            (
                name(item)
                for item in walk(selector, maximum=100)
                if name(item).casefold()
                in {value.casefold() for value in aliases("dark_style")}
            ),
            name(selector),
        )
        language = os.environ.get("LANG", "")
        if language.startswith("zh_") and "暗色样式" not in observed_label:
            raise UiFailure(
                "The GNOME theme selector was not localized for the Chinese session: "
                f"{observed_label!r}"
            )
        target_dark = transition == "prefer-dark"
        if checked(selector) == target_dark:
            raise UiFailure(
                "Opening the real selector produced no state transition to exercise"
            )
        request_shell_click(
            "dark_style",
            f"theme-dark-style-{expected}-{index}",
        )
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            if interface_color_scheme() == transition:
                break
            time.sleep(0.25)
        else:
            raise UiFailure(
                f"GNOME Shell did not apply color scheme {transition!r}"
            )
        time.sleep(1)

    dump_accessibility(evidence / f"theme-{expected}-desktop.txt")
    event(
        "theme-selected",
        expected=expected,
        color_scheme=interface_color_scheme(),
        localized_label=observed_label,
        transitions=transitions,
    )


def assert_theme_marker(expected: str, evidence: Path) -> None:
    marker = find(expected, timeout=60)
    dump_accessibility(evidence / "theme-marker.txt")
    event(
        "theme-marker",
        expected=expected,
        observed=name(marker),
        application=owning_application(marker),
    )


def assert_toggle(key: str, *, sensitive: bool, active: bool) -> None:
    target = control(key)
    actual_sensitive = enabled(target)
    actual_active = checked(target)
    if actual_sensitive != sensitive or actual_active != active:
        raise UiFailure(
            f"{key}: expected sensitive={sensitive}, active={active}; "
            f"got sensitive={actual_sensitive}, active={actual_active}"
        )
    event(
        "assert-toggle",
        target=key,
        sensitive=actual_sensitive,
        active=actual_active,
    )


def set_toggle(key: str, active: bool) -> None:
    target = control(key)
    if not enabled(target):
        raise UiFailure(f"Toggle is disabled: {key}")
    if checked(target) == active:
        event("set-toggle", target=key, active=active, method="already-set")
        return

    def reached(timeout: float) -> bool:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if checked(control(key)) == active:
                return True
            time.sleep(0.1)
        return False

    actions = []
    try:
        actions = [action_name(target, index) for index in range(action_count(target))]
    except Exception:
        pass
    acted = perform_action(target, 0)
    if reached(2.0):
        event("set-toggle", target=key, active=active, method="action")
        return

    # Some GTK4 CheckButtons expose the Action interface but reject its
    # advertised index. Focus the same accessible checkbox and synthesize a
    # real Space keysym through AT-SPI; no screen coordinate is involved.
    target = control(key)
    try:
        focused = bool(target.grab_focus())
    except Exception:
        focused = False
    keysym_sent = False
    if focused:
        keysym_sent = bool(
            Atspi.generate_keyboard_event(0x20, None, Atspi.KeySynthType.SYM)
        )
    if reached(2.0):
        event("set-toggle", target=key, active=active, method="space-keysym")
        return

    # If GTK exposes neither Action nor Component focus, walk the real
    # keyboard focus chain.  The number of Tab presses is deliberately not
    # assumed: AT-SPI confirms that this exact semantic checkbox is focused
    # before Space is emitted.
    tab_sent = 0
    tab_space_sent = False
    for _ in range(30):
        target = control(key)
        target_focused = has_state(target, Atspi.StateType.FOCUSED) or any(
            has_state(item, Atspi.StateType.FOCUSED)
            for item in walk(target, maximum=100)
        )
        if target_focused:
            tab_space_sent = bool(
                Atspi.generate_keyboard_event(
                    0x20, None, Atspi.KeySynthType.SYM
                )
            )
            break
        if not Atspi.generate_keyboard_event(
            0xFF09, None, Atspi.KeySynthType.SYM
        ):
            break
        tab_sent += 1
        time.sleep(0.1)
    if reached(2.0):
        event(
            "set-toggle",
            target=key,
            active=active,
            method="tab-focus-space",
            tab_count=tab_sent,
        )
        return

    # The legacy AT-SPI backend interprets PRESSRELEASE as an evdev keycode;
    # 65 is Space in the XKB keycode set used by the Live GNOME session.
    keycode_sent = False
    target = control(key)
    try:
        focused = bool(target.grab_focus())
    except Exception:
        focused = False
    if focused:
        keycode_sent = bool(
            Atspi.generate_keyboard_event(
                65, None, Atspi.KeySynthType.PRESSRELEASE
            )
        )
    if reached(2.0):
        event("set-toggle", target=key, active=active, method="space-keycode")
        return

    # Wayland may reject in-guest synthetic keyboard events entirely. Ask the
    # host harness for one QMP key at a time, but keep semantic control here:
    # Space is requested only after AT-SPI observes this exact checkbox as the
    # focused object. The host never assumes a coordinate or Tab count.
    qmp_requests = 0
    for index in range(40):
        target = control(key)
        target_focused = has_state(target, Atspi.StateType.FOCUSED) or any(
            has_state(item, Atspi.StateType.FOCUSED)
            for item in walk(target, maximum=100)
        )
        requested_key = "spc" if target_focused else "tab"
        event(
            "qmp-key",
            request=f"{key}-{index}-{requested_key}",
            key=requested_key,
        )
        qmp_requests += 1
        if requested_key == "spc":
            if reached(2.0):
                event("set-toggle", target=key, active=active, method="qmp-space")
                return
        else:
            time.sleep(0.35)
    raise UiFailure(
        f"Toggle did not reach requested state: {key}={active}; "
        f"role={role(target)!r}, actions={actions!r}, acted={acted}, "
        f"focused={focused}, keysym_sent={keysym_sent}, "
        f"tab_sent={tab_sent}, tab_space_sent={tab_space_sent}, "
        f"keycode_sent={keycode_sent}, qmp_requests={qmp_requests}"
    )


def set_radio(key: str) -> None:
    """Select one radio using the observed group focus and real arrow input."""

    target = control(key)
    if role(target) != "radio button":
        raise UiFailure(f"Expected a radio button for {key!r}, got {role(target)!r}")
    if checked(target):
        event("set-radio", target=key, method="already-set")
        return

    # GTK exposes the localized mnemonic in the accessible radio label (for
    # example ``现在设置密码(O)``).  Activating that mnemonic is both semantic
    # and stable under layout changes, and avoids pretending an unselected
    # radio can be reached with Tab (Tab focuses only the selected group item).
    mnemonic = re.search(r"\(([A-Za-z])\)", name(target))
    if mnemonic is not None:
        chord = f"alt-{mnemonic.group(1).lower()}"
        event(
            "qmp-key",
            request=f"{key}-radio-mnemonic-{chord}",
            key=chord,
        )
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            if checked(control(key)):
                event(
                    "set-radio",
                    target=key,
                    method="localized-mnemonic",
                    mnemonic=chord,
                )
                return
            time.sleep(0.1)

    current = target
    radios = []
    for _ in range(10):
        radios = [
            item
            for item in walk(current, maximum=200)
            if role(item) == "radio button" and showing(item)
        ]
        if len(radios) >= 2 and target in radios:
            break
        try:
            current = current.get_parent()
        except Exception:
            current = None
        if current is None:
            break
    if len(radios) < 2:
        raise UiFailure(f"Could not discover the radio group for {key!r}")

    deadline = time.monotonic() + 30
    arrow_count = 0
    for index in range(80):
        target = control(key)
        if checked(target):
            event(
                "set-radio",
                target=key,
                method="qmp-focus-and-arrow",
                arrow_count=arrow_count,
                input_count=index,
            )
            return
        focused_target = has_state(target, Atspi.StateType.FOCUSED)
        focused_group = any(
            has_state(item, Atspi.StateType.FOCUSED) for item in radios
        )
        if focused_target:
            requested_key = "spc"
        elif focused_group:
            requested_key = "down"
            arrow_count += 1
        else:
            requested_key = "tab"
        event(
            "qmp-key",
            request=f"{key}-radio-{index}-{requested_key}",
            key=requested_key,
        )
        time.sleep(0.35)
        if time.monotonic() >= deadline:
            break
    raise UiFailure(f"Radio button did not become selected: {key!r}")


def dump_accessibility(destination: Path) -> None:
    lines = []
    for item in visible_nodes():
        value = name(item)
        if value:
            lines.append(f"{role(item)}\t{value}")
    destination.write_text("\n".join(lines) + "\n", encoding="utf-8")


def dump_accessible_text(destination: Path) -> str:
    values = []
    for item in visible_nodes():
        try:
            if not item.is_text():
                continue
            count = item.get_character_count()
            value = item.get_text(0, count)
        except Exception:
            continue
        value = (value or "").strip()
        if value and value not in values:
            values.append(value)
    content = "\n\n".join(values)
    destination.write_text(content + "\n", encoding="utf-8")
    return content


def assert_summary_plan(config: dict[str, object]) -> None:
    content = "\n".join(name(item) for item in visible_nodes() if name(item))

    def require(*variants: str) -> None:
        if not any(value in content for value in variants):
            raise UiFailure(f"Installation summary is missing: {variants!r}")

    filesystem = str(config["filesystem"])
    require(f"Filesystem: {filesystem}", f"文件系统: {filesystem}")
    expected_hostname = str(config["hostname"]).casefold()
    require(
        f"Computer Name: {expected_hostname}",
        f"计算机名称: {expected_hostname}",
    )
    if str(config["ssh"]) == "enabled":
        require("SSH password login: enabled", "SSH 密码登录: 已启用")
    else:
        require("SSH password login: disabled", "SSH 密码登录: 已禁用")
    if bool(config["automatic_login"]):
        require("Automatic desktop login: enabled", "自动登录桌面: 已启用")
    else:
        require("Automatic desktop login: disabled", "自动登录桌面: 已禁用")
    if bool(config["passwordless_sudo"]):
        require(
            "Account security: password required for login; sudo does not require a password",
            "账户安全: 登录需要密码; sudo 不需要密码",
        )
    else:
        require(
            "Account security: password required for login; sudo requires the account password",
            "账户安全: 登录需要密码; sudo 需要账户密码",
        )
    if str(config["network"]) != "online":
        require("Install input method: do not install", "安装输入法: 不安装")
        require("System updates: do not install", "系统更新: 不安装")
        require("Third-party drivers: do not install", "第三方驱动程序: 不安装")
        require(
            "Extended multimedia formats: do not install",
            "扩展多媒体格式: 不安装",
        )
    else:
        if bool(config["rime"]):
            require(
                "Install input method: AnduinOS Rime",
                "安装输入法: AnduinOS Rime",
            )
        else:
            require("Install input method: do not install", "安装输入法: 不安装")
        require("System updates: download and install", "系统更新: 下载并安装")
        if bool(config["online_features"]):
            require(
                "Third-party drivers: detect and install",
                "第三方驱动程序: 检测并安装",
            )
            require(
                "Extended multimedia formats: download and install",
                "扩展多媒体格式: 下载并安装",
            )
        else:
            require("Third-party drivers: do not install", "第三方驱动程序: 不安装")
            require(
                "Extended multimedia formats: do not install",
                "扩展多媒体格式: 不安装",
            )
    event("summary-plan", filesystem=filesystem, hostname=expected_hostname)


def connect_wifi_from_installer(config: dict[str, object], evidence: Path) -> None:
    """Associate through the real installer row and protected password dialog."""

    ssid = str(config.get("wifi_ssid", ""))
    if not ssid or len(ssid.encode("utf-8")) > 32:
        raise UiFailure("Wi-Fi scenario has no valid SSID")
    click_exact_name(ssid, timeout=90)
    password_length = config.get("wifi_password_length")
    if isinstance(password_length, bool) or not isinstance(password_length, int):
        raise UiFailure("Wi-Fi scenario has no safe password-length contract")
    request_wifi_secret("wifi-password", password_length)
    click("connect", timeout=30)

    deadline = time.monotonic() + 90
    active_uuid = ""
    active_device = ""
    ui_connected = False
    while time.monotonic() < deadline:
        result = subprocess.run(
            (
                "nmcli",
                "--terse",
                "--escape",
                "no",
                "--fields",
                "UUID,TYPE,DEVICE",
                "connection",
                "show",
                "--active",
            ),
            check=False,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            timeout=10,
        )
        matches = []
        for line in result.stdout.splitlines():
            fields = line.split(":")
            if len(fields) == 3 and fields[1] in ("802-11-wireless", "wifi"):
                matches.append((fields[0].lower(), fields[2]))
        if len(matches) == 1:
            active_uuid, active_device = matches[0]
            state = subprocess.run(
                ("nmcli", "--get-values", "GENERAL.STATE", "device", "show", active_device),
                check=False,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                timeout=10,
            ).stdout.strip()
            if not state.startswith("100"):
                active_uuid = ""
                active_device = ""
                time.sleep(0.5)
                continue
            link = subprocess.run(
                ("iw", "dev", active_device, "link"),
                check=False,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                timeout=10,
            ).stdout
            if re.search(
                rf"^\s*SSID: {re.escape(ssid)}$",
                link,
                re.MULTILINE,
            ):
                ssid_nodes = [
                    item for item in visible_nodes() if name(item) == ssid
                ]
                for ssid_node in ssid_nodes:
                    current = ssid_node
                    for _ in range(6):
                        values = [name(item) for item in walk(current, maximum=100)]
                        if any(
                            any(label.casefold() in value.casefold() for label in aliases("connected"))
                            for value in values
                            if value
                        ):
                            ui_connected = True
                            break
                        try:
                            current = current.get_parent()
                        except Exception:
                            current = None
                        if current is None:
                            break
                    if ui_connected:
                        break
        if active_uuid and ui_connected:
            break
        time.sleep(0.5)
    if not active_uuid:
        dump_accessibility(evidence / "wifi-connect-failure.txt")
        raise UiFailure("Installer Wi-Fi action did not activate a connection")
    if not ui_connected:
        dump_accessibility(evidence / "wifi-connect-failure.txt")
        raise UiFailure("Installer Wi-Fi row did not expose its Connected state")
    event(
        "wifi-connected",
        ssid=ssid,
        uuid=active_uuid,
        device=active_device,
        ui_connected=True,
        secret_transport="qmp-protected-entry",
    )


def assert_step_completed(key: str) -> None:
    nodes = [item for item in visible_nodes() if name(item)]
    for index, item in enumerate(nodes):
        if not matches(item, aliases(key)):
            continue
        previous = name(nodes[index - 1]) if index else ""
        if previous != "✓":
            raise UiFailure(f"Installer step did not complete: {key} ({previous!r})")
        event("step-complete", step=key)
        return
    raise UiFailure(f"Installer completion page is missing step: {key}")


def wait_page(key: str, timeout: float = 60) -> None:
    node = find(key, timeout=timeout)
    event("page", page=key, accessible_name=name(node))


def wait_application(candidates: tuple[str, ...], timeout: float = 90) -> str:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        applications = [name(item) for item in children(desktop())]
        for application in applications:
            if any(value.casefold() in application.casefold() for value in candidates):
                return application
        time.sleep(0.25)
    raise UiFailure(f"AT-SPI did not discover application {candidates!r}")


def launch_installer() -> subprocess.Popen | None:
    shell = wait_application(("gnome-shell", "GNOME Shell"))
    event("desktop", application=shell)
    process = None
    welcome = find_optional("welcome", 2)
    if welcome is None:
        process = subprocess.Popen(
            ["anduinos-installer-beta"],
            stdin=subprocess.DEVNULL,
            stdout=open("/tmp/anduinos-installer-ui.stdout", "wb"),
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
        welcome = find("welcome", timeout=90)
    application = welcome.get_application()
    event("installer", application=name(application) or "unnamed", window=name(welcome))
    return process


def choose_chinese() -> None:
    node = None
    for candidate in visible_nodes():
        if matches(candidate, ("Chinese (Simplified)", "中文(简体)", "中文（简体）")):
            node = candidate
            break
    if node is None:
        raise UiFailure("Simplified Chinese is not visible in the language list")
    selected = False
    current = node
    for _ in range(8):
        try:
            parent = current.get_parent()
            if parent is None:
                break
            if parent.is_selection():
                selected = bool(parent.select_child(current.get_index_in_parent()))
                if selected:
                    break
            current = parent
        except Exception:
            break
    if not selected:
        target = actionable(node)
        selected = bool(perform_action(target, 0))
    if not selected:
        raise UiFailure("Could not select Simplified Chinese")
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        if any(name(item) == "欢迎使用 AnduinOS" for item in visible_nodes()):
            event("language", locale="zh_CN.UTF-8")
            return
        time.sleep(0.25)
    raise UiFailure("Simplified Chinese selection did not update the installer")


def install(config: dict[str, object], evidence: Path) -> None:
    saved_log = Path.home() / "anduinos-install.log"
    saved_log.unlink(missing_ok=True)

    def save_executor_output() -> str:
        # Both success and failure must preserve the executor transcript.  A
        # red result without its privileged-step log is not actionable and can
        # hide the original error behind the final UI banner.
        click("output_tab")
        find("copy_log", timeout=10)
        dump_accessibility(evidence / "output.txt")
        click("save_log")
        for _ in range(40):
            if saved_log.is_file() and saved_log.stat().st_size:
                break
            time.sleep(0.25)
        else:
            raise UiFailure("Save Log did not create a non-empty installer log")
        output = saved_log.read_text(encoding="utf-8")
        (evidence / "installer-output.txt").write_text(output, encoding="utf-8")
        return output

    launch_installer()
    choose_chinese()
    click("next")

    firmware = str(config["firmware"])
    if firmware != "uefi-sb":
        wait_page("secure_boot")
        click("skip")
    network = str(config["network"])
    if network == "offline":
        wait_page("network")
        click("next")
    elif network == "wifi":
        wait_page("network")
        connect_wifi_from_installer(config, evidence)
        click("next")

    wait_page("keyboard")
    online = network == "online"
    rime = bool(config["rime"])
    assert_toggle("rime", sensitive=online, active=online)
    if online:
        set_toggle("rime", rime)
    elif rime:
        raise UiFailure("Offline scenario cannot request AnduinOS Rime")
    if not online:
        find("offline_input")
    click("next")

    wait_page("software")
    assert_toggle("updates", sensitive=online, active=online)
    if online and bool(config["online_features"]):
        set_toggle("drivers", True)
        set_toggle("multimedia", True)
    else:
        assert_toggle("drivers", sensitive=online, active=False)
        assert_toggle("multimedia", sensitive=online, active=False)
    if not online:
        find("offline_base")
    click("next")

    wait_page("disk", 120)
    disk_node = None
    disk_target = None
    deadline = time.monotonic() + 120
    while time.monotonic() < deadline and disk_target is None:
        for item in visible_nodes():
            try:
                is_action = item.is_action() and action_count(item) > 0
            except Exception:
                is_action = False
            if not is_action or role(item) not in {"toggle button", "button", "table cell"}:
                continue
            descendant = next(
                (
                    candidate
                    for candidate in walk(item, maximum=200)
                    if any(
                        path in name(candidate)
                        for path in ("/dev/vda", "/dev/sda", "/dev/nvme")
                    )
                ),
                None,
            )
            if descendant is not None:
                disk_node = descendant
                disk_target = item
                break
        if disk_target is None:
            time.sleep(0.5)
    if disk_node is None or disk_target is None:
        dump_accessibility(evidence / "disk-page.txt")
        raise UiFailure("No actionable install target disk appeared")
    if not perform_action(disk_target, 0):
        raise UiFailure("Could not select the target disk")
    event(
        "disk",
        accessible_name=name(disk_node),
        target_role=role(disk_target),
        target_name=name(disk_target),
    )
    click("next")

    wait_page("strategy")
    filesystem = str(config["filesystem"])
    set_toggle(filesystem, True)
    click("next")

    wait_page("user")
    set_text("full_name", str(config["full_name"]))
    set_text("username", str(config["username"]))
    set_text("password", str(config["password"]))
    set_text("confirm_password", str(config["password"]))
    set_text("hostname", str(config["hostname"]))
    click("next")

    wait_page("advanced")
    assert_toggle("sudo", sensitive=True, active=False)
    assert_toggle("automatic_login", sensitive=True, active=False)
    set_toggle("sudo", bool(config["passwordless_sudo"]))
    set_toggle("automatic_login", bool(config["automatic_login"]))
    ssh_enabled = str(config["ssh"]) == "enabled"
    set_toggle("ssh", ssh_enabled)
    click("next")

    wait_page("timezone")
    click("next")
    wait_page("summary")
    assert_summary_plan(config)
    dump_accessibility(evidence / "summary.txt")
    click("install")
    click("confirm", timeout=180)

    deadline = time.monotonic() + float(config["install_timeout_seconds"])
    while time.monotonic() < deadline:
        if find_optional("failed", 0.25) is not None:
            dump_accessibility(evidence / "failure.txt")
            # on_done() schedules the terminal ERROR line on the GTK main
            # context after exposing the failure banner. Give that append one
            # event-loop turn before saving the real output page.
            time.sleep(0.5)
            output = save_executor_output()
            raise UiFailure(
                "Installer reached its failure state:\n" + output[-8000:]
            )
        if find_optional("complete", 0.25) is not None:
            dump_accessibility(evidence / "complete.txt")
            # The final page hides the scrollable executor log behind the
            # StackSwitcher.  Open the real Output page so the host harness
            # can verify command execution and fatal-error markers instead of
            # trusting only the green completion banner.
            output = save_executor_output()
            if "Traceback (most recent call last)" in output:
                raise UiFailure("Installer output contains a Python traceback")
            if bool(config["online_features"]):
                assert_step_completed("driver_step")
            if network == "wifi":
                assert_step_completed("wifi_migration")
            click("complete_tab")
            event("installation-complete")
            return
    dump_accessibility(evidence / "timeout.txt")
    raise UiFailure("Timed out waiting for installation completion")


def prepare_secure_shell(evidence: Path) -> None:
    dismiss_initial_setup()
    # GNOME 50 deliberately does not register Secure Shell as a command-line
    # subpage.  The System panel exposes it through on_secure_shell_row_clicked,
    # so follow the same path a user does instead of inventing a private route.
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
    subprocess.run(
        [
            "systemd-run",
            "--user",
            "--unit=anduinos-acceptance-control-center",
            "--collect",
            "--quiet",
            "--property=StandardOutput=append:/tmp/gnome-control-center.stdout",
            "--property=StandardError=append:/tmp/gnome-control-center.stdout",
            *environment,
            "--",
            "gnome-control-center",
            "system",
        ],
        check=True,
    )
    wait_application(("gnome-control-center", "Settings", "设置"), timeout=90)
    dump_accessibility(evidence / "secure-shell-system-panel.txt")
    event("secure-shell-system-panel-ready")


def prepare_user_accounts(evidence: Path) -> None:
    """Open GNOME 50's real nested System/Users panel."""

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
    # This driver runs once as the installed user and again as the newly
    # created user.  A shared /tmp log is not writable by the second UID, and
    # a fixed transient-unit name can retain stale state after a failed run.
    # Keep both resources private to the current user and process.
    unit = f"anduinos-acceptance-user-accounts-{os.getpid()}"
    application_log = runtime / f"{unit}.log"
    application_log.unlink(missing_ok=True)

    def launch_diagnostics() -> str:
        status = subprocess.run(
            ("systemctl", "--user", "status", unit, "--no-pager", "--full"),
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        ).stdout
        log = (
            application_log.read_text(encoding="utf-8", errors="replace")
            if application_log.exists()
            else ""
        )
        diagnostics = f"systemd status:\n{status}\napplication output:\n{log}\n"
        (evidence / "gnome-users-launch-failure.txt").write_text(
            diagnostics, encoding="utf-8"
        )
        return diagnostics

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
            "users",
        ],
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    event("users-settings-launched", returncode=launched.returncode, unit=unit)
    if launched.returncode != 0:
        diagnostics = launch_diagnostics()
        raise UiFailure(
            "Could not execute GNOME Settings transient unit:\n"
            + launched.stdout
            + diagnostics[-8000:]
        )
    try:
        wait_application(("gnome-control-center", "Settings", "设置"), timeout=90)
    except UiFailure as error:
        diagnostics = launch_diagnostics()
        raise UiFailure(
            "GNOME Settings did not become accessible after launch:\n"
            + diagnostics[-8000:]
        ) from error
    find("users_panel", timeout=60)
    dump_accessibility(evidence / "users-panel.txt")
    event("users-panel-ready")


def authenticate_user_panel(evidence: Path) -> None:
    click("unlock", timeout=30)
    find("polkit", timeout=30)
    dump_accessibility(evidence / "users-polkit.txt")
    # GNOME's Polkit agent deliberately hides its password entry from AT-SPI;
    # the dialog itself owns keyboard focus.  Request opaque QMP input exactly
    # as the Secure Shell toggle path does instead of inventing an inaccessible
    # text control or falling back to screen coordinates.
    event("qmp-secret", request="accounts-polkit-password")
    event("qmp-key", request="accounts-polkit-submit", key="ret")
    wait_absent("polkit", timeout=90)
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        try:
            if enabled(find("add_user", timeout=1)):
                event("users-panel-unlocked")
                return
        except UiFailure:
            pass
        time.sleep(0.25)
    raise UiFailure("GNOME Users panel did not unlock after authentication")


def create_user(account: str, full_name: str, evidence: Path) -> None:
    prepare_user_accounts(evidence)
    authenticate_user_panel(evidence)
    request_focused_activation("add_user", "accounts-add-user", timeout=30)
    find("add_user", timeout=30)
    dump_accessibility(evidence / "add-user-dialog.txt")
    set_text("full_name", full_name)
    set_text("username", account)
    set_radio("set_password_now")
    # Selecting "Set password now" turns the dialog into a two-stage
    # assistant.  The details page action is Next; Add belongs to the password
    # page.  Keeping those semantic actions distinct makes a GNOME UI change
    # fail at the exact stage instead of tabbing around an unrelated control.
    request_focused_activation("next", "accounts-add-details", timeout=30)
    find("set_password_page", timeout=30)
    request_secret("password", "accounts-initial-password")
    request_secret("confirm_password", "accounts-initial-confirmation")
    deadline = time.monotonic() + 60
    while time.monotonic() < deadline:
        if enabled(control("add")):
            event("password-pair-accepted", context="account-create")
            break
        time.sleep(0.25)
    else:
        raise UiFailure("GNOME rejected the matching account password fields")
    request_focused_activation("add", "accounts-add-password", timeout=30)
    wait_absent("set_password_page", timeout=90)
    find(full_name, timeout=60)
    dump_accessibility(evidence / "created-user.txt")
    event("user-created", account=account, full_name=full_name)


def change_own_password(evidence: Path) -> None:
    prepare_user_accounts(evidence)
    request_focused_activation(
        "password",
        "accounts-open-change-password",
        timeout=30,
    )
    find("change_password", timeout=30)
    dump_accessibility(evidence / "change-password-dialog.txt")
    # GNOME 50 rejects grab_focus(), omits FOCUSED and character counts, and
    # reports Wayland surface-local coordinates as SCREEN coordinates. Discover
    # the current field through the product's own authentication transition;
    # after that succeeds, focus remains in the current entry and each
    # PasswordEntryRow contributes its reveal button before the next entry.
    discover_current_password_focus()
    request_dialog_secret(
        "new_password", "accounts-new-password", tab_count=2
    )
    request_dialog_secret(
        "confirm_password", "accounts-new-confirmation", tab_count=2
    )
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        if enabled(control("change")):
            event("password-pair-accepted", context="account-change")
            break
        time.sleep(0.1)
    else:
        raise UiFailure("GNOME rejected the matching replacement passwords")
    # The Users panel behind the modal also exposes "Change Avatar".  Resolve
    # the exact mnemonic-normalized dialog button and invoke that accessible
    # action; a global substring lookup can silently click the avatar instead.
    request_focused_activation(
        "change",
        "accounts-change-password-submit",
        timeout=30,
    )
    wait_absent("change_password", timeout=90)
    dump_accessibility(evidence / "password-changed.txt")
    event("password-changed")


def dynamic_user_node(account: str, full_name: str, timeout: float = 60):
    deadline = time.monotonic() + timeout
    last_nodes: list[tuple[str, str]] = []
    while time.monotonic() < deadline:
        nodes = visible_nodes()
        last_nodes = [
            (role(item), name(item)) for item in nodes if name(item)
        ][-80:]
        # GDM exposes the account as the text rendered inside the clickable
        # tile and the full name as an auxiliary accessible label.  Prefer the
        # visible account label so any AT-SPI-derived pointer target lands in
        # the real tile; retain the full name as a compatibility fallback.
        for expected in (account.casefold(), full_name.casefold()):
            exact = [item for item in nodes if name(item).casefold() == expected]
            if len(exact) == 1:
                return exact[0]
        time.sleep(0.25)
    raise UiFailure(
        f"GDM did not expose one unambiguous user label for "
        f"{account!r}/{full_name!r}; visible={last_nodes!r}"
    )


def select_gdm_user(account: str, full_name: str, evidence: Path) -> None:
    target = None
    selection_method = ""
    selection_bounds: list[int] = []
    # GNOME Shell intentionally does not expose GDM's password entry as an
    # editable AT-SPI object.  Prove the user tile transitioned to its password
    # page instead: the selected account and display name remain, and exactly
    # one Cancel button appears.  GNOME 50 keeps the selected account label in
    # its accessible cache even though only the full name is painted.  The
    # hidden entry owns keyboard focus, just like the Polkit prompt above.
    prompt_cancel_count = 0
    account_label_present = False
    display_name_present = False
    selection_attempts = 0

    def wait_password_prompt(timeout: float) -> bool:
        nonlocal prompt_cancel_count
        nonlocal account_label_present
        nonlocal display_name_present

        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            nodes = visible_nodes()
            prompt_cancel_count = sum(
                1
                for item in nodes
                if role(item) == "button" and matches(item, aliases("cancel"))
            )
            account_label_present = any(
                name(item).casefold() == account.casefold() for item in nodes
            )
            display_name_present = any(
                name(item).casefold() == full_name.casefold() for item in nodes
            )
            if (
                prompt_cancel_count == 1
                and account_label_present
                and display_name_present
            ):
                return True
            time.sleep(0.25)
        return False

    # Prefer the exact user tile's real accessible action. GNOME Shell usually
    # exposes it on an ancestor of the account label, and invoking that action
    # avoids pointer timing entirely. The coordinate fallback below remains
    # available for Shell builds that omit an actionable tile interface.
    target = dynamic_user_node(account, full_name)
    event(
        "gdm-user-target",
        account=account,
        accessible_name=name(target),
        role=role(target),
        focused=has_state(target, Atspi.StateType.FOCUSED),
        attempt=1,
    )
    try:
        semantic_target = actionable(target)
        semantic_action = perform_named_activation(semantic_target)
    except Exception:
        semantic_target = None
        semantic_action = None
    if semantic_target is not None and semantic_action is not None:
        event(
            "gdm-user-action",
            account=account,
            accessible_name=name(target),
            owner_role=role(semantic_target),
            action=semantic_action,
        )
        if wait_password_prompt(5):
            selection_method = "atspi-action"
            selection_attempts = 1

    # A freshly returned GDM greeter can consume the pointer click as selection
    # rather than activation. Bind one click to this exact account's live
    # AT-SPI bounds. If the password page does not open, activate the selected
    # tile once with Enter. Repeated pointer clicks are unsafe here: Shell may
    # begin its page transition while a later click is still queued against
    # coordinates that no longer represent a user tile.
    for attempt in (range(1) if not selection_method else ()):
        target = dynamic_user_node(account, full_name)
        selection_attempts = attempt + 1
        event(
            "gdm-user-target",
            account=account,
            accessible_name=name(target),
            role=role(target),
            focused=has_state(target, Atspi.StateType.FOCUSED),
            attempt=selection_attempts,
        )
        try:
            if not target.is_component():
                raise UiFailure("the semantic user label has no Component interface")
            bounds = target.get_extents(Atspi.CoordType.SCREEN)
        except Exception as error:
            raise UiFailure(
                f"Could not derive a click target for GDM user {account!r}: {error}"
            ) from error
        selection_bounds = [bounds.x, bounds.y, bounds.width, bounds.height]
        if (
            bounds.x < 0
            or bounds.y < 0
            or bounds.width < 2
            or bounds.height < 2
        ):
            raise UiFailure(
                f"GDM returned unusable bounds for {account!r}: "
                f"{selection_bounds!r}"
            )
        event(
            "qmp-click",
            request="gdm-select-user",
            target=account,
            accessible_name=name(target),
            x_px=round(bounds.x + bounds.width / 2, 3),
            y_px=round(bounds.y + bounds.height / 2, 3),
            bounds=selection_bounds,
            attempt=selection_attempts,
        )
        if wait_password_prompt(5):
            selection_method = "qmp-atspi-bounds"
            break
        event(
            "qmp-key",
            request="gdm-select-user-submit",
            key="ret",
            target=account,
            attempt=selection_attempts,
        )
        if wait_password_prompt(20):
            selection_method = "qmp-atspi-bounds-keyboard"
            break
    else:
        if not selection_method:
            raise UiFailure(
                f"GDM did not expose the password page for {account!r}; "
                f"cancel_count={prompt_cancel_count}, "
                f"account_label_present={account_label_present}, "
                f"selection_attempts={selection_attempts}"
            )
    assert target is not None
    dump_accessibility(evidence / f"gdm-selected-{account}.txt")
    event(
        "gdm-password-prompt",
        account=account,
        display_name=full_name,
        cancel_controls=prompt_cancel_count,
        account_label_present=account_label_present,
        editable_exposed=False,
        selection_attempts=selection_attempts,
    )
    event(
        "gdm-user-selected",
        account=account,
        accessible_name=name(target),
        method=selection_method,
        bounds=selection_bounds,
        selection_attempts=selection_attempts,
    )
    event("qmp-secret", request="gdm-password")
    event("qmp-key", request="gdm-password-submit", key="ret")


def audit_gdm_users(
    account: str,
    full_name: str,
    original_account: str,
    original_full_name: str,
    evidence: Path,
) -> None:
    nodes = visible_nodes()
    names = {name(item).casefold() for item in nodes if name(item)}
    expected = (
        (account, full_name),
        (original_account, original_full_name),
    )
    missing = [
        user
        for user, display in expected
        if user.casefold() not in names and display.casefold() not in names
    ]
    dump_accessibility(evidence / "gdm-users.txt")
    if missing:
        raise UiFailure("GDM user list is missing: " + ", ".join(missing))
    event(
        "gdm-users",
        accounts=[original_account, account],
        count=2,
    )


def probe_secure_shell_row(evidence: Path) -> None:
    matches_found = [
        item
        for item in visible_nodes()
        if role(item) == "button" and matches(item, aliases("secure_shell"))
    ]
    if len(matches_found) != 1:
        dump_accessibility(evidence / "secure-shell-row-failure.txt")
        raise UiFailure(
            "System panel did not expose exactly one Secure Shell button"
        )
    dump_accessibility(evidence / "secure-shell-row.txt")
    event(
        "secure-shell-row",
        count=1,
        focused=has_state(matches_found[0], Atspi.StateType.FOCUSED),
    )


def probe_secure_shell_switch(evidence: Path) -> None:
    target = associated_toggle("secure_shell", timeout=60)
    dump_accessibility(evidence / "secure-shell-panel.txt")
    focused = [
        {"role": role(item), "name": name(item)}
        for item in visible_nodes()
        if has_state(item, Atspi.StateType.FOCUSED)
    ]
    event(
        "secure-shell-switch",
        active=checked(target),
        enabled=enabled(target),
        focused=focus_within(target),
        focused_nodes=focused,
    )


def focus_within(node) -> bool:
    if any(has_state(item, Atspi.StateType.FOCUSED) for item in walk(node, 100)):
        return True
    current = node
    for _ in range(8):
        try:
            current = current.get_parent()
        except Exception:
            return False
        if current is None:
            return False
        if has_state(current, Atspi.StateType.FOCUSED):
            return True
    return False


def toggle_secure_shell(active: bool, evidence: Path) -> None:
    target = associated_toggle("secure_shell", timeout=60)
    if checked(target) != active:
        leaves = [
            item
            for item in list(walk(target, maximum=100))[1:]
            if role(item) in {"switch", "toggle button", "check box"}
            and not any(
                role(descendant) in {"switch", "toggle button", "check box"}
                for descendant in list(walk(item, maximum=100))[1:]
            )
        ]
        if len(leaves) != 1:
            raise UiFailure("Secure Shell row has no unique inner GTK switch")
        inner = actionable(leaves[0])
        if not perform_action(inner, 0):
            raise UiFailure("Could not activate the inner Secure Shell switch")
        deadline = time.monotonic() + 15
        while checked(target) != active and time.monotonic() < deadline:
            time.sleep(0.25)
        if find_optional("polkit", timeout=3) is not None:
            dump_accessibility(evidence / "polkit-authentication.txt")
            # GNOME Polkit exposes its hidden Caps Lock warning as SHOWING in
            # AT-SPI even when the warning is not painted. It is therefore not
            # a trustworthy keyboard-state signal for automation.
            event("polkit-required")
            return
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            current = associated_toggle("secure_shell", timeout=2)
            if checked(current) == active:
                target = current
                break
            time.sleep(0.25)
    if checked(target) != active:
        raise UiFailure(f"GNOME Secure Shell switch did not reach active={active}")
    dump_accessibility(evidence / "secure-shell-panel.txt")
    event("secure-shell", active=active)


def assert_secure_shell(active: bool, evidence: Path) -> None:
    # Polkit closes asynchronously after the password is submitted.  Waiting a
    # fixed number of seconds here made the test race the authentication agent
    # on slower guests.  The switch state is the contract we care about, so
    # wait until both the dialog has gone and GNOME exposes the final state.
    deadline = time.monotonic() + 90
    last_state: bool | None = None
    while time.monotonic() < deadline:
        if find_optional("polkit", timeout=0.5) is None:
            try:
                target = associated_toggle("secure_shell", timeout=2)
                last_state = checked(target)
                if last_state == active:
                    break
            except UiFailure:
                pass
        time.sleep(0.5)
    else:
        dump_accessibility(evidence / "secure-shell-authentication-timeout.txt")
        raise UiFailure(
            "Secure Shell authentication did not finish with "
            f"active={active}; last observed state was {last_state}"
        )
    dump_accessibility(evidence / "secure-shell-panel.txt")
    event("secure-shell", active=active, authenticated=True)


def associated_toggle(key: str, timeout: float):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        label = find_optional(key, timeout=0.25)
        if label is None:
            continue
        current = label
        for _ in range(10):
            toggles = [
                item
                for item in walk(current, maximum=500)
                if role(item) in {"switch", "toggle button", "check box"}
            ]
            semantic = semantic_toggles(toggles)
            if len(semantic) == 1:
                return semantic[0]
            try:
                current = current.get_parent()
            except Exception:
                break
            if current is None:
                break
        named = [
            item
            for item in visible_nodes()
            if role(item) in {"switch", "toggle button", "check box"}
            and matches(item, aliases(key))
        ]
        semantic = semantic_toggles(named)
        if len(semantic) == 1:
            return semantic[0]
        all_switches = [item for item in visible_nodes() if role(item) == "switch"]
        semantic = semantic_toggles(all_switches)
        if len(semantic) == 1:
            return semantic[0]
        time.sleep(0.25)
    dump_accessibility(Path("/tmp/secure-shell-panel-failure.txt"))
    raise UiFailure("Secure Shell panel has no unambiguous accessible switch")


def semantic_toggles(candidates):
    containers = []
    leaves = []
    for candidate in candidates:
        descendants = list(walk(candidate, maximum=100))[1:]
        contains_toggle = any(
            role(item) in {"switch", "toggle button", "check box"}
            for item in descendants
        )
        if contains_toggle:
            containers.append(candidate)
        else:
            leaves.append(candidate)
    # AdwSwitchRow exposes both its semantic row and an implementation child
    # as switches. The outer row owns focus, keyboard handling, and state.
    return containers if len(containers) == 1 else leaves


def verify_snapshots_manager(evidence: Path) -> None:
    dismiss_initial_setup()
    subprocess.Popen(
        ["gtk-launch", "org.anduinos.BtrfsSnapshotsManager"],
        stdin=subprocess.DEVNULL,
        stdout=open("/tmp/anduinos-snapshots-manager.stdout", "wb"),
        stderr=subprocess.STDOUT,
        start_new_session=True,
    )
    application = wait_application(
        (
            "Disk Snapshots Manager",
            "BtrfsSnapshotsManager",
            "anduinos-btrfs-snapshots-manager",
        ),
        timeout=90,
    )
    find("snapshots_manager", timeout=30)
    dump_accessibility(evidence / "snapshots-manager.txt")
    event("snapshots-manager", application=application)


def arm_snapshot_restore(title: str, evidence: Path) -> None:
    """Choose one exact deployment in the real GUI and arm its rollback."""

    dismiss_initial_setup()
    subprocess.Popen(
        ["gtk-launch", "org.anduinos.BtrfsSnapshotsManager"],
        stdin=subprocess.DEVNULL,
        stdout=open("/tmp/anduinos-snapshots-manager.stdout", "ab"),
        stderr=subprocess.STDOUT,
        start_new_session=True,
    )
    wait_application(
        (
            "Disk Snapshots Manager",
            "BtrfsSnapshotsManager",
            "anduinos-btrfs-snapshots-manager",
        ),
        timeout=90,
    )
    deadline = time.monotonic() + 90
    snapshot = None
    while time.monotonic() < deadline:
        # GTK exposes a list item's title twice: once as the semantic list
        # item name and again as its implementation label.  Count only the
        # owning rows so one real snapshot cannot look like two deployments.
        rows = [
            item
            for item in visible_nodes()
            if role(item) == "list item" and name(item) == title and showing(item)
        ]
        if len(rows) == 1:
            snapshot = rows[0]
            break
        if len(rows) > 1:
            dump_accessibility(evidence / "snapshot-restore-ambiguous.txt")
            raise UiFailure(
                f"Multiple snapshot rows have the exact title {title!r}"
            )
        time.sleep(0.5)
    if snapshot is None:
        dump_accessibility(evidence / "snapshot-restore-missing.txt")
        raise UiFailure(f"Snapshot {title!r} did not appear in the recovery UI")

    # Invoke the Roll Back button *inside this exact row*. A global text lookup
    # would silently choose the first snapshot's button when multiple rows are
    # present and could roll back to the wrong deployment.
    rollback_buttons = [
        item
        for item in walk(snapshot, maximum=200)
        if role(item) == "button"
        and name(item) in {"Roll Back", "回滚"}
        and showing(item)
    ]
    if len(rollback_buttons) != 1:
        dump_accessibility(evidence / "snapshot-restore-button-failure.txt")
        raise UiFailure(
            f"Snapshot {title!r} exposes {len(rollback_buttons)} semantic "
            "Roll Back buttons"
        )
    target = actionable(rollback_buttons[0])
    if not perform_action(target, 0):
        raise UiFailure(f"Could not invoke Roll Back for snapshot {title!r}")
    event(
        "snapshot-rollback-click",
        title=title,
        row_role=role(snapshot),
        button=name(rollback_buttons[0]),
    )
    confirmation = find_candidates(
        (f"Roll Back to {title}?", f"回滚到 {title}？"),
        label=f"rollback confirmation for {title}",
        timeout=30,
    )
    event(
        "snapshot-rollback-confirmation",
        title=title,
        accessible_name=name(confirmation),
    )
    dump_accessibility(evidence / "snapshot-restore-confirmation.txt")
    click("snapshot_prepare_restart", timeout=30)
    if find_optional("polkit", timeout=8) is not None:
        # The password is deliberately never passed into this process or its
        # serial transcript. The host recognizes this opaque request and types
        # its in-memory secret directly through QMP.
        event("qmp-secret", request="snapshot-polkit-password")
        event("qmp-key", request="snapshot-polkit-submit", key="ret")
    find("snapshot_armed", timeout=90)
    find("snapshot_restart_now", timeout=30, require_enabled=True)
    dump_accessibility(evidence / "snapshot-rollback-armed.txt")
    event(
        "snapshot-rollback-armed",
        title=title,
        restart="automatic-countdown-visible",
    )


def verify_font_rendering(evidence: Path) -> None:
    """Open the production GTK/Pango stack and expose exact text over AT-SPI."""

    dismiss_initial_setup()
    fixture = Path(__file__).with_name("font_fixture.py")
    if not fixture.is_file():
        raise UiFailure(f"Font rendering fixture is missing: {fixture}")
    output_path = Path("/tmp/anduinos-font-fixture.stdout")
    output_stream = output_path.open("wb")
    process = subprocess.Popen(
        [sys.executable, str(fixture)],
        stdin=subprocess.DEVNULL,
        stdout=output_stream,
        stderr=subprocess.STDOUT,
        start_new_session=True,
    )
    deadline = time.monotonic() + 90
    while time.monotonic() < deadline:
        if any(
            name(item) == "AnduinOS Font Rendering Fixture"
            for item in visible_nodes()
        ):
            break
        if process.poll() is not None:
            output_stream.close()
            output = output_path.read_text(encoding="utf-8", errors="replace")
            raise UiFailure(
                f"Font fixture exited with {process.returncode}: {output[-4000:]}"
            )
        time.sleep(0.25)
    else:
        output_stream.close()
        raise UiFailure("AT-SPI did not discover the font fixture window")
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        visible_names = {name(item) for item in visible_nodes() if name(item)}
        if {"🤓 🍔 🔫 👽 ✨", "变角次亮采之门"} <= visible_names:
            (evidence / "font-rendering-text.txt").write_text(
                "🤓 🍔 🔫 👽 ✨\n变角次亮采之门\n",
                encoding="utf-8",
            )
            break
        time.sleep(0.25)
    else:
        dump_accessibility(evidence / "font-rendering-failure.txt")
        raise UiFailure("Font fixture did not expose the exact test strings")
    dump_accessibility(evidence / "font-rendering.txt")
    event(
        "font-rendering",
        application="AnduinOS Font Rendering Fixture",
        emoji="🤓 🍔 🔫 👽 ✨",
        chinese="变角次亮采之门",
    )


def _select_download_in_nautilus(filename: str) -> tuple[Path, list]:
    """Select one exact Downloads item and return its accessible candidates."""

    downloads = Path.home() / "Downloads"
    target_path = downloads / filename
    if not target_path.is_file():
        raise UiFailure(f"Desktop fixture is missing: {target_path}")
    subprocess.Popen(
        ["nautilus", "--new-window", "--select", str(target_path)],
        stdin=subprocess.DEVNULL,
        stdout=open("/tmp/anduinos-nautilus.stdout", "ab"),
        stderr=subprocess.STDOUT,
        start_new_session=True,
    )
    wait_application(("Files", "Nautilus", "文件"), timeout=90)
    deadline = time.monotonic() + 60
    candidates = []
    while time.monotonic() < deadline:
        candidates = [
            item
            for item in visible_nodes()
            if name(item) == filename or name(item).startswith(filename + ".")
        ]
        if candidates:
            priority = {"table row": 0, "table cell": 1, "label": 2}
            candidates.sort(key=lambda item: priority.get(role(item), 3))
            break
        time.sleep(0.25)
    if not candidates:
        raise UiFailure(f"Nautilus did not expose {filename!r}")
    return target_path, candidates


def _open_download_in_nautilus(
    filename: str,
    expected: str | None,
    evidence: Path,
) -> None:
    """Open one selected Nautilus item through real host-delivered input."""

    target_path, candidates = _select_download_in_nautilus(filename)

    opened = False
    activation_method = ""
    # Wayland may deliberately withhold global coordinates. When it does
    # expose trustworthy screen bounds, ask the host SPICE client to deliver
    # the complete physical double-click. AT-SPI is only the semantic target
    # oracle; it must not synthesize the activation itself.
    for file_node in candidates:
        try:
            if not file_node.is_component():
                continue
            bounds = file_node.get_extents(Atspi.CoordType.SCREEN)
            if (
                # GTK4/Wayland may expose widget-relative rectangles such as
                # [0, 0, 662, 44] even when SCREEN was requested. Treat an
                # origin on either zero axis as non-global; the real trace
                # proved that accepting it double-clicks QEMU's top edge.
                bounds.x <= 0
                or bounds.y <= 0
                or bounds.width <= 0
                or bounds.height <= 0
            ):
                continue
            request_node_double_click(
                file_node,
                f"open-{filename}-double-click",
                semantic_target=filename,
            )
            event(
                "nautilus-open-attempt",
                filename=filename,
                method="host-spice-double-click",
                bounds=[bounds.x, bounds.y, bounds.width, bounds.height],
            )
            opened = True
            activation_method = "host-spice-double-click"
            break
        except Exception:
            continue

    # If Wayland hides coordinates, use Nautilus' coordinate-free keyboard
    # activation. The CLI selected the exact fixture before this point. Cycle
    # the real focus chain with QMP Tab until the selected row/content view is
    # observably focused, then let QMP deliver Enter. Never treat an AT-SPI
    # Action.do_action() return value as evidence that the file was opened.
    if not opened:
        selected_row = None
        for file_node in candidates:
            if role(file_node) != "table row":
                continue
            try:
                parent = file_node.get_parent()
                index = file_node.get_index_in_parent()
                if parent is None or not parent.is_selection():
                    continue
                if not parent.select_child(index):
                    continue
            except Exception:
                continue
            time.sleep(0.2)
            selected = has_state(file_node, Atspi.StateType.SELECTED)
            if not selected:
                continue
            selected_row = file_node
            break

        if selected_row is not None:
            for focus_attempt in range(40):
                if focus_within(selected_row):
                    event(
                        "qmp-key",
                        request=f"open-{filename}-ret",
                        key="ret",
                    )
                    event(
                        "nautilus-open-attempt",
                        filename=filename,
                        method="selected-item-qmp-enter",
                        focused=True,
                        focus_tabs=focus_attempt,
                    )
                    opened = True
                    activation_method = "selected-item-qmp-enter"
                    break
                event(
                    "qmp-key",
                    request=f"focus-{filename}-{focus_attempt}-tab",
                    key="tab",
                )
                time.sleep(0.2)

    if not opened:
        focused = [
            {
                "application": owning_application(item),
                "role": role(item),
                "name": name(item),
            }
            for item in visible_nodes()
            if has_state(item, Atspi.StateType.FOCUSED)
        ]
        raise UiFailure(
            "Nautilus could not focus the selected fixture for real host input: "
            f"{filename!r}; focused={focused!r}"
        )
    if expected is None:
        # Give Nautilus enough time to present any warning and, more
        # importantly, enough time for an incorrectly launched fixture to
        # expose either its process or its accessible GTK window.
        time.sleep(6)
        fixture_names = set(aliases("appimage_fixture"))
        fixture_window_visible = any(
            name(item) in fixture_names for item in visible_nodes()
        )
        filename_bytes = filename.encode("utf-8")
        target_resolved = target_path.resolve()
        direct_processes = []
        referencing_processes = []
        for command_line in Path("/proc").glob("[0-9]*/cmdline"):
            try:
                value = command_line.read_bytes()
            except (FileNotFoundError, PermissionError, ProcessLookupError):
                continue
            if filename_bytes not in value:
                continue
            process = command_line.parent
            arguments = [item for item in value.split(b"\0") if item]
            try:
                executable = (process / "exe").resolve(strict=True)
            except (FileNotFoundError, PermissionError, ProcessLookupError):
                executable = None
            direct = False
            if executable is not None:
                try:
                    direct = executable.samefile(target_resolved)
                except (FileNotFoundError, OSError):
                    direct = False
            if not direct and arguments:
                try:
                    argument_zero = Path(os.fsdecode(arguments[0]))
                    if argument_zero.is_absolute():
                        direct = argument_zero.samefile(target_resolved)
                except (FileNotFoundError, OSError, UnicodeError):
                    direct = False
            observation = {
                "pid": int(process.name),
                "argv0": os.fsdecode(arguments[0]) if arguments else "",
                "executable": str(executable) if executable is not None else "",
            }
            referencing_processes.append(observation)
            if direct:
                direct_processes.append(observation)
        process_running = bool(direct_processes)
        executable = os.access(target_path, os.X_OK)
        dump_accessibility(evidence / f"{filename}-blocked.txt")
        event(
            "nautilus-open-blocked",
            filename=filename,
            activation_method=activation_method,
            executable=executable,
            fixture_window_visible=fixture_window_visible,
            process_running=process_running,
            direct_processes=direct_processes,
            referencing_processes=referencing_processes,
        )
        if executable or fixture_window_visible or process_running:
            raise UiFailure(
                "Nautilus crossed the non-executable AppImage boundary: "
                f"executable={executable}, "
                f"fixture_window_visible={fixture_window_visible}, "
                f"process_running={process_running}"
            )
        # Nautilus is allowed to explain why execution was refused. Dismiss
        # that transient surface through real host input so it cannot obscure
        # the following independent PE dispatch check.
        event(
            "qmp-key",
            request=f"dismiss-{filename}-warning",
            key="esc",
        )
        time.sleep(0.5)
        return

    observed = name(find(expected, timeout=90))
    dump_accessibility(evidence / f"{filename}-opened.txt")
    event(
        "nautilus-open",
        filename=filename,
        activation_method=activation_method,
        observed=observed,
    )


def verify_appimage_file(evidence: Path) -> None:
    dismiss_initial_setup()
    Path("/tmp/anduinos-nautilus.stdout").unlink(missing_ok=True)
    try:
        _open_download_in_nautilus(
            "AnduinOS-Acceptance.AppImage",
            "appimage_fixture",
            evidence,
        )
    finally:
        subprocess.run(
            ["pkill", "-f", "AnduinOS-Acceptance.AppImage"],
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        subprocess.run(
            ["pkill", "-x", "zenity"],
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )


def verify_non_executable_appimage_file(evidence: Path) -> None:
    dismiss_initial_setup()
    Path("/tmp/anduinos-nautilus.stdout").unlink(missing_ok=True)
    _open_download_in_nautilus(
        "AnduinOS-Blocked.AppImage",
        None,
        evidence,
    )


def verify_file_thumbnail(filename: str, evidence: Path) -> None:
    """Require Nautilus to generate a content thumbnail for one exact URI."""

    dismiss_initial_setup()
    target_path, candidates = _select_download_in_nautilus(filename)
    uri = target_path.resolve().as_uri()
    digest = hashlib.md5(uri.encode("utf-8"), usedforsecurity=False).hexdigest()
    cache_roots = (
        Path.home() / ".cache" / "thumbnails" / size
        for size in ("normal", "large", "x-large", "xx-large")
    )
    thumbnail = None
    deadline = time.monotonic() + 120
    while time.monotonic() < deadline:
        for root in cache_roots:
            candidate = root / f"{digest}.png"
            if candidate.is_file() and candidate.stat().st_size > 128:
                thumbnail = candidate
                break
        if thumbnail is not None:
            break
        # Recreate the generator because cache_roots is deliberately lazy.
        cache_roots = (
            Path.home() / ".cache" / "thumbnails" / size
            for size in ("normal", "large", "x-large", "xx-large")
        )
        time.sleep(0.5)
    if thumbnail is None:
        dump_accessibility(evidence / f"{filename}-thumbnail-missing.txt")
        raise UiFailure(f"Nautilus generated no thumbnail for {filename!r}")
    visible = [
        {"name": name(item), "role": role(item)}
        for item in candidates
        if showing(item)
    ]
    if not visible:
        raise UiFailure(f"Nautilus hid {filename!r} while generating its thumbnail")
    dump_accessibility(evidence / f"{filename}-thumbnail-visible.txt")
    event(
        "file-thumbnail",
        filename=filename,
        uri=uri,
        cache_path=str(thumbnail),
        cache_size=thumbnail.stat().st_size,
        visible_nodes=visible,
    )


def verify_image_open(evidence: Path) -> None:
    dismiss_initial_setup()
    filename = "AnduinOS-Image.png"
    _open_download_in_nautilus(filename, filename, evidence)
    application = wait_application(("loupe", "image viewer", "图像查看器"), timeout=90)
    running = subprocess.run(
        ("pgrep", "-x", "loupe"),
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        text=True,
    ).returncode == 0
    windows = sorted(
        {
            name(item)
            for item in visible_nodes()
            if owning_application(item) == application and name(item)
        }
    )
    if not running or not windows:
        raise UiFailure("Loupe did not expose the opened image fixture")
    event(
        "image-opened",
        filename=filename,
        application=application,
        process_running=running,
        visible_names=windows,
    )


def _gdbus_call(*arguments: str) -> str:
    result = subprocess.run(
        ("gdbus", "call", "--session", *arguments),
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        timeout=15,
    )
    if result.returncode != 0:
        raise UiFailure("D-Bus query failed: " + result.stdout)
    return result.stdout


def verify_video_open(evidence: Path) -> None:
    dismiss_initial_setup()
    filename = "AnduinOS-Video.mp4"
    _open_download_in_nautilus(filename, filename, evidence)
    application = wait_application(("celluloid",), timeout=90)
    names = _gdbus_call(
        "--dest",
        "org.freedesktop.DBus",
        "--object-path",
        "/org/freedesktop/DBus",
        "--method",
        "org.freedesktop.DBus.ListNames",
    )
    matches = sorted(
        set(
            re.findall(
                r"org\.mpris\.MediaPlayer2\.[^'\s,)]*celluloid[^'\s,)]*",
                names,
                re.IGNORECASE,
            )
        )
    )
    if len(matches) != 1:
        raise UiFailure(f"Celluloid exposed no unique MPRIS identity: {matches!r}")
    destination = matches[0]

    def property_value(property_name: str) -> str:
        return _gdbus_call(
            "--dest",
            destination,
            "--object-path",
            "/org/mpris/MediaPlayer2",
            "--method",
            "org.freedesktop.DBus.Properties.Get",
            "org.mpris.MediaPlayer2.Player",
            property_name,
        )

    metadata = property_value("Metadata")
    if filename not in metadata:
        raise UiFailure("Celluloid MPRIS metadata does not identify the fixture")
    position = 0
    status = ""
    deadline = time.monotonic() + 30
    requested_play = False
    while time.monotonic() < deadline:
        status_output = property_value("PlaybackStatus")
        status_match = re.search(r"(?:Playing|Paused|Stopped)", status_output)
        status = status_match.group(0) if status_match else ""
        position_output = property_value("Position")
        position_match = re.search(r"(?:u?int64)\s+(\d+)", position_output)
        position = int(position_match.group(1)) if position_match else 0
        if position > 100_000:
            break
        if status == "Paused" and not requested_play:
            event("qmp-key", request="celluloid-start-playback", key="spc")
            requested_play = True
        time.sleep(0.5)
    if position <= 100_000:
        raise UiFailure(
            f"Celluloid playback never advanced: status={status!r}, position={position}"
        )
    event(
        "video-opened",
        filename=filename,
        application=application,
        mpris_destination=destination,
        playback_status=status,
        position_microseconds=position,
        metadata_identifies_fixture=True,
    )


def verify_deb_software(evidence: Path) -> None:
    dismiss_initial_setup()
    filename = "anduinos-acceptance-fixture_1.0_all.deb"
    _open_download_in_nautilus(filename, filename, evidence)
    application = wait_application(("gnome-software", "software", "软件"), timeout=120)
    deadline = time.monotonic() + 120
    details = []
    while time.monotonic() < deadline:
        details = [
            name(item)
            for item in visible_nodes()
            if owning_application(item) == application
            and (
                "anduinos acceptance fixture" in name(item).casefold()
                or "anduinos-acceptance-fixture" in name(item).casefold()
            )
        ]
        if details:
            break
        time.sleep(0.5)
    installed = subprocess.run(
        ("dpkg-query", "-W", "-f=${db:Status-Abbrev}", "anduinos-acceptance-fixture"),
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        text=True,
    ).stdout.strip().startswith("ii ")
    if not details or installed:
        dump_accessibility(evidence / "deb-software-page-missing.txt")
        raise UiFailure(
            f"GNOME Software did not expose the harmless DEB without installing it: "
            f"details={details!r}, installed={installed}"
        )
    event(
        "deb-software",
        filename=filename,
        application=application,
        detail_names=sorted(set(details)),
        package_installed=installed,
    )


def verify_chinese_editor(evidence: Path) -> None:
    """Edit and save the exact acceptance phrase in GNOME Text Editor."""

    dismiss_initial_setup()
    filename = "AnduinOS-Chinese.txt"
    target_path = Path.home() / "Downloads" / filename
    _open_download_in_nautilus(filename, filename, evidence)
    application = wait_application(
        ("gnome-text-editor", "text editor", "文本编辑器"),
        timeout=90,
    )
    deadline = time.monotonic() + 60
    editables = []
    while time.monotonic() < deadline:
        editables = []
        for item in visible_nodes():
            if owning_application(item) != application:
                continue
            try:
                if item.is_editable_text() and showing(item):
                    editables.append(item)
            except Exception:
                continue
        if editables:
            break
        time.sleep(0.25)
    if not editables:
        dump_accessibility(evidence / "chinese-editor-missing.txt")
        raise UiFailure("GNOME Text Editor exposed no editable document surface")

    def editable_area(item) -> int:
        try:
            bounds = item.get_extents(Atspi.CoordType.WINDOW)
            return max(0, bounds.width) * max(0, bounds.height)
        except Exception:
            return 0

    target = max(editables, key=editable_area)
    expected = "变角次亮采之门"
    try:
        target.grab_focus()
    except Exception:
        pass
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        if has_state(target, Atspi.StateType.FOCUSED):
            break
        time.sleep(0.1)
    else:
        raise UiFailure("GNOME Text Editor document surface did not gain focus")

    text_interface = target.get_text()
    initial_count = Atspi.Text.get_character_count(text_interface)
    initial = Atspi.Text.get_text(text_interface, 0, initial_count)
    if initial:
        raise UiFailure(
            f"GNOME Text Editor fixture was not initially empty: {initial!r}"
        )
    # Type every non-ASCII character through Linux's standard Unicode input
    # sequence. The host supplies the physical Ctrl+Shift+U, hexadecimal code
    # point, and Enter events; AT-SPI only verifies focus and the final text.
    for index, character in enumerate(expected):
        event(
            "qmp-key",
            request=f"chinese-editor-unicode-{index}-start",
            key="ctrl-shift-u",
        )
        event("qmp-text", request=f"chinese-editor-unicode-{index}-codepoint")
        event(
            "qmp-key",
            request=f"chinese-editor-unicode-{index}-commit",
            key="ret",
        )
    deadline = time.monotonic() + 30
    observed = ""
    while time.monotonic() < deadline:
        count = Atspi.Text.get_character_count(text_interface)
        observed = Atspi.Text.get_text(text_interface, 0, count)
        observed = unicodedata.normalize("NFC", observed)
        if observed == expected:
            break
        time.sleep(0.1)
    else:
        raise UiFailure(
            f"GNOME Text Editor returned {observed!r}, expected {expected!r}"
        )
    def activate_editor_control(names: tuple[str, ...], purpose: str) -> str:
        semantic_names = {semantic_name(value) for value in names}
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            for item in visible_nodes():
                if (
                    owning_application(item) != application
                    or semantic_name(name(item)) not in semantic_names
                    or not showing(item)
                ):
                    continue
                try:
                    control = actionable(item)
                    actions = [
                        action_name(control, action_index)
                        for action_index in range(action_count(control))
                    ]
                except Exception:
                    continue
                if perform_action(control, 0):
                    event(
                        "text-editor-action",
                        purpose=purpose,
                        accessible_name=name(item),
                        actions=actions,
                    )
                    time.sleep(0.35)
                    return name(item)
            time.sleep(0.25)
        raise UiFailure(
            f"GNOME Text Editor exposed no actionable {purpose}: {names!r}"
        )

    menu_name = activate_editor_control(("Main Menu", "主菜单"), "main-menu")
    # GTK 4 does not expose ordinary GMenu rows (including Save) through
    # AT-SPI, and the popover's custom children incorrectly report 0,0 for
    # SCREEN coordinates. The title-bar menu button does expose correct screen
    # bounds. This acceptance VM has an explicitly verified 1280x800
    # framebuffer, and Text Editor opens at a deterministic centered size.
    # Click the rendered Save row in that fixed viewport. A future resolution
    # or layout change fails the host precondition or the exact-byte oracle.
    event(
        "qmp-click",
        request="chinese-editor-save-menu-row",
        target="Save",
        anchor="fixed-1280x800-framebuffer",
        x_px=852,
        y_px=364,
        button="left",
        framebuffer=[1280, 800],
    )
    save_name = "Save menu row"
    # GNOME Text Editor deliberately enables GtkSourceBuffer's implicit
    # trailing newline by default. The visible document remains exactly the
    # requested seven characters; its normal serialized form contains one
    # additional LF and nothing else.
    serialized = (expected + "\n").encode("utf-8")
    deadline = time.monotonic() + 30
    saved = b""
    while time.monotonic() < deadline:
        try:
            saved = target_path.read_bytes()
        except OSError:
            saved = b""
        if saved == serialized:
            break
        time.sleep(0.25)
    if saved != serialized:
        raise UiFailure(
            "GNOME Text Editor did not save the exact normalized UTF-8 text "
            "with its one implicit trailing newline"
        )
    running = subprocess.run(
        ("pgrep", "-f", "(^|/)gnome-text-editor( |$)"),
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        text=True,
    ).returncode == 0
    if not running:
        raise UiFailure("GNOME Text Editor exited while saving the fixture")
    dump_accessibility(evidence / "chinese-editor-saved.txt")
    event(
        "chinese-editor",
        filename=filename,
        application=application,
        expected=expected,
        observed=observed,
        menu_accessible_name=menu_name,
        save_accessible_name=save_name,
        character_count=len(observed),
        utf8_sha256=hashlib.sha256(saved).hexdigest(),
        implicit_trailing_newline=True,
        process_running=running,
        saved=True,
    )


def verify_windows_executable_file(evidence: Path) -> None:
    dismiss_initial_setup()
    Path("/tmp/anduinos-nautilus.stdout").unlink(missing_ok=True)
    _open_download_in_nautilus("cpu-z.exe", "cpuz_recommendation", evidence)
    find("mission_center", timeout=30)
    event("cpu-z-recommendation", application="AnduinOS Windows EXE Runner")


def verify_windows_executable_thumbnail(evidence: Path) -> None:
    verify_file_thumbnail("cpu-z.exe", evidence)


def verify_public_cpuz_file(filename: str, evidence: Path) -> None:
    """Preview and dispatch the pinned public CPU-Z binary on a clean system."""

    if filename != "cpuz_x64.exe":
        raise UiFailure(f"Unsupported public CPU-Z member: {filename!r}")
    dismiss_initial_setup()
    Path("/tmp/anduinos-nautilus.stdout").unlink(missing_ok=True)
    verify_file_thumbnail(filename, evidence)
    _open_download_in_nautilus(filename, "cpuz_installing", evidence)

    reason = find("cpuz_native_reason", timeout=30)
    controls = {
        key: find(key, timeout=30)
        for key in ("cancel", "force_run", "cpux_get")
    }
    control_evidence = {
        key: {
            "name": name(node),
            "role": role(node),
            "enabled": enabled(node),
            "showing": showing(node),
        }
        for key, node in controls.items()
    }
    if any(
        value["role"] not in {"button", "push button"}
        or value["enabled"] is not True
        or value["showing"] is not True
        for value in control_evidence.values()
    ):
        dump_accessibility(evidence / "cpuz-recommendation-controls-failed.txt")
        raise UiFailure(
            "CPU-Z native recommendation has unusable semantic controls: "
            f"{control_evidence!r}"
        )

    bottles = subprocess.run(
        ("flatpak", "info", "com.usebottles.bottles"),
        check=False,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    ).returncode == 0
    runner = subprocess.run(
        ("pgrep", "-af", "anduinos-exe-runner"),
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        text=True,
    )
    runner_lines = [
        line
        for line in runner.stdout.splitlines()
        if filename in line and "pgrep -af" not in line
    ]
    if bottles or not runner_lines:
        dump_accessibility(evidence / "cpuz-runner-precondition-failed.txt")
        raise UiFailure(
            "CPU-Z did not reach its native-alternative EXE Runner page: "
            f"bottles_installed={bottles}, runner_lines={runner_lines!r}"
        )
    dump_accessibility(evidence / "cpuz-runner-opened.txt")
    event(
        "cpu-z-public-recommendation",
        filename=filename,
        application="AnduinOS Windows EXE Runner",
        heading=name(find("cpuz_installing", timeout=3)),
        reason=name(reason),
        controls=control_evidence,
        bottles_installed=bottles,
        runner_processes=runner_lines,
    )


def _rime_fixture_entry(evidence: Path):
    deadline = time.monotonic() + 90
    while time.monotonic() < deadline:
        for window in visible_nodes():
            if name(window) != "AnduinOS Rime Input Fixture":
                continue
            editables = []
            for item in walk(window, maximum=1000):
                try:
                    if item.is_editable_text() and showing(item):
                        editables.append(item)
                except Exception:
                    continue
            if len(editables) == 1:
                return editables[0]
            if editables:
                dump_accessibility(evidence / "rime-input-ambiguous.txt")
                raise UiFailure(
                    f"Rime fixture exposed {len(editables)} editable controls"
                )
        time.sleep(0.25)
    dump_accessibility(evidence / "rime-input-missing.txt")
    raise UiFailure("AT-SPI did not discover the Rime input fixture")


def prepare_rime_input(evidence: Path) -> None:
    dismiss_initial_setup()
    target = _rime_fixture_entry(evidence)
    if not target.set_text_contents(""):
        raise UiFailure("Could not clear the Rime input fixture")
    focused = has_state(target, Atspi.StateType.FOCUSED)
    if not focused:
        try:
            target.grab_focus()
        except Exception:
            pass
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        if has_state(target, Atspi.StateType.FOCUSED):
            break
        time.sleep(0.1)
    else:
        raise UiFailure("Rime input fixture never received keyboard focus")
    dump_accessibility(evidence / "rime-input-prepared.txt")
    event("rime-input-prepared", focused=True)


def assert_rime_input(expected: str, evidence: Path) -> None:
    target = _rime_fixture_entry(evidence)
    # Atspi.Accessible.get_text() returns the Text interface in current GI.
    # Calling the old range-taking form on Accessible itself fails on GNOME 50.
    text_interface = target.get_text()
    count = Atspi.Text.get_character_count(text_interface)
    # Accessible and Text both export a method named get_text. Invoke the
    # interface method explicitly so PyGObject cannot resolve the proxy back
    # to Accessible.get_text() and reject the range arguments.
    observed = Atspi.Text.get_text(text_interface, 0, count)
    normalized_expected = unicodedata.normalize("NFC", expected)
    normalized_observed = unicodedata.normalize("NFC", observed)
    (evidence / "rime-input-result.json").write_text(
        json.dumps(
            {
                "expected": normalized_expected,
                "observed": normalized_observed,
                "exact": normalized_observed == normalized_expected,
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    if normalized_observed != normalized_expected:
        dump_accessibility(evidence / "rime-input-wrong-text.txt")
        raise UiFailure(
            f"Rime produced {normalized_observed!r}, expected "
            f"{normalized_expected!r}"
        )
    event("rime-input-result", expected=normalized_expected, observed=normalized_observed)


SHELL_WINDOW_ALPHA = "AnduinOS Shortcut Window Alpha"
SHELL_WINDOW_BETA = "AnduinOS Shortcut Window Beta"
NETWORK_STATS_UUID = "network-stats@gnome.noroadsleft.xyz"
SHELL_FIXTURE_NAME = "AnduinOS Shell Acceptance Fixture"
PANEL_FIXTURE_NAME = "AnduinOS Panel Acceptance Fixture"
PANEL_WINDOW_TITLE = "AnduinOS Panel Fixture Window"


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


def _overview_nodes() -> list[tuple[str, str]]:
    candidates = {value.casefold() for value in aliases("overview_panel")}
    return [
        (role(item), name(item))
        for item in visible_nodes()
        if owning_application(item) == "gnome-shell"
        and role(item) == "panel"
        and name(item).casefold() in candidates
    ]


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


def _close_arcmenu(request: str) -> None:
    if _arcmenu_markers():
        event("qmp-key", request=request, key="esc")
        _wait_arcmenu(False)


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
            if owning_application(item) != "gnome-shell"
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


def exercise_desktop_terminal(evidence: Path) -> None:
    dismiss_initial_setup()
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
    item = find("desktop_open_terminal", timeout=30, require_enabled=True)
    menu_label = name(item)
    dump_accessibility(evidence / "desktop-context-menu.txt")
    click("desktop_open_terminal", timeout=30)
    deadline = time.monotonic() + 60
    windows: list[tuple[str, str, str]] = []
    while time.monotonic() < deadline:
        windows = _terminal_windows()
        if windows:
            break
        time.sleep(0.25)
    if not windows:
        raise UiFailure("DING Open in Terminal did not create a visible Ptyxis window")
    dump_accessibility(evidence / "desktop-terminal-opened.txt")
    event(
        "desktop-terminal",
        phase="opened",
        visible=True,
        application=windows[0][0],
        windows=windows,
        menu_label=menu_label,
        directory=str(_desktop_fixture_path().parent),
    )
    event("qmp-key", request="desktop-terminal-close", key="alt-f4")
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline and _terminal_windows():
        time.sleep(0.25)
    if _terminal_windows():
        raise UiFailure("Ptyxis remained visible after Alt+F4")
    event("desktop-terminal", phase="closed", visible=False)


def _desktop_fixture_click_target(icon):
    """Return DING's labelled hit area, after proving its icon ownership.

    DING connects button handlers to the icon and label ``Gtk.EventBox``
    children, not to the outer grid-cell filler exposed through AT-SPI.  The
    label accessible is nested inside one of those event boxes, so its centre
    is a semantic, resolution-independent click point which is guaranteed to
    reach DING's own click counter.  Walking to the filler is only an ownership
    proof; clicking the filler centre can land in padding between the two hit
    areas and turn a double-click into selection-only behaviour.
    """

    tile = icon
    for _depth in range(8):
        if role(tile) == "filler" and PANEL_FIXTURE_NAME in name(tile):
            return icon
        try:
            tile = tile.get_parent()
        except Exception:
            tile = None
        if tile is None:
            break
    raise UiFailure("DING did not expose the desktop application's semantic icon tile")


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
    activated = activate_shell_context_action(
        "desktop_shortcut_create",
        "desktop-shortcut-action",
    )
    if activated != localized:
        raise UiFailure("Desktop shortcut action identity changed before activation")
    _close_arcmenu("desktop-shortcut-close")
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
    click_target = _desktop_fixture_click_target(icon)
    request_node_double_click(
        click_target,
        "desktop-shortcut-launch",
        semantic_target=PANEL_FIXTURE_NAME,
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


def dismiss_initial_setup() -> None:
    target = find_optional("finish_setup", timeout=3)
    if target is None:
        return
    setup_application = owning_application(target)
    click("finish_setup", timeout=30)
    deadline = time.monotonic() + 60
    while time.monotonic() < deadline:
        button_absent = find_optional("finish_setup", timeout=0.25) is None
        application_absent = not any(
            owning_application(item) == setup_application for item in visible_nodes()
        )
        if button_absent and application_absent:
            break
        time.sleep(0.25)
    else:
        raise UiFailure(
            f"Initial Setup did not close after its Finish action: "
            f"{setup_application!r}"
        )
    time.sleep(2)
    event("initial-setup-complete", application=setup_application)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "mode",
        choices=(
            "install",
            "secure-shell-prepare",
            "secure-shell-row",
            "secure-shell-probe",
            "secure-shell-on",
            "secure-shell-off",
            "secure-shell-assert-on",
            "secure-shell-assert-off",
            "snapshots-manager",
            "font-rendering",
            "appimage-file",
            "appimage-file-non-executable",
            "windows-executable-thumbnail",
            "windows-executable-file",
            "public-cpuz-file",
            "file-image-thumbnail",
            "file-video-thumbnail",
            "file-image-open",
            "file-video-open",
            "file-deb-software",
            "file-chinese-editor",
            "rime-input-prepare",
            "rime-input-assert",
            "snapshot-restore-arm",
            "accounts-create",
            "accounts-change-password",
            "gdm-select-user",
            "gdm-audit-users",
            "theme-set",
            "theme-assert-marker",
            "shell-initial-overview",
            "shortcut-alt-tab",
            "shortcut-super-tab",
            "shortcut-super-i",
            "settings-about-branding",
            "installed-region-zh-cn",
            "localization-zh-cn",
            "shortcut-super-u",
            "shortcut-screenshot",
            "shell-start-button",
            "shell-panel-pin",
            "shell-panel-pin-persisted",
            "shell-panel-remove",
            "shell-appindicator-roundtrip",
            "shell-desktop-icons",
            "shell-desktop-terminal",
            "shell-desktop-shortcut",
            "shell-spotify-store",
            "public-wechat-install",
            "public-wechat-tray",
            "swapcontrol-green",
        ),
    )
    parser.add_argument("--config", type=Path)
    parser.add_argument("--evidence", type=Path, required=True)
    parser.add_argument("--expected", default="")
    parser.add_argument("--account", default="")
    parser.add_argument("--full-name", default="")
    parser.add_argument("--original-account", default="")
    parser.add_argument("--original-full-name", default="")
    parser.add_argument("--filename", default="")
    args = parser.parse_args()
    args.evidence.mkdir(parents=True, exist_ok=True)
    try:
        if args.mode == "install":
            if args.config is None:
                raise UiFailure("Installer mode requires --config")
            install(json.loads(args.config.read_text(encoding="utf-8")), args.evidence)
        elif args.mode == "secure-shell-prepare":
            prepare_secure_shell(args.evidence)
        elif args.mode == "secure-shell-row":
            probe_secure_shell_row(args.evidence)
        elif args.mode == "secure-shell-probe":
            probe_secure_shell_switch(args.evidence)
        elif args.mode.startswith("secure-shell-assert-"):
            assert_secure_shell(args.mode.endswith("on"), args.evidence)
        elif args.mode.startswith("secure-shell-"):
            toggle_secure_shell(args.mode.endswith("on"), args.evidence)
        elif args.mode == "snapshots-manager":
            verify_snapshots_manager(args.evidence)
        elif args.mode == "font-rendering":
            verify_font_rendering(args.evidence)
        elif args.mode == "appimage-file":
            verify_appimage_file(args.evidence)
        elif args.mode == "appimage-file-non-executable":
            verify_non_executable_appimage_file(args.evidence)
        elif args.mode == "windows-executable-thumbnail":
            verify_windows_executable_thumbnail(args.evidence)
        elif args.mode == "windows-executable-file":
            verify_windows_executable_file(args.evidence)
        elif args.mode == "public-cpuz-file":
            verify_public_cpuz_file(args.filename, args.evidence)
        elif args.mode == "file-image-thumbnail":
            verify_file_thumbnail("AnduinOS-Image.png", args.evidence)
        elif args.mode == "file-video-thumbnail":
            verify_file_thumbnail("AnduinOS-Video.mp4", args.evidence)
        elif args.mode == "file-image-open":
            verify_image_open(args.evidence)
        elif args.mode == "file-video-open":
            verify_video_open(args.evidence)
        elif args.mode == "file-deb-software":
            verify_deb_software(args.evidence)
        elif args.mode == "file-chinese-editor":
            verify_chinese_editor(args.evidence)
        elif args.mode == "rime-input-prepare":
            prepare_rime_input(args.evidence)
        elif args.mode == "rime-input-assert":
            if not args.expected:
                raise UiFailure("Rime assertion mode requires --expected")
            assert_rime_input(args.expected, args.evidence)
        elif args.mode == "snapshot-restore-arm":
            if not args.expected:
                raise UiFailure("Snapshot restore mode requires --expected")
            arm_snapshot_restore(args.expected, args.evidence)
        elif args.mode == "accounts-create":
            if not args.account or not args.full_name:
                raise UiFailure("Account creation requires account and full name")
            create_user(args.account, args.full_name, args.evidence)
        elif args.mode == "accounts-change-password":
            change_own_password(args.evidence)
        elif args.mode == "gdm-select-user":
            if not args.account or not args.full_name:
                raise UiFailure("GDM selection requires account and full name")
            select_gdm_user(args.account, args.full_name, args.evidence)
        elif args.mode == "gdm-audit-users":
            if not all(
                (
                    args.account,
                    args.full_name,
                    args.original_account,
                    args.original_full_name,
                )
            ):
                raise UiFailure("GDM audit requires both account identities")
            audit_gdm_users(
                args.account,
                args.full_name,
                args.original_account,
                args.original_full_name,
                args.evidence,
            )
        elif args.mode == "theme-set":
            if args.expected not in {"light", "dark"}:
                raise UiFailure("Theme selection requires --expected light or dark")
            set_desktop_theme(args.expected, args.evidence)
        elif args.mode == "theme-assert-marker":
            if not args.expected:
                raise UiFailure("Theme marker assertion requires --expected")
            assert_theme_marker(args.expected, args.evidence)
        elif args.mode == "shell-initial-overview":
            assert_initial_overview_hidden(args.evidence)
        elif args.mode == "shortcut-alt-tab":
            exercise_alt_tab(args.evidence)
        elif args.mode == "shortcut-super-tab":
            exercise_super_tab(args.evidence)
        elif args.mode == "shortcut-super-i":
            exercise_super_i(args.evidence)
        elif args.mode == "settings-about-branding":
            exercise_settings_about_branding(args.evidence)
        elif args.mode == "installed-region-zh-cn":
            observe_installed_region_zh_cn(args.evidence)
        elif args.mode == "localization-zh-cn":
            exercise_localization_zh_cn(args.evidence)
        elif args.mode == "shortcut-super-u":
            exercise_super_u(args.evidence)
        elif args.mode == "shortcut-screenshot":
            exercise_screenshot_shortcut(args.evidence)
        elif args.mode == "shell-start-button":
            exercise_start_button(args.evidence)
        elif args.mode == "shell-panel-pin":
            exercise_panel_pin(args.evidence)
        elif args.mode == "shell-panel-pin-persisted":
            exercise_panel_pin_persisted(args.evidence)
        elif args.mode == "shell-panel-remove":
            exercise_panel_remove(args.evidence)
        elif args.mode == "shell-appindicator-roundtrip":
            exercise_appindicator_roundtrip(args.evidence)
        elif args.mode == "shell-desktop-icons":
            verify_default_desktop_icons(args.evidence)
        elif args.mode == "shell-desktop-terminal":
            exercise_desktop_terminal(args.evidence)
        elif args.mode == "shell-desktop-shortcut":
            exercise_desktop_shortcut(args.evidence)
        elif args.mode == "shell-spotify-store":
            exercise_spotify_store(args.evidence)
        elif args.mode == "public-wechat-install":
            exercise_wechat_install(args.evidence)
        elif args.mode == "public-wechat-tray":
            exercise_wechat_tray(args.evidence)
        elif args.mode == "swapcontrol-green":
            exercise_swapcontrol_green(args.evidence)
        else:
            raise UiFailure(f"Unhandled AT-SPI driver mode: {args.mode}")
        return 0
    except Exception as error:
        event("failure", error=str(error), type=type(error).__name__)
        try:
            dump_accessibility(args.evidence / "last-accessibility-tree.txt")
        except Exception:
            pass
        return 1


if __name__ == "__main__":
    sys.exit(main())
