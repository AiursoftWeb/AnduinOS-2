"""Fast self-tests for the QEMU acceptance harness itself."""

from __future__ import annotations

import io
import signal
import socket
import subprocess
import tempfile
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from PIL import Image, ImageDraw

from iso_test.errors import ConfigurationError, TestFailure
from iso_test.assertions import _assert_release_contracts
from iso_test.dashboard import AcceptanceDashboard
from iso_test.cli import _termination_as_interrupt, _validate_disk_retention
from iso_test.firmware import FirmwareSelection
from iso_test.grub import (
    InstalledBootFiles,
    boot_installed_with_debug_shell,
    debug_kernel_arguments,
)
from iso_test.fixtures import _build_pe
from iso_test.iso import _parse_live_entries
from iso_test.model import (
    Architecture,
    Filesystem,
    Firmware,
    Network,
    SshPolicy,
    TestMatrix,
)
from iso_test.qemu import QemuConfig, QemuVm, _file_size_limiter
from iso_test.runner import (
    _GRAPHICAL_USER_SCRIPT,
    ScenarioRunner,
    scenario_check_ids,
    _assert_guest_ssh_stopped,
    _desktop_command,
    _parse_qmp_key_request,
    _ssh_login,
    _validate_installer_output,
)
from iso_test.serial import CommandResult
from iso_test.serial import SerialConsole
from iso_test.storage import (
    GIB,
    DiskStorage,
    assert_capacity,
    assert_disk_storage_ready,
    cleanup_disk_storage,
    prepare_disk_storage,
    select_disk_storage,
)
from iso_test.visual import assert_font_fixture, plymouth_match


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
        self.assertEqual(3, sum(item.rime for item in scenarios))
        self.assertEqual(1, sum(item.automatic_login for item in scenarios))
        self.assertEqual(1, sum(item.desktop_release_gate for item in scenarios))
        release_case = next(item for item in scenarios if item.desktop_release_gate)
        self.assertEqual("uefi-nosb-online-btrfs-ssh-enabled", release_case.id)
        self.assertTrue(release_case.rime)
        self.assertTrue(release_case.automatic_login)
        self.assertEqual(
            "Simplified Chinese (China Mainland)", matrix.defaults.live_grub_entry
        )
        self.assertEqual("zh_CN.UTF-8", matrix.defaults.live_locale)
        self.assertEqual("Asia/Shanghai", matrix.defaults.live_timezone)

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
                checks={"first-case": ("live-boot", "journal-health")},
                stream=stream,
                live=False,
            )
            dashboard.start()
            dashboard.begin("first-case")
            dashboard.check(
                "first-case", "live-boot", "running", "Booting original ISO"
            )
            dashboard.check(
                "first-case", "live-boot", "passed", "Live GNOME is ready"
            )
            dashboard.check(
                "first-case",
                "journal-health",
                "passed",
                "0 blockers; 3 known diagnostics",
            )
            dashboard.phase("first-case", "Booting original ISO")
            dashboard.complete("first-case", "passed", 65.0)
            dashboard.close()
        output = stream.getvalue()
        self.assertIn("NOT STARTED", output)
        self.assertIn("RUNNING", output)
        self.assertIn("PASSED", output)
        self.assertIn("first-case", output)
        self.assertIn("second-case", output)
        self.assertIn("first-case / live-boot", output)
        self.assertIn("first-case / journal-health", output)
        self.assertIn("3 known diagnostics", output)
        self.assertIn("Acceptance summary: 1/2 passed", output)

    def test_live_dashboard_renders_a_fixed_status_table(self):
        stream = io.StringIO()
        with tempfile.TemporaryDirectory() as directory:
            dashboard = AcceptanceDashboard(
                ("one",),
                iso=Path(directory) / "test-amd64.iso",
                architecture="amd64",
                artifacts=Path(directory) / "artifacts",
                checks={"one": ("live-boot", "desktop-file-dispatch")},
                stream=stream,
                live=True,
                refresh_seconds=60,
            )
            dashboard.start()
            dashboard.begin("one")
            dashboard.check("one", "live-boot", "passed", "Live GNOME is ready")
            dashboard.check(
                "one",
                "desktop-file-dispatch",
                "failed",
                "CPU-Z handler missing",
            )
            dashboard.complete("one", "failed", 2.0, "example failure")
            dashboard.close()
        output = stream.getvalue()
        self.assertIn("AnduinOS ISO Acceptance", output)
        self.assertIn("NOT STARTED", output)
        self.assertIn("RUNNING", output)
        self.assertIn("FAILED", output)
        self.assertIn("example failure", output)
        self.assertIn("Checks — one", output)
        self.assertIn("desktop-file-dispatch", output)
        self.assertIn("CPU-Z handler missing", output)

    def test_dashboard_rejects_an_undeclared_child_event(self):
        with tempfile.TemporaryDirectory() as directory:
            dashboard = AcceptanceDashboard(
                ("one",),
                iso=Path(directory) / "test-amd64.iso",
                architecture="amd64",
                artifacts=Path(directory) / "artifacts",
                checks={"one": ("live-boot",)},
                stream=io.StringIO(),
                live=False,
            )
            with self.assertRaisesRegex(ValueError, "undeclared check"):
                dashboard.check("one", "invented-check", "running")


