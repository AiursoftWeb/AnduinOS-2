"""Installed-guest command, transfer, login, SSH, and shutdown helpers."""

from .shared import *  # noqa: F403


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
"""
    environment = r"""
runuser -u "$user" -- env \
    HOME="$home" \
    XDG_RUNTIME_DIR="$runtime" \
    DBUS_SESSION_BUS_ADDRESS="unix:path=$runtime/bus" \
    WAYLAND_DISPLAY="$wayland" DISPLAY=:0 NO_AT_BRIDGE=0 \
    XDG_CURRENT_DESKTOP=GNOME XDG_SESSION_DESKTOP=gnome \
    DESKTOP_SESSION=gnome GDMSESSION=gnome"""
    if managed:
        return common + environment + f""" \
    systemd-run --user --wait --pipe --collect --quiet \
        --setenv=HOME="$home" \
        --setenv=XDG_RUNTIME_DIR="$runtime" \
        --setenv=DBUS_SESSION_BUS_ADDRESS="unix:path=$runtime/bus" \
        --setenv=WAYLAND_DISPLAY="$wayland" --setenv=DISPLAY=:0 \
        --setenv=NO_AT_BRIDGE=0 --setenv=XDG_CURRENT_DESKTOP=GNOME \
        --setenv=XDG_SESSION_DESKTOP=gnome --setenv=DESKTOP_SESSION=gnome \
        --setenv=GDMSESSION=gnome -- {rendered}
"""
    return common + environment + f" \\\n    {rendered}\n"


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


def _login_gdm(vm: QemuVm, username: str, password: str, timeout: float) -> None:
    assert vm.qmp is not None and vm.serial is not None
    deadline = time.monotonic() + timeout
    for attempt in range(3):
        active = vm.serial.run(
            f"loginctl show-user {shlex.quote(username)} -p State --value 2>/dev/null || true"
        ).stdout.strip()
        if active == "active":
            return
        vm.qmp.send_key("ret")
        time.sleep(1)
        vm.qmp.type_text(password, interval=0.06)
        vm.qmp.send_key("ret")
        time.sleep(8)
        if time.monotonic() >= deadline:
            break
    raise TestFailure("Could not log the test account into GNOME through GDM")


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


def _power_off(vm: QemuVm) -> None:
    """Flush guest filesystems and close the disposable VM through QMP."""

    assert vm.serial is not None and vm.qmp is not None
    try:
        vm.serial.run("sync", timeout=30)
        # The harness exits the Live VM through QMP instead of asking the
        # desktop session to shut down.  Flush the named target block node
        # explicitly so the next QEMU process cannot observe acknowledged
        # writes or qcow2 metadata still pending at this instrumentation
        # boundary.
        vm.qmp.flush_block_device("target")
        vm.qmp.quit()
        vm.wait(15)
    finally:
        vm.stop()


def _status(identifier: str, message: str) -> None:
    print(f"[{identifier}] {message}", flush=True)


__all__ = tuple(name for name in globals() if not name.startswith("__"))
