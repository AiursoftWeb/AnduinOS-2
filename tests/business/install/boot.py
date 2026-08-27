"""MOK enrollment, temporary GRUB instrumentation, and Live cleanup."""

from .context import *  # noqa: F403


class BootChecks:
    def _enroll_mok(
        self,
        vm: QemuVm,
        scenario: Scenario,
        artifacts: Path,
    ) -> None:
        self.status(scenario.id, "Completing MOK enrollment with fresh UEFI VARS")
        vm.start(attach_iso=False)
        assert vm.qmp is not None
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
