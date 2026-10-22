"""Voice Typing acceptance on an installed-system disposable overlay."""

from .context import *  # noqa: F403


class VoiceChecks:
    def _exercise_voice_typing(self, vm: QemuVm, base: PromotedBase, artifacts: Path) -> None:
        assert vm.serial is not None
        remote = '/run/anduinos-feature-voice'
        vm.serial.run(f'install -d -m 0777 {remote}/evidence')
        self.driver.upload(vm.serial, remote)

        def drive(mode: str, phase: str = '') -> None:
            result = _run_with_qmp_key_requests(
                vm,
                _desktop_command(self.username, ('python3', f'{remote}/atspi_driver.py',
                    mode, '--evidence', f'{remote}/evidence', '--expected', phase)),
                timeout=1000 if mode == 'voice-install' else 300,
                secret_texts={'voice-install-password': self.password},
                request_trace=artifacts / f'{mode}-{phase}-qmp.jsonl',
            )
            (artifacts / f'{mode}-{phase}-events.jsonl').write_text(result.stdout + '\n')
            _retrieve_tree(vm.serial, remote, artifacts / f'{mode}-{phase}-guest')
            if result.returncode:
                raise TestFailure(f'{mode} {phase} failed:\n{result.stdout[-8000:]}')
            expected_event = 'voice-install' if mode == 'voice-install' else 'voice-activation'
            events = []
            for line in result.stdout.splitlines():
                try:
                    events.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
            if not any(e.get('event') == expected_event and e.get('status') == 'passed'
                       and (not phase or e.get('phase') == phase) for e in events):
                raise TestFailure(f'Missing completion evidence for {mode} {phase}')
            vm.screenshot(f'voice-{phase or "installed"}')

        def relogin() -> None:
            self._logout_graphical_user(vm, self.username)
            _login_gdm(vm, self.username, self.password, timeout=120)
            if _graphical_user(vm.serial) != self.username:
                raise TestFailure('Voice test logged into the wrong account')
            self._wait_for_gdm_greeter_exit(vm)

        drive('voice-install')
        relogin()
        drive('voice-activation', 'first')
        drive('voice-activation', 'repeat')
        # Ordinary language changes must not invalidate the expensive selection.
        vm.serial.run(_desktop_command(self.username, ('gsettings', 'set',
            'com.anduinos.voice-typing', 'language', 'en')))
        relogin()
        drive('voice-activation', 'relogin')
