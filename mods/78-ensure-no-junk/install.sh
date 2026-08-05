#!/bin/bash

set -e                  # exit on error
set -o pipefail         # exit on pipeline error
set -u                  # treat unset variable as error

# remove unused and clean up apt cache
print_ok "Removing unused packages..."
apt autoremove -y --purge
judge "Remove unused packages"

EXIT_IF_UNNECESSARY_PACKAGE_FOUND=1

print_ok "Purging unnecessary packages"
packages=(
    # ── Ubuntu desktop metapackages ────────────────────────────
    ubuntu-desktop
    ubuntu-desktop-minimal

    # ── Snap ecosystem ─────────────────────────────────────────
    snapd
    snap
    snap-store

    # ── Ubuntu session & branding ──────────────────────────────
    ubuntu-session
    yaru-theme-gnome-shell
    yaru-theme-unity
    yaru-theme-icon
    yaru-theme-gtk
    ubuntu-wallpapers
    ubuntu-wallpaper

    # ── Ubuntu Pro / upgrader / telemetry ──────────────────────
    ubuntu-pro-client
    ubuntu-advantage-desktop-daemon
    ubuntu-advantage-tools
    ubuntu-pro-client-l10n
    ubuntu-release-upgrader-core
    ubuntu-release-upgrader-gtk
    update-notifier
    update-notifier-common
    update-manager
    update-manager-core
    apport
    popularity-contest
    ubuntu-report
    whoopsie

    # ── Ubuntu GNOME extensions (AnduinOS ships own versions) ─
    gnome-shell-ubuntu-extensions
    gnome-shell-extension-ubuntu-dock
    gnome-shell-extension-appindicator
    gnome-shell-extension-dash-to-panel
    gnome-shell-extension-desktop-icons-ng
    gnome-shell-extension-gtk4-desktop-icons-ng

    # ── Retired installer stack ───────────────────────
    ubiquity
    ubiquity-casper
    ubiquity-frontend-gtk
    ubiquity-ubuntu-artwork
    ubiquity-slideshow-ubuntu
    anduinos-installer-config
    anduinos-bwrap-hack

    # ── Packages replaced by AnduinOS forks ───────────────────
    firefox
    software-properties-common
    software-properties-gtk
    firmware-sof-signed
    alsa-ucm-conf
    plymouth-theme-spinner

    # ── LibreOffice (monster package) ──────────────────────────
    libreoffice-*

    # ── Alternative terminals (AnduinOS uses Ptyxis) ──────────
    alacritty
    gnome-terminal
    tilix
    zutty
    xterm

    # ── GNOME apps / games (unwanted) ─────────────────────────
    gnome-mahjongg
    gnome-mines
    gnome-sudoku
    aisleriot
    hitori
    gnome-initial-setup
    gnome-photos
    eog
    gnome-contacts

    # ── Dev tools not needed at runtime ────────────────────────
    gdb
    build-essential
)

violators=()

for pkg in "${packages[@]}"; do
    if dpkg -l "$pkg" 2>/dev/null | grep -q '^ii'; then
        print_warn "Unwanted package found: $pkg"
        violators+=("$pkg")
        apt autoremove -y --purge "$pkg"
    fi
done

if [[ ${#violators[@]} -gt 0 && $EXIT_IF_UNNECESSARY_PACKAGE_FOUND -eq 1 ]]; then
    print_error "Build failed! The following unnecessary packages were injected: ${violators[*]}"
    exit 1
fi
