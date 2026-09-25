"""ISO-mode USB regression: actual UEFI boot, Live identity and GNOME login."""
from __future__ import annotations

import json
import contextlib
import shutil
import tempfile
import time
from pathlib import Path

from PIL import Image

from framework.errors import ConfigurationError, TestFailure
from framework.firmware import resolve_firmware
from framework.grub import boot_iso_with_debug_shell
from framework.iso import volume_label
from framework.model import Architecture, Firmware, Network
from framework.qemu import QemuConfig, QemuVm, resolve_qemu
from framework.reporting import write_junit_report
from framework.usb_iso import prepare_iso_usb


USB_CASE_ID = 'iso-media'


def _labels(inspection) -> tuple[str, str]:
    default = volume_label(inspection.path).upper()[:11]
    return default, 'CUSTOM_USB' if default != 'CUSTOM_USB' else 'ALT_USB'


def live_usb_suite_checks(inspection) -> dict[str, tuple[str, ...]]:
    return {
        **{f'live-usb-iso-mode-{label}': ('uefi-boot', 'live-desktop-and-integrity')
           for label in _labels(inspection)},
        'live-usb-to-go-optical-rejected': ('warning-visible', 'power-off'),
    }


def _write_summary(inspection, artifacts: Path, records: list[dict], started: float,
                   dashboard) -> None:
    case = dashboard.case_result(USB_CASE_ID)
    suites = case['suites']
    actual = {item['id']: item for item in records}
    for suite in suites:
        fallback = ('TO_GO_OPTICAL_REJECTED' if suite['id'] == 'live-usb-to-go-optical-rejected'
                    else suite['id'].removeprefix('live-usb-iso-mode-'))
        suite['artifacts'] = actual.get(suite['id'], {}).get('artifacts', str(artifacts / fallback))
    summary = dict(schema_version=2, iso=str(inspection.path), iso_sha256=inspection.sha256,
                   scope='live-usb-iso-mode', results=[{
                       **case, 'seconds': case['seconds'] or time.monotonic()-started,
                       'artifacts': str(artifacts), 'suites': suites,
                   }])
    (artifacts/'summary.json').write_text(json.dumps(summary, indent=2)+'\n')
    write_junit_report(summary, artifacts/'junit.xml')


