#!/bin/bash

set -e                  # exit on error
set -o pipefail         # exit on pipeline error
set -u                  # treat unset variable as error

wait_network

print_ok "Installing the AnduinOS Dracut Live stack..."
apt install -y \
    dracut \
    dracut-core \
    dracut-install \
    anduinos-live-layers \
    discover \
    laptop-detect \
    os-prober \
    keyutils \
    --no-install-recommends
judge "Install live-boot"

print_ok "Installing anduinos-desktop (full AnduinOS desktop metapackage)..."
# DKMS legitimately needs gcc/make/dpkg-dev, but dpkg-dev only recommends the
# unrelated build-essential C++ stack. Keep that soft dependency out of the ISO.
apt install -y \
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
    gnome-shell-extension-desktop-icons-ng-anduinos \
    plymouth-anduinos \
    alsa-ucm-conf-anduinos \
    firmware-sof-anduinos \
    build-essential- \
    --install-recommends
judge "Install anduinos-desktop"

print_ok "Installing AnduinOS native installer..."
apt install -y anduinos-installer-beta \
    --no-install-recommends
judge "Install anduinos-installer-beta"

# Carry the Btrfs recovery UI inside the ISO without making it a desktop
# metapackage dependency. The native installer retains this package for Btrfs
# targets and purges it from ext4 targets through its explicit cleanup policy.
print_ok "Installing conditional Disk Snapshots Manager payload..."
apt install -y anduinos-btrfs-snapshots-manager \
    --no-install-recommends
judge "Install anduinos-btrfs-snapshots-manager payload"

# Carry VMware desktop integration in the amd64 Live image so VMware guests
# can resize dynamically before and after installation. The native installer
# retains it for VMware targets and purges it everywhere else.
if [ "$TARGET_ARCH" = "amd64" ]; then
    print_ok "Installing conditional VMware guest integration payload..."
    apt install -y open-vm-tools-desktop \
        --install-recommends
    judge "Install VMware guest integration payload"
fi
