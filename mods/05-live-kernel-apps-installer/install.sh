set -e                  # exit on error
set -o pipefail         # exit on pipeline error
set -u                  # treat unset variable as error

wait_network

print_ok "Installing capser (live-boot)..."
apt install $INTERACTIVE \
    casper \
    discover \
    laptop-detect \
    os-prober \
    keyutils \
    --no-install-recommends
judge "Install live-boot"

print_ok "Installing kernel..."
apt install $INTERACTIVE \
    linux-image-generic-hwe-26.04 \
    linux-headers-generic-hwe-26.04 \
    --no-install-recommends
judge "Install kernel"

print_ok "Installing anduinos-desktop (full AnduinOS desktop metapackage)..."
apt install $INTERACTIVE \
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
    anduinos-software-properties-gtk \
    anduinos-system-tweaks \
    firefox-anduinos \
    gnome-shell-extension-appindicator-anduinos \
    gnome-shell-extension-dash-to-panel-anduinos \
    gnome-shell-extension-desktop-icons-ng-anduinos \
    plymouth-anduinos \
    alsa-ucm-conf-anduinos \
    firmware-sof-anduinos \
    initramfs-tools \
    --install-recommends
judge "Install anduinos-desktop"

print_ok "Installing AnduinOS native installer..."
apt install $INTERACTIVE anduinos-installer-beta --no-install-recommends
judge "Install anduinos-installer-beta"
