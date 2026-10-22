"""Installed voice integration: real package UI, Shell shortcut and native daemon."""

from .core import *  # noqa: F403
from .core import _request_secret_delivery
from gi.repository import GLib

BUS = 'com.anduinos.VoiceTyping'
OBJECT = '/com/anduinos/VoiceTyping'



def voice_diagnostics(evidence: Path, phase: str) -> None:
    shell = Gio.Settings.new('org.gnome.shell')
    data = {key: shell.get_value(key).unpack() for key in
            ('enabled-extensions', 'disabled-extensions', 'disable-user-extensions')}
    data['extension_info'] = subprocess.run(
        ['gnome-extensions', 'info', 'voice-typing@anduinos.com'],
        capture_output=True, text=True).stdout
    bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
    for label, destination, path, interface in (
        ('overlay', 'org.gnome.Shell', OBJECT + '/UI', BUS + '.UI'),
        ('daemon', BUS, OBJECT, BUS),
    ):
        try:
            data[label] = bus.call_sync(destination, path, interface, 'GetState',
                None, None, Gio.DBusCallFlags.NO_AUTO_START, 5000, None).unpack()
        except GLib.Error as error:
            data[label] = str(error)
    data['shortcut'] = Gio.Settings.new('com.anduinos.voice-typing').get_strv('toggle-shortcut')
    (evidence / f'{phase}-diagnostics.json').write_text(json.dumps(data, ensure_ascii=False, indent=2) + '\n')


def exercise_voice_install(evidence: Path) -> None:
    installed = subprocess.run(['dpkg-query', '-W', '-f=${db:Status-Status}',
                                'anduinos-whisper-gtk'], capture_output=True, text=True)
    if installed.stdout == 'installed':
        raise UiFailure('Voice installation must start with the optional package absent')
    # Match the existing Swap Control driver: launch in the graphical user's
    # manager so pkexec cannot select a text agent on the serial control TTY.
    environment = [
        f"--setenv={key}={value}"
        for key in ("HOME", "XDG_RUNTIME_DIR", "DBUS_SESSION_BUS_ADDRESS",
                    "WAYLAND_DISPLAY", "DISPLAY", "NO_AT_BRIDGE",
                    "XDG_CURRENT_DESKTOP", "XDG_SESSION_DESKTOP",
                    "DESKTOP_SESSION", "GDMSESSION")
        if (value := os.environ.get(key)) is not None
    ]
    unit = f"anduinos-acceptance-voice-install-{os.getpid()}"
    subprocess.run(['systemd-run', '--user', f'--unit={unit}', '--collect',
                    '--property=Type=exec', *environment, '--',
                    'anduinos-control-panel', '--topic', 'accessibility.voice-typing'],
                   check=True, capture_output=True, text=True)
    try:
        find_candidates(('Install Voice Typing', '安装语音输入'), label='voice install dialog', timeout=60)
        install = find_candidates(('Install', '安装'), label='install voice', require_enabled=True)
        if not perform_action(actionable(install), 0):
            raise UiFailure('Could not activate the installation button')
        find('polkit', timeout=30)
        _request_secret_delivery('password', 'voice-install-password', verify_character_count=False)
        event('qmp-key', request='voice-install-auth-submit', key='ret')
        wait_absent('polkit', timeout=30)
        find_candidates(('✓ Installed. Sign out and back in once, then press Super + H to start Voice Typing.',
                         '✓ 已安装。请注销并重新登录一次，然后按 Super + H 开始语音输入。'),
                        label='voice installation completed', timeout=900)
        result = subprocess.run(['dpkg-query', '-W', '-f=${Package} ${Version} ${db:Status-Status}\n',
                                 'anduinos-whisper-gtk', 'anduinos-whisper-framework',
                                 'anduinos-whisper-worker'], capture_output=True, text=True, check=True)
        (evidence / 'packages.txt').write_text(result.stdout)
        settings = Gio.Settings.new('org.gnome.shell')
        uuid = 'voice-typing@anduinos.com'
        if uuid not in settings.get_strv('enabled-extensions') or uuid in settings.get_strv('disabled-extensions'):
            raise UiFailure('Control Panel did not enable the installed extension')
        voice_diagnostics(evidence, 'installed')
        event('voice-install', status='passed', packages=result.stdout)
    finally:
        output = subprocess.run(['journalctl', '--user', '-u', unit, '--no-pager'],
                                capture_output=True, text=True)
        (evidence / 'control-panel.log').write_text(output.stdout + output.stderr)
        subprocess.run(['systemctl', '--user', 'stop', unit], check=False,
                       capture_output=True, text=True)



