#!/bin/bash
set -e
set -o pipefail
set -u

print_ok "Building the dedicated non-host-only Dracut Live initrd..."

for forbidden in \
    casper \
    initramfs-tools \
    initramfs-tools-core \
    initramfs-tools-bin \
    busybox-initramfs \
    finalrd; do
    if dpkg-query -W -f='${db:Status-Abbrev}' "$forbidden" 2>/dev/null \
        | grep -q '^ii '; then
        print_error "Forbidden early-boot package is installed: $forbidden"
        exit 1
    fi
done

# Resolute's dracut package deliberately ships an update-initramfs-compatible
# frontend so Debian kernel package triggers can call Dracut.  Its presence is
# valid only when Dracut owns it; the package checks above still reject the
# complete initramfs-tools stack.
dpkg-query -S /usr/sbin/update-initramfs 2>/dev/null \
    | grep -Fxq 'dracut: /usr/sbin/update-initramfs' || {
    print_error "/usr/sbin/update-initramfs is not owned by Dracut"
    exit 1
}
command -v dracut >/dev/null
command -v lsinitrd >/dev/null

kernel_version=$(find /lib/modules -mindepth 1 -maxdepth 1 -type d \
    -printf '%f\n' | sort -V | tail -n 1)
if [ -z "$kernel_version" ] || [ ! -s "/boot/vmlinuz-$kernel_version" ]; then
    print_error "No complete installed kernel was found for the Live image"
    exit 1
fi

live_initrd=/boot/anduinos-live-initrd.img
dracut \
    --force \
    --no-hostonly \
    --no-hostonly-cmdline \
    --add "dmsquash-live dmsquash-live-autooverlay overlayfs anduinos-live-layers" \
    --add-drivers "loop squashfs overlay" \
    "$live_initrd" \
    "$kernel_version"

test -s "$live_initrd"
modules=$(lsinitrd -m "$live_initrd")
for required in \
    dmsquash-live \
    dmsquash-live-autooverlay \
    overlayfs \
    anduinos-live-layers; do
    printf '%s\n' "$modules" \
        | grep -Eq "^[[:space:]]*$required[[:space:]]*$" || {
        print_error "Dedicated Live initrd is missing Dracut module: $required"
        exit 1
    }
done

listing=$(lsinitrd "$live_initrd" | awk '
    $1 ~ /^l/ && $(NF - 1) == "->" { print $(NF - 2); next }
    $1 ~ /^[bcdps-]/ { print $NF }
')
for required_member in \
    var/lib/dracut/hooks/pre-pivot/90-anduinos-live-prepare.sh \
    usr/sbin/create-overlay \
    usr/sbin/create-overlay.upstream \
    usr/sbin/dmsquash-live-root; do
    printf '%s\n' "$listing" \
        | grep -Fxq "$required_member" || {
        print_error "Dedicated Live initrd is missing runtime member: $required_member"
        exit 1
    }
done

overlay_wrapper=$(lsinitrd -f usr/sbin/create-overlay "$live_initrd")
printf '%s\n' "$overlay_wrapper" \
    | grep -Fq 'parted --script --fix "$block_device" print' || {
    print_error "Dedicated Live initrd has no AnduinOS GPT auto-overlay repair"
    exit 1
}
printf '%s\n' "$overlay_wrapper" \
    | grep -Fq 'LABEL=ANDUINOS-PERSIST' || {
    print_error "Dedicated Live initrd has the wrong persistent-overlay ABI"
    exit 1
}

judge "Build dedicated Dracut Live initrd"
