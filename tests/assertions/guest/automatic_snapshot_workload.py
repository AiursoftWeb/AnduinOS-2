#!/usr/bin/python3
"""Exercise automatic timer outcomes inside a disposable installed guest."""

import copy
import json
import math
import os
from pathlib import Path
import subprocess
import sys
import time


CLI = "anduinos-btrfs-snapshots-manager-cli"
SERVICE = "anduinos-btrfs-snapshots-manager-scheduler.service"
TIMER = "anduinos-btrfs-snapshots-manager-scheduler.timer"
HELPER = "anduinos-btrfs-snapshots-manager-helper.service"
CONFIG = Path("/etc/anduinos-btrfs-snapshots-manager/automation.toml")


def run(*args, check=True):
    return subprocess.run(args, text=True, capture_output=True, check=check, timeout=120)


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def call(method, *args):
    result = run(
        "busctl", "--system", "--json=short", "call",
        "org.anduinos.BtrfsSnapshotsManager", "/org/anduinos/BtrfsSnapshotsManager",
        "org.anduinos.BtrfsSnapshotsManager.Helper", method, *args,
    )
    return json.loads(result.stdout)["data"]


def save_policy(policy):
    success, message = call("SaveAutomationConfig", "s", json.dumps(policy))
    require(success, f"Could not save automation policy: {message}")


def snapshot_ids():
    return {
        scope: sorted(row["id"] for row in json.loads(run(CLI, command, "--json").stdout))
        for scope, command in (("system", "list"), ("home", "personal-list"))
    }


def activate():
    started = time.monotonic()
    result = run("systemctl", "start", SERVICE, check=False)
    state = run("systemctl", "show", SERVICE, "-p", "Result", "-p", "ExecMainStatus")
    return {
        "started": started, "exit_code": result.returncode,
        "stderr": result.stderr, "state": state.stdout,
    }


def exercise_pair(policy, label, evidence, *, paused):
    """Use the real oneshot twice; never mask it or replace its executable."""
    save_policy(policy)
    run("systemctl", "restart", HELPER)
    before = snapshot_ids()
    first = activate()
    after_first = snapshot_ids()
    second = activate()
    after_second = snapshot_ids()
    record = {
        "first": first, "second": second, "before": before,
        "after_first": after_first, "after_second": after_second,
    }
    (evidence / f"{label}-pair.json").write_text(json.dumps(record, indent=2) + "\n")
    require(first["exit_code"] == second["exit_code"] == 0,
            f"{label}: automatic activation failed: {json.dumps(record)}")
    require(all("Result=success" in item["state"] and "ExecMainStatus=0" in item["state"]
                for item in (first, second)), f"{label}: oneshot did not succeed")
    for scope in before:
        require(set(before[scope]) <= set(after_first[scope]),
                f"{label}: existing {scope} history was removed")
        require(len(set(after_first[scope]) - set(before[scope])) <= 1,
                f"{label}: one activation created duplicate {scope} snapshots")
    require(after_second == after_first, f"{label}: repeated activation added snapshots")
    if paused:
        require(after_first == before, "Low-space policy still created a snapshot")
        require(second["started"] - first["started"] < 5,
                "Fixture did not place the low-space activations inside five seconds")
    return record


def main(evidence):
    require(os.geteuid() == 0, "Run only in the disposable guest's root control session")
    virtual_machine = run("systemd-detect-virt", "--vm", check=False).stdout.strip()
    require(virtual_machine in ("qemu", "kvm"), "Refusing to alter automation outside a QEMU guest")
    evidence.mkdir(parents=True, exist_ok=True)
    started = int(time.time())
    original = json.loads(call("GetAutomationConfig")[0])
    timer_active = run("systemctl", "is-active", "--quiet", TIMER, check=False).returncode == 0
    boot_id = Path("/proc/sys/kernel/random/boot_id").read_text().strip()
    records = {"schema": 1, "boot_id": boot_id, "phases": {}}
    try:
        # Stop only the timer while driving its real service deterministically.
        # Other feature overlays and the immutable installation base are untouched.
        run("systemctl", "stop", TIMER, SERVICE)
        policy = copy.deepcopy(original)
        for scope in ("system", "home"):
            policy[scope]["is_auto_snapshot_enabled"] = True
            policy[scope]["is_auto_cleanup_enabled"] = True
        policy["notifications"] = {key: False for key in policy["notifications"]}

        available = [os.statvfs(path).f_bavail * os.statvfs(path).f_frsize
                     for path in ("/", "/home")]
        policy["minimum_free_space_gib"] = math.ceil(max(available) / 1024**3) + 1
        records["phases"]["low_space"] = exercise_pair(policy, "low-space", evidence, paused=True)

        policy["minimum_free_space_gib"] = 0
        records["phases"]["normal_space"] = exercise_pair(policy, "normal-space", evidence, paused=False)

        # An actual caller-visible error must remain an error. The timer's own
        # configuration load fails before any scheduled D-Bus request is made.
        CONFIG.write_text("deliberately-invalid-automation = [\n")
        invalid = activate()
        records["phases"]["invalid_configuration"] = invalid
        require(invalid["exit_code"] != 0 and "ExecMainStatus=1" in invalid["state"],
                "A broken automation policy was reported as successful")
        save_policy(policy)

        # Interactive snapshot creation retains its separate five-second guard.
        run("systemctl", "restart", HELPER)
        manual = run(CLI, "create", "--json", "Acceptance manual throttle")
        repeated = run(CLI, "create", "--json", "Acceptance manual throttle duplicate", check=False)
        records["phases"]["manual_throttle"] = {
            "created": json.loads(manual.stdout), "second_exit": repeated.returncode,
            "second_stderr": repeated.stderr,
        }
        require(repeated.returncode != 0 and "Please wait" in repeated.stderr,
                "Interactive snapshot throttling was lost")
        recovered = activate()
        records["phases"]["valid_configuration_restored"] = recovered
        require(recovered["exit_code"] == 0 and "Result=success" in recovered["state"],
                "The scheduler did not recover after valid policy was restored")
        require(Path("/proc/sys/kernel/random/boot_id").read_text().strip() == boot_id,
                "Automatic snapshot checks unexpectedly rebooted the system")
        records["status"] = "passed"
    finally:
        # Keep the exact failure evidence even when a normal timer run fails.
        journal = run("journalctl", "-b", "--no-pager", "-u", SERVICE, "-u", HELPER,
                      "--since", f"@{started}", check=False)
        (evidence / "automatic-snapshots-journal.txt").write_text(journal.stdout + journal.stderr)
        (evidence / "automatic-snapshots.json").write_text(json.dumps(records, indent=2) + "\n")
        save_policy(original)
        if timer_active:
            run("systemctl", "start", TIMER)
    print(json.dumps(records))


if __name__ == "__main__":
    main(Path(sys.argv[1]))
