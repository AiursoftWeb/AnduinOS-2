# AnduinOS ISO acceptance tests

This directory contains a black-box acceptance framework for completed ISO
files. It replaces source-tree greps with disposable QEMU machines and drives
the same graphical installer a user sees.

The long-range architecture for reusable installed-system overlays, additional
desktop suites, virtual Wi-Fi, GNOME Boxes, and the complete requirement
backlog is documented in [`ARCHITECTURE.md`](ARCHITECTURE.md). That document
and `coverage-plan.json` are a roadmap, not evidence that every listed check is
implemented. The executable authority is `matrix.json` plus code reached from
`run.py`; a check counts only when `make test` runs it and retains evidence.

The current default `make test` release gate executes ten fresh installations
covering BIOS, UEFI with Secure Boot disabled, UEFI with Secure Boot enabled,
online/offline networking, Btrfs, Ext4, MOK enrollment, snapshot-manager
retention/removal, and three SSH policies. It also directly verifies:

- Rime selected and installed in three online cases, and explicitly not
  selected or installed in the other seven;
- GDM automatic login enabled in one case without sending credentials, and
  disabled in the other nine before their password login;
- the active GNOME cursor theme and size;
- image, video, DEB, and Windows executable MIME defaults;
- the `why` placeholder, the requested inotify runtime value, Noto CJK glyph
  coverage, and Twemoji color-font tables;
- real GTK/Pango rendering of `🤓 🍔 🔫 👽 ✨` and `变角次亮采之门`, including a
  pixel oracle requiring the pistol to be green;
- an ordinary ISO-detached boot with no GRUB input displaying the installed
  AnduinOS Plymouth watermark;
- the selected Simplified Chinese GRUB entry's locale and timezone arguments,
  all 28 regional menu entries, and the resulting Live session locale,
  timezone, `/etc/localtime`, and GNOME Shell environment;
- Nautilus default activation of a real Type-2 AppImage and a structurally
  valid CPU-Z-named PE fixture, including the MIME type and resolved desktop
  handler used by the installed system;
- every installed GNOME Shell extension enabled and in the `ACTIVE` state,
  except SimpleWeather and Network Stats, which must both remain inactive;
- a real SPICE GTK client resizing twice, with `spice-vdagent`, the virtio
  channel, and Mutter's reported current mode all required to follow;
- failed system and user units, crashes, GNOME extension errors, and unknown
  high-priority/fatal journal messages as release failures, while narrowly
  versioned known diagnostics remain visible without blocking healthy builds.

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

Every full scenario creates a new qcow2 target. By default the runner places
that target on a generic Linux tmpfs when `MemAvailable` is above 16 GiB and
the complete memory budget is safe; logs and screenshots remain in the durable
artifact directory. Every UEFI scenario also copies a fresh writable VARS
file. After installation QEMU is powered off, the ISO is detached, and the
installed target is booted again. Secure Boot scenarios must complete MOK
enrollment rather than merely reaching MokManager.

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
sudo apt install \
  dbus-daemon openssh-client ovmf python3-pil qemu-system-x86 qemu-utils \
  squashfs-tools virt-viewer xdotool xorriso xvfb
```

The AppImage fixture uses the upstream Type-2 runtime pinned by architecture
and SHA-256. The first desktop-gate run downloads it into the user's XDG cache;
later runs reuse the verified cache entry. The payload itself is generated
locally for the test and opens a uniquely named GTK window, so an executable
bit or MIME-table assertion alone cannot produce a pass.

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

On an interactive terminal the runner shows the ten installation scenarios as
the top-level matrix. The active scenario expands into the real child assertion
boundaries that it executes, such as `installer-ui`, `automatic-login-policy`,
`cursor-theme`, `desktop-file-dispatch`, `journal-health`, and
`plymouth-passive-boot`. Every child is shown as NOT STARTED, RUNNING, PASSED,
or FAILED; the journal child also reports the number of classified known
diagnostics. Small terminals keep the currently running child visible and show
which slice of the child list is on screen.

The top-level progress denominator deliberately remains the number of complete,
disposable installations. Child checks reuse those installed systems and are
not additional VM installations. Redirected output and CI preserve every case
and child transition line by line. `TEST_ARGS=--no-tui` forces that plain mode
locally, and `summary.json` records the same child verdicts.

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
- structured system and user Journal candidates, the package versions used by
  the Journal policy, independent GNOME functional-health evidence, and a
  machine-readable blocker/known-diagnostic verdict;
- screenshots at Live, completion, GDM, MOK, or failure boundaries;
- the fresh UEFI VARS used by that case;
- `target-disk-retention.txt`, recording whether the disposable target disk was
  discarded or explicitly retained.

Passed and failed target disks are both discarded by default after QEMU stops;
logs, screenshots, serial transcripts, UI evidence, and the summary remain.
This keeps a matrix from accumulating one multi-gigabyte qcow2 per case.

Target-disk placement is host-independent. `make test` never names, mounts,
formats, or discovers block devices. In the default `auto` mode it considers
only standard writable paths that the running Linux system reports as `tmpfs`
(`/dev/shm`, `/run/shm`, the user runtime directory, and a tmpfs `/tmp`). A
custom existing tmpfs may be offered through `ANDUINOS_TEST_RAMDISK`. Tiny CI
`/dev/shm` mounts, hosts without Linux `MemAvailable`, and memory-constrained
servers automatically use the artifact filesystem instead.

RAM-disk selection is deliberately stricter than checking total RAM:

- `/proc/meminfo` `MemAvailable` must be above 16 GiB;
- the writable tmpfs must have at least 8 GiB free;
- the qcow2 receives a kernel-enforced file-size limit of at most 12 GiB, and
  that complete budget must still leave the configured QEMU guest memory plus
  2 GiB for the host.

The limit is enforced in the QEMU child with `RLIMIT_FSIZE`; it is not based on
an assumed sparse-file size. The decision and exact reason are printed before
QEMU starts and recorded in `summary.json` and each scenario manifest. The
runner rechecks the budget before every scenario, deletes each qcow2 after QEMU
is reaped, and removes its private tmpfs workspace on normal exit, SIGINT, or
SIGTERM. A small CI tmpfs therefore falls back safely instead of failing
halfway through an installation.

The backend may be forced for diagnostics:

```bash
# Require RAM; fail before QEMU if no safe tmpfs exists.
make test TEST_ARGS=--disk-backend=ramdisk

