# AnduinOS ISO acceptance tests

This directory contains a black-box acceptance framework for completed ISO
files. It replaces source-tree greps with disposable QEMU machines and drives
the same graphical installer a user sees.

The architecture for reusable installed-system overlays, additional
desktop suites, virtual Wi-Fi, GNOME Boxes, and the complete requirement
backlog is documented in [`ARCHITECTURE.md`](ARCHITECTURE.md). That document
and `coverage-plan.json` are a roadmap, not evidence that every listed check is
implemented. The executable authority is `matrix.json` plus code reached from
`run.py`; a check counts only when `make test` runs it and retains evidence.

The current default `make test` release gate executes eleven fresh installations
on amd64 and seven on arm64. They cover BIOS where supported, UEFI with Secure
Boot disabled, UEFI with Secure Boot enabled, online/offline networking,
Btrfs, Ext4, MOK enrollment, snapshot-manager retention/removal, and three SSH
policies. The amd64 matrix also contains a local-only virtual-Wi-Fi installation.
It directly verifies:

- Rime selected and installed in the configured online cases (three on amd64,
  two on arm64), and explicitly not selected or installed in every other case;
- GDM automatic login enabled in one case without sending credentials, and
  disabled in all remaining cases before their password login;
- passwordless sudo explicitly enabled in one advanced-options case and
  securely disabled in all remaining cases; after clearing sudo timestamps,
  the created non-root user must respectively succeed or fail with `sudo -n`,
  while `visudo`, policy ownership, modes, exact rule scope, and installer
  state are all checked;
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
- independent Nautilus activation checks for a real Type-2 AppImage and a
  structurally valid CPU-Z-named PE fixture, including the AppImage executable
  permission boundary and the PE file's resolved desktop handler;
- every installed GNOME Shell extension enabled and in the `ACTIVE` state,
  except SimpleWeather and Network Stats, which must both remain inactive;
- a real SPICE GTK client resizing twice, with `spice-vdagent`, the virtio
  channel, and Mutter's reported current mode all required to follow;
- failed system and user units, crashes, GNOME extension errors, and unknown
  high-priority/fatal journal messages as release failures, while narrowly
  versioned known diagnostics remain visible without blocking healthy builds.
- promotion of the verified Chinese/Btrfs installation into a temporary,
  read-only qcow2 base, followed by a fresh disposable overlay in which QMP
  really switches to Rime, types a fixed composition, and AT-SPI must read the
  exact committed text `你好` before the input method is switched back;
- opening a plain text file through Nautilus in the real GNOME Text Editor,
  typing `变角次亮采之门` through recorded host Unicode key sequences,
  activating Text Editor's real Save menu action, and requiring the exact
  UTF-8 bytes plus Text Editor's one intentional trailing newline on disk
  while the editor remains open;
- launching the real Swap Control application, authenticating its polkit
  prompt through the opaque QMP secret channel, and requiring accessible
  dashboard markers, a green visual-state oracle, and clean scoped journals;
- deterministic image, video, and harmless local DEB fixtures: Nautilus must
  generate content-correct thumbnails, Loupe must render the image, Celluloid
  must expose the exact MPRIS title and advance playback, and GNOME Software
  must show the local package details without installing it;
- an action-scoped system/user journal verdict covering only the Rime action;
- an ordinary installed-system reboot with a changed boot ID and a restored
  graphical user session;
- GNOME Settings account creation, first login, password change, logout,
  branded GDM, and the GDM cursor theme;
- the localized bottom theme selector changing already-running GTK, Qt, and
  Firefox fixtures rather than merely changing configuration keys;
- Super+U, Super+Shift+S, Super+Tab, Alt+Tab, and Super+I with direct
  user-visible state or file-output oracles;
- the untouched post-login Shell state, with a positive accessibility-ready
  marker and eight stable observations proving Overview did not open itself;
