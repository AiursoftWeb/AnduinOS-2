"""Installed-guest command, transfer, login, SSH, and shutdown helpers."""

from .shared import *  # noqa: F403
from .protocol import _run_with_qmp_key_requests
from assertions.desktop.accounts import _validate_gdm_login_events


_GRAPHICAL_USER_SCRIPT = r"""
set -e
for runtime in $(find /run/user -mindepth 1 -maxdepth 1 -type d | sort -V -r); do
    uid=${runtime##*/}
    user=$(getent passwd "$uid" | cut -d: -f1)
    shell=$(getent passwd "$uid" | cut -d: -f7)
    [ -n "$user" ] || continue
    case "$user:$shell" in
        gdm:*|gdm-greeter:*|*:/usr/sbin/nologin|*:/bin/false) continue ;;
    esac
    [ -S "$runtime/bus" ] || continue
    find "$runtime" -maxdepth 1 -type s -name 'wayland-[0-9]*' 2>/dev/null | grep -q . || continue
    printf '%s\n' "$user"
    exit 0
done
exit 1
"""


def _graphical_user(console) -> str:
    result = console.run(_GRAPHICAL_USER_SCRIPT)
    return result.stdout.strip().splitlines()[-1]


def _graphical_user_optional(console) -> str:
    result = console.run(_GRAPHICAL_USER_SCRIPT, check=False)
    if result.returncode != 0 or not result.stdout.strip():
        return ""
    return result.stdout.strip().splitlines()[-1]
def _desktop_command(
    user: str,
    command: tuple[str, ...],
    *,
    managed: bool = False,
) -> str:
    rendered = shlex.join(command)
    quoted_user = shlex.quote(user)
    common = f"""
set -e
user={quoted_user}
uid=$(id -u "$user")
runtime=/run/user/$uid
home=$(getent passwd "$user" | cut -d: -f6)
wayland=$(find "$runtime" -maxdepth 1 -type s -name 'wayland-[0-9]*' -printf '%f\\n' 2>/dev/null | head -n1)
test -S "$runtime/bus"
test -n "$wayland"
get_atspi_address() {{
    runuser -u "$user" -- env -u AT_SPI_BUS_ADDRESS \
        HOME="$home" XDG_RUNTIME_DIR="$runtime" \
        DBUS_SESSION_BUS_ADDRESS="unix:path=$runtime/bus" \
        gdbus call --session --dest org.a11y.Bus --object-path /org/a11y/bus \
        --method org.a11y.Bus.GetAddress \
        | sed -n "s/^('\\(.*\\)',)$/\\1/p"
}}
atspi_address=$(get_atspi_address)
atspi_repaired=false
case "$atspi_address" in
    unix:path=*)
        atspi_socket=${{atspi_address#unix:path=}}
        atspi_socket=${{atspi_socket%%,*}}
        if [ ! -S "$atspi_socket" ]; then
            runuser -u "$user" -- env \
                HOME="$home" XDG_RUNTIME_DIR="$runtime" \
                DBUS_SESSION_BUS_ADDRESS="unix:path=$runtime/bus" \
                systemctl --user restart at-spi-dbus-bus.service
            atspi_address=$(get_atspi_address)
            atspi_socket=${{atspi_address#unix:path=}}
            atspi_socket=${{atspi_socket%%,*}}
            test -S "$atspi_socket"
            atspi_repaired=true
        fi
        ;;
    *)
        test -n "$atspi_address"
        ;;
esac
if [ "$atspi_repaired" = true ]; then
    session_env="HOME=$home XDG_RUNTIME_DIR=$runtime DBUS_SESSION_BUS_ADDRESS=unix:path=$runtime/bus WAYLAND_DISPLAY=$wayland DISPLAY=:0"
    runuser -u "$user" -- env $session_env \
        gnome-extensions disable ding@rastersoft.com || true
    runuser -u "$user" -- env $session_env \
        gnome-extensions enable ding@rastersoft.com
fi
"""
    environment = r"""
runuser -u "$user" -- env \
    HOME="$home" \
    XDG_RUNTIME_DIR="$runtime" \
    DBUS_SESSION_BUS_ADDRESS="unix:path=$runtime/bus" \
    AT_SPI_BUS_ADDRESS="$atspi_address" \
    WAYLAND_DISPLAY="$wayland" DISPLAY=:0 NO_AT_BRIDGE=0 \
    XDG_CURRENT_DESKTOP=GNOME XDG_SESSION_DESKTOP=gnome \
    DESKTOP_SESSION=gnome GDMSESSION=gnome"""
    if managed:
        return common + environment + f""" \
    systemd-run --user --wait --pipe --collect --quiet \
        --setenv=HOME="$home" \
        --setenv=XDG_RUNTIME_DIR="$runtime" \
        --setenv=DBUS_SESSION_BUS_ADDRESS="unix:path=$runtime/bus" \
        --setenv=AT_SPI_BUS_ADDRESS="$atspi_address" \
        --setenv=WAYLAND_DISPLAY="$wayland" --setenv=DISPLAY=:0 \
        --setenv=NO_AT_BRIDGE=0 --setenv=XDG_CURRENT_DESKTOP=GNOME \
        --setenv=XDG_SESSION_DESKTOP=gnome --setenv=DESKTOP_SESSION=gnome \
        --setenv=GDMSESSION=gnome -- {rendered}
"""
    return common + environment + f" \\\n    {rendered}\n"


