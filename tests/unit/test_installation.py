"""Installation, firmware, storage, and Wi-Fi tests."""

from unit.support import *  # noqa: F403
class WifiMigrationOracleTests(unittest.TestCase):
    _UUID = "a356839e-2ef2-4f56-abb0-294873676e41"

    def _good_evidence(self):
        return {
            "schema_version": 1,
            "auto_reconnected": True,
            "ssid": WIFI_LAB_SSID,
            "uuid": self._UUID,
            "device": "wlan0",
            "ipv4": "10.77.0.42/24",
            "gateway_reachable": True,
            "ethernet_carrier": "down",
            "profile_path": f"/etc/netplan/90-NM-{self._UUID}.yaml",
            "profile_regular": True,
            "profile_symlink": False,
            "profile_uid": 0,
            "profile_gid": 0,
            "profile_mode": "0600",
            "netplan_mapping": "valid",
        }

    def test_good_reconnect_evidence_passes(self):
        validate_reconnect_evidence(
            self._good_evidence(),
            expected_ssid=WIFI_LAB_SSID,
            expected_uuid=self._UUID,
        )

    def test_generated_wifi_guest_scripts_are_valid_bash(self):
        password = "unit-test-wifi-password"
        scripts = (
            WifiLab(password=password)._setup_script(),
            _live_profile_script(WIFI_LAB_SSID, "wlan0"),
            _installed_reconnect_script(WIFI_LAB_SSID, self._UUID),
        )
        self.assertNotIn(password, scripts[0].splitlines()[0])
        for script in scripts:
            result = subprocess.run(
                ("bash", "-n"),
                input=script,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=False,
            )
            self.assertEqual(0, result.returncode, result.stderr)

    def test_fault_injection_rejects_every_wifi_safety_boundary(self):
        faults = {
            "did-not-autoconnect": {"auto_reconnected": False},
            "wrong-ssid": {"ssid": "Evil-Twin"},
            "wrong-uuid": {"uuid": "b356839e-2ef2-4f56-abb0-294873676e41"},
            "no-dhcp": {"ipv4": "192.0.2.42/24"},
            "gateway-dead": {"gateway_reachable": False},
            "ethernet-fallback": {"ethernet_carrier": "up"},
            "wrong-profile": {"profile_path": "/etc/netplan/wrong.yaml"},
            "profile-symlink": {"profile_symlink": True},
            "profile-not-regular": {"profile_regular": False},
            "profile-owner": {"profile_uid": 1000},
            "profile-group": {"profile_gid": 1000},
            "profile-mode": {"profile_mode": "0644"},
            "mapping-invalid": {"netplan_mapping": "invalid"},
        }
        for label, mutation in faults.items():
            with self.subTest(label=label):
                evidence = self._good_evidence()
                evidence.update(mutation)
                with self.assertRaises(TestFailure):
                    validate_reconnect_evidence(
                        evidence,
                        expected_ssid=WIFI_LAB_SSID,
                        expected_uuid=self._UUID,
                    )

    def test_wifi_secret_artifact_audit_detects_chunk_boundary_leak(self):
        secret = "0123456789abcdef0123456789abcdef"
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            clean = root / "clean.bin"
            clean.write_bytes(b"safe evidence")
            assert_secret_absent(root, secret)
            leaked = root / "serial.log"
            leaked.write_bytes(
                b"A" * (1024 * 1024 - 7)
                + secret.encode("ascii")
                + b"tail"
            )
            with self.assertRaisesRegex(TestFailure, "serial.log"):
                assert_secret_absent(root, secret)

    def test_wifi_secret_artifact_audit_handles_one_byte_secrets(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "clean.bin").write_bytes(b"safe evidence")
            assert_secret_absent(root, "Z")
            (root / "leaked.bin").write_bytes(b"safe evidenceZ")
            with self.assertRaisesRegex(TestFailure, "leaked.bin"):
                assert_secret_absent(root, "Z")


