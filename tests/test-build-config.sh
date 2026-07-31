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

echo "Build configuration tests passed."
