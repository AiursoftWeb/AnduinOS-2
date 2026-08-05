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

package_remove=$(
    # shellcheck disable=SC1091
    source "$project_root/args.sh"
    printf '%s\n' "$TARGET_PACKAGE_REMOVE"
)
printf '%s\n' "$package_remove" | grep -Eq '(^|[[:space:]])anduinos-waypoint-gtk($|[[:space:]])'
if printf '%s\n' "$package_remove" | grep -Eq 'anduinos-timeback-machine'; then
    echo "The ext4 cleanup manifest must remove Waypoint, not obsolete Timeback." >&2
    exit 1
fi
grep -Eq '^[[:space:]]*apt install -y anduinos-waypoint-gtk([[:space:]\\]|$)' \
    "$desktop_installer"
if grep -Eq 'anduinos-timeback-machine' "$desktop_installer"; then
    echo "The live image must install Waypoint, not obsolete Timeback." >&2
    exit 1
fi

echo "Build configuration tests passed."
