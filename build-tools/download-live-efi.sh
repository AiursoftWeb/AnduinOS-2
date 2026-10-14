#!/bin/bash
# Download only: the target Ubuntu repositories select and authenticate the
# official removable-media loaders. Never install them into the rootfs.
set -euo pipefail
target_root=$(realpath "$1")
output=$(realpath -m "$2")
target_arch=$3
business_name=$4
case "$target_arch" in
    amd64) efi_suffix=x64; grub_platform=x86_64 ;;
    arm64) efi_suffix=aa64; grub_platform=arm64 ;;
    *) echo "Unsupported Live EFI architecture: $target_arch" >&2; exit 1 ;;
esac
scratch=$(mktemp -d "$target_root/tmp/anduinos-live-efi.XXXXXX")
trap 'rm -rf -- "$scratch"' EXIT

# Run before mods clean APT lists. Ignore addon sources: these files must come
# from the target Ubuntu release, not the build host or an AnduinOS provider.
# Download as the invoking build user, not as root inside the target.
sudo --preserve-env=HOME chroot --userspec="$(id -u):$(id -g)" "$target_root" /bin/sh -ec '
    cd "$1"
    apt-get -o Dir::Etc::sourcelist=/etc/apt/sources.list.d/ubuntu.sources \
        -o Dir::Etc::sourceparts=- download \
        "grub-efi-$2-signed:$2" "shim-signed:$2"
' sh "/${scratch#"${target_root%/}/"}" "$target_arch"

for deb in "$scratch"/*.deb; do
    dpkg-deb --extract "$deb" "$scratch/payload"
done
mkdir -p "$output"
install -m 0644 "$scratch/payload/usr/lib/grub/$grub_platform-efi-signed/gcd$efi_suffix.efi.signed" "$output/grub$efi_suffix.efi"
install -m 0644 "$scratch/payload/usr/lib/shim/shim$efi_suffix.efi.signed.latest" "$output/BOOT${efi_suffix^^}.EFI"
install -m 0644 "$scratch/payload/usr/lib/shim/mm$efi_suffix.efi" "$output/mm$efi_suffix.efi"
# Preserve the existing ARM64 media registration descriptor.
if [ "$target_arch" = arm64 ]; then
    printf 'shim%s.efi,%s,,This is the boot entry for %s\n' \
        "$efi_suffix" "$business_name" "$business_name" \
        | iconv -f UTF-8 -t UTF-16LE > "$output/BOOT${efi_suffix^^}.CSV"
fi
