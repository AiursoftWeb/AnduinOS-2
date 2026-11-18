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
| **shim** | [github.com/rhboot/shim](https://github.com/rhboot/shim) | BSD-2-Clause (Ubuntu package copyright) |
| **GNU Unifont** | [unifoundry.com/unifont](https://unifoundry.com/unifont/) | GPL-2.0-or-later |
| **systemd** | [github.com/systemd/systemd](https://github.com/systemd/systemd) | LGPL-2.1-or-later |
| **dracut** | [github.com/dracutdevs/dracut](https://github.com/dracutdevs/dracut) | GPL-2.0-or-later |
| **BusyBox** | [busybox.net](https://busybox.net/) | GPL-2.0-only |
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
| **GTK 3** | [gtk.org](https://www.gtk.org/) | LGPL-2.1-or-later |
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
| **Impression** (2.1.0 USB image writer) | [Source package impression 3.7.0-3](https://launchpad.net/ubuntu/+source/impression/3.7.0-3) | GPL-3.0-only, GPL-3.0-or-later, and CC-BY-SA-4.0 (AppStream metadata) |
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
| **HyperFluent GRUB Theme (AnduinOS variant)** | [pinned artwork source](https://github.com/Anduin2017/HyperFluent-GRUB-Theme/tree/6db5bb74760c37af6a0b92e326dc30522e6b8c75/anduinos), adapted in [AnduinOS-Packages release-2.0.4](https://github.com/AiursoftWeb/AnduinOS-Packages/tree/release-2.0.4/anduinos-hyperfluent-grub-theme) | GPL-3.0-only |
| **GNOME Extensions CLI** (`lib/resolve-gnome-ext.py`) | [github.com/essembeh/gnome-extensions-cli](https://github.com/essembeh/gnome-extensions-cli) | MIT |

---

## 12. GNOME Shell Extensions

Extensions are fetched from [extensions.gnome.org](https://extensions.gnome.org/) at package build time. See each extension's source notices for its license. The 2.0.6 DING package pins GTK 3 release v85 to [upstream archive 72024](https://extensions.gnome.org/review/download/72024.shell-extension.zip), SHA256 `429171dda75a6d449650679c77370fb7edd17b9b183d68e54ab6892ab478a3f3`. The extension sources and AnduinOS changes are traceable through the package recipe. The 2.1.0 image includes DING v105, [upstream archive 78123](https://extensions.gnome.org/review/download/78123.shell-extension.zip), SHA256 `84d9bf55afc5d050bd1eb10fa19019b23625e69b86c347d6ec3355e1708d4896`.

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
| **Nerd Fonts Symbols** | [github.com/ryanoasis/nerd-fonts](https://github.com/ryanoasis/nerd-fonts) | Various — see the [packaged copyright and license notices](https://github.com/AiursoftWeb/AnduinOS-Packages/blob/release-2.0.5/anduinos-fonts/COPYRIGHT) |
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
| **D-Bus Broker** (2.1.0) | [github.com/bus1/dbus-broker v37](https://github.com/bus1/dbus-broker/tree/v37) | Apache-2.0 (upstream v37, with component notices in the package copyright) |
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
| **AnduinOS Native Installer and Live Layers** | [github.com/AiursoftWeb/AnduinOS-Packages](https://github.com/AiursoftWeb/AnduinOS-Packages) | GPL-3.0-or-later |

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
- **License of GNOME Shell Extensions:** Consult each extension's upstream license and copyright notices for its applicable terms.
- **"Various" license entries:** Some projects (particularly Debian and Ubuntu) are aggregations of many sub-projects. Consult the upstream distribution's copyright file for per-component details.
- **Version information:** The manifest in each ISO records its binary package names and versions. For upstream sources and build inputs, consult the corresponding AnduinOS-Packages release tag and its `.aosproj` definitions, source pins, and build scripts. Some upstream versions are resolved at package build time.

## Obtaining Source Code for a Release

Use the image identity and package versions recorded below to locate the source for that image. An installed system may have newer packages after updates.

1. **AnduinOS-maintained code and packaging:** Use the **Packages source release** recorded with the image inventory. For these images, [AnduinOS-Packages `release-2.0.6`](https://github.com/AiursoftWeb/AnduinOS-Packages/tree/release-2.0.6) and [`release-2.1.0`](https://github.com/AiursoftWeb/AnduinOS-Packages/tree/release-2.1.0) contain the AnduinOS source, patches, `.aosproj` recipes, and build scripts. Follow each package's recipe for third-party inputs; the repository snapshot alone does not contain every upstream dependency. Use the recorded release rather than the current `master` branch.
2. **Ubuntu packages:** Look up the exact source package name and version, which can differ from the binary package name and version. For an installed package, this command reports the binary identity followed by its source identity (replace `bash` with the package you want):

   ```bash
   dpkg-query -W -f='${binary:Package} ${Version} (source: ${source:Package} ${source:Version})\n' bash
   ```

   Find that source version in [Ubuntu's Launchpad source archive](https://launchpad.net/ubuntu/+source/bash). Download its `.dsc` and all files listed in it, including the original source and Debian/Ubuntu packaging and patches. For a downloaded `.deb`, inspect its `Package`, `Version`, and `Source` fields with `dpkg-deb -f`; if `Source` omits a version, use the binary version, and if the field is absent, use the binary name and version.
3. **Reassembled upstream packages, such as AnduinOS GRUB:** Also inspect `/usr/share/doc/anduinos-grub/manifest.json` in the installed package. It records the exact upstream binary inputs, versions, architectures, repositories, and hashes used for that build. Inspect those inputs' source identities and obtain their corresponding Ubuntu source packages as above, together with the AnduinOS assembly scripts and configuration from the recorded Packages release. Different inputs can come from different source packages, such as `grub2` and `grub2-unsigned`.

Upstream project homepages and current releases are useful references, but do not replace the source and distribution patches corresponding to the binaries you received. Copyright and license notices remain in the relevant packages.

## Production ISO Package Inventories

Mount or extract the ISO and open `LiveOS/filesystem.manifest` to read the complete package list for that image. Each line lists a binary package and its version. The installed package set can differ with architecture, installation choices, and subsequent updates.

| AnduinOS release (Ubuntu suite) | Architecture | ISO filename | ISO SHA256 | Packages source release |
| --- | --- | --- | --- | --- |
| 2.0.6 (resolute) | `amd64` | `AnduinOS-2.0.6-amd64.iso` | `0bdfbd21774650e3c392bbffc01c6f2ae024a6d02e68a53d9b41a91d0490e244` | [`release-2.0.6`](https://github.com/AiursoftWeb/AnduinOS-Packages/tree/release-2.0.6) |
| 2.0.6 (resolute) | `arm64` | `AnduinOS-2.0.6-arm64.iso` | `e25210418c946d1fe047dfcaaad932ab63527398fa4f855bc97a9ce3bc8b81aa` | [`release-2.0.6`](https://github.com/AiursoftWeb/AnduinOS-Packages/tree/release-2.0.6) |
| 2.1.0 (stonking) | `amd64` | `AnduinOS-2.1.0-amd64.iso` | `ba7fe85b8966ee81b7cfac78ac3915afbe4f69bc43af031c89b8f642b793baca` | [`release-2.1.0`](https://github.com/AiursoftWeb/AnduinOS-Packages/tree/release-2.1.0) |
| 2.1.0 (stonking) | `arm64` | `AnduinOS-2.1.0-arm64.iso` | `a3afd476a3737123a825a6505a3daa5476a8208adb1f75e35e705e91c4f412d9` | [`release-2.1.0`](https://github.com/AiursoftWeb/AnduinOS-Packages/tree/release-2.1.0) |

The four images were built from AnduinOS-2 commit `8b8a05be77c825841b96169e54e174c8c2bc63b9`. Both Packages release tags identify production commit `44eb36b47743a5076b914811c8ed58820628746c`.
