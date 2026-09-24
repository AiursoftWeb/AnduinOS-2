"""ISO-mode USB regression: actual UEFI boot, Live identity and GNOME login."""
from __future__ import annotations

import json
import contextlib
import shutil
import tempfile
import time
from pathlib import Path

from framework.errors import ConfigurationError, TestFailure
from framework.firmware import resolve_firmware
from framework.grub import boot_iso_with_debug_shell
from framework.iso import volume_label
from framework.model import Architecture, Firmware, Network
from framework.qemu import QemuConfig, QemuVm, resolve_qemu
from framework.reporting import write_junit_report
from framework.usb_iso import prepare_iso_usb


def run_live_usb(inspection, artifacts: Path, overrides, *, timeout=600, memory=4096, cpus=2, delay=2) -> bool:
    """AMD64 Rufus regression. Dedicated reports remain visible in full runs."""
    if inspection.architecture is not Architecture.AMD64:
        raise ConfigurationError('Rufus ISO-mode boot regression currently requires AMD64')
    artifacts.mkdir(parents=True, exist_ok=False)
    started = time.monotonic()
    records = []
    firmware = resolve_firmware(Architecture.AMD64, Firmware.UEFI_NO_SECURE_BOOT, overrides)
    binary, accel = resolve_qemu(Architecture.AMD64)
    # Default FAT label and a user-selected label must both preserve the ABI.
    labels = (volume_label(inspection.path).upper()[:11], 'CUSTOM_USB')
    for label in labels:
        case = artifacts / label
        case.mkdir()
        record = dict(id=f'live-usb-iso-mode-{label}', status='failed', seconds=0, error='')
        begin = time.monotonic()
        vm = None
        print(f'[ISO USB] Testing FAT label {label}', flush=True)
        try:
            with tempfile.TemporaryDirectory(prefix='.usb-work-', dir=case) as directory:
                work = Path(directory)
                image = prepare_iso_usb(inspection.path, work, label)
                variables = work / 'vars.fd'
                shutil.copyfile(firmware.variables_template, variables)
                vm = QemuVm(QemuConfig(
                    architecture=Architecture.AMD64, firmware=Firmware.UEFI_NO_SECURE_BOOT,
                    network=Network.OFFLINE, memory_mib=memory, cpus=cpus, disk_gib=1,
                    ssh_forward_port=0, iso=inspection.path, disk=work/'target.qcow2',
                    variables=variables, firmware_selection=firmware, artifacts=case,
                    qemu_binary=binary, acceleration=accel, live_media=image, live_media_usb=True,
                ))
                try:
                    vm.create_disk()
                    vm.start(attach_iso=True)
                    boot_iso_with_debug_shell(vm.qmp, vm.serial, Architecture.AMD64,
                                              firmware_delay=delay, scratch_dir=case)
                    vm.serial.wait_for_shell(timeout)
                    result = vm.serial.run(r'''
set -eu
for attempt in $(seq 1 120); do
    if getent passwd live >/dev/null && pgrep -u "$(id -u live)" -x gnome-shell >/dev/null; then break; fi
    sleep 1
done
cat /proc/cmdline
test -s /run/anduinos-live/environment
grep -qx 'ANDUINOS_LIVE_USER=live' /run/anduinos-live/environment
test "$(systemctl show anduinos-live-session.service -p ConditionResult --value)" = yes
test "$(systemctl show anduinos-live-session.service -p Result --value)" = success
systemctl is-active --quiet anduinos-live-session.service
systemctl is-active --quiet gdm.service
getent passwd live
pgrep -a -u "$(id -u live)" -x gnome-shell
sessions=$(loginctl list-sessions --no-legend | awk '$3 == "live" {print $1}')
found=0
for session in $sessions; do
    test "$(loginctl show-session "$session" -p Active --value)" = yes || continue
    case "$(loginctl show-session "$session" -p Type --value)" in wayland|x11) found=1;; esac
done
test "$found" = 1
cat /run/anduinos-live/media-check.result
grep -qx 'status=passed' /run/anduinos-live/media-check.result
echo ISO_USB_DESKTOP_PASSED
''', timeout=timeout, check=False)
                    (case/'guest-evidence.txt').write_text(result.stdout)
                    vm.screenshot('desktop' if result.returncode == 0 else 'failure')
                    if result.returncode or 'ISO_USB_DESKTOP_PASSED' not in result.stdout:
                        raise TestFailure('ISO-mode Live login/integrity assertions failed; see guest-evidence.txt')
                    record['status'] = 'passed'
                except BaseException:
                    with contextlib.suppress(Exception):
                        vm.screenshot('failure')
                    raise
                finally:
                    vm.stop()
        except Exception as error:
            record['error'] = str(error)
        finally:
            record['seconds'] = time.monotonic()-begin
            records.append(record)
            summary = dict(schema_version=1, iso=str(inspection.path), iso_sha256=inspection.sha256,
                           scope='live-usb-iso-mode', results=records, feature_suites=[])
            (artifacts/'summary.json').write_text(json.dumps(summary, indent=2)+'\n')
            write_junit_report(summary, artifacts/'junit.xml')
        print(f"[ISO USB] {label}: {record['status']} {record['error']}", flush=True)
    print(f'[ISO USB] Evidence: {artifacts} ({time.monotonic()-started:.0f}s)', flush=True)
    return len(records) == 2 and all(r['status'] == 'passed' for r in records)
