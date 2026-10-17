"""Sequential GUI installs on one disposable disk, with real firmware boots."""

from .context import *  # noqa: F403
from assertions.coexistence import (
    assert_preserved, installation_parts, parse_snapshot, vendor_entry,
    validate_boot_identity,
)
from framework.model import StorageMode


def coexistence_check_ids(scenario: Scenario) -> tuple[str, ...]:
    shared = scenario.storage_mode is StorageMode.COEXISTENCE_SHARED_ESP
    return (
        "coexistence.package-versions", "coexistence.live-b-baseline",
        "coexistence.reject-shared-esp" if shared else "coexistence.install-b-independent",
        "coexistence.a-preserved",
        *(("coexistence.boot-a-after-rejection",) if shared else (
            "coexistence.boot-b", "coexistence.prepare-chainload", "coexistence.boot-a-via-b",
        )),
    )


def installation_root(parts):
    return parts.get("ext4") or parts["btrfs"]


def mounted_root_script(root: dict, body: str) -> str:
    root_uuid = root["uuid"]
    if not re.fullmatch(r"[0-9a-fA-F-]{36}", root_uuid):
        raise TestFailure("Unsafe root UUID in coexistence evidence")
    options = "ro,noload" if root.get("fstype") == "ext4" else "subvol=@root"
    return f"""
set -euo pipefail
device=/dev/disk/by-uuid/{root_uuid}
test -b "$device"
test "$(lsblk -dnro PKNAME "$device")" = vda
test -z "$(findmnt -rn -S "$device" -o TARGET)"
mountpoint=$(mktemp -d /run/anduinos-target.XXXXXX)
cleanup() {{ umount "$mountpoint"; rmdir "$mountpoint"; }}
trap cleanup EXIT
mount -o {options} "$device" "$mountpoint"
{body}
sync
"""


def ext4_file_manifest_script(root: dict) -> str:
    """Read every original regular file, symlink and metadata after offline fsck."""
    if root.get("fstype") != "ext4":
        raise TestFailure("File manifest requires an ext4 root")
    script = mounted_root_script(root, r'''
python3 - "$mountpoint" <<'PY'
import hashlib, json, os, stat, sys
base = sys.argv[1]
digest = hashlib.sha256()
for directory, dirs, files in os.walk(base, followlinks=False):
    dirs.sort()
    for name in sorted(dirs + files):
        path = os.path.join(directory, name)
        info = os.lstat(path)
        record = [os.path.relpath(path, base), info.st_mode, info.st_uid, info.st_gid]
        if stat.S_ISREG(info.st_mode):
            content = hashlib.sha256()
            with open(path, 'rb') as stream:
                for block in iter(lambda: stream.read(1024**2), b''):
                    content.update(block)
            record.extend((info.st_size, content.hexdigest()))
        elif stat.S_ISLNK(info.st_mode):
            record.append(os.readlink(path))
        digest.update(json.dumps(record, ensure_ascii=True).encode() + b'\n')
print('EXT4_FILES_SHA256=' + digest.hexdigest())
PY
''')
    # This script mounts read-only and does not replay a journal or repair.
    return script.replace('mount -o ro,noload',
        'e2fsck -f -n "$device"\nmount -o ro,noload')


def chainload_selection_script(a: dict, architecture: Architecture = Architecture.AMD64) -> str:
    suffix = "x64" if architecture is Architecture.AMD64 else "aa64"
    esp_uuid = a["vfat"]["uuid"]
    if not re.fullmatch(r"[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}", esp_uuid):
        raise TestFailure("Unsafe FAT UUID in coexistence evidence")
    title = f"AnduinOS (other installation) — ESP {esp_uuid}"
    # Select the product-generated entry via GRUB's normal one-shot mechanism.
    # No synthetic menuentry, direct linux command, or firmware redirection.
    return f"""
cfg="$mountpoint/boot/grub/grub.cfg"
test -x "$mountpoint/etc/grub.d/43_anduinos_linux"
test "$(grep -Fc {shlex.quote("menuentry '" + title + "'")} "$cfg")" = 1
grep -F {shlex.quote(f'chainloader /EFI/AnduinOS/shim{suffix}.efi')} "$cfg"
grep -F 'set default="${{next_entry}}"' "$cfg"
grub-script-check "$cfg"
grub-editenv "$mountpoint/boot/grub/grubenv" set {shlex.quote('next_entry=' + title)}
grub-editenv "$mountpoint/boot/grub/grubenv" list
cat "$mountpoint/etc/grub.d/43_anduinos_linux"
cat "$cfg"
"""


