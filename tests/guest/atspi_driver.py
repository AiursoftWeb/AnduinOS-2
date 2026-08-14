#!/usr/bin/python3
"""Drive the real GTK installer and GNOME Settings through AT-SPI.

This file is copied into a running guest by the host harness.  It deliberately
uses only PyGObject and the AT-SPI GIR shipped in the production desktop.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path

import gi

gi.require_version("Atspi", "2.0")
from gi.repository import Atspi


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
    "snapshots_manager": (
        "Disk Snapshots Manager",
        "Btrfs Snapshots Manager",
        "磁盘快照管理器",
    ),
    "finish_setup": (
        "Start your AnduinOS journey",
        "开始您的 AnduinOS 之旅",
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
    candidates = aliases(key)
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
        f"Timed out waiting for {key!r} ({candidates!r}); visible={last_names!r}"
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


def control(key: str):
    candidates = aliases(key)
    for item in visible_nodes():
        if role(item) not in {"check box", "toggle button", "switch", "button"}:
            continue
        if matches(item, candidates) or any(
            matches(descendant, candidates) for descendant in walk(item, maximum=200)
        ):
            return item
    return actionable(find(key))


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
    if str(config["network"]) == "offline":
        require("Install input method: do not install", "安装输入法: 不安装")
        require("System updates: do not install", "系统更新: 不安装")
        require("Third-party drivers: do not install", "第三方驱动程序: 不安装")
        require(
            "Extended multimedia formats: do not install",
            "扩展多媒体格式: 不安装",
        )
    elif bool(config["online_features"]):
        require("Install input method: AnduinOS Rime", "安装输入法: AnduinOS Rime")
        require("System updates: download and install", "系统更新: 下载并安装")
        require(
            "Third-party drivers: detect and install",
            "第三方驱动程序: 检测并安装",
        )
        require(
            "Extended multimedia formats: download and install",
            "扩展多媒体格式: 下载并安装",
        )
    event("summary-plan", filesystem=filesystem, hostname=expected_hostname)


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
    launch_installer()
    choose_chinese()
    click("next")

    firmware = str(config["firmware"])
    if firmware != "uefi-sb":
        wait_page("secure_boot")
        click("skip")
    if str(config["network"]) == "offline":
        wait_page("network")
        click("next")

    wait_page("keyboard")
    online = str(config["network"]) == "online"
    assert_toggle("rime", sensitive=online, active=online)
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
            raise UiFailure("Installer reached its failure state")
        if find_optional("complete", 0.25) is not None:
            dump_accessibility(evidence / "complete.txt")
            # The final page hides the scrollable executor log behind the
            # StackSwitcher.  Open the real Output page so the host harness
            # can verify command execution and fatal-error markers instead of
            # trusting only the green completion banner.
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
            (evidence / "installer-output.txt").write_text(
                output, encoding="utf-8"
            )
            if "Traceback (most recent call last)" in output:
                raise UiFailure("Installer output contains a Python traceback")
            if bool(config["online_features"]):
                assert_step_completed("driver_step")
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


def dismiss_initial_setup() -> None:
    if find_optional("finish_setup", timeout=3) is None:
        return
    click("finish_setup", timeout=30)
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        if find_optional("finish_setup", timeout=0.25) is None:
            break
        time.sleep(0.25)
    time.sleep(1)
    event("initial-setup-complete")


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
        ),
    )
    parser.add_argument("--config", type=Path)
    parser.add_argument("--evidence", type=Path, required=True)
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
        else:
            verify_snapshots_manager(args.evidence)
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
