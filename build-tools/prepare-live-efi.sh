#!/bin/bash
# The removable-media boot chain must work before any local MOK exists.
# Assemble the official loaders exported earlier from the target Ubuntu APT.
set -euo pipefail
image=$(realpath "$1")
loaders=$(realpath "$2")
media_label=$3
scratch=$(mktemp -d)
trap 'rm -rf "$scratch"' EXIT
printf 'search --no-floppy --label --set=anduinos_iso %s\nset prefix=($anduinos_iso)/boot/grub\nconfigfile $prefix/grub.cfg\n' \
    "$media_label" > "$scratch/grub.cfg"
mmd -i "$image" ::/EFI ::/EFI/BOOT
mcopy -i "$image" "$loaders"/* ::/EFI/BOOT/
mcopy -i "$image" "$scratch/grub.cfg" ::/EFI/BOOT/grub.cfg
