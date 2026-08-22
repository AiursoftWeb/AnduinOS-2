"""In-guest installation assertions."""

from __future__ import annotations

import re
import shlex
from pathlib import Path

from framework.errors import TestFailure
from framework.model import Architecture, Firmware, Network, Scenario, SshPolicy
from framework.serial import SerialConsole


LIVE_ONLY_PACKAGES = (
    "casper",
    "discover",
    "laptop-detect",
    "os-prober",
    "gparted",
    "anduinos-installer-beta",
    "anduinos-live-settings",
)

FORBIDDEN_IMAGE_PACKAGES = (
    # Ubuntu desktop metapackages and branding replaced by AnduinOS.
    "ubuntu-desktop",
    "ubuntu-desktop-minimal",
    "ubuntu-session",
    "yaru-theme-gnome-shell",
    "yaru-theme-unity",
    "yaru-theme-icon",
    "yaru-theme-gtk",
    "ubuntu-wallpapers",
    "ubuntu-wallpaper",
    # Snap and Ubuntu upgrade, telemetry, and reporting components.
    "snapd",
    "snap",
    "snap-store",
    "ubuntu-pro-client",
    "ubuntu-advantage-desktop-daemon",
    "ubuntu-advantage-tools",
    "ubuntu-pro-client-l10n",
    "ubuntu-release-upgrader-core",
    "ubuntu-release-upgrader-gtk",
    "update-notifier",
    "update-notifier-common",
    "update-manager",
    "update-manager-core",
    "apport",
    "popularity-contest",
    "ubuntu-report",
    "whoopsie",
    # Ubuntu extensions superseded by AnduinOS packages.
    "gnome-shell-ubuntu-extensions",
    "gnome-shell-extension-ubuntu-dock",
    "gnome-shell-extension-appindicator",
    "gnome-shell-extension-dash-to-panel",
    "gnome-shell-extension-desktop-icons-ng",
    "gnome-shell-extension-gtk4-desktop-icons-ng",
    # Retired installer stack.
    "ubiquity",
    "ubiquity-casper",
    "ubiquity-frontend-gtk",
    "ubiquity-ubuntu-artwork",
    "ubiquity-slideshow-ubuntu",
    "anduinos-installer-config",
    "anduinos-bwrap-hack",
    # Packages replaced by AnduinOS forks.
    "firefox",
    "software-properties-common",
    "software-properties-gtk",
    "firmware-sof-signed",
    "alsa-ucm-conf",
    "plymouth-theme-spinner",
    # Alternative terminals and unwanted desktop applications.
    "alacritty",
    "gnome-terminal",
    "tilix",
    "zutty",
    "xterm",
    "gnome-mahjongg",
    "gnome-mines",
    "gnome-sudoku",
    "aisleriot",
    "hitori",
    "gnome-initial-setup",
    "gnome-photos",
    "eog",
    "gnome-contacts",
    # A production image is not a native package build environment. Kernel
    # headers and the development/runtime tools explicitly owned by HWE
    # diagnostics, crash, and X11 remain intentional.
    "autoconf",
    "automake",
    "bison",
    "build-essential",
    "dkms",
    "dpkg-dev",
    "fakeroot",
    "flex",
    "gdb",
    "libcc1-0",
    "libcrypt-dev",
    "libfakeroot",
    "libtool",
    "lto-disabled-list",
    "make",
    "make-guile",
)

# Versioned compiler packages cannot be exhaustively enumerated without
# coupling the release test to one Ubuntu toolchain revision. These POSIX ERE
# fragments deliberately exclude runtime packages such as gcc-15-base,
# libgcc-s1, and libstdc++6.
FORBIDDEN_IMAGE_PACKAGE_PATTERNS = (
    r"libreoffice(-.*)?",
    r"(gcc|g\+\+)(-[0-9]+)?(-(x86-64|aarch64)-linux-gnu)?",
    r"lib(gcc|stdc\+\+)-[0-9]+-dev",
    r"lib(asan|tsan|ubsan|lsan|hwasan|itm|quadmath)[0-9]+",
)

_FORBIDDEN_IMAGE_PACKAGE_ERE = "^(" + "|".join(
    (*map(re.escape, FORBIDDEN_IMAGE_PACKAGES), *FORBIDDEN_IMAGE_PACKAGE_PATTERNS)
) + ")$"

RELEASE_CONTRACT_CHECKS = (
    "packages.installed-junk-absent",
    "system.inotify-max-user-instances",
    "terminal.ptyxis-initial-size",
    "desktop.mime-defaults",
    "command.why-placeholder",
    "font.selection-contracts",
    "boot.plymouth-theme-selection",
)


def is_forbidden_image_package(package: str) -> bool:
    """Return whether one architecture-neutral binary package is forbidden."""

    return package in FORBIDDEN_IMAGE_PACKAGES or any(
        re.fullmatch(pattern, package)
        for pattern in FORBIDDEN_IMAGE_PACKAGE_PATTERNS
    )


