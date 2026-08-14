"""In-guest acceptance assertions."""

from __future__ import annotations

from pathlib import Path

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
    if scenario.online_features:
        script = f"""
set -euo pipefail
for package in anduinos-rime anduinos-multimedia-codecs; do
    dpkg-query -W -f='${{db:Status-Abbrev}} ${{Package}} ${{Version}}\\n' "$package" | grep '^ii '
done
sources=$(runuser -u {username} -- env HOME=/home/{username} dbus-run-session -- \\
    gsettings get org.gnome.desktop.input-sources sources)
printf 'input-sources=%s\\n' "$sources"
printf '%s' "$sources" | grep -q "'ibus', 'rime'"
available_drivers=$(ubuntu-drivers list)
printf 'ubuntu-drivers-list=%s\\n' "$available_drivers"
test -z "$available_drivers"
"""
    else:
        script = "printf 'online-features=not-requested\\n'"
    _record(console, script, evidence / "installed-optional-software.txt")


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
    result = console.run(script)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(result.stdout + "\n", encoding="utf-8")