class BootContractTests(unittest.TestCase):
    _GOOD_KERNEL_HASH = "a" * 64

    def test_debug_tty_is_architecture_specific(self):
        self.assertIn("ttyS0", debug_kernel_arguments(Architecture.AMD64))
        self.assertIn("ttyAMA0", debug_kernel_arguments(Architecture.ARM64))
        self.assertIn("systemd.debug_shell", debug_kernel_arguments(Architecture.ARM64))

    def test_grub_synchronization_follows_the_available_console(self):
        self.assertTrue(uses_graphical_grub_synchronization(Architecture.AMD64))
        self.assertFalse(uses_graphical_grub_synchronization(Architecture.ARM64))

    def test_live_region_failure_preserves_observed_values_before_rejecting(self):
        console = Mock()
        console.run.return_value = CommandResult(
            "localectl-status=0\n"
            "timedatectl-status=0\n"
            "system-locale=C.UTF-8\n"
            "timezone=Etc/UTC\n",
            1,
        )
        with tempfile.TemporaryDirectory() as directory:
            evidence = Path(directory)
            with self.assertRaisesRegex(TestFailure, "live-locale-timezone"):
                assert_live_region(
                    console,
                    "zh_CN.UTF-8",
                    "Asia/Shanghai",
                    evidence,
                )
            self.assertIn(
                "system-locale=C.UTF-8",
                (evidence / "live-locale-timezone.txt").read_text(
                    encoding="utf-8"
                ),
            )
        script = console.run.call_args.args[0]
        self.assertNotIn("set -e", script)
        self.assertLess(
            script.index("printf 'system-locale="),
            script.index('test "$system_locale"'),
        )

    def test_live_region_waits_for_a_real_non_gdm_wayland_session(self):
        console = Mock()
        console.run.return_value = CommandResult("", 0)
        with tempfile.TemporaryDirectory() as directory:
            assert_live_region(
                console,
                "zh_CN.UTF-8",
                "Asia/Shanghai",
                Path(directory),
            )
        script = console.run.call_args.args[0]
        self.assertIn("session_deadline=$((SECONDS + 120))", script)
        self.assertIn("while (( SECONDS < session_deadline ))", script)
        self.assertIn("gdm-greeter", script)
        self.assertIn("test -S \"$runtime/bus\"", script)
        self.assertIn('for candidate in "$runtime"/wayland-[0-9]*', script)
        self.assertIn('test -S "$candidate" || continue', script)
        self.assertIn('pgrep -n -u "$uid" -x gnome-shell', script)
        self.assertIn('tr \'\\0\' \'\\n\' < "/proc/$pid/environ"', script)
        self.assertIn('test "$session_ready" = true || status=1', script)
        self.assertNotIn("pgrep -n -f '/usr/bin/gnome-shell'", script)
        self.assertEqual(150, console.run.call_args.kwargs["timeout"])

    def test_live_region_uses_the_requested_session_timeout_with_headroom(self):
        console = Mock()
        console.run.return_value = CommandResult("", 0)
        with tempfile.TemporaryDirectory() as directory:
            assert_live_region(
                console,
                "zh_CN.UTF-8",
                "Asia/Shanghai",
                Path(directory),
                session_timeout_seconds=300,
            )
        self.assertIn(
            "session_deadline=$((SECONDS + 300))",
            console.run.call_args.args[0],
        )
        self.assertEqual(330, console.run.call_args.kwargs["timeout"])

    def test_live_identity_requires_the_exact_runtime_contract(self):
        console = Mock()
        console.run.return_value = CommandResult("identity-ok\n", 0)
        with tempfile.TemporaryDirectory() as directory:
            evidence = Path(directory)
            assert_live_identity(
                console,
                evidence,
                session_timeout_seconds=300,
            )
            self.assertEqual(
                "identity-ok\n\n",
                (evidence / "live-identity.txt").read_text(encoding="utf-8"),
            )

        script = console.run.call_args.args[0]
        syntax = subprocess.run(
            ("bash", "-n"),
            input=script,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
        self.assertEqual(0, syntax.returncode, syntax.stderr)
        for contract in (
            "expected_user=live",
            "expected_uid=1000",
            "expected_full_name='AnduinOS Live session user'",
            "expected_home=/home/live",
            "expected_shell=/bin/bash",
            "expected_hostname=anduinos",
            'test "$runtime_hostname" = "$expected_hostname"',
            'test "$session_ready" = true',
            'test "$sudo_output" = 0',
            'test "$marker_user" = "$expected_user"',
            'test "$autologin_enabled" = true',
            'test "$autologin_user" = "$expected_user"',
            'test "$timed_login_enabled" = false',
        ):
            self.assertIn(contract, script)
        self.assertIn("session_deadline=$((SECONDS + 300))", script)
        self.assertEqual(330, console.run.call_args.kwargs["timeout"])

    def test_live_environment_rejects_legacy_initrd_hook_paths(self):
        console = Mock()
        console.run.return_value = CommandResult("", 0)
        scenario = TestMatrix.load(ROOT / "cases/install.json").scenarios[0]
        with tempfile.TemporaryDirectory() as directory:
            assert_live_environment(
                console,
                scenario,
                Path(directory),
                "zh_CN.UTF-8",
                "Asia/Shanghai",
                check_region=False,
            )
        script = next(
            item.args[0]
            for item in console.run.call_args_list
            if "initrd_listing=$(lsinitrd /cdrom/LiveOS/initrd)" in item.args[0]
        )
        self.assertIn("initrd_listing=$(lsinitrd /cdrom/LiveOS/initrd)", script)
        self.assertIn(
            "dpkg-query -S /usr/sbin/update-initramfs | "
            "grep -Fxq 'dracut: /usr/sbin/update-initramfs'",
            script,
        )
        for forbidden_path in (
            "scripts/casper",
            "scripts/casper-bottom",
            "usr/share/initramfs-tools",
            "usr/share/initramfs-tools-core",
        ):
            self.assertIn(forbidden_path, script)
        self.assertNotIn(
            'printf \'%s\\n\' "$initrd_listing" | grep',
            script,
        )
        self.assertIn(
            'grep -Fq "$required_member" <<< "$initrd_listing"',
            script,
        )
        for moved_assertion in (
            "var/lib/dracut/hooks/pre-pivot/90-anduinos-live-prepare.sh",
            "usr/sbin/create-overlay.upstream",
            "usr/sbin/dmsquash-live-root",
            'parted --script --fix "$block_device" print',
            "LABEL=ANDUINOS-PERSIST",
            "spice-vdagent",
            "openssh-server",
            "anduinos-installer-beta",
            "systemctl is-enabled ssh.service",
            "systemctl is-enabled ssh.socket",
            "ssh_host_*_key",
        ):
            self.assertIn(moved_assertion, script)

    def test_gdm_login_waits_for_wayland_after_user_manager_becomes_active(self):
        clock = [0.0]
        serial = Mock()
        serial.run.return_value = CommandResult("active\n", 0)
        qmp = Mock()
        vm = SimpleNamespace(serial=serial, qmp=qmp)
        observations = iter(("", "", "anduinostest"))

        with (
            patch(
                "business.install.guest._graphical_user_optional",
                side_effect=lambda _console: next(observations),
            ),
            patch(
                "business.install.guest.time.monotonic",
                side_effect=lambda: clock[0],
            ),
            patch(
                "business.install.guest.time.sleep",
                side_effect=lambda seconds: clock.__setitem__(0, clock[0] + seconds),
            ),
        ):
            _login_gdm(vm, "anduinostest", "secret", timeout=120)

        self.assertEqual(2.0, clock[0])
        qmp.send_key.assert_not_called()
        qmp.type_text.assert_not_called()

    def test_gdm_login_types_once_then_waits_for_slow_wayland_session(self):
        clock = [0.0]
        serial = Mock()
        state_probes = [0]

        def loginctl_state(*_args, **_kwargs):
            state_probes[0] += 1
            state = "inactive" if state_probes[0] == 1 else "active"
            return CommandResult(state + "\n", 0)

        serial.run.side_effect = loginctl_state
        qmp = Mock()
        vm = SimpleNamespace(serial=serial, qmp=qmp)
        probe_count = [0]

        def graphical_user(_console):
            probe_count[0] += 1
            return "anduinostest" if probe_count[0] == 20 else ""

        with (
            patch(
                "business.install.guest._graphical_user_optional",
                side_effect=graphical_user,
            ),
            patch(
                "business.install.guest.time.monotonic",
                side_effect=lambda: clock[0],
            ),
            patch(
                "business.install.guest.time.sleep",
                side_effect=lambda seconds: clock.__setitem__(0, clock[0] + seconds),
            ),
        ):
            _login_gdm(vm, "anduinostest", "secret", timeout=120)

        self.assertGreaterEqual(clock[0], 19)
        self.assertEqual([call("ret"), call("ret")], qmp.send_key.call_args_list)
        qmp.type_text.assert_called_once_with("secret", interval=0.06)

    def test_installed_region_requires_configuration_and_real_gnome_process(self):
        console = Mock()
        console.run.return_value = CommandResult("", 0)
        with tempfile.TemporaryDirectory() as directory:
            evidence = Path(directory)
            assert_installed_region(
                console,
                "anduinostest",
                "zh_CN.UTF-8",
                "Asia/Shanghai",
                evidence,
            )
            self.assertTrue(
                (evidence / "installed-locale-timezone-session.txt").is_file()
            )
        script = console.run.call_args.args[0]
        self.assertIn("/etc/default/locale", script)
        self.assertIn("timedatectl show -p Timezone --value", script)
        self.assertIn('pgrep -n -u "$uid" -x gnome-shell', script)
        self.assertIn("/proc/$session_pid/environ", script)
        self.assertNotIn('test "$session_lang" = zh_CN.UTF-8', script)
        self.assertNotIn('test "$session_language" = zh_CN:zh', script)
        self.assertNotIn("dbus-run-session", script)

    def test_installed_region_ui_oracle_requires_real_localized_gnome_shell(self):
        passing = json.dumps(
            {
                "event": "installed-region-zh-cn",
                "application": "gnome-shell",
                "markers": [
                    {"role": "menu", "name": "系统"},
                    {"role": "toggle button", "name": "显示应用"},
                ],
            },
            ensure_ascii=False,
        )
        _validate_installed_region_ui_events(passing)
        faults = (
            passing.replace("显示应用", "Show Applications"),
            passing.replace('"application": "gnome-shell"', '"application": "fixture"'),
            passing.replace('"role": "menu"', '"role": "label"'),
            passing + "\n" + passing,
        )
        for broken in faults:
            with self.subTest(broken=broken):
                with self.assertRaises(TestFailure):
                    _validate_installed_region_ui_events(broken)

    def test_arm_grub_gates_graphical_commands_then_proves_pl011_handoff(self):
        console = Mock()
        qmp = Mock()

        with (
            patch("framework.grub.SpiceInputClient") as input_client,
            patch("framework.grub._ArmGraphicalGrubCommandLine") as controller,
        ):
            keyboard = input_client.return_value
            command_line = controller.return_value
            boot_iso_with_debug_shell(
                qmp,
                console,
                Architecture.ARM64,
                firmware_delay=0,
                menu_entry_index=2,
                kernel_arguments=(
                    "root=live:CDLABEL=anduinos",
                    "rd.live.dir=LiveOS",
                    "rd.live.squashimg=rootfs.squashfs",
                    "rd.overlay",
                    "rd.anduinos.live=1",
                    "locale=zh_CN.UTF-8",
                    "quiet",
                    "splash",
                    "---",
                ),
                spice_socket=Path("/test/spice.sock"),
            )

        command_line.open.assert_called_once_with(timeout=120)
        self.assertEqual(
            [
                call(
                    "linux /LiveOS/vmlinuz root=live:CDLABEL=anduinos"
                    " rd.live.dir=LiveOS rd.live.squashimg=rootfs.squashfs"
                    " rd.overlay rd.anduinos.live=1 locale=zh_CN.UTF-8"
                    + debug_kernel_arguments(Architecture.ARM64),
                    timeout=120,
                ),
                call("initrd /LiveOS/initrd", timeout=120),
            ],
            command_line.submit.call_args_list,
        )
        command_line.boot.assert_called_once_with()
        command_line.close.assert_called_once_with()
        console.wait_for_text.assert_called_once_with(
            "BdsDxe: starting Boot", timeout=120
        )
        console.wait_for_kernel_console.assert_called_once_with(timeout=120)
        input_client.assert_called_once_with(Path("/test/spice.sock"), timeout=30)
        keyboard.connect.assert_called_once_with(require_agent=False)
        keyboard.close.assert_called_once_with()
        controller.assert_called_once_with(qmp, keyboard)

    def test_arm_grub_missing_banner_sends_no_command_or_gpu(self):
        console = Mock()
        console.wait_for_text.side_effect = ProtocolError("injected missing banner")
        qmp = Mock()

        with (
            patch("framework.grub.SpiceInputClient") as input_client,
            self.assertRaisesRegex(ProtocolError, "injected missing banner"),
        ):
            boot_iso_with_debug_shell(
                qmp,
                console,
                Architecture.ARM64,
                firmware_delay=0,
                menu_entry_index=0,
                spice_socket=Path("/test/spice.sock"),
            )

        input_client.assert_not_called()
        qmp.assert_not_called()

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
            self.assertIn("virtio-gpu-pci,id=video0", rendered)
            self.assertNotIn("grubserial", rendered)
            self.assertNotIn("pci-serial", rendered)

    def test_arm_grub_requires_private_spice_input(self):
        with self.assertRaisesRegex(ProtocolError, "private SPICE"):
            boot_iso_with_debug_shell(
                Mock(),
                Mock(),
                Architecture.ARM64,
                firmware_delay=0,
                menu_entry_index=0,
                spice_socket=None,
            )

    def test_arm_grub_framebuffer_failure_blocks_all_commands(self):
        qmp = Mock()
        qmp.screendump.side_effect = ProtocolError("injected framebuffer failure")
        keyboard = Mock()
        command_line = _ArmGraphicalGrubCommandLine(qmp, keyboard)
        try:
            with self.assertRaisesRegex(ProtocolError, "injected framebuffer"):
                command_line.open(timeout=1)
        finally:
            command_line.close()
        self.assertEqual(
            [call("esc"), call("c")],
            keyboard.send_boot_key.call_args_list,
        )
        keyboard.type_boot_text.assert_not_called()

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

    def test_persistent_live_media_is_a_writable_boot_disk_not_a_cdrom(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            live_media = root / "live-media.raw"
            config = QemuConfig(
                architecture=Architecture.AMD64,
                firmware=Firmware.BIOS,
                network=Network.OFFLINE,
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
                live_media=live_media,
            )
            vm = QemuVm(config)
            vm._runtime = tempfile.TemporaryDirectory(prefix="anduinos-unit-")
            try:
                command = vm.command(attach_iso=True)
            finally:
                vm._runtime.cleanup()
                vm._runtime = None
        rendered = " ".join(command)
        self.assertIn(f"file={live_media}", rendered)
        self.assertIn("id=live-media", rendered)
        self.assertIn("scsi-hd", rendered)
        self.assertNotIn("scsi-cd", rendered)
        self.assertNotIn("readonly=on", rendered)

    def test_persistent_live_media_copy_has_sparse_partition_space(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source.iso"
            source.write_bytes(b"hybrid-iso-fixture")
            destination = root / "live-media.raw"
            config = QemuConfig(
                architecture=Architecture.AMD64,
                firmware=Firmware.BIOS,
                network=Network.OFFLINE,
                memory_mib=4096,
                cpus=2,
                disk_gib=20,
                ssh_forward_port=2222,
                iso=source,
                disk=root / "target.qcow2",
                variables=None,
                firmware_selection=None,
                artifacts=root / "artifacts",
                qemu_binary="qemu-system-x86_64",
                acceleration="tcg,thread=multi",
                live_media=destination,
            )

            QemuVm(config).create_live_media()

            self.assertEqual(
                source.stat().st_size + PERSISTENT_LIVE_FREE_SPACE_GIB * GIB,
                destination.stat().st_size,
            )
            with destination.open("rb") as stream:
                self.assertEqual(source.read_bytes(), stream.read(source.stat().st_size))
            self.assertLess(destination.stat().st_blocks * 512, 1024 * 1024)

    def test_qemu_screenshot_retains_lossless_png_and_removes_raw_ppm(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            vm = QemuVm(SimpleNamespace(artifacts=root))

            def screendump(destination):
                Image.new("RGB", (64, 32), (12, 34, 56)).save(
                    destination,
                    format="PPM",
                )

            vm.qmp = SimpleNamespace(screendump=screendump)
            screenshot = vm.screenshot("desktop-boundary")

            self.assertEqual(root / "desktop-boundary.png", screenshot)
            self.assertTrue(screenshot.is_file())
            self.assertFalse((root / ".desktop-boundary.capture.ppm").exists())
            self.assertFalse((root / "desktop-boundary.ppm").exists())
            with Image.open(screenshot) as image:
                self.assertEqual((64, 32), image.size)
                self.assertEqual((12, 34, 56), image.getpixel((0, 0)))

    @patch("framework.qemu.subprocess.run")
    def test_feature_disk_is_a_qcow2_overlay_with_an_absolute_backing_file(self, run):
        run.return_value = subprocess.CompletedProcess([], 0, stdout="")
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            backing = root / "verified-base.qcow2"
            backing.write_bytes(b"base")
            config = QemuConfig(
                architecture=Architecture.AMD64,
                firmware=Firmware.BIOS,
                network=Network.ONLINE,
                memory_mib=4096,
                cpus=2,
                disk_gib=40,
                ssh_forward_port=2222,
                iso=root / "test.iso",
                disk=root / "suite" / "overlay.qcow2",
                variables=None,
                firmware_selection=None,
                artifacts=root / "artifacts",
                qemu_binary="qemu-system-x86_64",
                acceleration="tcg,thread=multi",
                backing_disk=backing,
            )
            QemuVm(config).create_disk()
        command = run.call_args.args[0]
        self.assertEqual("qemu-img", command[0])
        self.assertIn("-F", command)
        self.assertIn("-b", command)
        self.assertEqual(str(backing.resolve()), command[command.index("-b") + 1])


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

    def test_vm_transition_flushes_the_target_before_qmp_quit(self):
        events = []
        serial = Mock()
        serial.run.side_effect = lambda *args, **kwargs: events.append("guest-sync")
        qmp = Mock()
        qmp.flush_block_device.side_effect = (
            lambda *args, **kwargs: events.append("block-flush")
        )
        qmp.quit.side_effect = lambda: events.append("qmp-quit")
        vm = SimpleNamespace(
            serial=serial,
            qmp=qmp,
            wait=Mock(side_effect=lambda _timeout: events.append("qemu-exit")),
            stop=Mock(side_effect=lambda: events.append("cleanup")),
        )

        _power_off(vm)

        self.assertEqual(
            ["guest-sync", "block-flush", "qmp-quit", "qemu-exit", "cleanup"],
            events,
        )
        qmp.flush_block_device.assert_called_once_with("target")

    def test_persistent_live_transition_flushes_both_writable_devices(self):
        events = []
        qmp = Mock()
        qmp.flush_block_device.side_effect = lambda node: events.append(node)
        vm = SimpleNamespace(
            serial=Mock(),
            qmp=qmp,
            config=SimpleNamespace(live_media=Path("live-media.raw")),
            live_media_attached=True,
            wait=Mock(),
            stop=Mock(),
        )

        _power_off(vm)

        self.assertEqual(["target", "live-media"], events)

    def test_installed_boot_does_not_flush_detached_persistent_live_media(self):
        events = []
        qmp = Mock()
        qmp.flush_block_device.side_effect = lambda node: events.append(node)
        vm = SimpleNamespace(
            serial=Mock(),
            qmp=qmp,
            config=SimpleNamespace(live_media=Path("live-media.raw")),
            live_media_attached=False,
            wait=Mock(),
            stop=Mock(),
        )

        _power_off(vm)

        self.assertEqual(["target"], events)

    def test_live_overlay_guest_probes_are_valid_bash(self):
        runner = object.__new__(ScenarioRunner)
        for method_name in (
            "_assert_temporary_live_overlay",
            "_create_persistent_live_sentinel",
            "_assert_persistent_live_sentinel",
        ):
            with self.subTest(method=method_name):
                serial = Mock()
                serial.run.return_value = SimpleNamespace(stdout="ok")
                vm = SimpleNamespace(serial=serial)
                with tempfile.TemporaryDirectory() as directory:
                    getattr(runner, method_name)(vm, Path(directory))
                script = serial.run.call_args.args[0]
                syntax = subprocess.run(
                    ("bash", "-n"),
                    input=script,
                    text=True,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    check=False,
                )
                self.assertEqual(0, syntax.returncode, syntax.stderr)

    def test_failed_target_flush_is_a_visible_failure_and_still_cleans_up(self):
        vm = SimpleNamespace(
            serial=Mock(),
            qmp=Mock(),
            wait=Mock(),
            stop=Mock(),
        )
        vm.qmp.flush_block_device.side_effect = ProtocolError(
            "injected block flush failure"
        )

        with self.assertRaisesRegex(ProtocolError, "injected block flush failure"):
            _power_off(vm)

        vm.qmp.quit.assert_not_called()
        vm.stop.assert_called_once_with()

    def test_target_boot_integrity_rejects_a_copied_kernel_bit_flip(self):
        passing = "\n".join(
            (
                f"ANDUINOS_TARGET_KERNEL_SHA256={self._GOOD_KERNEL_HASH}",
                f"ANDUINOS_ISO_KERNEL_SHA256={self._GOOD_KERNEL_HASH}",
                "ANDUINOS_INITRD_CHECK=ok",
            )
        )
        _validate_target_boot_integrity(passing)

        corrupted = passing.replace(
            f"ANDUINOS_TARGET_KERNEL_SHA256={self._GOOD_KERNEL_HASH}",
            f"ANDUINOS_TARGET_KERNEL_SHA256={'b' * 64}",
        )
        with self.assertRaisesRegex(TestFailure, "differs byte-for-byte"):
            _validate_target_boot_integrity(corrupted)

    @patch("framework.base._check_qcow2", return_value={"corruptions": 0})
    def test_immutable_base_oracle_rejects_a_same_size_bit_flip(self, _check):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            disk = root / "target.qcow2"
            original = b"qcow2-base-contents"
            corrupted = b"qcow2-base-contentz"
            self.assertEqual(len(original), len(corrupted))
            disk.write_bytes(original)
            disk.chmod(0o400)
            disk_stat = disk.stat()
            scenario = TestMatrix.load(ROOT / "cases/install.json").scenarios[0]
            base = PromotedBase(
                identity="test-base",
                architecture=Architecture.AMD64,
                scenario=scenario,
                disk=disk,
                variables=None,
                config=SimpleNamespace(),
                boot_files=InstalledBootFiles("/boot/vmlinuz", "/boot/initrd"),
                disk_sha256=hashlib.sha256(original).hexdigest(),
                disk_size_bytes=disk_stat.st_size,
                disk_mtime_ns=disk_stat.st_mtime_ns,
                variables_sha256=None,
                variables_size_bytes=None,
                variables_mtime_ns=None,
                manifest=root / "manifest.json",
                lock_path=root / "base.lock",
            )

            evidence = base.verify_integrity()
            self.assertEqual(base.disk_sha256, evidence["disk_sha256"])

            disk.chmod(0o600)
            disk.write_bytes(corrupted)
            os.utime(
                disk,
                ns=(disk.stat().st_atime_ns, disk_stat.st_mtime_ns),
            )
            disk.chmod(0o400)
            with self.assertRaisesRegex(TestFailure, "content changed"):
                base.verify_integrity()

    def test_promoted_base_cleanup_discards_disk_and_uefi_variables(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            disk = root / "target.qcow2"
            variables = root / "uefi-vars.fd"
            lock = root / "base.lock"
            disk.write_bytes(b"promoted disk")
            variables.write_bytes(b"promoted firmware state")
            lock.write_text("", encoding="utf-8")
            scenario = TestMatrix.load(ROOT / "cases/install.json").scenarios[0]
            base = PromotedBase(
                identity="cleanup-base",
                architecture=Architecture.AMD64,
                scenario=scenario,
                disk=disk,
                variables=variables,
                config=SimpleNamespace(),
                boot_files=InstalledBootFiles("/boot/vmlinuz", "/boot/initrd"),
                disk_sha256="0" * 64,
                disk_size_bytes=disk.stat().st_size,
                disk_mtime_ns=disk.stat().st_mtime_ns,
                variables_sha256="1" * 64,
                variables_size_bytes=variables.stat().st_size,
                variables_mtime_ns=variables.stat().st_mtime_ns,
                manifest=root / "manifest.json",
                lock_path=lock,
            )

            base.cleanup()

            self.assertFalse(disk.exists())
            self.assertFalse(variables.exists())
            self.assertFalse(lock.exists())

    def test_iso_boot_uses_the_exact_selected_grub_region(self):
        grub = "\n".join(
            f'''menuentry "Language {index}" {{
 linux /LiveOS/vmlinuz root=live:CDLABEL=anduinos rd.live.dir=LiveOS rd.live.squashimg=rootfs.squashfs rd.overlay rd.anduinos.live=1 locale=l{index}_XX.UTF-8 timezone=Zone/{index} systemd.timezone=Zone/{index} quiet splash ---
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
 linux /LiveOS/vmlinuz root=live:CDLABEL=anduinos rd.live.dir=LiveOS rd.live.squashimg=rootfs.squashfs rd.overlay rd.anduinos.live=1 locale=en_US.UTF-8 timezone=Etc/UTC systemd.timezone=Etc/UTC
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
            self.assertIn(b".rsrc\0\0\0", content)
            self.assertIn(b"\x89PNG\r\n\x1a\n", content)
            thumbnailer = shutil.which("exe-thumbnailer")
            if thumbnailer is not None:
                thumbnail = Path(directory) / "cpu-z.png"
                generated = subprocess.run(
                    (thumbnailer, "-s", "256", str(destination), str(thumbnail)),
                    check=False,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                )
                self.assertEqual(0, generated.returncode, generated.stdout)
                assert_cpu_z_thumbnail(
                    thumbnail,
                    Path(directory) / "cpu-z-thumbnail-analysis.json",
                )

    def test_file_integration_fixtures_are_deterministic_and_harmless(self):
        digests = []
        for _iteration in range(2):
            with tempfile.TemporaryDirectory() as directory:
                fixtures = build_file_integration_fixtures(Path(directory))
                paths = (
                    fixtures.image,
                    fixtures.video,
                    fixtures.deb,
                    fixtures.text,
                )
                digests.append(
                    tuple(hashlib.sha256(path.read_bytes()).hexdigest() for path in paths)
                )
                with Image.open(fixtures.image) as image:
                    self.assertEqual((320, 240), image.size)
                self.assertGreater(fixtures.video.stat().st_size, 1024)
                fields = subprocess.run(
                    (
                        "dpkg-deb",
                        "--field",
                        str(fixtures.deb),
                        "Package",
                        "Version",
                        "Architecture",
                    ),
                    check=True,
                    stdout=subprocess.PIPE,
                    text=True,
                ).stdout.splitlines()
                self.assertEqual(
                    [
                        "Package: anduinos-acceptance-fixture",
                        "Version: 1.0",
                        "Architecture: all",
                    ],
                    fields,
                )
                control_tar = subprocess.run(
                    ("dpkg-deb", "--ctrl-tarfile", str(fixtures.deb)),
                    check=True,
                    stdout=subprocess.PIPE,
                ).stdout
                members = subprocess.run(
                    ("tar", "-tf", "-"),
                    input=control_tar,
                    check=True,
                    stdout=subprocess.PIPE,
                ).stdout.decode().splitlines()
                self.assertEqual({"./", "./control"}, set(members))
        self.assertEqual(digests[0], digests[1])

    def test_installed_grub_instrumentation_is_byte_for_byte_reversible(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            grub = root / "boot/grub"
            grub.mkdir(parents=True)
            config = grub / "grub.cfg"
            original = (
                "set default=0\n"
                "menuentry 'AnduinOS' {\n"
                "  linux /boot/vmlinuz root=UUID=test ro quiet splash\n"
                "  initrd /boot/initrd.img\n"
                "}\n"
            )
            config.write_text(original, encoding="utf-8")
            subprocess.run(
                ("grub-editenv", str(grub / "grubenv"), "create"),
                check=True,
            )
            environment = os.environ | {"mountpoint": str(root)}
            instrument = subprocess.run(
                ("bash", "-c", render_installed_grub_instrumentation(
                    Architecture.AMD64,
                    mounted_target=True,
                )),
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                env=environment,
                check=False,
            )
            self.assertEqual(0, instrument.returncode, instrument.stdout)
            self.assertIn("systemd.debug_shell=ttyS0", config.read_text())
            self.assertTrue(config.with_name("grub.cfg.anduinos-acceptance-original").is_file())
            restore = subprocess.run(
                ("bash", "-c", render_installed_grub_restoration(mounted_target=True)),
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                env=environment,
                check=False,
            )
            self.assertEqual(0, restore.returncode, restore.stdout)
            self.assertEqual(original, config.read_text(encoding="utf-8"))
            self.assertIn("byte-for-byte-restored=yes", restore.stdout)
