"""Disposable-VM workload: remove curl, then observe real factory recovery."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess


STORE = Path("/.snapshots/anduinos-btrfs-snapshots-manager")


def run(*command):
    return subprocess.check_output(command, text=True).strip()


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def prepare(home, factory_root):
    baseline = STORE / "deployments" / factory_root / "root"
    query = ("dpkg-query", f"--admindir={baseline}/var/lib/dpkg", "-W")
    require(run(*query, "-f=${Status}", "curl") == "install ok installed",
            "Factory baseline must contain installed curl")
    version = run(*query, "-f=${Version}", "curl")
    checksum = digest(baseline / "usr/bin/curl")
    require(run("dpkg-query", "-W", "-f=${Status}", "curl") == "install ok installed",
            "curl must be installed before each mutation")
    run("/usr/bin/curl", "--version")
    files = {
        str(home / "documents" / "keep-me.txt"): "Acceptance document: original contents\n",
        str(home / ".config" / "settings.ini"): "[acceptance]\nmodified=true\n",
    }
    owner = home.parent.stat()
    for name, content in files.items():
        path = Path(name)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        for entry in (home, path.parent, path):
            os.chown(entry, owner.st_uid, owner.st_gid)
    # No autoremove, dependency overrides, or package download is allowed.
    run("dpkg", "--remove", "curl")
    require(not Path("/usr/bin/curl").exists() and shutil.which("curl") is None,
            "Removing curl did not make it unavailable")
    status = subprocess.run(("dpkg-query", "-W", "-f=${Status}", "curl"),
                            text=True, capture_output=True)
    require(status.stdout.strip() != "install ok installed", "curl is still installed")
    require(not run("dpkg", "--audit"), "Package database is damaged before recovery")
    run("apt-get", "check")
    return {"version": version, "sha256": checksum, "files": files,
            "boot_id": Path("/proc/sys/kernel/random/boot_id").read_text().strip()}


def verify(workloads, erase_home):
    latest = workloads[-1]
    require(run("dpkg-query", "-W", "-f=${Status}", "curl") == "install ok installed",
            "Recovery did not restore the curl package")
    require(run("dpkg-query", "-W", "-f=${Version}", "curl") == latest["version"],
            "Restored curl version differs from the factory baseline")
    require(digest(Path("/usr/bin/curl")) == latest["sha256"],
            "Restored curl binary differs from the factory baseline")
    run("/usr/bin/curl", "--version")
    require(Path("/proc/sys/kernel/random/boot_id").read_text().strip() != latest["boot_id"],
            "Recovery did not boot a new system")
    histories = [json.loads(path.read_text()) for path in (STORE / "rollback-history").glob("*.json")]
    resets = sorted((record for record in histories
                     if record["target_deployment_id"] == latest["factory_root_id"]),
                    key=lambda record: record["created_at"])
    require(len(resets) == len(workloads), "Expected one completed recovery per round")
    for index, record in enumerate(resets):
        require(record["phase"] == "confirmed" and record["failure"] is None,
                "Recovery history does not confirm a successful reset")
        require(record["reset_home"] is (index == 1),
                "Recovery history disagrees with the requested Home policy")
    for workload in workloads:
        for name, content in workload["files"].items():
            path = Path(name)
            if erase_home:
                require(not os.path.lexists(path), f"User file survived erasure: {path}")
            else:
                require(path.read_text(encoding="utf-8") == content,
                        f"Preserved user file content changed: {path}")
        identifier = workload["personal_snapshot_id"]
        snapshot = STORE / "personal/snapshots" / identifier
        metadata = STORE / "personal/metadata" / f"{identifier}.json"
        if erase_home:
            require(not os.path.lexists(snapshot) and not os.path.lexists(metadata),
                    "Erased Home data remains accessible through snapshot history")
        else:
            for name, content in workload["files"].items():
                saved = snapshot / "home" / Path(name).relative_to("/home")
                require(saved.read_text(encoding="utf-8") == content,
                        "Preserve mode lost Home snapshot contents")
    print("curl=restored-and-runnable")
    print("home-workload=" + ("erased-with-history" if erase_home else "content-preserved"))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="action", required=True)
    before = sub.add_parser("prepare")
    before.add_argument("--home", required=True, type=Path)
    before.add_argument("--factory-root", required=True)
    after = sub.add_parser("verify")
    after.add_argument("--workloads", required=True, type=json.loads)
    after.add_argument("--erase-home", action="store_true")
    args = parser.parse_args()
    if args.action == "prepare":
        print("factory-workload=" + json.dumps(prepare(args.home, args.factory_root)))
    else:
        verify(args.workloads, args.erase_home)


if __name__ == "__main__":
    main()