def wait_voice_overlay(phase: str) -> None:
    """GDM's Wayland socket can precede Shell extension/keybinding readiness."""
    bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
    started = time.monotonic()
    first_error = ''
    while time.monotonic() - started < 30:
        try:
            state = bus.call_sync('org.gnome.Shell', OBJECT + '/UI', BUS + '.UI',
                'GetState', None, None, Gio.DBusCallFlags.NO_AUTO_START, 1000, None).unpack()
            if state[0] in ('closed', 'ready'):
                event('voice-overlay-ready', phase=phase, state=state[0],
                      waited_ms=round((time.monotonic() - started) * 1000),
                      initial_error=first_error)
                return
        except GLib.Error as error:
            first_error = first_error or str(error)
        time.sleep(.2)
    raise UiFailure(f'Voice extension did not become ready after login: {first_error}')


def exercise_voice_activation(evidence: Path, phase: str) -> None:
    if phase not in ('first', 'repeat', 'relogin'):
        raise UiFailure('Unknown voice activation phase')
    cache = Path(GLib.get_user_cache_dir()) / 'anduinos-whisper/performance.json'
    first = phase == 'first'
    if cache.exists() == first:
        raise UiFailure(f'{phase}: unexpected pre-activation cache existence')
    before = None if first else cache.read_bytes()
    if not first and before != (evidence / 'first-performance.json').read_bytes():
        raise UiFailure(f'{phase}: cache changed between activations')
    wait_voice_overlay(phase)
    voice_diagnostics(evidence, phase + '-before')
    settings = Gio.Settings.new('com.anduinos.voice-typing')
    if settings.get_string('recognition-backend') != 'auto':
        raise UiFailure('Voice test requires the production automatic backend default')
    # A real PipeWire source replaces unavailable physical VM microphones only.
    # The production daemon, worker, models and benchmark remain unmodified.
    audio_log = (evidence / f'{phase}-audio.log').open('w')
    audio = subprocess.Popen(['pw-loopback',
        '--capture-props=media.class=Audio/Sink node.name=acceptance_voice_sink',
        '--playback-props=media.class=Audio/Source node.name=acceptance_voice_source'],
        stdout=audio_log, stderr=audio_log)
    old_microphone = settings.get_string('microphone')
    bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
    states = []
    def signal(_connection, sender, _path, _interface, _signal, parameters):
        state, detail = parameters.unpack()
        states.append(state)
        event('voice-state', phase=phase, sender=sender, state=state, detail=detail)
    subscription = bus.signal_subscribe(BUS, BUS, 'StateChanged', OBJECT, None,
                                       Gio.DBusSignalFlags.NONE, signal)
    def spin(predicate, seconds=120):
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            while GLib.MainContext.default().pending():
                GLib.MainContext.default().iteration(False)
            if audio.poll() is not None:
                raise UiFailure('PipeWire microphone fixture exited')
            if 'error' in states:
                raise UiFailure(f'Voice daemon reported an error: {states}')
            if predicate():
                return
            time.sleep(.05)
        raise UiFailure(f'{phase}: timed out; states={states}')
    try:
        # Wait for the real graph node before selecting it as the microphone.
        def microphone_ready():
            nodes = json.loads(subprocess.check_output(['pw-dump'], text=True))
            return any(n.get('info', {}).get('props', {}).get('node.name') ==
                       'acceptance_voice_source' for n in nodes)
        spin(microphone_ready, 20)
        settings.set_string('microphone', 'acceptance_voice_source')
        Gio.Settings.sync()
        bus.flush_sync(None)  # Install the signal match before the keyboard gesture.
        event('qmp-key', request=f'voice-{phase}-start', key='meta_l-h')
        spin(lambda: 'listening' in states)
        # Check the Shell overlay independently of the daemon observation.
        ui = bus.call_sync('org.gnome.Shell', OBJECT + '/UI', BUS + '.UI',
                           'GetState', None, None, Gio.DBusCallFlags.NONE, 5000, None).unpack()
        if ui[0] != 'listening':
            raise UiFailure(f'Super+H did not show the listening overlay: {ui}')
        settle = time.monotonic() + 2
        spin(lambda: time.monotonic() >= settle, 5)
        record = json.loads(cache.read_text())
        selected = record.get('selected', {})
        if selected.get('backend') not in ('cpu', 'gpu') or not isinstance(selected.get('threads'), int) or selected['threads'] < 1:
            raise UiFailure(f'Invalid persisted selection: {selected}')
        if ('calibrating' in states) != first:
            raise UiFailure(f'{phase}: incorrect calibration behavior: {states}')
        if not first and cache.read_bytes() != before:
            raise UiFailure(f'{phase}: cached selection was rewritten')
        (evidence / f'{phase}-performance.json').write_bytes(cache.read_bytes())
        event('qmp-key', request=f'voice-{phase}-stop', key='meta_l-h')
        spin(lambda: any(state in ('idle', 'ready') for state in states[states.index('listening') + 1:]))
        event('voice-activation', phase=phase, status='passed', states=states,
              cache=str(cache), sha256=hashlib.sha256(cache.read_bytes()).hexdigest(), overlay=ui)
    finally:
        voice_diagnostics(evidence, phase + '-after')
        bus.signal_unsubscribe(subscription)
        settings.set_string('microphone', old_microphone)
        Gio.Settings.sync()
        audio.terminate()
        audio.wait(timeout=15)
        audio_log.close()
