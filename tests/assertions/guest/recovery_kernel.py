"""Guest-side fault injection and independent recovery oracle, disposable VM only."""
import hashlib
import json
import re
from pathlib import Path
import subprocess
import sys
import time

STORE = Path('/.snapshots/anduinos-btrfs-snapshots-manager')
STATE = Path('/var/lib/anduinos-recovery-acceptance.json')
DAMAGE = Path('/etc/anduinos-recovery-acceptance-damaged')
HOME = Path('/home/anduinos-recovery-acceptance-preserved')


def output(*args):
    return subprocess.check_output(args, text=True).strip()


def digest(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def snapshot(title):
    value = json.loads(output('anduinos-btrfs-snapshots-manager-cli', 'create', '--json', title, 'Recovery environment acceptance'))
    identifier = value.get('id') or value.get('deployment_id')
    assert identifier and (STORE / 'deployments' / identifier / 'root').is_dir(), value
    return identifier


def marker(identifier):
    value = json.loads((STORE / 'last-successful-boot.json').read_text())
    assert value['snapshot_id'] == identifier, value
    assert value['boot_id'] == Path('/proc/sys/kernel/random/boot_id').read_text().strip(), value
    return value


mode = sys.argv[1]
if mode == 'baseline':
    assert output('findmnt', '-n', '-o', 'FSROOT', '/') == '/@root'
    assert output('findmnt', '-n', '-o', 'FSTYPE', '/') == 'btrfs'
    assert Path('/var/lib/anduinos-recovery-env/volume.json').is_file()
    files = sorted(set(Path('/boot').glob('vmlinuz-*')) | set(Path('/boot').glob('initrd.img-*')))
    assert len(files) >= 2
    STATE.write_text(json.dumps({str(path): digest(path) for path in files}))
    # Firmware Settings is a top-level UEFI item nested in an `if` in the
    # generated script, unlike the kernel entries inside Advanced options.
    entries = re.findall(r"^(?:(?:menuentry|submenu) |[ \t]+menuentry 'UEFI Firmware Settings').+$",
                         Path('/boot/grub/grub.cfg').read_text(), re.MULTILINE)
    recovery = [i for i, entry in enumerate(entries) if '--id anduinos-recovery-env' in entry]
    assert len(recovery) == 1, entries
    print(json.dumps({'snapshot_a': snapshot('Acceptance A - bootable'), 'recovery_menu_index': recovery[0]}))
elif mode == 'marker':
    deadline = time.monotonic() + 90
    while True:
        try:
            print(json.dumps(marker(sys.argv[2])))
            break
        except (AssertionError, FileNotFoundError):
            if time.monotonic() > deadline:
                raise
            time.sleep(1)
elif mode == 'damage':
    before = marker(sys.argv[2])
    files = json.loads(STATE.read_text())
    # systemd tmpfiles can create these empty child subvolumes on a healthy
    # system. Keep them in the broken root so the independent recovery image
    # must list snapshots, restore A and clean up the old root with this layout.
    # Never hide unexpected data by replacing a nonempty directory/subvolume.
    children = ['/var/lib/machines', '/var/lib/portables']
    for name in children:
        path = Path(name)
        if path.exists():
            assert path.is_dir() and not path.is_symlink(), name
            assert not any(path.iterdir()), name
            existing = subprocess.run(['btrfs', 'subvolume', 'show', name],
                                      stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            if existing.returncode == 0:
                continue
            path.rmdir()
        path.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run(['btrfs', 'subvolume', 'create', name],
                       check=True, stdout=subprocess.DEVNULL)
    DAMAGE.write_text('Must disappear after recovery A\n')
    HOME.write_text('Personal data survives recovery\n')
    # Corrupt every installed kernel and initrd, including older alternatives.
    # The dedicated recovery volume and immutable snapshots remain untouched.
    for name in files:
        Path(name).write_bytes(b'Not a bootable kernel or initrd\n')
    time.sleep(1)
    identifier = snapshot('Acceptance B - broken kernel')
    assert marker(sys.argv[2]) == before
    subprocess.run(['sync'], check=True)
    print(json.dumps({'snapshot_b': identifier, 'marker': before, 'damaged_files': list(files),
                      'empty_system_subvolumes': children}))
elif mode == 'verify':
    files = json.loads(STATE.read_text())
    assert not DAMAGE.exists()
    assert HOME.read_text() == 'Personal data survives recovery\n'
    for name, expected in files.items():
        assert digest(Path(name)) == expected, name
        assert digest(STORE / 'deployments' / sys.argv[2] / 'root' / name.lstrip('/')) == expected
        assert digest(STORE / 'deployments' / sys.argv[3] / 'root' / name.lstrip('/')) != expected
    assert output('findmnt', '-n', '-o', 'FSROOT', '/') == '/@root'
    assert not (STORE / 'offline-transactions/pending.json').exists()
    print(json.dumps({'restored': sys.argv[2], 'broken_snapshot_retained': sys.argv[3], 'kernels_and_initrds': files, 'boot_id': Path('/proc/sys/kernel/random/boot_id').read_text().strip()}))
else:
    raise ValueError(mode)