def assert_no_image_junk(
    console: SerialConsole,
    evidence: Path,
    scope: str,
) -> None:
    """Prove the Live or installed package database contains no build junk."""

    if scope not in {"live", "installed"}:
        raise ValueError(f"Unknown package-junk assertion scope: {scope}")
    quoted_regex = shlex.quote(_FORBIDDEN_IMAGE_PACKAGE_ERE)
    quoted_scope = shlex.quote(scope)
    script = f"""
set -euo pipefail
installed_packages=$(
    dpkg-query -W -f='${{binary:Package}}\\t${{db:Status-Abbrev}}\\n' | \
        awk '$2 == "ii" {{ sub(/:.*/, "", $1); print $1 }}' | sort -u
)
violators=$(printf '%s\\n' "$installed_packages" | \
    grep -E {quoted_regex} || true)
printf 'scope=%s\\n' {quoted_scope}
printf 'installed-package-count=%s\\n' \
    "$(printf '%s\\n' "$installed_packages" | sed '/^$/d' | wc -l)"
if test -n "$violators"; then
    printf 'Forbidden packages remain in the %s image:\\n%s\\n' \
        {quoted_scope} "$violators" >&2
    exit 1
fi
printf 'forbidden-package-count=0\\n'
"""
    identifier = (
        "packages-live-image-junk-absent"
        if scope == "live"
        else "packages-installed-junk-absent"
    )
    _record(console, script, evidence / f"{identifier}.txt")


def assert_live_environment(
    console: SerialConsole,
    scenario: Scenario,
    evidence: Path,
    expected_locale: str,
    expected_timezone: str,
    session_timeout_seconds: int = 120,
    *,
    check_region: bool = True,
) -> None:
    script = r"""
set -euo pipefail
ready=false
for _ in $(seq 1 90); do
    if systemctl is-active --quiet graphical.target && systemctl is-active --quiet gdm.service; then
        ready=true
        break
    fi
    sleep 1
done
if [ "$ready" != true ]; then
    systemctl --no-pager --full status graphical.target gdm.service || true
    exit 1
fi
systemctl is-active --quiet graphical.target
systemctl is-active --quiet gdm.service
printf 'graphical-target=active\ngdm=active\n'
if [ -d /sys/firmware/efi ]; then
    printf 'firmware=uefi\n'
else
    printf 'firmware=bios\n'
fi
systemd-detect-virt || true
ip -brief link
"""
    _record(console, script, evidence / "live-environment.txt")
    if scenario.firmware is Firmware.BIOS:
        _record(
            console,
            "test ! -d /sys/firmware/efi; echo 'legacy BIOS confirmed'",
            evidence / "live-firmware.txt",
        )
    else:
        expected = "enabled" if scenario.firmware.secure_boot else "disabled"
        _record(
            console,
            "set -e\n"
            "test -d /sys/firmware/efi\n"
            "state=$(mokutil --sb-state)\n"
            "printf '%s\\n' \"$state\"\n"
            f"printf '%s' \"$state\" | grep -qi 'SecureBoot {expected}'",
            evidence / "live-firmware.txt",
        )
    _assert_network(console, scenario.network, evidence)
    if check_region:
        assert_live_region(
            console,
            expected_locale,
            expected_timezone,
            evidence,
            session_timeout_seconds=session_timeout_seconds,
        )


