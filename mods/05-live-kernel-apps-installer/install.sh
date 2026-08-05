#!/bin/bash

set -e                  # exit on error
set -o pipefail         # exit on pipeline error
set -u                  # treat unset variable as error

wait_network

print_ok "Installing Casper (live boot)..."
apt install -y \
    casper \
    discover \
    laptop-detect \
    os-prober \
    keyutils \
    --no-install-recommends
judge "Install live-boot"

print_ok "Installing kernel..."
apt install -y \
    linux-image-generic-hwe-26.04 \
    linux-headers-generic-hwe-26.04 \
    --no-install-recommends
judge "Install kernel"

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
    initramfs-tools \
    build-essential- \
    --install-recommends
judge "Install anduinos-desktop"

print_ok "Installing AnduinOS native installer..."
apt install -y anduinos-installer-beta \
    --no-install-recommends
judge "Install anduinos-installer-beta"

# Carry the Btrfs recovery UI inside the ISO without making it a desktop
# metapackage dependency. The native installer retains this package for Btrfs
# targets and purges it from ext4 targets using the Casper manifests.
print_ok "Installing conditional AnduinOS Waypoint payload..."
apt install -y anduinos-waypoint-gtk \
    --no-install-recommends
judge "Install anduinos-waypoint-gtk payload"
