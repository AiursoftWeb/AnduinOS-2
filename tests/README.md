# ISO acceptance tests

Run the complete release test from the repository root:

```bash
make test
```

There is one test result. The command first verifies the framework, then boots
the newest ISO in `dist/`, performs every supported installation, and runs every
desktop suite. Exit code zero means every declared check ran and passed. A
failure, interruption, missing prerequisite, unavailable public service, or
unexecuted check means the ISO is not approved for release.

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

The JSON files under `cases/` are the complete executable inventory. Adding a
declared desktop check without an implementation is a unit-test failure. The
runner also fails unless every selected installation and suite produces a
verdict.

The installation matrix boots temporary Live overlays on the original
read-only ISO. One amd64/arm64 scenario additionally boots a writable hybrid
copy through the real Dracut persistent menu entry, writes a sentinel, powers
off, and boots the same media again before installation. Persistence is not
credited from GRUB text inspection alone.

## Results

Each run writes a new directory under `test-results/` containing `summary.json`,
`junit.xml`, screenshots, serial logs, installer output, journal evidence, and
per-check diagnostics. Disposable virtual disks and overlays are deleted after
the run, including the expanded writable Live-media copy and including after
interruption. Keep the result directory when filing a failure; its evidence
identifies whether the product, host prerequisites, or an external service
caused the failure.