def assert_live_region(
    console: SerialConsole,
    expected_locale: str,
    expected_timezone: str,
    evidence: Path,
    *,
    session_timeout_seconds: int = 120,
) -> None:
    if session_timeout_seconds < 1:
        raise ValueError("GNOME session timeout must be positive")
    script = f"""
set -uo pipefail
localectl_output=$(localectl status 2>&1)
localectl_status=$?
system_locale=$(printf '%s\\n' "$localectl_output" | sed -n 's/^[[:space:]]*System Locale: LANG=//p')
timedatectl_output=$(timedatectl show -p Timezone --value 2>&1)
timedatectl_status=$?
timezone=$timedatectl_output
zone_target=$(readlink -f /etc/localtime)
session_user=
session_uid=
session_pid=
session_lang=
session_ready=false
session_deadline=$((SECONDS + {session_timeout_seconds}))
while (( SECONDS < session_deadline )); do
    for runtime in $(find /run/user -mindepth 1 -maxdepth 1 -type d 2>/dev/null | sort -V -r); do
        uid=${{runtime##*/}}
        user=$(getent passwd "$uid" | cut -d: -f1)
        shell=$(getent passwd "$uid" | cut -d: -f7)
        test -n "$user" || continue
        case "$user:$shell" in
            gdm:*|gdm-greeter:*|*:/usr/sbin/nologin|*:/bin/false) continue ;;
        esac
        test -S "$runtime/bus" || continue
        wayland=
        for candidate in "$runtime"/wayland-[0-9]*; do
            test -S "$candidate" || continue
            wayland=${{candidate##*/}}
            break
        done
        test -n "$wayland" || continue
        pid=$(pgrep -n -u "$uid" -x gnome-shell || true)
        test -n "$pid" || continue
        test -r "/proc/$pid/environ" || continue
        lang=$(tr '\\0' '\\n' < "/proc/$pid/environ" | sed -n 's/^LANG=//p' | tail -n1)
        test -n "$lang" || continue
        session_user=$user
        session_uid=$uid
        session_pid=$pid
        session_lang=$lang
        session_ready=true
        break
    done
    test "$session_ready" = true && break
    sleep 1
done
printf 'localectl-status=%s\\ntimedatectl-status=%s\\n' \\
    "$localectl_status" "$timedatectl_status"
printf 'system-locale=%s\\ntimezone=%s\\nzone-target=%s\\n' \\
    "$system_locale" "$timezone" "$zone_target"
printf 'session-ready=%s\\nsession-user=%s\\nsession-uid=%s\\nsession-pid=%s\\nsession-lang=%s\\n' \\
    "$session_ready" "$session_user" "$session_uid" "$session_pid" "$session_lang"
printf '%s\\n' "$localectl_output" | sed 's/^/localectl-output: /'
if test "$session_ready" != true; then
    loginctl --no-pager list-sessions || true
    ps -eo user:24,pid,comm,args | grep -E 'gnome-shell|gdm' || true
    for runtime in $(find /run/user -mindepth 1 -maxdepth 1 -type d 2>/dev/null | sort -V -r); do
        uid=${{runtime##*/}}
        user=$(getent passwd "$uid" | cut -d: -f1)
        shell=$(getent passwd "$uid" | cut -d: -f7)
        printf 'candidate-runtime=%s uid=%s user=%s shell=%s\\n' \\
            "$runtime" "$uid" "$user" "$shell"
        stat -c 'candidate-bus-type=%F' "$runtime/bus" 2>&1 || true
        find "$runtime" -maxdepth 1 -name 'wayland-*' -printf 'candidate-wayland=%f type=%y\\n' 2>&1 || true
        pgrep -a -u "$uid" gnome-shell 2>&1 | sed 's/^/candidate-gnome-shell: /' || true
    done
fi
status=0
test "$localectl_status" -eq 0 || status=1
test "$timedatectl_status" -eq 0 || status=1
test "$system_locale" = {shlex.quote(expected_locale)} || status=1
test "$timezone" = {shlex.quote(expected_timezone)} || status=1
test "$zone_target" = /usr/share/zoneinfo/{shlex.quote(expected_timezone)} || status=1
test "$session_ready" = true || status=1
test "$session_lang" = {shlex.quote(expected_locale)} || status=1
exit "$status"
"""
    _record(
        console,
        script,
        evidence / "live-locale-timezone.txt",
        timeout=session_timeout_seconds + 30,
    )


def assert_installed_region(
    console: SerialConsole,
    username: str,
    expected_locale: str,
    expected_timezone: str,
    evidence: Path,
) -> None:
    """Prove both installed configuration and the real GNOME session region."""

    quoted_user = shlex.quote(username)
    quoted_locale = shlex.quote(expected_locale)
    quoted_timezone = shlex.quote(expected_timezone)
    expected_language = expected_locale.removesuffix(".UTF-8")
    language_chain = f"{expected_language}:{expected_language.partition('_')[0]}"
    script = f"""
set -uo pipefail
localectl_output=$(localectl status 2>&1)
localectl_status=$?
system_locale=$(printf '%s\n' "$localectl_output" | sed -n 's/^[[:space:]]*System Locale: LANG=//p')
timezone=$(timedatectl show -p Timezone --value 2>&1)
timedatectl_status=$?
zone_target=$(readlink -f /etc/localtime)
configured_lang=$(sh -c '. /etc/default/locale; printf %s "$LANG"')
configured_language=$(sh -c '. /etc/default/locale; printf %s "$LANGUAGE"')
uid=$(id -u {quoted_user})
session_pid=$(pgrep -n -u "$uid" -x gnome-shell || true)
session_lang=
session_language=
if test -n "$session_pid" && test -r "/proc/$session_pid/environ"; then
    session_lang=$(tr '\0' '\n' < "/proc/$session_pid/environ" | sed -n 's/^LANG=//p' | tail -n1)
    session_language=$(tr '\0' '\n' < "/proc/$session_pid/environ" | sed -n 's/^LANGUAGE=//p' | tail -n1)
fi
normalized_expected=$(printf '%s' {quoted_locale} | tr '[:upper:]' '[:lower:]' | tr -d '._-')
generated_locale=$(locale -a | while IFS= read -r candidate; do
    normalized=$(printf '%s' "$candidate" | tr '[:upper:]' '[:lower:]' | tr -d '._-')
    if test "$normalized" = "$normalized_expected"; then
        printf '%s\n' "$candidate"
        break
    fi
done)
printf 'localectl-status=%s\ntimedatectl-status=%s\n' "$localectl_status" "$timedatectl_status"
printf 'system-locale=%s\nconfigured-lang=%s\nconfigured-language=%s\n' \
    "$system_locale" "$configured_lang" "$configured_language"
printf 'timezone=%s\nzone-target=%s\ngenerated-locale=%s\n' \
    "$timezone" "$zone_target" "$generated_locale"
printf 'session-pid=%s\nsession-lang=%s\nsession-language=%s\n' \
    "$session_pid" "$session_lang" "$session_language"
printf '%s\n' "$localectl_output" | sed 's/^/localectl-output: /'
status=0
test "$localectl_status" -eq 0 || status=1
test "$timedatectl_status" -eq 0 || status=1
test "$system_locale" = {quoted_locale} || status=1
test "$configured_lang" = {quoted_locale} || status=1
test "$configured_language" = {shlex.quote(language_chain)} || status=1
test "$timezone" = {quoted_timezone} || status=1
test "$zone_target" = /usr/share/zoneinfo/{quoted_timezone} || status=1
test -n "$generated_locale" || status=1
test -n "$session_pid" || status=1
exit "$status"
"""
    _record(
        console,
        script,
        evidence / "installed-locale-timezone-session.txt",
        timeout=60,
    )


