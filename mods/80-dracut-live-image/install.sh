#!/bin/bash
set -e
set -o pipefail
set -u

print_ok "Building the dedicated non-host-only Dracut Live initrd..."

kernel_version=$(find /lib/modules -mindepth 1 -maxdepth 1 -type d \
    -printf '%f\n' | sort -V | tail -n 1)

live_initrd=/boot/anduinos-live-initrd.img
dracut \
    --force \
    --no-hostonly \
    --no-hostonly-cmdline \
    --add "dmsquash-live dmsquash-live-autooverlay overlayfs anduinos-live-layers" \
    --add-drivers "loop squashfs overlay" \
    "$live_initrd" \
    "$kernel_version"

judge "Build dedicated Dracut Live initrd"
