# ISO acceptance tests

Run the complete release test from the repository root:

```bash
make test
```

The command verifies the framework, then boots the newest ISO in `dist/` and runs
every installation and desktop suite. Exit zero requires every declared check to pass.
Failures, interruptions, missing prerequisites, unavailable services and unexecuted
checks all prevent release approval.

Pass `ISO=/path/to/image.iso` and `ARCH=amd64|arm64` only when the newest image
cannot be selected automatically. `TEST_ARGS=--no-tui` switches to persistent
plain output without changing which tests run.

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

The `public-ghex` suite verifies a fresh installation of GHex from the configured public Flathub remote, checking commit, origin, desktop entry,
application version and ArcMenu launch into a real GTK window; it does not test editing.
External catalog/download failures are reported as failures, not skipped passes.
GHex uses an isolated local search; Spotify suites retain the Software provider.
Plymouth is checked before debug injection and retains failed frames; **BLOCKED** prerequisites prevent release.

`factory-reset-repeat` removes GNOME Clocks and creates Home files, then resets the same
disposable VM twice: preserve Home, then roll back Home while retaining browsable snapshot history.
Both boots must restore baseline GNOME Clocks, package health and desktop login, with QEMU blocking Internet access. Dependency-checked `dpkg` removes only GNOME Clocks; the snapshot manager must remain installed. Package edge cases stay in AnduinOS-Packages.
The power-loss overlay adds serial observation and a temporary confirmation mask to its recovery entry. After cutting QEMU at the durable apply checkpoint, it verifies the fallback checkpoint in the next boot's journal and rollback history (the fallback boots without the injected serial argument); a final clean boot must reconcile the transaction. Normal reset/rollback suites use unmodified recovery boots.

`btrfs-home-rollback` uses the Home GUI and an offline reboot: user files return,
root/package state stays unchanged, both histories are browsable and login works.
It requires Home-only support in the ISO; older packages fail, never skip.

`rescue-center-offline-restore` takes a system snapshot, uninstalls GNOME Shell, proves the installed desktop cannot start, then boots the tested Live ISO and drives the real Rescue Center UI with host QMP pointer clicks. It selects the damaged installation and baseline, keeps the default safety snapshot enabled, restores offline, removes the Live ISO, and requires a healthy graphical boot, restored package state, preserved newer Home data, and an archived transaction.

The installation matrix boots temporary Live overlays on the original
read-only ISO. One amd64/arm64 scenario additionally boots a writable hybrid
copy through the real Dracut persistent menu entry, writes a sentinel, powers
off, and boots the same media again before installation. Persistence is not
credited from GRUB text inspection alone.

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
