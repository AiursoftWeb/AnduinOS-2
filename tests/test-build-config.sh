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

desktop_installer="$project_root/mods/05-live-kernel-apps-installer/install.sh"
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
grep -Eq '^[[:space:]]*apt install -y anduinos-btrfs-snapshots-manager([[:space:]\\]|$)' \
    "$desktop_installer"
if grep -Eq 'anduinos-timeback-machine' "$desktop_installer"; then
    echo "The live image must install Disk Snapshots Manager, not obsolete Timeback." >&2
    exit 1
fi

echo "Build configuration tests passed."
