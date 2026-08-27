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


def visible_application_nodes(application_name: str):
    """Return visible nodes from one real AT-SPI application only.

    First boot can expose GNOME Shell, OOBE, and desktop extensions at the
    same time.  A temporarily incomplete cache in one application must not
    prevent a contract about another application from being observed.
    """

    roots = [
        item
        for item in children(desktop())
        if name(item) == application_name
    ]
    return tuple(
        item
        for root in roots
        for item in walk(root)
        if showing(item)
    )


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
__all__ = tuple(name for name in globals() if not name.startswith("__"))
