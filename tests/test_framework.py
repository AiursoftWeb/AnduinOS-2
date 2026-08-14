"""Fast self-tests for the QEMU acceptance harness itself."""

from __future__ import annotations

import io
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from iso_test.errors import ConfigurationError, TestFailure
from iso_test.dashboard import AcceptanceDashboard
from iso_test.firmware import FirmwareSelection
from iso_test.grub import (
    InstalledBootFiles,
    boot_installed_with_debug_shell,
    debug_kernel_arguments,
)
from iso_test.model import (
    Architecture,
    Filesystem,
    Firmware,
    Network,
    SshPolicy,
    TestMatrix,
)
from iso_test.qemu import QemuConfig, QemuVm
from iso_test.runner import (
    _assert_guest_ssh_stopped,
    _parse_qmp_key_request,
    _ssh_login,
    _validate_installer_output,
)
from iso_test.serial import CommandResult


ROOT = Path(__file__).parent


class MatrixTests(unittest.TestCase):
    def test_matrix_has_the_intended_ten_unique_scenarios(self):
        matrix = TestMatrix.load(ROOT / "matrix.json")
        self.assertEqual(10, len(matrix.scenarios))
        self.assertEqual(10, len({item.id for item in matrix.scenarios}))
        self.assertEqual(
            {
                "bios-offline-btrfs",
                "bios-online-btrfs",
                "bios-online-ext4",
                "uefi-nosb-offline-btrfs",
                "uefi-nosb-online-btrfs-ssh-enabled",
                "uefi-nosb-online-btrfs-ssh-toggle",
                "uefi-nosb-offline-ext4",
                "uefi-sb-offline-btrfs",
                "uefi-sb-online-btrfs",
                "uefi-sb-online-ext4",
            },
            {item.id for item in matrix.scenarios},
        )
        self.assertEqual(10, len(matrix.select(Architecture.AMD64)))
        self.assertEqual(7, len(matrix.select(Architecture.ARM64)))

        scenarios = matrix.scenarios
        self.assertEqual(3, sum(item.firmware is Firmware.BIOS for item in scenarios))
        self.assertEqual(
            3,
            sum(item.firmware is Firmware.UEFI_SECURE_BOOT for item in scenarios),
        )
        self.assertEqual(3, sum(item.filesystem is Filesystem.EXT4 for item in scenarios))
        self.assertEqual(1, sum(item.ssh is SshPolicy.ENABLED for item in scenarios))
        self.assertEqual(1, sum(item.ssh is SshPolicy.TOGGLE for item in scenarios))
        self.assertEqual(4, sum(item.network is Network.OFFLINE for item in scenarios))

    def test_unknown_case_is_rejected(self):
        matrix = TestMatrix.load(ROOT / "matrix.json")
        with self.assertRaises(ConfigurationError):
            matrix.select(Architecture.AMD64, ("does-not-exist",))


class DashboardTests(unittest.TestCase):
    def test_plain_dashboard_reports_all_state_transitions(self):
        stream = io.StringIO()
        with tempfile.TemporaryDirectory() as directory:
            dashboard = AcceptanceDashboard(
                ("first-case", "second-case"),
                iso=Path(directory) / "test-amd64.iso",
                architecture="amd64",
                artifacts=Path(directory) / "artifacts",
                stream=stream,
                live=False,
            )
            dashboard.start()
            dashboard.begin("first-case")
            dashboard.phase("first-case", "Booting original ISO")
            dashboard.complete("first-case", "passed", 65.0)
            dashboard.close()
        output = stream.getvalue()
        self.assertIn("NOT STARTED", output)
        self.assertIn("RUNNING", output)
        self.assertIn("PASSED", output)
        self.assertIn("first-case", output)
        self.assertIn("second-case", output)
        self.assertIn("Acceptance summary: 1/2 passed", output)

    def test_live_dashboard_renders_a_fixed_status_table(self):
        stream = io.StringIO()
        with tempfile.TemporaryDirectory() as directory:
            dashboard = AcceptanceDashboard(
                ("one",),
                iso=Path(directory) / "test-amd64.iso",
                architecture="amd64",
                artifacts=Path(directory) / "artifacts",
                stream=stream,
                live=True,
                refresh_seconds=60,
            )
            dashboard.start()
            dashboard.begin("one")
            dashboard.complete("one", "failed", 2.0, "example failure")
            dashboard.close()
        output = stream.getvalue()
        self.assertIn("AnduinOS ISO Acceptance", output)
        self.assertIn("NOT STARTED", output)
        self.assertIn("RUNNING", output)
        self.assertIn("FAILED", output)
        self.assertIn("example failure", output)


