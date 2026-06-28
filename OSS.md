# AnduinOS — Third-Party Open Source Software

This document lists the open source projects that AnduinOS incorporates, derives from, or depends upon. Each entry includes the upstream project name, its primary website or repository, and the license under which it is distributed (where known).

> **Note:** License identifiers follow the [SPDX](https://spdx.org/licenses/) convention. "Various" means the project bundles components under more than one license — consult the upstream source for details.

---

## 1. Operating System Foundation

| Project | Homepage / Repository | License |
|---------|----------------------|---------|
| **Linux Kernel** | [kernel.org](https://www.kernel.org/) | GPL-2.0-only |
| **Debian** | [debian.org](https://www.debian.org/) | Various (DFSG-free) |
| **Ubuntu** | [ubuntu.com](https://ubuntu.com/) | Various (DFSG-free) |

---

## 2. Boot & Init

| Project | Homepage / Repository | License |
|---------|----------------------|---------|
| **GNU GRUB** | [gnu.org/software/grub](https://www.gnu.org/software/grub/) | GPL-3.0-or-later |
| **systemd** | [github.com/systemd/systemd](https://github.com/systemd/systemd) | LGPL-2.1-or-later |
| **dracut** | [github.com/dracutdevs/dracut](https://github.com/dracutdevs/dracut) | GPL-2.0-or-later |
| **BusyBox** | [busybox.net](https://busybox.net/) | GPL-2.0-only |
| **initramfs-tools** | [salsa.debian.org/kernel-team/initramfs-tools](https://salsa.debian.org/kernel-team/initramfs-tools) | GPL-2.0-or-later |
| **efibootmgr** | [github.com/rhboot/efibootmgr](https://github.com/rhboot/efibootmgr) | GPL-2.0-or-later |

---

## 3. Display & Graphics

| Project | Homepage / Repository | License |
|---------|----------------------|---------|
| **Wayland** | [wayland.freedesktop.org](https://wayland.freedesktop.org/) | MIT |
| **Xwayland** | [wayland.freedesktop.org/xserver.html](https://wayland.freedesktop.org/xserver.html) | MIT |
| **Mesa** | [mesa3d.org](https://www.mesa3d.org/) | MIT |
| **Plymouth** | [gitlab.freedesktop.org/plymouth/plymouth](https://gitlab.freedesktop.org/plymouth/plymouth) | GPL-2.0-or-later |
| **Vulkan Loader / Headers** | [github.com/KhronosGroup/Vulkan-Loader](https://github.com/KhronosGroup/Vulkan-Loader) | Apache-2.0 |

---

## 4. Desktop — GNOME Platform

| Project | Homepage / Repository | License |
|---------|----------------------|---------|
| **GNOME Shell** | [gitlab.gnome.org/GNOME/gnome-shell](https://gitlab.gnome.org/GNOME/gnome-shell) | GPL-2.0-or-later |
| **GNOME Control Center** | [gitlab.gnome.org/GNOME/gnome-control-center](https://gitlab.gnome.org/GNOME/gnome-control-center) | GPL-2.0-or-later |
| **GDM** (GNOME Display Manager) | [gitlab.gnome.org/GNOME/gdm](https://gitlab.gnome.org/GNOME/gdm) | GPL-2.0-or-later |
| **GNOME Session** | [gitlab.gnome.org/GNOME/gnome-session](https://gitlab.gnome.org/GNOME/gnome-session) | GPL-2.0-or-later |
| **GNOME Keyring** | [gitlab.gnome.org/GNOME/gnome-keyring](https://gitlab.gnome.org/GNOME/gnome-keyring) | GPL-2.0-or-later |
| **GNOME Remote Desktop** | [gitlab.gnome.org/GNOME/gnome-remote-desktop](https://gitlab.gnome.org/GNOME/gnome-remote-desktop) | GPL-2.0-or-later |
| **Mutter** (window manager) | [gitlab.gnome.org/GNOME/mutter](https://gitlab.gnome.org/GNOME/mutter) | GPL-2.0-or-later |
| **GTK 4** | [gtk.org](https://www.gtk.org/) | LGPL-2.1-or-later |
| **Libadwaita** | [gitlab.gnome.org/GNOME/libadwaita](https://gitlab.gnome.org/GNOME/libadwaita) | LGPL-2.1-or-later |
| **GLib** | [gitlab.gnome.org/GNOME/glib](https://gitlab.gnome.org/GNOME/glib) | LGPL-2.1-or-later |
| **Pango** | [gitlab.gnome.org/GNOME/pango](https://gitlab.gnome.org/GNOME/pango) | LGPL-2.1-or-later |
| **Cairo** | [cairographics.org](https://www.cairographics.org/) | LGPL-2.1-only / MPL-1.1 |
| **Graphene** | [ebassi.github.io/graphene](https://ebassi.github.io/graphene/) | MIT |
| **GSK** (GTK Scene Kit) | Part of GTK 4 | LGPL-2.1-or-later |
| **GDK-Pixbuf** | [gitlab.gnome.org/GNOME/gdk-pixbuf](https://gitlab.gnome.org/GNOME/gdk-pixbuf) | LGPL-2.1-or-later |
| **GObject Introspection** | [gi.readthedocs.io](https://gi.readthedocs.io/) | LGPL-2.1-or-later / GPL-2.0-or-later |
| **PyGObject** (Python GI bindings) | [gitlab.gnome.org/GNOME/pygobject](https://gitlab.gnome.org/GNOME/pygobject) | LGPL-2.1-or-later |
| **dconf** | [gitlab.gnome.org/GNOME/dconf](https://gitlab.gnome.org/GNOME/dconf) | LGPL-2.1-or-later |
| **GSettings / GIO** | Part of GLib | LGPL-2.1-or-later |

---

## 5. Desktop — GNOME Core Applications

| Application | Homepage / Repository | License |
|-------------|----------------------|---------|
| **Nautilus** (file manager) | [gitlab.gnome.org/GNOME/nautilus](https://gitlab.gnome.org/GNOME/nautilus) | GPL-3.0-or-later |
| **GNOME Text Editor** | [gitlab.gnome.org/GNOME/gnome-text-editor](https://gitlab.gnome.org/GNOME/gnome-text-editor) | GPL-3.0-or-later |
| **GNOME Calculator** | [gitlab.gnome.org/GNOME/gnome-calculator](https://gitlab.gnome.org/GNOME/gnome-calculator) | GPL-3.0-or-later |
| **GNOME Calendar** | [gitlab.gnome.org/GNOME/gnome-calendar](https://gitlab.gnome.org/GNOME/gnome-calendar) | GPL-3.0-or-later |
| **GNOME Clocks** | [gitlab.gnome.org/GNOME/gnome-clocks](https://gitlab.gnome.org/GNOME/gnome-clocks) | GPL-2.0-or-later |
| **GNOME Weather** | [gitlab.gnome.org/GNOME/gnome-weather](https://gitlab.gnome.org/GNOME/gnome-weather) | GPL-2.0-or-later |
| **GNOME Characters** | [gitlab.gnome.org/GNOME/gnome-characters](https://gitlab.gnome.org/GNOME/gnome-characters) | BSD-2-Clause |
| **GNOME Font Viewer** | [gitlab.gnome.org/GNOME/gnome-font-viewer](https://gitlab.gnome.org/GNOME/gnome-font-viewer) | GPL-2.0-or-later |
| **GNOME Logs** | [gitlab.gnome.org/GNOME/gnome-logs](https://gitlab.gnome.org/GNOME/gnome-logs) | GPL-3.0-or-later |
| **GNOME Disk Utility** | [gitlab.gnome.org/GNOME/gnome-disk-utility](https://gitlab.gnome.org/GNOME/gnome-disk-utility) | GPL-2.0-or-later |
| **Seahorse** (passwords and keys) | [gitlab.gnome.org/GNOME/seahorse](https://gitlab.gnome.org/GNOME/seahorse) | GPL-2.0-or-later |
| **Baobab** (disk usage analyzer) | [gitlab.gnome.org/GNOME/baobab](https://gitlab.gnome.org/GNOME/baobab) | GPL-2.0-or-later |
| **File Roller** (archive manager) | [gitlab.gnome.org/GNOME/file-roller](https://gitlab.gnome.org/GNOME/file-roller) | GPL-2.0-or-later |
| **GNOME Snapshot** (camera) | [gitlab.gnome.org/GNOME/snapshot](https://gitlab.gnome.org/GNOME/snapshot) | GPL-3.0-or-later |
| **GNOME System Monitor** | [gitlab.gnome.org/GNOME/gnome-system-monitor](https://gitlab.gnome.org/GNOME/gnome-system-monitor) | GPL-2.0-or-later |
| **Evince** / **Papers** (document viewer) | [gitlab.gnome.org/GNOME/evince](https://gitlab.gnome.org/GNOME/evince) | GPL-2.0-or-later |
| **Loupe** (image viewer) | [gitlab.gnome.org/GNOME/loupe](https://gitlab.gnome.org/GNOME/loupe) | GPL-3.0-or-later |
| **Eye of GNOME** (EOG) | [gitlab.gnome.org/GNOME/eog](https://gitlab.gnome.org/GNOME/eog) | GPL-2.0-or-later |
| **GNOME Software** | [gitlab.gnome.org/GNOME/gnome-software](https://gitlab.gnome.org/GNOME/gnome-software) | GPL-2.0-or-later |
| **Geary** (email) | [gitlab.gnome.org/GNOME/geary](https://gitlab.gnome.org/GNOME/geary) | LGPL-2.1-or-later |
| **GNOME Connections** | [gitlab.gnome.org/GNOME/connections](https://gitlab.gnome.org/GNOME/connections) | GPL-3.0-or-later |
| **Orca** (screen reader) | [gitlab.gnome.org/GNOME/orca](https://gitlab.gnome.org/GNOME/orca) | LGPL-2.1-or-later |

---

## 6. Desktop — Additional Applications

| Application | Homepage / Repository | License |
|-------------|----------------------|---------|
| **Mozilla Firefox** | [mozilla.org/firefox](https://www.mozilla.org/firefox/) | MPL-2.0 |
| **Celluloid** (video player) | [github.com/celluloid-player/celluloid](https://github.com/celluloid-player/celluloid) | GPL-3.0-or-later |
| **Amberol** (music player) | [gitlab.gnome.org/World/amberol](https://gitlab.gnome.org/World/amberol) | GPL-3.0-or-later |
| **Totem** (video player) | [gitlab.gnome.org/GNOME/totem](https://gitlab.gnome.org/GNOME/totem) | GPL-2.0-or-later |
| **Transmission** (BitTorrent client) | [transmissionbt.com](https://transmissionbt.com/) | GPL-2.0-only / GPL-3.0-only |
| **Remmina** (remote desktop) | [remmina.org](https://remmina.org/) | GPL-2.0-or-later |
| **Ptyxis** (terminal) | [gitlab.gnome.org/chergert/ptyxis](https://gitlab.gnome.org/chergert/ptyxis) | GPL-3.0-or-later |
| **FFmpeg** (via ffmpegthumbnailer) | [ffmpeg.org](https://ffmpeg.org/) | LGPL-2.1-or-later / GPL-2.0-or-later |
| **Flatpak** | [flatpak.org](https://flatpak.org/) | LGPL-2.1-or-later |
| **Flathub** | [flathub.org](https://flathub.org/) | Various |

---

## 7. Audio

| Project | Homepage / Repository | License |
|---------|----------------------|---------|
| **PipeWire** | [pipewire.org](https://pipewire.org/) | MIT |
| **WirePlumber** | [pipewire.pages.freedesktop.org/wireplumber](https://pipewire.pages.freedesktop.org/wireplumber/) | MIT |
| **ALSA** | [alsa-project.org](https://alsa-project.org/) | GPL-2.0-or-later / LGPL-2.1-or-later |
| **ALSA UCM Conf** | [github.com/alsa-project/alsa-ucm-conf](https://github.com/alsa-project/alsa-ucm-conf) | BSD-3-Clause |
| **Sound Open Firmware (SOF)** | [github.com/thesofproject/sof-bin](https://github.com/thesofproject/sof-bin) | BSD-3-Clause / MIT |
| **GStreamer** | [gstreamer.freedesktop.org](https://gstreamer.freedesktop.org/) | LGPL-2.1-or-later |
| **espeak-ng** | [github.com/espeak-ng/espeak-ng](https://github.com/espeak-ng/espeak-ng) | GPL-3.0-or-later |
| **Speech Dispatcher** | [github.com/brailcom/speechd](https://github.com/brailcom/speechd) | GPL-2.0-or-later |

---

## 8. Networking

| Project | Homepage / Repository | License |
|---------|----------------------|---------|
| **NetworkManager** | [networkmanager.dev](https://networkmanager.dev/) | GPL-2.0-or-later / LGPL-2.1-or-later |
| **ModemManager** | [freedesktop.org/wiki/Software/ModemManager](https://www.freedesktop.org/wiki/Software/ModemManager/) | GPL-2.0-or-later / LGPL-2.1-or-later |
| **wpa_supplicant** | [w1.fi/wpa_supplicant](https://w1.fi/wpa_supplicant/) | BSD-3-Clause |
| **OpenVPN** | [openvpn.net](https://openvpn.net/) | GPL-2.0-only |
| **dhcpcd** | [github.com/NetworkConfiguration/dhcpcd](https://github.com/NetworkConfiguration/dhcpcd) | BSD-2-Clause |
| **Dnsmasq** | [thekelleys.org.uk/dnsmasq](https://thekelleys.org.uk/dnsmasq/doc.html) | GPL-2.0-or-later / GPL-3.0-or-later |
| **UFW** (Uncomplicated Firewall) | [launchpad.net/ufw](https://launchpad.net/ufw) | GPL-3.0-only |
| **iptables** | [netfilter.org](https://netfilter.org/) | GPL-2.0-or-later |
| **nftables** | [netfilter.org](https://netfilter.org/) | GPL-2.0-only |
| **iproute2** | [wiki.linuxfoundation.org/networking/iproute2](https://wiki.linuxfoundation.org/networking/iproute2) | GPL-2.0-or-later |

---

## 9. Security

| Project | Homepage / Repository | License |
|---------|----------------------|---------|
| **AppArmor** | [gitlab.com/apparmor/apparmor](https://gitlab.com/apparmor/apparmor) | GPL-2.0-only / LGPL-2.1-or-later |
| **OpenSSH** | [openssh.com](https://www.openssh.com/) | BSD-2-Clause |
| **sudo** | [sudo.ws](https://www.sudo.ws/) | ISC |
| **Mozilla CA Certificates** | [wiki.mozilla.org/CA](https://wiki.mozilla.org/CA) | MPL-2.0 |
| **Linux PAM** | [github.com/linux-pam/linux-pam](https://github.com/linux-pam/linux-pam) | BSD-3-Clause / GPL-2.0-or-later |
| **Polkit** | [gitlab.freedesktop.org/polkit/polkit](https://gitlab.freedesktop.org/polkit/polkit) | LGPL-2.0-or-later |

---

## 10. Input Methods

| Project | Homepage / Repository | License |
|---------|----------------------|---------|
| **IBus** | [github.com/ibus/ibus](https://github.com/ibus/ibus) | GPL-2.0-or-later / LGPL-2.1-or-later |
| **librime** (Rime input method engine) | [rime.im](https://rime.im/) | BSD-3-Clause |
| **rime-ice** (input schema) | [github.com/iDvel/rime-ice](https://github.com/iDvel/rime-ice) | GPL-3.0-only |

---

## 11. Themes

__Please note__: AnduinOS team is **Sponsoring** `vinceliuice` for his great work on the themes and icons used in AnduinOS.

| Project | Homepage / Repository | License |
|---------|----------------------|---------|
| **Fluent GTK Theme** | [github.com/vinceliuice/Fluent-gtk-theme](https://github.com/vinceliuice/Fluent-gtk-theme) | GPL-3.0-only |
| **Fluent Icon Theme** | [github.com/vinceliuice/Fluent-icon-theme](https://github.com/vinceliuice/Fluent-icon-theme) | GPL-3.0-only |
| **GNOME Extensions CLI** (`lib/resolve-gnome-ext.py`) | [github.com/essembeh/gnome-extensions-cli](https://github.com/essembeh/gnome-extensions-cli) | MIT |

---

## 12. GNOME Shell Extensions

All extensions are fetched from [extensions.gnome.org](https://extensions.gnome.org/) at build time and are distributed under GPL-2.0-or-later (the required license for GNOME Shell extensions).

| Extension | UUID | Upstream Repository |
|-----------|------|---------------------|
| **Arc Menu** | `arcmenu@arcmenu.com` | [github.com/fishears/Arc-Menu](https://github.com/fishears/Arc-Menu) |
| **Blur My Shell** | `blur-my-shell@aunetx` | [github.com/aunetx/blur-my-shell](https://github.com/aunetx/blur-my-shell) |
| **Dash to Panel** | `dash-to-panel@jderose9.github.com` | [github.com/home-sweet-gnome/dash-to-panel](https://github.com/home-sweet-gnome/dash-to-panel) |
| **Desktop Icons NG (DING)** | `ding@rastersoft.com` | [gitlab.com/rastersoft/desktop-icons-ng](https://gitlab.com/rastersoft/desktop-icons-ng) |
| **Clipboard Indicator** | `clipboard-indicator@tudmotu.com` | [github.com/Tudmotu/gnome-shell-extension-clipboard-indicator](https://github.com/Tudmotu/gnome-shell-extension-clipboard-indicator) |
| **Customize IBus** | `customize-ibus@hollowman.ml` | [github.com/openSUSE/Customize-IBus](https://github.com/openSUSE/Customize-IBus) |
| **Lock Keys** | `lockkeys@vaina.lt` | [github.com/kazysmaster/gnome-shell-extension-lockkeys](https://github.com/kazysmaster/gnome-shell-extension-lockkeys) |
| **Network Stats** | `network-stats@gnome.noroadsleft.xyz` | [github.com/noroadsleft000/gnome-network-stats](https://github.com/noroadsleft000/gnome-network-stats) |
| **Proxy Switcher** | `ProxySwitcher@flannaghan.com` | [github.com/tomflannaghan/proxy-switcher](https://github.com/tomflannaghan/proxy-switcher) |
| **Simple Weather** | `simple-weather@romanlefler.com` | [github.com/romanlefler/SimpleWeather](https://github.com/romanlefler/SimpleWeather) |
| **Tiling Assistant** | `tiling-assistant@leleat-on-github` | [github.com/Leleat/Tiling-Assistant](https://github.com/Leleat/Tiling-Assistant) |
| **Media Controls** | `mediacontrols@cliffniff.github.com` | [github.com/cliffniff/mediacontrols](https://github.com/cliffniff/mediacontrols) |
| **AppIndicator** | `appindicatorsupport@rgcjonas.gmail.com` | [github.com/ubuntu/gnome-shell-extension-appindicator](https://github.com/ubuntu/gnome-shell-extension-appindicator) |
| **Accent GTK Theme** | `accent-gtk-theme@brgvos` | Fork of [taiwbi/gnome-accent-directories](https://github.com/taiwbi/gnome-accent-directories) |
| **Accent Icons Theme** | `accent-icons-theme@brgvos` | Fork of [taiwbi/gnome-accent-directories](https://github.com/taiwbi/gnome-accent-directories) |
| **Accent User Theme** | `accent-user-theme@brgvos` | Fork of [taiwbi/gnome-accent-directories](https://github.com/taiwbi/gnome-accent-directories) |
| **User Theme** | `user-theme@gnome-shell-extensions.gcampax.github.com` | Part of GNOME Shell Extensions |
| **Drive Menu** | `drive-menu@gnome-shell-extensions.gcampax.github.com` | Part of GNOME Shell Extensions |

---

## 13. Fonts

| Font | Homepage / Repository | License |
|------|----------------------|---------|
| **Cascadia Code** | [github.com/microsoft/cascadia-code](https://github.com/microsoft/cascadia-code) | SIL OFL-1.1 |
| **Nerd Fonts Symbols** | [github.com/ryanoasis/nerd-fonts](https://github.com/ryanoasis/nerd-fonts) | MIT |
| **Noto Sans** | [github.com/notofonts/latin-greek-cyrillic](https://github.com/notofonts/latin-greek-cyrillic) | SIL OFL-1.1 |
| **Noto Serif** | [github.com/notofonts/latin-greek-cyrillic](https://github.com/notofonts/latin-greek-cyrillic) | SIL OFL-1.1 |
| **Noto Sans CJK** | [github.com/notofonts/noto-cjk](https://github.com/notofonts/noto-cjk) | SIL OFL-1.1 |
| **Noto Color Emoji** | [github.com/googlefonts/noto-emoji](https://github.com/googlefonts/noto-emoji) | SIL OFL-1.1 / Apache-2.0 |
| **Twemoji COLRv1** | [github.com/TCOTC/twemoji-colr](https://github.com/TCOTC/twemoji-colr) (derived from [jdecked/twemoji](https://github.com/jdecked/twemoji)) | CC-BY-4.0 |

---

## 14. Printing & Scanning

| Project | Homepage / Repository | License |
|---------|----------------------|---------|
| **CUPS** | [openprinting.github.io/cups](https://openprinting.github.io/cups/) | Apache-2.0 |
| **SANE** | [sane-project.org](http://www.sane-project.org/) | GPL-2.0-or-later |
| **IPP-USB** | [github.com/OpenPrinting/ipp-usb](https://github.com/OpenPrinting/ipp-usb) | BSD-2-Clause |

---

## 15. Firmware & Hardware Support

| Project | Homepage / Repository | License |
|---------|----------------------|---------|
| **fwupd** / **LVFS** | [fwupd.org](https://fwupd.org/) | LGPL-2.1-or-later |
| **UPower** | [upower.freedesktop.org](https://upower.freedesktop.org/) | GPL-2.0-or-later |
| **Bolt** (Thunderbolt) | [gitlab.freedesktop.org/bolt/bolt](https://gitlab.freedesktop.org/bolt/bolt) | GPL-2.0-or-later |
| **iio-sensor-proxy** | [gitlab.freedesktop.org/hadess/iio-sensor-proxy](https://gitlab.freedesktop.org/hadess/iio-sensor-proxy) | GPL-2.0-or-later |
| **fprintd** (fingerprint authentication) | [fprint.freedesktop.org](https://fprint.freedesktop.org/) | GPL-2.0-or-later |
| **smartmontools** | [smartmontools.org](https://www.smartmontools.org/) | GPL-2.0-or-later |
| **pciutils** | [github.com/pciutils/pciutils](https://github.com/pciutils/pciutils) | GPL-2.0-or-later |
| **usbutils** | [github.com/gregkh/usbutils](https://github.com/gregkh/usbutils) | GPL-2.0-or-later |
| **ethtool** | [kernel.org/pub/software/network/ethtool](https://www.kernel.org/pub/software/network/ethtool/) | GPL-2.0-only |
| **lshw** | [ezix.org/project/wiki/HardwareLiSter](https://ezix.org/project/wiki/HardwareLiSter) | GPL-2.0-only |
| **mdadm** | [raid.wiki.kernel.org](https://raid.wiki.kernel.org/index.php/A_guide_to_mdadm) | GPL-2.0-or-later |

---

## 16. GNU & Userspace Tools

| Project | Homepage / Repository | License |
|---------|----------------------|---------|
| **GNU Coreutils** | [gnu.org/software/coreutils](https://www.gnu.org/software/coreutils/) | GPL-3.0-or-later |
| **GNU Bash** | [gnu.org/software/bash](https://www.gnu.org/software/bash/) | GPL-3.0-or-later |
| **GNU Tar** | [gnu.org/software/tar](https://www.gnu.org/software/tar/) | GPL-3.0-or-later |
| **GNU Wget** | [gnu.org/software/wget](https://www.gnu.org/software/wget/) | GPL-3.0-or-later |
| **GNU Nano** | [nano-editor.org](https://nano-editor.org/) | GPL-3.0-or-later |
| **Vim** | [vim.org](https://www.vim.org/) | Vim |
| **curl** | [curl.se](https://curl.se/) | curl |
| **rsync** | [rsync.samba.org](https://rsync.samba.org/) | GPL-3.0-or-later |
| **zstd** | [github.com/facebook/zstd](https://github.com/facebook/zstd) | BSD-3-Clause |
| **xz-utils** | [tukaani.org/xz](https://tukaani.org/xz/) | Public Domain / LGPL-2.1-or-later |
| **procps-ng** | [gitlab.com/procps-ng/procps](https://gitlab.com/procps-ng/procps) | GPL-2.0-or-later |
| **psmisc** | [gitlab.com/psmisc/psmisc](https://gitlab.com/psmisc/psmisc) | GPL-2.0-or-later |
| **lsof** | [github.com/lsof-org/lsof](https://github.com/lsof-org/lsof) | BSD-4-Clause |
| **file** | [darwinsys.com/file](https://www.darwinsys.com/file/) | BSD-2-Clause |
| **kmod** | [git.kernel.org/pub/scm/utils/kernel/kmod](https://git.kernel.org/pub/scm/utils/kernel/kmod/) | GPL-2.0-or-later |
| **iputils** | [github.com/iputils/iputils](https://github.com/iputils/iputils) | BSD-3-Clause / GPL-2.0-or-later |
| **cron** (cronie) | [github.com/cronie-crond/cronie](https://github.com/cronie-crond/cronie) | ISC |
| **logrotate** | [github.com/logrotate/logrotate](https://github.com/logrotate/logrotate) | GPL-2.0-or-later |
| **D-Bus** | [freedesktop.org/wiki/Software/dbus](https://www.freedesktop.org/wiki/Software/dbus/) | AFL-2.1 / GPL-2.0-or-later |
| **xdg-desktop-portal** | [github.com/flatpak/xdg-desktop-portal](https://github.com/flatpak/xdg-desktop-portal) | LGPL-2.1-or-later |
| **xdg-desktop-portal-gnome** | [gitlab.gnome.org/GNOME/xdg-desktop-portal-gnome](https://gitlab.gnome.org/GNOME/xdg-desktop-portal-gnome) | LGPL-2.1-or-later |
| **xdg-desktop-portal-gtk** | [github.com/flatpak/xdg-desktop-portal-gtk](https://github.com/flatpak/xdg-desktop-portal-gtk) | LGPL-2.1-or-later |
| **GNU gettext** | [gnu.org/software/gettext](https://www.gnu.org/software/gettext/) | GPL-3.0-or-later |
| **libfuse** | [github.com/libfuse/libfuse](https://github.com/libfuse/libfuse) | GPL-2.0-only / LGPL-2.0-only |

---

## 17. Rust Crate Dependencies (anduinos-ufwall-gtk)

The `anduinos-ufwall-gtk` firewall configuration tool is original AnduinOS code, but it compiles against the following third-party Rust crates from [crates.io](https://crates.io/).

### Direct Dependencies

| Crate | Repository | License |
|-------|-----------|---------|
| **gtk4** | [github.com/gtk-rs/gtk4-rs](https://github.com/gtk-rs/gtk4-rs) | MIT |
| **libadwaita** | [github.com/gtk-rs/gtk4-rs](https://github.com/gtk-rs/gtk4-rs) | MIT |
| **gettext-rs** | [github.com/gtk-rs/gettext-rs](https://github.com/gtk-rs/gettext-rs) | MIT |
| **tokio** | [github.com/tokio-rs/tokio](https://github.com/tokio-rs/tokio) | MIT |
| **notify** | [github.com/notify-rs/notify](https://github.com/notify-rs/notify) | CC0-1.0 |
| **async-channel** | [github.com/smol-rs/async-channel](https://github.com/smol-rs/async-channel) | Apache-2.0 / MIT |

### Transitive Dependencies (70+ crates)

| Crate | License |
|-------|---------|
| aho-corasick | MIT / Unlicense |
| autocfg | Apache-2.0 / MIT |
| bitflags | MIT / Apache-2.0 |
| block | MIT |
| cairo-rs / cairo-sys-rs | MIT |
| cc | MIT / Apache-2.0 |
| cfg-expr | MIT / Apache-2.0 |
| cfg-if | MIT / Apache-2.0 |
| concurrent-queue | Apache-2.0 / MIT |
| crossbeam-utils | MIT / Apache-2.0 |
| equivalent | Apache-2.0 / MIT |
| event-listener / event-listener-strategy | Apache-2.0 / MIT |
| field-offset | MIT / Apache-2.0 |
| filetime | MIT / Apache-2.0 |
| fsevent-sys | MIT |
| futures-channel / futures-core / futures-executor / futures-io / futures-macro / futures-task / futures-util | MIT / Apache-2.0 |
| gdk-pixbuf / gdk-pixbuf-sys | MIT |
| gdk4 / gdk4-sys | MIT |
| gettext-sys | MIT |
| gio / gio-sys | MIT |
| glib / glib-macros / glib-sys | MIT |
| gobject-sys | MIT |
| graphene-rs / graphene-sys | MIT |
| gsk4 / gsk4-sys | MIT |
| gtk4-macros / gtk4-sys | MIT |
| hashbrown | MIT / Apache-2.0 |
| heck | MIT / Apache-2.0 |
| indexmap | Apache-2.0 / MIT |
| inotify / inotify-sys | ISC |
| instant | BSD-3-Clause |
| kqueue / kqueue-sys | MIT |
| lazy_static | MIT / Apache-2.0 |
| libadwaita-sys | MIT |
| libc | MIT / Apache-2.0 |
| locale_config | MIT |
| log | MIT / Apache-2.0 |
| malloc_buf | MIT / Apache-2.0 |
| memchr | MIT / Unlicense |
| memoffset | MIT |
| mio | MIT |
| notify-types | MIT / Apache-2.0 |
| objc / objc-foundation / objc_id | MIT |
| pango / pango-sys | MIT |
| parking | Apache-2.0 / MIT |
| pin-project-lite | Apache-2.0 / MIT |
| pkg-config | MIT / Apache-2.0 |
| proc-macro-crate | MIT / Apache-2.0 |
| proc-macro2 | MIT / Apache-2.0 |
| quote | MIT / Apache-2.0 |
| regex / regex-automata / regex-syntax | MIT / Apache-2.0 |
| rustc_version | MIT / Apache-2.0 |
| same-file | MIT / Unlicense |
| semver | MIT / Apache-2.0 |
| serde / serde_derive / serde_spanned | MIT / Apache-2.0 |
| shlex | MIT / Apache-2.0 |
| slab | MIT |
| smallvec | MIT / Apache-2.0 |
| syn | MIT / Apache-2.0 |
| system-deps | MIT / Apache-2.0 |
| target-lexicon | Apache-2.0 |
| temp-dir | MIT / Apache-2.0 |
| tokio-macros | MIT |
| toml / toml_datetime / toml_edit / toml_parser / toml_writer | MIT / Apache-2.0 |
| unicode-ident | MIT / Apache-2.0 / Unicode-3.0 |
| version-compare | MIT |
| walkdir | MIT / Unlicense |
| winapi / winapi-i686-pc-windows-gnu / winapi-util / winapi-x86_64-pc-windows-gnu | MIT / Apache-2.0 |
| windows-link | MIT / Apache-2.0 |
| windows-sys / windows-targets / windows_*_* | MIT / Apache-2.0 |
| winnow | MIT |

---

## 18. Build-Time Tools

These tools are used during the package build process and are not shipped in the final ISO.

| Tool | Homepage / Repository | License |
|------|----------------------|---------|
| **sassc** | [github.com/sass/sassc](https://github.com/sass/sassc) | MIT |
| **Rust / Cargo** | [rust-lang.org](https://www.rust-lang.org/) | MIT / Apache-2.0 |
| **GCC** | [gcc.gnu.org](https://gcc.gnu.org/) | GPL-3.0-or-later |
| **Git** | [git-scm.com](https://git-scm.com/) | GPL-2.0-only |
| **Aiursoft Apkg SDK** | [github.com/AiursoftWeb/Apkg](https://github.com/AiursoftWeb/Apkg) | MIT |

---

## 19. Installer Components

| Project | Homepage / Repository | License |
|---------|----------------------|---------|
| **Ubiquity** (Ubuntu Installer) | [launchpad.net/ubiquity](https://launchpad.net/ubiquity) | GPL-2.0-or-later |
| **Casper** (Live System) | [launchpad.net/ubuntu/+source/casper](https://launchpad.net/ubuntu/+source/casper) | GPL-2.0-or-later |

---

## 20. Multimedia & Codecs

These video and audio codec libraries power media playback through GStreamer and FFmpeg. Many are shipped via `gstreamer1.0-plugins-bad`, `gstreamer1.0-plugins-ugly`, or `libavcodec-extra`.

| Project | Homepage / Repository | License |
|---------|----------------------|---------|
| **x264** (H.264 encoder) | [videolan.org/developers/x264.html](https://www.videolan.org/developers/x264.html) | GPL-2.0-or-later |
| **x265** (H.265/HEVC encoder) | [bitbucket.org/multicoreware/x265_git](https://bitbucket.org/multicoreware/x265_git) | GPL-2.0-or-later |
| **libvpx** (VP8/VP9 codec) | [webmproject.org](https://www.webmproject.org/code/) | BSD-3-Clause |
| **libaom** (AV1 reference codec) | [aomedia.org](https://aomedia.googlesource.com/aom/) | BSD-2-Clause |
| **dav1d** (AV1 decoder) | [code.videolan.org/videolan/dav1d](https://code.videolan.org/videolan/dav1d) | BSD-2-Clause |
| **SVT-AV1** (AV1 encoder) | [gitlab.com/AOMediaCodec/SVT-AV1](https://gitlab.com/AOMediaCodec/SVT-AV1) | BSD-2-Clause |
| **rav1e** (AV1 encoder) | [github.com/xiph/rav1e](https://github.com/xiph/rav1e) | BSD-2-Clause |
| **openh264** (H.264 codec) | [github.com/cisco/openh264](https://github.com/cisco/openh264) | BSD-2-Clause |
| **LAME** (MP3 encoder) | [lame.sourceforge.io](https://lame.sourceforge.io/) | LGPL-2.0-or-later |
| **Opus** (audio codec) | [opus-codec.org](https://opus-codec.org/) | BSD-3-Clause |
| **Vorbis** (audio codec) | [xiph.org/vorbis](https://xiph.org/vorbis/) | BSD-3-Clause |
| **FLAC** (lossless audio codec) | [xiph.org/flac](https://xiph.org/flac/) | BSD-3-Clause / GPL-2.0-or-later |
| **Speex** (speech codec) | [speex.org](https://speex.org/) | BSD-3-Clause |
| **libtheora** (video codec) | [theora.org](https://theora.org/) | BSD-3-Clause |
| **mpg123** (MPEG audio decoder) | [mpg123.org](https://www.mpg123.org/) | LGPL-2.1-or-later |
| **faad2** (AAC decoder) | [github.com/knik0/faad2](https://github.com/knik0/faad2) | GPL-2.0-or-later |
| **libbluray** | [code.videolan.org/videolan/libbluray](https://code.videolan.org/videolan/libbluray) | LGPL-2.1-or-later |
| **SDL2** (Simple DirectMedia Layer) | [libsdl.org](https://www.libsdl.org/) | zlib |
| **libsndfile** | [github.com/libsndfile/libsndfile](https://github.com/libsndfile/libsndfile) | LGPL-2.1-or-later |
| **soundtouch** | [soundtouch.com](https://www.soundtouch.com/) | LGPL-2.1-or-later |
| **chromaprint** (AcoustID fingerprinting) | [github.com/acoustid/chromaprint](https://github.com/acoustid/chromaprint) | LGPL-2.1-or-later |

---

## 21. Security & Cryptography

| Project | Homepage / Repository | License |
|---------|----------------------|---------|
| **OpenSSL** | [openssl.org](https://www.openssl.org/) | Apache-2.0 |
| **GnuPG** (Gnu Privacy Guard) | [gnupg.org](https://gnupg.org/) | GPL-3.0-or-later |
| **GnuTLS** | [gnutls.org](https://www.gnutls.org/) | LGPL-2.1-or-later |
| **libgcrypt** | [gnupg.org/software/libgcrypt](https://gnupg.org/software/libgcrypt/) | LGPL-2.1-or-later |
| **libsodium** | [doc.libsodium.org](https://doc.libsodium.org/) | ISC |
| **libfido2** (FIDO2/WebAuthn) | [github.com/Yubico/libfido2](https://github.com/Yubico/libfido2) | BSD-2-Clause |
| **p11-kit** (PKCS#11) | [github.com/p11-glue/p11-kit](https://github.com/p11-glue/p11-kit) | BSD-3-Clause |
| **libksba** (X.509 / CMS) | [gnupg.org/software/libksba](https://gnupg.org/software/libksba/) | LGPL-2.1-or-later |
| **cracklib** | [github.com/cracklib/cracklib](https://github.com/cracklib/cracklib) | LGPL-2.1-or-later |
| **libpwquality** | [github.com/libpwquality/libpwquality](https://github.com/libpwquality/libpwquality) | BSD-3-Clause / GPL-2.0-or-later |
| **libseccomp** | [github.com/seccomp/libseccomp](https://github.com/seccomp/libseccomp) | LGPL-2.1-or-later |

---

## 22. Content & Document Libraries

| Project | Homepage / Repository | License |
|---------|----------------------|---------|
| **Poppler** (PDF rendering) | [poppler.freedesktop.org](https://poppler.freedesktop.org/) | GPL-2.0-or-later / LGPL-2.1-or-later |
| **librsvg** (SVG rendering) | [gitlab.gnome.org/GNOME/librsvg](https://gitlab.gnome.org/GNOME/librsvg) | LGPL-2.1-or-later |
| **Ghostscript** (PostScript / PDF) | [ghostscript.com](https://www.ghostscript.com/) | AGPL-3.0-or-later |
| **ImageMagick** | [imagemagick.org](https://imagemagick.org/) | Apache-2.0 |
| **LibRaw** (RAW image decoding) | [libraw.org](https://www.libraw.org/) | LGPL-2.1-or-later / CDDL-1.0 |
| **libjpeg-turbo** | [libjpeg-turbo.org](https://libjpeg-turbo.org/) | IJG / BSD-3-Clause / zlib |
| **libpng** | [libpng.org](http://www.libpng.org/pub/png/libpng.html) | libpng |
| **libwebp** | [chromium.googlesource.com/webm/libwebp](https://chromium.googlesource.com/webm/libwebp) | BSD-3-Clause |
| **libtiff** | [libtiff.gitlab.io/libtiff](https://libtiff.gitlab.io/libtiff/) | libtiff |
| **libjxl** (JPEG-XL) | [github.com/libjxl/libjxl](https://github.com/libjxl/libjxl) | BSD-3-Clause |
| **libheif** (HEIF/AVIF) | [github.com/strukturag/libheif](https://github.com/strukturag/libheif) | LGPL-3.0-or-later |
| **openjpeg** (JPEG 2000) | [github.com/uclouvain/openjpeg](https://github.com/uclouvain/openjpeg) | BSD-2-Clause |
| **libopenexr** | [openexr.org](https://openexr.org/) | BSD-3-Clause |
| **libexif** | [libexif.github.io](https://libexif.github.io/) | LGPL-2.1-or-later |
| **Exiv2** (image metadata) | [exiv2.org](https://www.exiv2.org/) | GPL-2.0-or-later |

---

## 23. Spell Checking & Accessibility

| Project | Homepage / Repository | License |
|---------|----------------------|---------|
| **Hunspell** | [hunspell.github.io](https://hunspell.github.io/) | LGPL-2.1-or-later / MPL-1.1 |
| **Enchant** | [abiword.github.io/enchant](https://abiword.github.io/enchant/) | LGPL-2.1-or-later |
| **Aspell** | [aspell.net](http://aspell.net/) | LGPL-2.1-or-later |
| **liblouis** (Braille translator) | [liblouis.io](https://liblouis.io/) | LGPL-2.1-or-later |
| **flite** (speech synthesis) | [cmuflite.org](http://www.cmuflite.org/) | BSD-3-Clause |
| **libwacom** (tablet support) | [github.com/linuxwacom/libwacom](https://github.com/linuxwacom/libwacom) | MIT |

---

## 24. Additional System Components

| Project | Homepage / Repository | License |
|---------|----------------------|---------|
| **BlueZ** (Bluetooth stack) | [bluez.org](http://www.bluez.org/) | GPL-2.0-or-later |
| **PulseAudio** (client library) | [freedesktop.org/wiki/Software/PulseAudio](https://www.freedesktop.org/wiki/Software/PulseAudio/) | LGPL-2.1-or-later |
| **libinput** | [wayland.freedesktop.org/libinput](https://wayland.freedesktop.org/libinput/) | MIT |
| **libcamera** | [libcamera.org](https://libcamera.org/) | LGPL-2.1-or-later |
| **cryptsetup** (LUKS) | [gitlab.com/cryptsetup/cryptsetup](https://gitlab.com/cryptsetup/cryptsetup) | GPL-2.0-or-later |
| **LVM2** (Logical Volume Manager) | [sourceware.org/lvm2](https://sourceware.org/lvm2/) | GPL-2.0-or-later |
| **btrfs-progs** | [btrfs.wiki.kernel.org](https://btrfs.wiki.kernel.org/) | GPL-2.0-or-later |
| **linux-firmware** | [git.kernel.org/pub/scm/linux/kernel/git/firmware/linux-firmware](https://git.kernel.org/pub/scm/linux/kernel/git/firmware/linux-firmware.git) | Various |
| **bubblewrap** | [github.com/containers/bubblewrap](https://github.com/containers/bubblewrap) | LGPL-2.0-or-later |
| **ostree** | [github.com/ostreedev/ostree](https://github.com/ostreedev/ostree) | LGPL-2.0-or-later |
| **libmbim** / **libqmi** (mobile broadband) | [freedesktop.org/wiki/Software/libmbim](https://www.freedesktop.org/wiki/Software/libmbim/) | LGPL-2.1-or-later |
| **libimobiledevice** (iOS device support) | [libimobiledevice.org](https://libimobiledevice.org/) | LGPL-2.1-or-later |
| **libusbmuxd** | [github.com/libimobiledevice/libusbmuxd](https://github.com/libimobiledevice/libusbmuxd) | LGPL-2.1-or-later |
| **Spice** (remote desktop protocol) | [spice-space.org](https://www.spice-space.org/) | GPL-2.0-or-later |
| **FreeRDP** | [freerdp.com](https://www.freerdp.com/) | Apache-2.0 |
| **Samba** (SMB/CIFS) | [samba.org](https://www.samba.org/) | GPL-3.0-or-later |
| **NFS** (Network File System) | [linux-nfs.org](https://linux-nfs.org/) | GPL-2.0-or-later |
| **Protobuf** (Protocol Buffers) | [github.com/protocolbuffers/protobuf](https://github.com/protocolbuffers/protobuf) | BSD-3-Clause |
| **WebKitGTK** | [webkitgtk.org](https://webkitgtk.org/) | LGPL-2.0-or-later / BSD-2-Clause |
| **libgphoto2** (digital camera access) | [gphoto.org](http://www.gphoto.org/) | LGPL-2.1-or-later |
| **libmtp** (MTP device support) | [libmtp.sourceforge.net](https://libmtp.sourceforge.net/) | LGPL-2.1-or-later |

---

## 25. Additional CLI Tools

| Project | Homepage / Repository | License |
|---------|----------------------|---------|
| **htop** | [htop.dev](https://htop.dev/) | GPL-2.0-or-later |
| **fastfetch** | [github.com/fastfetch-cli/fastfetch](https://github.com/fastfetch-cli/fastfetch) | MIT |
| **jq** (JSON processor) | [jqlang.github.io/jq](https://jqlang.github.io/jq/) | MIT |
| **strace** | [strace.io](https://strace.io/) | LGPL-2.1-or-later |
| **tcpdump** | [tcpdump.org](https://www.tcpdump.org/) | BSD-3-Clause |
| **squashfs-tools** | [github.com/plougher/squashfs-tools](https://github.com/plougher/squashfs-tools) | GPL-2.0-or-later |
| **yt-dlp** | [github.com/yt-dlp/yt-dlp](https://github.com/yt-dlp/yt-dlp) | Unlicense |
| **less** | [greenwoodsoftware.com/less](https://www.greenwoodsoftware.com/less/) | GPL-3.0-or-later / BSD-2-Clause |
| **grep** (GNU Grep) | [gnu.org/software/grep](https://www.gnu.org/software/grep/) | GPL-3.0-or-later |
| **sed** (GNU Sed) | [gnu.org/software/sed](https://www.gnu.org/software/sed/) | GPL-3.0-or-later |
| **gawk** (GNU Awk) | [gnu.org/software/gawk](https://www.gnu.org/software/gawk/) | GPL-3.0-or-later |
| **diffutils** (GNU Diffutils) | [gnu.org/software/diffutils](https://www.gnu.org/software/diffutils/) | GPL-3.0-or-later |
| **findutils** (GNU Findutils) | [gnu.org/software/findutils](https://www.gnu.org/software/findutils/) | GPL-3.0-or-later |
| **netcat-openbsd** | [man.openbsd.org/nc](https://man.openbsd.org/nc.1) | BSD-3-Clause |
| **unzip** / **zip** (Info-ZIP) | [info-zip.org](https://info-zip.org/) | Info-ZIP |
| **bzip2** | [sourceware.org/bzip2](https://sourceware.org/bzip2/) | BSD-4-Clause |
| **cpio** (GNU cpio) | [gnu.org/software/cpio](https://www.gnu.org/software/cpio/) | GPL-3.0-or-later |
| **parted** (GNU Parted) | [gnu.org/software/parted](https://www.gnu.org/software/parted/) | GPL-3.0-or-later |
| **dosfstools** | [github.com/dosfstools/dosfstools](https://github.com/dosfstools/dosfstools) | GPL-3.0-or-later |
| **ntfs-3g** | [github.com/tuxera/ntfs-3g](https://github.com/tuxera/ntfs-3g) | GPL-2.0-or-later |
| **exfatprogs** | [github.com/exfatprogs/exfatprogs](https://github.com/exfatprogs/exfatprogs) | GPL-2.0-or-later |
| **net-tools** | [sourceforge.net/projects/net-tools](https://sourceforge.net/projects/net-tools/) | GPL-2.0-or-later |
| **whois** | [github.com/rfc1036/whois](https://github.com/rfc1036/whois) | GPL-2.0-or-later |
| **mtr** (My TraceRoute) | [bitwizard.nl/mtr](https://www.bitwizard.nl/mtr/) | GPL-2.0-or-later |
| **iperf3** | [software.es.net/iperf](https://software.es.net/iperf/) | BSD-3-Clause |

---

## Notes

- **Ubuntu/Debian transitive dependencies:** The packages listed above are direct inclusions and dependencies. A full Debian/Ubuntu-based system includes thousands of additional packages from the Ubuntu and Debian archives, each with their own upstream projects and licenses. This document focuses on projects whose code AnduinOS directly fetches, patches, repackages, or prominently features.
- **License of GNOME Shell Extensions:** All GNOME Shell extensions that interact with GNOME Shell's JavaScript internals are effectively licensed under GPL-2.0-or-later, as required by the GNOME Shell extension system.
- **"Various" license entries:** Some projects (particularly Debian and Ubuntu) are aggregations of many sub-projects. Consult the upstream distribution's copyright file for per-component details.
- **Version information:** For the exact version of each project used in a given AnduinOS release, refer to the respective `.aosproj` package definition and its pinned commit hash or version tag.

## Full List of Packages in AnduinOS 2

```
3cpio 0.14.0-1ubuntu1
accountsservice 23.13.9-8ubuntu5.1
acl 2.3.2-2
adduser 3.153ubuntu1
adwaita-icon-theme 50.0-1
alsa-base 1.0.25+dfsg-0ubuntu9
alsa-topology-conf 1.2.5.1-3build1
alsa-ucm-conf-anduinos 2.0.0-1+resolute
alsa-utils 1.2.15.2-1ubuntu1
amberol 2025.1-5
amd64-microcode 3.20251202.1ubuntu2
anduinos-appearance 2.0.0-1+resolute
anduinos-appstore 2.0.0-1+resolute
anduinos-apt-config 2.0.0-1+resolute
anduinos-archive-keyring 2.0.0-1+resolute
anduinos-bwrap-hack 2.0.0-1+resolute
anduinos-container 2.0.0-1+resolute
anduinos-core-system 2.0.0-1+resolute
anduinos-dconf-defaults 2.0.0-2+resolute
anduinos-dconf-runtime 2.0.0-2+resolute
anduinos-deskmon 2.0.0-1+resolute
anduinos-desktop 2.0.0-1+resolute
anduinos-desktop-apps 2.0.0-1+resolute
anduinos-desktop-core 2.0.0-1+resolute
anduinos-fluent-gtk-theme 2.0.0-1+resolute
anduinos-fluent-icon-theme 2.0.0-1+resolute
anduinos-fonts 2.0.0-1+resolute
anduinos-gdm3-wallpaper 2.0.0-1+resolute-addon
anduinos-gnome-extensions 2.0.0-1+resolute
anduinos-gnome-shell-locale 2.0.0-1+resolute
anduinos-installer-config 2.0.0-1+resolute
anduinos-live-settings 2.0.0-1+resolute
anduinos-mimeapps 2.0.0-1+resolute
anduinos-no-snapd 2.0.0-1+resolute
anduinos-rime 2.0.0-1+resolute
anduinos-session 2.0.0-1+resolute
anduinos-software-properties-common 2.0.0+0.120-1+resolute-addon
anduinos-software-properties-gtk 2.0.0+0.120-1+resolute-addon
anduinos-system-tweaks 2.0.0-1+resolute
anduinos-templates 2.0.0-1+resolute
anduinos-theme 2.0.0-1+resolute
anduinos-ufwall-gtk 2.0.0-3+resolute
anduinos-wallpapers 2.0.0-1+resolute
apparmor 5.0.0~beta1-0ubuntu7
appstream 1.1.2-1
apt 3.2.0
apt-config-icons 1.1.2-1
aptdaemon 2.0.2build1
aptdaemon-data 2.0.2build1
aspell 0.60.8.2-3
aspell-en 2020.12.07-0-1.1build1
at-spi2-common 2.60.0-1
at-spi2-core 2.60.0-1
avahi-daemon 0.8-18ubuntu1.1
avahi-utils 0.8-18ubuntu1.1
baobab 49.1-2
base-files 1:2.0.0+14ubuntu6-1+resolute-addon
base-passwd 3.6.8
bash 5.3-2ubuntu1
bash-completion 1:2.16.0-8build1
bc 1.07.1-4build1
bind9-dnsutils 1:9.20.18-1ubuntu2.1
bind9-host 1:9.20.18-1ubuntu2.1
bind9-libs 1:9.20.18-1ubuntu2.1
binutils 2.46-3ubuntu2
binutils-common 2.46-3ubuntu2
binutils-x86-64-linux-gnu 2.46-3ubuntu2
bluez 5.85-4
bluez-obexd 5.85-4
bolt 0.9.10-1
bsdextrautils 2.41.3-3ubuntu2
bsdutils 1:2.41.3-3ubuntu2
btrfs-progs 6.17.1-1build1
bubblewrap 0.11.1-1ubuntu0.1
busybox-initramfs 1:1.37.0-7ubuntu1
busybox-static 1:1.37.0-7ubuntu1
bzip2 1.0.8-6build2
ca-certificates 20260601~26.04.1
casper 26.04.2
celluloid 0.29-3
cifs-utils 2:7.4-1build1
colord 1.4.8-3
colord-data 1.4.8-3
command-not-found 23.04.0build1
console-setup 1.237ubuntu3
console-setup-linux 1.237ubuntu3
coreutils 9.5-1ubuntu2+0.0.0~ubuntu25
coreutils-from-uutils 0.0.0~ubuntu25
cpio 2.15+dfsg-2.1
cpp 4:15.2.0-5ubuntu1
cpp-15 15.2.0-16ubuntu1
cpp-15-x86-64-linux-gnu 15.2.0-16ubuntu1
cpp-x86-64-linux-gnu 4:15.2.0-5ubuntu1
cracklib-runtime 2.9.6-5.2build3
crash 9.0.1+~16.3-1ubuntu1
cron 3.0pl1-200ubuntu1
cron-daemon-common 3.0pl1-200ubuntu1
cryptsetup 2:2.8.4-1ubuntu4
cryptsetup-bin 2:2.8.4-1ubuntu4
cryptsetup-initramfs 2:2.8.4-1ubuntu4
cups 2.4.16-1ubuntu1.3
cups-browsed 2.1.1-0ubuntu3
cups-bsd 2.4.16-1ubuntu1.3
cups-client 2.4.16-1ubuntu1.3
cups-common 2.4.16-1ubuntu1.3
cups-core-drivers 2.4.16-1ubuntu1.3
cups-daemon 2.4.16-1ubuntu1.3
cups-filters 2.0.1-0ubuntu4.1
cups-filters-core-drivers 2.0.1-0ubuntu4.1
cups-ipp-utils 2.4.16-1ubuntu1.3
cups-pk-helper 0.2.6-2.1build1
cups-ppdc 2.4.16-1ubuntu1.3
cups-server-common 2.4.16-1ubuntu1.3
curl 8.18.0-1ubuntu2.1
dash 0.5.12-12ubuntu3
dbus 1.16.2-2ubuntu4
dbus-bin 1.16.2-2ubuntu4
dbus-daemon 1.16.2-2ubuntu4
dbus-session-bus-common 1.16.2-2ubuntu4
dbus-system-bus-common 1.16.2-2ubuntu4
dbus-user-session 1.16.2-2ubuntu4
dbus-x11 1.16.2-2ubuntu4
dc 1.07.1-4build1
dconf-cli 0.49.0-4
dconf-gsettings-backend 0.49.0-4
dconf-service 0.49.0-4
dctrl-tools 2.24-3build4
debconf 1.5.92
debconf-i18n 1.5.92
debianutils 5.23.2build1
desktop-file-utils 0.28-1build1
dhcpcd-base 1:10.3.0-7
dictionaries-common 1.31.4
diffutils 1:3.12-1
dirmngr 2.4.8-4ubuntu3
discover 2.1.2-10.1build1
discover-data 2.2013.01.13+nmu1build1
distro-info-data 0.68ubuntu0.1
dmeventd 2:1.02.205-2ubuntu3
dmidecode 3.6-2build1
dmsetup 2:1.02.205-2ubuntu3
dns-root-data 2025080400build1
dnsmasq-base 2.92-1ubuntu0.3
docbook-xml 4.5-13build1
dosfstools 4.2-1.2build1
dpkg 1.23.7ubuntu1
dpkg-repack 1.54build1
dracut-install 110-11
e2fsprogs 1.47.2-3ubuntu4
eatmydata 131-2build1
efibootmgr 18-4ubuntu1
eject 2.41.3-3ubuntu2
emacsen-common 3.0.8build1
enchant-2 2.8.2+dfsg1-3build1
espeak-ng-data 1.52.0+dfsg-5build1
ethtool 1:6.19-1
evolution-data-server 3.56.2-8
evolution-data-server-common 3.56.2-8
exfatprogs 1.3.2-1
fastfetch 2.57.1+dfsg-1ubuntu1
fdisk 2.41.3-3ubuntu2
ffmpeg 7:8.0.1-3ubuntu2
ffmpegthumbnailer 2.3.0-1
file 1:5.46-5build2
file-roller 44.6-3
finalrd 9build2
findutils 4.10.0-3build2
firefox-anduinos 1:2.0.0+152.0.3~build1-1+resolute
firmware-sof-anduinos 2.0.0-2025.12.2+resolute-addon
flatpak 1.16.6-1
folks-common 0.15.12-1
fontconfig 2.17.1-3ubuntu1
fontconfig-config 2.17.1-3ubuntu1
fonts-adwaita 49.0+dfsg-2
fonts-adwaita-sans 49.0+dfsg-2
fonts-droid-fallback 1:8.1.0r7-1~1.gbp36536bbuild1
fonts-noto-cjk 1:20240730+repack1-1build1
fonts-noto-color-emoji 2.051-1build1
fonts-noto-core 20201225-2build1
fonts-noto-mono 20201225-2build1
fonts-ubuntu 0.869+git20240321-0ubuntu2
fonts-urw-base35 20200910-8build1
foomatic-db-compressed-ppds 20250819-1build1
fprintd 1.94.5-4
fuse3 3.18.2-1
fwupd 2.1.1-1ubuntu3
fwupd-signed 1.55+1.7-1
gcc-15-base 15.2.0-16ubuntu1
gcc-16-base 16-20260322-1ubuntu1
gcr 3.41.2-6
gcr4 4.4.0.1-8
gdisk 1.0.10-2build1
gdm3 50.0-0ubuntu1
geary 46.0-13build1
geoclue-2.0 2.7.2-2ubuntu3
geocode-glib-common 3.26.4-3
gettext 0.23.2-1
gettext-base 0.23.2-1
ghostscript 10.06.0~dfsg-3ubuntu1
gir1.2-accountsservice-1.0 23.13.9-8ubuntu5.1
gir1.2-adw-1 1.9.0-0ubuntu1
gir1.2-atk-1.0 2.60.0-1
gir1.2-atspi-2.0 2.60.0-1
gir1.2-dbusmenu-glib-0.4 18.10.20180917~bzr492+repack1-4build1
gir1.2-dee-1.0 1.2.7+17.10.20170616-8build1
gir1.2-evince-3.0 48.1+dfsg-1build1
gir1.2-freedesktop 1.86.0-6build1
gir1.2-gck-2 4.4.0.1-8
gir1.2-gcr-4 4.4.0.1-8
gir1.2-gdesktopenums-3.0 50.0-1ubuntu2
gir1.2-gdkpixbuf-2.0 2.44.5+dfsg-4ubuntu1
gir1.2-gdm-1.0 50.0-0ubuntu1
gir1.2-geoclue-2.0 2.7.2-2ubuntu3
gir1.2-girepository-3.0 2.88.0-1
gir1.2-glib-2.0 2.88.0-1
gir1.2-gmenu-3.0 3.38.1-1ubuntu1
gir1.2-gnomebg-4.0 44.5-1ubuntu1
gir1.2-gnomebluetooth-3.0 47.1-5
gir1.2-gnomedesktop-3.0 44.5-1ubuntu1
gir1.2-gnomedesktop-4.0 44.5-1ubuntu1
gir1.2-gnomeqr-4.0 44.5-1ubuntu1
gir1.2-graphene-1.0 1.10.8-5build1
gir1.2-gst-plugins-bad-1.0 1.28.2-1ubuntu1.1
gir1.2-gst-plugins-base-1.0 1.28.2-1
gir1.2-gst-plugins-extra-1.0 1.28.2-1ubuntu1.1
gir1.2-gstreamer-1.0 1.28.2-1
gir1.2-gtk-3.0 3.24.52-0ubuntu1
gir1.2-gtk-4.0 4.22.4+ds-0ubuntu0.1
gir1.2-gtksource-4 4.8.4-9
gir1.2-gudev-1.0 1:238-7build1
gir1.2-gweather-4.0 4.4.4-4
gir1.2-handy-1 1.8.3-3build1
gir1.2-harfbuzz-0.0 12.3.2-2
gir1.2-ibus-1.0 1.5.34~rc2-1
gir1.2-javascriptcoregtk-4.1 2.52.3-0ubuntu0.26.04.2
gir1.2-json-1.0 1.10.8+ds-2
gir1.2-mutter-18 50.1-0ubuntu2.2
gir1.2-nm-1.0 1.54.3-2ubuntu3
gir1.2-nma-1.0 1.10.6-7
gir1.2-nma4-1.0 1.10.6-7
gir1.2-notify-0.7 0.8.8-1
gir1.2-packagekitglib-1.0 1.3.4-3ubuntu1.1
gir1.2-pango-1.0 1.57.0-1
gir1.2-polkit-1.0 127-2ubuntu1
gir1.2-rsvg-2.0 2.61.3+dfsg-3
gir1.2-secret-1 0.21.7-2build1
gir1.2-soup-3.0 3.6.6-1
gir1.2-timezonemap-1.0 0.4.6-7build1
gir1.2-udisks-2.0 2.10.91-1ubuntu2
gir1.2-unity-7.0 7.1.4+19.04.20190319-6.1ubuntu1
gir1.2-upowerglib-1.0 1.91.1-1
gir1.2-vte-2.91 0.84.0-2
gir1.2-webkit2-4.1 2.52.3-0ubuntu0.26.04.2
gir1.2-wnck-3.0 43.3-1build1
gir1.2-xkl-1.0 5.4-6build1
girepository-tools 2.88.0-1
gjs 1.88.0-1
glib-networking 2.80.1-1build2
glib-networking-common 2.80.1-1build2
glib-networking-services 2.80.1-1build2
glycin-loaders 2.1.1+ds-0ubuntu1
glycin-thumbnailers 2.1.1+ds-0ubuntu1
gnome-bluetooth-3-common 47.1-5
gnome-bluetooth-sendto 47.1-5
gnome-browser-connector 42.1-7
gnome-calculator 1:50.0-1ubuntu1
gnome-calendar 50.0-1
gnome-characters 50.0-1
gnome-chess 1:49.2-2
gnome-clocks 50.0-1
gnome-control-center 1:50.0-0ubuntu6.1
gnome-control-center-data 1:50.0-0ubuntu6.1
gnome-control-center-faces 1:50.0-0ubuntu6.1
gnome-desktop3-data 44.5-1ubuntu1
gnome-disk-utility 46.1-2ubuntu2
gnome-font-viewer 49.0-1
gnome-keyring 50.0-1
gnome-keyring-pkcs11 50.0-1
gnome-logs 49.0-1
gnome-menus 3.38.1-1ubuntu1
gnome-online-accounts 3.58.0-1
gnome-power-manager 43.0-5
gnome-remote-desktop 50.0-0ubuntu2
gnome-session 50.0-0ubuntu3.2
gnome-session-bin 50.0-0ubuntu3.2
gnome-session-common 50.0-0ubuntu3.2
gnome-settings-daemon 50.0-1ubuntu1
gnome-settings-daemon-common 50.0-1ubuntu1
gnome-shell 50.1-0ubuntu1
gnome-shell-common 50.1-0ubuntu1
gnome-shell-extension-accent-gtk-theme 2.0.0-1+resolute
gnome-shell-extension-accent-icons-theme 2.0.0-1+resolute
gnome-shell-extension-accent-user-theme 2.0.0-1+resolute
gnome-shell-extension-anduinos-loc 2.0.0-1+resolute
gnome-shell-extension-appindicator-anduinos 2.0.0-1+resolute
gnome-shell-extension-arcmenu 2.0.0-1+resolute
gnome-shell-extension-blur-my-shell 2.0.0-2+resolute
gnome-shell-extension-clipboard-indicator 2.0.0-1+resolute
gnome-shell-extension-customize-ibus 2.0.0-1+resolute
gnome-shell-extension-dash-to-panel-anduinos 2.0.0-1+resolute
gnome-shell-extension-desktop-icons-ng-anduinos 2.0.0-1+resolute
gnome-shell-extension-drive-menu 50.0-1
gnome-shell-extension-lockkeys 2.0.0-1+resolute
gnome-shell-extension-network-stats 2.0.0-1+resolute
gnome-shell-extension-no-power-icon 2.0.0-1+resolute
gnome-shell-extension-noti-bottom-right 2.0.0-1+resolute
gnome-shell-extension-prefs 50.1-0ubuntu1
gnome-shell-extension-proxy-switcher 2.0.0-1+resolute
gnome-shell-extension-simple-weather 2.0.0-1+resolute
gnome-shell-extension-tiling-assistant 2.0.0-1+resolute
gnome-shell-extension-user-theme 50.0-1
gnome-shell-extensions-common 50.0-1
gnome-snapshot 50.0-0ubuntu1
gnome-software 50.0-1
gnome-software-common 50.0-1
gnome-software-plugin-deb 50.0-1
gnome-software-plugin-flatpak 50.0-1
gnome-sound-recorder 43~beta-5
gnome-sushi 50.0-0ubuntu0.1
gnome-text-editor 50.0-1
gnome-user-docs 50.0-0ubuntu1
gnome-weather 50.0-1
gnu-coreutils 9.7-3ubuntu2
gnupg 2.4.8-4ubuntu3
gnupg-l10n 2.4.8-4ubuntu3
gnupg-utils 2.4.8-4ubuntu3
gpg 2.4.8-4ubuntu3
gpg-agent 2.4.8-4ubuntu3
gpg-wks-client 2.4.8-4ubuntu3
gpgconf 2.4.8-4ubuntu3
gpgsm 2.4.8-4ubuntu3
gpgv 2.4.8-4ubuntu3
grep 3.12-1
groff-base 1.23.0-10
grub-common 2.14-2ubuntu2
grub-efi-amd64 2.14-2ubuntu1
grub-efi-amd64-bin 2.14-2ubuntu1
grub-efi-amd64-signed 1.215+2.14-2ubuntu1
grub-efi-amd64-unsigned 2.14-2ubuntu1
grub-gfxpayload-lists 0.7build3
grub-pc 2.14-2ubuntu2
grub-pc-bin 2.14-2ubuntu2
grub2-common 2.14-2ubuntu2
gsettings-desktop-schemas 50.0-1ubuntu2
gstreamer1.0-alsa 1.28.2-1
gstreamer1.0-gl 1.28.2-1
gstreamer1.0-gtk3 1.28.2-2
gstreamer1.0-gtk4 0.14.4-1ubuntu1
gstreamer1.0-libav 1.28.2-1
gstreamer1.0-libcamera 0.7.0-1ubuntu2
gstreamer1.0-packagekit 1.3.4-3ubuntu1.1
gstreamer1.0-pipewire 1.6.2-1ubuntu1
gstreamer1.0-plugins-bad 1.28.2-1ubuntu1.1
gstreamer1.0-plugins-base 1.28.2-1
gstreamer1.0-plugins-base-apps 1.28.2-1
gstreamer1.0-plugins-extra 1.28.2-1ubuntu1.1
gstreamer1.0-plugins-good 1.28.2-2
gstreamer1.0-plugins-ugly 1.28.2-1
gstreamer1.0-tools 1.28.2-1
gstreamer1.0-x 1.28.2-1
gtk-update-icon-cache 4.22.4+ds-0ubuntu0.1
gvfs 1.60.0-1
gvfs-backends 1.60.0-1
gvfs-common 1.60.0-1
gvfs-daemons 1.60.0-1
gvfs-fuse 1.60.0-1
gvfs-libs 1.60.0-1
gzip 1.14-1~exp2ubuntu1
hdparm 9.65+ds-1.1build1
heif-gdk-pixbuf 1.21.2-3ubuntu0.1
heif-thumbnailer 1.21.2-3ubuntu0.1
hicolor-icon-theme 0.18-2build1
hoichess 0.22.0-3build2
hostname 3.25build1
htop 3.4.1-5build2
httping 4.4.0-3build1
hunspell-en-us 1:2020.12.07-4build1
hwdata 0.394-1build1
ibus 1.5.34~rc2-1
ibus-data 1.5.34~rc2-1
ibus-gtk 1.5.34~rc2-1
ibus-gtk3 1.5.34~rc2-1
ibus-gtk4 1.5.34~rc2-1
ibus-rime 1.6.0-1
ibverbs-providers 61.0-2ubuntu3
iio-sensor-proxy 3.8-1
im-config 0.62
imagemagick-7-common 8:7.1.2.18+dfsg1-1
init 1.69
init-system-helpers 1.69
initramfs-tools 0.151ubuntu1
initramfs-tools-bin 0.151ubuntu1
initramfs-tools-core 0.151ubuntu1
intel-microcode 3.20260210.1ubuntu2
ipp-usb 0.9.31-1
iproute2 6.19.0-1ubuntu1
iptables 1.8.11-2ubuntu3
iputils-ping 3:20250605-1ubuntu1
iputils-tracepath 3:20250605-1ubuntu1
iso-codes 4.20.1-1
iucode-tool 2.3.1-3build2
iw 6.17-1
jq 1.8.1-4ubuntu2
kbd 2.7.1-2ubuntu2
keyboard-configuration 1.237ubuntu3
keyutils 1.6.3-6ubuntu3
klibc-utils 2.0.14-1ubuntu2
kmod 34.2-2ubuntu2
language-pack-ar 1:26.04+20260417
language-pack-ar-base 1:26.04+20260417
language-pack-da 1:26.04+20260417
language-pack-da-base 1:26.04+20260417
language-pack-de 1:26.04+20260417
language-pack-de-base 1:26.04+20260417
language-pack-el 1:26.04+20260417
language-pack-el-base 1:26.04+20260417
language-pack-en 1:26.04+20260417
language-pack-en-base 1:26.04+20260417
language-pack-es 1:26.04+20260417
language-pack-es-base 1:26.04+20260417
language-pack-fi 1:26.04+20260417
language-pack-fi-base 1:26.04+20260417
language-pack-fr 1:26.04+20260417
language-pack-fr-base 1:26.04+20260417
language-pack-gnome-ar 1:26.04+20260417
language-pack-gnome-ar-base 1:26.04+20260417
language-pack-gnome-da 1:26.04+20260417
language-pack-gnome-da-base 1:26.04+20260417
language-pack-gnome-de 1:26.04+20260417
language-pack-gnome-de-base 1:26.04+20260417
language-pack-gnome-el 1:26.04+20260417
language-pack-gnome-el-base 1:26.04+20260417
language-pack-gnome-en 1:26.04+20260417
language-pack-gnome-en-base 1:26.04+20260417
language-pack-gnome-es 1:26.04+20260417
language-pack-gnome-es-base 1:26.04+20260417
language-pack-gnome-fi 1:26.04+20260417
language-pack-gnome-fi-base 1:26.04+20260417
language-pack-gnome-fr 1:26.04+20260417
language-pack-gnome-fr-base 1:26.04+20260417
language-pack-gnome-hi 1:26.04+20260417
language-pack-gnome-hi-base 1:26.04+20260417
language-pack-gnome-id 1:26.04+20260417
language-pack-gnome-id-base 1:26.04+20260417
language-pack-gnome-it 1:26.04+20260417
language-pack-gnome-it-base 1:26.04+20260417
language-pack-gnome-ja 1:26.04+20260417
language-pack-gnome-ja-base 1:26.04+20260417
language-pack-gnome-ko 1:26.04+20260417
language-pack-gnome-ko-base 1:26.04+20260417
language-pack-gnome-nl 1:26.04+20260417
language-pack-gnome-nl-base 1:26.04+20260417
language-pack-gnome-pl 1:26.04+20260417
language-pack-gnome-pl-base 1:26.04+20260417
language-pack-gnome-pt 1:26.04+20260417
language-pack-gnome-pt-base 1:26.04+20260417
language-pack-gnome-ro 1:26.04+20260417
language-pack-gnome-ro-base 1:26.04+20260417
language-pack-gnome-ru 1:26.04+20260417
language-pack-gnome-ru-base 1:26.04+20260417
language-pack-gnome-sv 1:26.04+20260417
language-pack-gnome-sv-base 1:26.04+20260417
language-pack-gnome-th 1:26.04+20260417
language-pack-gnome-th-base 1:26.04+20260417
language-pack-gnome-tr 1:26.04+20260417
language-pack-gnome-tr-base 1:26.04+20260417
language-pack-gnome-uk 1:26.04+20260417
language-pack-gnome-uk-base 1:26.04+20260417
language-pack-gnome-vi 1:26.04+20260417
language-pack-gnome-vi-base 1:26.04+20260417
language-pack-gnome-zh-hans 1:26.04+20260417
language-pack-gnome-zh-hans-base 1:26.04+20260417
language-pack-gnome-zh-hant 1:26.04+20260417
language-pack-gnome-zh-hant-base 1:26.04+20260417
language-pack-hi 1:26.04+20260417
language-pack-hi-base 1:26.04+20260417
language-pack-id 1:26.04+20260417
language-pack-id-base 1:26.04+20260417
language-pack-it 1:26.04+20260417
language-pack-it-base 1:26.04+20260417
language-pack-ja 1:26.04+20260417
language-pack-ja-base 1:26.04+20260417
language-pack-ko 1:26.04+20260417
language-pack-ko-base 1:26.04+20260417
language-pack-nl 1:26.04+20260417
language-pack-nl-base 1:26.04+20260417
language-pack-pl 1:26.04+20260417
language-pack-pl-base 1:26.04+20260417
language-pack-pt 1:26.04+20260417
language-pack-pt-base 1:26.04+20260417
language-pack-ro 1:26.04+20260417
language-pack-ro-base 1:26.04+20260417
language-pack-ru 1:26.04+20260417
language-pack-ru-base 1:26.04+20260417
language-pack-sv 1:26.04+20260417
language-pack-sv-base 1:26.04+20260417
language-pack-th 1:26.04+20260417
language-pack-th-base 1:26.04+20260417
language-pack-tr 1:26.04+20260417
language-pack-tr-base 1:26.04+20260417
language-pack-uk 1:26.04+20260417
language-pack-uk-base 1:26.04+20260417
language-pack-vi 1:26.04+20260417
language-pack-vi-base 1:26.04+20260417
language-pack-zh-hans 1:26.04+20260417
language-pack-zh-hans-base 1:26.04+20260417
language-pack-zh-hant 1:26.04+20260417
language-pack-zh-hant-base 1:26.04+20260417
language-selector-common 0.228build1
language-selector-gnome 0.228build1
laptop-detect 0.16+nmu1build1
ldap-utils 2.6.10+dfsg-1ubuntu5
less 668-1build1
liba52-0.7.4 0.7.4-22
libaa1 1.4p5-51.1build1
libaacs0 0.11.1-4build1
libabsl20260107 20260107.0-4
libaccountsservice0 23.13.9-8ubuntu5.1
libacl1 2.3.2-2
libadwaita-1-0 1.9.0-0ubuntu1
libaio1t64 0.3.113-8build1
libao-common 1.2.2+20180113-1.2ubuntu2
libao4 1.2.2+20180113-1.2ubuntu2
libaom3 3.13.1-2
libapparmor1 5.0.0~beta1-0ubuntu7
libappstream5 1.1.2-1
libapt-pkg7.0 3.2.0
libarchive13t64 3.8.5-1ubuntu2.1
libaribb24-0t64 1.0.3-3
libasound2-data 1.2.15.3-1ubuntu1
libasound2t64 1.2.15.3-1ubuntu1
libaspell15 0.60.8.2-3
libass9 1:0.17.4-2
libassuan9 3.0.2-2build1
libasyncns0 0.8-7
libatasmart4 0.19-6
libatk-bridge2.0-0t64 2.60.0-1
libatk1.0-0t64 2.60.0-1
libatomic1 16-20260322-1ubuntu1
libatopology2t64 1.2.15.3-1ubuntu1
libatspi2.0-0t64 2.60.0-1
libattr1 1:2.5.2-4
libaudit-common 1:4.1.2-1build1
libaudit1 1:4.1.2-1build1
libauthen-sasl-perl 2.2000-1
libavahi-client3 0.8-18ubuntu1.1
libavahi-common-data 0.8-18ubuntu1.1
libavahi-common3 0.8-18ubuntu1.1
libavahi-core7 0.8-18ubuntu1.1
libavahi-glib1 0.8-18ubuntu1.1
libavahi-ui-gtk3-0 0.8-18ubuntu1.1
libavc1394-0 0.5.4-5build4
libavcodec-extra 7:8.0.1-3ubuntu2
libavcodec-extra62 7:8.0.1-3ubuntu2
libavdevice62 7:8.0.1-3ubuntu2
libavfilter11 7:8.0.1-3ubuntu2
libavformat62 7:8.0.1-3ubuntu2
libavtp0 0.2.0-2build1
libavutil60 7:8.0.1-3ubuntu2
libayatana-appindicator3-1 0.5.94-1build1
libayatana-ido3-0.4-0 0.10.4-1build1
libayatana-indicator3-7 0.9.4-2
libbasicobjects0t64 0.6.2-3build1
libbdplus0 0.2.0-4build1
libbinutils 2.46-3ubuntu2
libblkid1 2.41.3-3ubuntu2
libblockdev-crypto3 3.4.0-1
libblockdev-fs3 3.4.0-1
libblockdev-loop3 3.4.0-1
libblockdev-mdraid3 3.4.0-1
libblockdev-nvme3 3.4.0-1
libblockdev-part3 3.4.0-1
libblockdev-smart3 3.4.0-1
libblockdev-swap3 3.4.0-1
libblockdev-utils3 3.4.0-1
libblockdev3 3.4.0-1
libbluetooth3 5.85-4
libbluray3 1:1.4.1-1
libboost-locale1.90.0 1.90.0-6ubuntu1
libboost-thread1.90.0 1.90.0-6ubuntu1
libbpf1 1:1.6.3-1ubuntu1
libbrlapi0.8 6.7-1ubuntu6
libbrotli1 1.2.0-3build1
libbs2b0 3.1.0+dfsg-8build1
libbsd0 0.12.2-2build2
libburn4t64 1.5.6-1.2build1
libbytesize-common 2.12-1
libbytesize1 2.12-1
libbz2-1.0 1.0.8-6build2
libc-bin 2.43-2ubuntu2
libc-gconv-modules-extra 2.43-2ubuntu2
libc6 2.43-2ubuntu2
libcaca0 0.99.beta20-6ubuntu2.1
libcairo-gobject-perl 1.005-4build4
libcairo-gobject2 1.18.4-3
libcairo-perl 1.109-5build1
libcairo-script-interpreter2 1.18.4-3
libcairo2 1.18.4-3
libcairomm-1.16-1 1.18.0-3
libcamel-1.2-64t64 3.56.2-8
libcamera-ipa 0.7.0-1ubuntu2
libcamera0.7 0.7.0-1ubuntu2
libcanberra-gtk3-0 0.30-18ubuntu3
libcanberra-gtk3-module 0.30-18ubuntu3
libcanberra-pulse 0.30-18ubuntu3
libcanberra0 0.30-18ubuntu3
libcap-ng0 0.8.5-4build5
libcap2 1:2.75-10ubuntu2
libcap2-bin 1:2.75-10ubuntu2
libcares2 1.34.6-1
libcbor0.10 0.10.2-2ubuntu3
libcdio-cdda2t64 10.2+2.0.2-2
libcdio-paranoia2t64 10.2+2.0.2-2
libcdio19t64 2.2.0-4build1
libcdparanoia0 3.10.2+debian-14ubuntu2
libchromaprint1 1.6.0-2build1
libcjson1 1.7.19-2
libclone-perl 0.47-1
libcodec2-1.2 1.2.0-4
libcollection4t64 0.6.2-3build1
libcolord-gtk4-1t64 0.3.1-2
libcolord2 1.4.8-3
libcolorhug2 1.4.8-3
libcom-err2 1.47.2-3ubuntu4
libcomposefs1 1.0.8-3
libcpuinfo0 0.0~git20250905.877328f-1
libcrack2 2.9.6-5.2build3
libcrypt-urandom-perl 0.55-1
libcrypt1 1:4.5.1-1
libcryptsetup12 2:2.8.4-1ubuntu4
libctf-nobfd0 2.46-3ubuntu2
libctf0 2.46-3ubuntu2
libcue2 2.2.1-4.2
libcups2t64 2.4.16-1ubuntu1.3
libcupsfilters2-common 2.1.1-0ubuntu5
libcupsfilters2t64 2.1.1-0ubuntu5
libcupsimage2t64 2.4.16-1ubuntu1.3
libcurl3t64-gnutls 8.18.0-1ubuntu2.1
libcurl4t64 8.18.0-1ubuntu2.1
libdaemon0 0.14-7.1ubuntu5
libdata-dump-perl 1.25-1
libdatrie1 0.2.14-1
libdav1d7 1.5.3-1
libdb5.3t64 5.3.28+dfsg2-10ubuntu1
libdbus-1-3 1.16.2-2ubuntu4
libdbusmenu-glib4 18.10.20180917~bzr492+repack1-4build1
libdbusmenu-gtk3-4 18.10.20180917~bzr492+repack1-4build1
libdc1394-25 2.2.6-6
libdca0 0.0.7-2build2
libdconf1 0.49.0-4
libde265-0 1.0.16-1build1
libdebconfclient0 0.280ubuntu1
libdebian-installer4 0.125ubuntu3
libdecor-0-0 0.2.5-1
libdecor-0-plugin-1-gtk 0.2.5-1
libdee-1.0-4 1.2.7+17.10.20170616-8build1
libdeflate0 1.23-2ubuntu1
libdevmapper-event1.02.1 2:1.02.205-2ubuntu3
libdevmapper1.02.1 2:1.02.205-2ubuntu3
libdhash1t64 0.6.2-3build1
libdiscover2 2.1.2-10.1build1
libdisplay-info3 0.3.0-1
libdjvulibre-text 3.5.29-1
libdjvulibre21 3.5.29-1
libdnnl3.6 3.9.1+ds-2
libdotconf0 1.4.1-1build1
libdpkg-perl 1.23.7ubuntu1
libdrm-amdgpu1 2.4.131-1
libdrm-common 2.4.131-1
libdrm-intel1 2.4.131-1
libdrm2 2.4.131-1
libduktape207 2.7.0+tests-0ubuntu4
libdv4t64 1.0.0-17.1build2
libdvdnav4 7.0.0-2
libdvdread8t64 7.0.1-1
libdw1t64 0.194-4
libeatmydata1 131-2build1
libebackend-1.2-11t64 3.56.2-8
libebook-1.2-21t64 3.56.2-8
libebook-contacts-1.2-4t64 3.56.2-8
libecal-2.0-3 3.56.2-8
libedata-book-1.2-27t64 3.56.2-8
libedata-cal-2.0-2t64 3.56.2-8
libedataserver-1.2-27t64 3.56.2-8
libedataserverui-1.2-4t64 3.56.2-8
libedataserverui4-1.0-0t64 3.56.2-8
libedit2 3.1-20251016-1
libeditorconfig0 0.12.10+~0.17.1-3ubuntu0.1
libefiboot1t64 39-2
libefivar1t64 39-2
libegl-mesa0 26.0.3-1ubuntu1
libegl1 1.7.0-3
libei1 1.5.0-3
libeis1 1.5.0-3
libelf1t64 0.194-4
libenchant-2-2 2.8.2+dfsg1-3build1
libencode-locale-perl 1.05-3
libepoxy0 1.5.10-2build1
libespeak-ng1 1.52.0+dfsg-5build1
libevdev2 1.13.6+dfsg-1
libevdocument3-4t64 48.1+dfsg-1build1
libevent-core-2.1-7t64 2.1.12-stable-10build2
libevent-extra-2.1-7t64 2.1.12-stable-10build2
libevview3-3t64 48.1+dfsg-1build1
libexempi8 2.6.6-2build1
libexif12 0.6.25-2
libexiv2-28 0.28.8+dfsg-1
libexiv2-data 0.28.8+dfsg-1
libexpat1 2.7.4-1
libext2fs2t64 1.47.2-3ubuntu4
libextutils-depends-perl 0.8002-1
libfaad2 2.11.2-1build1
libfarmhash0 0~git20190513.0d859a8-4
libfdisk1 2.41.3-3ubuntu2
libffi8 3.5.2-4
libffmpegthumbnailer4v5 2.3.0-1
libfftw3-double3 3.3.10-2fakesync1build3
libfftw3-single3 3.3.10-2fakesync1build3
libfido2-1 1.16.0-2build1
libfile-basedir-perl 0.09-2
libfile-desktopentry-perl 0.23-1
libfile-listing-perl 6.16-1
libfile-mimeinfo-perl 0.36-2
libflac14 1.5.0+ds-5
libflashrom1 1.6.0-2ubuntu1
libflatpak0 1.16.6-1
libflite1 2.2-7build1
libfluidsynth3 2.4.8+dfsg-1
libfolks-eds26 0.15.12-1
libfolks26 0.15.12-1
libfont-afm-perl 1.20-4
libfontconfig1 2.17.1-3ubuntu1
libfontenc1 1:1.1.8-1build2
libfprint-2-2 1:1.95.1+tod1-0ubuntu1
libfprint-2-tod1 1:1.95.1+tod1-0ubuntu1
libfreeaptx0 0.2.2-1build1
libfreerdp-client3-3 3.24.2+dfsg-1ubuntu1.1
libfreerdp-server3-3 3.24.2+dfsg-1ubuntu1.1
libfreerdp3-3 3.24.2+dfsg-1ubuntu1.1
libfreetype6 2.14.2+dfsg-1
libfribidi0 1.0.16-5
libftdi1-2 1.6~rc1-1build1
libfuse2t64 2.9.9-9build1
libfuse3-4 3.18.2-1
libfwupd3 2.1.1-1ubuntu3
libfyaml0 0.9.4-1
libgbm1 26.0.3-1ubuntu1
libgcc-s1 16-20260322-1ubuntu1
libgck-1-0 3.41.2-6
libgck-2-2 4.4.0.1-8
libgcr-4-4 4.4.0.1-8
libgcr-base-3-1 3.41.2-6
libgcr-ui-3-1 3.41.2-6
libgcrypt20 1.12.0-2ubuntu0.1
libgd3 2.3.3-13ubuntu2
libgdbm-compat4t64 1.26-1build1
libgdbm6t64 1.26-1build1
libgdk-pixbuf-2.0-0 2.44.5+dfsg-4ubuntu1
libgdk-pixbuf2.0-bin 2.44.5+dfsg-4ubuntu1
libgdk-pixbuf2.0-common 2.44.5+dfsg-4ubuntu1
libgdm1 50.0-0ubuntu1
libgee-0.8-2 0.20.8-2
libgeoclue-2-0 2.7.2-2ubuntu3
libgeocode-glib-2-0 3.26.4-3
libgexiv2-2 0.14.6-2
libgflags2.2 2.2.2-3
libgif7 5.2.2-1ubuntu3
libgio-2.0-dev-bin 2.88.0-1
libgirepository-1.0-1 1.86.0-6build1
libgirepository-2.0-0 2.88.0-1
libgjs0 1.88.0-1
libgl1 1.7.0-3
libgl1-mesa-dri 26.0.3-1ubuntu1
libgles2 1.7.0-3
libglib-object-introspection-perl 0.052-1
libglib-perl 3:1.329.4-1
libglib2.0-0t64 2.88.0-1
libglib2.0-bin 2.88.0-1
libglib2.0-data 2.88.0-1
libglib2.0-dev-bin 2.88.0-1
libglibmm-2.68-1t64 2.86.0-7
libglvnd0 1.7.0-3
libglx-mesa0 26.0.3-1ubuntu1
libglx0 1.7.0-3
libglycin-2-0 2.1.1+ds-0ubuntu1
libglycin-gtk4-2-0 2.1.1+ds-0ubuntu1
libgme0 0.6.4-1
libgmime-3.0-0t64 3.2.15+dfsg-1build2
libgmp10 2:6.3.0+dfsg-5ubuntu2
libgnome-autoar-0-0 0.4.5-5
libgnome-bg-4-2t64 44.5-1ubuntu1
libgnome-bluetooth-3.0-13 47.1-5
libgnome-bluetooth-ui-3.0-13 47.1-5
libgnome-desktop-3-20t64 44.5-1ubuntu1
libgnome-desktop-4-2t64 44.5-1ubuntu1
libgnome-menu-3-0 3.38.1-1ubuntu1
libgnome-qr-4-0 44.5-1ubuntu1
libgnutls30t64 3.8.12-2ubuntu1.1
libgoa-1.0-0b 3.58.0-1
libgoa-1.0-common 3.58.0-1
libgoa-backend-1.0-2 3.58.0-1
libgomp1 16-20260322-1ubuntu1
libgoogle-glog0v6t64 0.6.0-3
libgpg-error0 1.58-2
libgpgme45 2.0.1-2build1
libgpgmepp7 2.0.0-2
libgphoto2-6t64 2.5.33-1ubuntu1
libgphoto2-l10n 2.5.33-1ubuntu1
libgphoto2-port12t64 2.5.33-1ubuntu1
libgpm2 1.20.7-12build1
libgprofng0 2.46-3ubuntu2
libgraphene-1.0-0 1.10.8-5build1
libgraphite2-3 1.3.14-11ubuntu1.1
libgs-common 10.06.0~dfsg-3ubuntu1
libgs10 10.06.0~dfsg-3ubuntu1
libgs10-common 10.06.0~dfsg-3ubuntu1
libgsf-1-114 1.14.53-1.1
libgsf-1-common 1.14.53-1.1
libgsm1 1.0.23-2
libgsound0t64 1.0.3-4
libgspell-1-3 1.14.2-2
libgspell-1-common 1.14.2-2
libgssapi-krb5-2 1.22.1-2ubuntu4
libgssdp-1.6-0 1.6.4-5
libgstreamer-gl1.0-0 1.28.2-1
libgstreamer-plugins-bad1.0-0 1.28.2-1ubuntu1.1
libgstreamer-plugins-base1.0-0 1.28.2-1
libgstreamer-plugins-extra1.0-0 1.28.2-1ubuntu1.1
libgstreamer1.0-0 1.28.2-1
libgtk-3-0t64 3.24.52-0ubuntu1
libgtk-3-bin 3.24.52-0ubuntu1
libgtk-3-common 3.24.52-0ubuntu1
libgtk-4-1 4.22.4+ds-0ubuntu0.1
libgtk-4-bin 4.22.4+ds-0ubuntu0.1
libgtk-4-common 4.22.4+ds-0ubuntu0.1
libgtk3-perl 0.038-3
libgtkmm-4.0-0 4.20.0-1build1
libgtksourceview-4-0 4.8.4-9
libgtksourceview-4-common 4.8.4-9
libgtksourceview-5-0 5.18.0-3
libgtksourceview-5-common 5.18.0-3
libgtop-2.0-11 2.41.3-2ubuntu1
libgtop2-common 2.41.3-2ubuntu1
libgudev-1.0-0 1:238-7build1
libgupnp-1.6-0 1.6.9-4
libgupnp-av-1.0-3 0.14.4-3
libgupnp-dlna-2.0-4 0.12.0-8
libgupnp-igd-1.6-0 1.6.0-5
libgusb2a 0.4.9-7
libgutenprint-common 5.3.4.20220624T01008808d602-4ubuntu2
libgutenprint9 5.3.4.20220624T01008808d602-4ubuntu2
libgweather-4-0t64 4.4.4-4
libgweather-4-common 4.4.4-4
libgxps2t64 0.3.2-6
libhandy-1-0 1.8.3-3build1
libharfbuzz-gobject0 12.3.2-2
libharfbuzz-icu0 12.3.2-2
libharfbuzz-subset0 12.3.2-2
libharfbuzz0b 12.3.2-2
libheif-plugin-aomdec 1.21.2-3ubuntu0.1
libheif-plugin-aomenc 1.21.2-3ubuntu0.1
libheif1 1.21.2-3ubuntu0.1
libhogweed6t64 3.10.2-1
libhpmud0 3.24.4+dfsg0-0ubuntu8
libhtml-form-perl 6.13-1build1
libhtml-format-perl 2.16-2
libhtml-parser-perl 3.83-1build1
libhtml-tagset-perl 3.24-1
libhtml-tree-perl 5.07-3
libhttp-cookies-perl 6.11-1
libhttp-daemon-perl 6.16-1ubuntu0.26.04.1
libhttp-date-perl 6.06-1
libhttp-message-perl 7.01-1ubuntu1
libhttp-negotiate-perl 6.01-2
libhunspell-1.7-0 1.7.2+really1.7.2-11
libhwy1t64 1.3.0-2
libhyphen0 2.8.8-7build4
libibus-1.0-5 1.5.34~rc2-1
libibverbs1 61.0-2ubuntu3
libical3t64 3.0.20-2build1
libice6 2:1.1.1-1build1
libicu78 78.2-2ubuntu1
libidn12 1.43-2build1
libidn2-0 2.3.8-4build1
libiec61883-0 1.2.0-8
libieee1284-3t64 0.2.11-14.1build2
libijs-0.35 0.35-16
libimagequant0 4.4.1-1
libimath-3-1-29t64 3.1.12-1ubuntu5
libimobiledevice-1.0-6 1.4.0-1build1
libimobiledevice-glue-1.0-0 1.3.2-2build1
libini-config5t64 0.6.2-3build1
libinih1 61-1ubuntu1
libinireader0 61-1ubuntu1
libinput-bin 1.31.1-1
libinput10 1.31.1-1
libinsights0 0.9.3ubuntu
libinstpatch-1.0-2 1.1.7-1.1
libio-html-perl 1.004-3
libio-socket-ssl-perl 2.098-1
libio-stringy-perl 2.113-2
libip4tc2 1.8.11-2ubuntu3
libip6tc2 1.8.11-2ubuntu3
libipa-hbac0t64 2.12.0-1ubuntu5.1
libipc-system-simple-perl 1.30-2
libisl23 0.27-1build1
libisoburn1t64 1:1.5.6-1.1ubuntu4
libisofs6t64 1.5.6.pl01-1.1ubuntu3
libiw30t64 30~pre9-18ubuntu2
libjack-jackd2-0 1.9.22~dfsg-5build1
libjansson4 2.14-2build4
libjavascriptcoregtk-4.1-0 2.52.3-0ubuntu0.26.04.2
libjavascriptcoregtk-6.0-1 2.52.3-0ubuntu0.26.04.2
libjbig0 2.1-6.1ubuntu3
libjbig2dec0 0.20-1build4
libjcat1 0.2.5-1build1
libjemalloc2 5.3.0-4
libjpeg-turbo8 2.1.5-4ubuntu4
libjpeg8 8c-2ubuntu12
libjq1 1.8.1-4ubuntu2
libjson-c5 0.18+ds-3
libjson-glib-1.0-0 1.10.8+ds-2
libjson-glib-1.0-common 1.10.8+ds-2
libjxl-gdk-pixbuf 0.11.1-6ubuntu4.2
libjxl0.11 0.11.1-6ubuntu4.2
libjxr-tools 1.2~git20170615.f752187-5.3build1
libjxr0t64 1.2~git20170615.f752187-5.3build1
libk5crypto3 1.22.1-2ubuntu4
libkeyutils1 1.6.3-6ubuntu3
libklibc 2.0.14-1ubuntu2
libkmod2 34.2-2ubuntu2
libkpathsea6 2025.20250727.75242+ds-5build1
libkrb5-3 1.22.1-2ubuntu4
libkrb5support0 1.22.1-2ubuntu4
libksba8 1.6.7-2build1
liblc3-1 1.1.3+dfsg-1build1
liblcms2-2 2.17-1ubuntu0.2
liblcms2-utils 2.17-1ubuntu0.2
libldacbt-abr2 2.0.2.3+git20200429+ed310a0-5build1
libldacbt-enc2 2.0.2.3+git20200429+ed310a0-5build1
libldap-common 2.6.10+dfsg-1ubuntu5
libldap2 2.6.10+dfsg-1ubuntu5
libldb2 2:2.11.0+samba4.23.6+dfsg-1ubuntu2.1
liblerc4 4.0.0+ds-5ubuntu2
libleveldb1d 1.23-6
liblilv-0-0 0.26.2-1
libllvm21 1:21.1.8-6ubuntu1
liblmdb0 0.9.31-1build2
liblocale-gettext-perl 1.07-8
liblouis-data 3.36.0-1
liblouis20 3.36.0-1
liblouisutdml-bin 2.12.0-8build1
liblouisutdml-data 2.12.0-8build1
liblouisutdml9t64 2.12.0-8build1
liblqr-1-0 0.4.2-2.2
liblrdf0 0.6.1-5
liblsof0 4.99.4+dfsg-2build2
libltc11 1.3.2-1build2
libltdl7 2.5.4-9
liblttng-ust-common1t64 2.14.0-1.1
liblttng-ust-ctl6 2.14.0-1.1
liblttng-ust1t64 2.14.0-1.1
liblua5.2-0 5.2.4-4
liblua5.4-0 5.4.8-1build1
liblvm2cmd2.03 2.03.31-2ubuntu3
liblwp-mediatypes-perl 6.04-2
liblwp-protocol-https-perl 6.14-1
liblz4-1 1.10.0-8
liblzma5 5.8.3-1
liblzo2-2 2.10-3build2
libmagic-mgc 1:5.46-5build2
libmagic1t64 1:5.46-5build2
libmagickcore-7.q16-10 8:7.1.2.18+dfsg1-1
libmagickcore-7.q16-10-extra 8:7.1.2.18+dfsg1-1
libmagickwand-7.q16-10 8:7.1.2.18+dfsg1-1
libmailtools-perl 2.22-1
libmalcontent-0-0 0.14.0-0ubuntu1.1
libmalcontent-common 0.14.0-0ubuntu1.1
libmarisa1 0.3.1+git20250817-1build1
libmaxminddb0 1.12.2-1build2
libmbedcrypto16 3.6.5-0.1ubuntu2
libmbim-glib4 1.32.0-2ubuntu1
libmbim-proxy 1.32.0-2ubuntu1
libmbim-utils 1.32.0-2ubuntu1
libmd0 1.1.0-2build4
libmediaart-2.0-0 1.9.7-3
libmessaging-menu0 24.5.1-1build1
libminiupnpc21 2.3.3-2build1
libmjpegutils-2.2-0 1:2.2.1-3
libmm-glib0 1.25.95-1ubuntu1
libmnl0 1.0.5-3build1
libmodplug1 1:0.8.9.0-3build2
libmount1 2.41.3-3ubuntu2
libmozjs-140-0 140.8.0-4
libmp3lame0 3.101~svn6525+dfsg-2
libmpc3 1.3.1-3
libmpcdec6 2:0.1~r495-3build1
libmpeg2-4 0.5.1-10
libmpeg2encpp-2.2-0 1:2.2.1-3
libmpfr6 4.2.2-3
libmpg123-0t64 1.33.3-2
libmplex2-2.2-0 1:2.2.1-3
libmpv2 0.41.0-2ubuntu4
libmsgraph-1-1 0.3.3-3build1
libmtdev1t64 1.1.7-1build1
libmtp-common 1.1.22-1ubuntu1
libmtp-runtime 1.1.22-1ubuntu1
libmtp9t64 1.1.22-1ubuntu1
libmujs3 1.3.8-2
libmutter-18-0 50.1-0ubuntu2.2
libmysofa1 1.3.3+dfsg-1ubuntu2
libnatpmp1t64 20230423-1.2build4
libnautilus-extension4 1:50.0-0ubuntu2
libncurses6 6.6+20251231-1
libncursesw6 6.6+20251231-1
libndp0 1.9-1build1
libneon27t64 0.36.0-1
libnet-dbus-perl 1.2.0-2build4
libnet-http-perl 6.24-1build1
libnet-smtp-ssl-perl 1.04-2
libnet-ssleay-perl 1.94-3
libnetfilter-conntrack3 1.1.1-1
libnetplan1 1.2-1ubuntu5
libnettle8t64 3.10.2-1
libnewt0.52 0.52.25-1ubuntu3
libnfnetlink0 1.0.2-3build1
libnfs14 5.0.2-1ubuntu1.1
libnfsidmap1 1:2.8.5-1ubuntu1
libnftables1 1.1.6-1
libnftnl11 1.3.1-1
libnghttp2-14 1.68.0-2ubuntu0.1
libnice10 0.1.23-2
libnl-3-200 3.12.0-2
libnl-genl-3-200 3.12.0-2
libnl-route-3-200 3.12.0-2
libnm0 1.54.3-2ubuntu3
libnma-common 1.10.6-7
libnma-gtk4-0 1.10.6-7
libnma0 1.10.6-7
libnorm1t64 1.5.9+dfsg-4
libnotify4 0.8.8-1
libnpth0t64 1.8-3build1
libnspr4 2:4.38.2-1ubuntu1
libnss-mdns 0.15.1-5
libnss-sss 2.12.0-1ubuntu5.1
libnss-systemd 259.5-0ubuntu3
libnss3 2:3.120-1ubuntu2
libntfs-3g89t64 1:2022.10.3-5ubuntu1
libnuma1 2.0.19-1build1
libnvme1t64 1.16.1-4
liboeffis1 1.5.0-3
libogg0 1.3.6-2
libonig5 6.9.10-1build1
libonnx1t64 1.20.0-1
libonnxruntime-providers 1.23.2+dfsg-6ubuntu1
libonnxruntime1.23 1.23.2+dfsg-6ubuntu1
libopenal-data 1:1.25.1-2
libopenal1 1:1.25.1-2
libopencc-data 1.1.9+ds1-4build1
libopencc1.1 1.1.9+ds1-4build1
libopencore-amrnb0 0.1.6-1build2
libopencore-amrwb0 0.1.6-1build2
libopenexr-3-1-30 3.1.13-2build1
libopengl0 1.7.0-3
libopenh264-8 2.6.0+dfsg-2build1
libopenjp2-7 2.5.4-1ubuntu0.1
libopenmpt0t64 0.8.4-1
libopenni2-0 2.2.0.33+dfsg-19
libopus0 1.6.1-1
liborc-0.4-0t64 1:0.4.42-2
libostree-1-1 2025.7-3build1
libp11-kit0 0.26.2-2
libpackagekit-glib2-18 1.3.4-3ubuntu1.1
libpam-cap 1:2.75-10ubuntu2
libpam-fprintd 1.94.5-4
libpam-gnome-keyring 50.0-1
libpam-modules 1.7.0-5ubuntu3
libpam-modules-bin 1.7.0-5ubuntu3
libpam-pwquality 1.4.5-5build1
libpam-runtime 1.7.0-5ubuntu3
libpam-sss 2.12.0-1ubuntu5.1
libpam-systemd 259.5-0ubuntu3
libpam0g 1.7.0-5ubuntu3
libpango-1.0-0 1.57.0-1
libpangocairo-1.0-0 1.57.0-1
libpangoft2-1.0-0 1.57.0-1
libpangomm-2.48-1t64 2.56.1-2
libpangoxft-1.0-0 1.57.0-1
libpaper-utils 2.2.5-0.3maysync1
libpaper2 2.2.5-0.3maysync1
libparted-fs-resize0t64 3.6-6
libparted2t64 3.6-6
libpath-utils1t64 0.6.2-3build1
libpcap0.8t64 1.10.6-1ubuntu1
libpcaudio0 1.3-1build1
libpci3 1:3.14.0-1build2
libpciaccess0 0.18.1-1ubuntu4
libpcre2-8-0 10.46-1build1
libpcsclite1 2.4.1-1
libpeas-1.0-1 1.38.1-4ubuntu1
libpeas-common 1.38.1-4ubuntu1
libperl5.40 5.40.1-7ubuntu0.1
libpgm-5.3-0t64 5.3.128~dfsg-2.1build2
libphonenumber8 8.13.51+ds-5
libpipeline1 1.5.8-2
libpipewire-0.3-0t64 1.6.2-1ubuntu1
libpipewire-0.3-common 1.6.2-1ubuntu1
libpipewire-0.3-modules 1.6.2-1ubuntu1
libpixman-1-0 0.46.4-1
libpkcs11-helper1t64 1.31.0-1
libplacebo360 7.360.0-3
libplist-2.0-4 2.7.0+git20250820-1build1
libplymouth5 24.004.60+git20250831.4a3c171d-0ubuntu8
libpng16-16t64 1.6.57-1
libpolkit-agent-1-0 127-2ubuntu1
libpolkit-gobject-1-0 127-2ubuntu1
libpoppler-cpp3 26.01.0-2ubuntu0.1
libpoppler-glib8t64 26.01.0-2ubuntu0.1
libpoppler156 26.01.0-2ubuntu0.1
libpopt0 1.19+dfsg-2build1
libportal-gtk4-1 0.9.1-2build1
libportal1 0.9.1-2build1
libppd2 2:2.1.1-0ubuntu2
libppd2-common 2:2.1.1-0ubuntu2
libppsdocument-4.0-6 50.1-0ubuntu1.1
libppsview-4.0-5 50.1-0ubuntu1.1
libproc2-0 2:4.0.4-9ubuntu1
libprotobuf32t64 3.21.12-15ubuntu1
libproxy1v5 0.5.12-1
libpsl5t64 0.21.2-1.1build2
libpthreadpool0 0.0~git20251020.0e6ca13-1
libpulse-mainloop-glib0 1:17.0+dfsg1-2ubuntu4
libpulse0 1:17.0+dfsg1-2ubuntu4
libpwquality-common 1.4.5-5build1
libpwquality1 1.4.5-5build1
libpython3-stdlib 3.14.3-0ubuntu2
libpython3.14 3.14.4-1
libpython3.14-minimal 3.14.4-1
libpython3.14-stdlib 3.14.4-1
libqmi-glib5 1.38.0-1
libqmi-proxy 1.38.0-1
libqmi-utils 1.38.0-1
libqpdf30 12.3.2-1
libqrencode4 4.1.1-2build1
libqrtr-glib0 1.2.2-2ubuntu1
librabbitmq4 0.15.0-1ubuntu0.26.04.1
libraptor2-0 2.0.16-6build1
librav1e0.8 0.8.1-7
libraw1394-11 2.1.2-2build4
libraw23t64 0.21.5b-1ubuntu1
libre2-11 20250805-1build3
libreadline8t64 8.3-4
libref-array1t64 0.6.2-3build1
librest-1.0-0 0.10.2-1
librime-bin 1.16.1+dfsg1-1build1
librime-data 0.39+debian-1
librime-plugin-charcode 1.16.1+dfsg1~git20240319-1build1
librime-plugin-lua 1.16.1+dfsg1~git20250707-1build1
librime-plugin-octagram 1.16.1+dfsg1~git20241118-1build1
librime1t64 1.16.1+dfsg1-1build1
librist4 0.2.11+dfsg-1build1
libroc0.4 0.4.0+dfsg-5ubuntu3
librsvg2-2 2.61.3+dfsg-3
librsvg2-common 2.61.3+dfsg-3
librtmp1 2.4+20151223.gitfa8646d.1-3
librubberband3 4.0.0+dfsg-2ubuntu1
librygel-core-2.8-0 45.0-1ubuntu1
librygel-db-2.8-0 45.0-1ubuntu1
librygel-renderer-2.8-0 45.0-1ubuntu1
librygel-server-2.8-0 45.0-1ubuntu1
libsamplerate0 0.2.2-4build2
libsane-common 1.4.0-1ubuntu1
libsane1 1.4.0-1ubuntu1
libsasl2-2 2.1.28+dfsg1-9ubuntu3
libsasl2-modules 2.1.28+dfsg1-9ubuntu3
libsasl2-modules-db 2.1.28+dfsg1-9ubuntu3
libsasl2-modules-gssapi-mit 2.1.28+dfsg1-9ubuntu3
libsass1 3.6.6-0ubuntu3
libsbc1 2.1-1build1
libsdl2-2.0-0 2.32.10+dfsg-6
libsdl2-classic 2.32.10+dfsg-6
libsdl3-0 3.4.2+ds-1ubuntu1
libseccomp2 2.6.0-2ubuntu5
libsecret-1-0 0.21.7-2build1
libsecret-common 0.21.7-2build1
libselinux1 3.9-4build1
libsemanage-common 3.9-1build1
libsemanage2 3.9-1build1
libsensors-config 1:3.6.2-2build1
libsensors5 1:3.6.2-2build1
libsepol2 3.9-2
libserd-0-0 0.32.6-1
libsframe3 2.46-3ubuntu2
libsharpyuv0 1.5.0-0.1build1
libshine3 3.1.1-3build1
libshout3 2.4.6-1build3
libsidplay1v5 1.36.60-1build2
libsigc++-3.0-0 3.6.0-2build1
libsimdutf31 8.0.0-1
libsixel1 1.10.5-1build1
libslang2 2.3.3-5build1
libsm6 2:1.2.6-1build1
libsmartcols1 2.41.3-3ubuntu2
libsmbclient0 2:4.23.6+dfsg-1ubuntu2.1
libsnapd-glib-2-1 1.72-0ubuntu3
libsnappy1v5 1.2.2-2
libsndfile1 1.2.2-4
libsndio7.0 1.10.0-0.2
libsnmp-base 5.9.4+dfsg-2ubuntu3
libsnmp40t64 5.9.4+dfsg-2ubuntu3
libsodium23 1.0.18-2
libsonic0 0.2.0-13build2
libsord-0-0 0.16.20-1
libsoundtouch1 2.4.0+ds-1build1
libsoup-3.0-0 3.6.6-1
libsoup-3.0-common 3.6.6-1
libsoxr0 0.1.3-4.1
libspa-0.2-bluetooth 1.6.2-1ubuntu1
libspa-0.2-libcamera 1.6.2-1ubuntu1
libspa-0.2-modules 1.6.2-1ubuntu1
libspandsp2t64 0.0.6+dfsg-2.2build2
libspectre1 0.2.12-2
libspeechd-module0 0.12.1-2ubuntu1
libspeechd2 0.12.1-2ubuntu1
libspeex1 1.2.1-3build1
libspeexdsp1 1.2.1-3build1
libspelling-1-2 0.4.9-1build1
libspelling-common 0.4.9-1build1
libsqlite3-0 3.46.1-9
libsratom-0-0 0.6.20-1
libsrt1.5-gnutls 1.5.4-3
libsrtp2-1 2.7.0-3build1
libss2 1.47.2-3ubuntu4
libssh-4 0.11.3-1ubuntu1
libssh2-1t64 1.11.1-1ubuntu0.26.04.1
libssl3t64 3.5.5-1ubuntu3.2
libsss-certmap0 2.12.0-1ubuntu5.1
libsss-idmap0 2.12.0-1ubuntu5.1
libsss-nss-idmap0 2.12.0-1ubuntu5.1
libstartup-notification0 0.12-8build1
libstdc++6 16-20260322-1ubuntu1
libstemmer0d 3.0.1-1
libsvtav1enc2 2.3.0+dfsg-1build1
libswresample6 7:8.0.1-3ubuntu2
libswscale9 7:8.0.1-3ubuntu2
libsynctex2 2025.20250727.75242+ds-5build1
libsystemd-shared 259.5-0ubuntu3
libsystemd0 259.5-0ubuntu3
libtag2 2.2.1-3
libtalloc2 2:2.4.3+samba4.23.6+dfsg-1ubuntu2.1
libtasn1-6 4.21.0-2
libtcl8.6 8.6.17+dfsg-1build1
libtdb1 2:1.4.14+samba4.23.6+dfsg-1ubuntu2.1
libteamdctl0 1.31-1build4
libtensorflow-lite2.14.1 2.14.1+dfsg-3build1
libtevent0t64 2:0.17.1+samba4.23.6+dfsg-1ubuntu2.1
libtext-charwidth-perl 0.04-11build4
libtext-iconv-perl 1.7-8.1
libtext-wrapi18n-perl 0.06-10
libthai-data 0.1.30-1
libthai0 0.1.30-1
libtheora1 1.2.0+dfsg-6
libtheoradec2 1.2.0+dfsg-6
libtheoraenc2 1.2.0+dfsg-6
libtie-ixhash-perl 1.23-4
libtiff6 4.7.0-3ubuntu4
libtimedate-perl 2.3300-2
libtimezonemap-data 0.4.6-7build1
libtimezonemap1 0.4.6-7build1
libtinfo6 6.6+20251231-1
libtinysparql-3.0-0 3.11.0-1
libtirpc-common 1.3.7-0.1
libtirpc3t64 1.3.7-0.1
libtotem-plparser-common 3.26.6-3
libtotem-plparser18 3.26.6-3
libtry-tiny-perl 0.32-1
libtss2-esys-3.0.2-0t64 4.1.3-6
libtss2-mu-4.0.1-0t64 4.1.3-6
libtss2-rc0t64 4.1.3-6
libtss2-sys1t64 4.1.3-6
libtss2-tcti-cmd0t64 4.1.3-6
libtss2-tcti-device0t64 4.1.3-6
libtss2-tcti-libtpms0t64 4.1.3-6
libtss2-tcti-mssim0t64 4.1.3-6
libtss2-tcti-spi-helper0t64 4.1.3-6
libtss2-tcti-swtpm0t64 4.1.3-6
libtss2-tctildr0t64 4.1.3-6
libtwolame0 0.4.0-2build4
libuchardet0 0.0.8-2
libudev1 259.5-0ubuntu3
libudfread3 1.2.0-2
libudisks2-0 2.10.91-1ubuntu2
libunibreak6 6.1-3build1
libunistring5 1.3-2build1
libunity-protocol-private0 7.1.4+19.04.20190319-6.1ubuntu1
libunity-scopes-json-def-desktop 7.1.4+19.04.20190319-6.1ubuntu1
libunity9 7.1.4+19.04.20190319-6.1ubuntu1
libunwind8 1.8.3-0ubuntu1
libupower-glib3 1.91.1-1
liburcu8t64 0.15.6-1
liburi-perl 5.34-2build1
libusb-1.0-0 2:1.0.29-2build1
libusbmuxd-2.0-7 2.1.1-1
libuuid1 2.41.3-3ubuntu2
libuv1t64 1.51.0-2ubuntu1
libv4l-0t64 1.32.0-2ubuntu1
libv4lconvert0t64 1.32.0-2ubuntu1
libva-drm2 2.23.0-1ubuntu1
libva-wayland2 2.23.0-1ubuntu1
libva-x11-2 2.23.0-1ubuntu1
libva2 2.23.0-1ubuntu1
libvdpau1 1.5-4
libvidstab1.1 1.1.0-2.1
libvisual-0.4-0 0.4.2-4
libvncclient1 0.9.15+dfsg-3ubuntu0.1
libvo-aacenc0 0.1.3-3build1
libvo-amrwbenc0 0.1.3-2build2
libvolume-key1 0.3.12-10build2
libvorbis0a 1.3.7-3build2
libvorbisenc2 1.3.7-3build2
libvorbisfile3 1.3.7-3build2
libvpl2 1:2.16.0-1
libvpx12 1.16.0-3
libvte-2.91-0 0.84.0-2
libvte-2.91-common 0.84.0-2
libvte-2.91-gtk4-0 0.84.0-2
libvulkan1 1.4.341.0-1
libwacom-common 2.18.0-1
libwacom9 2.18.0-1
libwavpack1 5.9.0-1
libwayland-client0 1.24.0-2
libwayland-cursor0 1.24.0-2
libwayland-egl1 1.24.0-2
libwayland-server0 1.24.0-2
libwbclient0 2:4.23.6+dfsg-1ubuntu2.1
libwebkit2gtk-4.1-0 2.52.3-0ubuntu0.26.04.2
libwebkitgtk-6.0-4 2.52.3-0ubuntu0.26.04.2
libwebp7 1.5.0-0.1build1
libwebpdemux2 1.5.0-0.1build1
libwebpmux3 1.5.0-0.1build1
libwebrtc-audio-processing-1-3 1.3-3build2
libwhoopsie-preferences0 23build4
libwhoopsie0 0.2.82ubuntu
libwildmidi2 0.4.6-1
libwinpr3-3 3.24.2+dfsg-1ubuntu1.1
libwireplumber-0.5-0 0.5.13-1ubuntu1
libwmflite-0.2-7 0.2.14-1
libwnck-3-0 43.3-1build1
libwnck-3-common 43.3-1build1
libwrap0 7.6.q-36build2
libwww-perl 6.81-1ubuntu0.1
libwww-robotrules-perl 6.02-1build1
libx11-6 2:1.8.13-1
libx11-data 2:1.8.13-1
libx11-protocol-perl 0.56-9
libx11-xcb1 2:1.8.13-1
libx264-165 2:0.165.3222+gitb35605ac-3build1
libx265-215 4.1-4
libxau6 1:1.0.11-1build2
libxaw7 2:1.0.16-1build1
libxcb-dri3-0 1.17.0-2ubuntu1
libxcb-glx0 1.17.0-2ubuntu1
libxcb-present0 1.17.0-2ubuntu1
libxcb-randr0 1.17.0-2ubuntu1
libxcb-render0 1.17.0-2ubuntu1
libxcb-res0 1.17.0-2ubuntu1
libxcb-shape0 1.17.0-2ubuntu1
libxcb-shm0 1.17.0-2ubuntu1
libxcb-sync1 1.17.0-2ubuntu1
libxcb-util1 0.4.1-1build1
libxcb-xfixes0 1.17.0-2ubuntu1
libxcb-xkb1 1.17.0-2ubuntu1
libxcb1 1.17.0-2ubuntu1
libxcomposite1 1:0.4.6-1build1
libxcursor1 1:1.2.3-1build1
libxcvt0 0.1.3-1build1
libxdamage1 1:1.1.7-1
libxdmcp6 1:1.1.5-2
libxext6 2:1.3.4-1build3
libxfixes3 1:6.0.0-2build2
libxfont2 1:2.0.6-2
libxft2 2.3.6-1build2
libxi6 2:1.8.2-2
libxinerama1 2:1.1.4-3build2
libxkbcommon-x11-0 1.13.1-1
libxkbcommon0 1.13.1-1
libxkbfile1 1:1.1.0-1build5
libxkbregistry0 1.13.1-1
libxklavier16 5.4-6build1
libxml-parser-perl 2.47-1ubuntu1
libxml-twig-perl 1:3.54-1build1
libxml-xpathengine-perl 0.14-2
libxml2-16 2.15.2+dfsg-0.1ubuntu0.1
libxmlb2 0.3.24-2
libxmu6 2:1.1.3-4
libxmuu1 2:1.1.3-4
libxnnpack0.20241108 0.0~git20241108.4ea82e5-2build1
libxpm4 1:3.5.17-1build3
libxpresent1 1.0.1-1build1
libxrandr2 2:1.5.4-1build1
libxrender1 1:0.9.12-1build1
libxres1 2:1.2.1-1build2
libxshmfence1 1.3.3-1build1
libxslt1.1 1.1.45-0.1
libxss1 1:1.2.3-1build4
libxt6t64 1:1.2.1-1.3build1
libxtables12 1.8.11-2ubuntu3
libxtst6 2:1.2.5-1build1
libxv1 2:1.0.13-1
libxvidcore4 2:1.3.7-3
libxxf86dga1 2:1.1.5-1build2
libxxf86vm1 1:1.1.4-2
libxxhash0 0.8.3-2build1
libyajl2 2.1.0-5.1
libyaml-0-2 0.2.5-2build3
libyaml-cpp0.8 0.8.0+dfsg-9
libyelp-1-0 49.0-5
libytnef0 2.1.2-1build2
libyuv0 0.0.1922.20260106-1
libyyjson0 0.12.0+ds-1
libzbar0t64 0.23.93-9ubuntu1
libzimg2 3.0.6+ds1-1
libzix-0-0 0.8.0-1
libzmq5 4.3.5-1build3
libzstd1 1.5.7+dfsg-3
libzvbi-common 0.2.44-1ubuntu2
libzvbi0t64 0.2.44-1ubuntu2
libzxing3 2.3.0-5
linux-base 4.15ubuntu5
linux-firmware 20260319.git217ca6e4.1ubuntu
linux-firmware-amd-graphics 20260319.git217ca6e4-0ubuntu3
linux-firmware-amd-misc 20260319.git217ca6e4-0ubuntu1
linux-firmware-broadcom-wireless 20260319.git217ca6e4-0ubuntu1
linux-firmware-intel-graphics 20260319.git217ca6e4-0ubuntu2
linux-firmware-intel-misc 20260319.git217ca6e4-0ubuntu1
linux-firmware-intel-wireless 20260319.git217ca6e4-0ubuntu2
linux-firmware-marvell-prestera 20260319.git217ca6e4-0ubuntu1
linux-firmware-marvell-wireless 20260319.git217ca6e4-0ubuntu1
linux-firmware-mediatek 20260319.git217ca6e4-0ubuntu1
linux-firmware-mellanox-spectrum 20260319.git217ca6e4-0ubuntu1
linux-firmware-misc 20260319.git217ca6e4-0ubuntu2
linux-firmware-netronome 20260319.git217ca6e4-0ubuntu1
linux-firmware-nvidia-graphics 20260319.git217ca6e4-0ubuntu1
linux-firmware-qlogic 20260319.git217ca6e4-0ubuntu1
linux-firmware-qualcomm-graphics 20260319.git217ca6e4-0ubuntu1
linux-firmware-qualcomm-misc 20260319.git217ca6e4-0ubuntu2
linux-firmware-qualcomm-wireless 20260319.git217ca6e4-0ubuntu1
linux-firmware-realtek 20260319.git217ca6e4-0ubuntu1
linux-headers-7.0.0-27 7.0.0-27.27
linux-headers-7.0.0-27-generic 7.0.0-27.27
linux-headers-generic-hwe-26.04 7.0.0-27.27
linux-image-7.0.0-27-generic 7.0.0-27.27
linux-image-generic-hwe-26.04 7.0.0-27.27
linux-main-modules-zfs-7.0.0-27-generic 7.0.0-27.27
linux-modules-7.0.0-27-generic 7.0.0-27.27
linux-sound-base 1.0.25+dfsg-0ubuntu9
linux-sysctl-defaults 4.15ubuntu5
localechooser-data 2.89ubuntu7
locales 2.43-2ubuntu2
localsearch 3.11.0-1ubuntu1.1
login 1:4.16.0-2+really2.41.3-3ubuntu2
login.defs 1:4.17.4-2ubuntu3
logrotate 3.22.0-1build1
logsave 1.47.2-3ubuntu4
loupe 50.0-0ubuntu2
lsb-release 12.1-2build1
lshw 02.19.git.2021.06.19.996aaad9c7-2.1ubuntu3
lsof 4.99.4+dfsg-2build2
luit 2.0.20250912-1
lvm2 2.03.31-2ubuntu3
lzma 25.00+dfsg-1
man-db 2.13.1-1build1
manpages 6.17-1
manpages-dev 6.17-1
mawk 1.3.4.20260129-1
mdadm 4.5-5ubuntu1
media-types 14.0.0build1
mesa-libgallium 26.0.3-1ubuntu1
mesa-vulkan-drivers 26.0.3-1ubuntu1
mobile-broadband-provider-info 20251101-1build1
modemmanager 1.25.95-1ubuntu1
mokutil 0.7.2-2
mount 2.41.3-3ubuntu2
mscompress 0.4-10build2
mtr-tiny 0.95-1.1ubuntu2
mutter-common 50.1-0ubuntu2.2
mutter-common-bin 50.1-0ubuntu2.2
nano 8.7.1-1ubuntu0.1
native-architecture 0.2.6build1
nautilus 1:50.0-0ubuntu2
nautilus-data 1:50.0-0ubuntu2
ncurses-base 6.6+20251231-1
ncurses-bin 6.6+20251231-1
net-tools 2.10-2ubuntu1
netbase 6.5build1
netplan-generator 1.2-1ubuntu5
netplan.io 1.2-1ubuntu5
network-manager 1.54.3-2ubuntu3
network-manager-l10n 1.54.3-2ubuntu3
network-manager-openvpn 1.12.5-1
network-manager-openvpn-gnome 1.12.5-1
network-manager-pptp 1.2.12-6
network-manager-pptp-gnome 1.2.12-6
networkd-dispatcher 2.2.4-1.1ubuntu1
nftables 1.1.6-1
nm-connection-editor 1.36.0-4ubuntu1
ntfs-3g 1:2022.10.3-5ubuntu1
numactl 2.0.19-1build1
ocl-icd-libopencl1 2.3.4-1
openssh-client 1:10.2p1-2ubuntu3.2
openssl 3.5.5-1ubuntu3.2
openssl-provider-legacy 3.5.5-1ubuntu3.2
openvpn 2.7.0-1ubuntu1.1
orca 50.1.2-1ubuntu1
os-prober 1.84ubuntu1
p11-kit 0.26.2-2
p11-kit-modules 0.26.2-2
packagekit 1.3.4-3ubuntu1.1
papers 50.1-0ubuntu1.1
papers-common 50.1-0ubuntu1.1
parted 3.6-6
passwd 1:4.17.4-2ubuntu3
patch 2.8-2build1
pci.ids 0.0~2026.02.12-1
pciutils 1:3.14.0-1build2
perl 5.40.1-7ubuntu0.1
perl-base 5.40.1-7ubuntu0.1
perl-modules-5.40 5.40.1-7ubuntu0.1
perl-openssl-defaults 7build4
pinentry-gnome3 1.3.2-3ubuntu1
pipewire 1.6.2-1ubuntu1
pipewire-alsa 1.6.2-1ubuntu1
pipewire-audio 1.6.2-1ubuntu1
pipewire-bin 1.6.2-1ubuntu1
pipewire-pulse 1.6.2-1ubuntu1
pkexec 127-2ubuntu1
plymouth 24.004.60+git20250831.4a3c171d-0ubuntu8
plymouth-anduinos 2.0.0+24.004.60+git20250831.4a3c171d-0ubuntu8-1+resolute-addon
plymouth-label 24.004.60+git20250831.4a3c171d-0ubuntu8
plymouth-theme-ubuntu-text 24.004.60+git20250831.4a3c171d-0ubuntu8
pnp.ids 0.394-1build1
policykit-desktop-privileges 0.22build1
polkitd 127-2ubuntu1
poppler-data 0.4.12-1build1
poppler-utils 26.01.0-2ubuntu0.1
power-profiles-daemon 0.30-2
powermgmt-base 1.38ubuntu2
ppp 2.5.2-1+1.2
pptp-linux 1.10.0-2build1
printer-driver-all 0.20210903build1
printer-driver-brlaser 6.2.8-1
printer-driver-c2050 0.3b-10build1
printer-driver-c2esp 27-11ubuntu8
printer-driver-cjet 0.8.9-11build1
printer-driver-dymo 1.4.0-12build3
printer-driver-escpr 1.8.7-1
printer-driver-foo2zjs 20200505dfsg0-3ubuntu1
printer-driver-foo2zjs-common 20200505dfsg0-3ubuntu1
printer-driver-fujixerox 1.1.0+ds-4build3
printer-driver-gutenprint 5.3.4.20220624T01008808d602-4ubuntu2
printer-driver-hpcups 3.24.4+dfsg0-0ubuntu8
printer-driver-indexbraille 1.2.3-5build1
printer-driver-m2300w 0.51-15build3
printer-driver-min12xxw 0.0.9-11build4
printer-driver-oki 1.0.2-3
printer-driver-pnm2ppa 1.13+nondbs-0ubuntu11
printer-driver-postscript-hp 3.24.4+dfsg0-0ubuntu8
printer-driver-ptouch 1.7.1-1build1
printer-driver-pxljr 1.4+repack0-6build3
printer-driver-sag-gdi 0.1-8build1
printer-driver-splix 2.0.1-2
procps 2:4.0.4-9ubuntu1
psmisc 23.7-2ubuntu2
ptyxis 50.1-1ubuntu2
publicsuffix 20260129.1928-1
python-apt-common 3.1.0ubuntu1
python-babel-localedata 2.17.0-2
python-is-python3 3.13.3-1+build1
python3 3.14.3-0ubuntu2
python3-apt 3.1.0ubuntu1
python3-aptdaemon 2.0.2build1
python3-aptdaemon.gtk3widgets 2.0.2build1
python3-autocommand 2.2.2-4
python3-babel 2.17.0-2
python3-bcrypt 5.0.0-3build1
python3-blinker 1.9.0-2build1
python3-brlapi 6.7-1ubuntu6
python3-cairo 1.27.0-2build2
python3-certifi 2026.1.4+ds-1
python3-cffi-backend 2.0.0-3build1
python3-chardet 5.2.0+dfsg-2build1
python3-click 8.2.0+0.really.8.1.8-1build1
python3-commandnotfound 23.04.0build1
python3-cryptography 46.0.5-1ubuntu2
python3-cups 2.0.4-3build1
python3-cupshelpers 1.5.18-4ubuntu2
python3-dasbus 1.7-2build1
python3-dateutil 2.9.0-4build1
python3-dbus 1.4.0-1build2
python3-debconf 1.5.92
python3-debian 1.0.1ubuntu2
python3-defer 1.0.6-2.1ubuntu2
python3-distro 1.9.0-1build1
python3-distro-info 1.15
python3-gdbm 3.14.3-0ubuntu2
python3-gi 3.56.2-1
python3-gi-cairo 3.56.2-1
python3-httplib2 0.22.0-1build1
python3-ibus-1.0 1.5.34~rc2-1
python3-icu 2.16.1-1build1
python3-idna 3.11-1
python3-inflect 7.5.0-1build1
python3-jaraco.context 6.0.1-2
python3-jaraco.functools 4.1.0-1build1
python3-jaraco.text 4.0.0-1build1
python3-jwt 2.10.1-4ubuntu1
python3-launchpadlib 2.1.0-1build1
python3-lazr.restfulclient 0.14.6-3build1
python3-lazr.uri 1.0.6-7build1
python3-linkify-it 2.0.3-1ubuntu3
python3-louis 3.36.0-1
python3-markdown-it 3.0.0-3build1
python3-mdurl 0.1.2-1build1
python3-minimal 3.14.3-0ubuntu2
python3-more-itertools 10.8.0-1build1
python3-mutagen 1.47.0-1build1
python3-netplan 1.2-1ubuntu5
python3-oauthlib 3.3.1-1build1
python3-packaging 26.0-1
python3-pam 0.4.2-19build4
python3-pkg-resources 78.1.1-0.1build1
python3-psutil 7.1.0-1ubuntu1
python3-pycryptodome 3.20.0+dfsg-3build1
python3-pygments 2.19.2+dfsg-1
python3-pyparsing 3.3.2-2
python3-requests 2.32.5+dfsg-1ubuntu1
python3-rich 13.9.4-1.2
python3-setproctitle 1.3.7-2build1
python3-setuptools 78.1.1-0.1build1
python3-software-properties 0.120
python3-speechd 0.12.1-2ubuntu1
python3-sss 2.12.0-1ubuntu5.1
python3-systemd 235-1build9
python3-typeguard 4.4.4-2
python3-typing-extensions 4.15.0-2
python3-uc-micro 1.0.3-1build1
python3-urllib3 2.6.3-1ubuntu1.1
python3-wadllib 2.0.0-3
python3-websockets 15.0.1-1build2
python3-xdg 0.28-3
python3-xkit 0.5.0ubuntu8
python3-yaml 6.0.3-1build1
python3-zipp 3.23.0-1build1
python3.14 3.14.4-1
python3.14-gdbm 3.14.4-1
python3.14-minimal 3.14.4-1
rdate 1:1.11-3ubuntu3
readline-common 8.3-4
remmina 1.4.40+dfsg-2ubuntu1
remmina-common 1.4.40+dfsg-2ubuntu1
remmina-plugin-rdp 1.4.40+dfsg-2ubuntu1
remmina-plugin-secret 1.4.40+dfsg-2ubuntu1
remmina-plugin-vnc 1.4.40+dfsg-2ubuntu1
resources 1.10.2-0ubuntu3.1
rime-data-bopomofo 0.0~git20260106.a8c35a4-1
rime-data-cangjie5 0.0~git20240325.0ac8452-1build1
rime-data-luna-pinyin 0.0~git20260106.d7b4e52-1
rime-data-stroke 0.0~git20250923.3a4b0f4-1
rime-data-terra-pinyin 0.0~git20251206.fa30016-1
rime-essay 0.0~git20260105.816b9ee-1
rime-prelude 0.0~git20251229.db691d2-1
rsync 3.4.1+ds1-7ubuntu0.3
rtkit 0.14-1
rust-coreutils 0.8.0-0ubuntu3
rygel 45.0-1ubuntu1
samba-libs 2:4.23.6+dfsg-1ubuntu2.1
sane-airscan 0.99.36-2ubuntu1
sane-utils 1.4.0-1ubuntu1
sbsigntool 0.9.4-3.1ubuntu9
seahorse 47.0.1-3build1
secureboot-db 1.9build2
sed 4.9-2ubuntu1
sensible-utils 0.0.26build1
sgml-base 1.31+nmu1build1
sgml-data 2.0.11+nmu1build1
shared-mime-info 2.4-5build3
shim-signed 1.59+15.8-0ubuntu2
simple-scan 48.1-0ubuntu3
smartmontools 7.5-2
sound-icons 0.1-8build1
sound-theme-freedesktop 0.8-7build1
speech-dispatcher 0.12.1-2ubuntu1
speech-dispatcher-audio-plugins 0.12.1-2ubuntu1
speech-dispatcher-espeak-ng 0.12.1-2ubuntu1
spice-vdagent 0.23.0-1
squashfs-tools 1:4.7.5-1
ssl-cert 1.1.3ubuntu2
sssd 2.12.0-1ubuntu5.1
sssd-ad 2.12.0-1ubuntu5.1
sssd-ad-common 2.12.0-1ubuntu5.1
sssd-common 2.12.0-1ubuntu5.1
sssd-ipa 2.12.0-1ubuntu5.1
sssd-krb5 2.12.0-1ubuntu5.1
sssd-krb5-common 2.12.0-1ubuntu5.1
sssd-ldap 2.12.0-1ubuntu5.1
sssd-proxy 2.12.0-1ubuntu5.1
strace 6.19+ds-0ubuntu5
sudo 1.9.17p2-1ubuntu3
sudo-common 1.2ubuntu
sudo-rs 0.2.13-0ubuntu1
switcheroo-control 3.0-2
sysstat 12.7.7-0ubuntu2
system-config-printer 1.5.18-4ubuntu2
system-config-printer-common 1.5.18-4ubuntu2
system-config-printer-udev 1.5.18-4ubuntu2
systemd 259.5-0ubuntu3
systemd-cryptsetup 259.5-0ubuntu3
systemd-hwe-hwdb 259.5.3ubuntu
systemd-oomd 259.5-0ubuntu3
systemd-resolved 259.5-0ubuntu3
systemd-sysv 259.5-0ubuntu3
systemd-timesyncd 259.5-0ubuntu3
sysvinit-utils 3.15-5ubuntu1
tar 1.35+dfsg-4ubuntu0.1
tcl 8.6.16build1
tcl8.6 8.6.17+dfsg-1build1
tcpdump 4.99.6-1
tecla 49.0-2
thermald 2.5.11-0ubuntu1
time 1.9-0.4
timgm6mb-soundfont 1.3-5build1
tinysparql 3.11.0-1
tpm-udev 4.1.3-6
traceroute 1:2.1.6-1build1
transmission-common 4.1.1+dfsg-1ubuntu1.1
transmission-gtk 4.1.1+dfsg-1ubuntu1.1
tzdata 2026a-3ubuntu1
tzdata-legacy 2026a-3ubuntu1
ubiquity 26.04.1
ubiquity-casper 26.04.2
ubiquity-frontend-gtk 26.04.1
ubiquity-ubuntu-artwork 26.04.1
ubuntu-docs 26.04.1
ubuntu-drivers-common 1:0.10.9
ubuntu-keyring 2023.11.28.1build1
ucf 3.0052ubuntu1
udev 259.5-0ubuntu3
udisks2 2.10.91-1ubuntu2
ufw 0.36.2-9build1
unattended-upgrades 2.12ubuntu9
unzip 6.0-29ubuntu1
update-inetd 4.54build1
upower 1.91.1-1
usb-creator-common 0.4.1build1
usb-creator-gtk 0.4.1build1
usb-modeswitch 2.6.2-1ubuntu1
usb-modeswitch-data 20191128-7build1
usb.ids 2025.12.13-1
usbmuxd 1.1.1-7
usbutils 1:019-1
user-session-migration 0.5.1
user-setup 1.107ubuntu2
util-linux 2.41.3-3ubuntu2
uuid-runtime 2.41.3-3ubuntu2
vim-common 2:9.1.2141-1ubuntu4.5
vim-tiny 2:9.1.2141-1ubuntu4.5
wamerican 2020.12.07-4build1
wayland-protocols 1.47-1
webp-pixbuf-loader 0.2.7-3
wget 1.25.0-2ubuntu4
whiptail 0.52.25-1ubuntu3
whois 5.6.6
whoopsie-preferences 23build4
wireless-regdb 2026.02.04-0ubuntu1
wireplumber 0.5.13-1ubuntu1
wpasupplicant 2:2.11-0ubuntu5
wsdd 2:0.8-5ubuntu1
x11-common 1:7.7+26ubuntu1
x11-utils 7.7+7build1
x11-xkb-utils 7.7+9build1
x11-xserver-utils 7.7+11build1
xauth 1:1.1.2-1.1build1
xbrlapi 6.7-1ubuntu6
xdg-dbus-proxy 0.1.7-1
xdg-desktop-portal 1.21.1+ds-1ubuntu3
xdg-desktop-portal-gnome 50.0-0ubuntu1
xdg-desktop-portal-gtk 1.15.3-2ubuntu1
xdg-terminal-exec 0.14.0-1
xdg-user-dirs 0.19-1
xdg-user-dirs-gtk 0.16-1
xdg-utils 1.2.1-2ubuntu2
xfonts-base 1:1.0.5+nmu1build1
xfonts-encodings 1:1.0.5-0ubuntu3
xfonts-utils 1:7.7+7build1
xkb-data 2.46-2
xml-core 0.19build1
xorriso 1:1.5.6-1.1ubuntu4
xserver-common 2:21.1.22-1ubuntu1
xwayland 2:24.1.10-1
xxd 2:9.1.2141-1ubuntu4.5
xz-utils 5.8.3-1
yaru-theme-sound 26.04.5.1ubuntu
yelp 49.0-5
yelp-xsl 49.0-2
yt-dlp 2026.03.17-1
zenity 4.2.1-1
zenity-common 4.2.1-1
zip 3.0-15ubuntu3
zlib1g 1:1.3.dfsg+really1.3.1-1ubuntu3
zstd 1.5.7+dfsg-3
```
