"""Recover an unbootable kernel through the installed recovery GUI, without ISO."""
from .context import *  # noqa: F403
from framework.grub import _GraphicalGrubMenuEditor


class RecoveryChecks:
    def _exercise_recovery_kernel_rollback(self, vm, base, artifacts):
        remote = '/usr/local/lib/anduinos-recovery-acceptance'
        helper = remote + '/recovery_kernel.py'
        vm.serial.run(f'install -d -m 0755 {remote}')
        key = self._prepare_power_control(vm, artifacts, remote)
        vm.serial.upload(self.framework_root / 'assertions/guest/recovery_kernel.py', helper, 0o644)
        vm.serial.run(
            f"printf '%s ALL=(root) NOPASSWD: /usr/bin/python3 {helper} *\\n' "
            f"{shlex.quote(self.username)} > /etc/sudoers.d/anduinos-recovery-acceptance; "
            'chmod 0440 /etc/sudoers.d/anduinos-recovery-acceptance; '
            'visudo -cf /etc/sudoers.d/anduinos-recovery-acceptance'
        )
        def oracle(mode, *args):
            result = self._ssh(vm, key, f'sudo -n /usr/bin/python3 {helper} ' +
                               ' '.join(shlex.quote(value) for value in (mode, *args)), timeout=180)
            value = json.loads(result.strip().splitlines()[-1])
            (artifacts / f'recovery-{mode}.json').write_text(json.dumps(value, indent=2) + '\n')
            return value

        def poweroff(label):
            self._ssh(vm, key, 'sudo -n /usr/local/sbin/anduinos-acceptance-poweroff')
            self._wait_for_power_transition(vm, key, artifacts, label, timeout=150)
            vm.stop()

        def normal_boot(label):
            vm.start(attach_iso=False, phase=label)
            self._ssh_eventually(vm, key, self._graphical_boot_ready_command(),
                                 timeout=self.options.boot_timeout_seconds)
            self._ssh_eventually(vm, key, "pgrep -x gnome-shell >/dev/null", timeout=120)

        baseline = oracle('baseline')
        a = baseline['snapshot_a']
        vm.screenshot('recovery-01-snapshot-a')
        poweroff('recovery-a-poweroff')
        normal_boot('recovery-a-successful-boot')
        oracle('marker', a)
        vm.screenshot('recovery-02-a-booted')
        b = oracle('damage', a)['snapshot_b']
        vm.screenshot('recovery-03-b-created')
        poweroff('recovery-b-poweroff')

        # Explicitly boot the normal product menu entry with the damaged files.
        vm.start(attach_iso=False, phase='recovery-broken-normal-boot')
        with vm.serial.capture_output():
            self._recovery_menu_entry(vm, 0, 'recovery-04-normal-entry')
        try:
            self._ssh_eventually(vm, key, 'true', timeout=45)
        except TestFailure as error:
            if not vm.running or not str(error).startswith('SSH control did not become healthy'):
                raise
            (artifacts / 'recovery-broken-boot.txt').write_text(str(error) + '\n')
        else:
            raise TestFailure('Corrupted kernels unexpectedly booted the installed system')
        vm.screenshot('recovery-05-kernel-boot-failed')
        vm.stop()

        vm.start(attach_iso=False, phase='recovery-independent-environment')
        with vm.serial.capture_output():
            self._recovery_menu_entry(vm, baseline['recovery_menu_index'], 'recovery-06-recovery-entry')
            # The only green text in this product page is the successful-boot
            # badge. Select its row, not the latest snapshot (B). A wrong badge
            # or wrong click must fail the independent kernel/hash oracle below.
            deadline = time.monotonic() + 120
            while time.monotonic() < deadline:
                frame = vm.screenshot('recovery-07-list')
                with Image.open(frame) as image:
                    image = image.convert('RGB')
                    green = [(x, y) for y in range(100, image.height - 60)
                             for x in range(image.width // 2, image.width - 50)
                             if image.getpixel((x, y)) == (146, 212, 167)]
                    if len(green) > 50:
                        y = sum(p[1] for p in green) // len(green)
                        orange = [x for x in range(image.width // 2, image.width)
                                  if image.getpixel((x, y)) == (233, 84, 32)]
                        if orange:
                            self._recovery_click(vm, (min(orange) + max(orange)) / 2 / image.width,
                                                 y / image.height)
                            break
                time.sleep(1)
            else:
                raise TestFailure('Recovery GUI did not show a usable last-successful-boot row')
            time.sleep(.5)
            vm.screenshot('recovery-08-confirm-a')
            # Confirmation initially focuses Cancel; Tab selects Roll Back.
            vm.qmp.send_key('tab')
            vm.qmp.send_key('ret')
            # Recovery completion has an orange Restart button in the footer
            # and no remaining list/confirmation actions above it.
            deadline = time.monotonic() + 180
            while time.monotonic() < deadline:
                frame = vm.screenshot('recovery-09-result')
                with Image.open(frame) as image:
                    image = image.convert('RGB')
                    upper = list(image.crop((0, 0, image.width, image.height * 3 // 4)).getdata())
                    lower = list(image.crop((0, image.height * 3 // 4, image.width, image.height)).getdata())
                    if upper.count((233, 84, 32)) < 10 and lower.count((233, 84, 32)) > 500:
                        break
                time.sleep(1)
            else:
                raise TestFailure('Recovery GUI did not reach its completion page')
            vm.qmp.send_key('ret')
            deadline = time.monotonic() + 60
            while vm.running and time.monotonic() < deadline:
                time.sleep(.2)
            if vm.running:
                raise TestFailure('Recovery Restart button did not reboot')
        vm.stop()
        normal_boot('recovery-restored-a')
        first = oracle('verify', a, b)
        (artifacts / 'recovery-verify-first-boot.json').write_text(json.dumps(first, indent=2))
        vm.screenshot('recovery-10-restored-desktop')
        poweroff('recovery-restored-poweroff')
        normal_boot('recovery-persistent-second-boot')
        second = oracle('verify', a, b)
        if first['boot_id'] == second['boot_id']:
            raise TestFailure('Recovery persistence check did not perform a second boot')
        vm.screenshot('recovery-11-second-boot')
        poweroff('recovery-final-poweroff')

    @staticmethod
    def _recovery_menu_entry(vm, index, label):
        editor = _GraphicalGrubMenuEditor(vm.qmp)
        try:
            editor.wait_for_top_menu(timeout=45)
            for _ in range(index):
                vm.qmp.send_key('down')
                time.sleep(.15)
            vm.screenshot(label)
            vm.qmp.send_key('ret')
        finally:
            editor.close()

    @staticmethod
    def _recovery_click(vm, x, y):
        vm.qmp.execute('input-send-event', {'device': 'video0', 'events': [
            {'type': 'abs', 'data': {'axis': 'x', 'value': round(x * 32767)}},
            {'type': 'abs', 'data': {'axis': 'y', 'value': round(y * 32767)}}]})
        for down in (True, False):
            vm.qmp.execute('input-send-event', {'device': 'video0', 'events': [
                {'type': 'btn', 'data': {'button': 'left', 'down': down}}]})
            time.sleep(.15)
