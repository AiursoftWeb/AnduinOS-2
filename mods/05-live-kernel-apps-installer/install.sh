#!/bin/bash

set -e                  # exit on error
set -o pipefail         # exit on pipeline error
set -u                  # treat unset variable as error

wait_network

# The package lists are generated on the build host by
# gui/packages_config.py from packages.json (edited in the GTK UI's
# "软件包管理" page). This lets users choose which packages are installed
# without hand-editing this shell script. The files are copied into the
# chroot by build.sh before this mod runs.
CORE_LIST="/root/mods/core_packages.txt"
DESKTOP_LIST="/root/mods/desktop_packages.txt"

# Complete kernel configuration, depmod, and triggers before initrd consumers.
# The core metapackage selects the kernel for the target suite and architecture.
mapfile -t core_packages < "$CORE_LIST"
if (( ${#core_packages[@]} > 0 )); then
    print_ok "Installing the AnduinOS core system and kernel..."
    # Select the installed-system boot stack during rootfs assembly. The ISO
    # builder obtains its separate official signed CD GRUB outside this root.
    # build-essential- is an apt "do not install" marker: DKMS may legitimately
    # need gcc/make/dpkg-dev, but the soft build-essential C++ stack is kept out.
    apt install -y "${core_packages[@]}" build-essential- --install-recommends
    judge "Install AnduinOS core system and kernel"
else
    print_warn "No core packages selected; skipping core installation."
fi

# Carry VMware integration on both architectures; the installer applies guest cleanup.
mapfile -t desktop_packages < "$DESKTOP_LIST"
if (( ${#desktop_packages[@]} > 0 )); then
    print_ok "Installing AnduinOS Live components, desktop, and installer..."
    # The kernel is configured; resolve the remaining Live and desktop payloads together.
    # DKMS legitimately needs gcc/make/dpkg-dev, but dpkg-dev only recommends the
    # unrelated build-essential C++ stack. Keep that soft dependency out of the ISO.
    # The GRUB theme remains standalone and removable. Disk Snapshots Manager is
    # included in the Live image; the installer retains it on Btrfs and purges it
    # from ext4 targets. Neither becomes a desktop metapackage dependency here.
    # Let anduinos-gnome-extensions select DING for the target suite (GTK 3 on
    # Resolute, GTK 4 on Stonking); do not override that policy in the ISO builder.
    apt install -y "${desktop_packages[@]}" build-essential- --install-recommends
    judge "Install AnduinOS Live components, desktop, and installer"
else
    print_warn "No desktop packages selected; skipping desktop installation."
fi
