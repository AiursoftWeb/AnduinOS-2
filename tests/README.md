# ISO acceptance tests

Run the complete release test below; `make test TEST_ARGS="--live-usb-only --no-tui"` selects only the Rufus ISO-mode regression (default/custom FAT labels, UEFI, Live login and media integrity; not a release verdict):

```bash
make test
```

After the unit tests, the dashboard shows cases, suites and checks from startup.
The ISO media case runs three suites once per ISO; installation cases follow.
Every assertion is a third-level check, including USB, install and desktop.
The final summary uses the same tree; failed or unexecuted checks block release.

Pass `ISO=/path/to/image.iso` and `ARCH=amd64|arm64` only when the newest image
cannot be selected automatically. `TEST_ARGS=--no-tui` switches to persistent
plain output without changing which tests run.

For a targeted regression, repeat `--case` with exact installation case IDs:

```bash
make test ISO=dist/your-image-amd64.iso TEST_ARGS="--case uefi-nosb-coexistence-shared-esp-rejected --case uefi-nosb-coexistence-separate-esp --case uefi-nosb-offline-manual-small-disk"
```

This still runs all unit tests and any desktop suites belonging to the selected
cases, but skips the ISO USB suites and other installations. The console and
summary explicitly mark it as a partial regression, **not a release verdict**.
Unknown or architecture-incompatible IDs fail; `--case` cannot be combined with
`--live-usb-only`. Plain `make test` continues to run the full release matrix.

Installed graphical checks hold a temporary GNOME idle inhibitor after login
and release it before shutdown, including on failure. Acquisition and release
are recorded in the case artifacts. The product's idle delay and lock policy
remain unchanged; passive boot checks run without the inhibitor.

For the offline Secure Boot first-install regression:

```bash
make test TEST_ARGS="--case uefi-sb-offline-btrfs --no-tui"
```

The existing installer/MokManager workflow enters `123456`, enrolls the fresh
certificate and boots the installed system with Secure Boot enabled and the
NIC disconnected. `secure-boot.first-boot-green` checks the unified certificate
purpose, matching protected private key, default DKMS signing configuration,
enrollment and driver trust. It then opens the real Driver Center as the logged-in
user and requires all six healthy row states on AMD64 and ARM64, including the
AnduinOS bootloader signature, enrollment and deployment, the `Trusted` summary and no
repair/enrollment action. The normal Check Again button is allowed. No repair
is performed by this check. No installed
third-party modules is a valid healthy state; DKMS itself need not be installed.
The check also runs in both online Secure Boot cases. Public status evidence,
the accessibility tree, application log and a screenshot are retained; private
keys are never copied into these artifacts. This is a semantic UI assertion,
not a pixel-color test.

Installed GDM login uses the same AT-SPI account and password-page recognition
as the account-management checks, then sends the password through QMP once.
It waits for the requested user’s session bus and Wayland socket within the
existing login timeout; a slow greeter cannot consume blind keyboard retries.
The modular guest driver is transferred as one verified compressed archive.

Factory-reset checks that erase Home use password SSH after the control key is
removed. Both key and password SSH waits continuously drain the guest UART so
firmware output cannot block boot; recovery health and old-key removal checks
remain required.

The offline Secure Boot Btrfs and offline non-Secure-Boot ext4 cases also
remove only the verified AnduinOS NVRAM entry after checking normal registration.
Before removal, they require the four direct `EFI/BOOT` files to match the vendor
chain and reject the shim fallback registrar. Firmware trust variables and all
other boot entries must remain unchanged. The ISO is detached and the existing
VARS file is retained for default firmware boot, including MokManager when
required. First target boot must use a non-vendor entry and report a valid,
deployed GRUB. Other installation cases retain normal vendor-entry coverage.
The injection and recovery probes are saved as case artifacts.

