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


def mounted_root_script(root: dict, body: str) -> str:
    root_uuid = root["uuid"]
    if not re.fullmatch(r"[0-9a-fA-F-]{36}", root_uuid):
        raise TestFailure("Unsafe root UUID in coexistence evidence")
    return f"""
set -euo pipefail
device=/dev/disk/by-uuid/{root_uuid}
test -b "$device"
test "$(lsblk -dnro PKNAME "$device")" = vda
test -z "$(findmnt -rn -S "$device" -o TARGET)"
mountpoint=$(mktemp -d /run/anduinos-target.XXXXXX)
cleanup() {{ umount "$mountpoint"; rmdir "$mountpoint"; }}
trap cleanup EXIT
mount -o subvol=@root "$device" "$mountpoint"
{body}
sync
"""


def chainload_selection_script(a: dict) -> str:
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
grep -F {shlex.quote('chainloader /EFI/AnduinOS/shimx64.efi')} "$cfg"
grep -F 'set default="${{next_entry}}"' "$cfg"
grub-script-check "$cfg"
grub-editenv "$mountpoint/boot/grub/grubenv" set {shlex.quote('next_entry=' + title)}
grub-editenv "$mountpoint/boot/grub/grubenv" list
cat "$mountpoint/etc/grub.d/43_anduinos_linux"
cat "$cfg"
"""


class CoexistenceChecks:
    def _assert_coexistence_versions(self, vm, artifacts):
        result = vm.serial.run(r"""
set -euo pipefail
installer=$(dpkg-query -W -f='${Version}' anduinos-installer-beta)
toolkit=$(dpkg-query -W -f='${Version}' anduinos-secureboot-toolkit)
printf 'installer=%s\ntoolkit=%s\n' "$installer" "$toolkit"
dpkg --compare-versions "$installer" ge 2.0.4-3
dpkg --compare-versions "$toolkit" ge 2.0.4-2
""", check=False)
        (artifacts / "package-versions.txt").write_text(result.stdout + "\n", encoding="utf-8")
        if result.returncode != 0:
            raise TestFailure(
                "Coexistence requires installer >= 2.0.4-3 and secureboot toolkit >= 2.0.4-2; "
                "publish the packages and rebuild the ISO. Observed:\n" + result.stdout
            )

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
        result = vm.serial.run(mounted_root_script(parts["btrfs"], body), timeout=180)
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
test "$(findmnt -nro FSTYPE /)" = btrfs
dpkg-query -W anduinos-secureboot-toolkit
printf 'ROOT_UUID=%s\n' "$(findmnt -nro UUID /)"
printf 'ESP_UUID=%s\n' "$(findmnt -nro UUID /boot/efi)"
printf 'HOSTNAME=%s\n' "$(hostname)"
efibootmgr -v
""", timeout=240)
        (artifacts / f"{phase}-identity.txt").write_text(result.stdout + "\n", encoding="utf-8")
        validate_boot_identity(result.stdout, parts["btrfs"], parts["vfat"], hostname, firmware_esp)
        restored = vm.serial.run(render_installed_grub_restoration(), timeout=180)
        (artifacts / f"{phase}-restoration.txt").write_text(restored.stdout + "\n", encoding="utf-8")
        _login_gdm(vm, self.defaults.username, self.defaults.password, timeout=180)
        if _graphical_user(vm.serial) != self.defaults.username:
            raise TestFailure("Installed desktop login reached the wrong user")
        vm.screenshot(phase + "-desktop")
        _power_off(vm, unmount_esp=True)

    def _run_coexistence(self, vm, scenario, artifacts):
        shared = scenario.storage_mode is StorageMode.COEXISTENCE_SHARED_ESP
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
            a = installation_parts(initial)
            vendor_entry(initial["nvram"], a["vfat"])
            health = vm.serial.run(
                "fsck.fat -n " + shlex.quote(a["vfat"]["path"]),
                timeout=180, check=False,
            )
            (b_dir / "a-esp-health.txt").write_text(health.stdout + "\n", encoding="utf-8")
            if health.returncode != 0:
                raise TestFailure("A's ESP is not clean before planning B:\n" + health.stdout)
            paths = tuple(item["path"] for item in initial["partitions"])
            before = self._coexistence_snapshot(vm, b_dir, "before-b", paths)
        check = "coexistence.reject-shared-esp" if shared else "coexistence.install-b-independent"
        with self._check(scenario, check):
            self._run_installer_driver(vm, scenario, b_dir, config_overrides={
                "coexistence_stage": "b-shared" if shared else "b-separate",
                "hostname": "coexist-b", "existing_esp_path": a["vfat"]["path"],
            })
            vm.screenshot("b-rejected" if shared else "b-installed")
        with self._check(scenario, "coexistence.a-preserved"):
            after = self._coexistence_snapshot(vm, b_dir, "after-b", paths)
            assert_preserved(before, after, rejected=shared)
            if not shared:
                b = installation_parts(after, excluded=paths)
                b_entry = vendor_entry(after["nvram"], b["vfat"])
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
                mounted_root_script(b["btrfs"], chainload_selection_script(a)), timeout=180,
            )
            (chain_dir / "b-chainload-entry.txt").write_text(result.stdout + "\n", encoding="utf-8")
            self._assert_live_cleanup(vm, chain_dir)
            _power_off(vm)
        with self._check(scenario, "coexistence.boot-a-via-b"):
            # BootCurrent must still name B's ESP, while / and /boot/efi must
            # belong to A: proves B -> A's shim/GRUB -> A's kernel, not fallback.
            self._coexistence_boot(vm, a, b["vfat"], a_hostname, chain_dir, "a-via-b", scenario_id=scenario.id)
