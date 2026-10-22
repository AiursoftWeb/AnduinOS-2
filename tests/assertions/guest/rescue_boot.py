#!/usr/bin/python3
"""Fault injection and independent readback for disposable boot-rescue guests."""

import argparse
from contextlib import contextmanager
import hashlib
import json
from pathlib import Path
import re
import struct
import subprocess
import tempfile


def run(*args):
    try:
        return subprocess.check_output(args, text=True, stderr=subprocess.STDOUT).strip()
    except subprocess.CalledProcessError as error:
        print(error.output, flush=True)
        raise


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def efi_files(esp):
    return {str(p.relative_to(esp)): digest(p) for p in sorted(esp.rglob('*'))
            if p.is_file() and not p.name.lower().endswith('grubenv')}


def certificate(root):
    current = root / 'var/lib/anduinos-secureboot/current.json'
    if current.exists():
        identifier = json.loads(current.read_text())['identity']
        assert re.fullmatch('[0-9a-f]{32}', identifier), 'Invalid identity pointer'
        return root / 'var/lib/anduinos-secureboot/identities' / identifier / 'MOK.der'
    return root / 'var/lib/shim-signed/mok/MOK.der'


def verify_image(image, cert, machine):
    data = image.read_bytes()
    assert data[:2] == b'MZ'
    pe = struct.unpack_from('<I', data, 0x3c)[0]
    assert data[pe:pe + 4] == b'PE\0\0'
    assert struct.unpack_from('<H', data, pe + 4)[0] == machine
    with tempfile.TemporaryDirectory() as temporary:
        pem = str(Path(temporary) / 'certificate.pem')
        run('openssl', 'x509', '-inform', 'DER', '-in', str(cert), '-out', pem)
        print(run('sbverify', '--cert', pem, str(image)), flush=True)


def corrupt_text(path):
    data = bytearray(path.read_bytes())
    pe = struct.unpack_from('<I', data, 0x3c)[0]
    count = struct.unpack_from('<H', data, pe + 6)[0]
    optional = struct.unpack_from('<H', data, pe + 20)[0]
    for index in range(count):
        section = pe + 24 + optional + index * 40
        if data[section:section + 8].rstrip(b'\0') == b'.text':
            size, offset = struct.unpack_from('<II', data, section + 16)
            assert size > 128 and offset + size <= len(data)
            data[offset + 128] ^= 1
            path.write_bytes(data)
            return
    raise ValueError('GRUB has no executable .text section')


def assert_vendor_boot(state):
    assert run('mokutil', '--sb-state') == 'SecureBoot enabled'
    entries = run('efibootmgr', '-v')
    current = re.search(r'^BootCurrent: ([0-9A-Fa-f]{4})$', entries, re.M)
    assert current, entries
    entry = re.search(r'^Boot' + current[1] + r'\*?\s+(.+)$', entries, re.M)
    assert entry, entries
    assert ('\\efi\\anduinos\\shim' + state['suffix'] + '.efi') in entry[1].lower(), entries
    assert state['esp_partuuid'].lower() in entry[1].lower(), entries
    print(entries)


