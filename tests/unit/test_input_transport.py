"""SSH, QMP input, serial transport, and visual-oracle tests."""

from unit.support import *  # noqa: F403
class SshContractTests(unittest.TestCase):
    @patch("business.install.subprocess.run")
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
    SEARCH_PROVIDER_PREFLIGHT = "\n".join(
        (
            "package=gnome-software version=50.0-1",
            "package=gnome-software-plugin-deb version=50.0-1",
            "package=packagekit version=1.3.4-3ubuntu1.1",
            "package=libpackagekit-glib2-18 version=1.3.4-3ubuntu1.1",
            "before_pid=2192 before_restarts=0 before_active=active",
            "(@as [],)",
            "after_pid=2192 after_restarts=0 after_active=active",
            "search-provider=ready pid=2192 restarts=0",
        )
    )

    def test_shell_search_provider_oracle_accepts_one_unchanged_process(self):
        _validate_search_provider_preflight(self.SEARCH_PROVIDER_PREFLIGHT, 0)

    def test_shell_search_provider_oracle_rejects_crash_then_restart(self):
        crashed = self.SEARCH_PROVIDER_PREFLIGHT.replace(
            "after_pid=2192 after_restarts=0",
            "after_pid=3791 after_restarts=1",
        ).replace(
            "search-provider=ready pid=2192 restarts=0",
            "search-provider=ready pid=3791 restarts=1",
        )
        with self.assertRaisesRegex(TestFailure, "crashed and restarted"):
            _validate_search_provider_preflight(crashed, 0)

    def test_shell_search_provider_oracle_rejects_missing_version_evidence(self):
        incomplete = self.SEARCH_PROVIDER_PREFLIGHT.replace(
            "package=packagekit version=1.3.4-3ubuntu1.1\n",
            "",
        )
        with self.assertRaisesRegex(TestFailure, "every installed package version"):
            _validate_search_provider_preflight(incomplete, 0)

    def test_shell_search_provider_preflight_rejects_an_unstable_service(self):
        runner = object.__new__(FeatureSuiteRunner)
        runner.username = "anduinostest"
        serial = Mock()
        serial.run.return_value = SimpleNamespace(
            returncode=1,
            stdout="search-provider=unstable\n",
        )
        vm = SimpleNamespace(serial=serial)
        with tempfile.TemporaryDirectory() as directory:
            artifacts = Path(directory)
            with self.assertRaisesRegex(TestFailure, "stable session state"):
                runner._stabilize_shell_search_provider(vm, artifacts)
            self.assertEqual(
                "search-provider=unstable\n\n",
                (artifacts / "shell-search-provider-preflight.txt").read_text(),
            )
        command = serial.run.call_args.args[0]
        self.assertIn("org.gnome.Shell.SearchProvider2.GetInitialResultSet", command)
        self.assertIn("MainPID", command)
        self.assertIn("NRestarts", command)
        self.assertIn("sleep 15", command)
        self.assertIn('test "$before_restarts" != 0', command)
        self.assertNotIn("for attempt in", command)

        source = _source_tree(ROOT / "business/desktop")
        body = source.split("def _run_shell_driver", 1)[1].split(
            "def _stabilize_shell_search_provider", 1
        )[0]
        self.assertLess(
            body.index("preflight_cursors = self._journal_cursors"),
            body.index("self._stabilize_shell_search_provider"),
        )
        self.assertLess(
            body.index("self._stabilize_shell_search_provider"),
            body.index('scope="shell-search-provider-preflight"'),
        )
        self.assertLess(
            body.index('scope="shell-search-provider-preflight"'),
            body.rindex("cursors = self._journal_cursors"),
        )

    def test_local_arcmenu_search_isolated_without_weakening_store_checks(self):
        configured = "\n".join(
            (
                "provider=org.gnome.Software.desktop",
                "configured=['org.gnome.Software.desktop']",
            )
        )
        runtime = "\n".join(
            (
                "provider=org.gnome.Software.desktop",
                "configured=['org.gnome.Software.desktop']",
                "before_state=inactive before_restarts=0",
                "after_load=masked after_state=inactive after_pid=0",
            )
        )
        post_action = "\n".join(
            (
                "provider=org.gnome.Software.desktop",
                "configured=['org.gnome.Software.desktop']",
                "load=masked state=inactive pid=0",
            )
        )
        _validate_local_search_provider_isolation_configuration(configured, 0)
        _validate_local_search_provider_runtime_isolation(runtime, 0)
        _validate_local_search_provider_post_action_isolation(post_action, 0)

        with self.assertRaisesRegex(TestFailure, "was not disabled"):
            _validate_local_search_provider_isolation_configuration(
                configured.replace(
                    "configured=['org.gnome.Software.desktop']",
                    "configured=@as []",
                ),
                0,
            )
        with self.assertRaisesRegex(TestFailure, "was not masked"):
            _validate_local_search_provider_runtime_isolation(
                runtime.replace("after_load=masked", "after_load=loaded"),
                0,
            )
        with self.assertRaisesRegex(TestFailure, "activated GNOME Software"):
            _validate_local_search_provider_post_action_isolation(
                post_action.replace(
                    "load=masked state=inactive pid=0",
                    "load=loaded state=active pid=2247",
                ),
                0,
            )

        source = _source_tree(ROOT / "business/desktop")
        boot = source.split("def _boot_overlay", 1)[1].split("def _check", 1)[0]
        self.assertLess(
            boot.index("self._configure_local_search_provider_isolation"),
            boot.index("_login_gdm"),
        )
        self.assertIn("vm.config.artifacts", boot)
        shell_driver = source.split("def _run_shell_driver", 1)[1].split(
            "def _configure_local_search_provider_isolation", 1
        )[0]
        self.assertIn("if mode in _LOCAL_SEARCH_DRIVER_MODES", shell_driver)
        self.assertIn("elif mode in _SOFTWARE_SEARCH_DRIVER_MODES", shell_driver)
        self.assertIn(
            "self._assert_local_search_provider_remained_isolated",
            shell_driver,
        )
        self.assertLess(
            shell_driver.index("self._assert_local_search_provider_isolation"),
            shell_driver.index("preflight_cursors = self._journal_cursors"),
        )

    def test_named_non_secret_text_request_is_strictly_parsed(self):
        self.assertEqual(
            "arcmenu-search-fixture",
            _parse_qmp_text_request(
                'serial: {"event": "qmp-text", '
                '"request": "arcmenu-search-fixture"}'
            ),
        )
        self.assertIsNone(
            _parse_qmp_text_request('{"event": "qmp-text", "request": ""}')
        )

    def test_qemu_block_flush_uses_the_open_named_node(self):
        client = QmpClient(Path("/unused-qmp-socket"))
        client.hmp = Mock(return_value="")

        client.flush_block_device("target")

        client.hmp.assert_called_once_with('qemu-io target "flush"')

    def test_qemu_block_flush_rejects_a_monitor_error(self):
        client = QmpClient(Path("/unused-qmp-socket"))
        client.hmp = Mock(return_value="Device 'target' not found")

        with self.assertRaisesRegex(ProtocolError, "failed to flush"):
            client.flush_block_device("target")

    def test_terminal_guest_requests_are_drained_after_the_command_exits(self):
        with tempfile.TemporaryDirectory() as directory:
            transcript = Path(directory) / "serial.log"
            transcript.touch()
            release = threading.Event()

            def finish_with_terminal_requests(*_args, **_kwargs):
                self.assertTrue(release.wait(timeout=1))
                with transcript.open("a", encoding="utf-8") as stream:
                    stream.write(
                        '{"event": "qmp-secret", "request": "tail-secret"}\n'
                        '{"event": "qmp-text", "request": "tail-text"}\n'
                        '{"event": "qmp-key", "request": "tail-submit", '
                        '"key": "ret"}\n'
                    )
                return CommandResult("", 0)

            serial = SimpleNamespace(
                transcript=transcript,
                run=finish_with_terminal_requests,
            )
            qmp = Mock()
            vm = SimpleNamespace(serial=serial, qmp=qmp)

            def release_during_poll(_seconds):
                release.set()
                threading.Event().wait(0.02)

            with patch("business.install.time.sleep", side_effect=release_during_poll):
                _run_with_qmp_key_requests(
                    vm,
                    "terminal-request-fixture",
                    timeout=1,
                    secret_texts={"tail-secret": "Tail-Secret-123!"},
                    text_inputs={"tail-text": "Spotify"},
                )

            self.assertEqual(
                [
                    call("Tail-Secret-123!", interval=0.06),
                    call("Spotify", interval=0.06),
                ],
                qmp.type_text.call_args_list,
            )
            qmp.send_key.assert_called_once_with("ret")

    def test_completed_host_click_is_written_to_the_request_trace(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            transcript = root / "serial.log"
            trace = root / "qmp-requests.jsonl"
            transcript.touch()
            clicked = threading.Event()

            def request_click(*_args, **_kwargs):
                with transcript.open("a", encoding="utf-8") as stream:
                    stream.write(
                        '{"event": "qmp-click", "request": "first-click", '
                        '"x_px": 64, "y_px": 312.5, "button": "left"}\n'
                    )
                self.assertTrue(clicked.wait(timeout=1))
                return CommandResult("", 0)

            serial = SimpleNamespace(transcript=transcript, run=request_click)
            qmp = Mock()
            qmp.click_pointer_pixels.side_effect = lambda *_args, **_kwargs: clicked.set()
            vm = SimpleNamespace(serial=serial, qmp=qmp)

            with patch("business.install.time.sleep", wraps=time.sleep) as sleep:
                _run_with_qmp_key_requests(
                    vm,
                    "click-fixture",
                    timeout=1,
                    request_trace=trace,
                )

            qmp.click_pointer_pixels.assert_called_once_with(
                64.0,
                312.5,
                button="left",
            )
            records = [json.loads(line) for line in trace.read_text().splitlines()]
            self.assertEqual(1, len(records))
            self.assertEqual("first-click", records[0]["request"])
            self.assertEqual("click", records[0]["kind"])
            self.assertEqual(500, records[0]["settle_ms"])
            self.assertIs(True, records[0]["completed"])
            self.assertGreaterEqual(records[0]["duration_ms"], 0)
            self.assertIn(
                call(_GUEST_QMP_CLICK_SETTLE_SECONDS),
                sleep.call_args_list,
            )

    def test_completed_host_key_is_written_to_the_request_trace(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            transcript = root / "serial.log"
            trace = root / "qmp-requests.jsonl"
            transcript.touch()
            delivered = threading.Event()

            def request_key(*_args, **_kwargs):
                with transcript.open("a", encoding="utf-8") as stream:
                    stream.write(
                        '{"event": "qmp-key", "request": "open-file-ret", '
                        '"key": "ret"}\n'
                    )
                self.assertTrue(delivered.wait(timeout=1))
                return CommandResult("", 0)

            serial = SimpleNamespace(transcript=transcript, run=request_key)
            qmp = Mock()
            qmp.send_key.side_effect = lambda *_args, **_kwargs: delivered.set()
            vm = SimpleNamespace(serial=serial, qmp=qmp)

            with patch("business.install.time.sleep", wraps=time.sleep) as sleep:
                _run_with_qmp_key_requests(
                    vm,
                    "key-fixture",
                    timeout=1,
                    request_trace=trace,
                )

            qmp.send_key.assert_called_once_with("ret")
            records = [json.loads(line) for line in trace.read_text().splitlines()]
            self.assertEqual(1, len(records))
            self.assertEqual("open-file-ret", records[0]["request"])
            self.assertEqual("key", records[0]["kind"])
            self.assertEqual("ret", records[0]["key"])
            self.assertEqual("qmp-hmp", records[0]["input_transport"])
            self.assertEqual(200, records[0]["settle_ms"])
            self.assertIs(True, records[0]["completed"])
            self.assertIn(
                call(_GUEST_QMP_KEY_SETTLE_SECONDS),
                sleep.call_args_list,
            )

    def test_completed_host_double_click_is_written_to_the_request_trace(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            transcript = root / "serial.log"
            trace = root / "qmp-requests.jsonl"
            transcript.touch()
            clicked = threading.Event()

            def request_double_click(*_args, **_kwargs):
                with transcript.open("a", encoding="utf-8") as stream:
                    stream.write(
                        '{"event": "spice-double-click", '
                        '"request": "desktop-launch", '
                        '"x_px": 64, "y_px": 312.5, '
                        '"button": "left", "clicks": 2, '
                        '"positioning_clicks": 1, '
                        '"double_click_time_ms": 400, '
                        '"bounds": [4, 292, 120, 41]}\n'
                    )
                self.assertTrue(clicked.wait(timeout=1))
                return CommandResult("", 0)

            serial = SimpleNamespace(
                transcript=transcript,
                run=request_double_click,
            )
            qmp = Mock()
            vm = SimpleNamespace(
                serial=serial,
                qmp=qmp,
                spice_socket=Path("/run/qemu/spice.sock"),
            )

            with patch("business.install.protocol.SpiceInputClient") as client_type:
                pointer = client_type.return_value.__enter__.return_value
                pointer.double_click_pointer_pixels.side_effect = (
                    lambda *_args, **_kwargs: clicked.set()
                )
                _run_with_qmp_key_requests(
                    vm,
                    "double-click-fixture",
                    timeout=1,
                    request_trace=trace,
                )

            qmp.validate_pointer_bounds.assert_called_once_with(
                64.0, 312.5, (4, 292, 120, 41)
            )
            pointer.double_click_pointer_pixels.assert_called_once_with(
                64.0,
                312.5,
                double_click_time_ms=400,
            )
            records = [json.loads(line) for line in trace.read_text().splitlines()]
            self.assertEqual(1, len(records))
            self.assertEqual("desktop-launch", records[0]["request"])
            self.assertEqual("double-click", records[0]["kind"])
            self.assertEqual(2, records[0]["clicks"])
            self.assertEqual(1, records[0]["positioning_clicks"])
            self.assertEqual(400, records[0]["double_click_time_ms"])
            self.assertEqual("spice-vdagent", records[0]["input_transport"])
            self.assertEqual(2, records[0]["client_mouse_mode"])
            self.assertIs(True, records[0]["position_coupled_to_press"])
            self.assertIs(True, records[0]["completed"])

    def test_semantic_radio_navigation_supports_the_down_arrow(self):
        self.assertIn("down", _SUPPORTED_GUEST_QMP_KEYS)
        source = _source_tree(ROOT / "assertions/guest/ui")
        radio_body = source.split("def set_radio(key: str)", 1)[1].split(
            "def dump_accessibility", 1
        )[0]
        self.assertIn('requested_key = "down"', radio_body)

    def test_desktop_context_menu_uses_a_versioned_source_validated_fallback(self):
        self.assertFalse(_guest_qmp_key_supported("end"))
        self.assertTrue(_guest_qmp_key_supported("up"))
        self.assertTrue(_guest_qmp_key_supported("meta_l-d"))
        self.assertFalse(_guest_qmp_key_supported("home"))
        source = _source_tree(ROOT / "assertions/guest/ui")
        terminal_body = source.split("def exercise_desktop_terminal", 1)[1].split(
            "def exercise_desktop_shortcut", 1
        )[0]
        self.assertIn("_desktop_terminal_keyboard_plan(evidence)", terminal_body)
        self.assertIn('f"desktop-terminal-menu-up-{number}"', terminal_body)
        self.assertIn("_ptyxis_descendant_cwds()", terminal_body)
        self.assertNotIn('"desktop-terminal-menu-end"', terminal_body)
        close_body = source.split("def _close_arcmenu", 1)[1].split(
            "def _open_arcmenu_search", 1
        )[0]
        self.assertIn("for attempt in range(2)", close_body)
        self.assertIn("_visible_shell_result(search_result)", close_body)

    def test_wifi_password_focus_recovery_supports_reverse_tab(self):
        self.assertIn("shift-tab", _SUPPORTED_GUEST_QMP_KEYS)
        self.assertTrue(_guest_qmp_key_supported("shift-tab"))

    def test_text_editor_input_and_save_use_narrowly_supported_host_keys(self):
        self.assertIn("ctrl-shift-u", _SUPPORTED_GUEST_QMP_KEYS)
        self.assertTrue(_guest_qmp_key_supported("ctrl-shift-u"))
        self.assertIn("ctrl-s", _SUPPORTED_GUEST_QMP_KEYS)
        self.assertTrue(_guest_qmp_key_supported("ctrl-s"))
        self.assertFalse(_guest_qmp_key_supported("s"))
        self.assertFalse(_guest_qmp_key_supported("ctrl-shift-s"))

    def test_arcmenu_context_targets_result_before_keyboard_menu_navigation(self):
        source = _source_tree(ROOT / "assertions/guest/ui")
        context_body = source.split("def request_search_result_context", 1)[1].split(
            "def activate_shell_context_action", 1
        )[0]
        self.assertIn('role(search_entry) != "text"', context_body)
        self.assertIn("Atspi.StateType.FOCUSED", context_body)
        self.assertIn('method="search-entry-popup-menu"', context_body)
        self.assertIn('key="shift-f10"', context_body)
        self.assertNotIn("request_node_click(", context_body)
        search_body = source.split("def _open_arcmenu_search", 1)[1].split(
            "def request_search_result_context", 1
        )[0]
        self.assertIn('role(item) == "text"', search_body)
        self.assertIn("stable_observations < 4", search_body)
        self.assertIn('"search-entry-focus"', search_body)
        activation_body = source.split("def activate_shell_context_action", 1)[
            1
        ].split("def exercise_start_button", 1)[0]
        self.assertIn('key="down"', activation_body)
        self.assertIn('key="ret"', activation_body)

    def test_localized_radio_mnemonic_is_narrowly_allowed(self):
        self.assertTrue(_guest_qmp_key_supported("alt-o"))
        self.assertTrue(_guest_qmp_key_supported("alt-f4"))
        self.assertFalse(_guest_qmp_key_supported("alt-f12"))
        self.assertFalse(_guest_qmp_key_supported("ctrl-alt-delete"))
        source = _source_tree(ROOT / "assertions/guest/ui")
        self.assertIn('method="localized-mnemonic"', source)

    def test_absolute_pointer_uses_normalized_tablet_coordinates(self):
        client = QmpClient(Path("unused"))
        client.execute = Mock(return_value={})
        client.move_pointer_absolute(0.25, 0.75)
        client.execute.assert_called_once_with(
            "input-send-event",
            {
                "device": "video0",
                "events": [
                    {"type": "abs", "data": {"axis": "x", "value": 8192}},
                    {"type": "abs", "data": {"axis": "y", "value": 24575}},
                ]
            },
        )
        with self.assertRaisesRegex(Exception, "0..1"):
            client.move_pointer_absolute(-0.1, 0.5)

    @patch("framework.qmp.time.sleep")
    def test_pointer_click_moves_then_presses_and_releases_primary_button(self, sleep):
        client = QmpClient(Path("unused"))
        client.execute = Mock(return_value={})
        client.click_pointer_absolute(0.4, 0.6)
        self.assertEqual(3, client.execute.call_count)
        move, press, release = client.execute.call_args_list
        self.assertEqual("input-send-event", move.args[0])
        self.assertEqual(
            {
                "device": "video0",
                "events": [
                    {"type": "btn", "data": {"down": True, "button": "left"}}
                ],
            },
            press.args[1],
        )
        self.assertEqual(
            {
                "device": "video0",
                "events": [
                    {"type": "btn", "data": {"down": False, "button": "left"}}
                ],
            },
            release.args[1],
        )
        self.assertEqual(
            [((0.25,), {}), ((0.06,), {})],
            [(item.args, item.kwargs) for item in sleep.call_args_list],
        )

    def test_spice_pointer_double_click_emits_two_complete_gestures(self):
        client = SpiceInputClient.__new__(SpiceInputClient)
        client._inputs = Mock()
        client._run_for = Mock()

        client.double_click_pointer_pixels(
            64.0,
            312.5,
            double_click_time_ms=400,
        )

        self.assertEqual(
            [call(64, 312, 0, 0), call(64, 312, 0, 0), call(64, 312, 0, 0)],
            client._inputs.position.call_args_list,
        )
        self.assertEqual(3, client._inputs.button_press.call_count)
        self.assertEqual(3, client._inputs.button_release.call_count)
        self.assertEqual(
            [call(1, 0), call(1, 0), call(1, 0)],
            client._inputs.button_press.call_args_list,
        )
        self.assertEqual(
            [0.06, 0.06, 0.60, 0.06, 0.12, 0.06, 0.25],
            [item.args[0] for item in client._run_for.call_args_list],
        )

    def test_spice_pointer_connection_requires_the_guest_agent(self):
        client = SpiceInputClient.__new__(SpiceInputClient)
        client._main = Mock()
        client._main.get_property.side_effect = lambda name: {
            "mouse-mode": 2,
            "agent-connected": False,
        }[name]
        with self.assertRaisesRegex(ProtocolError, "guest agent"):
            client._require_agent()

    def test_spice_pointer_mapping_settles_then_revalidates_readiness(self):
        client = SpiceInputClient.__new__(SpiceInputClient)
        client._main = Mock()
        client._main.get_property.side_effect = lambda name: {
            "mouse-mode": 2,
            "agent-connected": True,
        }[name]
        client._run_for = Mock()

        client._settle_pointer_mapping()

        client._run_for.assert_called_once_with(1.0)
        self.assertEqual(
            [call("agent-connected"), call("mouse-mode")],
            client._main.get_property.call_args_list,
        )

    def test_spice_pointer_mapping_rejects_agent_loss_during_settle(self):
        client = SpiceInputClient.__new__(SpiceInputClient)
        client._main = Mock()
        client._main.get_property.side_effect = lambda name: {
            "mouse-mode": 2,
            "agent-connected": False,
        }[name]
        client._run_for = Mock()

        with self.assertRaisesRegex(ProtocolError, "guest agent"):
            client._settle_pointer_mapping()

        client._run_for.assert_called_once_with(1.0)
        client._main.get_property.assert_called_once_with("agent-connected")

    def test_spice_boot_keyboard_uses_strict_set1_scancodes_without_agent(self):
        client = SpiceInputClient.__new__(SpiceInputClient)
        client._inputs = Mock()
        client._run_for = Mock()

        client.type_boot_text("C_:/@", interval=0.01)
        client.send_boot_key("c")
        client.send_boot_key("ret")

        self.assertEqual(
            [call(0x2A), call(0x2A), call(0x2A), call(0x2A)],
            client._inputs.key_press.call_args_list,
        )
        self.assertEqual(
            [
                call(0x2E),
                call(0x0C),
                call(0x27),
                call(0x35),
                call(0x03),
                call(0x2E),
                call(0x1C),
            ],
            client._inputs.key_press_and_release.call_args_list,
        )
        self.assertEqual(
            [call(0x2A), call(0x2A), call(0x2A), call(0x2A)],
            client._inputs.key_release.call_args_list,
        )
        self.assertEqual(7, client._run_for.call_count)
        client._inputs.reset_mock()
        with self.assertRaisesRegex(ProtocolError, "Unsupported boot text"):
            client.type_boot_text("safe?")
        client._inputs.key_press_and_release.assert_not_called()
        with self.assertRaisesRegex(ProtocolError, "Unsupported boot key"):
            client.send_boot_key("f10")

    def test_spice_pointer_rejects_input_before_connection(self):
        client = SpiceInputClient.__new__(SpiceInputClient)
        client._inputs = None
        with self.assertRaisesRegex(ProtocolError, "not connected"):
            client.double_click_pointer_pixels(
                64.0,
                312.5,
                double_click_time_ms=400,
            )

    def test_spice_pointer_rejects_server_mouse_mode(self):
        client = SpiceInputClient.__new__(SpiceInputClient)
        client._main = Mock()
        client._main.get_property.return_value = 1
        with self.assertRaisesRegex(ProtocolError, "client mouse mode"):
            client._require_client_mouse_mode()

    @patch("framework.qmp.time.sleep")
    def test_pointer_context_click_uses_the_secondary_button(self, _sleep):
        client = QmpClient(Path("unused"))
        client.execute = Mock(return_value={})
        client.click_pointer_absolute(0.4, 0.6, button="right")
        press, release = client.execute.call_args_list[1:]
        self.assertEqual("right", press.args[1]["events"][0]["data"]["button"])
        self.assertEqual("right", release.args[1]["events"][0]["data"]["button"])
        with self.assertRaisesRegex(ProtocolError, "Unsupported pointer button"):
            client.click_pointer_absolute(0.4, 0.6, button="middle")

    def test_atspi_derived_pointer_request_is_strictly_parsed(self):
        line = (
            'serial-prefix {"event": "qmp-click", "request": "accounts-add-user", '
            '"target": "add_user", "x_px": 1183.5, "y_px": 776.0, '
            '"screen": [1282, 848]}'
        )
        self.assertEqual(
            ("accounts-add-user", 1183.5, 776.0, "left"),
            _parse_qmp_click_request(line),
        )
        self.assertEqual(
            ("taskbar-context", 640.0, 780.0, "right"),
            _parse_qmp_click_request(
                '{"event": "qmp-click", "request": "taskbar-context", '
                '"x_px": 640, "y_px": 780, "button": "right"}'
            ),
        )
        self.assertIsNone(
            _parse_qmp_click_request(
                '{"event": "qmp-click", "request": "desktop-launch", '
                '"x_px": 64, "y_px": 344, "click_count": 2}'
            ),
        )
        self.assertIsNone(
            _parse_qmp_click_request(
                '{"event": "qmp-click", "request": "off-screen", '
                '"x_px": -1, "y_px": 500}'
            )
        )
        self.assertIsNone(
            _parse_qmp_click_request(
                '{"event": "qmp-click", "request": "missing-y", "x_px": 500}'
            )
        )
        self.assertIsNone(
            _parse_qmp_click_request(
                '{"event": "qmp-click", "request": "bad-button", '
                '"x_px": 500, "y_px": 500, "button": "middle"}'
            )
        )
        self.assertIsNone(
            _parse_qmp_click_request(
                '{"event": "qmp-click", "request": "bad-count", '
                '"x_px": 500, "y_px": 500, "click_count": 3}'
            )
        )

    def test_atspi_double_click_request_requires_exactly_two_primary_clicks(self):
        valid = (
            'serial-prefix {"event": "spice-double-click", '
            '"request": "desktop-launch", "x_px": 64, "y_px": 312.5, '
            '"button": "left", "clicks": 2, '
            '"positioning_clicks": 1, "double_click_time_ms": 400, '
            '"bounds": [4, 292, 120, 41]}'
        )
        self.assertEqual(
            ("desktop-launch", 64.0, 312.5, (4, 292, 120, 41), 400),
            _parse_spice_double_click_request(valid),
        )
        self.assertIsNone(
            _parse_spice_double_click_request(
                valid.replace('"clicks": 2', '"clicks": 1')
            )
        )
        self.assertIsNone(
            _parse_spice_double_click_request(
                valid.replace('"button": "left"', '"button": "right"')
            )
        )
        self.assertIsNone(
            _parse_spice_double_click_request(
                valid.replace('"positioning_clicks": 1', '"positioning_clicks": 0')
            )
        )
        self.assertIsNone(
            _parse_spice_double_click_request(
                valid.replace('"x_px": 64', '"x_px": 63')
            )
        )

    def test_atspi_pixels_use_qemu_framebuffer_not_shell_stage_size(self):
        client = QmpClient(Path("unused"))
        client.framebuffer_size = Mock(return_value=(1280, 800))
        client.click_pointer_absolute = Mock()
        client.click_pointer_pixels(1183.5, 776.0)
        client.click_pointer_absolute.assert_called_once_with(
            1183.5 / 1280,
            776 / 800,
            button="left",
        )

        client.click_pointer_absolute.reset_mock()
        client.click_pointer_pixels(100, 200, button="right")
        client.click_pointer_absolute.assert_called_once_with(
            100 / 1280,
            200 / 800,
            button="right",
        )

        # Failure injection: the same Y coordinate would look valid against
        # GNOME Shell's reported 848-pixel stage, but must fail against the
        # real 700-pixel QEMU framebuffer.
        client.framebuffer_size = Mock(return_value=(1280, 700))
        with self.assertRaisesRegex(Exception, "outside the QEMU framebuffer"):
            client.click_pointer_pixels(1183.5, 776.0)

    def test_qemu_ppm_dimensions_reject_a_malformed_screendump(self):
        with tempfile.TemporaryDirectory() as directory:
            valid = Path(directory) / "valid.ppm"
            valid.write_bytes(b"P6\n# qemu\n1280 800\n255\n")
            self.assertEqual((1280, 800), _ppm_dimensions(valid))
            valid.write_bytes(b"not-a-ppm\n")
            with self.assertRaisesRegex(Exception, "invalid PPM header"):
                _ppm_dimensions(valid)

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

    def test_nautilus_activation_never_trusts_an_atspi_action_return(self):
        source = _source_tree(ROOT / "assertions/guest/ui")
        body = source.split("def _open_download_in_nautilus", 1)[1].split(
            "def verify_appimage_file", 1
        )[0]
        self.assertNotIn("Atspi.generate_mouse_event", body)
        self.assertNotIn("perform_action", body)
        self.assertIn("request_node_double_click", body)
        self.assertIn('method="selected-item-qmp-enter"', body)
        self.assertIn("bounds.x <= 0", body)
        self.assertIn("bounds.y <= 0", body)

    def test_secret_request_contains_no_secret_material(self):
        line = '{"event": "qmp-secret", "request": "polkit-password"}'
        self.assertEqual("polkit-password", _parse_qmp_secret_request(line))
        self.assertNotIn("AnduinOS-Test", line)

    def test_named_secret_requests_are_resolved_without_a_shared_password(self):
        values = {
            "current": "old-password",
            "replacement": "new-password",
        }
        self.assertEqual(
            "old-password",
            _resolve_qmp_secret("current", secret_text=None, secret_texts=values),
        )
        self.assertEqual(
            "new-password",
            _resolve_qmp_secret(
                "replacement", secret_text=None, secret_texts=values
            ),
        )
        with self.assertRaisesRegex(TestFailure, "missing"):
            _resolve_qmp_secret("missing", secret_text=None, secret_texts=values)


class SerialTransportTests(unittest.TestCase):
    def test_run_uploads_long_scripts_before_executing_them(self):
        console = SerialConsole(Path("unused"), Path("unused"), timeout=1)
        script = "printf 'one sufficiently long assertion line\\n'\n" * 100
        uploaded = {}

        def capture_upload(source, destination, mode=0o600):
            uploaded["content"] = source.read_text(encoding="utf-8")
            uploaded["destination"] = destination
            uploaded["mode"] = mode

        with patch.object(console, "upload", side_effect=capture_upload), patch.object(
            console,
            "_run_inline",
            return_value=CommandResult(stdout="complete", returncode=0),
        ) as run_inline:
            result = console.run(script)

        self.assertEqual(script, uploaded["content"])
        self.assertEqual(0o700, uploaded["mode"])
        self.assertRegex(
            uploaded["destination"],
            r"^/tmp/anduinos-serial-run-[0-9a-f]+\.sh$",
        )
        execution = run_inline.call_args_list[0].args[0]
        self.assertIn(f"/bin/bash {uploaded['destination']}", execution)
        self.assertEqual(CommandResult(stdout="complete", returncode=0), result)

    def test_run_waits_for_the_complete_return_code_line(self):
        with tempfile.TemporaryDirectory() as directory:
            transcript = Path(directory) / "serial.log"
            reader, writer = socket.socketpair()
            console = SerialConsole(Path("unused"), transcript, timeout=1)
            console._socket = reader
            console._log = transcript.open("ab", buffering=0)
            failures = []

            def emulate_split_return_code():
                try:
                    command = bytearray()
                    while not command.endswith(b"\n"):
                        command.extend(writer.recv(65536))
                    token = re.search(
                        rb"__ANDUINOS_BEGIN_([0-9a-f]+)__",
                        bytes(command),
                    )
                    if token is None:
                        raise AssertionError("serial command marker is missing")
                    value = token.group(1)
                    writer.sendall(
                        b"__ANDUINOS_BEGIN_" + value
                        + b"__\noutput\n__ANDUINOS_END_" + value
                        + b"__:14"
                    )
                    time.sleep(0.05)
                    writer.sendall(b"1\r\n")
                except BaseException as error:
                    failures.append(error)

            thread = threading.Thread(target=emulate_split_return_code)
            thread.start()
            try:
                result = console.run("exit 141", check=False)
            finally:
                thread.join(timeout=1)
                console.close()
                writer.close()
            self.assertEqual([], failures)
            self.assertEqual(141, result.returncode)
            self.assertEqual("output", result.stdout)

    def test_wait_for_shell_never_sends_a_probe_to_firmware_or_grub(self):
        with tempfile.TemporaryDirectory() as directory:
            transcript = Path(directory) / "serial.log"
            reader, writer = socket.socketpair()
            console = SerialConsole(Path("unused"), transcript, timeout=0.2)
            console._socket = reader
            console._log = transcript.open("ab", buffering=0)
            try:
                with self.assertRaisesRegex(
                    ProtocolError,
                    "no command was sent to firmware or GRUB",
                ):
                    console.wait_for_shell(timeout=0.2)
                readable, _, _ = select.select([writer], [], [], 0)
                self.assertEqual([], readable)
            finally:
                console.close()
                writer.close()

    def test_wait_for_shell_probes_only_after_kernel_console_marker(self):
        with tempfile.TemporaryDirectory() as directory:
            transcript = Path(directory) / "serial.log"
            reader, writer = socket.socketpair()
            console = SerialConsole(Path("unused"), transcript, timeout=2)
            console._socket = reader
            console._log = transcript.open("ab", buffering=0)
            server_failures = []
            received_commands = []

            def emulate_debug_shell():
                try:
                    readable, _, _ = select.select([writer], [], [], 0.1)
                    if readable:
                        raise AssertionError("shell probe arrived while GRUB owned serial")
                    writer.sendall(
                        b"[    0.015] Kernel command line: console=ttyS0,115200\n"
                    )
                    readable, _, _ = select.select([writer], [], [], 0.1)
                    if readable:
                        raise AssertionError(
                            "shell probe arrived before Bash owned serial"
                        )
                    writer.sendall(
                        b"servicename=debug-shell.service;type=service\n"
                    )
                    for _ in range(2):
                        command = bytearray()
                        while not command.endswith(b"\n"):
                            command.extend(writer.recv(65536))
                        received_commands.append(bytes(command))
                        token = re.search(
                            rb"__ANDUINOS_BEGIN_([0-9a-f]+)__",
                            bytes(command),
                        )
                        if token is None:
                            raise AssertionError("serial command marker is missing")
                        value = token.group(1)
                        writer.sendall(
                            b"__ANDUINOS_BEGIN_"
                            + value
                            + b"__\n\n__ANDUINOS_END_"
                            + value
                            + b"__:0\n"
                        )
                except BaseException as error:  # reported by the test thread
                    server_failures.append(error)

            thread = threading.Thread(target=emulate_debug_shell)
            thread.start()
            try:
                try:
                    # ARM boot consumes this passive boundary after leaving its
                    # PCI GRUB console. The shell handshake must remember it.
                    console.wait_for_kernel_console(timeout=2)
                    console.wait_for_shell(timeout=2)
                except ProtocolError:
                    thread.join(timeout=2)
                    if server_failures:
                        raise server_failures[0]
                    raise
                thread.join(timeout=2)
            finally:
                console.close()
                writer.close()
            self.assertFalse(thread.is_alive())
            self.assertEqual([], server_failures)
            self.assertEqual(2, len(received_commands))
            self.assertTrue(
                all(command.endswith(b"\r\n") for command in received_commands)
            )

    def test_bootloader_line_is_bounded_ascii_and_rejects_injection(self):
        with tempfile.TemporaryDirectory() as directory:
            transcript = Path(directory) / "serial.log"
            reader, writer = socket.socketpair()
            console = SerialConsole(Path("unused"), transcript, timeout=1)
            console._socket = reader
            console._log = transcript.open("ab", buffering=0)
            try:
                console.send_bootloader_line(
                    "linux /LiveOS/vmlinuz locale=zh_CN.UTF-8 "
                    "console=ttyAMA0,115200 "
                    "systemd.mask=serial-getty@ttyAMA0.service"
                )
                self.assertEqual(
                    b"linux /LiveOS/vmlinuz locale=zh_CN.UTF-8 "
                    b"console=ttyAMA0,115200 "
                    b"systemd.mask=serial-getty@ttyAMA0.service\n",
                    writer.recv(4096),
                )
                for unsafe in ("boot\nreboot", "boot; reboot", "x" * 4097, ""):
                    with self.subTest(value=unsafe[:20]):
                        with self.assertRaisesRegex(ProtocolError, "Unsafe"):
                            console.send_bootloader_line(unsafe)
                readable, _, _ = select.select([writer], [], [], 0)
                self.assertEqual([], readable)
            finally:
                console.close()
                writer.close()

    def test_quiet_boot_uses_debug_shell_unit_as_passive_handoff(self):
        with tempfile.TemporaryDirectory() as directory:
            transcript = Path(directory) / "serial.log"
            reader, writer = socket.socketpair()
            console = SerialConsole(Path("unused"), transcript, timeout=1)
            console._socket = reader
            console._log = transcript.open("ab", buffering=0)
            writer.sendall(
                b"GNU GRUB 2.14\nservicename=debug-shell.service;type=service\n"
            )
            try:
                console._wait_for_kernel_console(time.monotonic() + 1)
                self.assertTrue(console._debug_shell_ready)
                readable, _, _ = select.select([writer], [], [], 0)
                self.assertEqual([], readable)
            finally:
                console.close()
                writer.close()

    def test_kernel_fatal_oracle_catches_early_zstd_decompression_failure(self):
        self.assertEqual(
            "ZSTD-compressed data is corrupt",
            _fatal_kernel_marker(
                b"EFI stub: WARNING: Decompression failed: "
                b"ZSTD-compressed data is corrupt\n"
            ),
        )

    def test_kernel_oops_oracle_drains_the_following_call_trace(self):
        with tempfile.TemporaryDirectory() as directory:
            transcript = Path(directory) / "serial.log"
            reader, writer = socket.socketpair()
            console = SerialConsole(Path("unused"), transcript)
            console._socket = reader
            console._log = transcript.open("ab", buffering=0)
            released = threading.Event()

            def delayed_trace() -> None:
                # Reproduce a loaded VM where the header arrives well before
                # the diagnostic body.  The old 350 ms idle window discarded
                # precisely the RIP needed to triage a real guest Oops.
                time.sleep(0.5)
                writer.sendall(
                    b"protection fault\nRIP: 0010:test_fault+0x1/0x2\n"
                    b"Call Trace:\n test_caller+0x3/0x4\n---[ end trace ]---\n"
                )
                released.set()

            sender = threading.Thread(target=delayed_trace, daemon=True)
            sender.start()
            try:
                with self.assertRaisesRegex(TestFailure, "Call Trace"):
                    console._record_chunk(b"[  12.0] Oops: general ")
            finally:
                sender.join(timeout=2)
                console.close()
                writer.close()

            self.assertTrue(released.is_set())
            evidence = transcript.read_bytes()
            self.assertIn(b"Oops: general protection fault", evidence)
            self.assertIn(b"test_caller", evidence)

    def test_kernel_fatal_oracle_catches_split_soft_lockup_marker(self):
        first = b"watchdog: BUG: soft "
        second = b"lockup - CPU#3 stuck for 26s!"
        self.assertIsNone(_fatal_kernel_marker(first))
        self.assertEqual(
            "watchdog: BUG: soft lockup",
            _fatal_kernel_marker(first + second),
        )

    def test_kernel_fatal_oracle_catches_oops_before_watchdog_fallout(self):
        first = b"[   87.132877] Oo"
        second = b"ps: general protection fault [#1] SMP NOPTI\n"
        self.assertIsNone(_fatal_kernel_marker(first))
        self.assertEqual("Oops: ", _fatal_kernel_marker(first + second))

    def test_kernel_fatal_oracle_rejects_a_dead_acceptance_input_controller(self):
        self.assertEqual(
            "xHCI host controller not responding, assume dead",
            _fatal_kernel_marker(
                b"xhci_hcd 0000:00:04.0: xHCI host controller not responding, "
                b"assume dead\n"
            ),
        )

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
            console.upload(
                source,
                "/tmp/anduinos-serial-run-0123456789abcdef0123456789abcdef.sh",
                0o755,
            )
        self.assertGreater(len(console.scripts), 1000)
        self.assertLessEqual(max(map(len, console.scripts)), 2048)
        self.assertIn(": > ", console.scripts[0])
        self.assertIn("if [ \"$current\" -eq \"$next\" ]", console.scripts[1])
        self.assertIn("sha256sum", console.scripts[1])
        self.assertIn("chmod 755", console.scripts[-1])
        self.assertIn("mv ", console.scripts[-1])

    def test_download_retries_a_frame_contaminated_by_kernel_console_output(self):
        payload = bytes(range(256)) * 300
        with tempfile.TemporaryDirectory() as directory:
            destination = Path(directory) / "cursor.png"
            console = _DownloadCaptureConsole(payload, corrupt_first_chunk=True)
            self.assertTrue(console.download("/run/cursor.png", destination))
            self.assertEqual(payload, destination.read_bytes())
        self.assertGreater(console.chunk_calls, 4)
        self.assertEqual(1, console.corruptions_injected)

    def test_download_fails_closed_when_every_frame_is_contaminated(self):
        payload = b"cursor-plane" * 2048
        with tempfile.TemporaryDirectory() as directory:
            destination = Path(directory) / "cursor.png"
            console = _DownloadCaptureConsole(payload, corrupt_every_chunk=True)
            with self.assertRaisesRegex(
                ProtocolError, "uncorrupted serial download frame"
            ):
                console.download("/run/cursor.png", destination)
            self.assertFalse(destination.exists())


class VisualOracleTests(unittest.TestCase):
    def test_grub_top_menu_waits_for_three_stable_frames(self):
        editor = object.__new__(_GraphicalGrubMenuEditor)
        editor.qmp = Mock()
        editor.current_frame = None
        editor.capture = Mock(
            side_effect=[
                Path("painting.ppm"),
                Path("stable-1.ppm"),
                Path("stable-2.ppm"),
                Path("stable-3.ppm"),
            ]
        )
        ticks = iter(range(100))

        def layout(frame):
            return SimpleNamespace(
                visible_unselected_entries=3,
                highlight_center=(70 if frame.name == "painting.ppm" else 80),
            )

        def difference(first, second):
            return 200 if first.name == "painting.ppm" else 0

        with (
            patch("framework.grub.time.monotonic", side_effect=lambda: next(ticks)),
            patch("framework.grub.time.sleep"),
            patch("framework.grub.grub_menu_layout", side_effect=layout),
            patch("framework.grub.grub_frame_difference", side_effect=difference),
        ):
            editor.wait_for_top_menu(30)

        self.assertEqual(Path("stable-3.ppm"), editor.current_frame)

    def test_signed_grub_locale_menu_may_finish_after_ten_seconds(self):
        editor = object.__new__(_GraphicalGrubMenuEditor)
        editor.qmp = Mock()
        editor.current_frame = Path("top-menu.ppm")
        editor.capture = Mock(
            side_effect=[Path("top-menu.ppm")] * 12
            + [Path("locale-menu.ppm")]
        )
        ticks = iter(range(100))

        def layout(frame):
            return SimpleNamespace(
                visible_unselected_entries=(
                    8 if frame.name == "locale-menu.ppm" else 3
                )
            )

        with (
            patch("framework.grub.time.monotonic", side_effect=lambda: next(ticks)),
            patch("framework.grub.time.sleep"),
            patch("framework.grub.grub_menu_layout", side_effect=layout),
        ):
            editor.enter_language_submenu()

        editor.qmp.send_key.assert_called_once_with("ret")
        self.assertEqual(Path("locale-menu.ppm"), editor.current_frame)

    def test_grub_timeout_cancel_moves_and_restores_top_selection(self):
        editor = object.__new__(_GraphicalGrubMenuEditor)
        editor.qmp = Mock()
        editor.current_frame = Path("top.ppm")
        editor.capture = Mock(
            side_effect=[Path("top.ppm")] * 12
            + [Path("moved.ppm")]
            + [Path("moved.ppm")] * 12
            + [Path("restored.ppm")]
        )
        ticks = iter(range(100))

        def layout(frame):
            centers = {"top.ppm": 80, "moved.ppm": 100, "restored.ppm": 80}
            return SimpleNamespace(
                visible_unselected_entries=3,
                highlight_center=centers[frame.name],
            )

        with (
            patch("framework.grub.time.monotonic", side_effect=lambda: next(ticks)),
            patch("framework.grub.time.sleep"),
            patch("framework.grub.grub_menu_layout", side_effect=layout),
        ):
            editor.cancel_timeout()

        self.assertEqual(
            [call("down"), call("up")], editor.qmp.send_key.call_args_list
        )
        self.assertEqual(Path("restored.ppm"), editor.current_frame)

    def test_grub_editor_waits_for_stable_wrapped_command_content(self):
        editor = object.__new__(_GraphicalGrubMenuEditor)
        editor.qmp = Mock()
        editor.current_frame = Path("locale-menu.ppm")
        editor.capture = Mock(
            side_effect=[
                Path("partial-1.ppm"),
                Path("partial-2.ppm"),
                Path("full-1.ppm"),
                Path("full-2.ppm"),
                Path("full-3.ppm"),
            ]
        )
        ticks = iter(range(100))

        def layout(frame):
            return SimpleNamespace(
                visible_command_lines=(3 if frame.name.startswith("partial") else 5)
            )

        def difference(first, second):
            return 200 if first.name == "locale-menu.ppm" else 0

        with (
            patch("framework.grub.time.monotonic", side_effect=lambda: next(ticks)),
            patch("framework.grub.time.sleep"),
            patch("framework.grub.grub_editor_layout", side_effect=layout),
            patch("framework.grub.grub_frame_difference", side_effect=difference),
        ):
            editor.open_editor()

        editor.qmp.send_key.assert_called_once_with("e")
        self.assertEqual(Path("full-3.ppm"), editor.current_frame)

    def test_grub_editor_down_waits_for_delayed_cursor_motion(self):
        editor = object.__new__(_GraphicalGrubMenuEditor)
        editor.qmp = Mock()
        editor.current_frame = Path("editor.ppm")
        editor._editor_cursor_y = 80
        editor.capture = Mock(
            side_effect=[Path(f"waiting-{index}.ppm") for index in range(12)]
            + [Path("cursor-112.ppm")]
        )
        ticks = iter(range(100))

        with (
            patch("framework.grub.time.monotonic", side_effect=lambda: next(ticks)),
            patch("framework.grub.time.sleep"),
            patch("framework.grub.grub_editor_layout", return_value=SimpleNamespace()),
            patch(
                "framework.grub.grub_editor_left_cursor_y",
                side_effect=[None] * 12 + [112],
            ),
            patch("framework.grub.grub_frame_difference", return_value=24),
        ):
            editor.move_editor_cursor_down()

        editor.qmp.send_key.assert_called_once_with("down")
        self.assertEqual(112, editor._editor_cursor_y)
        self.assertEqual(Path("cursor-112.ppm"), editor.current_frame)

    def test_grub_editor_down_requires_a_pre_key_cursor_baseline(self):
        editor = object.__new__(_GraphicalGrubMenuEditor)
        editor.qmp = Mock()
        editor.current_frame = Path("editor.ppm")
        editor._editor_cursor_y = None
        editor.capture = Mock(
            side_effect=[Path("blink-off.ppm"), Path("baseline.ppm"), Path("moved.ppm")]
        )
        ticks = iter(range(100))

        with (
            patch("framework.grub.time.monotonic", side_effect=lambda: next(ticks)),
            patch("framework.grub.time.sleep"),
            patch("framework.grub.grub_editor_layout", return_value=SimpleNamespace()),
            patch(
                "framework.grub.grub_editor_left_cursor_y",
                side_effect=[None, 80, 112],
            ),
            patch("framework.grub.grub_frame_difference", return_value=24),
        ):
            editor.move_editor_cursor_down()

        editor.qmp.send_key.assert_called_once_with("down")
        self.assertEqual(112, editor._editor_cursor_y)

    def test_grub_editor_down_accepts_real_cursor_above_false_static_baseline(self):
        editor = object.__new__(_GraphicalGrubMenuEditor)
        editor.qmp = Mock()
        editor.current_frame = Path("false-static-baseline.ppm")
        editor._editor_cursor_y = 184
        editor.capture = Mock(return_value=Path("real-cursor-113.ppm"))
        ticks = iter(range(100))

        with (
            patch("framework.grub.time.monotonic", side_effect=lambda: next(ticks)),
            patch("framework.grub.time.sleep"),
            patch("framework.grub.grub_editor_layout", return_value=SimpleNamespace()),
            patch("framework.grub.grub_editor_left_cursor_y", return_value=113),
            patch("framework.grub.grub_frame_difference", return_value=24),
        ):
            editor.move_editor_cursor_down()

        editor.qmp.send_key.assert_called_once_with("down")
        self.assertEqual(113, editor._editor_cursor_y)
        self.assertEqual(Path("real-cursor-113.ppm"), editor.current_frame)

    def test_grub_editor_end_waits_for_left_cursor_to_disappear(self):
        editor = object.__new__(_GraphicalGrubMenuEditor)
        editor.qmp = Mock()
        editor.current_frame = Path("cursor-left.ppm")
        editor._editor_cursor_y = 151
        editor.capture = Mock(
            side_effect=[Path(f"waiting-{index}.ppm") for index in range(12)]
            + [Path("cursor-end.ppm")]
        )
        ticks = iter(range(100))

        with (
            patch("framework.grub.time.monotonic", side_effect=lambda: next(ticks)),
            patch("framework.grub.time.sleep"),
            patch("framework.grub.grub_editor_layout", return_value=SimpleNamespace()),
            patch(
                "framework.grub.grub_editor_left_cursor_y",
                side_effect=[151] * 12 + [None],
            ),
            patch(
                "framework.grub.grub_frame_difference",
                return_value=24,
            ),
        ):
            editor.move_editor_cursor_to_end()

        editor.qmp.send_key.assert_called_once_with("end")
        self.assertIsNone(editor._editor_cursor_y)
        self.assertEqual(Path("cursor-end.ppm"), editor.current_frame)

    def test_grub_editor_end_ignores_cursor_like_stroke_on_wrapped_row(self):
        editor = object.__new__(_GraphicalGrubMenuEditor)
        editor.qmp = Mock()
        editor.current_frame = Path("cursor-left.ppm")
        editor._editor_cursor_y = 151
        editor.capture = Mock(return_value=Path("cursor-end-wrapped.ppm"))
        ticks = iter(range(100))

        with (
            patch("framework.grub.time.monotonic", side_effect=lambda: next(ticks)),
            patch("framework.grub.time.sleep"),
            patch("framework.grub.grub_editor_layout", return_value=SimpleNamespace()),
            patch("framework.grub.grub_editor_left_cursor_y", return_value=184),
            patch("framework.grub.grub_frame_difference", return_value=24),
        ):
            editor.move_editor_cursor_to_end()

        editor.qmp.send_key.assert_called_once_with("end")
        self.assertIsNone(editor._editor_cursor_y)
        self.assertEqual(Path("cursor-end-wrapped.ppm"), editor.current_frame)

    def test_installer_disk_selection_excludes_live_media_partitions(self):
        source = (ROOT / "assertions/guest/ui/installer.py").read_text(
            encoding="utf-8"
        )
        body = source.split('wait_page("disk", 120)', 1)[1].split(
            'wait_page("strategy")', 1
        )[0]
        self.assertIn(r"^/dev/(?:vda|nvme\d+n\d+)\s+·", body)
        self.assertNotIn('"/dev/sda"', body)
        self.assertIn('role(item) not in {"toggle button", "button"}', body)
        self.assertNotIn('"table cell"', body)
        self.assertIn('selection_method="atspi-action"', body)

    def test_grub_verified_typing_waits_for_every_character_repaint(self):
        editor = object.__new__(_GraphicalGrubMenuEditor)
        editor.qmp = Mock()
        editor.current_frame = Path("start.ppm")
        editor._editor_cursor_y = None
        editor.capture = Mock(
            side_effect=[Path("space.ppm"), Path("letter.ppm")]
        )
        ticks = iter(range(100))

        with (
            patch("framework.grub.time.monotonic", side_effect=lambda: next(ticks)),
            patch("framework.grub.time.sleep"),
            patch("framework.grub.grub_editor_layout", return_value=SimpleNamespace()),
            patch("framework.grub.grub_frame_difference", return_value=24),
        ):
            editor.type_text_verified(" c")

        self.assertEqual(
            [call(" ", interval=0), call("c", interval=0)],
            editor.qmp.type_text.call_args_list,
        )
        self.assertEqual(Path("letter.ppm"), editor.current_frame)

    def test_grub_editor_oracle_requires_border_and_command_lines(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            frame = root / "editor.ppm"
            missing = root / "missing.ppm"
            crowded = root / "crowded-menu.ppm"
            cursor = root / "cursor.ppm"
            wrapped = root / "wrapped-editor.ppm"
            image = Image.new("RGB", (1280, 800), "black")
            draw = ImageDraw.Draw(image)
            draw.rectangle((12, 67, 1267, 675), outline=(190, 190, 190), width=2)
            draw.text((14, 82), "setparams 'Simplified Chinese'", fill="white")
            draw.text((80, 120), "set gfxpayload=auto", fill="white")
            draw.text((80, 140), "linux /LiveOS/vmlinuz", fill="white")
            draw.text((80, 160), "initrd /LiveOS/initrd", fill="white")
            image.save(frame)
            image_without_cursor = Image.new("RGB", (1280, 800), "black")
            ImageDraw.Draw(image_without_cursor).rectangle(
                (12, 67, 1267, 675),
                outline=(190, 190, 190),
                width=2,
            )
            image_without_cursor.save(missing)
            crowded_menu = Image.new("RGB", (1280, 800), "black")
            crowded_draw = ImageDraw.Draw(crowded_menu)
            crowded_draw.rectangle(
                (12, 67, 1267, 675), outline=(190, 190, 190), width=2
            )
            for index in range(20):
                crowded_draw.text(
                    (24, 82 + index * 24),
                    f"Locale entry {index}",
                    fill="white",
                )
            crowded_menu.save(crowded)
            layout = grub_editor_layout(frame)
            self.assertIsNotNone(layout)
            self.assertGreaterEqual(layout.visible_command_lines, 3)
            self.assertIsNone(grub_editor_layout(missing))
            self.assertIsNone(grub_editor_layout(crowded))
            wrapped_image = image.copy()
            wrapped_draw = ImageDraw.Draw(wrapped_image)
            wrapped_draw.text(
                (80, 180),
                "timezone=Asia/Shanghai rd.overlay quiet splash ---",
                fill="white",
            )
            wrapped_image.save(wrapped)
            wrapped_layout = grub_editor_layout(wrapped)
            self.assertIsNotNone(wrapped_layout)
            self.assertEqual(5, wrapped_layout.visible_command_lines)
            cursor_image = image.copy()
            ImageDraw.Draw(cursor_image).rectangle(
                (16, 112, 23, 114), fill="white"
            )
            cursor_image.save(cursor)
            self.assertEqual(113, grub_editor_left_cursor_y(cursor))
            self.assertIsNone(grub_editor_left_cursor_y(frame))

    def test_grub_menu_oracle_requires_border_and_highlight(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            menu = root / "menu.ppm"
            editor = root / "editor.ppm"
            menu_image = Image.new("RGB", (640, 400), "black")
            draw = ImageDraw.Draw(menu_image)
            # This mirrors the signed GRUB text layout: its lower border is at
            # 85% of the screen, with help text below it.
            draw.rectangle((15, 50, 624, 340), outline=(190, 190, 190), width=2)
            draw.rectangle((18, 62, 621, 78), fill=(180, 180, 180))
            draw.text((22, 64), "*AnduinOS", fill="black")
            menu_image.save(menu)
            editor_image = Image.new("RGB", (640, 400), "black")
            ImageDraw.Draw(editor_image).rectangle(
                (15, 50, 624, 340),
                outline=(190, 190, 190),
                width=2,
            )
            editor_image.save(editor)
            self.assertIsNotNone(grub_menu_layout(menu))
            self.assertIsNone(grub_menu_layout(editor))

    def test_grub_ppm_reader_fails_closed_on_malformed_frames(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            truncated = root / "truncated.ppm"
            truncated.write_bytes(b"P6\n640 400\n255\n" + b"\0" * 10)
            with self.assertRaisesRegex(TestFailure, "Incomplete PPM screendump"):
                grub_menu_layout(truncated)

            trailing = root / "trailing.ppm"
            trailing.write_bytes(b"P6\n1 1\n255\n\0\0\0unexpected")
            with self.assertRaisesRegex(TestFailure, "Incomplete PPM screendump"):
                grub_menu_layout(trailing)

            huge = root / "huge.ppm"
            huge.write_bytes(b"P6\n16384 16384\n255\n")
            with self.assertRaisesRegex(TestFailure, "Unsafe PPM dimensions"):
                grub_menu_layout(huge)

            hostile_header = root / "hostile-header.ppm"
            hostile_header.write_bytes(b"P6\n" + b"9" * 33 + b" 1\n255\n")
            with self.assertRaisesRegex(TestFailure, "Unsafe PPM header token"):
                grub_menu_layout(hostile_header)

    def test_theme_transition_requires_a_visible_light_to_dark_repaint(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            light_path = root / "light.ppm"
            dark_path = root / "dark.ppm"
            light = Image.new("RGB", (800, 600), (245, 245, 245))
            dark = Image.new("RGB", (800, 600), (28, 30, 34))
            light.save(light_path)
            dark.save(dark_path)
            assert_theme_transition(light_path, dark_path, root / "theme.json")
            self.assertTrue((root / "theme.json").is_file())
            with self.assertRaisesRegex(TestFailure, "light frame"):
                assert_theme_transition(dark_path, dark_path, root / "same.json")
            with self.assertRaisesRegex(TestFailure, "dark frame"):
                assert_theme_transition(light_path, light_path, root / "reversed.json")

    def test_gdm_pointer_oracle_requires_motion_at_both_requested_positions(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            before = Image.new("RGB", (800, 600), "white")
            after = before.copy()
            ImageDraw.Draw(before).rectangle((190, 285, 209, 304), fill="black")
            ImageDraw.Draw(after).rectangle((590, 285, 609, 304), fill="black")
            before_path = root / "before.ppm"
            after_path = root / "after.ppm"
            before.save(before_path)
            after.save(after_path)
            assert_pointer_motion(before_path, after_path, root / "pointer.json")
            after.save(before_path)
            with self.assertRaisesRegex(TestFailure, "both GDM target positions"):
                assert_pointer_motion(before_path, after_path, root / "bad.json")

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
