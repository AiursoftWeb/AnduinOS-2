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
    gnome-mahjongg
    gnome-mines
    gnome-sudoku
    aisleriot
    hitori
    gnome-initial-setup
    gnome-photos
    eog
    tilix
    gnome-contacts
    gnome-terminal
    zutty
    update-notifier
    update-notifier-common
    update-manager-core
    gnome-shell-extension-ubuntu-dock
    libreoffice-*
    yaru-theme-unity
    yaru-theme-icon
    yaru-theme-gtk
    ubuntu-session
    apport
    imagemagick*
    ubuntu-pro-client
    ubuntu-advantage-desktop-daemon
    ubuntu-advantage-tools
    ubuntu-pro-client-l10n
    ubuntu-release-upgrader-core
    popularity-contest
    ubuntu-report
    ubuntu-wallpaper
    apport
    snapd
    snap
    snap-store
    xterm
    software-properties-common
    software-properties-gtk
)

#whoopsie

for pkg in "${packages[@]}"; do
    if dpkg -l "$pkg" 2>/dev/null | grep -q '^ii'; then
        print_warn "Error: package '$pkg' is installed." >&2

        if [[ $EXIT_IF_UNNECESSARY_PACKAGE_FOUND -eq 1 ]]; then
            print_error "Unnecessary package found: $pkg"
            exit 1
        fi

        apt autoremove -y --purge "$pkg"
        judge "Purge package $pkg"
    fi
done