class BootContractTests(unittest.TestCase):
    def test_debug_tty_is_architecture_specific(self):
        self.assertIn("ttyS0", debug_kernel_arguments(Architecture.AMD64))
        self.assertIn("ttyAMA0", debug_kernel_arguments(Architecture.ARM64))
        self.assertIn("systemd.debug_shell", debug_kernel_arguments(Architecture.ARM64))

    def test_arm_qemu_uses_neoverse_and_virtio_scsi(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            code = root / "code.fd"
            variables = root / "vars.fd"
            code.touch()
            variables.touch()
            config = QemuConfig(
                architecture=Architecture.ARM64,
                firmware=Firmware.UEFI_NO_SECURE_BOOT,
                network=Network.ONLINE,
                memory_mib=4096,
                cpus=2,
                disk_gib=20,
                ssh_forward_port=2222,
                iso=root / "test.iso",
                disk=root / "target.qcow2",
                variables=variables,
                firmware_selection=FirmwareSelection(code, variables),
                artifacts=root / "artifacts",
                qemu_binary="qemu-system-aarch64",
                acceleration="tcg,thread=multi",
            )
            vm = QemuVm(config)
            vm._runtime = tempfile.TemporaryDirectory(prefix="anduinos-unit-")
            try:
                rendered = " ".join(vm.command(attach_iso=True))
            finally:
                vm._runtime.cleanup()
                vm._runtime = None
            self.assertIn("neoverse-n1", rendered)
            self.assertNotIn("-cpu max", rendered)
            self.assertIn("virtio-scsi-pci", rendered)
            self.assertIn("scsi-cd", rendered)

    @patch("iso_test.grub.time.sleep")
    def test_installed_btrfs_boot_uses_discovered_versioned_files(self, _sleep):
        qmp = _RecordingQmp()
        boot_installed_with_debug_shell(
            qmp,
            _RecordingConsole(),
            Architecture.AMD64,
            Filesystem.BTRFS,
            InstalledBootFiles(
                "/@root/boot/vmlinuz-7.0.0-29-generic",
                "/@root/boot/initrd.img-7.0.0-29-generic",
            ),
            firmware_delay=1,
        )
        typed = "\n".join(qmp.typed)
        self.assertIn("/@root/boot/vmlinuz-7.0.0-29-generic", typed)
        self.assertIn("rootflags=subvol=@root", typed)
        self.assertIn("/@root/boot/initrd.img-7.0.0-29-generic", typed)
        self.assertEqual("boot", qmp.typed[-1])


class SshContractTests(unittest.TestCase):
    @patch("iso_test.runner.subprocess.run")
    def test_password_login_uses_forced_ephemeral_askpass(self, run):
        def complete(command, **options):
            environment = options["env"]
            askpass = Path(environment["SSH_ASKPASS"])
            self.assertTrue(askpass.is_file())
            self.assertTrue(askpass.stat().st_mode & 0o100)
            self.assertEqual("force", environment["SSH_ASKPASS_REQUIRE"])
            self.assertEqual(
                "AnduinOS-Test-123!",
                environment["ANDUINOS_ACCEPTANCE_SSH_PASSWORD"],
            )
            self.assertIn("NumberOfPasswordPrompts=1", " ".join(command))
            self.assertIn("-F /dev/null", " ".join(command))
            self.assertIn("ControlMaster=no", " ".join(command))
            self.assertIn("ControlPersist=no", " ".join(command))
            self.assertIn("ControlPath=none", " ".join(command))
            return __import__("subprocess").CompletedProcess(
                command,
                0,
                stdout="anduinostest\n",
            )

        run.side_effect = complete
        output = _ssh_login(
            2222,
            "anduinostest",
            "AnduinOS-Test-123!",
            should_succeed=True,
        )
        self.assertEqual("anduinostest\n", output)

    def test_gnome_off_requires_units_and_listener_to_stop(self):
        with tempfile.TemporaryDirectory() as directory:
            artifacts = Path(directory)
            console = _ResultConsole(
                CommandResult(
                    "ssh.socket enabled=disabled active=inactive\n"
                    "ssh.service enabled=disabled active=inactive\n"
                    "listeners=\n",
                    0,
                )
            )
            _assert_guest_ssh_stopped(console, artifacts)
            self.assertTrue(
                (artifacts / "installed-ssh-after-gnome-off.txt").is_file()
            )

    def test_gnome_off_rejects_a_remaining_listener(self):
        with tempfile.TemporaryDirectory() as directory:
            artifacts = Path(directory)
            console = _ResultConsole(
                CommandResult(
                    "ssh.socket enabled=disabled active=inactive\n"
                    "ssh.service enabled=disabled active=active\n"
                    "listeners=LISTEN 0 4096 0.0.0.0:22\n",
                    1,
                )
            )
            with self.assertRaises(TestFailure):
                _assert_guest_ssh_stopped(console, artifacts)


class InstallerTranscriptTests(unittest.TestCase):
    DRIVER_COMMAND = (
        "$ chroot /target ubuntu-drivers install --no-oem --package-list "
        "/run/anduinos-installer-drivers"
    )

    def test_online_driver_flow_requires_command_and_no_driver_result(self):
        _validate_installer_output(
            self.DRIVER_COMMAND
            + "\nAll the available drivers are already installed.\n",
            expects_driver_flow=True,
        )

    def test_online_driver_flow_rejects_a_green_step_without_command(self):
        with self.assertRaises(TestFailure):
            _validate_installer_output(
                "Install hardware drivers succeeded\n",
                expects_driver_flow=True,
            )

    def test_installer_transcript_rejects_fatal_markers(self):
        with self.assertRaises(TestFailure):
            _validate_installer_output(
                "Fatal step: install-bootloader\n",
                expects_driver_flow=False,
            )


class QmpSemanticKeyboardTests(unittest.TestCase):
    def test_guest_keyboard_request_is_parsed_from_serial_prefix(self):
        self.assertEqual(
            ("drivers-2-spc", "spc"),
            _parse_qmp_key_request(
                'debug-prefix {"event": "qmp-key", '
                '"request": "drivers-2-spc", "key": "spc"}'
            ),
        )

    def test_unrelated_or_incomplete_serial_lines_are_ignored(self):
        self.assertIsNone(_parse_qmp_key_request('{"event": "page"}'))
        self.assertIsNone(
            _parse_qmp_key_request('{"event": "qmp-key", "key": "tab"}')
        )


class _RecordingQmp:
    def __init__(self):
        self.keys = []
        self.typed = []

    def send_key(self, key, hold_ms=50):
        self.keys.append(key)

    def type_text(self, value):
        self.typed.append(value)


class _ResultConsole:
    def __init__(self, result):
        self.result = result

    def run(self, *_args, **_options):
        return self.result


class _RecordingConsole:
    def __init__(self):
        self.waited = []

    def wait_for_text(self, value, timeout):
        self.waited.append((value, timeout))


if __name__ == "__main__":
    unittest.main()