- the AnduinOS Start-button logo, taskbar Pin and localized Remove actions,
  the localized Home and Trash desktop icons, a semantic desktop-background
  right-click opening Ptyxis, and creation plus activation of a trusted desktop
  shortcut. Before any Ptyxis window can save its geometry, an installed-system
  contract also requires the fresh user's effective `window-size` setting to be
  the correctly typed, nonzero `(uint32 80, uint32 24)` tuple;
- on amd64, a real WPA2 connection created through the Live GNOME password
  dialog, migration of that exact NetworkManager UUID into the installed
  system, and automatic reconnection after reboot without supplying the secret
  again. Ethernet remains disconnected, the isolated AP supplies no default
  route or DNS, and the retained Netplan profile must be a root-owned regular
  file with mode `0600` and a valid generated mapping. The ephemeral PSK is
  scanned out of all durable test artifacts.

`PROFILE=nightly-online` reruns those deterministic suites and additionally
adds the destructive Btrfs rollback lane plus the public Spotify store lane.
It creates a real system snapshot, installs and starts `docker.io`, writes
separate `/etc` and `/home` sentinels, selects the exact snapshot in the real
Disk Snapshots Manager UI, verifies that the rollback is armed, requests an
ordinary systemd reboot through the pre-snapshot least-privilege control
channel, performs the recovery boot and another ordinary boot, and proves
Docker and root changes disappeared while user data survived.
The post-boot oracle runs as root and reads the recovery engine's protected
transaction and deployment records directly. The public `status --json`
command is intentionally redacted and therefore cannot prove system snapshot
health. The oracle instead ties the exact UI-selected deployment to one
confirmed history record, verifies its target and pre-rollback fallback are
complete `ready` Btrfs subvolumes with matching UUIDs, proves the active root
is a writable child of that target, and requires the pending transaction and
one-shot EFI recovery selection to be empty on both successful boots.
The positive recovery lane uses the UEFI/Secure-Boot-disabled Btrfs installation
because the recovery package defines that as an authoritative qualification
environment. It is nightly rather than release-gate until the online package
source is a fixed signed snapshot. BIOS remains a separate firmware contract:
an ISO whose Secure Boot toolkit reports BIOS as indeterminate is a product
failure, not a reason to weaken the rollback oracle.

The test runner never edits the ISO. On amd64 it opens the selected regional
entry in the ISO's real graphical GRUB editor and appends only the temporary
serial-console/debug-shell arguments; firmware, submenu, highlight, editor,
cursor movement, and boot transitions are synchronized from QEMU frames rather
than keyboard timing. On cross-architecture ARM64 TCG, QMP framebuffer calls
cannot reliably accept QMP keyboard calls while AAVMF/GRUB owns the machine.
After the real firmware ISO hand-off, an agent-independent SPICE keyboard opens
the graphical GRUB command line and types only strictly mapped scan codes. QMP
screendumps must prove a stable non-menu command-line repaint before each next
linux/initrd command is released. After `boot`, PL011 must expose the exact
kernel/debug-shell hand-off created by those arguments; a default menu timeout
therefore cannot produce a false pass. The virtio GPU remains present
throughout for GNOME. The resulting root serial shell is the control channel,
and the runner copies an AT-SPI driver into `/run`. The driver clicks the real
GTK4 installer by accessible name and control state; it does not use fixed
screen coordinates. Neither the temporary driver nor the debug shell becomes
part of the installed system.

Guest files are not trusted merely because one long base64 command returned
zero. Kernel and systemd diagnostics share the serial byte stream and may be
printed in the middle of a shell response. Downloads therefore use bounded
frames carrying an offset and SHA-256, retry only a corrupted transport frame,
and verify the whole guest file before and after transfer before atomically
publishing the local evidence. A guest file that changes during collection or
cannot produce an intact frame fails closed. A fatal kernel event is never a
retryable transport error; in particular, loss of the emulated xHCI controller
invalidates all later keyboard and pointer evidence.

Some GTK4 CheckButtons expose checked/sensitive state but no invokable AT-SPI
action under the Live Wayland session. For those controls, the guest driver and
host use a semantic handshake: the guest requests one QMP Tab at a time and
observes accessibility focus, then requests Space only when the intended
checkbox is focused. The host never assumes a coordinate or fixed Tab count.

