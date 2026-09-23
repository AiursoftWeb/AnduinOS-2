#!/bin/bash
set -e
set -o pipefail
set -u

print_ok "Building the dedicated non-host-only Dracut Live initrd..."

kernel_version=$(find /lib/modules -mindepth 1 -maxdepth 1 -type d \
    -printf '%f\n' | sort -V | tail -n 1)

live_initrd=/boot/anduinos-live-initrd.img
# Plymouth's UseSimpledrm default only pulls in the firmware framebuffer driver.
# Include lightweight VM display drivers early to avoid repositioning the splash
# at switch-root. The full drm module also pulls in large physical-GPU firmware;
# leave those drivers in the Live rootfs, as before. This is only the Live initrd.
dracut \
    --force \
    --no-hostonly \
    --no-hostonly-cmdline \
    --add "dmsquash-live dmsquash-live-autooverlay overlayfs anduinos-live-layers" \
    --add-drivers "loop squashfs overlay virtio_gpu qxl bochs vmwgfx vboxvideo" \
    "$live_initrd" \
    "$kernel_version"

judge "Build dedicated Dracut Live initrd"
