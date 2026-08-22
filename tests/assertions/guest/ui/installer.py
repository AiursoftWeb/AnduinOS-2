"""Native installer navigation, Wi-Fi, plan, and completion behavior."""

from .core import *  # noqa: F403


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
__all__ = tuple(name for name in globals() if not name.startswith("__"))