def assert_installed_environment(
    console: SerialConsole,
    scenario: Scenario,
    architecture: Architecture,
    username: str,
    expected_hostname: str,
    evidence: Path,
) -> None:
    root_type = scenario.filesystem.value
    packages = " ".join(LIVE_ONLY_PACKAGES)
    common = f"""
set -euo pipefail
ready=false
for _ in $(seq 1 90); do
    if systemctl is-active --quiet graphical.target && systemctl is-active --quiet gdm.service; then
        ready=true
        break
    fi
    sleep 1
done
test "$ready" = true
systemctl is-active --quiet graphical.target
systemctl is-active --quiet gdm.service
test "$(findmnt -n -o FSTYPE /)" = {root_type}
test "$(cat /etc/hostname)" = {expected_hostname}
test "$(hostname)" = {expected_hostname}
test -z "$(dpkg --audit)"
apt-get check
test ! -e /target
mount_targets=$(findmnt -rn -o TARGET)
if printf '%s\n' "$mount_targets" | grep -Eq '^/target($|/)|^/run/anduinos-target\\.'; then
    echo 'Installer temporary mount remains in installed system' >&2
    printf '%s\n' "$mount_targets" >&2
    exit 1
fi
grub-script-check /boot/grub/grub.cfg
! grub-editenv /boot/grub/grubenv list | grep -q '^menu_show_once='
! grub-editenv /boot/grub/grubenv list | grep -q '^recordfail='
for package in {packages}; do
    if dpkg-query -W -f='${{db:Status-Abbrev}}' "$package" 2>/dev/null | grep -q '^ii '; then
        echo "Live-only package remains: $package" >&2
        exit 1
    fi
done
dpkg-query -W -f='${{db:Status-Abbrev}}' openssh-server | grep -q '^ii '
sshd -t
test -n "$(find /etc/ssh -maxdepth 1 -type f -name 'ssh_host_*_key' -print -quit)"
for package in open-vm-tools open-vm-tools-desktop xserver-xorg-video-vmware; do
    ! dpkg-query -W -f='${{db:Status-Abbrev}}' "$package" 2>/dev/null | grep -q '^ii '
done
id {username}
printf 'root-filesystem=%s\\n' "$(findmnt -n -o FSTYPE /)"
printf 'hostname=%s\\n' "$(hostname)"
printf 'graphical-target=active\\ngdm=active\\ndpkg-audit=clean\\n'
"""
    _record(console, common, evidence / "installed-common.txt")
    _assert_boot_packages(console, architecture, evidence)
    _assert_snapshots_manager(console, scenario, evidence)
    _assert_optional_software(console, scenario, username, evidence)
    _assert_automatic_login_configuration(console, scenario, username, evidence)
    _assert_secure_boot(console, scenario, evidence)
    _assert_ssh_units(console, scenario.ssh, evidence)


