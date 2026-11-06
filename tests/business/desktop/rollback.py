"""Desktop-armed rollback across real Ubuntu kernel boots."""

from .context import *  # noqa: F403


class KernelRollbackChecks:
    def _exercise_cross_kernel_rollback(self, vm, base, artifacts):
        self._exercise_kernel_rollback(vm, base, artifacts, "cross-kernel")

    def _exercise_failed_target_rollback(self, vm, base, artifacts):
        self._exercise_kernel_rollback(vm, base, artifacts, "failed-target")

    def _exercise_default_kernel_rollback(self, vm, base, artifacts):
        self._exercise_kernel_rollback(vm, base, artifacts, "default-kernel")

    def _exercise_kernel_rollback(self, vm, base, artifacts, variant):
        assert vm.serial is not None
        remote = "/usr/local/lib/anduinos-acceptance"
        vm.serial.run(f"install -d -m 0755 {remote}; install -d -m 0777 {remote}/evidence")
        key = self._prepare_power_control(vm, artifacts, remote)
        helper = f"{remote}/rollback_kernel_workload.py"
        vm.serial.upload(self.framework_root / "assertions/guest/rollback_kernel_workload.py",
                         helper, 0o644)
        self.driver.upload(vm.serial, remote)
        tty = "ttyS0" if vm.config.architecture.value == "amd64" else "ttyAMA0"
        setup = (
            "#!/bin/sh\nset -eu\n"
            "install -d /run/systemd/system/debug-shell.service.d\n"
            f"printf '[Unit]\\nConditionPathExists=\\n[Service]\\nTTYPath=/dev/{tty}\\n' "
            "> /run/systemd/system/debug-shell.service.d/acceptance.conf\n"
            f"systemctl stop serial-getty@{tty}.service\n"
            "systemctl daemon-reload\nsystemctl start debug-shell.service\n"
        )
        console = "/usr/local/sbin/anduinos-acceptance-kernel-console"
        # Only this fixed read-only verdict is allowed through the SSH control
        # channel. Preparation and the GUI run before recovery, via the normal
        # acceptance debug session. No root SSH or password policy changes.
        vm.serial.run(
            f"printf %s {shlex.quote(setup)} > {console}; chmod 0755 {console}; "
            f"printf '%s ALL=(root) NOPASSWD: /usr/bin/python3 {helper} verify, {console}\\n' "
            f"{shlex.quote(self.username)} > /etc/sudoers.d/anduinos-kernel-acceptance; "
            "chmod 0440 /etc/sudoers.d/anduinos-kernel-acceptance; "
            "visudo -cf /etc/sudoers.d/anduinos-kernel-acceptance"
        )
        prepared = vm.serial.run(f"python3 {helper} prepare {variant}", timeout=2400)
        (artifacts / "kernel-prepare.json").write_text(prepared.stdout + "\n")
        state = _json_object(prepared.stdout)
        vm.screenshot("kernel-01-snapshot-and-alternate-installed")
        self._ssh(vm, key, "sudo -n /usr/local/sbin/anduinos-acceptance-reboot")
        self._wait_for_power_transition(vm, key, artifacts, "kernel-alternate-reboot", timeout=150)
        vm.stop()
        vm.start(attach_iso=False, phase="kernel-alternate")
        self._ssh_eventually(vm, key, self._graphical_boot_ready_command(),
                             timeout=self.options.boot_timeout_seconds * 2)

        # The subsequent UI must run in a real active GNOME session. Restore
        # only the runtime serial control channel, not a boot argument/initrd.
        # This existing helper permits the fixed diagnostics/boot commands;
        # use its initial serial channel to install a narrowly scoped runtime
        # setup helper before losing that channel on ordinary boot.
        self._ssh(vm, key, "sudo -n /usr/local/sbin/anduinos-acceptance-kernel-console")
        assert vm.serial is not None
        vm.serial.wait_for_shell(self.options.boot_timeout_seconds)
        ready = vm.serial.run(f"python3 {helper} ready", timeout=180)
        (artifacts / "kernel-alternate-ready.json").write_text(ready.stdout + "\n")
        _login_gdm(vm, self.username, self.password, timeout=120)
        self._wait_for_gdm_greeter_exit(vm)
        vm.screenshot("kernel-02-alternate-desktop")
        command = _desktop_command(self.username, (
            "python3", f"{remote}/atspi_driver.py", "snapshot-restore-arm",
            "--expected", state["title"], "--evidence", f"{remote}/evidence",
        ), managed=True)
        armed = _run_with_qmp_key_requests(vm, command, timeout=300, secret_text=self.password)
        (artifacts / "kernel-restore-ui.jsonl").write_text(armed.stdout + "\n")
        _retrieve_tree(vm.serial, remote, artifacts / "guest-kernel-evidence")
        if armed.returncode:
            raise TestFailure("Cross-kernel GUI did not arm the selected snapshot:\n" + armed.stdout[-8000:])
        protocol = self._armed_recovery_protocol(vm, artifacts)
        if protocol != 3:
            raise TestFailure("Cross-kernel restore must use the restart protocol")
        vm.screenshot("kernel-03-restore-armed")
        self._ssh(vm, key, "sudo -n /usr/local/sbin/anduinos-acceptance-reboot")
        self._wait_for_power_transition(vm, key, artifacts, "kernel-restore-reboot", timeout=150)
        vm.stop()
        vm.start(attach_iso=False, phase="kernel-restore-apply")
        self._finish_recovery_restart(vm, artifacts, "kernel-restore-target", protocol)
        if variant == "failed-target":
            # Simulate the user restarting after the target's mandatory mount
            # fails. The final oracle also requires that boot's failed-mount
            # journal; a slow boot or an arbitrary power cut cannot earn a pass.
            try:
                self._ssh_eventually(vm, key, self._graphical_boot_ready_command(), timeout=60)
            except TestFailure as error:
                if not vm.running or not str(error).startswith("SSH control did not become healthy"):
                    raise
                (artifacts / "failed-target-observation.txt").write_text(str(error) + "\n")
            else:
                raise TestFailure("Target with the deliberately failed required mount reached the desktop")
            vm.screenshot("kernel-04-target-failed")
            vm.stop()
            vm.start(attach_iso=False, phase="kernel-restore-revert")
            self._finish_recovery_restart(vm, artifacts, "kernel-restore-fallback", protocol)

        previous_boot = None
        for number in (1, 2):
            self._ssh_eventually(vm, key, self._graphical_boot_ready_command(),
                                 timeout=self.options.boot_timeout_seconds * 2)
            result = self._ssh_eventually(vm, key, f"sudo -n /usr/bin/python3 {helper} verify",
                                          timeout=self.options.boot_timeout_seconds)
            (artifacts / f"kernel-result-{number}.json").write_text(result + "\n")
            boot = _json_object(result)["boot_id"]
            if previous_boot is not None:
                _validate_distinct_boot_ids(previous_boot, boot)
            previous_boot = boot
            vm.screenshot(f"kernel-05-result-{number}")
            if number == 1:
                self._ssh(vm, key, "sudo -n /usr/local/sbin/anduinos-acceptance-reboot")
                self._wait_for_power_transition(vm, key, artifacts, "kernel-stable-reboot", timeout=150)
                vm.stop()
                vm.start(attach_iso=False, phase="kernel-stable")
        self._ssh(vm, key, "sync")
        vm.stop()
