"""Reboot, Btrfs rollback, and SSH recovery oracles."""

from unit.support import *  # noqa: F403


class DesktopLifecycleOracleTests(FeatureOracleCase):
    def test_spice_guest_agent_cannot_stall_reboot_for_the_vendor_timeout(self):
        script = (
            ROOT.parent
            / "mods/84-spice-vdagent-shutdown/install.sh"
        ).read_text(encoding="utf-8")
        self.assertIn("spice-vdagent", script)
        self.assertIn(
            "/etc/systemd/system/spice-vdagentd.service.d",
            script,
        )
        self.assertIn("TimeoutStopSec=15s", script)
        self.assertIn('judge "Bound SPICE guest-agent shutdown latency"', script)
        self.assertNotIn("dpkg-query", script)
        self.assertNotIn("grep", script)
        self.assertNotIn("/usr/lib/systemd/system/spice-vdagentd.service <<", script)

    def test_ordinary_reboot_oracle_rejects_a_reused_boot_id(self):
        _validate_distinct_boot_ids("first", "second")
        with self.assertRaisesRegex(TestFailure, "distinct boot ID"):
            _validate_distinct_boot_ids("same", "same")

    def test_rime_oracle_rejects_wrong_committed_text(self):
        with tempfile.TemporaryDirectory() as directory:
            evidence = Path(directory) / "rime.json"
            evidence.write_text(
                '{"expected":"你好","observed":"你号","exact":false}\n',
                encoding="utf-8",
            )
            with self.assertRaisesRegex(TestFailure, "exact committed text"):
                _validate_rime_evidence(evidence, "你好")
            evidence.write_text(
                '{"expected":"你好","observed":"你好","exact":true}\n',
                encoding="utf-8",
            )
            _validate_rime_evidence(evidence, "你好")

    def test_btrfs_oracle_rejects_a_surviving_root_sentinel(self):
        passing = "\n".join(
            (
                "docker=absent",
                "root-sentinel=absent",
                "home-sentinel=present",
                "dpkg=ok",
                "apt=ok",
                "boot-artifacts=ok",
                "btrfs-default-subvolume=unchanged",
                "btrfs-staging-roots=absent",
                "recovery-grubenv=empty",
                "confirm-service=success",
                "recovery-pending=absent",
                "rollback-history=confirmed",
                "deployments-ready=target-and-fallback",
                "deployment-roots=verified",
                "active-root=selected-target",
                "snapshot-state=ok",
                "rollback-health=ok",
            )
        )
        _validate_rollback_health(passing)
        with self.assertRaisesRegex(TestFailure, "root-sentinel=absent"):
            _validate_rollback_health(
                passing.replace("root-sentinel=absent", "root-sentinel=present")
            )

    def test_btrfs_postboot_health_uses_fixed_privileged_helpers(self):
        command = FeatureSuiteRunner._rollback_health_command(
            "/etc/root-sentinel",
            "/home/user/home-sentinel",
            "11111111-1111-4111-8111-111111111111",
        )
        self.assertIn(
            "sudo -n /usr/local/sbin/anduinos-acceptance-package-health",
            command,
        )
        self.assertIn(
            "sudo -n /usr/local/sbin/anduinos-acceptance-boot-health",
            command,
        )
        self.assertIn(
            "sudo -n /usr/local/sbin/anduinos-acceptance-rollback-state",
            command,
        )
        self.assertNotIn("apt-get check", command)
        self.assertNotIn("grub-script-check", command)

    def test_btrfs_postboot_waits_until_graphical_boot_is_really_ready(self):
        command = FeatureSuiteRunner._graphical_boot_ready_command()
        self.assertIn("graphical.target", command)
        self.assertIn("gdm", command)

        runner = object.__new__(FeatureSuiteRunner)
        runner._ssh = Mock(
            side_effect=(
                TestFailure("Feature SSH control failed with 3"),
                "graphical-ready\n",
            )
        )
        with patch("business.desktop.time.sleep"):
            output = runner._ssh_eventually(
                SimpleNamespace(), Path("control-key"), command, timeout=60
            )
        self.assertEqual("graphical-ready\n", output)
        self.assertEqual(2, runner._ssh.call_count)

    def test_ordinary_reboot_reuses_the_graphical_boot_readiness_gate(self):
        source = _source_tree(ROOT / "business/desktop")
        body = source.split("def _exercise_ordinary_reboot", 1)[1].split(
            "def _exercise_account_add_user", 1
        )[0]
        reboot_start = body.index('vm.start(attach_iso=False, phase="lifecycle-reboot")')
        post_reboot = body[reboot_start:]
        self.assertIn("self._graphical_boot_ready_command()", post_reboot)
        self.assertNotIn('key,\n            "true",', post_reboot)

    def test_snapshot_restore_confirmation_accepts_exact_locale_variants(self):
        source = _source_tree(ROOT / "assertions/guest/ui")
        body = source.split("def arm_snapshot_restore", 1)[1].split(
            "def verify_font_rendering", 1
        )[0]
        self.assertIn('f"Roll Back to {title}?"', body)
        self.assertIn('f"回滚到 {title}？"', body)
        self.assertIn("confirmation = find_candidates(", body)
        self.assertIn('"snapshot-rollback-confirmation"', body)

    def test_spotify_release_check_physically_drops_the_qemu_nic(self):
        runner = object.__new__(FeatureSuiteRunner)
        runner._run_shell_driver = Mock()
        serial = Mock()
        serial.run.return_value = SimpleNamespace(
            stdout=(
                "qmp-link=nic0-down\ninterface=enp1s0\n"
                "carrier=0\noperstate=down\n"
            )
        )
        qmp = Mock()
        vm = SimpleNamespace(qmp=qmp, serial=serial)
        base = SimpleNamespace(scenario=SimpleNamespace(id="bios-online-btrfs"))
        with tempfile.TemporaryDirectory() as directory:
            artifacts = Path(directory)
            runner._exercise_spotify_store(vm, base, artifacts)
            evidence = (artifacts / "spotify-network-isolation.txt").read_text()

        qmp.set_link.assert_called_once_with("nic0", up=False)
        self.assertIn("carrier=0", evidence)
        command = serial.run.call_args.args[0]
        self.assertIn("/sys/class/net", command)
        syntax = subprocess.run(
            ("bash", "-n"),
            input=command,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
        self.assertEqual(0, syntax.returncode, syntax.stderr)
        runner._run_shell_driver.assert_called_once()

    def test_btrfs_privileged_state_helper_is_valid_and_checks_recovery_invariants(self):
        commands = []

        def run(command, **_kwargs):
            commands.append(command)
            return SimpleNamespace(stdout="")

        runner = object.__new__(FeatureSuiteRunner)
        runner.username = "test-user"
        runner.btrfs_rollback_oracle = (
            ROOT / "assertions/guest/btrfs_rollback_oracle.py"
        )
        runner._ssh_eventually = lambda *_args, **_kwargs: "ready"
        vm = SimpleNamespace(
            serial=SimpleNamespace(
                upload=lambda *_args, **_kwargs: None,
                run=run,
            )
        )
        with tempfile.TemporaryDirectory() as directory, patch(
            "business.desktop.subprocess.run"
        ):
            runner._prepare_power_control(vm, Path(directory), "/run/feature")

        payload = commands[0]
        marker = (
            "cat > /usr/local/sbin/anduinos-acceptance-rollback-state "
            "<<'EOF'\n"
        )
        helper = payload.split(marker, 1)[1].split("\nEOF\n", 1)[0] + "\n"
        syntax = subprocess.run(
            ("bash", "-n"),
            input=helper,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            check=False,
        )
        self.assertEqual(0, syntax.returncode, syntax.stdout)
        for contract in (
            "btrfs subvolume get-default /",
            "@root\\.snapshots-manager-(old|new)-",
            "/boot/efi/EFI/anduinos/btrfs-snapshots-manager-grubenv",
            "anduinos-btrfs-snapshots-manager-confirm.service",
            "btrfs_rollback_oracle.py",
            '"$expected_target"',
        ):
            self.assertIn(contract, helper)
        self.assertNotIn("snapshots-manager-cli status", helper)

    def test_btrfs_protected_state_oracle_rejects_a_broken_fallback(self):
        target = "11111111-1111-4111-8111-111111111111"
        fallback = "22222222-2222-4222-8222-222222222222"
        target_snapshot = "33333333-3333-4333-8333-333333333333"
        fallback_snapshot = "44444444-4444-4444-8444-444444444444"
        digest = "a" * 64
        oracle = ROOT / "assertions/guest/btrfs_rollback_oracle.py"

        def deployment(identifier, kind, snapshot):
            return {
                "schema_version": 1,
                "id": identifier,
                "parent_id": None,
                "kind": kind,
                "state": "ready",
                "created_at": "2026-08-18T00:00:00Z",
                "title": "Acceptance fixture",
                "reason": "Failure-injection fixture",
                "snapshot_uuid": snapshot,
                "snapshot_parent_uuid": None,
                "kernel_release": "7.0.0-test",
                "initramfs_sha256": digest,
                "boot_artifact_sha256": digest,
                "dpkg_status_sha256": digest,
                "mok_certificate_sha256": None,
                "pinned": False,
                "failure": None,
            }

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            store = root / "store"
            metadata = store / "metadata"
            history = store / "rollback-history"
            transactions = store / "transactions"
            target_root = store / "deployments" / target / "root"
            fallback_root = store / "deployments" / fallback / "root"
            current_root = root / "current-root"
            for path in (
                metadata,
                history,
                transactions,
                target_root,
                fallback_root,
                current_root,
            ):
                path.mkdir(parents=True, exist_ok=True)
            target_record = deployment(target, "manual", target_snapshot)
            fallback_record = deployment(fallback, "pre-rollback", fallback_snapshot)
            (metadata / f"{target}.json").write_text(
                json.dumps(target_record), encoding="utf-8"
            )
            fallback_path = metadata / f"{fallback}.json"
            fallback_path.write_text(json.dumps(fallback_record), encoding="utf-8")
            (history / "55555555-5555-4555-8555-555555555555.json").write_text(
                json.dumps(
                    {
                        "schema_version": 3,
                        "id": "55555555-5555-4555-8555-555555555555",
                        "target_deployment_id": target,
                        "fallback_deployment_id": fallback,
                        "phase": "confirmed",
                        "recovery_protocol_version": 2,
                        "root_filesystem_uuid": "66666666-6666-4666-8666-666666666666",
                        "kernel_release": "7.0.0-test",
                        "recovery_kernel_sha256": digest,
                        "recovery_initramfs_sha256": digest,
                        "recovery_confirm_sha256": digest,
                        "failure": None,
                    }
                ),
                encoding="utf-8",
            )
            fake_btrfs = root / "fake-btrfs"
            mapping = {
                str(target_root): target_snapshot,
                str(fallback_root): fallback_snapshot,
            }
            fake_btrfs.write_text(
                "#!/usr/bin/python3\n"
                "import sys\n"
                f"mapping = {mapping!r}\n"
                f"current = {str(current_root)!r}\n"
                f"parent = {target_snapshot!r}\n"
                "path = sys.argv[-1]\n"
                "if path in mapping:\n"
                "    print(f'UUID: {mapping[path]}')\n"
                "elif path == current:\n"
                "    print('UUID: 77777777-7777-4777-8777-777777777777')\n"
                "    print(f'Parent UUID: {parent}')\n"
                "else:\n"
                "    raise SystemExit(2)\n",
                encoding="utf-8",
            )
            fake_btrfs.chmod(0o755)
            command = (
                "python3",
                str(oracle),
                target,
                "--store-root",
                str(store),
                "--current-root",
                str(current_root),
                "--btrfs",
                str(fake_btrfs),
            )
            passing = subprocess.run(
                command,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                check=False,
            )
            self.assertEqual(0, passing.returncode, passing.stdout)
            self.assertIn("active-root=selected-target", passing.stdout)
            self.assertIn("snapshot-state=ok", passing.stdout)

            fallback_record["state"] = "broken"
            fallback_path.write_text(json.dumps(fallback_record), encoding="utf-8")
            failing = subprocess.run(
                command,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                check=False,
            )
            self.assertNotEqual(0, failing.returncode, failing.stdout)
            self.assertIn(f"deployment {fallback} is not ready", failing.stdout)

    def test_btrfs_oracle_rejects_uncleared_recovery_boot_state(self):
        passing = "\n".join(
            (
                "docker=absent",
                "root-sentinel=absent",
                "home-sentinel=present",
                "dpkg=ok",
                "apt=ok",
                "boot-artifacts=ok",
                "btrfs-default-subvolume=unchanged",
                "btrfs-staging-roots=absent",
                "recovery-grubenv=empty",
                "confirm-service=success",
                "recovery-pending=absent",
                "rollback-history=confirmed",
                "deployments-ready=target-and-fallback",
                "deployment-roots=verified",
                "active-root=selected-target",
                "snapshot-state=ok",
                "rollback-health=ok",
            )
        )
        _validate_rollback_health(passing)
        with self.assertRaisesRegex(TestFailure, "recovery-grubenv=empty"):
            _validate_rollback_health(
                passing.replace("recovery-grubenv=empty", "recovery-grubenv=armed")
            )

    def test_ssh_eventually_retries_a_forwarded_socket_handshake_timeout(self):
        runner = object.__new__(FeatureSuiteRunner)
        runner._ssh = Mock(
            side_effect=(
                subprocess.TimeoutExpired(("ssh", "true"), 15),
                TestFailure("connection reset during guest boot"),
                "ready\n",
            )
        )
        with patch("business.desktop.time.sleep"):
            output = runner._ssh_eventually(
                SimpleNamespace(), Path("control-key"), "true", timeout=60
            )
        self.assertEqual("ready\n", output)
        self.assertEqual(3, runner._ssh.call_count)
        self.assertTrue(
            all(call.kwargs["timeout"] <= 15 for call in runner._ssh.call_args_list)
        )

    def test_ssh_eventually_fails_immediately_when_qemu_has_exited(self):
        runner = object.__new__(FeatureSuiteRunner)
        runner._ssh = Mock(side_effect=AssertionError("SSH must not be attempted"))
        vm = SimpleNamespace(process=SimpleNamespace(poll=lambda: 0))

        with self.assertRaisesRegex(TestFailure, "QEMU exited.*exit code 0"):
            runner._ssh_eventually(vm, Path("control-key"), "true", timeout=1200)

        runner._ssh.assert_not_called()

    def test_stalled_btrfs_power_transition_retains_diagnostics(self):
        class Clock:
            now = 0.0

            @classmethod
            def monotonic(cls):
                return cls.now

            @classmethod
            def sleep(cls, seconds):
                cls.now += seconds

        runner = object.__new__(FeatureSuiteRunner)
        runner._ssh = lambda *_args, **_kwargs: "timer failed: inhibitor active"
        vm = SimpleNamespace(process=SimpleNamespace(poll=lambda: None))
        with tempfile.TemporaryDirectory() as directory:
            artifacts = Path(directory)
            with (
                patch("business.desktop.time.monotonic", Clock.monotonic),
                patch("business.desktop.time.sleep", Clock.sleep),
                self.assertRaisesRegex(TestFailure, "did not stop QEMU"),
            ):
                runner._wait_for_power_transition(
                    vm,
                    artifacts / "key",
                    artifacts,
                    "btrfs-rollback-reboot",
                    timeout=20,
                )
            evidence = (
                artifacts / "btrfs-rollback-reboot-diagnostics.txt"
            ).read_text(encoding="utf-8")
        self.assertIn("inhibitor active", evidence)

    def test_stalled_btrfs_power_transition_prefers_root_serial_diagnostics(self):
        class Clock:
            now = 0.0

            @classmethod
            def monotonic(cls):
                return cls.now

            @classmethod
            def sleep(cls, seconds):
                cls.now += seconds

        serial = SimpleNamespace(
            run=lambda *_args, **_kwargs: SimpleNamespace(
                stdout="42 shutdown.target start running"
            )
        )
        runner = object.__new__(FeatureSuiteRunner)
        runner._ssh = Mock(side_effect=AssertionError("SSH must not be preferred"))
        vm = SimpleNamespace(
            process=SimpleNamespace(poll=lambda: None),
            serial=serial,
        )
        with tempfile.TemporaryDirectory() as directory:
            artifacts = Path(directory)
            with (
                patch("business.desktop.time.monotonic", Clock.monotonic),
                patch("business.desktop.time.sleep", Clock.sleep),
                self.assertRaisesRegex(TestFailure, "did not stop QEMU"),
            ):
                runner._wait_for_power_transition(
                    vm,
                    artifacts / "key",
                    artifacts,
                    "btrfs-rollback-reboot",
                    timeout=20,
                )
            evidence = (
                artifacts / "btrfs-rollback-reboot-diagnostics.txt"
            ).read_text(encoding="utf-8")
        self.assertIn("root serial control channel", evidence)
        self.assertIn("shutdown.target", evidence)
        runner._ssh.assert_not_called()
