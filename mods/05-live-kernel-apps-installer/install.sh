#!/bin/bash

set -e                  # exit on error
set -o pipefail         # exit on pipeline error
set -u                  # treat unset variable as error

wait_network

# Complete kernel configuration, depmod, and triggers before initrd consumers.
# The core metapackage selects the kernel for the target suite and architecture.
print_ok "Installing the AnduinOS core system and kernel..."
apt install -y \
    anduinos-core-system \
    dracut \
    dracut-core \
    dracut-install \
    discover \
    laptop-detect \
    os-prober \
    keyutils \
    build-essential- \
    --install-recommends
judge "Install AnduinOS core system and kernel"

guest_packages=()
# Carry VMware integration on amd64; the installer retains it only on VMware.
if [ "$TARGET_ARCH" = "amd64" ]; then
    guest_packages+=(open-vm-tools-desktop)
fi

print_ok "Installing AnduinOS Live components, desktop, and installer..."
# The kernel is configured; resolve the remaining Live and desktop payloads together.
# DKMS legitimately needs gcc/make/dpkg-dev, but dpkg-dev only recommends the
# unrelated build-essential C++ stack. Keep that soft dependency out of the ISO.
# The GRUB theme remains standalone and removable. Disk Snapshots Manager is
# included in the Live image; the installer retains it on Btrfs and purges it
# from ext4 targets. Neither becomes a desktop metapackage dependency here.
apt install -y \
    anduinos-live-layers \
    anduinos-desktop \
    anduinos-desktop-apps \
    anduinos-gnome-extensions \
    anduinos-appstore \
    anduinos-theme \
    anduinos-wallpapers \
    anduinos-fonts \
    anduinos-no-snapd \
    anduinos-session \
    anduinos-software-properties-common \
    anduinos-system-tweaks \
    firefox-anduinos \
    gnome-shell-extension-appindicator-anduinos \
    gnome-shell-extension-dash-to-panel-anduinos \
    gnome-shell-extension-desktop-icons-ng-gtk-3-anduinos \
    plymouth-anduinos \
    alsa-ucm-conf-anduinos \
    firmware-sof-anduinos \
    anduinos-hyperfluent-grub-theme \
    anduinos-installer-beta \
    anduinos-btrfs-snapshots-manager \
    "${guest_packages[@]}" \
    build-essential- \
    --install-recommends
judge "Install AnduinOS Live components, desktop, and installer"
