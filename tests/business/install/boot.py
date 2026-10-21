"""MOK enrollment, temporary GRUB instrumentation, and Live cleanup."""

from .context import *  # noqa: F403


class BootChecks:
    def _assert_secure_boot_first_boot(
        self, vm: QemuVm, scenario: Scenario, artifacts: Path,
    ) -> None:
        """Inspect trust and the real frontend without invoking any repair."""
        assert vm.serial is not None
        remote = "/run/anduinos-acceptance-secure-boot"
        vm.serial.run(f"install -d -m 0777 {remote}/evidence")
        self.driver.upload(vm.serial, remote)
        try:
            result = vm.serial.run(
                f"python3 {remote}/ui/secure_boot.py",
                timeout=120, check=False,
            )
            (artifacts / "secure-boot-first-boot.txt").write_text(
                result.stdout + "\n", encoding="utf-8"
            )
            if result.returncode:
                raise TestFailure("First-boot signing readiness failed:\n" + result.stdout[-8000:])
            result = vm.serial.run(
                _desktop_command(self.defaults.username, (
                    "python3", f"{remote}/atspi_driver.py", "secure-boot-green",
                    "--evidence", f"{remote}/evidence",
                ), managed=True), timeout=180, check=False,
            )
            with (artifacts / "atspi-events.jsonl").open("a", encoding="utf-8") as stream:
                stream.write(result.stdout + "\n")
            if result.returncode or not any(
                line.startswith('{"event": "secure-boot-green"')
                for line in result.stdout.splitlines()
            ):
                raise TestFailure("Driver Center is not healthy on first boot:\n" + result.stdout[-8000:])
            self._check_note(scenario, "secure-boot.first-boot-green",
                             "Unified MOK enrolled; signing defaults and bootloader ready; healthy UI, no repair needed")
        finally:
            vm.screenshot("secure-boot-first-boot")
            _retrieve_tree(vm.serial, remote, artifacts / "guest-secure-boot-evidence")

    def _assert_uefi_boot_registration(
        self,
        vm: QemuVm,
        scenario: Scenario,
        artifacts: Path,
    ) -> None:
        """Prove the first target boot cannot enter shim's #422 reset loop."""

        if not scenario.firmware.is_uefi:
            raise TestFailure("UEFI registration check used for a BIOS case")
        assert vm.serial is not None
        suffix = "x64" if self.architecture is Architecture.AMD64 else "aa64"
        # The native installer always registers shim, including when Secure
        # Boot is disabled.  It provides one consistent vendor boot path and
        # allows Secure Boot to be enabled later without reinstalling GRUB.
        executable = f"shim{suffix}.efi"
        registrar = "fbx64.efi" if suffix == "x64" else "fbaa64.efi"
        relative_loader = f"EFI/AnduinOS/{executable}"
        expected_loader = "\\" + relative_loader.replace("/", "\\")
        script = f"""
set -uo pipefail
esp_device=$(lsblk -pnro NAME,PARTLABEL,FSTYPE,TYPE | awk '$2 == "efi-system" && $3 == "vfat" && $4 == "part" {{ print $1; exit }}')
esp_partuuid=missing
vendor_loader=missing
fallback_registrar=unknown
if [ -n "$esp_device" ] && [ -b "$esp_device" ]; then
    esp_partuuid=$(blkid -s PARTUUID -o value "$esp_device" 2>/dev/null || true)
    mountpoint=$(mktemp -d /run/anduinos-esp.XXXXXX)
    if mount --read-only --types vfat --options nosuid,nodev,noexec "$esp_device" "$mountpoint"; then
        [ -s "$mountpoint/{relative_loader}" ] && vendor_loader=present || vendor_loader=missing
        [ -e "$mountpoint/EFI/BOOT/{registrar}" ] && fallback_registrar=present || fallback_registrar=absent
        umount "$mountpoint"
    fi
    rmdir "$mountpoint" 2>/dev/null || true
fi
nvram_output=$(efibootmgr --verbose 2>&1 || true)
printf 'ESP_DEVICE=%s\n' "${{esp_device:-missing}}"
printf 'ESP_PARTUUID=%s\n' "${{esp_partuuid:-missing}}"
printf 'VENDOR_LOADER=%s\n' "$vendor_loader"
printf 'FALLBACK_REGISTRAR=%s\n' "$fallback_registrar"
printf '%s\n' "$nvram_output"
"""
        result = vm.serial.run(script, timeout=60, check=False)
        destination = artifacts / "uefi-boot-registration.txt"
        destination.write_text(result.stdout + "\n", encoding="utf-8")
        _validate_uefi_boot_registration_evidence(
            result.stdout,
            expected_loader=expected_loader,
        )
        self._check_note(
            scenario,
            "boot.uefi-vendor-registration",
            "AnduinOS vendor loader is first in BootOrder; shim fallback registrar absent",
        )

    def _remove_vendor_boot_entry(
        self, vm: QemuVm, scenario: Scenario, artifacts: Path,
    ) -> None:
        """Lose only the verified install entry, preserving the trust store."""
        assert vm.serial is not None
        evidence = (artifacts / "uefi-boot-registration.txt").read_text()
        entries = re.findall(r"^Boot([0-9A-Fa-f]{4})\*?\s+AnduinOS\s+.*$", evidence, re.MULTILINE)
        partuuids = re.findall(r"^ESP_PARTUUID=(\S+)$", evidence, re.MULTILINE)
        if len(entries) != 1 or len(partuuids) != 1:
            raise TestFailure("Cannot identify the verified installation entry and ESP")
        number, partuuid = entries[0], partuuids[0]
        suffix = "x64" if self.architecture is Architecture.AMD64 else "aa64"
        boot_name = "BOOTX64.EFI" if suffix == "x64" else "BOOTAA64.EFI"
        script = f"""
python3 - <<'PY'
import hashlib, json, re, subprocess, tempfile
from pathlib import Path
def command(*args):
    return subprocess.check_output(args, text=True)
def trust():
    return {{p.name: hashlib.sha256(p.read_bytes()).hexdigest()
            for p in Path('/sys/firmware/efi/efivars').iterdir()
            if p.name.split('-')[0] in ('PK', 'KEK', 'db', 'dbx') or p.name.startswith('Mok')}}
before = command('efibootmgr', '--verbose')
entry = next(line for line in before.splitlines() if line.startswith('Boot{number}'))
assert 'AnduinOS' in entry and {partuuid.lower()!r} in entry.lower(), entry
assert r'\\EFI\\AnduinOS\\shim{suffix}.efi'.lower() in entry.lower(), entry
assert not re.search(r'^BootNext:', before, re.M), before
keys = trust()
device = command('findfs', 'PARTUUID={partuuid}').strip()
with tempfile.TemporaryDirectory(prefix='anduinos-fallback-', dir='/run') as directory:
    subprocess.run(['mount', '-t', 'vfat', '-o', 'ro,nosuid,nodev,noexec', device, directory], check=True)
    try:
        esp = Path(directory)
        for source, target in (('shim{suffix}.efi', '{boot_name}'), ('grub{suffix}.efi', 'grub{suffix}.efi'),
                               ('mm{suffix}.efi', 'mm{suffix}.efi'), ('grub.cfg', 'grub.cfg')):
            payload = (esp / 'EFI/AnduinOS' / source).read_bytes()
            assert payload and payload == (esp / 'EFI/BOOT' / target).read_bytes(), target
        assert not list((esp / 'EFI/BOOT').glob('fb*.efi'))
    finally:
        subprocess.run(['umount', directory], check=True)
subprocess.run(['efibootmgr', '--bootnum', '{number}', '--delete-bootnum'], check=True)
after = command('efibootmgr', '--verbose')
numbers = lambda text: set(re.findall(r'^Boot([0-9A-Fa-f]{{4}})\\*?\\s', text, re.M))
assert numbers(after) == numbers(before) - {{{number!r}}}, after
assert not re.search(r'^BootNext:', after, re.M), after
assert trust() == keys, 'Firmware trust variables changed'
print(json.dumps({{'removed': '{number}', 'esp_partuuid': '{partuuid}', 'before': before,
                  'after': after, 'trust_unchanged': True}}))
PY
"""
        result = vm.serial.run(script, timeout=120, check=False)
        (artifacts / "uefi-entry-loss-injection.txt").write_text(result.stdout + "\n")
        if result.returncode:
            raise TestFailure("UEFI entry-loss injection failed:\n" + result.stdout[-8000:])
        self._check_note(scenario, "boot.uefi-entry-loss-injection",
                         "Only the verified vendor entry removed; direct fallback matches; firmware trust unchanged")

    def _assert_fallback_boot(
        self, vm: QemuVm, scenario: Scenario, artifacts: Path,
    ) -> None:
        assert vm.serial is not None
        script = r"""
python3 - <<'PY'
import json, re, subprocess
def command(*args):
    return subprocess.check_output(args, text=True)
nvram = command('efibootmgr', '--verbose')
current = re.search(r'^BootCurrent:\s*([0-9A-Fa-f]{4})$', nvram, re.M).group(1)
entry = next(line for line in nvram.splitlines() if line.startswith('Boot' + current))
assert '\\efi\\anduinos\\' not in entry.lower(), entry
assert not re.search(r'^BootNext:', nvram, re.M), nvram
state = json.loads(command('/usr/libexec/anduinos-grub-probe'))
assert state['signature'] == 'valid' and state['deployment'] == 'ready', state
print(json.dumps({'boot_current': entry, 'nvram': nvram, 'grub': state,
                  'root': command('findmnt', '-no', 'SOURCE,UUID', '/')}))
PY
"""
        result = vm.serial.run(script, timeout=120, check=False)
        (artifacts / "uefi-entry-loss-recovery.txt").write_text(result.stdout + "\n")
        if result.returncode:
            raise TestFailure("Default firmware fallback boot is not healthy:\n" + result.stdout[-8000:])
        self._check_note(scenario, "boot.uefi-entry-loss-recovery",
                         "Booted without ISO or vendor entry; signed boot chain deployed and healthy")

    def _enroll_mok(
        self,
        vm: QemuVm,
        scenario: Scenario,
        artifacts: Path,
    ) -> None:
        self.status(scenario.id, "Completing MOK enrollment in the existing UEFI VARS")
        vm.start(attach_iso=False)
        assert vm.qmp is not None
        assert vm.serial is not None
        try:
            with vm.serial.capture_output():
                delay = self.options.firmware_delay_seconds + (
                    18 if self.architecture is Architecture.ARM64 else 8
                )
                time.sleep(delay)
                vm.screenshot("mok-manager")
                sequence = (
                    ("down", 0.5),
                    ("ret", 1.0),
                    ("down", 0.5),
                    ("ret", 1.0),
                    ("down", 0.5),
                    ("ret", 1.0),
                )
                for key, pause in sequence:
                    vm.qmp.send_key(key)
                    time.sleep(pause)
                vm.qmp.type_text(self.defaults.mok_password, interval=0.08)
                vm.qmp.send_key("ret")
                time.sleep(1)
                vm.qmp.send_key("ret")
                try:
                    vm.wait(180)
                except ProtocolError:
                    vm.screenshot("mok-manager-timeout")
                    raise TestFailure("MokManager did not reboot after enrollment")
        finally:
            vm.stop()
        (artifacts / "mok-enrollment.txt").write_text(
            "MokManager keyboard workflow completed; lifecycle verification follows.\n",
            encoding="utf-8",
        )

    def _assert_mok_enrollment_lifecycle(
        self,
        vm: QemuVm,
        scenario: Scenario,
        artifacts: Path,
    ) -> None:
        if not scenario.mok_enrollment:
            raise TestFailure("MOK lifecycle assertion used for a non-enrollment case")
        assert vm.serial is not None
        pending_path = artifacts / "target-grub-one-shot.txt"
        try:
            pending_output = pending_path.read_text(encoding="utf-8")
        except OSError as error:
            raise TestFailure(f"Cannot read pre-enrollment MOK evidence: {error}") from error
        result = vm.serial.run(
            r"""
set -euo pipefail
state=$(mokutil --sb-state)
printf '%s\n' "$state" | grep -qi 'SecureBoot enabled'
test -z "$(mokutil --list-new 2>/dev/null)"
certificate=/var/lib/shim-signed/mok/MOK.der
test -s "$certificate"
expected=$(openssl x509 -inform DER -in "$certificate" -noout -fingerprint -sha1 | cut -d= -f2 | tr -d ':' | tr '[:lower:]' '[:upper:]')
normalized=$(mokutil --list-enrolled | tr -d ':' | tr '[:lower:]' '[:upper:]')
printf '%s' "$normalized" | grep -Fq "$expected"
printf 'MOK_SECURE_BOOT=enabled\n'
printf 'MOK_PENDING=none\n'
printf 'MOK_ENROLLED_FINGERPRINT=%s\n' "$expected"
""",
            check=False,
        )
        destination = artifacts / "mok-enrollment-verification.txt"
        destination.write_text(result.stdout + "\n", encoding="utf-8")
        if result.returncode != 0:
            raise TestFailure(
                "Installed MOK lifecycle probe failed with exit "
                f"{result.returncode}:\n{result.stdout[-8000:]}"
            )
        _validate_mok_lifecycle_evidence(pending_output, result.stdout)
        self._check_note(
            scenario,
            "mok-enrollment",
            "Secure Boot enabled; pending cleared; installed certificate enrolled",
        )

    def _show_target_grub_once(
        self,
        vm: QemuVm,
        scenario: Scenario,
        artifacts: Path,
    ) -> InstalledBootFiles:
        """Validate target boot files and arm a reversible normal GRUB boot."""

        assert vm.serial is not None
        mount_options = (
            "-o subvol=@root" if scenario.filesystem.value == "btrfs" else ""
        )
        script = f"""
set -euo pipefail
root_device=$(lsblk -pnro NAME,FSTYPE,TYPE | awk '$2 == "{scenario.filesystem.value}" && $3 == "part" {{ print $1; exit }}')
test -b "$root_device"
mountpoint=$(mktemp -d /run/anduinos-target.XXXXXX)
cleanup() {{ umount "$mountpoint" 2>/dev/null || true; rmdir "$mountpoint" 2>/dev/null || true; }}
trap cleanup EXIT
mount {mount_options} "$root_device" "$mountpoint"
test -s "$mountpoint/boot/grub/grub.cfg"
grub-script-check "$mountpoint/boot/grub/grub.cfg"
kernel=$(find "$mountpoint/boot" -maxdepth 1 -type f -name 'vmlinuz-*' -printf '%f\n' | sort -V | tail -n1)
test -n "$kernel"
version=${{kernel#vmlinuz-}}
initrd="initrd.img-$version"
test -s "$mountpoint/boot/$kernel"
test -s "$mountpoint/boot/$initrd"
test -s /cdrom/LiveOS/vmlinuz
target_kernel_sha256=$(sha256sum "$mountpoint/boot/$kernel" | awk '{{ print $1 }}')
iso_kernel_sha256=$(sha256sum /cdrom/LiveOS/vmlinuz | awk '{{ print $1 }}')
lsinitrd "$mountpoint/boot/$initrd" >/dev/null
printf 'ANDUINOS_TARGET_KERNEL_SHA256=%s\n' "$target_kernel_sha256"
printf 'ANDUINOS_ISO_KERNEL_SHA256=%s\n' "$iso_kernel_sha256"
printf 'ANDUINOS_INITRD_CHECK=ok\n'
if [ "{scenario.firmware.value}" = "uefi-sb" ]; then
    certificate="$mountpoint/var/lib/shim-signed/mok/MOK.der"
    test -s "$certificate"
    pending=$(mokutil --list-new 2>/dev/null)
    test -n "$pending"
    expected=$(openssl x509 -inform DER -in "$certificate" -noout -fingerprint -sha1 | cut -d= -f2 | tr -d ':' | tr '[:lower:]' '[:upper:]')
    normalized=$(printf '%s' "$pending" | tr -d ':' | tr '[:lower:]' '[:upper:]')
    printf '%s' "$normalized" | grep -Fq "$expected"
    printf 'MOK_PENDING_FINGERPRINT=%s\n' "$expected"
elif [ "{scenario.firmware.value}" = "uefi-nosb" ]; then
    test -z "$(mokutil --list-new 2>/dev/null)"
    printf 'MOK_PENDING=none\n'
fi
printf 'ANDUINOS_KERNEL=%s\n' "$kernel"
printf 'ANDUINOS_INITRD=%s\n' "$initrd"
grub-editenv "$mountpoint/boot/grub/grubenv" list
{render_installed_grub_instrumentation(self.architecture, mounted_target=True)}
sync
"""
        result = vm.serial.run(script, timeout=120)
        (artifacts / "target-grub-one-shot.txt").write_text(
            result.stdout + "\n", encoding="utf-8"
        )
        _validate_target_boot_integrity(result.stdout)
        kernel = _extract_boot_filename(result.stdout, "ANDUINOS_KERNEL", "vmlinuz-")
        initrd = _extract_boot_filename(result.stdout, "ANDUINOS_INITRD", "initrd.img-")
        prefix = "/@root/boot" if scenario.filesystem.value == "btrfs" else "/boot"
        return InstalledBootFiles(
            kernel=f"{prefix}/{kernel}",
            initrd=f"{prefix}/{initrd}",
        )

    def _assert_live_cleanup(self, vm: QemuVm, artifacts: Path) -> None:
        """Prove that neither the installer nor target inspection leaked mounts."""

        assert vm.serial is not None
        result = vm.serial.run(
            r"""
set -euo pipefail
mount_targets=$(findmnt -rn -o TARGET)
printf '%s\n' "$mount_targets"
if printf '%s\n' "$mount_targets" | grep -Eq '^/target($|/)|^/run/anduinos-target\.'; then
    echo 'Installer or harness target mount remains active' >&2
    exit 1
fi
if find /run -maxdepth 1 -type d -name 'anduinos-target.*' -print -quit | grep -q .; then
    echo 'Harness target mount directory remains' >&2
    exit 1
fi
printf 'temporary-target-mounts=clean\n'
"""
        )
        (artifacts / "live-post-install-cleanup.txt").write_text(
            result.stdout + "\n", encoding="utf-8"
        )