class CoexistenceChecks:
    def _assert_coexistence_versions(self, vm, artifacts, *, ext4_shrink=False):
        result = vm.serial.run(r"""
set -euo pipefail
installer=$(dpkg-query -W -f='${Version}' anduinos-installer-beta)
toolkit=$(dpkg-query -W -f='${Version}' anduinos-secureboot-toolkit)
printf 'installer=%s\ntoolkit=%s\n' "$installer" "$toolkit"
dpkg --compare-versions "$installer" ge 2.0.4-3
dpkg --compare-versions "$toolkit" ge 2.0.4-2
""".replace("ge 2.0.4-3", "ge 2.0.4-15" if ext4_shrink else "ge 2.0.4-3"), check=False)
        (artifacts / "package-versions.txt").write_text(result.stdout + "\n", encoding="utf-8")
        if result.returncode != 0:
            raise TestFailure(
                f"Coexistence requires installer >= {'2.0.4-15' if ext4_shrink else '2.0.4-3'} "
                "and secureboot toolkit >= 2.0.4-2; "
                "publish the packages and rebuild the ISO. Observed:\n" + result.stdout
            )

    def _ext4_manifest(self, vm, root, artifacts, label):
        result = vm.serial.run(ext4_file_manifest_script(root), timeout=1800)
        (artifacts / f"{label}-file-manifest.txt").write_text(result.stdout + "\n", encoding="utf-8")
        matches = re.findall(r"^EXT4_FILES_SHA256=([0-9a-f]{64})$", result.stdout, re.MULTILINE)
        if len(matches) != 1:
            raise TestFailure("Missing/ambiguous ext4 file manifest")
        self._assert_live_cleanup(vm, artifacts)
        return matches[0]

    def _coexistence_live(self, vm, scenario, artifacts, phase):
        entry = self._assert_grub_regional_contract(scenario, artifacts)
        region = scenario_live_region(self.defaults, scenario)
        self._boot_live_session(
            vm, entry, region, artifacts, persistent=False, phase=phase,
        )
        assert_live_environment(
            vm.serial, scenario, artifacts, region.locale, region.timezone,
            region.keyboard, session_timeout_seconds=self.options.boot_timeout_seconds,
            check_region=False,
        )
        vm.screenshot(phase)

    def _coexistence_snapshot(self, vm, artifacts, label, hash_paths=()):
        source = Path(__file__).parents[2] / "assertions/guest/coexistence_probe.py"
        remote = "/run/anduinos-coexistence-probe.py"
        vm.serial.upload(source, remote, 0o644)
        result = vm.serial.run(shlex.join(("python3", remote, *hash_paths)), timeout=900)
        (artifacts / f"{label}.txt").write_text(result.stdout + "\n", encoding="utf-8")
        value = parse_snapshot(result.stdout)
        (artifacts / f"{label}.json").write_text(
            json.dumps(value, indent=2) + "\n", encoding="utf-8"
        )
        return value

    def _coexistence_arm(self, vm, parts, artifacts, label):
        body = f"""
test -s "$mountpoint/boot/grub/grub.cfg"
test -s "$mountpoint/boot/vmlinuz" || ls "$mountpoint"/boot/vmlinuz-* >/dev/null
test -s "$mountpoint/boot/initrd.img" || ls "$mountpoint"/boot/initrd.img-* >/dev/null
cat "$mountpoint/etc/fstab"
{render_installed_grub_instrumentation(self.architecture, mounted_target=True)}
"""
        script = mounted_root_script(installation_root(parts), body)
        # Boot instrumentation intentionally writes GRUB in the disposable VM;
        # file-preservation manifests above always use the read-only variant.
        script = script.replace("mount -o ro,noload", "mount -o rw")
        result = vm.serial.run(script, timeout=180)
        (artifacts / f"{label}-instrumentation.txt").write_text(result.stdout + "\n", encoding="utf-8")
        self._assert_live_cleanup(vm, artifacts)

    def _coexistence_boot(self, vm, parts, firmware_esp, hostname, artifacts, phase, *, scenario_id):
        self.status(scenario_id, f"Booting {hostname} without ISO; checking root, ESP and firmware identity")
        vm.start(attach_iso=False, phase=phase)
        vm.serial.timeout = self.options.command_timeout_seconds
        vm.serial.wait_for_shell(self.options.boot_timeout_seconds)
        # The debug shell can precede local-fs/GDM. Observe completed mounts
        # before comparing UUIDs, rather than accepting the Live root or initrd.
        result = vm.serial.run(r"""
set -euo pipefail
for attempt in $(seq 1 180); do
    if mountpoint -q /boot/efi && systemctl is-active --quiet display-manager; then break; fi
    sleep 1
done
mountpoint -q /boot/efi
systemctl is-active --quiet display-manager
test "$(findmnt -nro FSTYPE /)" = ROOT_FSTYPE
dpkg-query -W anduinos-secureboot-toolkit
printf 'ROOT_UUID=%s\n' "$(findmnt -nro UUID /)"
printf 'ESP_UUID=%s\n' "$(findmnt -nro UUID /boot/efi)"
printf 'HOSTNAME=%s\n' "$(hostname)"
efibootmgr -v
""".replace("ROOT_FSTYPE", installation_root(parts)["fstype"]), timeout=240)
        (artifacts / f"{phase}-identity.txt").write_text(result.stdout + "\n", encoding="utf-8")
        validate_boot_identity(result.stdout, installation_root(parts), parts["vfat"], hostname, firmware_esp, self.architecture)
        restored = vm.serial.run(render_installed_grub_restoration(), timeout=180)
        (artifacts / f"{phase}-restoration.txt").write_text(restored.stdout + "\n", encoding="utf-8")
        _login_gdm(vm, self.defaults.username, self.defaults.password, timeout=180)
        if _graphical_user(vm.serial) != self.defaults.username:
            raise TestFailure("Installed desktop login reached the wrong user")
        vm.screenshot(phase + "-desktop")
        if installation_root(parts)["fstype"] == "ext4":
            _power_off_clean_ext4(vm)
        else:
            _power_off(vm, unmount_esp=True)

    def _run_coexistence(self, vm, scenario, artifacts):
        shared = scenario.storage_mode is StorageMode.COEXISTENCE_SHARED_ESP
        shrinking = scenario.storage_mode is StorageMode.COEXISTENCE_EXT4_SHRINK
        filesystem = "ext4" if shrinking else "btrfs"
        a_dir, b_dir, chain_dir = (artifacts / name for name in ("a", "b", "chainload"))
        for directory in (a_dir, b_dir, chain_dir):
            directory.mkdir()
        # A executes the established full installation/desktop contract suite,
        # including recovery baselines. Only its disk-planning UI differs.
        boot_files = self._run_live_phase(
            vm, scenario, a_dir, config_overrides={"coexistence_stage": "a"},
        )
        if boot_files is None:
            raise TestFailure("Installation A did not produce boot files")
        self._run_target_phase(vm, scenario, boot_files, a_dir)
        a_hostname = self.defaults.hostname.casefold()
        with self._check(scenario, "coexistence.live-b-baseline"):
            self._coexistence_live(vm, scenario, b_dir, "live-b")
            initial = self._coexistence_snapshot(vm, b_dir, "initial-layout")
            a = installation_parts(initial, filesystem=filesystem, root_gib=96 if shrinking else 50)
            vendor_entry(initial["nvram"], a["vfat"], self.architecture)
            health = vm.serial.run(
                "fsck.fat -n " + shlex.quote(a["vfat"]["path"]),
                timeout=180, check=False,
            )
            (b_dir / "a-esp-health.txt").write_text(health.stdout + "\n", encoding="utf-8")
            if health.returncode != 0:
                raise TestFailure("A's ESP is not clean before planning B:\n" + health.stdout)
            paths = tuple(item["path"] for item in initial["partitions"])
            hash_paths = tuple(path for path in paths
                              if not shrinking or path != a["ext4"]["path"])
            if shrinking:
                manifest = self._ext4_manifest(vm, a["ext4"], b_dir, "before-b")
            before = self._coexistence_snapshot(vm, b_dir, "before-b", hash_paths)
        check = "coexistence.reject-shared-esp" if shared else "coexistence.install-b-independent"
        with self._check(scenario, check):
            self._run_installer_driver(vm, scenario, b_dir, config_overrides={
                "coexistence_stage": "b-shared" if shared else "b-separate",
                "hostname": "coexist-b", "existing_esp_path": a["vfat"]["path"],
                **({"resize_ext4_path": a["ext4"]["path"]} if shrinking else {}),
            })
            vm.screenshot("b-rejected" if shared else "b-installed")
        with self._check(scenario, "coexistence.a-preserved"):
            after = self._coexistence_snapshot(vm, b_dir, "after-b", hash_paths)
            assert_preserved(before, after, rejected=shared,
                **({"resized_ext4_path": a["ext4"]["path"], "target_size_bytes": 40 * 1024**3}
                   if shrinking else {}))
            if shrinking:
                a["ext4"] = next(p for p in after["partitions"] if p["path"] == a["ext4"]["path"])
                if self._ext4_manifest(vm, a["ext4"], b_dir, "after-b") != manifest:
                    raise TestFailure("Original ext4 files, links or metadata changed during shrinking")
            if not shared:
                b = installation_parts(after, excluded=paths, filesystem=filesystem)
                b_entry = vendor_entry(after["nvram"], b["vfat"], self.architecture)
                order = re.findall(r"^BootOrder: (.+)$", after["nvram"], re.MULTILINE)
                if len(order) != 1 or order[0].split(",")[0] != b_entry:
                    raise TestFailure("New installation B is not the default firmware entry")
        if shared:
            with self._check(scenario, "coexistence.boot-a-after-rejection"):
                self._coexistence_arm(vm, a, b_dir, "a-after")
                _power_off(vm)
                self._coexistence_boot(vm, a, a["vfat"], a_hostname, b_dir, "a-after-rejection", scenario_id=scenario.id)
            return
        with self._check(scenario, "coexistence.boot-b"):
            self._coexistence_arm(vm, b, b_dir, "b-first")
            _power_off(vm)
            self._coexistence_boot(vm, b, b["vfat"], "coexist-b", b_dir, "b-default", scenario_id=scenario.id)
        with self._check(scenario, "coexistence.prepare-chainload"):
            self._coexistence_live(vm, scenario, chain_dir, "live-chainload")
            self._coexistence_arm(vm, a, chain_dir, "a-chainload")
            result = vm.serial.run(
                mounted_root_script(installation_root(b), chainload_selection_script(a, self.architecture)).replace(
                    "mount -o ro,noload", "mount -o rw"), timeout=180,
            )
            (chain_dir / "b-chainload-entry.txt").write_text(result.stdout + "\n", encoding="utf-8")
            self._assert_live_cleanup(vm, chain_dir)
            _power_off(vm)
        with self._check(scenario, "coexistence.boot-a-via-b"):
            # BootCurrent must still name B's ESP, while / and /boot/efi must
            # belong to A: proves B -> A's shim/GRUB -> A's kernel, not fallback.
            self._coexistence_boot(vm, a, b["vfat"], a_hostname, chain_dir, "a-via-b", scenario_id=scenario.id)
