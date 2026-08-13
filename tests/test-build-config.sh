#!/bin/bash

set -euo pipefail

project_root=$(cd -- "$(dirname "$0")/.." && pwd)

actual_home=$(
    HOME=/home/anduinos-builder
    export HOME
    # shellcheck disable=SC1091
    source "$project_root/args.sh"
    printf '%s\n' "$HOME"
)
test "$actual_home" = "/home/anduinos-builder"

actual_override=$(
    TARGET_ARCH=arm64
    export TARGET_ARCH
    # shellcheck disable=SC1091
    source "$project_root/args.sh"
    printf '%s\n' "$TARGET_ARCH"
)
test "$actual_override" = "arm64"

host_arch=$(dpkg --print-architecture)
case "$host_arch" in
amd64)
    expected_dependency=grub-efi-amd64
    ;;
arm64)
    expected_dependency=grub-efi-arm64
    ;;
*)
    echo "Unsupported test host architecture: $host_arch" >&2
    exit 1
    ;;
esac

make_database=$(make --directory="$project_root" -pn help)
printf '%s\n' "$make_database" |
    grep -Eq "^DEPS := .*${expected_dependency}"
printf '%s\n' "$make_database" |
    grep -Eq '^DEPS_COMMON := .*fonts-unifont'

grep -Fq -- '--size="28"' "$project_root/build.sh"
grep -Fq -- '--output="image/isolinux/anduinos-unicode-28.pf2"' \
    "$project_root/build.sh"
grep -Fq 'set gfxmode=1440x900,1280x800,1280x720,1024x768,auto' \
    "$project_root/build.sh"
grep -Fq 'set gfxpayload=auto' "$project_root/build.sh"
if grep -Fq 'set gfxpayload=keep' "$project_root/build.sh"; then
    echo "The live kernel must not inherit the GRUB menu's lower resolution." >&2
    exit 1
fi
if grep -Eq 'new_building_os/(boot/grub/fonts|etc/default/grub[.]d)' \
    "$project_root/build.sh"; then
    echo "The outer ISO builder must not deploy files owned by the installed system." >&2
    exit 1
fi
if grep -Fq 'cp /usr/share/grub/unicode.pf2' "$project_root/build.sh"; then
    echo "The ISO must use the readable AnduinOS GRUB font, not 16 px unicode.pf2." >&2
    exit 1
fi
grep -Fq '| **GNU Unifont** |' "$project_root/OSS.md"

if [ -e "$project_root/mods/79-grub-font-mod" ]; then
    echo "Installed-system GRUB policy must come from anduinos-grub-style." >&2
    exit 1
fi

main_flow=$(sed -n '/# =============   main  ================/,$p' \
    "$project_root/build.sh")
prepare_directory_line=$(printf '%s\n' "$main_flow" |
    grep -n '^prepare_iso_directory$' | cut -d: -f1)
prepare_font_line=$(printf '%s\n' "$main_flow" |
    grep -n '^prepare_live_grub_font$' | cut -d: -f1)
build_iso_line=$(printf '%s\n' "$main_flow" |
    grep -n '^build_iso$' | cut -d: -f1)
test "$prepare_directory_line" -lt "$prepare_font_line"
test "$prepare_font_line" -lt "$build_iso_line"

desktop_installer="$project_root/mods/05-live-kernel-apps-installer/install.sh"
if grep -R -Eq '^[[:space:]]*(apt[^#]*install[^#]*openssh-server|openssh-server([[:space:]\\]|$))' \
    "$project_root/mods"; then
    echo "OpenSSH Server must enter the ISO through the Live-settings dependency." >&2
    exit 1
fi
grep -A25 -F 'Installing anduinos-desktop (full AnduinOS desktop metapackage)' \
    "$desktop_installer" | grep -Fq -- '--install-recommends'
if grep -Eq 'linux-(generic|image-generic|headers-generic)-hwe-26\.04' \
    "$desktop_installer"; then
    echo "The ISO builder must obtain its HWE kernel through anduinos-core-system." >&2
    exit 1
fi
if grep -Eq '^[[:space:]]*anduinos-software-properties-gtk([[:space:]\\]|$)' \
    "$desktop_installer"; then
    echo "Deprecated anduinos-software-properties-gtk must not enter the live image." >&2
    exit 1
fi
grep -Eq '^[[:space:]]*anduinos-software-properties-common([[:space:]\\]|$)' \
    "$desktop_installer"

if (
    # shellcheck disable=SC1091
    source "$project_root/args.sh"
    declare -p TARGET_PACKAGE_REMOVE >/dev/null 2>&1
); then
    echo "The ISO builder must not own the native installer's cleanup policy." >&2
    exit 1
fi
if grep -Eq 'filesystem\.manifest-desktop|TARGET_PACKAGE_REMOVE' \
    "$project_root/build.sh"; then
    echo "The ISO must publish only filesystem.manifest." >&2
    exit 1
fi
grep -q 'image/casper/filesystem.manifest' "$project_root/build.sh"
cleanup_mod="$project_root/mods/85-cleanup-mod/install.sh"
if grep -Fq 'Live package composition did not include openssh-server' \
    "$project_root/build.sh"; then
    echo "Secure Shell package validation belongs in the final chroot mod." >&2
    exit 1
fi
grep -Fq "dpkg-query -W -f='\${Status}\\n' openssh-server" "$cleanup_mod"
grep -Fq 'install ok installed' "$cleanup_mod"
grep -Fq "dpkg-query -W -f='\${Version}' anduinos-installer-beta" "$cleanup_mod"
grep -Fq "dpkg --compare-versions \"\$installer_version\" ge '2.0.1-66'" \
    "$cleanup_mod"
grep -Fq 'Native installer cannot provision target-owned SSH host keys' \
    "$cleanup_mod"
grep -Fq 'systemctl disable ssh.service ssh.socket' "$cleanup_mod"
grep -Fq 'Live image Secure Shell state is unsafe' "$cleanup_mod"
grep -Fq "ssh_host_*_key" "$cleanup_mod"
grep -Fq "SSH host identity remains after cleanup" "$cleanup_mod"
grep -Eq '^[[:space:]]*apt install -y anduinos-btrfs-snapshots-manager([[:space:]\\]|$)' \
    "$desktop_installer"
if grep -Eq 'anduinos-timeback-machine' "$desktop_installer"; then
    echo "The live image must install Disk Snapshots Manager, not obsolete Timeback." >&2
    exit 1
fi
grep -Fq 'if [ "$TARGET_ARCH" = "amd64" ]; then' "$desktop_installer"
grep -Eq '^[[:space:]]*apt install -y open-vm-tools-desktop([[:space:]\\]|$)' \
    "$desktop_installer"
grep -A1 -E '^[[:space:]]*apt install -y open-vm-tools-desktop([[:space:]\\]|$)' \
    "$desktop_installer" | grep -Fq -- '--install-recommends'

echo "Build configuration tests passed."