def inject(mode, record):
    assert run('systemd-detect-virt') in {'kvm', 'qemu'}
    assert run('lsblk', '-ndo', 'SERIAL', '/dev/vda') == 'ANDUINOS-TEST-TARGET'
    assert run('findmnt', '-n', '-o', 'FSROOT', '/') == '/@root'
    arch = run('dpkg', '--print-architecture')
    suffix, platform, machine = {'amd64': ('x64', 'x86_64-efi', 0x8664),
                                 'arm64': ('aa64', 'arm64-efi', 0xaa64)}[arch]
    root, esp = Path('/'), Path('/boot/efi')
    cert = certificate(root)
    source = Path(f'/usr/lib/anduinos-grub/grub{suffix}.efi')
    compat = Path(f'/usr/lib/grub/{platform}-signed/grub{suffix}.efi.signed')
    vendor = esp / f'EFI/AnduinOS/grub{suffix}.efi'
    verify_image(vendor, cert, machine)
    verify_image(compat, cert, machine)
    run('mokutil', '--test-key', str(cert))
    state = dict(mode=mode, suffix=suffix, machine=machine,
                 root_uuid=run('findmnt', '-n', '-o', 'UUID', '/'),
                 esp_uuid=run('findmnt', '-n', '-o', 'UUID', '/boot/efi'),
                 esp_partuuid=run('findmnt', '-n', '-o', 'PARTUUID', '/boot/efi'),
                 source=str(source), compat=str(compat), source_hash=digest(source),
                 certificate=str(cert), certificate_hash=digest(cert),
                 enrolled=run('mokutil', '--list-enrolled'), files=efi_files(esp))
    assert_vendor_boot(state)
    assert any(name.lower().startswith('efi/boot/') for name in state['files'])
    if mode == 'cache':
        corrupt_text(compat)
        # Signature table survives, but executable contents must fail authentication.
        run('sbverify', '--list', str(compat))
        try:
            verify_image(compat, cert, machine)
        except subprocess.CalledProcessError:
            pass
        else:
            raise AssertionError('Fault did not break cryptographic verification')
        vendor.unlink()
    else:
        corrupt_text(source)
        assert digest(source) != state['source_hash']
    record.write_text(json.dumps(state, indent=2) + '\n')
    run('sync')
    print(json.dumps(state, indent=2))


@contextmanager
def offline_mount(uuid, *, root=False):
    assert re.fullmatch('[A-Za-z0-9-]+', uuid), uuid
    with tempfile.TemporaryDirectory(prefix='rescue-readback-') as directory:
        run('mount', '-o', 'ro,subvol=@root' if root else 'ro',
            '/dev/disk/by-uuid/' + uuid, directory)
        try:
            yield Path(directory)
        finally:
            run('umount', directory)


def verify(state, root, esp):
    cert = root / state['certificate'].lstrip('/')
    assert digest(cert) == state['certificate_hash'], 'Rescue changed the identity'
    assert run('mokutil', '--list-enrolled') == state['enrolled'], 'MOK changed'
    run('mokutil', '--test-key', str(cert))
    files = efi_files(esp)
    if state['mode'] == 'source':
        assert files == state['files'], 'Rejected repair changed EFI files'
        assert digest(root / state['source'].lstrip('/')) != state['source_hash']
    else:
        before = {n: h for n, h in state['files'].items()
                  if not n.lower().startswith('efi/anduinos/')}
        after = {n: h for n, h in files.items()
                 if not n.lower().startswith('efi/anduinos/')}
        assert before == after, 'Rescue changed fallback or another EFI vendor'
        assert digest(root / state['source'].lstrip('/')) == state['source_hash']
        verify_image(root / state['compat'].lstrip('/'), cert, state['machine'])
        for name, value in state['files'].items():
            if name.lower().endswith(('shim' + state['suffix'] + '.efi',
                                      'mm' + state['suffix'] + '.efi')):
                assert files.get(name) == value, 'Rescue changed trusted shim/MokManager'
        cfg = esp / 'EFI/AnduinOS/grub.cfg'
        assert state['root_uuid'] in cfg.read_text(), 'Wrong root in EFI config'
        run('grub-script-check', str(root / 'boot/grub/grub.cfg'))
        assert 'menuentry ' in (root / 'boot/grub/grub.cfg').read_text()
    verify_image(esp / f"EFI/AnduinOS/grub{state['suffix']}.efi", cert, state['machine'])
    print(json.dumps({'verified': state['mode'], 'files': files}, indent=2))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('phase', choices=('cache', 'source', 'live', 'boot'))
    parser.add_argument('record', type=Path)
    args = parser.parse_args()
    if args.phase in {'cache', 'source'}:
        inject(args.phase, args.record)
        return
    state = json.loads(args.record.read_text())
    if args.phase == 'live':
        assert Path('/run/anduinos-live/environment').exists()
        with offline_mount(state['root_uuid'], root=True) as root:
            with offline_mount(state['esp_uuid']) as esp:
                verify(state, root, esp)
    else:
        assert not Path('/run/anduinos-live/environment').exists()
        assert_vendor_boot(state)
        verify(state, Path('/'), Path('/boot/efi'))
        status = json.loads(run('anduinos-securebootctl', 'status', '--json'))
        from ui.secure_boot import validate_status
        validate_status(status)
        print(json.dumps(status, indent=2))


if __name__ == '__main__':
    main()
