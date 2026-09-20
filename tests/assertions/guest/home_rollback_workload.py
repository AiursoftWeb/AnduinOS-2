#!/usr/bin/python3
"""End-user Home rollback outcome, executed only inside a disposable guest."""

import hashlib
import json
import os
from pathlib import Path
import pwd
import subprocess
import sys

STORE = Path("/.snapshots/anduinos-btrfs-snapshots-manager")
STATE = Path("/usr/local/lib/anduinos-acceptance/home-rollback.json")
MARKER = Path("/etc/anduinos-acceptance-home-only")
HOME = Path("/home")
BOOT_ID = Path("/proc/sys/kernel/random/boot_id")


def run(*args):
    return subprocess.check_output(args, text=True).strip()


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def root_uuid():
    return next(line.split(":", 1)[1].strip()
                for line in run("btrfs", "subvolume", "show", "/").splitlines()
                if line.strip().startswith("UUID:"))


def prepare(user):
    require(run("findmnt", "-n", "-o", "FSROOT", "/") == "/@root", "Unsupported root")
    require(run("findmnt", "-n", "-o", "FSROOT", "/home") == "/@home", "Unsupported Home")
    status = json.loads(run("anduinos-btrfs-snapshots-manager-cli", "status", "--json"))
    require(status.get("home_rollback_available") is True, "ISO lacks Home-only recovery")
    account = pwd.getpwnam(user)
    folder = Path(account.pw_dir) / "anduinos-acceptance-home-only"
    require(not folder.exists() and not MARKER.exists() and not STATE.exists(),
            "Refusing to reuse Home rollback fixture")
    folder.mkdir()
    os.chown(folder, account.pw_uid, account.pw_gid)
    for name in ("edited.txt", "deleted.txt"):
        path = folder / name
        path.write_text("baseline\n")
        os.chown(path, account.pw_uid, account.pw_gid)
    target = json.loads(run("anduinos-btrfs-snapshots-manager-cli", "personal-create", "--json",
                           "Acceptance Home baseline", "Before user data changes"))
    (folder / "edited.txt").write_text("changed\n")
    (folder / "deleted.txt").unlink()
    (folder / "new.txt").write_text("new user data\n")
    os.chown(folder / "new.txt", account.pw_uid, account.pw_gid)
    MARKER.write_text("system change must survive\n")
    state = {"user": user, "folder": str(folder), "target": target["id"],
             "root_uuid": root_uuid(), "dpkg": digest("/var/lib/dpkg/status"),
             "boot_id": BOOT_ID.read_text().strip(),
             "uid": account.pw_uid, "gid": account.pw_gid}
    STATE.write_text(json.dumps(state))
    print(json.dumps(state))


def verify():
    state = json.loads(STATE.read_text())
    require(BOOT_ID.read_text().strip() != state["boot_id"],
            "Home recovery did not reboot")
    require(root_uuid() == state["root_uuid"], "Home rollback replaced the system root")
    require(MARKER.read_text() == "system change must survive\n", "System change was lost")
    require(digest("/var/lib/dpkg/status") == state["dpkg"], "Package database changed")
    folder = Path(state["folder"])
    for name in ("edited.txt", "deleted.txt"):
        path = folder / name
        require(path.read_text() == "baseline\n", "Home baseline was not restored")
        require((path.stat().st_uid, path.stat().st_gid) == (state["uid"], state["gid"]),
                "Restored Home ownership changed")
    require(not os.path.lexists(folder / "new.txt"), "New Home file survived rollback")
    require(not os.path.lexists(STORE / "transactions/pending-rollback.json"),
            "Home recovery is still pending")
    records = [json.loads(path.read_text()) for path in (STORE / "rollback-history").glob("*.json")]
    matches = [record for record in records if record.get("factory_home_snapshot_id") == state["target"]]
    require(len(matches) == 1, "Expected one completed Home recovery")
    record = matches[0]
    require(record.get("schema_version") == 5 and record.get("home_only") is True
            and record.get("reset_home") is True and record.get("phase") == "confirmed"
            and record.get("failure") is None, "Home recovery did not confirm successfully")
    require(record.get("fallback_home_snapshot_id"), "Home safety snapshot is missing")
    for identifier, filename, content in (
        (state["target"], "deleted.txt", "baseline\n"),
        (record["fallback_home_snapshot_id"], "new.txt", "new user data\n"),
    ):
        relative = folder.relative_to(HOME) / filename
        saved = STORE / "personal/snapshots" / identifier / "home" / relative
        require(saved.read_text() == content, "Home snapshot history lost data")
        entries = json.loads(run("runuser", "-u", state["user"], "--",
                                 "env", f"XDG_RUNTIME_DIR=/run/user/{state['uid']}",
                                 f"DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/{state['uid']}/bus",
                                 "systemd-run", "--user", "--wait", "--pipe", "--collect", "--quiet", "--",
                                 "anduinos-btrfs-snapshots-manager-cli", "personal-files",
                                 identifier, folder.name, "--json"))
        require(any(item.get("name") == filename for item in entries),
                "Home history is not browsable by its owner")
    print("home-only-recovery=verified")


if __name__ == "__main__":
    if len(sys.argv) == 3 and sys.argv[1] == "prepare":
        prepare(sys.argv[2])
    elif sys.argv[1:] == ["verify"]:
        verify()
    else:
        raise SystemExit("Expected prepare USER or verify")
