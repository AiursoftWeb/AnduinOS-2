#!/bin/bash
# The removable-media boot chain must work before any local MOK exists.
# Fetch Canonical's signed CD GRUB as an ISO build input, never a rootfs package.
set -euo pipefail
image=$(realpath "$1")
target_root=$(realpath "$2")
media_label=$3
scratch=$(mktemp -d)
trap 'rm -rf "$scratch"' EXIT
deb="$scratch/grub.deb"
curl --fail --location --retry 3 --connect-timeout 30 \
    https://archive.ubuntu.com/ubuntu/pool/main/g/grub2-signed/grub-efi-amd64-signed_1.215+2.14-2ubuntu1_amd64.deb \
    -o "$deb"
printf '%s  %s\n' 603fe7db065634780d9576bab48fce8143a0451697c5be75a6cdb1f6a5e39188 "$deb" | sha256sum --check
dpkg-deb --extract "$deb" "$scratch/payload"
grub="$scratch/payload/usr/lib/grub/x86_64-efi-signed/gcdx64.efi.signed"
shim="$target_root/usr/lib/shim/shimx64.efi.signed.latest"
mok="$target_root/usr/lib/shim/mmx64.efi"
printf 'search --no-floppy --label --set=anduinos_iso %s\nset prefix=($anduinos_iso)/boot/grub\nconfigfile $prefix/grub.cfg\n' \
    "$media_label" > "$scratch/grub.cfg"
mmd -i "$image" ::/EFI ::/EFI/BOOT
mcopy -i "$image" "$shim" ::/EFI/BOOT/BOOTX64.EFI
mcopy -i "$image" "$grub" ::/EFI/BOOT/grubx64.efi
mcopy -i "$image" "$mok" ::/EFI/BOOT/mmx64.efi
mcopy -i "$image" "$scratch/grub.cfg" ::/EFI/BOOT/grub.cfg