Every full scenario creates a new qcow2 target. By default the runner places
that target on a generic Linux tmpfs when `MemAvailable` is above 16 GiB and
the complete memory budget is safe; logs and losslessly compressed screenshots
remain in the durable artifact directory. Every UEFI scenario also copies a
fresh writable VARS file for the lifetime of that VM. Its hashes and behavioral
evidence remain, but the writable copy is removed with the disposable disk.
After installation QEMU is powered off, the ISO is detached, and the installed
target is booted again. Secure Boot scenarios must complete MOK enrollment
rather than merely reaching MokManager.

For every installed target, the harness discovers the exact versioned kernel
and initrd created by the installer under `/boot`; it does not assume that
optional `/vmlinuz` or `/initrd.img` compatibility links exist. While the
target is still mounted from Live, it validates the generated `grub.cfg`, makes
an exact backup, appends only the temporary serial-console/debug-shell arguments
to every real `linux` line, validates the result with `grub-script-check`, and
then boots the product's normal default menuentry without GRUB input. The
harness first proves that Linux owns the serial port and then separately waits
for Bash's `servicename=debug-shell.service` prompt marker before sending any
shell probe. It restores the original `grub.cfg` byte for byte. This
ordering is a safety invariant: probing during the UEFI GRUB menu would treat a
`c` byte as “open the GRUB command line” and prevent the default entry from
booting. The restored hash and empty one-shot GRUB state are durable evidence;
later ordinary reboots, rollback boots, and Plymouth observation use the
unmodified product configuration.

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
  dbus-daemon ffmpeg gir1.2-spiceclientglib-2.0 openssh-client ovmf python3-pil \
  qemu-system-x86 qemu-utils \
  squashfs-tools virt-viewer xdotool xorriso xvfb