@contextmanager
def _inhibit_desktop_idle(console, user: str, artifacts: Path):
    """Keep graphical checks unlocked without changing the product's lock policy."""
    unit = f"anduinos-acceptance-idle-{uuid.uuid4().hex}"
    acquire = f"""
set -eu
systemd-run --user --unit={unit} --collect \\
    --property=PartOf=graphical-session.target \\
    --property=TimeoutStopSec=5 \\
    gnome-session-inhibit --app-id={unit} \\
    --reason='Installed desktop acceptance' --inhibit=idle --inhibit-only
deadline=$((SECONDS + 30))
while :; do
    inhibitors=$(gnome-session-inhibit --list)
    if printf '%s\\n' "$inhibitors" | grep -Fq '{unit}:'; then
        break
    fi
    test "$SECONDS" -lt "$deadline"
    sleep 0.2
done
printf '%s\\n' "$inhibitors"
systemctl --user is-active {unit}
active=$(gdbus call --session --dest org.gnome.ScreenSaver \\
    --object-path /org/gnome/ScreenSaver --method org.gnome.ScreenSaver.GetActive)
printf 'ScreenSaver.GetActive=%s\\n' "$active"
test "$active" = '(false,)'
"""
    release = f"""
set -eu
systemctl --user stop {unit}
deadline=$((SECONDS + 10))
while :; do
    inhibitors=$(gnome-session-inhibit --list)
    if ! printf '%s\\n' "$inhibitors" | grep -Fq '{unit}:'; then
        break
    fi
    test "$SECONDS" -lt "$deadline"
    sleep 0.2
done
printf '%s\\n' "$inhibitors"
"""
    try:
        result = console.run(
            _desktop_command(user, ("bash", "-c", acquire)),
            timeout=45, check=False,
        )
        (artifacts / "desktop-idle-inhibitor-acquire.txt").write_text(result.stdout)
        if result.returncode:
            raise TestFailure("Could not inhibit idle in the unlocked desktop session")
        yield
    finally:
        result = console.run(
            _desktop_command(user, ("bash", "-c", release)),
            timeout=30, check=False,
        )
        (artifacts / "desktop-idle-inhibitor-release.txt").write_text(result.stdout)
        if result.returncode:
            raise TestFailure("Could not release the desktop idle inhibitor")


