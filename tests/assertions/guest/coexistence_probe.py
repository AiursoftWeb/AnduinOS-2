"""Read-only inventory and byte fingerprints of the disposable QEMU disk."""

import hashlib
import json
import os
import re
import subprocess
import sys
from pathlib import Path


def output(*args):
    return subprocess.check_output(args, text=True).strip()


def digest(path, offset=0, length=None):
    result = hashlib.sha256()
    with open(path, "rb", buffering=0) as stream:
        stream.seek(offset)
        remaining = length
        while remaining is None or remaining > 0:
            chunk = stream.read(min(8 * 1024**2, remaining) if remaining is not None else 8 * 1024**2)
            if not chunk:
                if remaining:
                    raise RuntimeError("Short block-device read")
                break
            result.update(chunk)
            if remaining is not None:
                remaining -= len(chunk)
    return result.hexdigest()


def snapshot(hash_paths):
    # This oracle must never select a host device or an arbitrary guest disk.
    disk = "/dev/vda"
    tree = json.loads(output("lsblk", "-Jbp", "-o", "NAME,TYPE,SERIAL,FSTYPE,UUID,PARTUUID,PARTTYPE,MOUNTPOINTS", disk))["blockdevices"]
    if len(tree) != 1 or tree[0]["serial"] != "ANDUINOS-TEST-TARGET":
        raise RuntimeError("Not the dedicated acceptance disk")
    children = tree[0].get("children", [])
    if any(item.get("mountpoints") and any(item["mountpoints"]) for item in children):
        raise RuntimeError("Target partitions must be unmounted and not swap-active")
    table_type, table_id = output("lsblk", "-dnro", "PTTYPE,PTUUID", disk).split()
    if table_type != "gpt" or not re.fullmatch(r"[0-9a-fA-F-]{36}", table_id):
        raise RuntimeError("Expected the dedicated GPT acceptance disk")
    sector_size = int(output("blockdev", "--getss", disk))
    if sector_size < 512 or sector_size % 512:
        raise RuntimeError("Unexpected disk sector size")
    partitions = []
    records = []
    for item in sorted(children, key=lambda child: child["name"]):
        path = item["name"]
        if not re.fullmatch(r"/dev/vda[1-9][0-9]*", path):
            raise RuntimeError("Unexpected partition path")
        if item["type"] != "part" or not item.get("partuuid") or not item.get("parttype"):
            raise RuntimeError("Incomplete partition identity")
        sysfs = Path("/sys/class/block") / path.removeprefix("/dev/")
        start = int((sysfs / "start").read_text().strip()) * 512
        size = int((sysfs / "size").read_text().strip()) * 512
        if start % sector_size or size % sector_size or size <= 0:
            raise RuntimeError("Invalid partition geometry")
        partition = {
            "node": path, "start": start // sector_size, "size": size // sector_size,
            "type": item["parttype"], "uuid": item["partuuid"],
        }
        partitions.append(partition)
        records.append({
            "path": path, "uuid": item["uuid"], "partuuid": item["partuuid"],
            "fstype": item["fstype"], "geometry": partition,
            "sha256": digest(path) if path in hash_paths else None,
        })
    if set(hash_paths) - {item["path"] for item in records}:
        raise RuntimeError("A requested original partition disappeared")
    if len({item["path"] for item in records}) != len(records):
        raise RuntimeError("Duplicate partition identity")
    table = {
        "label": table_type, "id": table_id, "device": disk,
        "unit": "sectors", "sectorsize": sector_size, "partitions": partitions,
    }
    size = int(output("blockdev", "--getsize64", disk))
    return {
        "partitions": records, "table": table,
        "gpt_head": digest(disk, length=1024**2),
        "gpt_tail": digest(disk, offset=size - 1024**2, length=1024**2),
        "nvram": output("efibootmgr", "-v"),
    }


if __name__ == "__main__":
    os.sync()
    print("COEXISTENCE_JSON=" + json.dumps(snapshot(sys.argv[1:]), sort_keys=True))
