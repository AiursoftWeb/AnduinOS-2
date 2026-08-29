"""Ordinary reboot, Btrfs rollback, power transition, and SSH behavior."""

from .context import *  # noqa: F403


class LifecycleChecks:
    def _exercise_ordinary_reboot(
        self,
        vm: QemuVm,
        base: PromotedBase,
        artifacts: Path,
    ) -> None:
        """Prove that the same VM model can complete an ordinary guest reboot."""

        assert vm.serial is not None and vm.qmp is not None
        remote = "/run/anduinos-feature-lifecycle"
        vm.serial.run(f"install -d -m 0755 {remote}")
        key = self._prepare_power_control(vm, artifacts, remote)
        before = self._ssh(
            vm,
            key,
            "set -e; printf 'boot-id=%s\\n' "
            "\"$(cat /proc/sys/kernel/random/boot_id)\"; "
            "systemctl is-active graphical.target; systemctl is-active gdm; "
            "sudo -n /usr/local/sbin/anduinos-acceptance-package-health",
        )
        before_id = _last_value(before, "boot-id")
        (artifacts / "lifecycle-before-reboot.txt").write_text(
            before + "\n", encoding="utf-8"
        )

        self.phase_callback(
            base.scenario.id,
            "system-lifecycle",
            "Requesting ordinary guest reboot",
        )
        request = self._ssh(
            vm,
            key,
            "sudo -n /usr/local/sbin/anduinos-acceptance-reboot",
        )
        (artifacts / "lifecycle-reboot-request.txt").write_text(
            request + "\n", encoding="utf-8"
        )
        started = time.monotonic()
        self._wait_for_power_transition(
            vm,
            key,
            artifacts,
            "lifecycle-ordinary-reboot",
            timeout=150,
        )
        shutdown_seconds = time.monotonic() - started
        vm.stop()

        # This boot is deliberately untouched: no GRUB edit and no debug
        # shell.  SSH was installed in the disposable overlay before reboot.
        vm.start(attach_iso=False, phase="lifecycle-reboot")
        self._ssh_eventually(
            vm,
            key,
            self._graphical_boot_ready_command(),
            timeout=self.options.boot_timeout_seconds,
        )
        after = self._ssh(
            vm,
            key,
            "set -e; printf 'boot-id=%s\\n' "
            "\"$(cat /proc/sys/kernel/random/boot_id)\"; "
            "systemctl is-active graphical.target; systemctl is-active gdm; "
            "sudo -n /usr/local/sbin/anduinos-acceptance-package-health; "
            "printf 'ordinary-reboot=ok\\n'",
            timeout=180,
        )
        after_id = _last_value(after, "boot-id")
        _validate_distinct_boot_ids(before_id, after_id)
        (artifacts / "lifecycle-after-reboot.txt").write_text(
            after
            + f"\nbefore-boot-id={before_id}\nafter-boot-id={after_id}\n"
            + f"guest-shutdown-seconds={shutdown_seconds:.3f}\n",
            encoding="utf-8",
        )
        vm.screenshot("lifecycle-after-ordinary-reboot")
        # The successful second boot is intentionally free of the injected
        # serial debug shell, so the generic serial-based suite cleanup cannot
        # be used.  Flush through the authenticated guest channel, then close
        # the disposable VM through QMP.
        self._ssh(vm, key, "sync")
        vm.stop()
    def _exercise_btrfs_rollback(
        self,
        vm: QemuVm,
        base: PromotedBase,
        artifacts: Path,
    ) -> None:
        """Install Docker after a real snapshot, restore it, and boot twice."""

        assert vm.serial is not None and vm.qmp is not None
        title = "AnduinOS acceptance before Docker"
        root_sentinel = "/etc/anduinos-acceptance-after-snapshot"
        home_sentinel = f"/home/{self.username}/anduinos-acceptance-user-data"
        remote = "/run/anduinos-feature-btrfs"
        vm.serial.run(f"install -d -m 0777 {remote}/evidence")
        self.driver.upload(vm.serial, remote)

        precondition = vm.serial.run(
            "set -euo pipefail\n"
            "test \"$(findmnt -n -o FSTYPE /)\" = btrfs\n"
            "test \"$(findmnt -n -o FSROOT /)\" = /@root\n"
            "! dpkg-query -W -f='${db:Status-Abbrev}' docker.io 2>/dev/null "
            "| grep -q '^ii '\n"
            "test ! -e /usr/bin/docker\n"
            "anduinos-btrfs-snapshots-manager-cli status --json\n"
            "btrfs subvolume show /\n"
            "btrfs subvolume list /\n",
            timeout=120,
        )
        (artifacts / "btrfs-before.txt").write_text(
            precondition.stdout + "\n", encoding="utf-8"
        )

        key = self._prepare_power_control(vm, artifacts, remote)

        created = vm.serial.run(
            "anduinos-btrfs-snapshots-manager-cli create --json "
            f"{shlex.quote(title)} "
            f"{shlex.quote('Acceptance baseline before installing docker.io')}",
            timeout=300,
        )
        (artifacts / "btrfs-snapshot-created.json").write_text(
            created.stdout + "\n", encoding="utf-8"
        )
        deployment = _json_object(created.stdout)
        deployment_id = str(deployment.get("id") or deployment.get("deployment_id") or "")
        if not deployment_id:
            raise TestFailure("Snapshot manager did not return a deployment ID")
        verified = vm.serial.run(
            "anduinos-btrfs-snapshots-manager-cli verify "
            f"{shlex.quote(deployment_id)} --json",
            timeout=300,
        )
        (artifacts / "btrfs-snapshot-verified.json").write_text(
            verified.stdout + "\n", encoding="utf-8"
        )

        changed = vm.serial.run(
            "set -euo pipefail\n"
            "export DEBIAN_FRONTEND=noninteractive\n"
            "apt-get install --yes docker.io\n"
            "dpkg-query -W -f='${db:Status-Abbrev} ${Package} ${Version}\\n' "
            "docker.io | grep '^ii '\n"
            "test -x /usr/bin/docker\n"
            "systemctl enable --now docker.service\n"
            "systemctl is-active --quiet docker.service\n"
            f"printf 'root changes must roll back\\n' > {root_sentinel}\n"
            f"printf 'home data must survive\\n' > {home_sentinel}\n"
            f"chown {shlex.quote(self.username)}:{shlex.quote(self.username)} "
            f"{home_sentinel}\n"
            f"test -f {root_sentinel}\n"
            f"test -f {home_sentinel}\n",
            timeout=1200,
        )
        (artifacts / "btrfs-after-docker-install.txt").write_text(
            changed.stdout + "\n", encoding="utf-8"
        )

        arm = _desktop_command(
            self.username,
            (
                "python3",
                f"{remote}/atspi_driver.py",
                "snapshot-restore-arm",
                "--expected",
                title,
                "--evidence",
                f"{remote}/evidence",
            ),
        )
        armed = _run_with_qmp_key_requests(
            vm,
            arm,
            timeout=300,
            secret_text=self.password,
        )
        (artifacts / "btrfs-restore-atspi-events.jsonl").write_text(
            armed.stdout + "\n", encoding="utf-8"
        )
        _retrieve_tree(vm.serial, remote, artifacts / "guest-btrfs-evidence")
        if armed.returncode != 0:
            raise TestFailure(
                "The real snapshot-manager UI could not arm the selected restore:\n"
                + armed.stdout[-8000:]
            )

        # The UI has proved that the exact transaction is armed. Trigger an
        # ordinary systemd reboot through the pre-snapshot, least-privilege
        # control channel; do not boot a debug kernel or manipulate subvolumes.
        # QEMU's -no-reboot turns that guest reboot into a process exit, making
        # the product-owned GRUB/initramfs recovery boot explicit and observable.
        self.phase_callback(base.scenario.id, "btrfs-rollback", "Rebooting into armed rollback")
        reboot_request = self._ssh(
            vm,
            key,
            "sudo -n /usr/local/sbin/anduinos-acceptance-reboot",
        )
        (artifacts / "btrfs-rollback-reboot-request.txt").write_text(
            reboot_request + "\n", encoding="utf-8"
        )
        self._wait_for_power_transition(
            vm,
            key,
            artifacts,
            "btrfs-rollback-reboot",
            # systemd's default stop timeout alone is 90 seconds.  The
            # delayed request and the final firmware reset need their own
            # margin; cutting QEMU off at 90 seconds can manufacture a
            # failure immediately before systemd kills a stuck service.
            timeout=150,
        )
        vm.stop()
        vm.start(attach_iso=False, phase="rollback-apply")
        self._ssh_eventually(
            vm,
            key,
            self._graphical_boot_ready_command(),
            timeout=self.options.boot_timeout_seconds * 2,
        )
        first_boot = self._ssh(
            vm,
            key,
            self._rollback_health_command(
                root_sentinel,
                home_sentinel,
                deployment_id,
            ),
            timeout=300,
        )
        _validate_rollback_health(first_boot)
        (artifacts / "btrfs-after-rollback-first-boot.txt").write_text(
            first_boot + "\n", encoding="utf-8"
        )
        first_boot_id = _last_value(
            self._ssh(
                vm,
                key,
                "printf 'boot-id=%s\\n' \"$(cat /proc/sys/kernel/random/boot_id)\"",
            ),
            "boot-id",
        )

        self.phase_callback(base.scenario.id, "btrfs-rollback", "Performing ordinary reboot")
        second_reboot_request = self._ssh(
            vm,
            key,
            "sudo -n /usr/local/sbin/anduinos-acceptance-reboot",
        )
        (artifacts / "btrfs-ordinary-reboot-request.txt").write_text(
            second_reboot_request + "\n", encoding="utf-8"
        )
        self._wait_for_power_transition(
            vm,
            key,
            artifacts,
            "btrfs-ordinary-reboot",
            timeout=150,
        )
        vm.stop()
        vm.start(attach_iso=False, phase="rollback-second-boot")
        self._ssh_eventually(
            vm,
            key,
            self._graphical_boot_ready_command(),
            timeout=self.options.boot_timeout_seconds,
        )
        second_boot = self._ssh(
            vm,
            key,
            self._rollback_health_command(
                root_sentinel,
                home_sentinel,
                deployment_id,
            ),
            timeout=300,
        )
        _validate_rollback_health(second_boot)
        second_boot_id = _last_value(
            self._ssh(
                vm,
                key,
                "printf 'boot-id=%s\\n' \"$(cat /proc/sys/kernel/random/boot_id)\"",
            ),
            "boot-id",
        )
        _validate_distinct_boot_ids(first_boot_id, second_boot_id)
        (artifacts / "btrfs-after-rollback-second-boot.txt").write_text(
            second_boot + f"\nfirst-boot-id={first_boot_id}\n"
            f"second-boot-id={second_boot_id}\n",
            encoding="utf-8",
        )
        status = self._ssh(
            vm,
            key,
            "sudo -n /usr/local/sbin/anduinos-acceptance-rollback-state "
            + shlex.quote(deployment_id),
            timeout=180,
        )
        (artifacts / "btrfs-rollback-state.txt").write_text(
            status + "\n", encoding="utf-8"
        )

        # Prove the post-rollback graphical system, not merely sshd, is usable.
        vm.qmp.send_key("ret")
        time.sleep(1)
        vm.qmp.type_text(self.password, interval=0.06)
        vm.qmp.send_key("ret")
        graphical = self._ssh_eventually(
            vm,
            key,
            "set -e; systemctl is-active --quiet graphical.target; "
            "systemctl is-active --quiet gdm; "
            "loginctl list-sessions --no-legend | while read -r session rest; do "
            "test \"$(loginctl show-session \"$session\" -p Type --value)\" = wayland "
            "&& loginctl show-session \"$session\" -p Name --value; done | "
            f"grep -Fx {shlex.quote(self.username)}",
            timeout=180,
        )
        (artifacts / "btrfs-rollback-graphical-session.txt").write_text(
            graphical + "\n", encoding="utf-8"
        )
        vm.screenshot("btrfs-rollback-installed-gnome")
        poweroff_request = self._ssh(
            vm,
            key,
            "sudo -n /usr/local/sbin/anduinos-acceptance-poweroff",
        )
        (artifacts / "btrfs-poweroff-request.txt").write_text(
            poweroff_request + "\n", encoding="utf-8"
        )
        self._wait_for_power_transition(
            vm,
            key,
            artifacts,
            "btrfs-final-poweroff",
            timeout=150,
        )
        vm.stop()

    def _prepare_power_control(
        self,
        vm: QemuVm,
        artifacts: Path,
        remote: str,
    ) -> Path:
        """Install an overlay-local, least-privilege reboot control channel."""

        assert vm.serial is not None
        key = artifacts / "control-key"
        subprocess.run(
            ("ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-f", str(key)),
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            text=True,
            timeout=30,
        )
        vm.serial.upload(key.with_suffix(".pub"), f"{remote}/control-key.pub", 0o644)
        vm.serial.upload(
            self.btrfs_rollback_oracle,
            f"{remote}/btrfs_rollback_oracle.py",
            0o644,
        )
        vm.serial.run(
            "set -euo pipefail\n"
            f"home=$(getent passwd {shlex.quote(self.username)} | cut -d: -f6)\n"
            f"install -d -m 0700 -o {shlex.quote(self.username)} "
            f"-g {shlex.quote(self.username)} \"$home/.ssh\"\n"
            f"cat {remote}/control-key.pub >> \"$home/.ssh/authorized_keys\"\n"
            f"chown {shlex.quote(self.username)}:{shlex.quote(self.username)} "
            "\"$home/.ssh/authorized_keys\"\n"
            "chmod 0600 \"$home/.ssh/authorized_keys\"\n"
            "cat > /usr/local/sbin/anduinos-acceptance-reboot <<'EOF'\n"
            "#!/bin/sh\n"
            "set -eu\n"
            # The controlled boot uses systemd.debug_shell=ttyS*.  That unit
            # deliberately has no shutdown dependencies and IgnoreOnIsolate,
            # so it is not part of the product's ordinary reboot contract.
            "systemctl stop debug-shell.service 2>/dev/null || true\n"
            "exec /usr/bin/systemd-run --unit=anduinos-acceptance-reboot "
            "--on-active=2s /usr/bin/systemctl --no-block "
            "--check-inhibitors=no reboot\n"
            "EOF\n"
            "cat > /usr/local/sbin/anduinos-acceptance-poweroff <<'EOF'\n"
            "#!/bin/sh\n"
            "set -eu\n"
            "systemctl stop debug-shell.service 2>/dev/null || true\n"
            "exec /usr/bin/systemd-run --unit=anduinos-acceptance-poweroff "
            "--on-active=2s /usr/bin/systemctl --no-block "
            "--check-inhibitors=no poweroff\n"
            "EOF\n"
            "cat > /usr/local/sbin/anduinos-acceptance-package-health <<'EOF'\n"
            "#!/bin/sh\n"
            "set -eu\n"
            "test -z \"$(dpkg --audit)\"\n"
            "apt-get check\n"
            "printf 'dpkg=ok\\napt=ok\\n'\n"
            "EOF\n"
            "cat > /usr/local/sbin/anduinos-acceptance-boot-health <<'EOF'\n"
            "#!/bin/sh\n"
            "set -eu\n"
            "test -s /boot/grub/grub.cfg\n"
            "grub-script-check /boot/grub/grub.cfg\n"
            "kernel=$(readlink -f /boot/vmlinuz)\n"
            "initrd=$(readlink -f /boot/initrd.img)\n"
            "test -s \"$kernel\"\n"
            "test -s \"$initrd\"\n"
            "lsinitrd \"$initrd\" >/dev/null\n"
            "printf 'boot-artifacts=ok\\n'\n"
            "EOF\n"
            "install -d -m 0755 /usr/local/lib/anduinos-acceptance\n"
            f"install -m 0755 {remote}/btrfs_rollback_oracle.py "
            "/usr/local/lib/anduinos-acceptance/btrfs_rollback_oracle.py\n"
            "btrfs subvolume get-default / > "
            "/usr/local/lib/anduinos-acceptance/btrfs-default.expected\n"
            "cat > /usr/local/sbin/anduinos-acceptance-rollback-state <<'EOF'\n"
            "#!/bin/bash\n"
            "set -euo pipefail\n"
            "test \"$#\" -eq 1\n"
            "expected_target=$1\n"
            "[[ \"$expected_target\" =~ ^[0-9a-f]{8}-[0-9a-f]{4}-"
            "[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$ ]]\n"
            "test \"$(findmnt -n -o FSTYPE /)\" = btrfs\n"
            "test \"$(findmnt -n -o FSROOT /)\" = /@root\n"
            "expected_default=$(cat "
            "/usr/local/lib/anduinos-acceptance/btrfs-default.expected)\n"
            "observed_default=$(btrfs subvolume get-default /)\n"
            "test \"$observed_default\" = \"$expected_default\"\n"
            "printf 'btrfs-default-subvolume=unchanged\\n'\n"
            "root_details=$(btrfs subvolume show --raw /)\n"
            "printf '%s\\n' \"$root_details\"\n"
            "printf '%s\\n' \"$root_details\" | "
            "grep -Eq '^[[:space:]]*Name:[[:space:]]+@root$'\n"
            "subvolumes=$(btrfs subvolume list /)\n"
            "printf '%s\\n' \"$subvolumes\"\n"
            "! printf '%s\\n' \"$subvolumes\" | "
            "grep -Eq '@root\\.snapshots-manager-(old|new)-'\n"
            "printf 'btrfs-staging-roots=absent\\n'\n"
            "standard_env=$(grub-editenv /boot/grub/grubenv list)\n"
            "! printf '%s\\n' \"$standard_env\" | "
            "grep -Eq '^(recordfail|menu_show_once)='\n"
            "recovery_env=/boot/efi/EFI/anduinos/btrfs-snapshots-manager-grubenv\n"
            "test -s \"$recovery_env\"\n"
            "recovery_selection=$(grub-editenv \"$recovery_env\" list)\n"
            "test -z \"$recovery_selection\"\n"
            "printf 'recovery-grubenv=empty\\n'\n"
            "unit=anduinos-btrfs-snapshots-manager-confirm.service\n"
            "test \"$(systemctl show \"$unit\" -p Result --value)\" = success\n"
            "test \"$(systemctl show \"$unit\" -p ExecMainStatus --value)\" = 0\n"
            "printf 'confirm-service=success\\n'\n"
            "/usr/bin/python3 "
            "/usr/local/lib/anduinos-acceptance/btrfs_rollback_oracle.py "
            "\"$expected_target\"\n"
            "journalctl -b -u \"$unit\" --no-pager\n"
            "EOF\n"
            "chmod 0755 /usr/local/sbin/anduinos-acceptance-reboot "
            "/usr/local/sbin/anduinos-acceptance-poweroff "
            "/usr/local/sbin/anduinos-acceptance-package-health "
            "/usr/local/sbin/anduinos-acceptance-boot-health "
            "/usr/local/sbin/anduinos-acceptance-rollback-state\n"
            f"printf '%s ALL=(root) NOPASSWD: "
            f"/usr/local/sbin/anduinos-acceptance-reboot, "
            f"/usr/local/sbin/anduinos-acceptance-poweroff, "
            f"/usr/local/sbin/anduinos-acceptance-package-health, "
            f"/usr/local/sbin/anduinos-acceptance-boot-health, "
            f"/usr/local/sbin/anduinos-acceptance-rollback-state\\n' "
            f"{shlex.quote(self.username)} "
            "> /etc/sudoers.d/anduinos-acceptance-power\n"
            "chmod 0440 /etc/sudoers.d/anduinos-acceptance-power\n"
            "visudo -cf /etc/sudoers.d/anduinos-acceptance-power\n"
            # This is an overlay-local harness channel, not a product SSH
            # assertion.  A persistent service is intentional here: QEMU's
            # host forwarding accepts a TCP connection even while a restored
            # guest has no listener, which can make a socket-activation probe
            # block during the recovery boot.  The dedicated service and key
            # are both captured by the pre-mutation snapshot and discarded
            # with the feature overlay.
            "systemctl enable --now ssh.service\n",
            timeout=60,
        )
        self._ssh_eventually(vm, key, "id -un | grep -Fx " + shlex.quote(self.username))
        return key

    def _wait_for_power_transition(
        self,
        vm: QemuVm,
        key: Path,
        artifacts: Path,
        label: str,
        *,
        timeout: float,
    ) -> None:
        """Wait for QEMU exit and retain systemd state if shutdown stalls."""

        if vm.process is None:
            raise TestFailure("Power transition was requested before QEMU started")
        deadline = time.monotonic() + timeout
        diagnostic_at = time.monotonic() + min(15.0, timeout / 3)
        diagnostic_path = artifacts / f"{label}-diagnostics.txt"
        diagnostic_written = False
        while time.monotonic() < deadline:
            if vm.process.poll() is not None:
                return
            if not diagnostic_written and time.monotonic() >= diagnostic_at:
                diagnostic_written = True
                output = self._collect_power_transition_diagnostics(vm, key)
                diagnostic_path.write_text(output + "\n", encoding="utf-8")
            time.sleep(0.5)
        if not diagnostic_written:
            diagnostic_path.write_text(
                "QEMU remained alive but the diagnostic collection deadline "
                "was not reached.\n",
                encoding="utf-8",
            )
        raise TestFailure(
            f"Guest {label.replace('-', ' ')} did not stop QEMU within "
            f"{timeout:.0f} seconds; see {diagnostic_path.name}"
        )

    def _collect_power_transition_diagnostics(self, vm: QemuVm, key: Path) -> str:
        """Collect shutdown state over serial first, because sshd stops early."""

        command = (
            "set +e; "
            "date --iso-8601=seconds; uptime; "
            "printf '\\n== system state ==\\n'; "
            "systemctl is-system-running; "
            "systemctl show -p ActiveState -p SubState -p Job "
            "reboot.target poweroff.target shutdown.target final.target; "
            "printf '\\n== acceptance units ==\\n'; "
            "systemctl status anduinos-acceptance-reboot.timer "
            "anduinos-acceptance-reboot.service "
            "anduinos-acceptance-poweroff.timer "
            "anduinos-acceptance-poweroff.service --no-pager; "
            "printf '\\n== jobs ==\\n'; systemctl list-jobs --no-pager; "
            "printf '\\n== failed units ==\\n'; "
            "systemctl list-units --state=failed --no-pager; "
            "printf '\\n== inhibitors ==\\n'; loginctl list-inhibitors --no-pager; "
            "printf '\\n== processes ==\\n'; "
            "ps -eo pid,ppid,state,wchan:32,comm,args --sort=pid; "
            "printf '\\n== transition journal ==\\n'; "
            "journalctl -b --since '-3 min' --no-pager "
            "-u anduinos-acceptance-reboot.timer "
            "-u anduinos-acceptance-reboot.service "
            "-u anduinos-acceptance-poweroff.timer "
            "-u anduinos-acceptance-poweroff.service "
            "-u systemd-logind.service"
        )
        failures: list[str] = []
        serial = getattr(vm, "serial", None)
        if serial is not None:
            try:
                result = serial.run(command, timeout=20, check=False)
                return "Collected over the root serial control channel.\n" + result.stdout
            except Exception as error:
                failures.append(
                    "Serial diagnostic collection failed: "
                    f"{type(error).__name__}: {error}"
                )
        try:
            output = self._ssh(vm, key, command, timeout=30, check=False)
            prefix = "\n".join(failures)
            if prefix:
                prefix += "\n"
            return prefix + "Collected over SSH.\n" + output
        except Exception as error:
            failures.append(
                "SSH diagnostic collection failed while QEMU remained alive: "
                f"{type(error).__name__}: {error}"
            )
            return "\n".join(failures)

    @staticmethod
    def _graphical_boot_ready_command() -> str:
        """Do not confuse early sshd availability with a completed boot."""

        return (
            "systemctl is-active --quiet graphical.target && "
            "systemctl is-active --quiet gdm"
        )

    @staticmethod
    def _rollback_health_command(
        root_sentinel: str,
        home_sentinel: str,
        deployment_id: str,
    ) -> str:
        return (
            "set -euo pipefail; "
            "test \"$(findmnt -n -o FSTYPE /)\" = btrfs; "
            "test \"$(findmnt -n -o FSROOT /)\" = /@root; "
            "! dpkg-query -W -f='${db:Status-Abbrev}' docker.io 2>/dev/null "
            "| grep -q '^ii '; "
            "test ! -e /usr/bin/docker; "
            f"test ! -e {shlex.quote(root_sentinel)}; "
            f"test -f {shlex.quote(home_sentinel)}; "
            "sudo -n /usr/local/sbin/anduinos-acceptance-package-health; "
            "printf 'docker=absent\\nroot-sentinel=absent\\n"
            "home-sentinel=present\\n'; "
            "systemctl is-active --quiet graphical.target; "
            "sudo -n /usr/local/sbin/anduinos-acceptance-boot-health; "
            "sudo -n /usr/local/sbin/anduinos-acceptance-rollback-state "
            f"{shlex.quote(deployment_id)}; "
            "printf 'rollback-health=ok\\n'"
        )

    def _ssh_eventually(
        self,
        vm: QemuVm,
        key: Path,
        command: str,
        *,
        timeout: float = 120,
    ) -> str:
        deadline = time.monotonic() + timeout
        last = ""
        while time.monotonic() < deadline:
            process = getattr(vm, "process", None)
            if process is not None:
                returncode = process.poll()
                if returncode is not None:
                    raise TestFailure(
                        "QEMU exited while waiting for SSH control after boot "
                        f"(exit code {returncode})"
                    )
            remaining = deadline - time.monotonic()
            attempt_timeout = max(1.0, min(15.0, remaining))
            try:
                return self._ssh(vm, key, command, timeout=attempt_timeout)
            except (TestFailure, subprocess.TimeoutExpired) as error:
                last = f"{type(error).__name__}: {error}"
                time.sleep(2)
        raise TestFailure("SSH control did not become healthy after boot: " + last[-4000:])

    def _ssh(
        self,
        vm: QemuVm,
        key: Path,
        command: str,
        *,
        timeout: float = 60,
        check: bool = True,
    ) -> str:
        invocation = (
            "ssh",
            "-F",
            "/dev/null",
            "-i",
            str(key),
            "-p",
            str(vm.config.ssh_forward_port),
            "-o",
            "BatchMode=yes",
            "-o",
            "StrictHostKeyChecking=no",
            "-o",
            "UserKnownHostsFile=/dev/null",
            "-o",
            "ConnectTimeout=10",
            "-o",
            "ConnectionAttempts=1",
            "-o",
            "ServerAliveInterval=5",
            "-o",
            "ServerAliveCountMax=1",
            f"{self.username}@127.0.0.1",
            command,
        )
        result = subprocess.run(
            invocation,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            check=False,
            timeout=timeout,
        )
        if check and result.returncode != 0:
            raise TestFailure(
                f"Feature SSH control failed with {result.returncode}:\n"
                + result.stdout[-8000:]
            )
        return result.stdout