def _retrieve_tree(console, remote_root: str, destination: Path) -> None:
    token = uuid.uuid4().hex
    remote_archive = f"/run/anduinos-evidence-{token}.tar.gz"
    destination.parent.mkdir(parents=True, exist_ok=True)
    local_archive = destination.parent / f".{destination.name}-{token}.tar.gz"
    console.run(
        "set -euo pipefail\n"
        f"tar -C {shlex.quote(remote_root)} -czf "
        f"{shlex.quote(remote_archive)} evidence\n"
        f"test -s {shlex.quote(remote_archive)}",
        timeout=120,
    )
    try:
        console.download(remote_archive, local_archive)
        destination.mkdir(parents=True, exist_ok=True)
        with tarfile.open(local_archive, mode="r:gz") as archive:
            for member in archive.getmembers():
                path = PurePosixPath(member.name)
                if path.is_absolute() or ".." in path.parts or not member.isfile():
                    continue
                relative = (
                    Path(*path.parts[1:])
                    if path.parts[:1] == ("evidence",)
                    else Path(*path.parts)
                )
                if not relative.parts:
                    continue
                target = destination / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                source = archive.extractfile(member)
                if source is not None:
                    target.write_bytes(source.read())
    finally:
        local_archive.unlink(missing_ok=True)
        console.run(f"rm -f {shlex.quote(remote_archive)}", check=False)


def _retrieve_file(console, source: str, destination: Path) -> None:
    console.download(source, destination, missing_ok=True)


def _gdm_user_optional(console) -> str:
    probe = (
        "for user in gdm-greeter gdm; do "
        "uid=$(id -u \"$user\" 2>/dev/null) || continue; "
        "runtime=/run/user/$uid; "
        "test -S \"$runtime/bus\" || continue; "
        "find \"$runtime\" -maxdepth 1 -type s -name 'wayland-[0-9]*' "
        "2>/dev/null | grep -q . || continue; "
        "printf '%s\\n' \"$user\"; exit 0; "
        "done; exit 1"
    )
    result = console.run(probe, timeout=30, check=False)
    if result.returncode == 0 and result.stdout.strip():
        return result.stdout.strip().splitlines()[-1]
    return ""


def _authenticate_gdm_account(
    vm: QemuVm, gdm: str, remote: str, artifacts: Path,
    account: str, full_name: str, password: str, label: str, *, timeout: float,
) -> None:
    assert vm.serial is not None
    command = _desktop_command(
        gdm,
        (
            "python3",
            f"{remote}/atspi_driver.py",
            "gdm-select-user",
            "--account",
            account,
            "--full-name",
            full_name,
            "--evidence",
            f"{remote}/evidence/gdm-{label}",
        ),
    )
    result = _run_with_qmp_key_requests(
        vm,
        command,
        timeout=timeout,
        secret_texts={"gdm-password": password},
    )
    (artifacts / f"gdm-{label}-events.jsonl").write_text(
        result.stdout + "\n", encoding="utf-8"
    )
    if result.returncode != 0:
        raise TestFailure(
            f"Could not select and authenticate GDM account {account}:\n"
            + result.stdout[-8000:]
        )
    _validate_gdm_login_events(result.stdout, account, full_name)


