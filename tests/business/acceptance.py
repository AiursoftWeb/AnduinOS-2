"""Command-line interface for AnduinOS ISO acceptance tests."""

from __future__ import annotations

import argparse
import contextlib
import json
import signal
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

from framework.errors import AcceptanceError, ConfigurationError
from framework.dashboard import AcceptanceDashboard
from framework.display import SpiceDisplayController
from framework.feature_model import FeatureSuiteRegistry
from .desktop import FeatureSuiteResult, FeatureSuiteRunner
from framework.firmware import FirmwareOverrides, resolve_firmware
from framework.iso import inspect_iso
from framework.model import Architecture, LiveMode, TestMatrix
from framework.qemu import PERSISTENT_LIVE_FREE_SPACE_GIB, resolve_qemu
from framework.reporting import write_junit_report
from .install import RunnerOptions, ScenarioRunner, scenario_check_ids
from framework.storage import (
    DEFAULT_RAMDISK_THRESHOLD_GIB,
    GIB,
    assert_disk_storage_ready,
    cleanup_disk_storage,
    prepare_disk_storage,
    select_disk_storage,
)


def main(argv: list[str] | None = None) -> int:
    parser = _parser()
    args = parser.parse_args(argv)
    try:
        root = Path(__file__).parents[1]
        matrix = TestMatrix.load(root / "cases/install.json")
        registry = FeatureSuiteRegistry.load(root / "cases/desktop.json", matrix)
        architecture = Architecture(args.arch)
        selected = matrix.select(architecture, ())
        suites = registry.select(architecture)
        registry.validate_sources(
            suites,
            matrix,
            architecture,
            {scenario.id for scenario in selected},
        )
        inspection = inspect_iso(args.iso, architecture)
        overrides = FirmwareOverrides(
            uefi_code=args.uefi_code,
            uefi_vars_no_secure_boot=args.uefi_vars,
            uefi_vars_secure_boot=args.secure_boot_vars,
        )
        _preflight(architecture, selected, overrides, suites)
        persistent_live_bytes = (
            inspection.path.stat().st_size
            + PERSISTENT_LIVE_FREE_SPACE_GIB * GIB
            if any(
                scenario.live_mode is LiveMode.PERSISTENT
                for scenario in selected
            )
            else 0
        )
        options = _options(
            args,
            matrix,
            additional_disk_bytes=persistent_live_bytes,
        )
        assert_disk_storage_ready(
            options.disk_storage,
            disk_gib=options.disk_gib,
            filesystem_reserve_gib=options.free_space_reserve_gib,
            memory_mib=options.memory_mib,
            additional_bytes=persistent_live_bytes,
        )
        options.artifacts_root.mkdir(parents=True, exist_ok=False)
        prepare_disk_storage(options.disk_storage)
        try:
            print(
                f"Target disks: {options.disk_storage.backend} at "
                f"{options.disk_storage.root} ({options.disk_storage.reason})"
            )
            dashboard = AcceptanceDashboard(
                tuple(item.id for item in selected),
                iso=inspection.path,
                architecture=architecture.value,
                artifacts=options.artifacts_root,
                checks={
                    item.id: scenario_check_ids(item)
                    for item in selected
                },
                suites={
                    scenario.id: {
                        suite.id: suite.checks
                        for suite in suites
                        if suite.source_for(architecture) == scenario.id
                    }
                    for scenario in selected
                },
                live=False if args.no_tui else None,
            )
            runner = ScenarioRunner(
                inspection,
                architecture,
                matrix.defaults,
                options,
                status_callback=dashboard.phase,
                check_callback=dashboard.check,
            )
            results = []
            suite_results = []
            suites_by_source = {
                scenario.id: tuple(
                    suite
                    for suite in suites
                    if suite.source_for(architecture) == scenario.id
                )
                for scenario in selected
            }
            feature_runner = FeatureSuiteRunner(
                options,
                matrix.defaults.username,
                matrix.defaults.full_name,
                matrix.defaults.password,
                phase_callback=dashboard.suite_phase,
                check_callback=dashboard.suite_check,
            )
            dashboard.start()
            try:
                with _termination_as_interrupt():
                    for scenario in selected:
                        dashboard.begin(scenario.id)
                        source_suites = suites_by_source[scenario.id]
                        result = runner.run(scenario, promote=bool(source_suites))
                        results.append(result)
                        dashboard.complete(
                            result.id,
                            result.status,
                            result.seconds,
                            result.error,
                        )
                        base = result.promoted_base
                        try:
                            if result.status == "passed":
                                if source_suites and base is None:
                                    raise ConfigurationError(
                                        f"{scenario.id}: verified feature base was not promoted"
                                    )
                                for suite in source_suites:
                                    assert base is not None
                                    dashboard.begin_suite(scenario.id, suite.id)
                                    suite_result = feature_runner.run(base, suite)
                                    suite_results.append(suite_result)
                                    dashboard.complete_suite(
                                        scenario.id,
                                        suite.id,
                                        suite_result.status,
                                        suite_result.seconds,
                                        suite_result.error,
                                    )
                            else:
                                for suite in source_suites:
                                    error = "Source installation scenario failed"
                                    dashboard.complete_suite(
                                        scenario.id,
                                        suite.id,
                                        "failed",
                                        0.0,
                                        error,
                                    )
                                    suite_results.append(
                                        _failed_suite_result(
                                            suite.id,
                                            scenario.id,
                                            options.artifacts_root,
                                            error,
                                        )
                                    )
                        finally:
                            if base is not None:
                                base.cleanup()
                                (result.artifacts / "target-disk-retention.txt").write_text(
                                    "Temporary immutable feature-suite base deleted "
                                    "after every dependent overlay stopped.\n",
                                    encoding="utf-8",
                                )
            finally:
                dashboard.close()
            summary = {
                "schema_version": 1,
                "iso": str(inspection.path),
                "iso_sha256": inspection.sha256,
                "architecture": architecture.value,
                "disk_storage": {
                    "backend": options.disk_storage.backend,
                    "root": str(options.disk_storage.root),
                    "reason": options.disk_storage.reason,
                },
                "results": _materialize_case_results(
                    selected,
                    results,
                    dashboard,
                    options.artifacts_root,
                ),
                "feature_suites": _materialize_suite_results(
                    suites,
                    suite_results,
                    dashboard,
                    architecture,
                    options.artifacts_root,
                ),
            }
            (options.artifacts_root / "summary.json").write_text(
                json.dumps(summary, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            write_junit_report(summary, options.artifacts_root / "junit.xml")
            passed = sum(item.status == "passed" for item in results)
            suites_passed = sum(item.status == "passed" for item in suite_results)
            return (
                0
                if passed == len(results) == len(selected)
                and suites_passed == len(suite_results) == len(suites)
                else 1
            )
        finally:
            cleanup_disk_storage(options.disk_storage)
    except AcceptanceError as error:
        print(f"error: {error}", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        print(
            "error: acceptance run interrupted; QEMU and disposable disk cleanup completed",
            file=sys.stderr,
        )
        return 130


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Boot and install an AnduinOS ISO in disposable QEMU guests",
    )
    parser.add_argument("--iso", type=Path, required=True, help="ISO image under test")
    parser.add_argument(
        "--arch",
        required=True,
        choices=tuple(item.value for item in Architecture),
    )
    parser.add_argument("--artifacts", type=Path)
    parser.add_argument(
        "--no-tui",
        action="store_true",
        help="disable the live terminal dashboard",
    )
    parser.add_argument("--memory", type=int)
    parser.add_argument("--cpus", type=int)
    parser.add_argument("--disk-size", type=int)
    parser.add_argument(
        "--disk-backend",
        choices=("auto", "ramdisk", "filesystem"),
        default="auto",
        help="target qcow2 backend (default: auto-select safe tmpfs)",
    )
    parser.add_argument(
        "--ramdisk-threshold",
        type=int,
        default=DEFAULT_RAMDISK_THRESHOLD_GIB,
        metavar="GIB",
        help="minimum MemAvailable before automatic RAM-disk use (default: 16)",
    )
    parser.add_argument(
        "--free-space-reserve",
        type=int,
        default=10,
        metavar="GIB",
        help="host space that must remain beyond the guest disk (default: 10 GiB)",
    )
    parser.add_argument("--boot-timeout", type=int)
    parser.add_argument("--install-timeout", type=int)
    parser.add_argument("--command-timeout", type=int)
    parser.add_argument(
        "--firmware-delay",
        type=float,
        help="seconds from VM start to the GRUB keyboard sequence",
    )
    parser.add_argument("--uefi-code", type=Path)
    parser.add_argument("--uefi-vars", type=Path)
    parser.add_argument("--secure-boot-vars", type=Path)
    return parser


def _options(
    args,
    matrix: TestMatrix,
    *,
    additional_disk_bytes: int = 0,
) -> RunnerOptions:
    defaults = matrix.defaults
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    artifacts = (
        args.artifacts.expanduser().resolve()
        if args.artifacts
        else (Path.cwd() / "test-results" / timestamp).resolve()
    )
    delay = args.firmware_delay
    if delay is None:
        delay = 8.0 if args.arch == Architecture.ARM64.value else 3.0
    values = {
        "memory_mib": args.memory or defaults.memory_mib,
        "cpus": args.cpus or defaults.cpus,
        "disk_gib": args.disk_size or defaults.disk_gib,
        "boot_timeout_seconds": args.boot_timeout or defaults.boot_timeout_seconds,
        "install_timeout_seconds": (
            args.install_timeout or defaults.install_timeout_seconds
        ),
        "command_timeout_seconds": (
            args.command_timeout or defaults.command_timeout_seconds
        ),
    }
    for key, value in values.items():
        if value <= 0:
            raise ConfigurationError(f"{key} must be positive")
    if delay <= 0:
        raise ConfigurationError("firmware delay must be positive")
    if args.free_space_reserve < 1:
        raise ConfigurationError("free-space reserve must be at least 1 GiB")
    disk_storage = select_disk_storage(
        artifacts,
        memory_mib=values["memory_mib"],
        mode=args.disk_backend,
        ramdisk_threshold_gib=args.ramdisk_threshold,
        retain_disk=False,
        additional_bytes=additional_disk_bytes,
    )
    return RunnerOptions(
        artifacts_root=artifacts,
        disk_storage=disk_storage,
        firmware_overrides=FirmwareOverrides(
            uefi_code=args.uefi_code,
            uefi_vars_no_secure_boot=args.uefi_vars,
            uefi_vars_secure_boot=args.secure_boot_vars,
        ),
        firmware_delay_seconds=delay,
        free_space_reserve_gib=args.free_space_reserve,
        keep_passed_disk=False,
        keep_failed_disk=False,
        **values,
    )


def _materialize_case_results(
    selected,
    actual_results,
    dashboard,
    artifacts_root: Path,
) -> list[dict[str, object]]:
    """Include pending cases when infrastructure interrupts a full run."""

    actual = {item.id: item for item in actual_results}
    records = []
    for scenario in selected:
        view = dashboard.case_result(scenario.id)
        result = actual.get(scenario.id)
        records.append(
            {
                "id": scenario.id,
                "status": view["status"],
                "seconds": view["seconds"],
                "artifacts": str(
                    result.artifacts
                    if result is not None
                    else artifacts_root / scenario.id
                ),
                "error": result.error if result is not None else view["error"],
                "detail": view["detail"],
                "checks": view["checks"],
            }
        )
    return records


def _materialize_suite_results(
    selected_suites,
    actual_results,
    dashboard,
    architecture,
    artifacts_root: Path,
) -> list[dict[str, object]]:
    """Include every selected suite, including interrupted pending suites."""

    actual = {(item.source_case, item.id): item for item in actual_results}
    views = {
        (case_id, value["id"]): value
        for case_id in dashboard.cases
        for value in dashboard.suite_results(case_id)
    }
    records = []
    for suite in selected_suites:
        source = suite.source_for(architecture)
        if source is None:
            raise ConfigurationError(
                f"{suite.id}: no source for {architecture.value} while reporting"
            )
        view = views[(source, suite.id)]
        result = actual.get((source, suite.id))
        records.append(
            {
                "id": suite.id,
                "source_case": source,
                "status": view["status"],
                "seconds": view["seconds"],
                "artifacts": str(
                    result.artifacts
                    if result is not None
                    else artifacts_root
                    / source
                    / "feature-suites"
                    / suite.id
                ),
                "error": result.error if result is not None else view.get("error", ""),
                "detail": view["detail"],
                "checks": view["checks"],
            }
        )
    return records


def _preflight(architecture, selected, overrides, suites=()) -> None:
    if shutil.which("ssh") is None:
        raise ConfigurationError("Required executable is missing: ssh")
    try:
        import PIL  # noqa: F401
    except ImportError as error:
        raise ConfigurationError(
            "Required Python module is missing: Pillow (install python3-pil)"
        ) from error
    if any(scenario.desktop_contracts for scenario in selected) or suites:
        SpiceDisplayController.validate_dependencies()
    if any(scenario.desktop_contracts for scenario in selected):
        if shutil.which("mksquashfs") is None:
            raise ConfigurationError("Required executable is missing: mksquashfs")
    if any(suite.id == "file-integration" for suite in suites):
        for executable in ("ffmpeg", "dpkg-deb"):
            if shutil.which(executable) is None:
                raise ConfigurationError(
                    f"Required executable is missing: {executable}"
                )
    binary, acceleration = resolve_qemu(architecture)
    print(f"QEMU: {binary} ({acceleration})")
    seen = set()
    for scenario in selected:
        if scenario.firmware in seen:
            continue
        seen.add(scenario.firmware)
        selection = resolve_firmware(architecture, scenario.firmware, overrides)
        if selection is None:
            print("Firmware: SeaBIOS (QEMU default)")
        else:
            print(
                f"Firmware {scenario.firmware.value}: {selection.code}; "
                f"VARS template: {selection.variables_template}"
            )


def _failed_suite_result(
    identifier: str,
    source_case: str,
    artifacts_root: Path,
    error: str,
) -> FeatureSuiteResult:
    artifacts = artifacts_root / source_case / "feature-suites" / identifier
    artifacts.mkdir(parents=True, exist_ok=True)
    (artifacts / "failure.txt").write_text(error + "\n", encoding="utf-8")
    return FeatureSuiteResult(
        identifier,
        source_case,
        "failed",
        0.0,
        artifacts,
        error,
    )


@contextlib.contextmanager
def _termination_as_interrupt():
    """Make SIGTERM follow the same cleanup path as Ctrl+C."""

    previous = signal.getsignal(signal.SIGTERM)

    def interrupt(_signum, _frame):
        raise KeyboardInterrupt

    signal.signal(signal.SIGTERM, interrupt)
    try:
        yield
    finally:
        signal.signal(signal.SIGTERM, previous)
