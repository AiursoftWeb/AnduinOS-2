"""Disposable-VM workload: remove GNOME Clocks, then observe factory recovery."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import pwd
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
    require(run(*query, "-f=${Status}", "gnome-clocks") == "install ok installed",
            "Factory baseline must contain installed gnome-clocks")
    version = run(*query, "-f=${Version}", "gnome-clocks")
    checksum = digest(baseline / "usr/bin/gnome-clocks")
    require(run("dpkg-query", "-W", "-f=${Status}", "gnome-clocks") == "install ok installed",
            "gnome-clocks must be installed before each mutation")
    run("/usr/bin/gnome-clocks", "--version")
    require(run("dpkg-query", "-W", "-f=${Status}", "anduinos-btrfs-snapshots-manager")
            == "install ok installed", "Recovery manager must be installed before mutation")
    # Refuse dependency conflicts before mutation. dpkg removes only this
    # package; never let APT remove the recovery stack as a reverse dependant.
    run("dpkg", "--no-act", "--remove", "gnome-clocks")
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
    run("dpkg", "--remove", "gnome-clocks")
    require(not Path("/usr/bin/gnome-clocks").exists() and shutil.which("gnome-clocks") is None,
            "Removing gnome-clocks did not make it unavailable")
    status = subprocess.run(("dpkg-query", "-W", "-f=${Status}", "gnome-clocks"),
                            text=True, capture_output=True)
    require(status.stdout.strip() != "install ok installed", "gnome-clocks is still installed")
    require(run("dpkg-query", "-W", "-f=${Status}", "anduinos-btrfs-snapshots-manager")
            == "install ok installed", "Mutation removed the recovery manager")
    require(not run("dpkg", "--audit"), "Package database is damaged before recovery")
    run("apt-get", "check")
    return {"version": version, "sha256": checksum, "files": files,
            "boot_id": Path("/proc/sys/kernel/random/boot_id").read_text().strip()}


def verify(workloads, erase_home):
    latest = workloads[-1]
    require(run("dpkg-query", "-W", "-f=${Status}", "gnome-clocks") == "install ok installed",
            "Recovery did not restore the gnome-clocks package")
    require(run("dpkg-query", "-W", "-f=${Version}", "gnome-clocks") == latest["version"],
            "Restored gnome-clocks version differs from the factory baseline")
    require(digest(Path("/usr/bin/gnome-clocks")) == latest["sha256"],
            "Restored gnome-clocks binary differs from the factory baseline")
    run("/usr/bin/gnome-clocks", "--version")
    require(Path("/proc/sys/kernel/random/boot_id").read_text().strip() != latest["boot_id"],
            "Recovery did not boot a new system")
    histories = [json.loads(path.read_text()) for path in (STORE / "rollback-history").glob("*.json")]
    resets = sorted((record for record in histories
                     if record["target_deployment_id"] == latest["factory_root_id"]),
                    key=lambda record: record["created_at"])
    require(len(resets) == len(workloads), "Expected one completed recovery per round")
    for index, record in enumerate(resets):
        require(record.get("schema_version") in (4, 5), "Unsupported recovery history schema")
        require(record["phase"] == "confirmed" and record["failure"] is None,
                "Recovery history does not confirm a successful reset")
        require(record["reset_home"] is (index == 1),
                "Recovery history disagrees with the requested Home policy")
        if record["schema_version"] == 5:
            require(record.get("home_only") is False, "Factory recovery must include the system")
            if record["reset_home"]:
                require(record.get("fallback_home_snapshot_id"), "Home rollback has no safety snapshot")
    # Keep the currently running older ISO qualification valid. New-format
    # transactions MUST preserve history, not merely accept either outcome.
    preserve_history = resets[-1]["schema_version"] == 5
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
        if erase_home and not preserve_history:
            require(not os.path.lexists(snapshot) and not os.path.lexists(metadata),
                    "Erased Home data remains accessible through snapshot history")
        else:
            for name, content in workload["files"].items():
                saved = snapshot / "home" / Path(name).relative_to("/home")
                require(saved.read_text(encoding="utf-8") == content,
                        "Home snapshot history lost its saved contents")
                if preserve_history:
                    require(metadata.is_file(), "Home snapshot metadata is missing")
                    relative = Path(name).relative_to("/home")
                    account = relative.parts[0]
                    uid = pwd.getpwnam(account).pw_uid
                    folder = Path(*relative.parts[1:]).parent.as_posix()
                    entries = json.loads(run("runuser", "-u", account, "--",
                                             "env", f"XDG_RUNTIME_DIR=/run/user/{uid}",
                                             f"DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/{uid}/bus",
                                             "systemd-run", "--user", "--wait", "--pipe", "--collect", "--quiet", "--",
                                             "/usr/bin/anduinos-btrfs-snapshots-manager-cli",
                                             "personal-files", identifier,
                                             "" if folder == "." else folder, "--json"))
                    require(any(entry.get("name") == Path(name).name for entry in entries),
                            "Saved Home files are not browsable through the application API")
    print("gnome-clocks=restored-and-runnable")
    print("home-workload=" + ("rolled-back-history-preserved" if erase_home and preserve_history
                              else "erased-with-history" if erase_home else "content-preserved"))


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