def _login_gdm(vm: QemuVm, username: str, password: str, timeout: float) -> None:
    assert vm.qmp is not None and vm.serial is not None
    deadline = time.monotonic() + timeout
    remote = "/run/anduinos-acceptance-gdm"
    prepared = False
    submitted = False
    last_state = "unknown"
    while time.monotonic() < deadline:
        graphical_user = _graphical_user_optional(vm.serial)
        if graphical_user:
            if graphical_user != username:
                raise TestFailure(
                    "GDM opened a graphical session for unexpected user: "
                    f"{graphical_user}"
                )
            return

        last_state = vm.serial.run(
            f"loginctl show-user {shlex.quote(username)} "
            "-p State --value 2>/dev/null || true"
        ).stdout.strip() or "unknown"
        # PAM can start the user manager before GNOME creates its sockets.
        # Never send login input into a partially started desktop.
        if not submitted and last_state != "active":
            if not prepared:
                GuestUiDriver(Path(__file__).parents[2] / "assertions/guest").upload(
                    vm.serial, remote
                )
                vm.serial.run(f"install -d -m 0777 {remote}/evidence")
                prepared = True
                # Auto-login may have completed during the transfer.
                continue
            gdm = _gdm_user_optional(vm.serial)
            if gdm:
                full_name = vm.serial.run(
                    f"getent passwd {shlex.quote(username)} | cut -d: -f5 | cut -d, -f1"
                ).stdout.strip() or username
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    break
                artifacts = vm.config.artifacts / f"gdm-login-{uuid.uuid4().hex}"
                artifacts.mkdir(parents=True)
                _authenticate_gdm_account(
                    vm, gdm, remote, artifacts, username, full_name, password,
                    "login", timeout=remaining,
                )
                submitted = True
        time.sleep(1)
    raise TestFailure(
        "Could not log the test account into a ready GNOME session through "
        f"GDM; password-submitted={submitted}, loginctl-state={last_state}"
    )


def _ssh_login(
    port: int,
    username: str,
    password: str,
    *,
    should_succeed: bool,
) -> str:
    command = [
        "ssh",
        "-F",
        "/dev/null",
        "-p",
        str(port),
        "-o",
        "StrictHostKeyChecking=no",
        "-o",
        "UserKnownHostsFile=/dev/null",
        "-o",
        "PreferredAuthentications=password",
        "-o",
        "PubkeyAuthentication=no",
        "-o",
        "ConnectTimeout=15",
        "-o",
        "NumberOfPasswordPrompts=1",
        "-o",
        "ControlMaster=no",
        "-o",
        "ControlPersist=no",
        "-o",
        "ControlPath=none",
        f"{username}@127.0.0.1",
        "id -un",
    ]
    # A pipe or an inherited PTY is not necessarily ssh's controlling TTY.
    # In that situation OpenSSH does not read a password from stdin and may
    # silently fall back to askpass. Force that documented path explicitly.
    with tempfile.TemporaryDirectory(prefix="anduinos-ssh-askpass-") as directory:
        askpass = Path(directory) / "askpass"
        askpass.write_text(
            "#!/bin/sh\nprintf '%s\\n' \"$ANDUINOS_ACCEPTANCE_SSH_PASSWORD\"\n",
            encoding="utf-8",
        )
        askpass.chmod(0o700)
        environment = os.environ.copy()
        environment.update(
            {
                "DISPLAY": environment.get("DISPLAY") or ":0",
                "SSH_ASKPASS": str(askpass),
                "SSH_ASKPASS_REQUIRE": "force",
                "ANDUINOS_ACCEPTANCE_SSH_PASSWORD": password,
            }
        )
        try:
            result = subprocess.run(
                command,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                timeout=45,
                env=environment,
                check=False,
            )
            returncode = result.returncode
            text = result.stdout
        except subprocess.TimeoutExpired as error:
            returncode = 124
            text = str(error.stdout or "") + str(error.stderr or "")
    succeeded = returncode == 0 and username in text
    if succeeded != should_succeed:
        expectation = "succeed" if should_succeed else "fail"
        raise TestFailure(
            f"SSH login for {username} should {expectation}; rc={returncode}\n{text}"
        )
    return text


def _ssh_login_eventually(port: int, username: str, password: str) -> str:
    last_error: TestFailure | None = None
    for _ in range(6):
        try:
            return _ssh_login(
                port,
                username,
                password,
                should_succeed=True,
            )
        except TestFailure as error:
            last_error = error
            time.sleep(2)
    raise TestFailure("SSH did not become ready after GNOME enabled it") from last_error