def _assert_network(
    console: SerialConsole,
    network: Network,
    evidence: Path,
) -> None:
    source_probe = r"""
set -euo pipefail
source_file=$(find /etc/apt/sources.list.d -maxdepth 1 -type f -name '*.sources' -print | head -n1)
test -n "$source_file"
uri=$(awk '/^URIs:/ { print $2; exit }' "$source_file")
suite=$(awk '/^Suites:/ { print $2; exit }' "$source_file")
test -n "$uri"
test -n "$suite"
url="${uri%/}/dists/$suite/InRelease"
printf 'apt-probe=%s\n' "$url"
"""
    if network is Network.ONLINE:
        script = source_probe + r"""
curl --fail --location --silent --show-error --max-time 45 --output /dev/null "$url"
installer_endpoint=$(PYTHONPATH=/usr/lib/anduinos-installer-beta python3 - <<'PY'
from installer_core.network import _codename, probe_ubuntu_archive
from pathlib import Path

endpoint = probe_ubuntu_archive(_codename(Path('/etc/os-release')))
if endpoint is None:
    raise SystemExit(1)
print(endpoint)
PY
)
printf 'installer-network-probe=%s\n' "$installer_endpoint"
printf 'network=online\n'
"""
    elif network is Network.OFFLINE:
        script = source_probe + r"""
if curl --fail --location --silent --max-time 8 --output /dev/null "$url"; then
    echo 'Offline VM unexpectedly reached its package mirror' >&2
    exit 1
fi
carrier=$(cat /sys/class/net/e*/carrier 2>/dev/null | sort -u | tr '\n' ' ' || true)
test -z "$carrier" -o "$carrier" = "0 "
printf 'network=link-down\n'
"""
    else:
        script = source_probe + r"""
if curl --fail --location --silent --max-time 8 --output /dev/null "$url"; then
    echo 'Local-only Wi-Fi lab unexpectedly reached its package mirror' >&2
    exit 1
fi
carrier=$(cat /sys/class/net/e*/carrier 2>/dev/null | sort -u | tr '\n' ' ' || true)
test -z "$carrier" -o "$carrier" = "0 "
test -d /sys/module/mac80211_hwsim
test "$(find /sys/class/ieee80211 -mindepth 1 -maxdepth 1 | wc -l)" -eq 2
test "$(iw dev | awk '$1 == "Interface" { count++ } END { print count + 0 }')" -eq 2
test "$(iw dev | awk '$1 == "type" && $2 == "AP" { count++ } END { print count + 0 }')" -eq 1
test "$(iw dev | awk '$1 == "type" && $2 == "managed" { count++ } END { print count + 0 }')" -eq 1
if nmcli --terse --escape no --fields TYPE connection show --active | grep -Eq '^(802-11-wireless|wifi)$'; then
    echo 'Wi-Fi client connected before the installer UI supplied credentials' >&2
    exit 1
fi
printf 'network=local-wpa2-hwsim; ethernet=link-down; client=disconnected\n'
"""
    _record(console, script, evidence / "live-network.txt")


def _assert_boot_packages(
    console: SerialConsole,
    architecture: Architecture,
    evidence: Path,
) -> None:
    architecture_packages = (
        "grub-pc-bin grub-efi-amd64-bin grub-efi-amd64-signed shim-signed"
        if architecture is Architecture.AMD64
        else "grub-efi-arm64-bin grub-efi-arm64-signed shim-signed"
    )
    _record(
        console,
        "set -e\n"
        f"for package in anduinos-core-system grub-common grub2-common {architecture_packages}; do\n"
        "  dpkg-query -W -f='${db:Status-Abbrev} ${Package} ${Version}\\n' \"$package\" | grep '^ii '\n"
        "done\n"
        "kernel=$(find /boot -maxdepth 1 -type f -name 'vmlinuz-*' -printf '%f\\n' | sort -V | tail -n1)\n"
        "test -n \"$kernel\"\n"
        "version=${kernel#vmlinuz-}\n"
        "test -s \"/boot/$kernel\"\n"
        "test -s \"/boot/initrd.img-$version\"\n"
        "lsinitramfs \"/boot/initrd.img-$version\" >/dev/null\n"
        "printf 'kernel=%s\\ninitrd=%s\\n' \"$kernel\" \"initrd.img-$version\"",
        evidence / "installed-boot-packages.txt",
    )


def _assert_snapshots_manager(
    console: SerialConsole,
    scenario: Scenario,
    evidence: Path,
) -> None:
    if scenario.snapshots_manager:
        script = r"""
set -e
dpkg-query -W -f='${db:Status-Abbrev} ${Package} ${Version}\n' anduinos-btrfs-snapshots-manager | grep '^ii '
test -f /usr/share/applications/org.anduinos.BtrfsSnapshotsManager.desktop
desktop-file-validate /usr/share/applications/org.anduinos.BtrfsSnapshotsManager.desktop
"""
    else:
        script = r"""
set -e
! dpkg-query -W -f='${db:Status-Abbrev}' anduinos-btrfs-snapshots-manager 2>/dev/null | grep -q '^ii '
test ! -e /usr/share/applications/org.anduinos.BtrfsSnapshotsManager.desktop
test -z "$(apt-get --simulate autoremove | sed -n 's/^Remv /Remv /p')"
"""
    _record(console, script, evidence / "installed-snapshots-manager.txt")


def _assert_optional_software(
    console: SerialConsole,
    scenario: Scenario,
    username: str,
    evidence: Path,
) -> None:
    rime = f"""
set -euo pipefail
"""
    if scenario.rime:
        rime += f"""
dpkg-query -W -f='${{db:Status-Abbrev}} ${{Package}} ${{Version}}\\n' anduinos-rime | grep '^ii '
sources=$(runuser -u {username} -- env HOME=/home/{username} dbus-run-session -- \\
    gsettings get org.gnome.desktop.input-sources sources)
printf 'input-sources=%s\\n' "$sources"
printf '%s' "$sources" | grep -q "'ibus', 'rime'"
"""
    else:
        rime += f"""
! dpkg-query -W -f='${{db:Status-Abbrev}}' anduinos-rime 2>/dev/null | grep -q '^ii '
sources=$(runuser -u {username} -- env HOME=/home/{username} dbus-run-session -- \\
    gsettings get org.gnome.desktop.input-sources sources)
printf 'input-sources=%s\\n' "$sources"
! printf '%s' "$sources" | grep -q "'ibus', 'rime'"
"""
    if scenario.online_features:
        script = rime + r"""
dpkg-query -W -f='${db:Status-Abbrev} ${Package} ${Version}\n' anduinos-multimedia-codecs | grep '^ii '
available_drivers=$(ubuntu-drivers list)
printf 'ubuntu-drivers-list=%s\\n' "$available_drivers"
test -z "$available_drivers"
"""
    else:
        script = rime + r"""
! dpkg-query -W -f='${db:Status-Abbrev}' anduinos-multimedia-codecs 2>/dev/null | grep -q '^ii '
printf 'downloaded-online-features=not-requested\n'
"""
    _record(console, script, evidence / "installed-optional-software.txt")


