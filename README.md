# AnduinOS 2

[![GPL licensed](https://img.shields.io/badge/license-GPL-blue.svg)](https://github.com/AiursoftWeb/AnduinOS-2/blob/master/LICENSE)
[![Discussions](https://img.shields.io/badge/discussions-join-blue)](https://github.com/Anduin2017/AnduinOS/discussions)
[![Revolt Community](https://img.shields.io/badge/Revolt-Join-fd6671?style=flat-square)](https://rvlt.gg/dPwPs8e6)
[![Website](https://img.shields.io/website?url=https%3A%2F%2Fwww.anduinos.com%2F)](https://www.anduinos.com/)
[![Man hours](https://manhours.aiursoft.com/r/github.com/aiursoftweb/anduinos-2.svg)](https://manhours.aiursoft.com/r/github.com/aiursoftweb/anduinos-2.html)

<img align="right" width="100" height="100" src="./logo.svg" alt="AnduinOS logo">

AnduinOS is an Ubuntu-based Linux distribution designed to provide a familiar
desktop experience for people moving to Linux.

For the previous development line, see the
[AnduinOS 1 repository](https://github.com/Anduin2017/AnduinOS).

## Download

Download the latest release from the [AnduinOS website](https://www.anduinos.com/).
Installation instructions and system requirements are available in the
[AnduinOS documentation](https://docs.anduinos.com/).

![AnduinOS desktop](./screenshot.png)

## Project scope

This repository contains the scripts that assemble the AnduinOS live and
installation ISO. The build starts from a minimal Ubuntu system, applies the
ordered modifications under `mods/`, creates the Casper filesystem, and
produces the bootable image.

The image supports:

- amd64 systems using BIOS or UEFI;
- arm64 systems using UEFI;
- Secure Boot through signed GRUB and shim packages;
- the AnduinOS desktop and native declarative installer;
- automated installation and desktop acceptance testing under QEMU.

## Building

Building on AnduinOS is recommended. The build host must report Ubuntu,
Debian, Tuxedo, or AnduinOS, and its release codename must match
`TARGET_UBUNTU_VERSION` in `args.sh`.

Run the build as a regular user with `sudo` access, not as root. An Internet
connection is required; `make` checks the host and installs missing build
dependencies before starting.

```bash
git clone https://github.com/AiursoftWeb/AnduinOS-2.git
cd AnduinOS-2
make
```

The ISO and its SHA-256 checksum are written to `dist/`.

Use the configuration menu before building:

```bash
make menuconfig
```

The same settings can be edited directly in `args.sh`. They include the Ubuntu
release, package sources, AnduinOS version, and target architecture.

## Testing

Run the complete release test from the repository root:

```bash
make test
```

This first runs the unit tests, then selects the newest ISO in `dist/` and
executes the installation and desktop acceptance matrix in disposable QEMU
guests. To test a specific image:

```bash
make test ISO=/path/to/AnduinOS.iso ARCH=amd64
```

See [tests/README.md](tests/README.md) for prerequisites, execution details,
and generated evidence.

## Installer and live environment

AnduinOS uses `anduinos-installer-beta`, its native declarative installer.
Casper provides the live environment. The legacy Ubiquity integration stack is
retired and is not included, built, or maintained by AnduinOS.

## Documentation and support

- [Documentation](https://docs.anduinos.com/)
- [Discussions](https://github.com/Anduin2017/AnduinOS/discussions)
- [Bug reports and feature requests](https://github.com/Anduin2017/AnduinOS/issues)
- [Revolt community](https://rvlt.gg/dPwPs8e6)

Code and documentation contributions may be submitted as pull requests to
this repository.

## Support the project

AnduinOS is funded by user donations. If you find the project useful, you can
support its development through Ko-fi.

<a href="https://ko-fi.com/anduinxue/goal?g=0" target="_blank" title="Support AnduinOS on Ko-fi">
  <img height="36" src="https://storage.ko-fi.com/cdn/kofi3.png?v=3" alt="Support AnduinOS on Ko-fi">
</a>

## License

This project is licensed under the GNU General Public License. See
[LICENSE](LICENSE) for the complete license text.

The open-source software included in AnduinOS is distributed in the hope that
it will be useful, but without any warranty. See [OSS.md](OSS.md) for the
open-source software inventory.