The `rescue-boot-repair` and `rescue-boot-reject-source` desktop suites use
separate overlays of the online Secure Boot Btrfs installation on both architectures,
with external network access blocked throughout rescue. The first corrupts the
derived signed GRUB and removes the vendor ESP GRUB, then drives the ISO's Rescue
Center with real pointer input. Independent readback verifies the target certificate,
PE architecture, configuration and unchanged fallback files before a normal boot
without the ISO. The actual vendor boot entry, Secure Boot and six healthy Driver
Center rows must pass. The second corrupts the pristine package payload and requires
an explicit GUI rejection with all previous EFI files preserved. Neither suite
installs repair packages into Live or repairs the target outside the GUI. Fault,
repair-result and final desktop screenshots accompany signature and boot evidence.

## Architecture coverage

Every UEFI installation case runs on AMD64 and ARM64, including Wi-Fi credential
migration, cross-language installation, small disks and sequential coexistence.
Both architectures run the same media checks and common desktop suites from the
same UEFI installation bases. Firmware, EFI loader and native Flatpak names are
selected for the guest architecture; wrong-architecture evidence remains a failure.

The three BIOS cases are AMD64-only. The public Spotify catalog check is also
AMD64-only because its upstream Flatpak publishes only x86_64; it has a separate
`public-spotify` suite so it cannot exclude CPU-Z file handling or the Nextcloud
PPA workflow from ARM64. CPU-Z is tested as a Windows file, not executed natively.
GHex installation and launch use native x86_64/aarch64 refs on both platforms.

The shared `shell-store-search` suite searches for Inkscape on AMD64 and ARM64
with the QEMU NIC disconnected, then opens its cached GNOME Software details.
Inkscape is available on both architectures; the separate public Spotify check
retains its AMD64-only catalog contract.

## Layout

```text
tests/
├── cases/       Installation matrix and desktop suite declarations
├── assertions/  Product assertions and guest-side drivers
├── business/    Installation and desktop workflows
├── fixtures/    Deterministic applications and files used by UI tests
├── framework/   QEMU, firmware, storage, UI control, TUI, and reporting
├── unit/        Fast checks that keep the framework fail-closed
└── run.py       Supervised command entry point
```

The JSON files under `cases/` are the executable inventory. Declared checks without implementations fail unit tests. Every selected installation and suite must produce a verdict.

Test outcomes, not incidental UI timing or source layout. A VM is paused until
its control channels are ready; GRUB input is acknowledged by observed menu
state, while installation and recovery pass only after their guest-visible
effects are verified. If instrumentation bypasses a menu entry, an independent
case must exercise that entry's user-visible behavior.

`panel.autohide-drag-recovery` in `shell-panel-taskbar` checks ordinary
hide/reveal, then three left-button drags to the bottom edge and subsequent
recovery on AMD64 and ARM64. QMP supplies real input; a read-only Looking Glass
observer records pointer/button state and transformed panel bounds. The check
restores the original preference overrides and releases the mouse even on failure.

`live.offline-no-notifications` checks every offline installation's first Live
desktop before opening the installer. QEMU disconnects its NIC before boot.
The check inventories retained startup notifications and observes new Shell
MessageTray notifications for at least 10 seconds, recording title/body in
`live-notifications.json`. Two normal notices are permitted:

- GNOME Software's **Updates Are Out of Date / Please check for available updates**
  reminder, matched by application identity and exact translated title/body.
- GNOME Shell's **installer window is ready** notice, matched by its native
  window-attention source, tracked installer identity and exact translated text.
  An ordinary application notification with the same wording is not exempt.

Other notices still fail. Permitted notices remain in the evidence; application
behavior and notification settings are unchanged.
The check covers Shell-native and D-Bus notifications in any language.
A test-only module is loaded
through Looking Glass, which immediately closes; it neither clears notifications
nor disables extensions, changes notification settings, or enables unsafe D-Bus
Eval. Before each keyboard submission, a read-only AT-SPI probe verifies the
correct Shell prompt, focused input and exact typed text. Its handshakes are
retained in `live-notifications-ui.jsonl`; startup shortcut readiness is retried
at most three times. A missing observer, unavailable API or Shell restart fails
the check.
The window begins once the Live desktop is ready and the observer attaches, not
at kernel boot; transient notifications already destroyed before attachment are
not covered. The current offline matrix uses the US Live keyboard for QMP input.