```

The AppImage fixture uses the upstream Type-2 runtime pinned by architecture
and SHA-256. The first desktop-gate run downloads it into the user's XDG cache;
later runs reuse the verified cache entry. The payload itself is generated
locally for the test and opens a uniquely named GTK window, so an executable
bit or MIME-table assertion alone cannot produce a pass.

Before opening Nautilus, the gate requires the generated file to resolve to one
of the two dedicated AppImage MIME types while having no default MIME handler
and no `com.anduinos.AppImageRunner.desktop` file. Nautilus must launch the
fixture through its native executable-file path when the file is mode `0755`.
The gate then uploads the exact same AppImage as mode `0644`, activates it with
the same real host input, and requires that no fixture process or GTK window is
created. This proves both the intended double-click experience and the
executable-bit security boundary without inventing a redundant MIME runner.

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
# Run the complete installation matrix and deterministic feature release gate.
make test

# Run only the installation matrix.
make test PROFILE=install

# Run online/destructive suites separately.
make test PROFILE=nightly-online

# Run one selected executable feature suite and its required source case.
make test CASES=bios-online-btrfs SUITES=input-and-appearance

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

On an interactive terminal the runner shows eleven amd64 or seven arm64
installation scenarios as the top-level matrix. The active scenario expands
into the real child assertion
boundaries that it executes, such as `installer-ui`,
`login.autologin-enabled`/`login.autologin-disabled`,
`theme.cursor-user-session`, `files.appimage-open`,
`files.exe-thumbnail-fixture`, `files.exe-open-fixture`,
`journal.boot-and-idle`, and
`boot.plymouth-anduinos-logo`. Every
child is shown as NOT STARTED, RUNNING, PASSED,
or FAILED; the journal child also reports the number of classified known
diagnostics. Small terminals keep the currently running child visible and show
which slice of the child list is on screen. After a source installation passes,
the same scenario expands as `installation scenario -> feature suite -> check`.
Feature suites use a read-only promoted base plus one qcow2 overlay; they do not
repeat the installation.

The top-level progress denominator deliberately remains the number of complete,
disposable installations. Child checks reuse those installed systems and are
not additional VM installations. Redirected output and CI preserve every case
and child transition line by line. `TEST_ARGS=--no-tui` forces that plain mode
locally. `summary.json` and `junit.xml` are generated from that same dashboard
state. With `--fail-fast`, every unstarted case, suite, and child remains in
both reports as `pending`/JUnit error instead of disappearing or looking green.

Every completed installation exposes the lightweight package/runtime contracts
as separate children immediately after the ISO-detached target boot:
`system.inotify-max-user-instances`, `terminal.ptyxis-initial-size`,
`desktop.mime-defaults`, `command.why-placeholder`,
`font.selection-contracts`, and `boot.plymouth-theme-selection`. The runner
collects all six verdicts in that guest, then stops that scenario before GDM or
feature overlays when any contract fails. This catches image-wide composition
defects in the first installation while still showing independent evidence for
the other contracts.

The release-gate Spotify search uses only metadata already shipped in the
installed image. Before opening ArcMenu, QMP drops the VM's sole virtio NIC and
the guest proves carrier is down; the resulting GNOME Software details page
therefore cannot be a public-network false positive. Public catalog freshness
remains a separate `store.spotify-public` check in `nightly-online`. That check
refreshes the system Flathub AppStream metadata from the declared HTTPS remote,
resolves the exact `app/com.spotify.Client/x86_64/stable` ref and commit, proves
the refreshed local cache contains that same entry, reloads GNOME Software,
and then repeats the real ArcMenu-to-details-page workflow with networking up.
Failures before public resolution are labelled `external-catalog`; once the
catalog resolves, a desktop search/navigation failure is labelled
`product-regression`.

The `shell-shortcuts` suite also sends a real `Ctrl+Alt+F6` chord through QMP.
It requires the kernel's `/sys/class/tty/tty0/active` to report tty6 and reads
`/dev/vcs6`, the character-cell buffer for what that virtual terminal actually
displays. This deliberately requires no diagnostic utility in the installed
image. The buffer must contain `AnduinOS` and no Ubuntu branding. The harness
then returns to the exact VT which owned the user's Wayland session and verifies
that GDM, the graphical target, and that same session are still active.
The scoped journal verdict records SPICE vdagent's exact, version-bound
no-active-session diagnostic during that deliberate transition as known
evidence, with a finite occurrence budget; the same error outside this action
or beyond that budget still fails the release gate.

The taskbar suite includes a self-contained GTK4 StatusNotifierItem fixture.
It speaks the same `org.kde.StatusNotifierItem` and `com.canonical.dbusmenu`
protocols consumed by GNOME Shell's production AppIndicator extension; no
test-only binding is installed in the guest. A real Alt+F4 must hide its GTK
window while preserving the kernel PID and process start time. The runner then
requires one semantic lower-right Shell indicator, double-clicks that exact
geometry through host input using the extension's activation gesture, and
requires the same process/window to return. This proves AnduinOS tray
infrastructure independently of any third-party account state.

`PROFILE=nightly-online` additionally runs the public-ecosystem overlay on
amd64. It includes the current Flathub Spotify workflow described above. Its
CPU-Z check downloads CPUID's pinned 2.20.2 archive inside the
ordinary installed user's session, verifies the archive and `cpuz_x64.exe`
digests, and requires one of EXE Runner's two declared PE MIME types plus the
AnduinOS EXE Runner default.
Nautilus must generate the executable's embedded white-on-purple CPU-Z icon,
and a real double-click must make EXE Runner recognize CPU-Z and show its
CPU-X native-alternative recommendation. The Get CPU-X, Force Run Anyway, and
Cancel actions must all be visible and usable; the test deliberately does not
activate a public store action or install Bottles.

The same overlay's Nextcloud check invokes the installed user's real
`sudo add-apt-repository -y ppa:nextcloud-devs/client` command under a
temporary, exact-command sudo rule, requires a signed source for the installed
`VERSION_CODENAME`, and proves that APT downloaded an index from that PPA. The
rule is removed before the overlay is discarded. Because Launchpad availability
is external state, this check is intentionally not part of the deterministic
default release gate.

The separate `public-wechat` overlay installs the current `com.tencent.WeChat` stable
Flatpak from the declared Flathub remote. The resolved public ref and commit
must exactly match the installed deployment, and its exported desktop launcher
must remain inside that deployment. QMP then launches WeChat from the real
ArcMenu result. Tencent's proprietary X11/Qt window does not expose an AT-SPI
application, so the window oracle uses its EWMH identity, mapped state and
geometry, then requires the captured region to contain the black/white QR
structure and green login marker. This anonymous public nightly ends there:
closing the QR login window exits current WeChat builds, so it cannot honestly
assert post-login tray behavior without an authenticated account.

The separate `app.wechat-tray` platform-lab contract starts from an explicitly
provided, disposable authenticated WeChat profile. It sends Alt+F4, requires the
same kernel PID and process start time to remain alive with no main window,
locates a semantic WeChat
AppIndicator rendered by GNOME Shell in the lower-right screen region,
double-clicks it through host input using the extension's activation gesture,
and requires the same process and window to return.
The process identity comes from the EWMH client PID and `/proc`; `flatpak ps`
is retained as diagnostic evidence but is not treated as an infallible liveness
oracle because proprietary applications may daemonize inside their sandbox.
No account state or QR-login bypass is synthesized by the public test runner.
Catalog and Tencent payload download failures are labelled external; launcher
and window failures are product regressions. Authenticated tray geometry,
process replacement, and restoration remain platform-lab verdicts.

`CASES` and `SUITES` accept space-separated subsets, `PROFILE` selects
`install`, `release-gate`, `nightly-online`, or `platform-lab`, and `TEST_ARGS`
passes additional runner arguments:

```bash
make test \
  ISO=dist/AnduinOS-2.0.2-amd64.iso \
  ARCH=amd64 \
  CASES='bios-offline-btrfs uefi-nosb-online-btrfs-ssh-toggle' \
  TEST_ARGS='--fail-fast'