class ScenarioCheckPlanTests(unittest.TestCase):
    def test_release_gate_declares_every_runtime_child_check(self):
        matrix = TestMatrix.load(ROOT / "matrix.json")
        scenario = next(item for item in matrix.scenarios if item.desktop_release_gate)
        checks = scenario_check_ids(scenario)
        self.assertEqual(len(checks), len(set(checks)))
        for identifier in (
            "live-boot",
            "installer-ui",
            "target-boot-files",
            "installed-boot",
            "installed-contracts",
            "automatic-login-policy",
            "cursor-theme",
            "font-rendering",
            "desktop-file-dispatch",
            "gnome-extensions",
            "spice-resolution",
            "snapshots-manager",
            "host-ssh",
            "journal-health",
            "plymouth-passive-boot",
        ):
            self.assertIn(identifier, checks)

    def test_smoke_plan_only_declares_the_check_it_executes(self):
        matrix = TestMatrix.load(ROOT / "matrix.json")
        self.assertEqual(
            ("live-boot",),
            scenario_check_ids(matrix.scenarios[0], smoke_only=True),
        )

    def test_real_check_boundary_emits_running_and_passed(self):
        scenario = SimpleNamespace(id="child-events")
        events = []
        runner = object.__new__(ScenarioRunner)
        runner._check_details = {}
        runner._check_states = {scenario.id: {"journal-health": "pending"}}
        runner.check_status = lambda *event: events.append(event)

        with runner._check(scenario, "journal-health"):
            runner._check_note(
                scenario,
                "journal-health",
                "0 blockers; 3 known diagnostics",
            )

        self.assertEqual("passed", runner._check_states[scenario.id]["journal-health"])
        self.assertEqual(
            ["running", "running", "passed"],
            [event[2] for event in events],
        )
        self.assertEqual("0 blockers; 3 known diagnostics", events[-1][3])

    def test_scenario_cannot_pass_with_a_phantom_pending_check(self):
        scenario = SimpleNamespace(id="incomplete")
        runner = object.__new__(ScenarioRunner)
        runner._check_states = {
            scenario.id: {"live-boot": "passed", "installer-ui": "pending"}
        }
        with self.assertRaisesRegex(TestFailure, "installer-ui=pending"):
            runner._assert_check_completion(scenario)


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
            self.assertIn("spicevmc,id=vdagent,name=vdagent", rendered)
            self.assertIn("com.redhat.spice.0", rendered)

    def test_q35_does_not_add_a_second_i8042_controller(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config = QemuConfig(
                architecture=Architecture.AMD64,
                firmware=Firmware.BIOS,
                network=Network.ONLINE,
                memory_mib=4096,
                cpus=2,
                disk_gib=20,
                ssh_forward_port=2222,
                iso=root / "test.iso",
                disk=root / "target.qcow2",
                variables=None,
                firmware_selection=None,
                artifacts=root / "artifacts",
                qemu_binary="qemu-system-x86_64",
                acceleration="tcg,thread=multi",
            )
            vm = QemuVm(config)
            vm._runtime = tempfile.TemporaryDirectory(prefix="anduinos-unit-")
            try:
                command = vm.command(attach_iso=True)
            finally:
                vm._runtime.cleanup()
                vm._runtime = None
        self.assertNotIn("i8042", command)
        self.assertIn("usb-kbd,bus=xhci.0", command)

    def test_qmp_cleanup_failure_cannot_skip_qemu_reaping(self):
        vm = QemuVm(SimpleNamespace())
        qmp = _FaultyQmp()
        process = _ReapProcess()
        serial = _FaultyClose()
        log = _FaultyClose()
        runtime = _FaultyRuntime()
        vm.qmp = qmp
        vm.process = process
        vm.serial = serial
        vm._log = log
        vm._runtime = runtime

        vm.stop()

        self.assertTrue(qmp.close_attempted)
        self.assertTrue(process.waited)
        self.assertTrue(serial.close_attempted)
        self.assertTrue(log.close_attempted)
        self.assertTrue(runtime.cleanup_attempted)
        self.assertIsNone(vm.qmp)
        self.assertIsNone(vm.process)
        self.assertIsNone(vm.serial)
        self.assertIsNone(vm._runtime)

    def test_iso_boot_uses_the_exact_selected_grub_region(self):
        grub = "\n".join(
            f'''menuentry "Language {index}" {{
 linux /casper/vmlinuz boot=casper locale=l{index}_XX.UTF-8 timezone=Zone/{index} systemd.timezone=Zone/{index} nopersistent quiet splash ---
}}'''
            for index in range(28)
        )
        entries = _parse_live_entries(grub)
        self.assertEqual(28, len(entries))
        self.assertEqual("l2_XX.UTF-8", entries[2].locale)
        self.assertEqual("Zone/2", entries[2].timezone)

    def test_iso_rejects_a_partial_regional_menu(self):
        with self.assertRaises(ConfigurationError):
            _parse_live_entries(
                '''menuentry "Only one" {
 linux /casper/vmlinuz boot=casper locale=en_US.UTF-8 timezone=Etc/UTC systemd.timezone=Etc/UTC
}'''
            )

    def test_cpu_z_fixture_has_the_product_validated_pe_shape(self):
        with tempfile.TemporaryDirectory() as directory:
            destination = Path(directory) / "cpu-z.exe"
            _build_pe(destination)
            content = destination.read_bytes()
        self.assertEqual(b"MZ", content[:2])
        offset = int.from_bytes(content[60:64], "little")
        self.assertGreaterEqual(offset, 64)
        self.assertEqual(b"PE\0\0", content[offset : offset + 4])

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

    def test_semantic_file_activation_enter_request_is_parsed(self):
        self.assertEqual(
            ("open-fixture-ret", "ret"),
            _parse_qmp_key_request(
                '{"event": "qmp-key", "request": "open-fixture-ret", "key": "ret"}'
            ),
        )


class SerialTransportTests(unittest.TestCase):
    def test_large_fixture_upload_handles_nonblocking_backpressure(self):
        left, right = socket.socketpair()
        left.setblocking(False)
        left.setsockopt(socket.SOL_SOCKET, socket.SO_SNDBUF, 4096)
        payload = b"A" * (2 * 1024 * 1024)
        received = bytearray()

        def consume():
            while len(received) < len(payload):
                chunk = right.recv(65536)
                if not chunk:
                    break
                received.extend(chunk)

        thread = threading.Thread(target=consume)
        thread.start()
        console = SerialConsole(Path("unused"), Path("unused"), timeout=10)
        console._socket = left
        try:
            console._send(payload)
            left.shutdown(socket.SHUT_WR)
            thread.join(timeout=10)
        finally:
            left.close()
            right.close()
        self.assertFalse(thread.is_alive())
        self.assertEqual(payload, bytes(received))

    def test_large_upload_is_split_into_confirmed_tty_sized_commands(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "fixture.AppImage"
            source.write_bytes(b"X" * (1024 * 1024))
            console = _UploadCaptureConsole()
            console.upload(source, "/tmp/fixture.AppImage", 0o755)
        self.assertGreater(len(console.scripts), 20)
        self.assertLess(max(map(len, console.scripts)), 70000)
        self.assertTrue(console.scripts[0].startswith(": > "))
        self.assertIn("chmod 755", console.scripts[-1])
        self.assertIn("mv ", console.scripts[-1])


class VisualOracleTests(unittest.TestCase):
    def test_font_fixture_requires_green_pistol_and_visible_chinese(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            screenshot = root / "font.ppm"
            image = Image.new("RGB", (800, 600), "white")
            draw = ImageDraw.Draw(image)
            draw.rectangle((330, 100, 470, 230), fill=(20, 190, 80))
            draw.rectangle((250, 420, 550, 470), fill=(20, 20, 20))
            image.save(screenshot)
            assert_font_fixture(screenshot, root / "analysis.json")
            self.assertTrue((root / "analysis.json").is_file())

    def test_font_fixture_rejects_monochrome_pistol(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            screenshot = root / "font.ppm"
            image = Image.new("RGB", (800, 600), "white")
            ImageDraw.Draw(image).rectangle(
                (250, 420, 550, 470), fill=(20, 20, 20)
            )
            image.save(screenshot)
            with self.assertRaises(TestFailure):
                assert_font_fixture(screenshot, root / "analysis.json")

    def test_plymouth_oracle_finds_bottom_center_watermark(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            watermark = Image.new("RGBA", (120, 30), (0, 0, 0, 0))
            draw = ImageDraw.Draw(watermark)
            draw.rectangle((0, 0, 35, 29), fill=(20, 140, 240, 255))
            draw.rectangle((42, 5, 119, 24), fill=(255, 255, 255, 255))
            watermark_path = root / "watermark.png"
            watermark.save(watermark_path)
            frame = Image.new("RGB", (640, 480), "black")
            frame.paste(watermark, ((640 - 120) // 2, 420), watermark)
            frame_path = root / "frame.ppm"
            frame.save(frame_path)
            self.assertTrue(plymouth_match(frame_path, watermark_path)["matched"])

    def test_plymouth_oracle_rejects_unbranded_frame(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            watermark = Image.new("RGBA", (120, 30), (255, 255, 255, 255))
            watermark_path = root / "watermark.png"
            watermark.save(watermark_path)
            frame_path = root / "frame.ppm"
            Image.new("RGB", (640, 480), "black").save(frame_path)
            self.assertFalse(plymouth_match(frame_path, watermark_path)["matched"])


class ReleaseGateWiringTests(unittest.TestCase):
    def test_graphical_user_probe_excludes_display_manager_accounts(self):
        self.assertIn("gdm-greeter", _GRAPHICAL_USER_SCRIPT)
        self.assertIn("/usr/sbin/nologin", _GRAPHICAL_USER_SCRIPT)
        self.assertIn("/bin/false", _GRAPHICAL_USER_SCRIPT)

    def test_desktop_command_quotes_nested_shell_in_both_lifecycle_modes(self):
        payload = """set -euo pipefail
value=$(printf '%s\\n' \"nested quotes\")
test \"$value\" = 'nested quotes'
"""
        for managed in (False, True):
            command = _desktop_command(
                "anduinostest",
                ("bash", "-lc", payload),
                managed=managed,
            )
            parsed = subprocess.run(
                ("bash", "-n"),
                input=command,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=False,
            )
            self.assertEqual(0, parsed.returncode, parsed.stderr)
            self.assertIn("nested quotes", command)

    def test_installed_release_script_contains_every_declared_command_contract(self):
        with tempfile.TemporaryDirectory() as directory:
            console = _CaptureConsole()
            _assert_release_contracts(console, "anduinostest", Path(directory))
            script = console.scripts[0]
        self.assertIn("fs.inotify.max_user_instances", script)
        self.assertIn("xdg-mime query default", script)
        self.assertIn("org.gnome.Loupe.desktop", script)
        self.assertIn("io.github.celluloid_player.Celluloid.desktop", script)
        self.assertIn("gnome-software-local-file-packagekit.desktop", script)
        self.assertIn("com.anduinos.ExeRunner.desktop", script)
        self.assertIn("application/vnd.microsoft.portable-executable", script)
        self.assertIn("why_output=$(why", script)
        self.assertIn("Noto Sans CJK SC", script)
        self.assertIn("Twemoji", script)
        self.assertIn("/etc/alternatives/default.plymouth", script)

    def test_desktop_gate_calls_every_implemented_runtime_check(self):
        source = Path("tests/iso_test/runner.py").read_text(encoding="utf-8")
        for method in (
            "_exercise_font_rendering",
            "_exercise_desktop_file_dispatch",
            "_assert_gnome_extensions",
            "_exercise_dynamic_resolution",
            "_assert_journal_health",
            "_assert_passive_plymouth_boot",
        ):
            self.assertGreaterEqual(source.count(f"self.{method}("), 1, method)

    def test_passed_and_failed_target_disks_are_discarded_by_default(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            runner = object.__new__(ScenarioRunner)
            runner.options = SimpleNamespace(
                keep_passed_disk=False,
                keep_failed_disk=False,
                disk_storage=DiskStorage(root, "filesystem", "unit test"),
            )
            for passed in (True, False):
                disk = root / "target.qcow2"
                disk.write_bytes(b"disposable")
                vm = SimpleNamespace(
                    running=False,
                    config=SimpleNamespace(disk=disk),
                )
                runner._finalize_disk(vm, root, passed=passed)
                self.assertFalse(disk.exists())
                evidence = (root / "target-disk-retention.txt").read_text(
                    encoding="utf-8"
                )
                self.assertIn("discarded", evidence)
                self.assertIn("passed" if passed else "failed", evidence)

    def test_explicit_single_debug_disk_can_be_retained(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            disk = root / "target.qcow2"
            disk.write_bytes(b"debug")
            runner = object.__new__(ScenarioRunner)
            runner.options = SimpleNamespace(
                keep_passed_disk=False,
                keep_failed_disk=True,
                disk_storage=DiskStorage(root, "filesystem", "unit test"),
            )
            vm = SimpleNamespace(running=False, config=SimpleNamespace(disk=disk))
            runner._finalize_disk(vm, root, passed=False)
            self.assertTrue(disk.exists())
            self.assertIn(
                "retained",
                (root / "target-disk-retention.txt").read_text(encoding="utf-8"),
            )

    @patch("iso_test.runner.assert_disk_storage_ready")
    def test_keyboard_interrupt_stops_vm_and_discards_partial_disk(self, _capacity):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            disk = root / "interrupt" / "target.qcow2"
            vm = _CleanupVm(disk)
            runner = object.__new__(ScenarioRunner)
            runner.options = SimpleNamespace(
                artifacts_root=root,
                disk_storage=DiskStorage(root, "filesystem", "unit test"),
                disk_gib=40,
                memory_mib=8192,
                free_space_reserve_gib=10,
                smoke_only=False,
                keep_passed_disk=False,
                keep_failed_disk=False,
            )
            runner._create_vm = lambda _scenario, _artifacts: vm
            runner._write_manifest = lambda *_args: None

            def interrupt(*_args):
                raise KeyboardInterrupt

            runner._run_live_phase = interrupt
            interrupted_scenario = SimpleNamespace(
                id="interrupt",
                mok_enrollment=False,
                desktop_release_gate=False,
                snapshots_manager=False,
                ssh=SshPolicy.DISABLED,
            )
            with self.assertRaises(KeyboardInterrupt):
                runner.run(interrupted_scenario)
            self.assertTrue(vm.stopped)
            self.assertFalse(disk.exists())
            self.assertIn(
                "failed target disk discarded",
                (root / "interrupt" / "target-disk-retention.txt").read_text(
                    encoding="utf-8"
                ),
            )


class HostStorageSafetyTests(unittest.TestCase):
    @patch("iso_test.storage.shutil.disk_usage")
    def test_capacity_budgets_the_full_virtual_disk_and_reserve(self, disk_usage):
        disk_usage.return_value = SimpleNamespace(free=55 * GIB)
        with tempfile.TemporaryDirectory() as directory:
            capacity = assert_capacity(Path(directory), 40, 10)
        self.assertEqual(50 * GIB, capacity.required_bytes)
        self.assertEqual(55 * GIB, capacity.free_bytes)

    @patch("iso_test.storage.shutil.disk_usage")
    def test_capacity_fails_before_qemu_when_host_space_is_low(self, disk_usage):
        disk_usage.return_value = SimpleNamespace(free=21 * GIB)
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(
                ConfigurationError,
                r"21\.0 GiB is free.*requires 50\.0 GiB",
            ):
                assert_capacity(Path(directory), 40, 10)

    @patch("iso_test.storage.shutil.disk_usage")
    @patch("iso_test.storage._filesystem_type", return_value="tmpfs")
    @patch("iso_test.storage._read_mem_available", return_value=32 * GIB)
    def test_auto_selects_and_cleans_safe_generic_tmpfs(
        self,
        _memory,
        _filesystem,
        disk_usage,
    ):
        disk_usage.return_value = SimpleNamespace(free=12 * GIB)
        with tempfile.TemporaryDirectory() as directory:
            candidate = Path(directory)
            with patch(
                "iso_test.storage._ramdisk_candidates",
                return_value=(candidate,),
            ):
                storage = select_disk_storage(
                    Path("/persistent/results/run"),
                    memory_mib=8192,
                )
            self.assertTrue(storage.is_ramdisk)
            self.assertEqual(12 * GIB, storage.qcow_limit_bytes)
            self.assertEqual(candidate, storage.root.parents[1])
            prepare_disk_storage(storage)
            (storage.root / "case").mkdir()
            (storage.root / "case" / "target.qcow2").write_bytes(b"guest")
            cleanup_disk_storage(storage)
            self.assertFalse(storage.root.exists())

    @patch("iso_test.storage.shutil.disk_usage")
    @patch("iso_test.storage._filesystem_type", return_value="tmpfs")
    @patch("iso_test.storage._read_mem_available", return_value=23 * GIB)
    def test_ramdisk_recheck_budgets_hard_qcow_limit_not_whole_mount(
        self,
        _memory,
        _filesystem,
        disk_usage,
    ):
        disk_usage.return_value = SimpleNamespace(free=15 * GIB)
        storage = DiskStorage(
            Path("/dev/shm/private/run"),
            "ramdisk",
            "unit test",
            memory_available_bytes=23 * GIB,
            ramdisk_free_bytes=15 * GIB,
            qcow_limit_bytes=12 * GIB,
        )
        capacity = assert_disk_storage_ready(
            storage,
            disk_gib=40,
            filesystem_reserve_gib=10,
            memory_mib=8192,
        )
        self.assertEqual(12 * GIB, capacity.required_bytes)

    def test_qemu_child_file_size_limit_is_enforced_by_kernel(self):
        with tempfile.TemporaryDirectory() as directory:
            destination = Path(directory) / "too-large"
            result = subprocess.run(
                (
                    "python3",
                    "-c",
                    "from pathlib import Path; "
                    f"Path({str(destination)!r}).write_bytes(b'x' * 2097152)",
                ),
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=False,
                preexec_fn=_file_size_limiter(1024 * 1024),
            )
        self.assertNotEqual(0, result.returncode)

    @patch("iso_test.storage._read_mem_available", return_value=16 * GIB)
    def test_auto_falls_back_when_available_memory_is_not_above_threshold(
        self,
        _memory,
    ):
        artifacts = Path("/persistent/results/run")
        storage = select_disk_storage(artifacts, memory_mib=8192)
        self.assertFalse(storage.is_ramdisk)
        self.assertEqual(artifacts, storage.root)
        self.assertIn("not above", storage.reason)

    @patch("iso_test.storage.shutil.disk_usage")
    @patch("iso_test.storage._filesystem_type", return_value="tmpfs")
    @patch("iso_test.storage._read_mem_available", return_value=64 * GIB)
    def test_ci_sized_tmpfs_falls_back_to_filesystem(
        self,
        _memory,
        _filesystem,
        disk_usage,
    ):
        disk_usage.return_value = SimpleNamespace(free=64 * 1024**2)
        with tempfile.TemporaryDirectory() as directory:
            with patch(
                "iso_test.storage._ramdisk_candidates",
                return_value=(Path(directory),),
            ):
                storage = select_disk_storage(
                    Path("/persistent/results/run"),
                    memory_mib=8192,
                )
        self.assertFalse(storage.is_ramdisk)
        self.assertIn("no writable tmpfs", storage.reason)

    @patch("iso_test.storage._read_mem_available", return_value=64 * GIB)
    def test_retained_debug_disk_always_uses_persistent_storage(self, _memory):
        artifacts = Path("/persistent/results/run")
        storage = select_disk_storage(
            artifacts,
            memory_mib=8192,
            retain_disk=True,
        )
        self.assertFalse(storage.is_ramdisk)
        self.assertIn("retention", storage.reason)

    @patch("iso_test.storage._read_mem_available", return_value=8 * GIB)
    def test_forced_ramdisk_fails_closed_when_memory_is_low(self, _memory):
        with self.assertRaisesRegex(ConfigurationError, "requested but unavailable"):
            select_disk_storage(
                Path("/persistent/results/run"),
                memory_mib=8192,
                mode="ramdisk",
            )

    def test_retention_requires_exactly_one_explicit_case(self):
        unsafe = SimpleNamespace(
            keep_passed_disk=False,
            keep_failed_disk=True,
            cases=[],
        )
        with self.assertRaisesRegex(ConfigurationError, "exactly one explicit"):
            _validate_disk_retention(unsafe, (object(), object()))
        safe = SimpleNamespace(
            keep_passed_disk=False,
            keep_failed_disk=True,
            cases=["one"],
        )
        _validate_disk_retention(safe, (object(),))

    def test_sigterm_is_converted_to_cleanup_interrupt_and_restored(self):
        original = signal.getsignal(signal.SIGTERM)
        with _termination_as_interrupt():
            handler = signal.getsignal(signal.SIGTERM)
            self.assertTrue(callable(handler))
            with self.assertRaises(KeyboardInterrupt):
                handler(signal.SIGTERM, None)
        self.assertIs(original, signal.getsignal(signal.SIGTERM))


class _RecordingQmp:
    def __init__(self):
        self.keys = []
        self.typed = []

    def send_key(self, key, hold_ms=50):
        self.keys.append(key)

    def type_text(self, value):
        self.typed.append(value)


class _CleanupVm:
    def __init__(self, disk: Path):
        self.config = SimpleNamespace(disk=disk)
        self.running = False
        self.stopped = False

    def create_disk(self):
        self.config.disk.parent.mkdir(parents=True, exist_ok=True)
        self.config.disk.write_bytes(b"partial guest")
        self.running = True

    def stop(self):
        self.running = False
        self.stopped = True


class _FaultyQmp:
    def __init__(self):
        self.close_attempted = False

    def quit(self):
        raise RuntimeError("injected QMP failure")

    def close(self):
        self.close_attempted = True
        raise RuntimeError("injected QMP close failure")


class _ReapProcess:
    def __init__(self):
        self.returncode = None
        self.waited = False

    def poll(self):
        return self.returncode

    def wait(self, timeout):
        self.waited = True
        self.returncode = 0
        return 0


class _FaultyClose:
    def __init__(self):
        self.close_attempted = False

    def close(self):
        self.close_attempted = True
        raise OSError("injected close failure")


class _FaultyRuntime:
    def __init__(self):
        self.cleanup_attempted = False

    def cleanup(self):
        self.cleanup_attempted = True
        raise OSError("injected runtime cleanup failure")


class _ResultConsole:
    def __init__(self, result):
        self.result = result

    def run(self, *_args, **_options):
        return self.result


class _CaptureConsole:
    def __init__(self):
        self.scripts = []

    def run(self, script, **_options):
        self.scripts.append(script)
        return CommandResult("", 0)


class _UploadCaptureConsole(SerialConsole):
    def __init__(self):
        self.scripts = []

    def run(self, script, **_options):
        self.scripts.append(script)
        return CommandResult("", 0)


class _RecordingConsole:
    def __init__(self):
        self.waited = []

    def wait_for_text(self, value, timeout):
        self.waited.append((value, timeout))


if __name__ == "__main__":
    unittest.main()
