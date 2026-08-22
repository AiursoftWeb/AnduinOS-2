"""SSH policy, GNOME Secure Shell toggle, and snapshots-manager behavior."""

from .context import *  # noqa: F403


class AccessChecks:
    def _assert_host_ssh(
        self,
        vm: QemuVm,
        scenario: Scenario,
        artifacts: Path,
    ) -> None:
        port = vm.config.ssh_forward_port
        if scenario.ssh is SshPolicy.ENABLED:
            output = _ssh_login_eventually(
                port,
                self.defaults.username,
                self.defaults.password,
            )
            root = _ssh_login(
                port,
                "root",
                self.defaults.password,
                should_succeed=False,
            )
            text = output + "\nroot-login:\n" + root
        else:
            text = _ssh_login(
                port,
                self.defaults.username,
                self.defaults.password,
                should_succeed=False,
            )
        (artifacts / "host-ssh.txt").write_text(text, encoding="utf-8")

    def _exercise_gnome_ssh_switch(
        self,
        vm: QemuVm,
        scenario: Scenario,
        artifacts: Path,
    ) -> None:
        assert vm.qmp is not None and vm.serial is not None
        self.status(scenario.id, "Toggling Secure Shell in GNOME Settings")
        _login_gdm(
            vm,
            self.defaults.username,
            self.defaults.password,
            timeout=120,
        )
        remote_root = "/run/anduinos-acceptance-installed"
        vm.serial.run(f"install -d -m 0777 {remote_root}/evidence")
        self.driver.upload(vm.serial, remote_root)

        def run_driver(mode: str) -> str:
            command = _desktop_command(
                self.defaults.username,
                (
                    "python3",
                    f"{remote_root}/atspi_driver.py",
                    mode,
                    "--evidence",
                    f"{remote_root}/evidence",
                ),
                managed=True,
            )
            result = vm.serial.run(command, timeout=180, check=False)
            with (artifacts / "atspi-events.jsonl").open(
                "a", encoding="utf-8"
            ) as stream:
                stream.write(result.stdout + "\n")
            _retrieve_tree(
                vm.serial,
                remote_root,
                artifacts / "guest-settings-evidence",
            )
            _retrieve_file(
                vm.serial,
                "/tmp/gnome-control-center.stdout",
                artifacts / "gnome-control-center.stdout",
            )
            if result.returncode != 0:
                raise TestFailure(
                    f"GNOME Secure Shell UI mode {mode!r} failed:\n"
                    + result.stdout[-8000:]
                )
            return result.stdout

        run_driver("secure-shell-prepare")
        for _ in range(30):
            row = run_driver("secure-shell-row")
            if '"focused": true' in row:
                break
            vm.qmp.send_key("tab")
            time.sleep(0.3)
        else:
            raise TestFailure("Secure Shell row never received focus")
        vm.qmp.send_key("spc")
        time.sleep(1)
        for _ in range(12):
            probe = run_driver("secure-shell-probe")
            if '"focused": true' in probe and '"enabled": true' in probe:
                if '"active": true' in probe:
                    raise TestFailure("Secure Shell unexpectedly started enabled")
                break
            if '"focused": false' in probe:
                vm.qmp.send_key("tab")
            time.sleep(0.3)
        else:
            raise TestFailure("Secure Shell switch never received focus")
        vm.screenshot("secure-shell-dialog")

        # The outer AdwSwitchRow owns accessibility state and focus; its unique
        # inner GtkSwitch owns the activation action used by the guest driver.
        ssh_evidence: list[str] = []
        for mode, active in (("secure-shell-on", True), ("secure-shell-off", False)):
            result = run_driver(mode)
            if '"event": "polkit-required"' in result:
                vm.screenshot(f"{mode}-polkit-before-input")
                vm.qmp.type_text(
                    self.defaults.password,
                    interval=0.06,
                )
                vm.screenshot(f"{mode}-polkit-password-entered")
                vm.qmp.send_key("ret")
                run_driver(
                    "secure-shell-assert-on"
                    if active
                    else "secure-shell-assert-off"
                )
            time.sleep(2)
            vm.screenshot(f"{mode}-after-input")
            if active:
                ssh_evidence.append(
                    "after GNOME enabled Secure Shell:\n"
                    + _ssh_login_eventually(
                        vm.config.ssh_forward_port,
                        self.defaults.username,
                        self.defaults.password,
                    )
                )
            else:
                _assert_guest_ssh_stopped(vm.serial, artifacts)
                ssh_evidence.append(
                    "after GNOME disabled Secure Shell:\n"
                    + _ssh_login(
                        vm.config.ssh_forward_port,
                        self.defaults.username,
                        self.defaults.password,
                        should_succeed=False,
                    )
                )
        (artifacts / "host-ssh-toggle.txt").write_text(
            "\n\n".join(ssh_evidence) + "\n",
            encoding="utf-8",
        )
        vm.serial.run(
            _desktop_command(
                self.defaults.username,
                ("pkill", "-x", "gnome-control-center"),
            ),
            timeout=30,
            check=False,
        )

    def _exercise_snapshots_manager(
        self,
        vm: QemuVm,
        scenario: Scenario,
        artifacts: Path,
    ) -> None:
        assert vm.serial is not None
        self.status(scenario.id, "Launching Disk Snapshots Manager through GNOME")
        remote_root = "/run/anduinos-acceptance-snapshots"
        vm.serial.run(f"install -d -m 0777 {remote_root}/evidence")
        self.driver.upload(vm.serial, remote_root)
        command = _desktop_command(
            self.defaults.username,
            (
                "python3",
                f"{remote_root}/atspi_driver.py",
                "snapshots-manager",
                "--evidence",
                f"{remote_root}/evidence",
            ),
        )
        result = vm.serial.run(command, timeout=180, check=False)
        with (artifacts / "atspi-events.jsonl").open("a", encoding="utf-8") as stream:
            stream.write(result.stdout + "\n")
        _retrieve_tree(
            vm.serial,
            remote_root,
            artifacts / "guest-snapshots-evidence",
        )
        _retrieve_file(
            vm.serial,
            "/tmp/anduinos-snapshots-manager.stdout",
            artifacts / "snapshots-manager.stdout",
        )
        if result.returncode != 0:
            raise TestFailure(
                "Disk Snapshots Manager did not launch through AT-SPI:\n"
                + result.stdout[-8000:]
            )