def _assert_guest_ssh_stopped(console, artifacts: Path) -> None:
    result = console.run(
        r"""
set +e
for _ in $(seq 1 30); do
    if ! systemctl is-active --quiet ssh.socket \
        && ! systemctl is-active --quiet ssh.service \
        && ! ss -H -ltn 'sport = :22' | grep -q .; then
        break
    fi
    sleep 1
done
socket_enabled=$(systemctl is-enabled ssh.socket 2>/dev/null || true)
service_enabled=$(systemctl is-enabled ssh.service 2>/dev/null || true)
socket_active=$(systemctl is-active ssh.socket 2>/dev/null || true)
service_active=$(systemctl is-active ssh.service 2>/dev/null || true)
listeners=$(ss -H -ltn 'sport = :22' || true)
printf 'ssh.socket enabled=%s active=%s\n' "$socket_enabled" "$socket_active"
printf 'ssh.service enabled=%s active=%s\n' "$service_enabled" "$service_active"
printf 'listeners=%s\n' "$listeners"
test "$socket_enabled" != enabled
test "$service_enabled" != enabled
test "$socket_active" != active
test "$service_active" != active
test -z "$listeners"
""",
        timeout=45,
        check=False,
    )
    (artifacts / "installed-ssh-after-gnome-off.txt").write_text(
        result.stdout + "\n",
        encoding="utf-8",
    )
    if result.returncode != 0:
        raise TestFailure(
            "GNOME disabled its Secure Shell switch, but SSH remained enabled, "
            "active, or listening:\n" + result.stdout
        )


def _power_off(vm: QemuVm, *, unmount_esp: bool = False) -> None:
    """Flush guest filesystems and close the disposable VM through QMP."""

    assert vm.serial is not None and vm.qmp is not None
    try:
        if unmount_esp:
            # A/B tests reuse this ESP. sync + QMP quit leaves a mounted FAT
            # volume dirty, so it is not a valid healthy-ESP baseline for B.
            # Fail on unmount errors; never repair the disk to make tests pass.
            vm.serial.run("umount /boot/efi", timeout=180)
        vm.serial.run("sync", timeout=180)
        # The harness exits the Live VM through QMP instead of asking the
        # desktop session to shut down.  Flush the named target block node
        # explicitly so the next QEMU process cannot observe acknowledged
        # writes or qcow2 metadata still pending at this instrumentation
        # boundary.
        vm.qmp.flush_block_device("target")
        if getattr(vm, "live_media_attached", False):
            vm.qmp.flush_block_device("live-media")
        vm.qmp.quit()
        vm.wait(15)
    finally:
        vm.stop()


def _power_off_clean_ext4(vm: QemuVm) -> None:
    """Normally shut down the installed ext4 guest; never fsck to hide a crash."""
    assert vm.serial is not None
    try:
        deadline = time.monotonic() + 180
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TestFailure("Dracut migration kept the guest shutdown inhibited")
            result = vm.serial.run(
                'test "$(findmnt -nro FSTYPE /)" = ext4 && sync && systemctl poweroff --no-block',
                timeout=min(30, remaining), check=False,
            )
            if result.returncode == 0:
                break
            # First-boot migration may still be writing the initrd. Respect
            # its block inhibitor, and spend only the existing shutdown budget.
            if "Dracut-migration-is-writing-boot-files" not in result.stdout:
                raise TestFailure("Clean shutdown request failed:\n" + result.stdout)
            time.sleep(1)
        with vm.serial.capture_output():
            if vm.wait(max(0.1, deadline - time.monotonic())) != 0:
                raise TestFailure("QEMU failed during the installed ext4 guest's normal shutdown")
    finally:
        vm.stop()


def _status(identifier: str, message: str) -> None:
    print(f"[{identifier}] {message}", flush=True)


__all__ = tuple(name for name in globals() if not name.startswith("__"))