def _assert_automatic_login_configuration(
    console: SerialConsole,
    scenario: Scenario,
    username: str,
    evidence: Path,
) -> None:
    expected = "true" if scenario.automatic_login else "false"
    forbidden = (
        "false" if scenario.automatic_login else f"AutomaticLogin={username}"
    )
    script = f"""
set -euo pipefail
test -f /etc/gdm3/custom.conf
grep -Fx 'AutomaticLoginEnable={expected}' /etc/gdm3/custom.conf
"""
    if scenario.automatic_login:
        script += f"grep -Fx 'AutomaticLogin={username}' /etc/gdm3/custom.conf\n"
    else:
        script += f"! grep -Fx {forbidden!r} /etc/gdm3/custom.conf\n"
    script += f"""
password_hash=$(getent shadow {username} | cut -d: -f2)
test -n "$password_hash"
case "$password_hash" in '!'|'*'|'!!') exit 1;; esac
printf 'automatic-login={expected}\\npassword-hash=present\\n'
"""
    _record(console, script, evidence / "installed-gdm-policy.txt")


def assert_passwordless_sudo_behavior(
    console: SerialConsole,
    scenario: Scenario,
    username: str,
    evidence: Path,
) -> None:
    """Prove the installer sudo choice from the installed user's boundary."""

    quoted_username = shlex.quote(username)
    quoted_home = shlex.quote(f"/home/{username}")
    expected_rule = f"{username} ALL=(ALL:ALL) NOPASSWD: ALL"
    common = f"""
set -euo pipefail
user={quoted_username}
home={quoted_home}
policy=/etc/sudoers.d/90-anduinos-passwordless-admin
state=/var/lib/anduinos-passwordless-sudo/users
test "$(id -u "$user")" -gt 0
id -nG "$user" | tr ' ' '\n' | grep -Fx sudo
test -f "$state"
test ! -L "$state"
test "$(stat -c '%U:%G:%a' "$state")" = root:root:644
visudo --check --file /etc/sudoers
runuser -u "$user" -- sudo -K
set +e
sudo_output=$(runuser -u "$user" -- env -u SUDO_ASKPASS HOME="$home" \
    sudo -n -p '' id -u 2>&1)
sudo_status=$?
set -e
printf 'passwordless-sudo-selected=%s\n' \
    {str(scenario.passwordless_sudo).lower()!r}
printf 'sudo-noninteractive-status=%s\n' "$sudo_status"
printf 'sudo-noninteractive-output=%s\n' "$sudo_output"
"""
    if scenario.passwordless_sudo:
        script = common + f"""
test -f "$policy"
test ! -L "$policy"
test "$(stat -c '%U:%G:%a' "$policy")" = root:root:440
test "$(wc -c < "$policy")" -eq {len((expected_rule + chr(10)).encode())}
grep -Fx {shlex.quote(expected_rule)} "$policy"
test "$(cat "$state")" = "$user"
test "$(wc -c < "$state")" -eq {len((username + chr(10)).encode())}
test "$sudo_status" -eq 0
test "$sudo_output" = 0
printf 'SUDO_CONTRACT_SELECTED=enabled\n'
printf 'SUDO_CONTRACT_POLICY=valid\n'
printf 'SUDO_CONTRACT_STATE={username}\n'
printf 'SUDO_CONTRACT_NONINTERACTIVE=root\n'
"""
    else:
        script = common + r"""
test ! -e "$policy"
test ! -L "$policy"
test ! -s "$state"
test "$sudo_status" -ne 0
printf 'SUDO_CONTRACT_SELECTED=disabled\n'
printf 'SUDO_CONTRACT_POLICY=absent\n'
printf 'SUDO_CONTRACT_STATE=empty\n'
printf 'SUDO_CONTRACT_NONINTERACTIVE=denied\n'
"""
    destination = evidence / "installed-sudo-policy.txt"
    _record(console, script, destination)
    _validate_passwordless_sudo_evidence(
        destination.read_text(encoding="utf-8"),
        scenario.passwordless_sudo,
        username,
    )


