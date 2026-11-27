<a name="anduinos-2"></a>
# Aiursoft AnduinOS 2

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

## Overview

### What is AnduinOS 2?

AnduinOS 2 is the live and installation ISO build system for the AnduinOS desktop distribution. This repository assembles the OS image; installable package sources are maintained separately in [AnduinOS-Packages](https://github.com/AiursoftWeb/AnduinOS-Packages).

## Installation

<a name="download"></a>
Download the latest release from the [AnduinOS website](https://www.anduinos.com/).
Installation instructions and system requirements are available in the
[AnduinOS documentation](https://docs.anduinos.com/).

![AnduinOS desktop](./screenshot.png)

For a source build, use the host requirements and commands in Development. Building an ISO is separate from installing it onto a computer; follow the documentation for disk selection and installation.

## Usage

### Project scope

This repository contains the scripts that assemble the AnduinOS live and
installation ISO. The build starts from a minimal Ubuntu system, applies the
ordered modifications under `mods/`, creates one Dracut Live SquashFS, and
produces the bootable image.

The image supports:

- amd64 systems using BIOS or UEFI;
- arm64 systems using UEFI;
- Secure Boot through signed GRUB and shim packages;
- temporary Try mode and Dracut-backed persistent USB Live mode;
- the AnduinOS desktop and native declarative installer;
- automated installation and desktop acceptance testing under QEMU.

### Installer and live environment

AnduinOS uses `anduinos-installer-beta`, its native declarative installer, and
`anduinos-live-layers` on a non-host-only Dracut image for the live environment.
The legacy Casper, Ubiquity, and initramfs-tools stacks are retired and are not
included, built, or maintained by AnduinOS.

## Configuration

Use `make menuconfig` (text UI), `make gui` (GTK3 graphical UI), or edit [args.sh](args.sh) directly before building. The build sources that file; it is not an executable installer. Keep the variable names and structure intact. A prebuilt GTK3 `.deb` package is provided under `dist/`; see [gui/README.md](gui/README.md). The current inputs are:

| Setting | Meaning |
| --- | --- |
| `TARGET_UBUNTU_VERSION` | Target Ubuntu suite; the host codename must match it. |
| `APT_SOURCE` | Ubuntu APT source used to assemble the root filesystem. |
| `TARGET_NAME`, `TARGET_BUSINESS_NAME`, `TARGET_BUILD_VERSION` | Image identity, display name and release version embedded in build metadata. |
| `TARGET_ARCH` | Target architecture; defaults to the host's `dpkg --print-architecture` unless provided. Supported images are amd64 and arm64. |
| `APT_CONFIG_PACKAGE`, `APKG_SERVER`, `APKG_CERT_NAME` | AnduinOS APT configuration package, package server and signing-certificate name. |
| `LANG_PACK_CODES`, `LANGUAGE_PACKS`, `SUPPORTED_LIVE_REGIONS` | Language packages and the locale/timezone/keyboard options offered in the live environment. |
| `LC_ALL`, `LANG`, `LANGUAGE` | The declared English build-process locale, distinct from installed/live user locale choices. |
| `DEBIAN_FRONTEND`, `SCRIPT_DIR` | Noninteractive package setup and the derived repository directory used by the build scripts. |
| `KEEP_DOWNLOADED_DEBS` | Keep downloaded `.deb` packages in `.cache/apt-archives/` between builds so a retry after a network failure reuses them instead of re-downloading; the cache is excluded from the final ISO. |

[args.sh](args.sh) contains the authoritative current values and comments. Review the complete file when changing suite, architecture or package sources; a source configuration change is not a request to install the resulting image on the host.

The graphical UI additionally manages `packages.json` (which packages are installed or skipped), `custom_hooks.sh` (chroot hook), and `custom_pre_iso.sh` (host hook before ISO assembly). An interrupted build can be resumed from its last completed stage with `make resume` (equivalently `./build.sh --resume`). The UI is internationalized: English is the default, Chinese translations are stored as plain-text JSON under `gui/locales/`, and any additional `*.json` file placed there is automatically listed in the language selector.

## Development

<a name="building"></a>
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
make menuconfig   # text UI
make gui          # GTK3 graphical UI
```

The graphical UI can also select which packages are installed, define custom
chroot / pre-ISO hooks, start a build and resume an interrupted one. The same
settings can be edited directly in `args.sh`. They include the Ubuntu release,
package sources, AnduinOS version, and target architecture.

<a name="testing"></a>
**Testing.**

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

`make` can install host build dependencies and creates a real ISO; `make test` runs disposable VM acceptance and requires an image and the prerequisites documented in `tests/README.md`. Neither is a Markdown preview command. The Python unit tests additionally require Pillow (`PIL`), PyGObject (`gi`) and the AT-SPI 2.0 introspection library in the selected Python environment. For those existing unit tests alone, use the command invoked by the make target:

```bash
PYTHONPATH=tests python3 -m unittest discover -s tests/unit -p 'test_*.py' -q
```

Unit tests alone do not establish ISO installation or desktop acceptance. Existing test evidence is written under `test-results/`; retain the full release matrix when preparing an OS release.

## Documentation

<a name="documentation-and-support"></a>
- [Documentation](https://docs.anduinos.com/)
- [Discussions](https://github.com/Anduin2017/AnduinOS/discussions)
- [AnduinOS 2 bug reports and feature requests](https://github.com/AiursoftWeb/AnduinOS-2/issues)
- [Revolt community](https://rvlt.gg/dPwPs8e6)

Code and documentation contributions may be submitted as pull requests to
this repository.

## How to contribute

There are many ways to contribute to the project: logging bugs, submitting pull requests, reporting issues, and creating suggestions.

Even if you have push rights on the repository, you should create a personal fork and create feature branches there when you need them. This keeps the main repository clean and your workflow cruft out of sight.

We're also interested in your feedback on the future of this project. You can submit a suggestion or feature request through the issue tracker. To make this process more effective, we're asking that these include more information to help define them more clearly.



## License

This project is licensed under the GNU General Public License. See
[LICENSE](LICENSE) for the complete license text.

The open-source software included in AnduinOS is distributed in the hope that
it will be useful, but without any warranty. See [OSS.md](OSS.md) for the
open-source software inventory.