```

Without `--fail-fast`, a feature suite continues after a failed product
assertion while its disposable VM remains healthy, so one defect cannot hide
later declared checks. Protocol/configuration failures and an exited QEMU still
stop that suite immediately. `--fail-fast` stops at the first failed check,
suite, or installation scenario.

For a quick boot-only check, select an explicit scenario and add `--smoke`.
This proves firmware boot, graphical.target, GDM, network policy and the serial
control channel, but intentionally does not count as an installation pass.

## Network and firmware semantics

Offline means QEMU reports the virtual NIC link down through QMP. The guest
must observe no carrier and must fail to reach its configured APT mirror.
Online means the exact APT mirror and suite configured in the ISO must return
an InRelease file before the installer runs.

The amd64 `uefi-nosb-wifi-btrfs` case is deliberately neither of those modes.
It keeps QEMU Ethernet down and creates two `mac80211_hwsim` radios inside the
disposable guest. One radio provides a WPA2 AP and local DHCP while the other
is controlled by GNOME and NetworkManager. The AP advertises no router and no
DNS, so the installer must still classify Internet-dependent choices as
unavailable. After installation the harness recreates the AP but never gives
the installed NetworkManager process its PSK; successful association with the
same UUID therefore proves credential migration. Real USB/PCI Wi-Fi remains a
separate `platform-lab` responsibility.

Release-gate infrastructure should route the configured mirror to a pinned,
signed snapshot. Public mirrors are appropriate for nightly coverage, not a
deterministic release gate.

The default UEFI lookup uses Secure-Boot-capable OVMF/AAVMF code for both UEFI
modes. The no-Secure-Boot matrix uses an unprovisioned VARS template; Secure
Boot uses a Microsoft-key-provisioned template. Custom lab firmware can be
provided with `--uefi-code`, `--uefi-vars`, and `--secure-boot-vars`.
On amd64, shim-backed and non-Secure-Boot UEFI use the graphical regional
menuentry workflow described above. On cross-architecture ARM64 TCG, SPICE
delivers the bounded GRUB scan codes and framebuffer stability gates each next
command. After `boot`, every firmware mode must passively emit a kernel
command-line diagnostic on its operating-system console. It must then observe
the debug shell's own Bash prompt marker before the harness may send a probe.

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
- losslessly compressed PNG screenshots at Live, completion, GDM, MOK, or
  failure boundaries;
- hashes, sizes, and behavioral evidence for the fresh UEFI VARS used by that
  case; the writable VARS copy itself is discarded after QEMU stops;
- `summary.json` and `junit.xml`, including failed and not-started parent/child
  verdicts from the same state shown by the TUI;
- `target-disk-retention.txt`, recording whether the disposable target disk was
  discarded or explicitly retained.

Passed and failed target disks and disposable UEFI VARS are both discarded by
default after QEMU stops; logs, losslessly compressed screenshots, serial
transcripts, UI evidence, and the summary remain. This keeps a matrix from
accumulating one multi-gigabyte qcow2 or firmware-state copy per case.

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
is reaped, and removes its private tmpfs workspace on normal exit, assertion
failure, SIGINT, or SIGTERM. `run.py` also keeps the native/UI-heavy runner in
a supervised child. QEMU, Xvfb, and the SPICE viewer carry a Linux
parent-death signal, while the minimal parent owns the exact workspace token.
If Pillow, GI, AT-SPI, or another native component kills the worker with
SIGSEGV, the parent terminates the remaining process group and removes only
that token's RAM-disk workspace or exact `target.qcow2`/`overlay.qcow2` names.
Durable logs and screenshots are not deleted. The worker installs Python's
fatal-signal handler before importing any native UI modules; an actual native
crash retains every Python thread in `worker-fault.log`, while a normal run
does not leave an empty crash artifact. A failure-injection unit test uses a
real SIGSEGV and a separate-session child to enforce both evidence retention
and resource reclamation. A small CI tmpfs therefore falls back safely instead
of failing halfway through an installation.

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
runner exits. An externally delivered SIGKILL to the supervisor or host power
loss cannot execute filesystem cleanup; Linux parent-death containment still
prevents direct VM/display children from continuing after the supervisor is
killed, and a subsequent run refuses to reuse an existing artifact directory.

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

The current GNOME 50 policy recognizes four bounded diagnostics observed in
AnduinOS with Ubuntu's GNOME packages: GDM cannot unlock a password-protected
login keyring when automatic login supplies no password, `gsd-keyboard` can
emit one null-variant assertion during input-source startup, Mutter can emit
one transient stack-position assertion, and GNOME Shell can encounter one
not-yet-constructed icon while sizing its hidden stock Dash as Settings About
starts. The Dash exception applies only to the exact GNOME 50 stack during the
`settings-about-branding` action; the real About identity, rendered logo,
Shell process, and graphical session must still pass their independent
oracles. These diagnostics are non-blocking only in their applicable scope.
The same run independently requires a live GNOME Shell, `gsd-keyboard`, GNOME
Keyring daemon, configured Rime input source, working extensions, window
activation, and SPICE resizing. A failed functional oracle remains fatal
regardless of the Journal exception.

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

The AppImage and PE fixtures are separate child checks. Nautilus opens each
fixture through real host-delivered input: a SPICE double-click when AT-SPI
provides trustworthy global bounds, otherwise QMP Tab establishes observable
focus on the selected item/content view before QMP Enter activates it. The
driver never accepts `Atspi.Action.do_action()` returning true as proof that a
file opened. Evidence records the exact semantic selection, completed host
input request, MIME type, applicable handler state, and resulting process and
accessible-window state. A failed AppImage check cannot prevent the PE check
from running, or vice versa.
If AppImage activation fails, a direct same-session launch is used only to
record whether the runtime itself stays alive and what it writes to stderr;
that diagnostic can never turn the failed Nautilus check green.
