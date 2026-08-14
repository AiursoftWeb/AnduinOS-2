# AnduinOS ISO acceptance tests

This directory contains a black-box acceptance framework for completed ISO
files. It replaces source-tree greps with disposable QEMU machines and drives
the same graphical installer a user sees.

The test runner never edits the ISO. It temporarily adds a systemd debug shell
to the selected GRUB entry through QEMU keyboard events, uses that root serial
shell as its control channel, and copies an AT-SPI driver into `/run`. The
driver clicks the real GTK4 installer by accessible name and control state;
it does not use screen coordinates. The temporary driver and debug shell do
not become part of the installed system.

Some GTK4 CheckButtons expose checked/sensitive state but no invokable AT-SPI
action under the Live Wayland session. For those controls, the guest driver and
host use a semantic handshake: the guest requests one QMP Tab at a time and
observes accessibility focus, then requests Space only when the intended
checkbox is focused. The host never assumes a coordinate or fixed Tab count.

Every full scenario creates a new qcow2 target. Every UEFI scenario also copies
a fresh writable VARS file. After installation QEMU is powered off, the ISO is
detached, and the installed target is booted again. Secure Boot scenarios must
complete MOK enrollment rather than merely reaching MokManager.

For every installed target, the harness sets GRUB's standard `recordfail`
environment flag before the controlled reboot. That exposes the real installed
GRUB menu deterministically long enough to append the temporary serial
debug-shell arguments; relying on a UEFI firmware-delay race can miss the menu.
The flag is cleared as soon as the installed system's serial shell is
available, and the test asserts that no one-shot flag remains.
The harness discovers the exact versioned kernel and initrd created by the
installer under `/boot`; it does not assume that optional `/vmlinuz` or
`/initrd.img` compatibility links exist.

SSH reachability is tested with a real SSH handshake and password login. The
harness does not treat the QEMU host-forward listener itself as evidence that
the guest is accepting SSH: user-mode networking keeps that host socket open
even while both guest SSH units are disabled.
The GNOME-toggle scenario opens the real System panel, activates its Secure
Shell switch, completes the real Polkit password dialog through QEMU keyboard
events, and proves a password SSH login succeeds. It then switches Secure Shell
off again and requires both SSH units and port 22 to stop before proving a new
host login is rejected. Before touching the switch, the installed-system
assertions and a real host connection both prove that SSH is disabled. The UI
driver waits for GNOME's final switch state rather than assuming Polkit finishes
within a fixed delay.

## Dependencies

On an amd64 test host:

```bash
sudo apt install qemu-system-x86 ovmf qemu-utils openssh-client xorriso
```

To test arm64 through TCG on an amd64 host, also install:

```bash
sudo apt install qemu-system-arm qemu-efi-aarch64
```

Native guests use KVM when `/dev/kvm` is available. Cross-architecture arm64
guests use TCG with `neoverse-n1`; the harness intentionally never uses
`-cpu max` with AAVMF.

## Quick start

The four entry points used most often are:

```bash
# Run the complete matrix against the newest ISO in dist/.
make test

# Run one or more selected scenarios.
make test CASES=bios-offline-btrfs

# Keep durable line-by-line output instead of the interactive dashboard.
make test TEST_ARGS=--no-tui

# Run the fast unit tests for the acceptance framework itself.
make test-unit
```

`make test` infers `amd64` or `arm64` from the selected ISO filename. Every
acceptance run writes its complete logs and evidence under `test-results/`.

## Running

List the declarative matrix:

```bash
python3 tests/run.py --list
python3 tests/run.py --list --arch amd64
```

Validate an ISO, architecture, firmware files, and matrix without starting a
VM:

```bash
python3 tests/run.py \
  --iso dist/AnduinOS-2.0.2-amd64.iso \
  --arch amd64 \
  --dry-run
```

Run one complete installation:

```bash
python3 tests/run.py \
  --iso dist/AnduinOS-2.0.2-amd64.iso \
  --arch amd64 \
  --case bios-offline-btrfs
```

With no arguments, Make selects the newest ISO under `dist/` and infers its
architecture from the filename. To choose an image explicitly:

```bash
make test ISO=dist/AnduinOS-2.0.2-amd64.iso ARCH=amd64
```

On an interactive terminal the runner shows a live table with every case in
NOT STARTED, RUNNING, PASSED, or FAILED state, its current phase, elapsed time,
overall progress, and artifact directory. Redirected output and CI use durable
line-by-line transitions automatically. `TEST_ARGS=--no-tui` forces that plain
mode locally.

`CASES` accepts a space-separated subset, and `TEST_ARGS` passes additional
runner arguments:

```bash
make test \
  ISO=dist/AnduinOS-2.0.2-amd64.iso \
  ARCH=amd64 \
  CASES='bios-offline-btrfs uefi-nosb-online-btrfs-ssh-toggle' \
  TEST_ARGS='--fail-fast'
```

For a quick boot-only check, select an explicit scenario and add `--smoke`.
This proves firmware boot, graphical.target, GDM, network policy and the serial
control channel, but intentionally does not count as an installation pass.

## Network and firmware semantics

Offline means QEMU reports the virtual NIC link down through QMP. The guest
must observe no carrier and must fail to reach its configured APT mirror.
Online means the exact APT mirror and suite configured in the ISO must return
an InRelease file before the installer runs.

Release-gate infrastructure should route the configured mirror to a pinned,
signed snapshot. Public mirrors are appropriate for nightly coverage, not a
deterministic release gate.

The default UEFI lookup uses Secure-Boot-capable OVMF/AAVMF code for both UEFI
modes. The no-Secure-Boot matrix uses an unprovisioned VARS template; Secure
Boot uses a Microsoft-key-provisioned template. Custom lab firmware can be
provided with `--uefi-code`, `--uefi-vars`, and `--secure-boot-vars`.
For shim-backed Secure Boot, GRUB keyboard injection waits for the actual
`grub>` token on the serial terminal before typing. Its terminal-switch delay
varies enough that a fixed sleep can silently lose the first characters of an
otherwise valid kernel command.
Each preparatory Secure Boot command must return another `grub>` prompt. After
`boot`, every firmware mode must emit the kernel's `Linux version` marker
before the harness is allowed to send a shell probe, preventing a lost Enter
from turning `boot` and the first probe into one malformed GRUB command.

## Evidence

The default output is `test-results/<UTC timestamp>/`. Each scenario contains:

- the immutable scenario and ISO SHA-256 manifest;
- exact QEMU command lines and process logs;
- serial transcripts and in-guest assertion output;
- AT-SPI event logs and accessibility-tree snapshots;
- the complete executor transcript produced through the installer's real
  Save Log button, including driver-command evidence for online cases;
- screenshots at Live, completion, GDM, MOK, or failure boundaries;
- the disposable qcow2 and UEFI VARS used by that case.

A scenario fails closed: a missing firmware file, unexpected architecture,
reused disk or artifact path, installer warning promoted to fatal state,
package inconsistency, incorrect root filesystem, SSH mismatch, or incomplete
MOK workflow all produce a non-zero result and preserve evidence.
