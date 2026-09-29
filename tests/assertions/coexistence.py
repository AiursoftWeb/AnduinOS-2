"""Fail-closed evidence oracles for sequential installations on one disk."""

import json
import re

from framework.errors import TestFailure


def validate_rejection_events(output: str) -> None:
    events = []
    for line in output.splitlines():
        try:
            value = json.loads(line)
        except ValueError:
            continue
        if isinstance(value, dict):
            events.append(value)
    kinds = [item.get("event") for item in events]
    rejected = [item for item in events if item.get("event") == "coexistence-esp-rejected"]
    if (kinds.count("coexistence-esp-conflict-dialog") != 1
            or len(rejected) != 1
            or rejected[0].get("next_enabled") is not False
            or rejected[0].get("stage") != "advanced-storage"
            or "installation-complete" in kinds
            or any(item.get("page") in ("user", "summary", "progress") for item in events)):
        raise TestFailure("Shared ESP did not produce a fail-closed UI rejection")


def parse_snapshot(output: str) -> dict:
    records = [line.removeprefix("COEXISTENCE_JSON=") for line in output.splitlines()
               if line.startswith("COEXISTENCE_JSON=")]
    if len(records) != 1:
        raise TestFailure("Missing or ambiguous coexistence disk evidence")
    value = json.loads(records[0])
    partitions = value.get("partitions", [])
    for key in ("path", "uuid", "partuuid"):
        identities = [item.get(key) for item in partitions]
        if not identities or any(not item for item in identities) or len(set(identities)) != len(identities):
            raise TestFailure(f"Missing/duplicate partition {key}")
    return value


def installation_parts(snapshot: dict, excluded=()) -> dict:
    parts = [item for item in snapshot["partitions"] if item["path"] not in excluded]
    if len(parts) != 3 or sorted(item["fstype"] for item in parts) != ["btrfs", "swap", "vfat"]:
        raise TestFailure("Expected exactly one new Btrfs root, FAT ESP, and swap")
    result = {item["fstype"]: item for item in parts}
    if result["vfat"]["geometry"]["size"] * snapshot["table"]["sectorsize"] != 1024**3:
        raise TestFailure("New ESP is not the planned 1 GiB")
    if result["btrfs"]["geometry"]["size"] * snapshot["table"]["sectorsize"] != 50 * 1024**3:
        raise TestFailure("Root is not the planned 50 GiB; spare space may have been consumed")
    return result


def boot_entries(nvram: str) -> dict[str, tuple[bool, str]]:
    entries = {}
    for number, active, description in re.findall(
        r"^Boot([0-9A-Fa-f]{4})(\*?)[ \t]+(.+)$", nvram, re.MULTILINE
    ):
        number = number.upper()
        if number in entries:
            raise TestFailure("Duplicate firmware boot entry")
        entries[number] = (active == "*", description)
    return entries


def boot_order(nvram: str) -> tuple[str, ...]:
    matches = re.findall(r"^BootOrder: (.+)$", nvram, re.MULTILINE)
    if len(matches) != 1 or not re.fullmatch(r"[0-9A-Fa-f]{4}(?:,[0-9A-Fa-f]{4})*", matches[0]):
        raise TestFailure("Missing or malformed BootOrder")
    order = tuple(matches[0].upper().split(","))
    if len(order) != len(set(order)):
        raise TestFailure("Duplicate entry in BootOrder")
    return order


def vendor_entry(nvram: str, esp: dict) -> str:
    matches = [number for number, (active, line) in boot_entries(nvram).items()
               if active and re.search(r"^AnduinOS\s", line)
               and f",GPT,{esp['partuuid']},".lower() in line.lower()
               and r"\efi\anduinos\shimx64.efi" in line.lower()]
    if len(matches) != 1:
        raise TestFailure("Expected a unique AnduinOS NVRAM entry for the exact ESP PARTUUID")
    return matches[0]


def assert_preserved(before: dict, after: dict, *, rejected: bool) -> None:
    lookup = {item["path"]: item for item in after["partitions"]}
    for old in before["partitions"]:
        new = lookup.get(old["path"])
        if not re.fullmatch(r"[0-9a-f]{64}", old.get("sha256") or "") or new != old:
            raise TestFailure(f"Original partition identity, geometry, or bytes changed: {old['path']}")
    old_entries, new_entries = boot_entries(before["nvram"]), boot_entries(after["nvram"])
    if not old_entries or any(new_entries.get(key) != value for key, value in old_entries.items()):
        raise TestFailure("Existing firmware boot entries were changed or removed")
    old_order, new_order = boot_order(before["nvram"]), boot_order(after["nvram"])
    if tuple(number for number in new_order if number in old_order) != old_order:
        raise TestFailure("Existing BootOrder entries were removed or reordered")
    if rejected and any(before[key] != after[key] for key in ("table", "gpt_head", "gpt_tail", "nvram")):
        raise TestFailure("Rejected plan changed GPT or NVRAM")
    if rejected and len(before["partitions"]) != len(after["partitions"]):
        raise TestFailure("Rejected plan created partitions")


def validate_boot_identity(output: str, root: dict, esp: dict, hostname: str, firmware_esp: dict) -> None:
    def exact(key):
        matches = re.findall(rf"^{key}=(.+)$", output, re.MULTILINE)
        if len(matches) != 1:
            raise TestFailure(f"Missing/duplicate installed boot evidence: {key}")
        return matches[0]
    if (exact("ROOT_UUID") != root["uuid"] or exact("ESP_UUID") != esp["uuid"]
            or exact("HOSTNAME") != hostname):
        raise TestFailure("Boot reached the wrong installed system/root/ESP")
    current = re.findall(r"^BootCurrent: ([0-9A-Fa-f]{4})$", output, re.MULTILINE)
    if len(current) != 1 or current[0].upper() != vendor_entry(output, firmware_esp):
        raise TestFailure("Boot did not enter through the expected ESP's firmware entry")
