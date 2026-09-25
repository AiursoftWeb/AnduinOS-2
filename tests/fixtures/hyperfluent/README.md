The AMD64 frames were captured from an isolated QEMU OVMF Secure Boot VM
running the distribution-signed shim and GRUB 2.14.
The GRUB menu used the AnduinOS HyperFluent artwork pinned at upstream commit
`6db5bb74760c37af6a0b92e326dc30522e6b8c75` (GPL-3.0). No host disk was
attached. `submenu-scrolled.png` proves that the 28-entry language menu can
scroll even though only five choices are visible at once.

They are visual-oracle fixtures, not evidence that the completed ISO has
passed acceptance; that requires booting the actual assembled image.
The `*-1024.png` frames additionally check the minimum supported display size.
The 1024-pixel editor frames capture the left-anchored 80-column editor; a
narrower theme terminal request is overridden by GRUB and centered instead.

`arm-uefi-*.png` came from a separate QEMU ARM64 `virt` guest with AAVMF's
Microsoft-key firmware and Ubuntu's distribution-signed ARM64 shim and GRUB.
The package theme and a 28-entry sample menu were on a disposable FAT image;
this proves the signed ARM64 menu can render and navigate the theme, but does
not substitute for a full AnduinOS ARM64 ISO boot/install acceptance run.
