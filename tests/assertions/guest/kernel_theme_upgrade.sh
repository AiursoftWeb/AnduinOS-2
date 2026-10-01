#!/bin/bash
# Real package lifecycle regression; run only in a disposable installed VM.
set -euo pipefail
test "$(id -u)" = 0
systemd-detect-virt --vm --quiet
test -z "$(dpkg --audit)"

work=$(mktemp -d /var/tmp/anduinos-kernel-theme-upgrade.XXXXXX)
cd "$work"
kernel=$(basename "$(readlink -f /boot/vmlinuz)")
kernel=${kernel#vmlinuz-}
consumers=(plymouth-anduinos)
if dpkg-query -W -f='${db:Status-Abbrev}' anduinos-btrfs-snapshots-manager 2>/dev/null | grep -q '^ii '; then
    consumers+=(anduinos-btrfs-snapshots-manager)
fi
packages=("linux-image-$kernel" "${consumers[@]}")
for package in "${packages[@]}"; do
    version=$(dpkg-query -W -f='${Version}' "$package")
    apt-get download "$package=$version"
done

# Reinstall real payloads and configure the consumers before the kernel.
# Remove the generated dependency indexes to reproduce a freshly unpacked
# kernel. This deliberate fault injection is confined to the disposable VM.
dpkg --no-triggers --unpack ./*.deb
modules="/lib/modules/$kernel"
mv "$modules/modules.dep" "$work/modules.dep.before"
rm -f "$modules/modules.dep.bin"
printf 'kernel=%s\nmodule-index-before=absent\n' "$kernel"
dpkg --no-triggers --configure "${consumers[@]}"
test ! -e "$modules/modules.dep"
dpkg-query -W -f='${Triggers-Pending}\n' dracut | grep -w update-initramfs
printf 'consumer-configuration=deferred\n'

# The official kernel hooks perform depmod and generate the initrd; dpkg
# processes the requested theme update rather than an AnduinOS boot writer.
dpkg --configure -a
test -s "$modules/modules.dep"
test -z "$(dpkg --audit)"
apt-get check
lsinitrd -m "/boot/initrd.img-$kernel" | grep -x plymouth
if [ "${#consumers[@]}" = 2 ]; then
    lsinitrd -m "/boot/initrd.img-$kernel" | grep -x anduinos-btrfs-snapshots-manager
fi
grub-script-check /boot/grub/grub.cfg
dpkg-query -S /usr/sbin/update-initramfs | grep '^dracut:'
dpkg-query -S /usr/sbin/update-grub | grep '^grub2-common:'
test -z "$(dpkg-divert --list /usr/sbin/update-initramfs)"
test -z "$(dpkg-divert --list /usr/sbin/update-grub)"
printf 'kernel-theme-transaction=passed\n'
rm -rf -- "$work"