def _validate_passwordless_sudo_evidence(
    output: str,
    enabled: bool,
    username: str,
) -> None:
    prefix = "SUDO_CONTRACT_"
    markers: dict[str, str] = {}
    for raw_line in output.splitlines():
        line = raw_line.strip()
        if not line.startswith(prefix):
            continue
        key, separator, value = line.partition("=")
        if not separator or key in markers:
            raise TestFailure("Malformed or duplicate sudo contract marker")
        markers[key] = value
    expected = (
        {
            "SUDO_CONTRACT_SELECTED": "enabled",
            "SUDO_CONTRACT_POLICY": "valid",
            "SUDO_CONTRACT_STATE": username,
            "SUDO_CONTRACT_NONINTERACTIVE": "root",
        }
        if enabled
        else {
            "SUDO_CONTRACT_SELECTED": "disabled",
            "SUDO_CONTRACT_POLICY": "absent",
            "SUDO_CONTRACT_STATE": "empty",
            "SUDO_CONTRACT_NONINTERACTIVE": "denied",
        }
    )
    if markers != expected:
        raise TestFailure(
            "Installed sudo evidence contradicts the selected installer policy: "
            f"expected {expected!r}, observed {markers!r}"
        )


def _assert_release_contracts(
    console: SerialConsole,
    username: str,
    evidence: Path,
) -> None:
    for identifier in RELEASE_CONTRACT_CHECKS:
        assert_release_contract(console, username, evidence, identifier)


def assert_release_contract(
    console: SerialConsole,
    username: str,
    evidence: Path,
    identifier: str,
) -> None:
    """Execute one independently visible installed-system release contract."""

    if identifier == "packages.installed-junk-absent":
        assert_no_image_junk(console, evidence, "installed")
        return
    if identifier == "system.inotify-max-user-instances":
        script = r"""
set -euo pipefail
inotify_instances=$(sysctl -n fs.inotify.max_user_instances)
inotify_watches=$(sysctl -n fs.inotify.max_user_watches)
inotify_events=$(sysctl -n fs.inotify.max_queued_events)
printf 'inotify-instances=%s\n' "$inotify_instances"
printf 'inotify-watches=%s\n' "$inotify_watches"
printf 'inotify-events=%s\n' "$inotify_events"
test "$inotify_instances" = 524288
"""
    elif identifier == "terminal.ptyxis-initial-size":
        quoted_username = shlex.quote(username)
        quoted_home = shlex.quote(f"/home/{username}")
        script = f"""
set -euo pipefail
get_ptyxis_setting() {{
    runuser -u {quoted_username} -- env HOME={quoted_home} \
        XDG_CONFIG_HOME={quoted_home}/.config \
        GSETTINGS_BACKEND=dconf \
        gsettings "$@" org.gnome.Ptyxis window-size
}}
ptyxis_type=$(get_ptyxis_setting range)
ptyxis_size=$(get_ptyxis_setting get)
defaults_version=$(dpkg-query -W -f='${{Version}}' anduinos-dconf-defaults)
printf 'anduinos-dconf-defaults-version=%s\n' "$defaults_version"
printf 'ptyxis-window-size-type=%s\n' "$ptyxis_type"
printf 'ptyxis-window-size=%s\n' "$ptyxis_size"
test "$ptyxis_type" = 'type (uu)'
test "$ptyxis_size" = '(uint32 80, uint32 24)'
"""
    elif identifier == "desktop.mime-defaults":
        script = f"""
set -euo pipefail
query_mime() {{
    runuser -u {username} -- env HOME=/home/{username} XDG_CONFIG_HOME=/home/{username}/.config \
        XDG_CURRENT_DESKTOP=GNOME XDG_DATA_DIRS=/usr/local/share:/usr/share \
        xdg-mime query default "$1"
}}
mime_image=$(query_mime image/png)
mime_video=$(query_mime video/mp4)
mime_deb=$(query_mime application/vnd.debian.binary-package)
printf 'image/png=%s\n' "$mime_image"
printf 'video/mp4=%s\n' "$mime_video"
printf 'application/vnd.debian.binary-package=%s\n' "$mime_deb"
test "$mime_image" = org.gnome.Loupe.desktop
test "$mime_video" = io.github.celluloid_player.Celluloid.desktop
test "$mime_deb" = gnome-software-local-file-packagekit.desktop
for desktop in org.gnome.Loupe.desktop io.github.celluloid_player.Celluloid.desktop \
    gnome-software-local-file-packagekit.desktop; do
    test -f "/usr/share/applications/$desktop"
done
"""
    elif identifier == "command.why-placeholder":
        script = r"""
set -euo pipefail
set +e
why_output=$(why 2>&1)
why_status=$?
set -e
printf 'why-exit=%s\n%s\n' "$why_status" "$why_output"
test "$why_status" = 1
printf '%s\n' "$why_output" | grep -Fx 'To use the full AnduinOS AI-powered assistant, install anduinos-why-ai:'
printf '%s\n' "$why_output" | grep -Fx '    sudo apt install anduinos-why-ai'
"""
    elif identifier == "font.selection-contracts":
        script = r"""
set -euo pipefail
chinese_font=$(fc-match -f '%{family}\n' 'sans-serif:lang=zh-cn:charset=53d8 89d2 6b21 4eae 91c7 4e4b 95e8' | head -n1)
emoji_font=$(fc-match -f '%{family}\n' 'emoji:charset=1f52b' | head -n1)
printf 'chinese-font=%s\nemoji-font=%s\n' "$chinese_font" "$emoji_font"
printf '%s' "$chinese_font" | grep -q 'Noto Sans CJK SC'
printf '%s' "$emoji_font" | grep -q 'Twemoji'
test -s /usr/share/fonts/Twemoji/twemoji-colr.ttf
grep -a -q COLR /usr/share/fonts/Twemoji/twemoji-colr.ttf
grep -a -q CPAL /usr/share/fonts/Twemoji/twemoji-colr.ttf
"""
    elif identifier == "boot.plymouth-theme-selection":
        script = r"""
set -euo pipefail
plymouth_theme=$(readlink -f /etc/alternatives/default.plymouth)
printf 'plymouth-theme=%s\n' "$plymouth_theme"
test "$plymouth_theme" = /usr/share/plymouth/themes/anduinos/anduinos.plymouth
test -s /usr/share/plymouth/themes/anduinos/watermark.png
"""
    else:
        raise ValueError(f"Unknown release contract: {identifier}")
    filename = identifier.replace(".", "-") + ".txt"
    _record(console, script, evidence / filename)


