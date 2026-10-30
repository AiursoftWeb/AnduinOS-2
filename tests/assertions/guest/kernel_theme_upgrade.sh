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
# The ISO may contain a newer Ubuntu kernel than the selected mirror has
# synchronized. Try that source first, then three bounded archive fallbacks.
# This is payload preparation, not the fault under test: never change installed
# packages, the selected system sources, or version requirements to make it pass.
apt_limits=(-o Acquire::Retries=0 -o Acquire::http::Timeout=15
            -o Acquire::https::Timeout=15)
download_kernel() {
    local specification="$1" mirror
    if timeout 60 apt-get "${apt_limits[@]}" download "$specification"; then
        return 0
    fi

    . /etc/os-release
    local suite="${UBUNTU_CODENAME:?Ubuntu suite is required for archive fallback}"
    local archive=ubuntu
    local official=https://archive.ubuntu.com/ubuntu/
    if [ "$(dpkg --print-architecture)" = arm64 ]; then
        archive=ubuntu-ports
        official=https://ports.ubuntu.com/ubuntu-ports/
    fi
    local mirrors=("$official" "https://mirrors.bfsu.edu.cn/$archive/"
                   "https://mirrors.ustc.edu.cn/$archive/")
    local lists="$work/apt-lists" sources="$work/kernel.sources"
    mkdir -p "$lists/partial"
    local options=("${apt_limits[@]}"
                   -o "Dir::Etc::sourcelist=$sources"
                   -o Dir::Etc::sourceparts=-
                   -o "Dir::State::lists=$lists"
                   -o APT::Update::Error-Mode=any)
    for mirror in "${mirrors[@]}"; do
        printf 'Preparing kernel payload from %s\n' "$mirror"
        # A private index prevents mixing a stale mirror's metadata with the
        # next candidate. APT still verifies Ubuntu signatures and DEB hashes.
        rm -rf "$lists"
        mkdir -p "$lists/partial"
        cat > "$sources" <<EOF
Types: deb
URIs: $mirror
Suites: $suite $suite-updates $suite-security $suite-backports
Components: main
Signed-By: /usr/share/keyrings/ubuntu-archive-keyring.gpg
EOF
        if timeout 60 apt-get "${options[@]}" update &&
           timeout 60 apt-get "${options[@]}" download "$specification"; then
            return 0
        fi
    done
    return 1
}

for package in "${packages[@]}"; do
    version=$(dpkg-query -W -f='${Version}' "$package")
    if [[ "$package" == linux-image-* ]]; then
        download_kernel "$package=$version" && continue
    elif timeout 60 apt-get "${apt_limits[@]}" download "$package=$version"; then
        continue
    fi
    # AnduinOS payloads remain on their configured AnduinOS repository; Ubuntu
    # mirrors cannot supply them. No unpack/configure action has occurred yet.
    printf 'Payload preparation failed: %s=%s; fault injection not started.\n' \
        "$package" "$version" >&2
    exit 1
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
dpkg-query -S /usr/sbin/update-grub | grep '^anduinos-grub:'
test -z "$(dpkg-divert --list /usr/sbin/update-initramfs)"
test -z "$(dpkg-divert --list /usr/sbin/update-grub)"
printf 'kernel-theme-transaction=passed\n'
rm -rf -- "$work"
