"""One Home-only recovery journey through the actual GUI and normal boot."""

from .context import *  # noqa: F403


class HomeRecoveryChecks:
    def _login_home_gdm(self, vm, key, *, timeout):
        """Drive GDM while observing the serial-less restored boot over SSH."""
        assert vm.qmp is not None
        session_probe = (
            "loginctl list-sessions --no-legend | while read -r session rest; do "
            "test \"$(loginctl show-session \"$session\" -p Type --value)\" = wayland "
            "&& loginctl show-session \"$session\" -p Name --value; done | "
            f"grep -Fx {shlex.quote(self.username)} || true"
        )
        deadline = time.monotonic() + timeout
        next_input = 0.0
        attempts = 0
        last_error = "no graphical session"
        while time.monotonic() < deadline:
            try:
                graphical = self._ssh(vm, key, session_probe, timeout=20)
                if self.username in graphical.splitlines():
                    return graphical
            except TestFailure as error:
                last_error = str(error)
            now = time.monotonic()
            if now >= next_input and attempts < 4:
                vm.qmp.send_key("ret")
                time.sleep(1)
                vm.qmp.type_text(self.password, interval=0.06)
                vm.qmp.send_key("ret")
                attempts += 1
                next_input = now + 15
            time.sleep(1)
        raise TestFailure(
            "GDM did not open the restored Home's graphical session after "
            f"{attempts} input attempt(s): {last_error[-1000:]}"
        )

    def _exercise_btrfs_home_rollback(self, vm, base, artifacts):
        assert vm.serial is not None and vm.qmp is not None
        remote = "/run/anduinos-feature-home"
        vm.serial.run(f"install -d -m 0777 {remote}/evidence")
        self.driver.upload(vm.serial, remote)
        # Install the SSH key before the Home baseline so normal recovery does
        # not remove its control channel. System helpers are not rolled back.
        key = self._prepare_power_control(vm, artifacts, remote)
        helper = "/usr/local/lib/anduinos-acceptance/home_rollback_workload.py"
        vm.serial.upload(self.framework_root / "assertions/guest/home_rollback_workload.py",
                         helper, 0o755)
        policy = (
            f"{self.username} ALL=(root) NOPASSWD: /usr/bin/python3 {helper} verify\n"
        )
        vm.serial.run(
            "set -eu\n" + f"printf %s {shlex.quote(policy)} > /etc/sudoers.d/anduinos-home-acceptance\n"
            "chmod 0440 /etc/sudoers.d/anduinos-home-acceptance\n"
            "visudo -cf /etc/sudoers.d/anduinos-home-acceptance\n")
        prepared = vm.serial.run(f"python3 {helper} prepare {shlex.quote(self.username)}", timeout=300)
        (artifacts / "home-before.json").write_text(prepared.stdout + "\n")
        command = _desktop_command(self.username, (
            "python3", f"{remote}/atspi_driver.py", "home-restore-arm",
            "--expected", "Acceptance Home baseline", "--evidence", f"{remote}/evidence"),
            managed=True)
        armed = _run_with_qmp_key_requests(vm, command, timeout=300, secret_text=self.password)
        (artifacts / "home-restore-atspi-events.jsonl").write_text(armed.stdout + "\n")
        _retrieve_tree(vm.serial, remote, artifacts / "guest-home-evidence")
        if armed.returncode != 0:
            raise TestFailure("Home rollback GUI did not arm recovery:\n" + armed.stdout[-8000:])
        self._ssh(vm, key, "sudo -n /usr/local/sbin/anduinos-acceptance-reboot")
        self._wait_for_power_transition(vm, key, artifacts, "home-rollback-reboot", timeout=150)
        vm.stop()
        vm.start(attach_iso=False, phase="home-rollback-apply")
        self._ssh_eventually(vm, key, self._graphical_boot_ready_command(),
                             timeout=self.options.boot_timeout_seconds * 2)
        health = self._ssh(vm, key, "sudo -n /usr/local/sbin/anduinos-acceptance-package-health")
        (artifacts / "home-package-health.txt").write_text(health + "\n")
        # A working sshd alone is not a working desktop.
        graphical = self._login_home_gdm(
            vm, key, timeout=self.options.boot_timeout_seconds)
        (artifacts / "home-graphical-session.txt").write_text(graphical + "\n")
        # Browsing history is an active local user's operation, not an SSH
        # login's privilege. Verify it only once real desktop login succeeds.
        evidence = self._ssh(vm, key, f"sudo -n /usr/bin/python3 {helper} verify", timeout=180)
        if "home-only-recovery=verified" not in evidence.splitlines():
            raise TestFailure("Home rollback outcome was not verified")
        (artifacts / "home-after.txt").write_text(evidence + "\n")
        self._ssh(vm, key, "sudo -n /usr/local/sbin/anduinos-acceptance-poweroff")
        self._wait_for_power_transition(vm, key, artifacts, "home-poweroff", timeout=150)
        vm.stop()
