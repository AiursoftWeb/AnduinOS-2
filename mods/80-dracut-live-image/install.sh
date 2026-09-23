#!/bin/bash
set -e
set -o pipefail
set -u

print_ok "Building the dedicated non-host-only Dracut Live initrd..."

kernel_version=$(find /lib/modules -mindepth 1 -maxdepth 1 -type d \
    -printf '%f\n' | sort -V | tail -n 1)

live_initrd=/boot/anduinos-live-initrd.img
# Plymouth's UseSimpledrm default only pulls in the firmware framebuffer driver.
# Include native KMS drivers too, so GPU takeover need not wait until switch-root
# and visibly reposition the firmware logo and Plymouth watermark mid-boot.
dracut \
    --force \
    --no-hostonly \
    --no-hostonly-cmdline \
    --add "drm dmsquash-live dmsquash-live-autooverlay overlayfs anduinos-live-layers" \
    --add-drivers "loop squashfs overlay" \
    "$live_initrd" \
    "$kernel_version"

judge "Build dedicated Dracut Live initrd"
