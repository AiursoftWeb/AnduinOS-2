# ISO acceptance tests

Run the complete release test below; `make test TEST_ARGS="--live-usb-only --no-tui"` selects only the AMD64 Rufus ISO-mode regression (default/custom FAT labels, UEFI, Live login and media integrity; not a release verdict):

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

`live.offline-no-notifications` checks every offline installation's first Live
desktop before opening the installer. QEMU disconnects its NIC before boot.
The check inventories retained startup notifications and observes new Shell
MessageTray notifications for at least 10 seconds, recording title/body in
`live-notifications.json`. It catches Shell extensions' native notifications as
well as D-Bus app notifications, in any language. A test-only module is loaded
through Looking Glass, which immediately closes; it neither clears notifications
nor disables extensions, changes notification settings, or enables unsafe D-Bus
Eval. A missing observer, unavailable API or Shell restart fails the check.
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
GHex uses an isolated local search; Spotify suites retain the Software provider.
Plymouth is checked before debug injection and retains failed frames; **BLOCKED** prerequisites prevent release.

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

`rescue-center-offline-restore` takes a system snapshot, uninstalls GNOME Shell, proves the installed desktop cannot start, then boots the tested Live ISO and drives the real Rescue Center UI with host QMP pointer clicks. It selects the damaged installation and baseline, keeps the default safety snapshot enabled, restores offline, removes the Live ISO, and requires a healthy graphical boot, restored package state, preserved newer Home data, and an archived transaction.

The installation matrix boots temporary Live overlays on the original
read-only ISO. One amd64/arm64 scenario also boots a writable hybrid copy,
writes a sentinel, powers off, and boots the same media again before
installation. The test obtains the persistent kernel arguments from the
actual ISO and enters them through that ISO's GRUB command prompt; it does
not depend on the editor's visual line count. The separate optical-media
case executes the real To Go menu entry and requires its rejection warning.
Persistence is credited only when the running guest retains the sentinel
across boots, not from GRUB text inspection alone.

## Firmware regression coverage

The `uefi-unsupported-offline-btrfs` and `uefi-unsupported-offline-ext4`
scenarios use the non-Secure-Boot OVMF image (`OVMF_CODE_4M.fd`). Override that
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

The default AMD64 `make test` matrix includes two offline, UEFI Secure Boot
disabled cases (Btrfs, one disposable 112 GiB sparse disk per case):

- `uefi-nosb-coexistence-shared-esp-rejected`: install A through Advanced/manual
  partitioning, boot and log into A, reboot the ISO, plan B using A's ESP, require
  the occupied-ESP dialog and disabled Next button. GPT, firmware entries and
  SHA-256 of **all A partitions** must remain unchanged; A must still boot and
  accept a desktop login without the ISO.
- `uefi-nosb-coexistence-separate-esp`: install/boot A the same way, then install
  B through Advanced with its own ESP in the remaining space. A's partition
  identities, boundaries, contents and firmware entry must be preserved. Boot B
  without the ISO, then execute B's generated GRUB chainloader entry for A and
  log into A. Root UUID, mounted ESP UUID, distinct hostnames and BootCurrent
  distinguish the two systems and reject accidental firmware fallback.

Each installation uses 1 GiB ESP + 50 GiB Root + 3 GiB Swap. There is no shrink,
shared-ESP override or installer modification. Before an installed A/B guest is
closed through QMP, its ESP is explicitly unmounted: `sync` alone leaves FAT's
dirty bit set. Before planning B, a read-only `fsck.fat -n` must pass; the harness
never repairs an unhealthy ESP to satisfy the test. These cases require ISO packages
`anduinos-installer-beta >= 2.0.4-3` and `anduinos-secureboot-toolkit >= 2.0.4-2`; old ISOs
fail the version check. Build with `make` after publication, then `make test`.
They do not cover Secure Boot/MOK, Ubuntu coexistence, or ext4/Btrfs resizing.

The harness adds the existing reversible serial debug arguments only to the
target's generated kernel lines and restores the original GRUB file after boot.
For B → A it uses GRUB's `next_entry` (the `grub-reboot` mechanism) to select the
**existing generated menuentry**; it does not synthesize boot commands or test
keyboard menu navigation. The full A hashes are captured before any B writes
and compared before adding A's next-boot instrumentation. Full-partition hashing
adds runtime; the existing disk-capacity safety checks apply to the larger disk.
These two cases use the results filesystem even when other cases use tmpfs:
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
