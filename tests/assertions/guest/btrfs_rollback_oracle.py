#!/usr/bin/python3
"""Verify the protected recovery-engine state after a real rollback.

The user-facing snapshots CLI deliberately returns a redacted view of system
deployments.  This oracle runs only through the disposable acceptance helper,
as root, and validates the durable records consumed by the recovery engine.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import stat
import subprocess
import sys
import uuid
from pathlib import Path
from typing import Any


MAX_RECORD_BYTES = 1024 * 1024
SHA256 = re.compile(r"^[0-9a-f]{64}$")


class OracleFailure(RuntimeError):
    """The protected recovery state contradicts a successful rollback."""


def require(condition: bool, message: str) -> None:
    if not condition:
        raise OracleFailure(message)


def canonical_uuid(value: Any, label: str) -> str:
    require(isinstance(value, str), f"{label} is not a string")
    try:
        parsed = str(uuid.UUID(value))
    except (ValueError, AttributeError) as error:
        raise OracleFailure(f"{label} is not a UUID") from error
    require(parsed == value, f"{label} is not a canonical lowercase UUID")
    return value


def real_directory(path: Path, label: str) -> None:
    try:
        metadata = path.lstat()
    except OSError as error:
        raise OracleFailure(f"{label} is unavailable: {error}") from error
    require(stat.S_ISDIR(metadata.st_mode), f"{label} is not a real directory")


def read_record(path: Path, label: str) -> dict[str, Any]:
    try:
        metadata = path.lstat()
    except OSError as error:
        raise OracleFailure(f"{label} is unavailable: {error}") from error
    require(stat.S_ISREG(metadata.st_mode), f"{label} is not a regular file")
    require(metadata.st_size <= MAX_RECORD_BYTES, f"{label} is too large")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise OracleFailure(f"{label} is not valid JSON: {error}") from error
    require(isinstance(value, dict), f"{label} is not a JSON object")
    return value


def btrfs_field(btrfs: Path, subvolume: Path, field: str) -> str:
    try:
        result = subprocess.run(
            (str(btrfs), "subvolume", "show", "--raw", str(subvolume)),
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            timeout=30,
            env={"LC_ALL": "C", "PATH": "/usr/sbin:/usr/bin:/sbin:/bin"},
        )
    except (OSError, subprocess.SubprocessError) as error:
        raise OracleFailure(f"could not inspect Btrfs subvolume {subvolume}: {error}") from error
    require(
        result.returncode == 0,
        f"Btrfs rejected {subvolume}: {result.stdout.strip()}",
    )
    prefix = f"{field}:"
    value = next(
        (line.strip()[len(prefix) :].strip() for line in result.stdout.splitlines()
         if line.strip().startswith(prefix)),
        "",
    )
    return canonical_uuid(value, f"{subvolume} {field}")


def validate_deployment(
    store: Path,
    btrfs: Path,
    identifier: str,
) -> dict[str, Any]:
    record_path = store / "metadata" / f"{identifier}.json"
    record = read_record(record_path, f"deployment metadata {identifier}")
    require(record.get("schema_version") == 1, f"deployment {identifier} schema is unsupported")
    require(record.get("id") == identifier, f"deployment {identifier} has a mismatched ID")
    require(record.get("state") == "ready", f"deployment {identifier} is not ready")
    require(record.get("failure") is None, f"deployment {identifier} records a failure")
    for field in (
        "snapshot_uuid",
        "kernel_release",
        "initramfs_sha256",
        "boot_artifact_sha256",
        "dpkg_status_sha256",
    ):
        require(isinstance(record.get(field), str) and record[field],
                f"deployment {identifier} lacks {field}")
    snapshot_uuid = canonical_uuid(record["snapshot_uuid"], f"deployment {identifier} snapshot UUID")
    for field in ("initramfs_sha256", "boot_artifact_sha256", "dpkg_status_sha256"):
        require(bool(SHA256.fullmatch(record[field])),
                f"deployment {identifier} has an invalid {field}")

    root = store / "deployments" / identifier / "root"
    real_directory(root, f"deployment root {identifier}")
    observed_uuid = btrfs_field(btrfs, root, "UUID")
    require(observed_uuid == snapshot_uuid,
            f"deployment {identifier} snapshot UUID does not match its Btrfs root")
    return record


def validate(
    store: Path,
    current_root: Path,
    btrfs: Path,
    expected_target: str,
) -> None:
    expected_target = canonical_uuid(expected_target, "expected rollback target")
    real_directory(store, "recovery store")
    real_directory(store / "metadata", "deployment metadata directory")
    real_directory(store / "deployments", "deployment root directory")
    real_directory(store / "rollback-history", "rollback history directory")
    real_directory(store / "transactions", "rollback transaction directory")

    pending = store / "transactions" / "pending-rollback.json"
    require(not os.path.lexists(pending), "a pending rollback transaction remains")
    print("recovery-pending=absent")

    histories: list[dict[str, Any]] = []
    for path in sorted((store / "rollback-history").iterdir()):
        if path.suffix != ".json":
            continue
        transaction = read_record(path, f"rollback history {path.name}")
        if transaction.get("target_deployment_id") == expected_target:
            histories.append(transaction)
    require(len(histories) == 1,
            f"expected one rollback history for {expected_target}, found {len(histories)}")
    transaction = histories[0]
    require(transaction.get("schema_version") == 3, "rollback history schema is unsupported")
    require(transaction.get("phase") == "confirmed", "rollback history is not confirmed")
    require(transaction.get("failure") is None, "rollback history records a failure")
    require(transaction.get("recovery_protocol_version") == 2,
            "rollback recovery protocol is unsupported")
    target = canonical_uuid(transaction.get("target_deployment_id"), "history target deployment")
    fallback = canonical_uuid(
        transaction.get("fallback_deployment_id"), "history fallback deployment"
    )
    require(target == expected_target, "rollback history selected a different target")
    require(fallback != target, "rollback target and fallback are identical")
    canonical_uuid(transaction.get("root_filesystem_uuid"), "history root filesystem UUID")
    require(isinstance(transaction.get("kernel_release"), str)
            and bool(transaction["kernel_release"]), "rollback history lacks a kernel release")
    for field in (
        "recovery_kernel_sha256",
        "recovery_initramfs_sha256",
        "recovery_confirm_sha256",
    ):
        value = transaction.get(field)
        require(isinstance(value, str) and bool(SHA256.fullmatch(value)),
                f"rollback history has an invalid {field}")
    print("rollback-history=confirmed")

    records: dict[str, dict[str, Any]] = {}
    metadata_paths = sorted((store / "metadata").glob("*.json"))
    require(len(metadata_paths) >= 2, "fewer than two deployment records remain")
    for path in metadata_paths:
        identifier = canonical_uuid(path.stem, f"deployment filename {path.name}")
        records[identifier] = validate_deployment(store, btrfs, identifier)
    require(set((target, fallback)).issubset(records),
            "rollback target or fallback deployment metadata is missing")
    require(records[target].get("kind") == "manual",
            "the selected rollback target is not the manual acceptance snapshot")
    require(records[fallback].get("kind") == "pre-rollback",
            "the rollback safety deployment is not a pre-rollback snapshot")
    print("deployments-ready=target-and-fallback")
    print("deployment-roots=verified")

    parent_uuid = btrfs_field(btrfs, current_root, "Parent UUID")
    require(parent_uuid == records[target]["snapshot_uuid"],
            "the running root is not a writable child of the selected target")
    print("active-root=selected-target")
    print(f"rollback-target={target}")
    print(f"rollback-fallback={fallback}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("expected_target")
    parser.add_argument(
        "--store-root",
        type=Path,
        default=Path("/.snapshots/anduinos-btrfs-snapshots-manager"),
    )
    parser.add_argument("--current-root", type=Path, default=Path("/"))
    parser.add_argument("--btrfs", type=Path, default=Path("/usr/bin/btrfs"))
    arguments = parser.parse_args()
    try:
        validate(
            arguments.store_root,
            arguments.current_root,
            arguments.btrfs,
            arguments.expected_target,
        )
    except OracleFailure as error:
        print(f"rollback-state oracle failed: {error}", file=sys.stderr)
        return 1
    print("snapshot-state=ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
