"""Command-line interface for AnduinOS ISO acceptance tests."""

from __future__ import annotations

import argparse
import json
import shutil
import sys
import time
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path

from .errors import AcceptanceError, ConfigurationError
from .dashboard import AcceptanceDashboard
from .firmware import FirmwareOverrides, resolve_firmware
from .iso import inspect_iso
from .model import Architecture, TestMatrix
from .qemu import resolve_qemu
from .runner import RunnerOptions, ScenarioRunner


def main(argv: list[str] | None = None) -> int:
    parser = _parser()
    args = parser.parse_args(argv)
    try:
        matrix = TestMatrix.load(args.matrix)
        architecture = Architecture(args.arch) if args.arch else None
        if args.list:
            _list_cases(matrix, architecture)
            return 0
        if architecture is None or args.iso is None:
            parser.error("--iso and --arch are required unless --list is used")
        selected = matrix.select(architecture, tuple(args.cases))
        if args.smoke and not args.cases:
            raise ConfigurationError("--smoke requires one or more explicit --case values")
        inspection = inspect_iso(args.iso, architecture)
        overrides = FirmwareOverrides(
            uefi_code=args.uefi_code,
            uefi_vars_no_secure_boot=args.uefi_vars,
            uefi_vars_secure_boot=args.secure_boot_vars,
        )
        _preflight(architecture, selected, overrides)
        options = _options(args, matrix)
        if args.dry_run:
            _print_dry_run(inspection, architecture, selected, options)
            return 0
        options.artifacts_root.mkdir(parents=True, exist_ok=False)
        dashboard = AcceptanceDashboard(
            tuple(item.id for item in selected),
            iso=inspection.path,
            architecture=architecture.value,
            artifacts=options.artifacts_root,
            live=False if args.no_tui else None,
        )
        runner = ScenarioRunner(
            inspection,
            architecture,
            matrix.defaults,
            options,
            status_callback=dashboard.phase,
        )
        results = []
        dashboard.start()
        try:
            for scenario in selected:
                dashboard.begin(scenario.id)
                result = runner.run(scenario)
                results.append(result)
                dashboard.complete(
                    result.id,
                    result.status,
                    result.seconds,
                    result.error,
                )
                if result.status != "passed" and args.fail_fast:
                    break
        finally:
            dashboard.close()
        summary = {
            "iso": str(inspection.path),
            "iso_sha256": inspection.sha256,
            "architecture": architecture.value,
            "results": [
                {
                    "id": item.id,
                    "status": item.status,
                    "seconds": item.seconds,
                    "artifacts": str(item.artifacts),
                    "error": item.error,
                }
                for item in results
            ],
        }
        (options.artifacts_root / "summary.json").write_text(
            json.dumps(summary, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        passed = sum(item.status == "passed" for item in results)
        return 0 if passed == len(results) == len(selected) else 1
    except AcceptanceError as error:
        print(f"error: {error}", file=sys.stderr)
        return 2


def _parser() -> argparse.ArgumentParser:
    root = Path(__file__).parents[1]
    parser = argparse.ArgumentParser(
        description="Boot and install an AnduinOS ISO in disposable QEMU guests",
    )
    parser.add_argument("--iso", type=Path, help="ISO image under test")
    parser.add_argument("--arch", choices=tuple(item.value for item in Architecture))
    parser.add_argument("--case", dest="cases", action="append", default=[])
    parser.add_argument("--matrix", type=Path, default=root / "matrix.json")
    parser.add_argument("--artifacts", type=Path)
    parser.add_argument("--list", action="store_true", help="list matrix cases")
    parser.add_argument("--dry-run", action="store_true", help="validate without QEMU")
    parser.add_argument(
        "--smoke",
        action="store_true",
        help="boot selected Live environments but do not install",
    )
    parser.add_argument("--fail-fast", action="store_true")
    parser.add_argument(
        "--no-tui",
        action="store_true",
        help="disable the live terminal dashboard",
    )
    parser.add_argument("--memory", type=int)
    parser.add_argument("--cpus", type=int)
    parser.add_argument("--disk-size", type=int)
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
    return RunnerOptions(
        artifacts_root=artifacts,
        firmware_overrides=FirmwareOverrides(
            uefi_code=args.uefi_code,
            uefi_vars_no_secure_boot=args.uefi_vars,
            uefi_vars_secure_boot=args.secure_boot_vars,
        ),
        firmware_delay_seconds=delay,
        smoke_only=args.smoke,
        **values,
    )


def _preflight(architecture, selected, overrides) -> None:
    if shutil.which("ssh") is None:
        raise ConfigurationError("Required executable is missing: ssh")
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


def _list_cases(matrix: TestMatrix, architecture: Architecture | None) -> None:
    for scenario in matrix.scenarios:
        if architecture is not None and not scenario.supports(architecture):
            continue
        arches = ",".join(item.value for item in scenario.architectures)
        print(
            f"{scenario.id:43} {arches:11} {scenario.firmware.value:10} "
            f"{scenario.network.value:7} {scenario.filesystem.value:5} "
            f"ssh={scenario.ssh.value}"
        )


def _print_dry_run(inspection, architecture, selected, options) -> None:
    print(f"ISO: {inspection.path}")
    print(f"SHA-256: {inspection.sha256}")
    print(f"Architecture: {architecture.value}")
    print(f"Artifacts: {options.artifacts_root}")
    print(
        f"Resources: {options.memory_mib} MiB RAM, {options.cpus} CPUs, "
        f"{options.disk_gib} GiB disposable disk"
    )
    for scenario in selected:
        print(
            f"PLAN {scenario.id}: {scenario.firmware.value}, "
            f"{scenario.network.value}, {scenario.filesystem.value}, "
            f"ssh={scenario.ssh.value}, mok={scenario.mok_enrollment}"
        )
