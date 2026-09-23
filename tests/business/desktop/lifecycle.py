"""Ordinary reboot, Btrfs rollback, power transition, and SSH behavior."""

import os
import tempfile

from .context import *  # noqa: F403
from framework.grub import boot_iso_with_debug_shell


def _revert_checkpoint_probe_command() -> str:
    history_probe = (
        "jq -e '.phase == \"reverted\" and "
        ".checkpoint == \"reverted-recorded\"' "
        "/.snapshots/anduinos-btrfs-snapshots-manager/"
        "rollback-history/*.json >/dev/null"
    )
    return (
        "set -e; "
        "sudo -n journalctl -b -t dracut-pre-mount -o cat --no-pager "
        "| grep -Fx 'SNAPSHOTS-MANAGER-CHECKPOINT reverted-recorded'; "
        "sudo -n sh -c " + shlex.quote(history_probe) + "; "
        "printf 'reverted-history=verified\\n'"
    )


def _validate_rescue_pointer_trace(path: Path) -> None:
    required = {
        "rescue-select-installation",
        "rescue-open-snapshots",
        "rescue-select-snapshot",
        "rescue-confirm-restore",
    }
    completed = set()
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        event = json.loads(line)
        if event.get("event") != "host-qmp-request":
            continue
        if event.get("kind") == "click" and event.get("completed") is True:
            completed.add(str(event.get("request") or ""))
    missing = sorted(required - completed)
    if missing:
        raise TestFailure(
            "Rescue Center was not driven through every required real pointer "
            f"action: missing {missing!r}"
        )