def _assert_secure_boot(
    console: SerialConsole,
    scenario: Scenario,
    evidence: Path,
) -> None:
    if scenario.firmware is Firmware.BIOS:
        script = "test ! -d /sys/firmware/efi; echo 'firmware=bios'"
    elif scenario.firmware.secure_boot:
        script = r"""
set -e
mokutil --sb-state | tee /dev/stderr | grep -qi 'SecureBoot enabled'
test -z "$(mokutil --list-new 2>/dev/null)"
certificate=/var/lib/shim-signed/mok/MOK.der
test -s "$certificate"
expected_fingerprint=$(openssl x509 -inform DER -in "$certificate" -noout -fingerprint -sha1 | cut -d= -f2 | tr -d ':' | tr '[:lower:]' '[:upper:]')
enrolled=$(mokutil --list-enrolled)
normalized_enrolled=$(printf '%s' "$enrolled" | tr -d ':' | tr '[:lower:]' '[:upper:]')
printf '%s' "$normalized_enrolled" | grep -Fq "$expected_fingerprint"
printf '%s\n' "$enrolled"
if command -v dkms >/dev/null && [ -d /var/lib/dkms ]; then
    dkms_state=$(dkms status)
    printf '%s\n' "$dkms_state"
    if [ -n "$dkms_state" ] && printf '%s\n' "$dkms_state" | grep -Evq ':[[:space:]]+installed([[:space:]]|$)'; then
        echo 'DKMS contains a module that is not fully installed' >&2
        exit 1
    fi
fi
certificate_serial=$(openssl x509 -inform DER -in "$certificate" -noout -serial | cut -d= -f2 | tr '[:lower:]' '[:upper:]')
while IFS= read -r module; do
    test -n "$module" || continue
    module_serial=$(modinfo -F sig_key "$module" | tr -d ': ' | tr '[:lower:]' '[:upper:]')
    test "$module_serial" = "$certificate_serial"
    printf 'verified-module=%s\n' "$module"
done < <(find /lib/modules -path '*/updates/dkms/*.ko*' -type f -print)
"""
    else:
        script = r"""
set -e
mokutil --sb-state | tee /dev/stderr | grep -qi 'SecureBoot disabled'
test -z "$(mokutil --list-new 2>/dev/null)"
printf 'mok-enrollment=not-pending\n'
"""
    _record(console, script, evidence / "installed-secure-boot.txt")


def _assert_ssh_units(
    console: SerialConsole,
    policy: SshPolicy,
    evidence: Path,
) -> None:
    if policy is SshPolicy.ENABLED:
        expected = r"""
systemctl is-enabled ssh.socket | grep -qx enabled
systemctl is-active ssh.socket | grep -qx active
ss -H -ltn 'sport = :22' | grep -q .
sshd -T | grep -qx 'passwordauthentication yes'
sshd -T | grep -qx 'permitrootlogin no'
"""
    else:
        expected = r"""
! systemctl is-enabled ssh.service 2>/dev/null | grep -qx enabled
! systemctl is-enabled ssh.socket 2>/dev/null | grep -qx enabled
! ss -H -ltn 'sport = :22' | grep -q .
"""
    _record(
        console,
        "set -e\n"
        + expected
        + "sshd -T | grep -E '^(passwordauthentication|permitrootlogin) '",
        evidence / "installed-ssh.txt",
    )


def _record(
    console: SerialConsole,
    script: str,
    destination: Path,
    *,
    timeout: float | None = None,
) -> None:
    result = console.run(script, check=False, timeout=timeout)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(result.stdout + "\n", encoding="utf-8")
    if result.returncode != 0:
        raise TestFailure(
            f"Guest assertion {destination.name} failed with exit "
            f"{result.returncode}:\n{result.stdout[-8000:]}"
        )
