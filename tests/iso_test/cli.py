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

from .errors import AcceptanceError, ConfigurationError
from .dashboard import AcceptanceDashboard
from .display import SpiceDisplayController
from .feature_model import FeatureSuiteRegistry, TestProfile
from .feature_runner import FeatureSuiteResult, FeatureSuiteRunner
from .firmware import FirmwareOverrides, resolve_firmware
from .iso import inspect_iso
from .model import Architecture, TestMatrix
from .qemu import resolve_qemu
from .reporting import write_junit_report
from .runner import RunnerOptions, ScenarioRunner, scenario_check_ids
from .storage import (
    DEFAULT_RAMDISK_THRESHOLD_GIB,
    assert_disk_storage_ready,
    cleanup_disk_storage,
    inspect_capacity,
    prepare_disk_storage,
    select_disk_storage,
)


def main(argv: list[str] | None = None) -> int:
    parser = _parser()
    args = parser.parse_args(argv)
    try:
        matrix = TestMatrix.load(args.matrix)
        registry = FeatureSuiteRegistry.load(args.feature_suites, matrix)
        architecture = Architecture(args.arch) if args.arch else None
        if args.list:
            _list_cases(matrix, registry, architecture)
            return 0
        if architecture is None or args.iso is None:
            parser.error("--iso and --arch are required unless --list is used")
        selected = matrix.select(architecture, tuple(args.cases))
        profile = TestProfile(args.profile)
        suites = registry.select(architecture, profile, tuple(args.suites))
        if args.cases and not args.suites:
            selected_ids = {scenario.id for scenario in selected}
            suites = tuple(
                suite
                for suite in suites
                if suite.source_for(architecture) in selected_ids
            )
        registry.validate_sources(
            suites,
            matrix,
            architecture,
            {scenario.id for scenario in selected},
        )
        if args.smoke and not args.cases:
            raise ConfigurationError("--smoke requires one or more explicit --case values")
        if args.smoke and suites:
            raise ConfigurationError("Feature suites cannot run with --smoke")
        _validate_disk_retention(args, selected)
        if suites and (args.keep_passed_disk or args.keep_failed_disk):
            raise ConfigurationError(
                "Feature-suite overlays are always disposable; disk retention "
                "cannot be combined with an executable feature profile"
            )
        inspection = inspect_iso(args.iso, architecture)
        overrides = FirmwareOverrides(
            uefi_code=args.uefi_code,
            uefi_vars_no_secure_boot=args.uefi_vars,
            uefi_vars_secure_boot=args.secure_boot_vars,
        )
        _preflight(architecture, selected, overrides, suites)
        options = _options(args, matrix)
        if args.dry_run:
            _print_dry_run(
                inspection,
                architecture,
                selected,
                suites,
                profile,
                options,
            )
            return 0
        assert_disk_storage_ready(
            options.disk_storage,
            disk_gib=options.disk_gib,
            filesystem_reserve_gib=options.free_space_reserve_gib,
            memory_mib=options.memory_mib,
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
                    item.id: scenario_check_ids(
                        item,
                        smoke_only=options.smoke_only,
                    )
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
                fail_fast=args.fail_fast,
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
                                    if (
                                        suite_result.status != "passed"
                                        and args.fail_fast
                                    ):
                                        break
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
                        if result.status != "passed" and args.fail_fast:
                            break
                        if (
                            suite_results
                            and suite_results[-1].status != "passed"
                            and args.fail_fast
                        ):
                            break
            finally:
                dashboard.close()
            summary = {
                "schema_version": 1,
                "iso": str(inspection.path),
                "iso_sha256": inspection.sha256,
                "architecture": architecture.value,
                "profile": profile.value,
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
    root = Path(__file__).parents[1]
    parser = argparse.ArgumentParser(
        description="Boot and install an AnduinOS ISO in disposable QEMU guests",
    )
    parser.add_argument("--iso", type=Path, help="ISO image under test")
    parser.add_argument("--arch", choices=tuple(item.value for item in Architecture))
    parser.add_argument("--case", dest="cases", action="append", default=[])
    parser.add_argument("--matrix", type=Path, default=root / "matrix.json")
    parser.add_argument(
        "--feature-suites",
        type=Path,
        default=root / "feature-suites.json",
    )
    parser.add_argument(
        "--profile",
        choices=tuple(item.value for item in TestProfile),
        default=TestProfile.INSTALL.value,
        help="installation-only or executable installed-system feature profile",
    )
    parser.add_argument("--suite", dest="suites", action="append", default=[])
    parser.add_argument("--artifacts", type=Path)
    parser.add_argument("--list", action="store_true", help="list matrix cases")
    parser.add_argument("--dry-run", action="store_true", help="validate without QEMU")
    parser.add_argument(
        "--smoke",
        action="store_true",
        help="boot selected Live environments but do not install",
    )
    parser.add_argument(
        "--fail-fast",
        action="store_true",
        help=(
            "stop after the first failed scenario, feature suite, or safe "
            "in-suite product assertion"
        ),
    )
    parser.add_argument(
        "--keep-passed-disk",
        "--keep-passed-disks",
        dest="keep_passed_disk",
        action="store_true",
        help="retain the qcow2 from one explicitly selected passed case",
    )
    parser.add_argument(
        "--keep-failed-disk",
        action="store_true",
        help="retain the qcow2 from one explicitly selected failed case",
    )
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


def _options(args, matrix: TestMatrix) -> RunnerOptions:
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
    retain_disk = args.keep_passed_disk or args.keep_failed_disk
    disk_storage = select_disk_storage(
        artifacts,
        memory_mib=values["memory_mib"],
        mode=args.disk_backend,
        ramdisk_threshold_gib=args.ramdisk_threshold,
        retain_disk=retain_disk,
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
        smoke_only=args.smoke,
        keep_passed_disk=args.keep_passed_disk,
        keep_failed_disk=args.keep_failed_disk,
        **values,
    )


def _validate_disk_retention(args, selected) -> None:
    if not (args.keep_passed_disk or args.keep_failed_disk):
        return
    if len(args.cases) != 1 or len(selected) != 1:
        raise ConfigurationError(
            "Disk retention is allowed only with exactly one explicit --case; "
            "a matrix must never accumulate retained virtual disks"
        )


def _materialize_case_results(
    selected,
    actual_results,
    dashboard,
    artifacts_root: Path,
) -> list[dict[str, object]]:
    """Include not-started cases instead of omitting fail-fast coverage gaps."""

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
    """Include every selected suite, including fail-fast pending suites."""

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
    if any(scenario.desktop_release_gate for scenario in selected) or suites:
        SpiceDisplayController.validate_dependencies()
    if any(scenario.desktop_release_gate for scenario in selected):
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


def _list_cases(
    matrix: TestMatrix,
    registry: FeatureSuiteRegistry,
    architecture: Architecture | None,
) -> None:
    for scenario in matrix.scenarios:
        if architecture is not None and not scenario.supports(architecture):
            continue
        arches = ",".join(item.value for item in scenario.architectures)
        print(
            f"{scenario.id:43} {arches:11} {scenario.firmware.value:10} "
            f"{scenario.network.value:7} {scenario.filesystem.value:5} "
            f"rime={str(scenario.rime).lower():5} "
            f"ssh={scenario.ssh.value} "
            f"passwordless-sudo={str(scenario.passwordless_sudo).lower():5} "
            f"autologin={str(scenario.automatic_login).lower():5} "
            f"desktop-gate={str(scenario.desktop_release_gate).lower()}"
        )
    print("\nExecutable feature suites:")
    for suite in registry.suites:
        if architecture is not None and not suite.supports(architecture):
            continue
        sources = ",".join(
            f"{arch.value}:{source}"
            for arch, source in suite.source_cases.items()
        )
        profiles = ",".join(profile.value for profile in suite.profiles)
        print(
            f"{suite.id:43} profiles={profiles} sources={sources}\n"
            f"  CHECKS ({len(suite.checks)}): " + ", ".join(suite.checks)
        )


def _print_dry_run(
    inspection,
    architecture,
    selected,
    suites,
    profile,
    options,
) -> None:
    print(f"ISO: {inspection.path}")
    print(f"SHA-256: {inspection.sha256}")
    print(f"Architecture: {architecture.value}")
    print(f"Profile: {profile.value}")
    print(f"Artifacts: {options.artifacts_root}")
    print(
        f"Resources: {options.memory_mib} MiB RAM, {options.cpus} CPUs, "
        f"{options.disk_gib} GiB disposable disk"
    )
    print(
        f"Target disks: {options.disk_storage.backend} at "
        f"{options.disk_storage.root}"
    )
    print(f"Storage decision: {options.disk_storage.reason}")
    if options.disk_storage.is_ramdisk:
        print(
            "RAM-disk safety: "
            f"MemAvailable={options.disk_storage.memory_available_bytes / 1024**3:.1f} "
            "GiB, "
            f"tmpfs-free={options.disk_storage.ramdisk_free_bytes / 1024**3:.1f} "
            "GiB, "
            f"qcow2-limit={options.disk_storage.qcow_limit_bytes / 1024**3:.1f} "
            "GiB (ready)"
        )
    else:
        capacity = inspect_capacity(
            options.disk_storage.root,
            options.disk_gib,
            options.free_space_reserve_gib,
        )
        status = (
            "ready"
            if capacity.free_bytes >= capacity.required_bytes
            else "insufficient"
        )
        print(
            f"Host storage: {capacity.free_gib:.1f} GiB free; "
            f"{capacity.required_gib:.1f} GiB required ({status})"
        )
    for scenario in selected:
        print(
            f"PLAN {scenario.id}: {scenario.firmware.value}, "
            f"{scenario.network.value}, {scenario.filesystem.value}, "
            f"rime={scenario.rime}, ssh={scenario.ssh.value}, "
            f"passwordless-sudo={scenario.passwordless_sudo}, "
            f"autologin={scenario.automatic_login}, "
            f"desktop-gate={scenario.desktop_release_gate}, "
            f"mok={scenario.mok_enrollment}"
        )
        checks = scenario_check_ids(scenario, smoke_only=options.smoke_only)
        print(f"  CHECKS ({len(checks)}): " + ", ".join(checks))
        for suite in suites:
            if suite.source_for(architecture) != scenario.id:
                continue
            print(
                f"  FEATURE SUITE {suite.id} (qcow2 overlay): "
                + ", ".join(suite.checks)
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
