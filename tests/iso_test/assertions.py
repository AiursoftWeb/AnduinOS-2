"""In-guest acceptance assertions."""

from __future__ import annotations

import shlex
from pathlib import Path

from .errors import TestFailure
from .model import Architecture, Firmware, Network, Scenario, SshPolicy
from .serial import SerialConsole


LIVE_ONLY_PACKAGES = (
    "casper",
    "discover",
    "laptop-detect",
    "os-prober",
    "gparted",
    "anduinos-installer-beta",
    "anduinos-live-settings",
)


def assert_live_environment(
    console: SerialConsole,
    scenario: Scenario,
    evidence: Path,
    expected_locale: str,
    expected_timezone: str,
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
    _assert_live_region(console, expected_locale, expected_timezone, evidence)


def _assert_live_region(
    console: SerialConsole,
    expected_locale: str,
    expected_timezone: str,
    evidence: Path,
) -> None:
    script = f"""
set -euo pipefail
system_locale=$(localectl status | sed -n 's/^[[:space:]]*System Locale: LANG=//p')
timezone=$(timedatectl show -p Timezone --value)
zone_target=$(readlink -f /etc/localtime)
session_pid=$(pgrep -n -f '/usr/bin/gnome-shell' || true)
test -n "$session_pid"
session_lang=$(tr '\\0' '\\n' < "/proc/$session_pid/environ" | sed -n 's/^LANG=//p' | tail -n1)
printf 'system-locale=%s\\ntimezone=%s\\nzone-target=%s\\nsession-lang=%s\\n' \\
    "$system_locale" "$timezone" "$zone_target" "$session_lang"
test "$system_locale" = {shlex.quote(expected_locale)}
test "$timezone" = {shlex.quote(expected_timezone)}
test "$zone_target" = /usr/share/zoneinfo/{shlex.quote(expected_timezone)}
test "$session_lang" = {shlex.quote(expected_locale)}
"""
    _record(console, script, evidence / "live-locale-timezone.txt")


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
    _assert_release_contracts(console, username, evidence)
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
    else:
        script = source_probe + r"""
if curl --fail --location --silent --max-time 8 --output /dev/null "$url"; then
    echo 'Offline VM unexpectedly reached its package mirror' >&2
    exit 1
fi
carrier=$(cat /sys/class/net/e*/carrier 2>/dev/null | sort -u | tr '\n' ' ' || true)
test -z "$carrier" -o "$carrier" = "0 "
printf 'network=link-down\n'
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


def _assert_release_contracts(
    console: SerialConsole,
    username: str,
    evidence: Path,
) -> None:
    script = f"""
set -euo pipefail

# Kernel/runtime policy must be active, not merely present in a sysctl file.
inotify_instances=$(sysctl -n fs.inotify.max_user_instances)
inotify_watches=$(sysctl -n fs.inotify.max_user_watches)
inotify_events=$(sysctl -n fs.inotify.max_queued_events)
printf 'inotify-instances=%s\\n' "$inotify_instances"
printf 'inotify-watches=%s\\n' "$inotify_watches"
printf 'inotify-events=%s\\n' "$inotify_events"
test "$inotify_instances" = 524288

# Query the associations through the same freedesktop API used by desktop apps.
query_mime() {{
    runuser -u {username} -- env HOME=/home/{username} XDG_CONFIG_HOME=/home/{username}/.config \\
        XDG_CURRENT_DESKTOP=GNOME XDG_DATA_DIRS=/usr/local/share:/usr/share \\
        xdg-mime query default "$1"
}}
mime_image=$(query_mime image/png)
mime_video=$(query_mime video/mp4)
mime_deb=$(query_mime application/vnd.debian.binary-package)
mime_exe=$(query_mime application/x-msdownload)
mime_pe=$(query_mime application/vnd.microsoft.portable-executable)
printf 'image/png=%s\\n' "$mime_image"
printf 'video/mp4=%s\\n' "$mime_video"
printf 'application/vnd.debian.binary-package=%s\\n' "$mime_deb"
printf 'application/x-msdownload=%s\\n' "$mime_exe"
printf 'application/vnd.microsoft.portable-executable=%s\\n' "$mime_pe"
test "$mime_image" = org.gnome.Loupe.desktop
test "$mime_video" = io.github.celluloid_player.Celluloid.desktop
test "$mime_deb" = gnome-software-local-file-packagekit.desktop
test "$mime_exe" = com.anduinos.ExeRunner.desktop
test "$mime_pe" = com.anduinos.ExeRunner.desktop
for desktop in org.gnome.Loupe.desktop io.github.celluloid_player.Celluloid.desktop \\
    gnome-software-local-file-packagekit.desktop com.anduinos.ExeRunner.desktop; do
    test -f "/usr/share/applications/$desktop"
done

# The deliberately small non-AI `why` command is itself a product contract.
set +e
why_output=$(why 2>&1)
why_status=$?
set -e
printf 'why-exit=%s\\n%s\\n' "$why_status" "$why_output"
test "$why_status" = 1
printf '%s\\n' "$why_output" | grep -Fx 'To use the full AnduinOS AI-powered assistant, install anduinos-why-ai:'
printf '%s\\n' "$why_output" | grep -Fx '    sudo apt install anduinos-why-ai'

# Prove the installed fontconfig stack resolves both specified Chinese glyphs
# and the pistol emoji to the AnduinOS-selected font families.
chinese_font=$(fc-match -f '%{{family}}\\n' 'sans-serif:lang=zh-cn:charset=53d8 89d2 6b21 4eae 91c7 4e4b 95e8' | head -n1)
emoji_font=$(fc-match -f '%{{family}}\\n' 'emoji:charset=1f52b' | head -n1)
printf 'chinese-font=%s\\nemoji-font=%s\\n' "$chinese_font" "$emoji_font"
printf '%s' "$chinese_font" | grep -q 'Noto Sans CJK SC'
printf '%s' "$emoji_font" | grep -q 'Twemoji'
test -s /usr/share/fonts/Twemoji/twemoji-colr.ttf
grep -a -q COLR /usr/share/fonts/Twemoji/twemoji-colr.ttf
grep -a -q CPAL /usr/share/fonts/Twemoji/twemoji-colr.ttf

# The passive visual boot later proves this selected theme actually paints.
plymouth_theme=$(readlink -f /etc/alternatives/default.plymouth)
printf 'plymouth-theme=%s\\n' "$plymouth_theme"
test "$plymouth_theme" = /usr/share/plymouth/themes/anduinos/anduinos.plymouth
test -s /usr/share/plymouth/themes/anduinos/watermark.png
"""
    _record(console, script, evidence / "installed-release-contracts.txt")


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


def _record(console: SerialConsole, script: str, destination: Path) -> None:
    result = console.run(script, check=False)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(result.stdout + "\n", encoding="utf-8")
    if result.returncode != 0:
        raise TestFailure(
            f"Guest assertion {destination.name} failed with exit "
            f"{result.returncode}:\n{result.stdout[-8000:]}"
        )