# Always use the artifact filesystem.
make test TEST_ARGS=--disk-backend=filesystem

# Change only the automatic MemAvailable trigger.
make test TEST_ARGS=--ramdisk-threshold=24
```

When the persistent filesystem backend is selected, before the run and again
before every scenario the harness requires free host space for the guest's
entire advertised disk plus a safety reserve (40 GiB + 10 GiB with the default
matrix). It does not assume that yesterday's sparse qcow2 happened to allocate
only a few GiB. A capacity failure occurs before QEMU starts. `--dry-run`
reports the selected backend and its capacity calculation without requiring a
persistent backend to pass.

Retaining a disk is an explicit, single-case debugging operation. It is
rejected for a matrix, preventing accidental accumulation:

```bash
make test \
  CASES=uefi-nosb-online-btrfs-ssh-enabled \
  TEST_ARGS=--keep-failed-disk
```

Use `--keep-passed-disk` only when a successful installed target is required.
Either retention option automatically selects persistent storage even when
RAM is abundant, because a retained disk must survive process exit and reboot.
SIGINT and SIGTERM both stop QEMU and finalize the disposable disk before the
runner exits. SIGKILL and host power loss cannot execute process cleanup, so a
subsequent run still refuses to reuse an existing artifact directory.

A scenario fails closed: a missing firmware file, unexpected architecture,
reused disk or artifact path, installer warning promoted to fatal state,
package inconsistency, incorrect root filesystem, SSH mismatch, or incomplete
MOK workflow all produce a non-zero result and preserve evidence.

## Journal release policy

The Journal gate is designed to find defects, not to require a modern GNOME
desktop to produce an unrealistically empty log. Its executable policy is
[`journal-policy.json`](journal-policy.json), and its host-side classifier is
[`iso_test/journal.py`](iso_test/journal.py).

The classifier has three outcomes:

- **Release blocker:** failed system/user units, priority 0-3 entries not
  covered by an exact policy, crashes, core dumps, segfaults, OOM events,
  tracebacks, GNOME Shell JavaScript errors, extension exceptions, and unknown
  fatal/assertion messages.
- **Known diagnostic:** an exact component and message match whose scenario,
  package-version glob, and maximum occurrence count all match. The entry and
  reason remain in the report and raw JSONL evidence. It is never silently
  discarded.
- **Observation:** a collected candidate that is neither fatal nor covered by
  a release-blocking rule. It is retained but does not change the exit code.

Known diagnostics are deliberately fail-closed. Every entry declares an
owner, reason, scenario conditions, package version, and occurrence budget.
Changing from GNOME 50 to a later major release automatically expires the
current GNOME exceptions; a similar-but-not-identical message, a missing
package version, a second occurrence, or the same message in the wrong
scenario is a release blocker again.

The current GNOME 50 policy recognizes three bounded diagnostics observed in
AnduinOS with Ubuntu's GNOME packages: GDM cannot unlock a password-protected
login keyring when automatic login supplies no password, `gsd-keyboard` can
emit one null-variant assertion during input-source startup, and Mutter can
emit one transient stack-position assertion. They are non-blocking only in
the applicable release-gate scenario. The same run independently requires a
live GNOME Shell, `gsd-keyboard`, GNOME Keyring daemon, configured Rime input
source, working extensions, window activation, and SPICE resizing. A failed
functional oracle remains fatal regardless of the Journal exception.

For every run, inspect:

```text
installed-system-journal.jsonl
installed-user-journal.jsonl
installed-journal-package-versions.txt
installed-journal-functional-health.txt
installed-journal-verdict.json
journal-policy.json
```

Do not broaden a regular expression merely to make a release green. Add or
change a known diagnostic only after reproducing it, proving the associated
function still works, limiting its applicable versions and scenarios, and
adding a regression test that proves nearby unknown errors still fail.

The desktop file fixture is activated through Nautilus's selected-item default
action using a real QMP Enter key. This follows the same file-manager launch
and MIME-dispatch path as a double click, while avoiding fabricated screen
coordinates: GTK4/Wayland currently exposes zero global component bounds for
the Nautilus rows in this environment. Evidence records the exact semantic
selection, QMP request, detected MIME type, default handler, and resulting
accessible window.