class LifecycleChecks:
    def _exercise_rescue_center_offline_restore(
        self,
        vm: QemuVm,
        base: PromotedBase,
        artifacts: Path,
    ) -> None:
        """Damage an installed desktop and restore it from the real Live ISO."""

        assert vm.serial is not None and vm.qmp is not None
        suite_id = "rescue-center-offline-restore"
        title = "Rescue Center acceptance baseline"
        root_sentinel = "/etc/anduinos-rescue-center-damaged"
        home_sentinel = f"/home/{self.username}/anduinos-rescue-home-survives"
        remote = "/run/anduinos-feature-rescue-center"
        vm.serial.run(f"install -d -m 0777 {remote}")
        key = self._prepare_power_control(vm, artifacts, remote)
        system_name = vm.serial.run(
            ". /etc/os-release; printf '%s\\n' \"$PRETTY_NAME\""
        ).stdout.strip().splitlines()[-1]
        if not system_name:
            raise TestFailure("The installed system has no PRETTY_NAME")

        created = vm.serial.run(
            "set -euo pipefail\n"
            "test \"$(findmnt -n -o FSTYPE /)\" = btrfs\n"
            "test \"$(findmnt -n -o FSROOT /)\" = /@root\n"
            "test -x /usr/bin/gnome-shell\n"
            "! dpkg-query -W -f='${db:Status-Abbrev}' anduinos-rescue-center "
            "2>/dev/null | grep -q '^ii '\n"
            "anduinos-btrfs-snapshots-manager-cli create --json "
            f"{shlex.quote(title)} "
            f"{shlex.quote('Baseline for Live Rescue Center acceptance')}\n",
            timeout=300,
        )
        deployment = _json_object(created.stdout)
        deployment_id = str(
            deployment.get("id") or deployment.get("deployment_id") or ""
        )
        if not re.fullmatch(
            r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}",
            deployment_id,
        ):
            raise TestFailure("Rescue baseline did not return a deployment ID")
        (artifacts / "rescue-baseline-created.json").write_text(
            created.stdout + "\n", encoding="utf-8"
        )

        damaged = vm.serial.run(
            "set -euo pipefail\n"
            f"printf '%s\\n' 'root damage must disappear' > {root_sentinel}\n"
            f"printf '%s\\n' 'home data must survive rescue' > {home_sentinel}\n"
            f"chown {shlex.quote(self.username)}:{shlex.quote(self.username)} "
            f"{home_sentinel}\n"
            "dpkg --force-depends --remove gnome-shell\n"
            "! dpkg-query -W -f='${db:Status-Abbrev}' gnome-shell "
            "2>/dev/null | grep -q '^ii '\n"
            "test ! -e /usr/bin/gnome-shell\n"
            f"test -f {root_sentinel}\n"
            f"test -f {home_sentinel}\n"
            "sync\n"
            "printf 'critical-package=gnome-shell\\n'\n"
            "printf 'desktop-damage=package-removed\\n'\n"
            f"printf 'deployment-id=%s\\n' {shlex.quote(deployment_id)}\n"
        )
        (artifacts / "rescue-damaged-system.txt").write_text(
            damaged.stdout + "\n", encoding="utf-8"
        )
        _power_off(vm)

        self.phase_callback(
            base.scenario.id,
            suite_id,
            "Proving the damaged installation cannot start GNOME",
        )
        vm.start(attach_iso=False, phase="rescue-damaged-boot")
        broken = self._ssh_eventually(
            vm,
            key,
            "set -euo pipefail; "
            "! dpkg-query -W -f='${db:Status-Abbrev}' gnome-shell "
            "2>/dev/null | grep -q '^ii '; "
            "test ! -e /usr/bin/gnome-shell; "
            "sleep 15; "
            "! pgrep -x gnome-shell >/dev/null; "
            "printf 'critical-package=absent\\n"
            "graphical-shell=unavailable\\n'",
            timeout=self.options.boot_timeout_seconds,
        )
        (artifacts / "rescue-damaged-boot.txt").write_text(
            broken + "\n", encoding="utf-8"
        )
        vm.screenshot("rescue-damaged-boot")
        self._ssh(
            vm,
            key,
            "sudo -n /usr/local/sbin/anduinos-acceptance-poweroff",
        )
        self._wait_for_power_transition(
            vm,
            key,
            artifacts,
            "rescue-damaged-poweroff",
            timeout=150,
        )
        vm.stop()

        self.phase_callback(
            base.scenario.id,
            suite_id,
            "Booting the Live ISO and restoring the damaged installation",
        )
        vm.start(attach_iso=True, phase="rescue-live")
        assert vm.qmp is not None and vm.serial is not None
        boot_iso_with_debug_shell(
            vm.qmp,
            vm.serial,
            base.architecture,
            firmware_delay=self.options.firmware_delay_seconds,
            spice_socket=vm.spice_socket,
            scratch_dir=artifacts,
        )
        vm.serial.timeout = self.options.command_timeout_seconds
        vm.serial.wait_for_shell(self.options.boot_timeout_seconds)
        live_preflight = vm.serial.run(
            "set -euo pipefail\n"
            "test -s /run/anduinos-live/environment\n"
            "dpkg-query -W -f='${db:Status-Abbrev} ${Version}\\n' "
            "anduinos-rescue-center | grep '^ii '\n"
            "test -x /usr/bin/anduinos-rescue-center\n"
            "helper=/usr/libexec/anduinos-rescue-center-live-helper\n"
            "test -x \"$helper\"\n"
            "probe=$(\"$helper\" probe)\n"
            "printf 'probe=%s\\n' \"$probe\"\n"
            "test \"$(printf '%s' \"$probe\" | jq '[.disks[].partitions[] "
            "| select(.os_kind == \"anduinos\")] | length')\" = 1\n"
            "printf 'live-rescue-preflight=ready\\n'\n",
            timeout=300,
        )
        (artifacts / "rescue-live-preflight.txt").write_text(
            live_preflight.stdout + "\n", encoding="utf-8"
        )
        live_user = _graphical_user(vm.serial)
        live_remote = "/run/anduinos-live-rescue-acceptance"
        vm.serial.run(f"install -d -m 0777 {live_remote}/evidence")
        self.driver.upload(vm.serial, live_remote)
        launched = vm.serial.run(
            _desktop_command(
                live_user,
                (
                    "sh",
                    "-c",
                    "exec setsid --fork anduinos-rescue-center "
                    ">/tmp/anduinos-rescue-center-acceptance.log 2>&1",
                ),
            ),
            timeout=120,
        )
        (artifacts / "rescue-center-launch.txt").write_text(
            launched.stdout + "\n", encoding="utf-8"
        )
        pointer_trace = artifacts / "rescue-center-pointer-requests.jsonl"
        driver_command = _desktop_command(
            live_user,
            (
                "python3",
                f"{live_remote}/atspi_driver.py",
                "rescue-center-offline-restore",
                "--expected",
                title,
                "--system-name",
                system_name,
                "--evidence",
                f"{live_remote}/evidence",
            ),
            managed=True,
        )
        restored_by_ui = _run_with_qmp_key_requests(
            vm,
            driver_command,
            timeout=1200,
            request_trace=pointer_trace,
        )
        (artifacts / "rescue-center-ui-events.jsonl").write_text(
            restored_by_ui.stdout + "\n", encoding="utf-8"
        )
        _retrieve_tree(
            vm.serial,
            live_remote,
            artifacts / "guest-rescue-center-evidence",
        )
        if restored_by_ui.returncode != 0:
            raise TestFailure(
                "The Rescue Center GUI could not restore the damaged system:\n"
                + restored_by_ui.stdout[-8000:]
            )
        _validate_rescue_pointer_trace(pointer_trace)
        vm.screenshot("rescue-live-after-restore")
        _power_off(vm)

        self.phase_callback(
            base.scenario.id,
            suite_id,
            "Booting the restored installation and verifying GNOME",
        )
        vm.start(attach_iso=False, phase="rescue-restored")
        restored = self._ssh_eventually(
            vm,
            key,
            "set -euo pipefail; "
            "systemctl is-active --quiet graphical.target; "
            "systemctl is-active --quiet gdm; "
            "test \"$(dpkg-query -W -f='${db:Status-Abbrev}' gnome-shell)\" = 'ii '; "
            "test -x /usr/bin/gnome-shell; "
            f"test ! -e {shlex.quote(root_sentinel)}; "
            f"test \"$(cat {shlex.quote(home_sentinel)})\" = "
            "'home data must survive rescue'; "
            "! dpkg-query -W -f='${db:Status-Abbrev}' anduinos-rescue-center "
            "2>/dev/null | grep -q '^ii '; "
            "test \"$(findmnt -n -o FSTYPE /)\" = btrfs; "
            "test \"$(findmnt -n -o FSROOT /)\" = /@root; "
            "sudo -n /usr/local/sbin/anduinos-acceptance-rescue-state "
            f"{shlex.quote(deployment_id)}; "
            "sudo -n /usr/local/sbin/anduinos-acceptance-package-health; "
            "printf 'root-repaired=yes\\nhome-preserved=yes\\n"
            "offline-transaction=archived\\ngraphical-boot=ready\\n'",
            timeout=self.options.boot_timeout_seconds * 2,
        )
        (artifacts / "rescue-restored-system.txt").write_text(
            restored + "\n", encoding="utf-8"
        )
        self._login_gdm_over_ssh(vm, key, timeout=120)
        vm.screenshot("rescue-restored-gnome")
        self._ssh(vm, key, "sync")
        vm.stop()

    def _login_gdm_over_ssh(self, vm: QemuVm, key: Path, *, timeout: float) -> None:
        """Verify the restored graphical session without a debug serial shell."""

        assert vm.qmp is not None
        ready = (
            "set -e; "
            "uid=$(id -u); runtime=/run/user/$uid; "
            "test -S \"$runtime/bus\"; "
            "find \"$runtime\" -maxdepth 1 -type s "
            "-name 'wayland-[0-9]*' | grep -q .; "
            f"pgrep -u {shlex.quote(self.username)} -x gnome-shell >/dev/null; "
            "printf 'graphical-user=ready\\n'"
        )
        deadline = time.monotonic() + timeout
        next_input = 0.0
        attempts = 0
        while time.monotonic() < deadline:
            if "graphical-user=ready" in self._ssh(
                vm, key, ready, timeout=15, check=False
            ):
                return
            now = time.monotonic()
            if now >= next_input and attempts < 3:
                if attempts == 0:
                    vm.qmp.send_key("ret")
                    time.sleep(2)
                else:
                    vm.qmp.send_key("ctrl-a")
                    time.sleep(1)
                vm.qmp.type_text(self.password, interval=0.06)
                vm.qmp.send_key("ret")
                attempts += 1
                next_input = time.monotonic() + 15
            time.sleep(2)
        raise TestFailure(
            "The Rescue Center restored the system, but a GNOME user session "
            f"did not start after GDM login; attempts={attempts}"
        )

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
            managed=True,
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

    def _exercise_factory_reset_preserve_home(
        self,
        vm: QemuVm,
        base: PromotedBase,
        artifacts: Path,
    ) -> None:
        self._exercise_factory_reset(
            vm,
            base,
            artifacts,
            suite_id="factory-reset-preserve-home",
            erase_home=False,
            interrupt_after_apply=False,
        )

    def _exercise_factory_reset_erase_home(
        self,
        vm: QemuVm,
        base: PromotedBase,
        artifacts: Path,
    ) -> None:
        self._exercise_factory_reset(
            vm,
            base,
            artifacts,
            suite_id="factory-reset-erase-home",
            erase_home=True,
            interrupt_after_apply=False,
        )

    def _exercise_factory_reset_power_loss(
        self,
        vm: QemuVm,
        base: PromotedBase,
        artifacts: Path,
    ) -> None:
        self._exercise_factory_reset(
            vm,
            base,
            artifacts,
            suite_id="factory-reset-power-loss",
            erase_home=True,
            interrupt_after_apply=True,
        )

    def _exercise_factory_reset_repeat(
        self, vm: QemuVm, base: PromotedBase, artifacts: Path,
    ) -> None:
        """Two real UI resets of the same isolated disk, without Internet."""
        if not vm.config.restrict_network:
            raise TestFailure("Repeated factory recovery requires QEMU network isolation")
        (artifacts / "network-isolation.txt").write_text(
            "QEMU user networking: restrict=on; only explicit SSH forwarding allowed.\n",
            encoding="utf-8",
        )
        workloads: list[dict] = []
        for erase_home, name in ((False, "preserve"), (True, "erase")):
            round_artifacts = artifacts / name
            round_artifacts.mkdir()
            self._exercise_factory_reset(
                vm, base, round_artifacts,
                suite_id=f"factory-reset-repeat-{name}",
                erase_home=erase_home, interrupt_after_apply=False,
                workloads=workloads,
            )
        vm.stop()

    def _exercise_factory_reset(
        self,
        vm: QemuVm,
        base: PromotedBase,
        artifacts: Path,
        *,
        suite_id: str,
        erase_home: bool,
        interrupt_after_apply: bool,
        workloads: list[dict] | None = None,
    ) -> None:
        """Exercise the dedicated factory workflow, including atomic fallback."""

        assert vm.serial is not None and vm.qmp is not None
        root_sentinel = f"/etc/anduinos-acceptance-{suite_id}"
        home_sentinel = f"/home/{self.username}/anduinos-acceptance-{suite_id}"
        remote = f"/run/anduinos-feature-{suite_id}"
        vm.serial.run(f"install -d -m 0777 {shlex.quote(remote)}/evidence")
        self.driver.upload(vm.serial, remote)
        key = self._prepare_power_control(vm, artifacts, remote)
        workload_source = (
            Path(__file__).resolve().parents[2]
            / "assertions/guest/factory_reset_workload.py"
        ).read_text(encoding="utf-8") if workloads is not None else ""
        mutation = (
            "python3 -c " + shlex.quote(workload_source)
            + " prepare --home " + shlex.quote(home_sentinel + ".d")
            + ' --factory-root "$root_factory"\n'
            if workloads is not None else ""
        )

        prepared = vm.serial.run(
            "set -euo pipefail\n"
            "store=/.snapshots/anduinos-btrfs-snapshots-manager\n"
            "test \"$(findmnt -n -o FSTYPE /)\" = btrfs\n"
            "test \"$(findmnt -n -o FSROOT /)\" = /@root\n"
            "root_factory=$(jq -r 'select(.kind == \"factory\" and "
            ".state == \"ready\" and .pinned == true and .title == \"New OS\") | .id' "
            "\"$store/metadata/\"*.json)\n"
            "home_factory=$(jq -r 'select(.kind == \"factory\" and "
            ".state == \"ready\" and .pinned == true and (.title == \"New OS\" or .title == \"New OS Home\")) | .id' "
            "\"$store/personal/metadata/\"*.json)\n"
            "test \"$(printf '%s\\n' \"$root_factory\" | grep -c .)\" = 1\n"
            "test \"$(printf '%s\\n' \"$home_factory\" | grep -c .)\" = 1\n"
            f"printf 'root mutation must disappear\\n' > {shlex.quote(root_sentinel)}\n"
            f"printf 'home mutation contract\\n' > {shlex.quote(home_sentinel)}\n"
            f"chown {shlex.quote(self.username)}:{shlex.quote(self.username)} "
            f"{shlex.quote(home_sentinel)}\n"
            + mutation +
            # This is fixture setup, not the factory-reset action under test.
            # busctl's implicit 25-second limit can expire during the helper's
            # durable Btrfs sync on a slow host even when creation completes.
            # Call the same product D-Bus method with an explicit bounded wait.
            "personal=$(busctl --system --timeout=180 --json=short call "
            "org.anduinos.BtrfsSnapshotsManager "
            "/org/anduinos/BtrfsSnapshotsManager "
            "org.anduinos.BtrfsSnapshotsManager.Helper "
            "CreatePersonalSnapshot ssb "
            "'Factory reset acceptance Home history' "
            "'Home history retained across rollback' false)\n"
            "test \"$(printf '%s\\n' \"$personal\" | jq -er '.data[0] | booleans | tostring')\" = true\n"
            "personal_id=$(printf '%s\\n' \"$personal\" | jq -er '.data[1] | fromjson | .id')\n"
            f"test -f {shlex.quote(root_sentinel)}\n"
            f"test -f {shlex.quote(home_sentinel)}\n"
            "test -f \"$store/personal/metadata/$personal_id.json\"\n"
            "printf 'factory-root-id=%s\\nfactory-home-id=%s\\n"
            "personal-snapshot-id=%s\\n' "
            "\"$root_factory\" \"$home_factory\" \"$personal_id\"\n"
            "status=$(anduinos-btrfs-snapshots-manager-cli status --json)\n"
            "printf '%s\\n' \"$status\"\n"
            "if printf '%s' \"$status\" | jq -e '.home_rollback_available == true' >/dev/null; then "
            "printf 'home-history-policy=preserve\\n'; fi\n",
            timeout=300,
        )
        (artifacts / "factory-reset-before.txt").write_text(
            prepared.stdout + "\n", encoding="utf-8"
        )
        factory_root_id = _last_value(prepared.stdout, "factory-root-id")
        factory_home_id = _last_value(prepared.stdout, "factory-home-id")
        personal_snapshot_id = _last_value(prepared.stdout, "personal-snapshot-id")
        preserve_history = "home-history-policy=preserve" in prepared.stdout
        if workloads is not None:
            workload = json.loads(_last_value(prepared.stdout, "factory-workload"))
            workload.update(personal_snapshot_id=personal_snapshot_id,
                            factory_root_id=factory_root_id, factory_home_id=factory_home_id)
            if workloads and any(workloads[0][field] != workload[field] for field in
                                 ("factory_root_id", "factory_home_id", "version", "sha256")):
                raise TestFailure("Second reset does not reuse the original factory baseline")
            workloads.append(workload)

        command = [
            "python3",
            f"{remote}/atspi_driver.py",
            "factory-reset-arm",
            "--evidence",
            f"{remote}/evidence",
        ]
        if erase_home:
            command.append("--erase-home")
        armed = _run_with_qmp_key_requests(
            vm,
            # The GUI must belong to the desktop user's session manager so
            # Polkit can reach its real GNOME authentication agent. Merely
            # copying the session bus into a serial runuser process is not
            # equivalent to a desktop launch.
            _desktop_command(self.username, tuple(command), managed=True),
            timeout=300,
            secret_text=self.password,
        )
        (artifacts / "factory-reset-atspi-events.jsonl").write_text(
            armed.stdout + "\n", encoding="utf-8"
        )
        _retrieve_tree(vm.serial, remote, artifacts / "guest-factory-reset-evidence")
        _retrieve_file(
            vm.serial,
            "/tmp/anduinos-factory-reset.stdout",
            artifacts / "factory-reset-app.stdout",
        )
        if armed.returncode != 0:
            raise TestFailure(
                "The dedicated factory-reset UI could not arm recovery:\n"
                + armed.stdout[-8000:]
            )

        if interrupt_after_apply:
            # A normal product boot has no serial console. This fault-only
            # overlay exposes the durable checkpoint and suppresses userspace
            # confirmation for this boot, avoiding a host scheduling race.
            # Do not alter the kernel, initramfs, snapshots, or transaction.
            fault_source = (Path(__file__).resolve().parents[2]
                            / "assertions/guest/recovery_power_loss.py").read_text()
            fault_command = "python3 -c " + shlex.quote(fault_source)
            fault_arch = shlex.quote(vm.config.architecture.value)
            observation = vm.serial.run(
                "set -e; " + fault_command + " prepare " + fault_arch
                + "; grub-script-check /boot/grub/grub.cfg", timeout=30)
            (artifacts / "power-loss-instrumentation.txt").write_text(observation.stdout)

        # Repeated recovery has two round-specific artifact/sentinel names,
        # but both rounds belong to one declared feature suite.
        progress_suite = "factory-reset-repeat" if workloads is not None else suite_id
        self.phase_callback(base.scenario.id, progress_suite, "Rebooting into factory recovery")
        request = self._ssh(
            vm,
            key,
            "sudo -n /usr/local/sbin/anduinos-acceptance-reboot",
        )
        (artifacts / "factory-reset-reboot-request.txt").write_text(
            request + "\n", encoding="utf-8"
        )
        self._wait_for_power_transition(
            vm,
            key,
            artifacts,
            f"{suite_id}-reboot",
            timeout=150,
        )
        vm.stop()
        vm.start(attach_iso=False, phase=f"{suite_id}-apply")

        if interrupt_after_apply:
            assert vm.serial is not None
            vm.serial.wait_for_text(
                "SNAPSHOTS-MANAGER-CHECKPOINT booted-unconfirmed-recorded",
                timeout=self.options.boot_timeout_seconds,
            )
            (artifacts / "factory-reset-power-loss.txt").write_text(
                "QEMU stopped immediately after the durable "
                "booted-unconfirmed-recorded checkpoint.\n",
                encoding="utf-8",
            )
            vm.stop()
            vm.start(attach_iso=False, phase=f"{suite_id}-revert")
            # The fallback boots its original GRUB entry, which does not have
            # the fault-only serial console argument. Read the exact checkpoint
            # from this boot's durable journal and transaction history instead.
            reverted = self._ssh_eventually(
                vm, key, _revert_checkpoint_probe_command(),
                timeout=self.options.boot_timeout_seconds,
            )
            (artifacts / "power-loss-revert-evidence.txt").write_text(reverted)
            restored = self._ssh_eventually(
                vm, key, "set -e; sudo -n " + fault_command + " restore " + fault_arch
                + "; sudo -n grub-script-check /boot/grub/grub.cfg",
                timeout=self.options.boot_timeout_seconds)
            (artifacts / "power-loss-instrumentation-restored.txt").write_text(restored)
            # The mask was a boot argument, not a permanent unit override.
            # A clean boot removes it and lets the normal confirmation service
            # reconcile the reverted transaction before the health oracle.
            self._ssh(vm, key, "sudo -n /usr/local/sbin/anduinos-acceptance-reboot")
            self._wait_for_power_transition(vm, key, artifacts,
                                            "power-loss-clean-boot", timeout=150)
            vm.stop()
            vm.start(attach_iso=False, phase="power-loss-clean-boot")
            expected_root = True
            expected_home = True
            expected_history = True
            expected_transaction = "reverted"
        else:
            expected_root = False
            expected_home = not erase_home
            expected_history = preserve_history or not erase_home
            expected_transaction = "confirmed"

        health_command = self._factory_reset_health_command(
            root_sentinel=root_sentinel,
            home_sentinel=home_sentinel,
            personal_snapshot_id=personal_snapshot_id,
            factory_root_id=factory_root_id,
            factory_home_id=factory_home_id,
            root_present=expected_root,
            home_present=expected_home,
            personal_history_present=expected_history,
            transaction=expected_transaction,
        )
        if erase_home and not interrupt_after_apply:
            health = self._ssh_password_eventually(
                vm,
                health_command,
                timeout=self.options.boot_timeout_seconds * 2,
            )
            try:
                self._ssh(vm, key, "true", timeout=20)
            except TestFailure:
                health += "\nold-home-key=absent\n"
            else:
                raise TestFailure(
                    "Factory reset with Home erasure preserved the pre-reset SSH key"
                )
        else:
            health = self._ssh_eventually(
                vm,
                key,
                health_command,
                timeout=self.options.boot_timeout_seconds * 2,
            )
        _validate_factory_reset_health(
            health,
            root_present=expected_root,
            home_present=expected_home,
            personal_history_present=expected_history,
            transaction=expected_transaction,
        )
        (artifacts / "factory-reset-after.txt").write_text(
            health + "\n", encoding="utf-8"
        )
        if workloads is not None:
            # Only after an ordinary boot and successful recovery checks, add
            # a runtime-only serial channel for GDM input and the next round.
            tty = "ttyS0" if vm.config.architecture.value == "amd64" else "ttyAMA0"
            override = ("[Unit]\nConditionPathExists=\nConditionPathExists=/dev/" + tty
                        + "\n[Service]\nTTYPath=/dev/" + tty + "\n")
            setup = (
                "set -e; install -d /run/systemd/system/debug-shell.service.d; "
                "printf %s " + shlex.quote(override)
                + " > /run/systemd/system/debug-shell.service.d/acceptance.conf; "
                f"systemctl stop serial-getty@{tty}.service; "
                "systemctl daemon-reload; systemctl start debug-shell.service"
            )
            setup_command = "sudo -n bash -c " + shlex.quote(setup)
            if erase_home:
                self._ssh_password(vm, setup_command)
            else:
                self._ssh(vm, key, setup_command)
            assert vm.serial is not None
            vm.serial.wait_for_shell(self.options.boot_timeout_seconds)
            _login_gdm(vm, self.username, self.password,
                       timeout=self.options.boot_timeout_seconds)
            (artifacts / "desktop-login.txt").write_text(
                f"graphical-user={_graphical_user(vm.serial)}\n", encoding="utf-8"
            )
            # History browsing requires the real active local user, not the
            # remote control session used to check boot/recovery health.
            verify = "sudo -n python3 -c " + shlex.quote(workload_source)
            verify += " verify --workloads " + shlex.quote(json.dumps(workloads))
            if erase_home:
                verify += " --erase-home"
                evidence = self._ssh_password(vm, verify)
            else:
                evidence = self._ssh(vm, key, verify)
            (artifacts / "factory-workload-after.txt").write_text(
                evidence + "\n", encoding="utf-8"
            )
        vm.screenshot(f"{suite_id}-completed")
        if erase_home and not interrupt_after_apply:
            self._ssh_password(vm, "sync", timeout=180)
        else:
            self._ssh(vm, key, "sync", timeout=180)
        if workloads is None:
            vm.stop()

    @staticmethod
    def _factory_reset_health_command(
        *,
        root_sentinel: str,
        home_sentinel: str,
        personal_snapshot_id: str,
        factory_root_id: str,
        factory_home_id: str,
        root_present: bool,
        home_present: bool,
        personal_history_present: bool,
        transaction: str,
    ) -> str:
        root_test = "test -f" if root_present else "test ! -e"
        home_test = "test -f" if home_present else "test ! -e"
        history_test = "test -f" if personal_history_present else "test ! -e"
        confirmation = (
            "test \"$(systemctl show "
            "anduinos-btrfs-snapshots-manager-confirm.service "
            "-p Result --value)\" = success; "
            "test \"$(systemctl show "
            "anduinos-btrfs-snapshots-manager-confirm.service "
            "-p ExecMainStatus --value)\" = 0; "
            if transaction == "confirmed"
            else ""
        )
        return (
            "set -euo pipefail; "
            "store=/.snapshots/anduinos-btrfs-snapshots-manager; "
            f"factory_root_id={shlex.quote(factory_root_id)}; "
            f"factory_home_id={shlex.quote(factory_home_id)}; "
            f"personal_id={shlex.quote(personal_snapshot_id)}; "
            "test \"$(findmnt -n -o FSTYPE /)\" = btrfs; "
            "test \"$(findmnt -n -o FSROOT /)\" = /@root; "
            f"{root_test} {shlex.quote(root_sentinel)}; "
            f"{home_test} {shlex.quote(home_sentinel)}; "
            f"sudo -n {history_test} \"$store/personal/metadata/$personal_id.json\"; "
            "test -z \"$(sudo -n dpkg --audit)\"; "
            "sudo -n apt-get check >/dev/null; "
            "test -s /boot/grub/grub.cfg; "
            "sudo -n grub-script-check /boot/grub/grub.cfg; "
            "test -s /boot/vmlinuz; test -s /boot/initrd.img; "
            "sudo -n lsinitrd /boot/initrd.img >/dev/null; "
            "systemctl is-active --quiet graphical.target; "
            "systemctl is-active --quiet gdm; "
            "status=$(sudo -n anduinos-btrfs-snapshots-manager-cli status --json); "
            "test \"$(printf '%s' \"$status\" | jq -r '.pending')\" = null; "
            "test \"$(printf '%s' \"$status\" | jq -r --arg id \"$factory_root_id\" "
            "'[.deployments[] | select(.id == $id and .kind == \"factory\" and "
            ".state == \"ready\" and .pinned == true and .title == \"New OS\")] | length')\" = 1; "
            "sudo -n jq -e --arg id \"$factory_home_id\" "
            "'.id == $id and .kind == \"factory\" and .state == \"ready\" and "
            ".pinned == true and (.title == \"New OS\" or .title == \"New OS Home\")' "
            "\"$store/personal/metadata/$factory_home_id.json\" >/dev/null; "
            "sudo -n test -d \"$store/deployments/$factory_root_id/root\"; "
            "sudo -n test -d \"$store/personal/snapshots/$factory_home_id/home\"; "
            "subvolumes=$(sudo -n btrfs subvolume list /); "
            "! printf '%s\\n' \"$subvolumes\" | "
            "grep -Eq '@(root|home)\\.snapshots-manager-(old|new)-'; "
            "recovery_env=/boot/efi/EFI/anduinos/btrfs-snapshots-manager-grubenv; "
            "test -s \"$recovery_env\"; "
            "test -z \"$(sudo -n grub-editenv \"$recovery_env\" list)\"; "
            + confirmation
            + f"printf 'root-sentinel={'present' if root_present else 'absent'}\\n"
            f"home-sentinel={'present' if home_present else 'absent'}\\n"
            f"home-history={'present' if personal_history_present else 'absent'}\\n"
            "factory-root=healthy\\nfactory-home=healthy\\n"
            "recovery-pending=absent\\nbtrfs-staging-roots=absent\\n"
            f"factory-transaction={transaction}\\nfactory-reset-health=ok\\n'"
        )

    def _ssh_password_eventually(
        self,
        vm: QemuVm,
        command: str,
        *,
        timeout: float,
    ) -> str:
        deadline = time.monotonic() + timeout
        last = ""
        while time.monotonic() < deadline:
            process = getattr(vm, "process", None)
            if process is not None and process.poll() is not None:
                raise TestFailure(
                    "QEMU exited while waiting for password SSH after factory reset"
                )
            try:
                return self._ssh_password(
                    vm,
                    command,
                    timeout=max(1.0, min(20.0, deadline - time.monotonic())),
                )
            except (TestFailure, subprocess.TimeoutExpired) as error:
                last = f"{type(error).__name__}: {error}"
                time.sleep(2)
        raise TestFailure(
            "Password SSH did not become healthy after factory reset: " + last[-4000:]
        )

    def _ssh_password(
        self,
        vm: QemuVm,
        command: str,
        *,
        timeout: float = 60,
    ) -> str:
        invocation = (
            "ssh",
            "-F",
            "/dev/null",
            "-p",
            str(vm.config.ssh_forward_port),
            "-o",
            "StrictHostKeyChecking=no",
            "-o",
            "UserKnownHostsFile=/dev/null",
            "-o",
            "PreferredAuthentications=password",
            "-o",
            "PubkeyAuthentication=no",
            "-o",
            "NumberOfPasswordPrompts=1",
            "-o",
            "ConnectTimeout=10",
            "-o",
            "ConnectionAttempts=1",
            f"{self.username}@127.0.0.1",
            command,
        )
        with tempfile.TemporaryDirectory(prefix="anduinos-factory-askpass-") as directory:
            askpass = Path(directory) / "askpass"
            askpass.write_text(
                "#!/bin/sh\nprintf '%s\\n' \"$ANDUINOS_ACCEPTANCE_SSH_PASSWORD\"\n",
                encoding="utf-8",
            )
            askpass.chmod(0o700)
            environment = os.environ.copy()
            environment.update(
                {
                    "DISPLAY": environment.get("DISPLAY") or ":0",
                    "SSH_ASKPASS": str(askpass),
                    "SSH_ASKPASS_REQUIRE": "force",
                    "ANDUINOS_ACCEPTANCE_SSH_PASSWORD": self.password,
                }
            )
            result = subprocess.run(
                invocation,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                check=False,
                timeout=timeout,
                env=environment,
            )
        if result.returncode != 0:
            raise TestFailure(
                f"Factory-reset password SSH failed with {result.returncode}:\n"
                + result.stdout[-8000:]
            )
        return result.stdout

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
            "cat > /usr/local/sbin/anduinos-acceptance-rescue-state <<'EOF'\n"
            "#!/bin/bash\n"
            "set -euo pipefail\n"
            "test \"$#\" -eq 1\n"
            "expected_target=$1\n"
            "[[ \"$expected_target\" =~ ^[0-9a-f]{8}-[0-9a-f]{4}-"
            "[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$ ]]\n"
            "store=/.snapshots/anduinos-btrfs-snapshots-manager\n"
            "test \"$(jq -r .current_head_id \"$store/history/system-lineage.json\")\" "
            "= \"$expected_target\"\n"
            "test ! -e \"$store/offline-transactions/pending.json\"\n"
            "jq -r .phase \"$store/offline-transactions/history/\"*.json "
            "| grep -q '^completed$'\n"
            "jq -r 'select(.kind == \"pre-rollback\" and .state == \"ready\") "
            "| .id' \"$store/metadata/\"*.json | grep -q .\n"
            "! btrfs subvolume list / | "
            "grep -Eq '@root[.]rescue-center-(old|new)-'\n"
            "printf 'rescue-state=healthy\\n'\n"
            "EOF\n"
            "chmod 0755 /usr/local/sbin/anduinos-acceptance-reboot "
            "/usr/local/sbin/anduinos-acceptance-poweroff "
            "/usr/local/sbin/anduinos-acceptance-package-health "
            "/usr/local/sbin/anduinos-acceptance-boot-health "
            "/usr/local/sbin/anduinos-acceptance-rollback-state "
            "/usr/local/sbin/anduinos-acceptance-rescue-state\n"
            f"printf '%s ALL=(root) NOPASSWD: "
            f"/usr/local/sbin/anduinos-acceptance-reboot, "
            f"/usr/local/sbin/anduinos-acceptance-poweroff, "
            f"/usr/local/sbin/anduinos-acceptance-package-health, "
            f"/usr/local/sbin/anduinos-acceptance-boot-health, "
            f"/usr/local/sbin/anduinos-acceptance-rollback-state, "
            f"/usr/local/sbin/anduinos-acceptance-rescue-state\\n' "
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
            # A restored graphical session can saturate the disposable VM.
            # Allow SSH key exchange and PAM more time than a TCP connect;
            # the overall deadline still bounds a genuinely broken boot.
            attempt_timeout = max(1.0, min(30.0, remaining))
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
            "IdentitiesOnly=yes",
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