`localization.english-fallback` runs Firewall, Swap Control, YubiKey Manager,
Disk Snapshots Manager and Control Panel with
`--help` under a temporary Croatian locale and requires successful, nonempty
output from each. It catches missing-translation startup panics without opening
windows or changing the desktop language; it does not verify English GUI text.

The `public-ghex` suite verifies a fresh installation of GHex from the configured public Flathub remote, checking commit, origin, desktop entry,
application version and ArcMenu launch into a real GTK window; it does not test editing.
External catalog/download failures are reported as failures, not skipped passes.

The AppImage compatibility fixture downloads the current official Type-2 runtime
for the guest architecture when it is built. It does not pin an upstream digest
or reuse a runtime from an earlier run. The check verifies the generated
AppImage format and actual desktop launch; upstream runtime updates do not
require maintaining a hash in this repository.
GHex uses an isolated local search; Spotify suites retain the Software provider.
Plymouth is checked before debug injection and retains failed frames; **BLOCKED** prerequisites prevent release.

The boot journal retains one exact kernel `PCI: OF: of_root node is NULL,
cannot create PCI host bridge node` message as a known diagnostic only when
guest sysfs confirms one ACPI PCI root, no Device Tree, and driver-bound storage,
network and display controllers. The collected topology is retained in
`installed-pci-firmware.json`; missing evidence, repeated messages and other PCI
errors still fail. This rule is identical on both architectures and leaves all
functional assertions intact. The optional PCI-to-DT helper continues normal PCI
enumeration; [the upstream fix](https://github.com/torvalds/linux/commit/0111d600f0f456d09eb0ff6ac217fa5f30ae79ab)
changes only its log level from error to debug.

`system-lifecycle` reinstalls the actual installed kernel and theme packages in
its disposable VM, removes generated module dependency indexes, and configures
Plymouth and Disk Snapshots Manager before the pending kernel. Their updates
must defer through the official Dracut trigger. Kernel configuration must then
restore the indexes, generate valid images with both modules, and leave dpkg
healthy; the existing ordinary reboot check follows this transaction. This
regression covers package configuration ordering, not every historical upgrade
or every future kernel. Exact installed package versions must remain downloadable.

`factory-reset-repeat` removes GNOME Clocks and creates Home files, then resets the same
disposable VM twice: preserve Home, then roll back Home while retaining browsable snapshot history.
Both boots must restore baseline GNOME Clocks, package health and desktop login, with QEMU blocking Internet access. Dependency-checked `dpkg` removes only GNOME Clocks; the snapshot manager must remain installed. Package edge cases stay in AnduinOS-Packages.
The power-loss overlay adds serial observation and a temporary confirmation mask to its recovery entry. After cutting QEMU at the durable apply checkpoint, it verifies the fallback checkpoint in the next boot's journal and rollback history (the fallback boots without the injected serial argument); a final clean boot must reconcile the transaction. Normal reset/rollback suites use unmodified recovery boots.

`btrfs-home-rollback` uses the Home GUI and an offline reboot: user files return,
root/package state stays unchanged, both histories are browsable and login works.
It requires Home-only support in the ISO; older packages fail, never skip.

`recovery-kernel-rollback` runs on both architectures as part of default `make test`, using the offline Btrfs installation. It creates A, boots it successfully, corrupts all installed kernels and initrds, and creates B. The normal boot must fail. With no Live ISO attached, it enters the dedicated recovery environment through GRUB, selects the row marked as the last successful boot, confirms rollback, and restarts. Independent checks require A's original kernel/initrd hashes, preserved newer Home data, B still containing the fault, and two successful graphical boots. Screenshots cover the fault, recovery list, confirmation, result, and restored system. This case currently uses Secure Boot disabled; it does not claim recovery payload authentication.

`rescue-center-offline-restore` takes a system snapshot, uninstalls GNOME Shell, proves the installed desktop cannot start, then boots the tested Live ISO and drives the real Rescue Center UI with host QMP pointer clicks. It selects the damaged installation and baseline, keeps the default safety snapshot enabled, restores offline, removes the Live ISO, and requires a healthy graphical boot, restored package state, preserved newer Home data, and an archived transaction.

Wi-Fi lab setup waits for NetworkManager to answer before configuring radios;
Live rescue waits for the active local Wayland session before launching its UI.
Both waits are bounded and retain readiness evidence. Shutdown waits and
key-based feature SSH commands continuously capture UART output. Stalled-shutdown
diagnostics use SSH, without competing serial readers or extending the shutdown limit.
Clean ext4 shutdown respects an active Dracut migration inhibitor within that limit.

The installation matrix boots temporary Live overlays on the original
read-only ISO. One amd64/arm64 scenario also boots a writable hybrid copy,
writes a sentinel, powers off, and boots the same media again before
installation. The test obtains the persistent kernel arguments from the
actual ISO and enters them through that ISO's GRUB command prompt; it does
not depend on the editor's visual line count. The separate optical-media
case executes the real To Go menu entry and requires its rejection warning.
Persistence is credited only when the running guest retains the sentinel
across boots, not from GRUB text inspection alone.

`unlock-theme` runs on a fresh installed-system overlay using the account's
existing extension preferences. It requires default unlock-theme enablement,
then locks and authenticates with real keyboard input in Fluent dark and light
modes. A read-only Looking Glass observer records the actual application and
custom stylesheets: the unlock extension and readability layer must own the
locked screen, then relinquish ownership to desktop User Themes after unlock.
The Shell PID must stay unchanged. Missing enablement is a failure, never repaired
by the test. The observer neither changes styles nor reads password contents;
per-mode screenshots and structured state evidence are retained. This is a
loading/ownership and authentication check, not a pixel-perfect visual verdict.

## Firmware regression coverage

The `uefi-unsupported-offline-btrfs` and `uefi-unsupported-offline-ext4`
scenarios use the non-Secure-Boot OVMF (`OVMF_CODE_4M.fd`) or AAVMF
(`AAVMF_CODE.no-secboot.fd`) image for the target architecture. Override that
specific image with `--uefi-unsupported-code`; `--uefi-code` remains the image
for enabled/disabled Secure Boot scenarios. Each VM gets a fresh variable store.

Both the Live environment and the installed disk boot must independently
report UEFI with an absent SecureBoot variable and the customer's real
`mokutil` exit 255. A disabled toggle is not accepted as unsupported. The GUI
must complete the firmware check and skip the Secure Boot recommendation for
unsupported UEFI and BIOS. Unknown detection cannot pass this UI gate. Installed
boot verification runs after removing the ISO, with no MOK request left pending.
The ISO must contain installer, toolkit, and Live settings versions at least
`2.0.4-1`, including the initial firmware diagnostic written by Live setup.

## Sequential AnduinOS coexistence

The default AMD64 and ARM64 `make test` matrices includes three offline, UEFI Secure Boot
disabled cases (one disposable 112 GiB sparse disk per case):

- `uefi-nosb-coexistence-shared-esp-rejected`: install A through Advanced/manual
  partitioning, boot and log into A, reboot the ISO, plan B using A's ESP, require
  the occupied-ESP warning, explicitly choose Back (decline replacement), and
  require a disabled Next button. GPT, firmware entries and
  SHA-256 of **all A partitions** must remain unchanged; A must still boot and
  accept a desktop login without the ISO.
- `uefi-nosb-coexistence-separate-esp`: install/boot A the same way, then install
  B through Advanced with its own ESP in the remaining space. A's partition
  identities, boundaries, contents and firmware entry must be preserved. Boot B
  without the ISO, then execute B's generated GRUB chainloader entry for A and
  log into A. Root UUID, mounted ESP UUID, distinct hostnames and BootCurrent
  distinguish the two systems and reject accidental firmware fallback.
- `uefi-nosb-coexistence-ext4-shrink`: install and boot A with a 96 GiB ext4
  root, return to Live, plan shrinking A to 40 GiB through the real resize
  dialog and acknowledge the backup warning. Install B with its own ESP and
  50 GiB ext4 root in the released space. Verify A's UUID/PARTUUID/start,
  exact new boundary, read-only file/symlink/mode/owner manifest, and byte hashes
  of its unchanged ESP/swap. Boot B without ISO, then chainload and log into A
  through B's generated GRUB entry. This case requires installer >= 2.0.4-15.
  Installed ext4 guests shut down normally through systemd and QEMU must exit;
  `sync` followed by a QMP hard stop would leave a mounted root's journal dirty
  and is not a valid offline-shrink baseline.

The first two cases use Btrfs with 1 GiB ESP + 50 GiB Root + 3 GiB Swap per
installation, with no shrinking. All three cases avoid a shared-ESP override
or installer modification. Before an installed A/B guest is
closed through QMP, its ESP is explicitly unmounted: `sync` alone leaves FAT's
dirty bit set. Before planning B, a read-only `fsck.fat -n` must pass; the harness
never repairs an unhealthy ESP to satisfy the test. These cases require ISO packages
`anduinos-installer-beta >= 2.0.4-3` and `anduinos-secureboot-toolkit >= 2.0.4-2`; old ISOs
fail the version check. Build with `make` after publication, then `make test`.
They do not cover Secure Boot/MOK, Ubuntu coexistence, Btrfs resizing, or
power loss during ext4 resizing. The ext4 case's manifest mounts `ro,noload`
after `e2fsck -f -n`: the harness does not repair the old filesystem to make
preservation pass. Raw root-partition hashes are inappropriate after resizing
because filesystem blocks relocate; other original partitions still require
byte-for-byte preservation. Compare the file manifest before any next-boot
instrumentation changes GRUB.

The harness adds the existing reversible serial debug arguments only to the
target's generated kernel lines and restores the original GRUB file after boot.
For B → A it uses GRUB's `next_entry` (the `grub-reboot` mechanism) to select the
**existing generated menuentry**; it does not synthesize boot commands or test
keyboard menu navigation. The full A hashes are captured before any B writes
and compared before adding A's next-boot instrumentation. Full-partition hashing
adds runtime; the existing disk-capacity safety checks apply to the larger disk.
These three cases use the results filesystem even when other cases use tmpfs:
two installations must not exceed the existing single-install 12 GiB RAM-disk
limit. Allow at least 122 GiB free there (112 GiB disk plus the default 10 GiB
reserve); qcow2 only allocates written data and is removed after each case.

## Results

Each run writes `summary.json`, `junit.xml`, screenshots, logs and per-check diagnostics
under `test-results/`. Disposable disks, overlays and writable Live copies are removed,
including after interruption. Keep the result directory when reporting failures:
its evidence distinguishes product, host prerequisite and external service failures.

Before a new matrix starts, `make test` also reclaims disposable disks orphaned
by an uncatchable `SIGKILL`, power loss, or host reboot. A kernel-backed lease
prevents cleanup while another acceptance run is active. The scanner removes
only the exact `target.qcow2`, `overlay.qcow2`, and `live-media.raw` paths from
user-owned result directories; it preserves logs, screenshots, structured
evidence, explicit single-case debug disks, foreign-owned paths, and symlinks.

Run the same cleanup without starting QEMU through the singular test entrypoint:

```bash
python3 tests/run.py clean-disks
```

Preview reclaimable allocation without changing files:

```bash
python3 tests/run.py clean-disks --dry-run
```

The `voice-typing` installed-system suite runs on both architectures using
`uefi-nosb-online-btrfs-ssh-toggle`. It installs the optional Voice Typing package
through Control Panel and its real authorization dialog, logs out and back in
through GDM, then sends Super+H through QMP. The native daemon must calibrate on
its first start, reach listening with the Shell overlay, and persist a valid
selection. A second invocation and another login after changing the recognition
language must reach listening without calibration or rewriting that cache.
D-Bus transitions, cache snapshots, package versions, keyboard requests and
screenshots are retained. A PipeWire virtual microphone supplies silence in the
VM; this check covers installation, activation and caching, not physical audio
hardware or transcription accuracy. Package/download errors fail the check.