def run_live_usb(inspection, artifacts: Path, overrides, *, dashboard, timeout=600,
                 memory=4096, cpus=2, delay=2) -> bool:
    """AMD64 USB regressions and rejection of To Go on optical media."""
    if inspection.architecture is not Architecture.AMD64:
        raise ConfigurationError('Rufus ISO-mode boot regression currently requires AMD64')
    artifacts.mkdir(parents=True, exist_ok=False)
    started = time.monotonic()
    records = []
    firmware = resolve_firmware(Architecture.AMD64, Firmware.UEFI_NO_SECURE_BOOT, overrides)
    binary, accel = resolve_qemu(Architecture.AMD64)
    dashboard.begin(USB_CASE_ID)
    dashboard.phase(USB_CASE_ID, 'Testing ISO media boot paths')
    # Default FAT label and a user-selected label must both preserve the ABI.
    for label in _labels(inspection):
        case = artifacts / label
        case.mkdir()
        record = dict(id=f'live-usb-iso-mode-{label}', status='failed', seconds=0, error='')
        begin = time.monotonic()
        vm = None
        dashboard.begin_suite(USB_CASE_ID, record['id'])
        dashboard.suite_phase(USB_CASE_ID, record['id'], f'Booting FAT label {label}')
        dashboard.suite_check(USB_CASE_ID, record['id'], 'uefi-boot', 'running')
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
                    dashboard.suite_check(USB_CASE_ID, record['id'], 'uefi-boot', 'passed')
                    dashboard.suite_check(USB_CASE_ID, record['id'], 'live-desktop-and-integrity', 'running')
                    dashboard.suite_phase(USB_CASE_ID, record['id'], 'Checking Live desktop and media integrity')
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
                    dashboard.suite_check(USB_CASE_ID, record['id'], 'live-desktop-and-integrity', 'passed')
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
            record['artifacts'] = str(case)
            records.append(record)
            dashboard.complete_suite(USB_CASE_ID, record['id'], record['status'], record['seconds'], record['error'])
            _write_summary(inspection, artifacts, records, started, dashboard)
    case = artifacts / 'TO_GO_OPTICAL_REJECTED'
    case.mkdir()
    record = dict(id='live-usb-to-go-optical-rejected', status='failed', seconds=0, error='')
    begin = time.monotonic()
    vm = None
    dashboard.begin_suite(USB_CASE_ID, record['id'])
    dashboard.suite_phase(USB_CASE_ID, record['id'], 'Checking To Go rejection on optical ISO')
    dashboard.suite_check(USB_CASE_ID, record['id'], 'warning-visible', 'running')
    try:
        with tempfile.TemporaryDirectory(prefix='.optical-work-', dir=case) as directory:
            work = Path(directory)
            variables = work / 'vars.fd'
            shutil.copyfile(firmware.variables_template, variables)
            vm = QemuVm(QemuConfig(
                architecture=Architecture.AMD64, firmware=Firmware.UEFI_NO_SECURE_BOOT,
                network=Network.OFFLINE, memory_mib=memory, cpus=cpus, disk_gib=1,
                ssh_forward_port=0, iso=inspection.path, disk=work/'target.qcow2',
                variables=variables, firmware_selection=firmware, artifacts=case,
                qemu_binary=binary, acceleration=accel,
            ))
            try:
                vm.create_disk()
                vm.start(attach_iso=True)
                boot_iso_with_debug_shell(vm.qmp, vm.serial, Architecture.AMD64,
                                          firmware_delay=delay, menu_path=(1, 1),
                                          serial_debug=False, scratch_dir=case)
                # Boot unmodified, with the real screen console. A forced
                # serial console would invalidate this user-visible check.
                display_deadline = time.monotonic() + min(timeout, 180)
                while True:
                    if vm.process is not None and vm.process.poll() is not None:
                        raise TestFailure('QEMU stopped before the To Go rejection was recognized on the display')
                    warning_frame = vm.screenshot('unsupported-media')
                    with Image.open(warning_frame) as image:
                        screen = image.convert('RGB')
                        width, height = screen.size
                        # Exclude both the EFI/AnduinOS splash logos in the
                        # middle and the tiny HyperFluent icon at top left.
                        # A real text-VT warning starts in this upper band.
                        text_area = screen.crop((width * 12 // 100, 0,
                                                 width * 90 // 100, height * 30 // 100))
                        # The GRUB console renders this warning in gray (RGB
                        # 160 on the release ISO), not bright white.
                        if sum(min(pixel) >= 150 for pixel in text_area.get_flattened_data()) >= 100:
                            break
                    if time.monotonic() >= display_deadline:
                        raise TestFailure('To Go rejection is not visible on the display')
                    time.sleep(0.4)
                dashboard.suite_check(USB_CASE_ID, record['id'], 'warning-visible', 'passed')
                dashboard.suite_check(USB_CASE_ID, record['id'], 'power-off', 'running')
                dashboard.suite_phase(USB_CASE_ID, record['id'], 'Waiting for expected power-off')
                if vm.wait(timeout=45) != 0:
                    raise TestFailure('To Go rejection did not power off QEMU cleanly')
                dashboard.suite_check(USB_CASE_ID, record['id'], 'power-off', 'passed')
                record['status'] = 'passed'
            finally:
                vm.stop()
    except Exception as error:
        record['error'] = str(error)
    finally:
        record['seconds'] = time.monotonic()-begin
        record['artifacts'] = str(case)
        records.append(record)
        dashboard.complete_suite(USB_CASE_ID, record['id'], record['status'], record['seconds'], record['error'])
        _write_summary(inspection, artifacts, records, started, dashboard)
    passed = len(records) == 3 and all(r['status'] == 'passed' for r in records)
    error = '; '.join(r['error'] or r['id'] for r in records if r['status'] != 'passed')
    dashboard.complete(USB_CASE_ID, 'passed' if passed else 'failed',
                       time.monotonic()-started, error)
    _write_summary(inspection, artifacts, records, started, dashboard)
    return passed
