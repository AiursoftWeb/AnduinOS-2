"""Release wiring, cleanup, and host-storage safety tests."""

from unit.support import *  # noqa: F403
class AcceptanceWiringTests(unittest.TestCase):
    def test_action_scoped_journal_is_real_in_base_and_overlay_drivers(self):
        runner = _source_tree(ROOT / "business/install")
        base = runner.split("def _assert_action_scoped_journal(", 1)[1].split(
            "def _assert_journal_health(",
            1,
        )[0]
        self.assertIn('after_cursor=cursors["system"]', base)
        self.assertIn('after_cursor=cursors["user"]', base)
        self.assertIn('action_scope="installed-desktop-contracts"', base)
        self.assertIn("if not verdict.passed", base)

        features = _source_tree(ROOT / "business/desktop")
        shell_driver = features.split("def _run_shell_driver(", 1)[1].split(
            "def _stabilize_shell_search_provider(",
            1,
        )[0]
        file_driver = features.split("def _run_file_driver(", 1)[1].split(
            "def _exercise_image_thumbnail(",
            1,
        )[0]
        for body in (shell_driver, file_driver):
            self.assertIn("cursors = self._journal_cursors(vm)", body)
            self.assertIn("self._assert_scoped_journal(", body)

    def test_gdm_cursor_probe_restores_the_locked_security_policy(self):
        source = _source_tree(ROOT / "business/desktop")
        exercise = source.split("def _exercise_gdm_cursor(", 1)[1].split(
            "def _backup_gdm_screenshot_policy(",
            1,
        )[0]
        policy = source.split("def _set_gdm_screenshot_policy(", 1)[1].split(
            "def _capture_gdm_cursor_frame(",
            1,
        )[0]
        self.assertIn("finally:", exercise)
        self.assertIn("capture_enabled=False", exercise)
        self.assertIn('cmp -s \\"$backup/settings\\" \\"$settings\\"', policy)
        self.assertIn('cmp -s \\"$backup/locks\\" \\"$locks\\"', policy)
        self.assertIn("restored-lockdown=true", policy)

    def test_gdm_contract_reads_the_real_greeter_dconf_profile(self):
        source = _source_tree(ROOT / "business/desktop")
        helper = source.split("def _gdm_gsettings_get(", 1)[1].split(
            "def _capture_gdm_cursor_frame(",
            1,
        )[0]
        self.assertIn('"DCONF_PROFILE=gdm"', helper)
        self.assertIn('"gsettings"', helper)
        self.assertIn("_gdm_gsettings_get(", source)

    def test_gdm_cursor_uses_shell_capture_with_the_cursor_plane(self):
        body = inspect.getsource(FeatureSuiteRunner._capture_gdm_cursor_frame)
        self.assertIn("gdm_screenshot_client.py", body)
        self.assertIn("_retrieve_file", body)
        self.assertNotIn("vm.screenshot", body)

    def test_gdm_screenshot_client_fails_closed_without_trusted_name_or_capture(self):
        fixture = runpy.run_path("tests/fixtures/gdm_screenshot_client.py")
        with self.assertRaisesRegex(RuntimeError, "trusted screenshot sender"):
            fixture["_require_primary_owner"](2)
        with self.assertRaisesRegex(RuntimeError, "capture failed"):
            fixture["_require_screenshot_reply"](
                False, "/tmp/frame.png", "/tmp/frame.png"
            )
        with self.assertRaisesRegex(RuntimeError, "unexpected screenshot path"):
            fixture["_require_screenshot_reply"](
                True, "/tmp/wrong.png", "/tmp/frame.png"
            )

    def test_gdm_screenshot_client_uses_and_releases_shell_allowlisted_name(self):
        fixture = Path("tests/fixtures/gdm_screenshot_client.py").read_text(
            encoding="utf-8"
        )
        runner = _source_tree(ROOT / "business/desktop")
        self.assertIn('TRUSTED_NAME = "org.gnome.SettingsDaemon.MediaKeys"', fixture)
        self.assertIn("DBUS_REQUEST_NAME_FLAGS_DO_NOT_QUEUE", fixture)
        self.assertIn('"RequestName"', fixture)
        self.assertIn('"ReleaseName"', fixture)
        self.assertIn("finally:", fixture)
        self.assertIn("org.gnome.SettingsDaemon.MediaKeys.target", runner)
        self.assertIn("media-keys-restored=active", runner)

    def test_firefox_theme_fixture_disables_first_run_ui_and_forces_atspi(self):
        source = _source_tree(ROOT / "business/desktop")
        body = source.split("def _exercise_firefox_theme(", 1)[1].split(
            "def _prepare_theme_fixture(",
            1,
        )[0]
        for preference in (
            'browser.aboutwelcome.enabled\\\", false',
            'browser.preonboarding.enabled\\\", false',
            'trailhead.firstrun.didSeeAboutWelcome\\\", true',
            'termsofuse.bypassNotification\\\", true',
            'termsofuse.acceptedVersion\\\", 999',
            'accessibility.force_disabled\\\", -1',
        ):
            self.assertIn(preference, body)

    def test_qt_theme_fixture_keeps_the_normal_platform_integration(self):
        source = _source_tree(ROOT / "business/desktop")
        body = source.split("def _exercise_qt_theme(", 1)[1].split(
            "def _exercise_firefox_theme(",
            1,
        )[0]
        self.assertNotIn("--no-install-recommends", body)
        self.assertIn("python3-pyqt6", body)
        self.assertIn("qt6-gtk-platformtheme", body)
        self.assertIn("qt6-qpa-plugins", body)
        self.assertNotIn("QT_QPA_PLATFORMTHEME", body)
        self.assertNotIn("QT_STYLE_OVERRIDE", body)

        fixture = Path("tests/fixtures/qt_theme_fixture.py").read_text(encoding="utf-8")
        self.assertIn("application.paletteChanged.connect", fixture)
        self.assertIn("QPalette.ColorRole.Window", fixture)
        self.assertNotIn("setPalette", fixture)
        self.assertNotIn("setStyleSheet", fixture)

    def test_accounts_driver_treats_password_policy_radio_as_a_toggle(self):
        source = _source_tree(ROOT / "assertions/guest/ui")
        control_body = source.split("def control(key: str):", 1)[1].split(
            "def request_focused_activation", 1
        )[0]
        self.assertIn('"radio button"', control_body)

    def test_accounts_settings_log_is_private_to_each_graphical_user(self):
        source = _source_tree(ROOT / "assertions/guest/ui")
        body = source.split("def prepare_user_accounts(", 1)[1].split(
            "def authenticate_user_panel(", 1
        )[0]
        self.assertIn('os.environ.get("XDG_RUNTIME_DIR"', body)
        self.assertIn("os.getpid()", body)
        self.assertNotIn("/tmp/gnome-users.stdout", body)

    def test_accounts_evidence_is_separated_across_graphical_users(self):
        source = _source_tree(ROOT / "business/desktop")
        for directory in (
            "evidence/account-create",
            "evidence/account-change-password",
            "evidence/gdm-audit",
            "evidence/gdm-{label}",
        ):
            self.assertIn(directory, source)

        account_body = source.split("def _exercise_account_add_user(", 1)[1].split(
            "def _exercise_gdm_branding(", 1
        )[0]
        self.assertNotIn('f"{remote}/evidence",', account_body)

    def test_password_row_uses_verified_keyboard_activation(self):
        source = _source_tree(ROOT / "assertions/guest/ui")
        body = source.split("def change_own_password(", 1)[1].split(
            "def dynamic_user_node(", 1
        )[0]
        self.assertIn("request_focused_activation(", body)
        self.assertIn('"accounts-open-change-password"', body)
        self.assertNotIn('click("password"', body)
        self.assertNotIn("request_semantic_pointer_click(", body)
        self.assertIn("discover_current_password_focus()", body)
        self.assertIn("request_dialog_secret(", body)
        self.assertIn("accounts-change-password-submit", body)
        self.assertNotIn('click("change"', body)
        focus_search = source.split(
            "def discover_current_password_focus(", 1
        )[1].split("def request_dialog_secret(", 1)[0]
        self.assertIn("gnome-dialog-tab-search", focus_search)
        self.assertIn('enabled(editable_control("new_password"', focus_search)
        self.assertIn('event("current-password-authenticated"', focus_search)
        self.assertNotIn("qmp-click", focus_search)
        dialog_secret = source.split("def request_dialog_secret(", 1)[1].split(
            "def wait_absent(", 1
        )[0]
        self.assertIn("gnome-dialog-focus-chain", dialog_secret)
        self.assertIn('key="tab"', dialog_secret)
        self.assertNotIn("grab_focus", dialog_secret)
        delivery = source.split("def _request_secret_delivery(", 1)[1].split(
            "def request_secret(", 1
        )[0]
        self.assertIn("get_character_count()", delivery)
        self.assertIn("Secret input did not reach field", delivery)

    def test_installer_failure_path_preserves_the_executor_transcript(self):
        source = _source_tree(ROOT / "assertions/guest/ui")
        install = source.split("def install(", 1)[1].split(
            "def prepare_secure_shell(", 1
        )[0]
        failed = install.split('if find_optional("failed"', 1)[1].split(
            'if find_optional("complete"', 1
        )[0]
        self.assertIn("save_executor_output()", failed)
        self.assertIn('evidence / "installer-output.txt"', install)
        self.assertIn('click("save_log")', install)

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

    def test_desktop_command_repairs_and_pins_the_current_atspi_bus(self):
        for managed in (False, True):
            command = _desktop_command("anduinostest", ("true",), managed=managed)
            self.assertIn("env -u AT_SPI_BUS_ADDRESS", command)
            self.assertIn("org.a11y.Bus.GetAddress", command)
            self.assertIn("test -S \"$atspi_socket\"", command)
            self.assertIn("restart at-spi-dbus-bus.service", command)
            self.assertIn("atspi_repaired=true", command)
            self.assertIn("gnome-extensions disable ding@rastersoft.com", command)
            self.assertIn("gnome-extensions enable ding@rastersoft.com", command)
            self.assertIn('AT_SPI_BUS_ADDRESS="$atspi_address"', command)

    def test_installed_region_outer_timeout_covers_ding_readiness_wait(self):
        guest_source = (
            ROOT / "assertions/guest/ui/shell_common.py"
        ).read_text(encoding="utf-8")
        host_source = (
            ROOT / "business/install/contracts.py"
        ).read_text(encoding="utf-8")
        self.assertIn("deadline = time.monotonic() + 120", guest_source)
        self.assertIn("vm.serial.run(command, timeout=180", host_source)

    def test_installed_release_script_contains_every_declared_command_contract(self):
        with tempfile.TemporaryDirectory() as directory:
            console = _CaptureConsole()
            _assert_release_contracts(console, "anduinostest", Path(directory))
            script = "\n".join(console.scripts)
        self.assertEqual(len(RELEASE_CONTRACT_CHECKS), len(console.scripts))
        self.assertIn("fs.inotify.max_user_instances", script)
        self.assertIn("get_ptyxis_setting range", script)
        self.assertIn("get_ptyxis_setting get", script)
        self.assertIn("(uint32 80, uint32 24)", script)
        self.assertIn("xdg-mime query default", script)
        self.assertIn("org.gnome.Loupe.desktop", script)
        self.assertIn("io.github.celluloid_player.Celluloid.desktop", script)
        self.assertIn("gnome-software-local-file-packagekit.desktop", script)
        self.assertNotIn("com.anduinos.AppImageRunner.desktop", script)
        self.assertNotIn("com.anduinos.ExeRunner.desktop", script)
        self.assertIn("why_output=$(why", script)
        self.assertIn("Noto Sans CJK SC", script)
        self.assertIn("Twemoji", script)
        self.assertIn("/etc/alternatives/default.plymouth", script)

    def test_release_contracts_have_independent_scripts_and_evidence(self):
        with tempfile.TemporaryDirectory() as directory:
            evidence = Path(directory)
            scripts = {}
            for identifier in RELEASE_CONTRACT_CHECKS:
                console = _CaptureConsole()
                assert_release_contract(
                    console,
                    "anduinostest",
                    evidence,
                    identifier,
                )
                self.assertEqual(1, len(console.scripts))
                scripts[identifier] = console.scripts[0]
                expected = evidence / (identifier.replace(".", "-") + ".txt")
                self.assertTrue(expected.is_file())

        self.assertIn(
            "fs.inotify.max_user_instances",
            scripts["system.inotify-max-user-instances"],
        )
        ptyxis_script = scripts["terminal.ptyxis-initial-size"]
        self.assertIn("runuser -u anduinostest", ptyxis_script)
        self.assertIn("HOME=/home/anduinostest", ptyxis_script)
        self.assertIn("GSETTINGS_BACKEND=dconf", ptyxis_script)
        self.assertIn("dpkg-query -W", ptyxis_script)
        self.assertIn("anduinos-dconf-defaults", ptyxis_script)
        self.assertIn("gsettings \"$@\" org.gnome.Ptyxis window-size", ptyxis_script)
        self.assertIn("test \"$ptyxis_type\" = 'type (uu)'", ptyxis_script)
        self.assertIn(
            "test \"$ptyxis_size\" = '(uint32 80, uint32 24)'",
            ptyxis_script,
        )
        self.assertIn("xdg-mime query default", scripts["desktop.mime-defaults"])
        self.assertIn("why_output=$(why", scripts["command.why-placeholder"])
        self.assertIn("Twemoji", scripts["font.selection-contracts"])
        self.assertIn(
            "/etc/alternatives/default.plymouth",
            scripts["boot.plymouth-theme-selection"],
        )
        with tempfile.TemporaryDirectory() as directory, self.assertRaisesRegex(
            ValueError,
            "Unknown release contract",
        ):
            assert_release_contract(
                _CaptureConsole(),
                "anduinostest",
                Path(directory),
                "invented.contract",
            )

    def test_independent_file_contracts_accept_native_appimage_and_pe_handler(self):
        _validate_appimage_fixture_contract(
            "appimage-mime=application/vnd.appimage\n"
            "appimage-default=\n"
            "appimage-runner-present=no\n"
            "appimage-mode=755\n"
            "appimage-blocked-mode=644\n"
        )
        _validate_windows_executable_fixture_contract(
            "pe-mime=application/vnd.microsoft.portable-executable\n"
            "pe-default=com.anduinos.ExeRunner.desktop\n"
        )

    def test_appimage_contract_rejects_obsolete_runner_without_pe_evidence(
        self,
    ):
        with self.assertRaisesRegex(
            TestFailure,
            "unexpectedly depends on a MIME handler",
        ):
            _validate_appimage_fixture_contract(
                "appimage-mime=application/vnd.appimage\n"
                "appimage-default=com.anduinos.AppImageRunner.desktop\n"
                "appimage-runner-present=yes\n"
                "appimage-mode=755\n"
                "appimage-blocked-mode=644\n"
            )

    def test_appimage_contract_rejects_erased_execution_boundary(self):
        with self.assertRaisesRegex(TestFailure, "negative AppImage fixture"):
            _validate_appimage_fixture_contract(
                "appimage-mime=application/vnd.appimage\n"
                "appimage-default=\n"
                "appimage-runner-present=no\n"
                "appimage-mode=755\n"
                "appimage-blocked-mode=755\n"
            )

    def test_non_executable_appimage_requires_unique_blocked_runtime_event(self):
        passing = json.dumps(
            {
                "event": "nautilus-open-blocked",
                "filename": "AnduinOS-Blocked.AppImage",
                "activation_method": "selected-item-qmp-enter",
                "executable": False,
                "fixture_window_visible": False,
                "process_running": False,
            }
        ) + "\n"
        _validate_appimage_blocked_events(passing)
        with self.assertRaisesRegex(TestFailure, "execution boundary"):
            _validate_appimage_blocked_events(
                passing.replace('"process_running": false', '"process_running": true')
            )

    def test_non_executable_appimage_uses_retrievable_writable_evidence_tree(self):
        source = _source_tree(ROOT / "business/install")
        self.assertIn('f"{remote_root}/evidence/blocked"', source)
        self.assertNotIn("evidence-blocked", source)

    def test_non_executable_appimage_does_not_count_nautilus_select_as_execution(
        self,
    ):
        source = _source_tree(ROOT / "assertions/guest/ui")
        self.assertIn("executable.samefile(target_resolved)", source)
        self.assertIn("argument_zero.samefile(target_resolved)", source)
        self.assertIn("referencing_processes=referencing_processes", source)
        self.assertNotIn("if filename_bytes in value:\n                process_running", source)

    def test_pe_contract_fault_injection_does_not_require_appimage_evidence(self):
        with self.assertRaisesRegex(
            TestFailure,
            "CPU-Z PE default handler is missing or incorrect: <none>",
        ):
            _validate_windows_executable_fixture_contract(
                "pe-mime=application/vnd.microsoft.portable-executable\n"
                "pe-default=\n"
            )

    def test_desktop_checks_call_every_implemented_runtime_check(self):
        source = _source_tree(ROOT / "business/install")
        for method in (
            "_exercise_font_rendering",
            "_exercise_appimage_open",
            "_exercise_windows_executable_open",
            "_assert_gnome_extensions",
            "_exercise_dynamic_resolution",
            "_assert_journal_health",
            "_assert_passive_plymouth_boot",
        ):
            self.assertGreaterEqual(source.count(f"self.{method}("), 1, method)

    def test_appimage_failure_cannot_mask_windows_executable_check(self):
        runner = object.__new__(ScenarioRunner)
        events = []
        runner._check_details = {}
        runner._emit_check = (
            lambda scenario, check, state, detail: events.append(
                (scenario, check, state, detail)
            )
        )
        failures = []
        windows_executable_ran = False

        def fail_appimage():
            raise TestFailure("injected AppImage native activation failure")

        def pass_windows_executable():
            nonlocal windows_executable_ran
            windows_executable_ran = True

        with tempfile.TemporaryDirectory() as directory:
            artifacts = Path(directory)
            scenario = SimpleNamespace(id="desktop-contracts")
            runner._collect_gate_failure(
                scenario,
                "files.appimage-open",
                fail_appimage,
                failures,
                artifacts,
            )
            runner._collect_gate_failure(
                scenario,
                "files.exe-open-fixture",
                pass_windows_executable,
                failures,
                artifacts,
            )
            persisted = (artifacts / "gate-failures.txt").read_text(
                encoding="utf-8"
            )

        self.assertTrue(windows_executable_ran)
        self.assertEqual(1, len(failures))
        self.assertIn("injected AppImage native activation failure", persisted)
        self.assertIn(
            ("desktop-contracts", "files.exe-open-fixture", "passed", "All assertions passed"),
            events,
        )

    @patch("business.install.contracts.assert_release_contract")
    def test_failed_installed_contract_collects_every_sibling_then_blocks(self, contract):
        runner = object.__new__(ScenarioRunner)
        runner.defaults = SimpleNamespace(username="anduinostest")
        runner._check_details = {}
        events = []
        runner._emit_check = (
            lambda scenario, check, state, detail: events.append(
                (scenario, check, state, detail)
            )
        )
        def inject_ptyxis_failure(_console, _username, _artifacts, identifier):
            if identifier == "terminal.ptyxis-initial-size":
                raise TestFailure("injected invalid Ptyxis dconf value")

        contract.side_effect = inject_ptyxis_failure
        vm = SimpleNamespace(serial=object())
        scenario = SimpleNamespace(id="bios-offline-btrfs")

        with tempfile.TemporaryDirectory() as directory, self.assertRaisesRegex(
            TestFailure,
            "(?s)Installed-system release contracts failed.*invalid Ptyxis dconf value",
        ):
            runner._assert_installed_release_contracts(
                vm,
                scenario,
                Path(directory),
            )

        self.assertEqual(len(RELEASE_CONTRACT_CHECKS), contract.call_count)
        self.assertEqual(
            list(RELEASE_CONTRACT_CHECKS),
            [call.args[3] for call in contract.call_args_list],
        )
        states = {check: state for _scenario, check, state, _detail in events}
        self.assertEqual("failed", states["terminal.ptyxis-initial-size"])
        for identifier in RELEASE_CONTRACT_CHECKS:
            if identifier != "terminal.ptyxis-initial-size":
                self.assertEqual("passed", states[identifier])

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
                variables = root / "uefi-vars.fd"
                disk.write_bytes(b"disposable")
                variables.write_bytes(b"disposable firmware state")
                vm = SimpleNamespace(
                    running=False,
                    config=SimpleNamespace(disk=disk, variables=variables),
                )
                runner._finalize_disk(vm, root, passed=passed)
                self.assertFalse(disk.exists())
                self.assertFalse(variables.exists())
                evidence = (root / "target-disk-retention.txt").read_text(
                    encoding="utf-8"
                )
                self.assertIn("discarded", evidence)
                self.assertIn("passed" if passed else "failed", evidence)

    def test_explicit_single_debug_disk_can_be_retained(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            disk = root / "target.qcow2"
            variables = root / "uefi-vars.fd"
            disk.write_bytes(b"debug")
            variables.write_bytes(b"debug firmware state")
            runner = object.__new__(ScenarioRunner)
            runner.options = SimpleNamespace(
                keep_passed_disk=False,
                keep_failed_disk=True,
                disk_storage=DiskStorage(root, "filesystem", "unit test"),
            )
            vm = SimpleNamespace(
                running=False,
                config=SimpleNamespace(disk=disk, variables=variables),
            )
            runner._finalize_disk(vm, root, passed=False)
            self.assertTrue(disk.exists())
            self.assertTrue(variables.exists())
            self.assertIn(
                "retained",
                (root / "target-disk-retention.txt").read_text(encoding="utf-8"),
            )

    def test_persistent_live_media_is_discarded_even_with_target_retention(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            disk = root / "target.qcow2"
            live_media = root / "live-media.raw"
            disk.write_bytes(b"debug")
            live_media.write_bytes(b"writable hybrid media")
            runner = object.__new__(ScenarioRunner)
            runner.options = SimpleNamespace(
                keep_passed_disk=False,
                keep_failed_disk=True,
                disk_storage=DiskStorage(root, "filesystem", "unit test"),
            )
            vm = SimpleNamespace(
                running=False,
                config=SimpleNamespace(
                    disk=disk,
                    variables=None,
                    live_media=live_media,
                ),
            )

            runner._finalize_disk(vm, root, passed=False)

            self.assertTrue(disk.exists())
            self.assertFalse(live_media.exists())

    def test_feature_overlay_cleanup_discards_its_uefi_variables(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            backing = root / "base.qcow2"
            disk = root / "suite" / "overlay.qcow2"
            variables = root / "artifacts" / "uefi-vars.fd"
            backing.write_bytes(b"immutable base")
            disk.parent.mkdir()
            disk.write_bytes(b"overlay")
            variables.parent.mkdir()
            variables.write_bytes(b"overlay firmware state")
            vm = SimpleNamespace(
                stop=Mock(),
                config=SimpleNamespace(
                    backing_disk=backing,
                    disk=disk,
                    variables=variables,
                ),
            )

            discard_overlay(vm)

            vm.stop.assert_called_once_with()
            self.assertFalse(disk.exists())
            self.assertFalse(variables.exists())
            self.assertTrue(backing.exists())

    @patch("business.install.runner.assert_disk_storage_ready")
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
                keep_passed_disk=False,
                keep_failed_disk=False,
            )
            runner._create_vm = lambda _scenario, _artifacts: vm
            runner._write_manifest = lambda *_args: None

            def interrupt(*_args, **_kwargs):
                raise KeyboardInterrupt

            runner._run_live_phase = interrupt
            interrupted_scenario = SimpleNamespace(
                id="interrupt",
                firmware=Firmware.BIOS,
                network=Network.OFFLINE,
                mok_enrollment=False,
                passwordless_sudo=False,
                automatic_login=False,
                desktop_contracts=False,
                snapshots_manager=False,
                ssh=SshPolicy.DISABLED,
                live_mode=LiveMode.TEMPORARY,
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
    def test_supervisor_enables_python_native_fault_tracebacks_by_default(self):
        with tempfile.TemporaryDirectory() as directory:
            artifacts = Path(directory) / "new-artifacts"
            with patch(
                "framework.supervisor.run_supervised_worker",
                return_value=0,
            ) as run:
                result = supervised_main(
                    Path("tests/run.py"),
                    ["--artifacts", str(artifacts)],
                )
        self.assertEqual(0, result)
        environment = run.call_args.kwargs["environment"]
        self.assertEqual("1", environment["PYTHONFAULTHANDLER"])

    def test_native_worker_crash_reclaims_separate_session_and_disk(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            artifacts = root / "artifacts"
            fault_log = root / ".worker-fault.log"
            child_pid = root / "separate-child.pid"
            helper = root / "crashing-worker.py"
            helper.write_text(
                "\n".join(
                    (
                        "import os, resource, signal, subprocess, sys",
                        "from pathlib import Path",
                        "from framework.process_lifecycle import parent_death_preexec",
                        "from framework.supervisor import configure_worker_fault_handler",
                        "resource.setrlimit(resource.RLIMIT_CORE, (0, 0))",
                        "configure_worker_fault_handler()",
                        "artifacts = Path(sys.argv[1])",
                        "pid_file = Path(sys.argv[2])",
                        "disk = artifacts / 'case' / 'target.qcow2'",
                        "disk.parent.mkdir(parents=True)",
                        "disk.write_bytes(b'disposable guest')",
                        "(disk.parent / 'live-media.raw').write_bytes(b'disposable live')",
                        "(artifacts / 'durable-evidence.txt').write_text('keep\\n')",
                        "child = subprocess.Popen(",
                        "    ('sleep', '60'),",
                        "    start_new_session=True,",
                        "    preexec_fn=parent_death_preexec(),",
                        ")",
                        "pid_file.write_text(str(child.pid))",
                        "os.kill(os.getpid(), signal.SIGSEGV)",
                    )
                )
                + "\n",
                encoding="utf-8",
            )
            environment = os.environ.copy()
            environment["PYTHONPATH"] = str(ROOT)
            environment[FAULT_LOG_ENV] = str(fault_log)
            error = io.StringIO()
            with patch("sys.stderr", error):
                result = run_supervised_worker(
                    (sys.executable, str(helper), str(artifacts), str(child_pid)),
                    environment=environment,
                    artifacts=artifacts,
                    artifacts_preexisting=False,
                    workspace_token="a" * 16,
                    retain_disks=False,
                    fault_log=fault_log,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
            self.assertEqual(128 + signal.SIGSEGV, result)
            self.assertIn("SIGSEGV", error.getvalue())
            self.assertFalse((artifacts / "case" / "target.qcow2").exists())
            self.assertFalse((artifacts / "case" / "live-media.raw").exists())
            self.assertEqual(
                "keep\n",
                (artifacts / "durable-evidence.txt").read_text(encoding="utf-8"),
            )
            crash = (artifacts / "worker-fault.log").read_text(encoding="utf-8")
            self.assertIn("Fatal Python error: Segmentation fault", crash)
            self.assertIn("crashing-worker.py", crash)
            pid = int(child_pid.read_text(encoding="ascii"))
            deadline = time.monotonic() + 5
            while Path(f"/proc/{pid}").exists() and time.monotonic() < deadline:
                time.sleep(0.05)
            self.assertFalse(
                Path(f"/proc/{pid}").exists(),
                "parent-death signal left a separate-session child alive",
            )

    def test_supervisor_never_cleans_a_preexisting_artifact_root(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            disk = root / "case" / "target.qcow2"
            disk.parent.mkdir()
            disk.write_bytes(b"user-owned preexisting disk")
            live_media = disk.with_name("live-media.raw")
            live_media.write_bytes(b"user-owned preexisting live media")
            _cleanup_persistent_disks(root, preexisting=True)
            self.assertEqual(b"user-owned preexisting disk", disk.read_bytes())
            self.assertEqual(
                b"user-owned preexisting live media",
                live_media.read_bytes(),
            )

    @patch("framework.storage.shutil.disk_usage")
    def test_capacity_budgets_the_full_virtual_disk_and_reserve(self, disk_usage):
        disk_usage.return_value = SimpleNamespace(free=55 * GIB)
        with tempfile.TemporaryDirectory() as directory:
            capacity = assert_capacity(Path(directory), 40, 10)
        self.assertEqual(50 * GIB, capacity.required_bytes)
        self.assertEqual(55 * GIB, capacity.free_bytes)

    @patch("framework.storage.shutil.disk_usage")
    def test_capacity_adds_the_full_writable_live_media_budget(self, disk_usage):
        disk_usage.return_value = SimpleNamespace(free=60 * GIB)
        with tempfile.TemporaryDirectory() as directory:
            capacity = assert_capacity(
                Path(directory),
                40,
                10,
                additional_bytes=6 * GIB,
            )
        self.assertEqual(56 * GIB, capacity.required_bytes)

    @patch("framework.storage.shutil.disk_usage")
    def test_capacity_fails_before_qemu_when_host_space_is_low(self, disk_usage):
        disk_usage.return_value = SimpleNamespace(free=21 * GIB)
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(
                ConfigurationError,
                r"21\.0 GiB is free.*requires 50\.0 GiB",
            ):
                assert_capacity(Path(directory), 40, 10)

    @patch("framework.storage.shutil.disk_usage")
    @patch("framework.storage._filesystem_type", return_value="tmpfs")
    @patch("framework.storage._read_mem_available", return_value=32 * GIB)
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
                "framework.storage._ramdisk_candidates",
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

    @patch("framework.storage.shutil.disk_usage")
    @patch("framework.storage._filesystem_type", return_value="tmpfs")
    @patch("framework.storage._read_mem_available", return_value=23 * GIB)
    def test_auto_falls_back_when_ramdisk_has_no_runtime_headroom(
        self,
        _memory,
        _filesystem,
        disk_usage,
    ):
        disk_usage.return_value = SimpleNamespace(free=15 * GIB)
        with tempfile.TemporaryDirectory() as directory, patch(
            "framework.storage._ramdisk_candidates",
            return_value=(Path(directory),),
        ):
            storage = select_disk_storage(
                Path("/persistent/results/run"),
                memory_mib=8192,
            )
        self.assertFalse(storage.is_ramdisk)
        self.assertIn("startup headroom", storage.reason)

    @patch("framework.storage.shutil.disk_usage")
    @patch("framework.storage._filesystem_type", return_value="tmpfs")
    @patch("framework.storage._read_mem_available", return_value=23 * GIB)
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

    @patch("framework.storage.shutil.disk_usage")
    @patch("framework.storage._filesystem_type", return_value="tmpfs")
    @patch("framework.storage._read_mem_available", return_value=30 * GIB)
    def test_ramdisk_recheck_adds_persistent_live_media_budget(
        self,
        _memory,
        _filesystem,
        disk_usage,
    ):
        disk_usage.return_value = SimpleNamespace(free=20 * GIB)
        storage = DiskStorage(
            Path("/dev/shm/private/run"),
            "ramdisk",
            "unit test",
            qcow_limit_bytes=12 * GIB,
        )
        capacity = assert_disk_storage_ready(
            storage,
            disk_gib=40,
            filesystem_reserve_gib=10,
            memory_mib=8192,
            additional_bytes=6 * GIB,
        )
        self.assertEqual(18 * GIB, capacity.required_bytes)

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

    @patch("framework.storage._read_mem_available", return_value=16 * GIB)
    def test_auto_falls_back_when_available_memory_is_not_above_threshold(
        self,
        _memory,
    ):
        artifacts = Path("/persistent/results/run")
        storage = select_disk_storage(artifacts, memory_mib=8192)
        self.assertFalse(storage.is_ramdisk)
        self.assertEqual(artifacts, storage.root)
        self.assertIn("not above", storage.reason)

    @patch("framework.storage.shutil.disk_usage")
    @patch("framework.storage._filesystem_type", return_value="tmpfs")
    @patch("framework.storage._read_mem_available", return_value=64 * GIB)
    def test_ci_sized_tmpfs_falls_back_to_filesystem(
        self,
        _memory,
        _filesystem,
        disk_usage,
    ):
        disk_usage.return_value = SimpleNamespace(free=64 * 1024**2)
        with tempfile.TemporaryDirectory() as directory:
            with patch(
                "framework.storage._ramdisk_candidates",
                return_value=(Path(directory),),
            ):
                storage = select_disk_storage(
                    Path("/persistent/results/run"),
                    memory_mib=8192,
                )
        self.assertFalse(storage.is_ramdisk)
        self.assertIn("no writable tmpfs", storage.reason)

    @patch("framework.storage._read_mem_available", return_value=64 * GIB)
    def test_retained_debug_disk_always_uses_persistent_storage(self, _memory):
        artifacts = Path("/persistent/results/run")
        storage = select_disk_storage(
            artifacts,
            memory_mib=8192,
            retain_disk=True,
        )
        self.assertFalse(storage.is_ramdisk)
        self.assertIn("retention", storage.reason)

    @patch("framework.storage._read_mem_available", return_value=8 * GIB)
    def test_forced_ramdisk_fails_closed_when_memory_is_low(self, _memory):
        with self.assertRaisesRegex(ConfigurationError, "requested but unavailable"):
            select_disk_storage(
                Path("/persistent/results/run"),
                memory_mib=8192,
                mode="ramdisk",
            )

    def test_sigterm_is_converted_to_cleanup_interrupt_and_restored(self):
        original = signal.getsignal(signal.SIGTERM)
        with _termination_as_interrupt():
            handler = signal.getsignal(signal.SIGTERM)
            self.assertTrue(callable(handler))
            with self.assertRaises(KeyboardInterrupt):
                handler(signal.SIGTERM, None)
        self.assertIs(original, signal.getsignal(signal.SIGTERM))
