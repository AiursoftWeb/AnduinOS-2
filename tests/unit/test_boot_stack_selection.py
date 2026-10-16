"""The ISO boot-stack policy is architectural, not tied to a release name."""

from pathlib import Path
import subprocess
import shutil
import struct
import tempfile
import unittest
from unittest.mock import patch

from assertions import install
from assertions.guest.ui.secure_boot import requires_own_bootloader
from framework.model import Architecture
from framework.errors import ConfigurationError
from framework.iso import _validate_rootfs_boot_stack


class BootStackSelectionTests(unittest.TestCase):
    def test_rootfs_selects_own_stack_for_both_architectures(self):
        source = (Path(__file__).resolve().parents[2]
                  / "mods/05-live-kernel-apps-installer/install.sh").read_text()
        # Execute the actual first APT transaction with harmless shell stubs.
        source = source.split('judge "Install AnduinOS core system and kernel"', 1)[0]
        stubs = 'wait_network() { :; }; print_ok() { :; }; apt() { printf "%s\\n" "$@"; };\n'
        for arch in ("amd64", "arm64"):
            for release in ("resolute", "stonking", "future"):
                with self.subTest(architecture=arch, release=release):
                    script = f'TARGET_ARCH={arch}\nTARGET_UBUNTU_VERSION={release}\n' + stubs + source
                    result = subprocess.run(["bash", "-c", script], check=True,
                                            capture_output=True, text=True)
                    for package in ("anduinos-grub", "anduinos-shim-signed"):
                        self.assertIn(package, result.stdout.splitlines())

    def test_installed_package_assertion_has_no_release_fallback(self):
        for arch in (Architecture.AMD64, Architecture.ARM64):
            with self.subTest(architecture=arch), patch.object(install, "_record") as record:
                install._assert_boot_packages(None, arch, Path("unused"))
                script = record.call_args.args[1]
                self.assertNotIn("VERSION_CODENAME", script)
                self.assertIn("boot_packages='anduinos-grub anduinos-shim-signed'", script)

    def test_first_boot_ui_requires_own_stack_without_reading_release(self):
        for arch in ("x86_64", "aarch64"):
            with (self.subTest(architecture=arch), patch("platform.machine", return_value=arch),
                  patch.object(Path, "read_text", side_effect=AssertionError("No release gate"))):
                self.assertTrue(requires_own_bootloader())


@unittest.skipUnless(all(shutil.which(tool) for tool in
                        ('xorriso', 'mksquashfs', 'unsquashfs', 'sbverify', 'dpkg-query')),
                     'ISO inspection tools required')
class RootfsBootStackTests(unittest.TestCase):
    def test_delivered_iso_requires_native_packages_template_and_no_identity(self):
        for arch, suffix, machine in ((Architecture.AMD64, 'x64', 0x8664),
                                      (Architecture.ARM64, 'aa64', 0xAA64)):
            for fault in ('none', 'missing-package', 'wrong-package-arch', 'ubuntu-package',
                          'missing-template', 'wrong-pe', 'identity', 'signed-cache'):
                with self.subTest(architecture=arch, fault=fault), tempfile.TemporaryDirectory() as directory:
                    root = Path(directory)
                    source = root / 'source'
                    status = source / 'var/lib/dpkg/status'
                    status.parent.mkdir(parents=True)
                    packages = ['anduinos-grub', 'anduinos-shim-signed']
                    if fault == 'missing-package':
                        packages.pop()
                    if fault == 'ubuntu-package':
                        packages.append(f'grub-efi-{arch.value}-signed')
                    package_arch = ('arm64' if arch is Architecture.AMD64 else 'amd64') if fault == 'wrong-package-arch' else arch.value
                    status.write_text(''.join(
                        f'Package: {name}\nStatus: install ok installed\nArchitecture: {package_arch}\n'
                        'Version: 1\nMaintainer: Test <test@example.com>\nDescription: fixture\n\n'
                        for name in packages))
                    template = source / f'usr/lib/anduinos-grub/grub{suffix}.efi'
                    template.parent.mkdir(parents=True)
                    # Minimal non-executable PE32+ fixture accepted by sbverify.
                    image = bytearray(1024)
                    image[:2] = b'MZ'
                    struct.pack_into('<I', image, 60, 128)
                    image[128:132] = b'PE\0\0'
                    struct.pack_into('<HHIIIHH', image, 132, 0 if fault == 'wrong-pe' else machine,
                                     1, 0, 0, 0, 240, 0x22)
                    optional = 152
                    struct.pack_into('<H', image, optional, 0x20B)
                    struct.pack_into('<I', image, optional + 4, 512)
                    struct.pack_into('<II', image, optional + 16, 4096, 4096)
                    struct.pack_into('<II', image, optional + 32, 4096, 512)
                    struct.pack_into('<II', image, optional + 56, 8192, 512)
                    struct.pack_into('<H', image, optional + 68, 10)
                    struct.pack_into('<I', image, optional + 108, 16)
                    section = optional + 240
                    image[section:section + 8] = b'.text\0\0\0'
                    struct.pack_into('<IIII', image, section + 8, 8, 4096, 512, 512)
                    struct.pack_into('<I', image, section + 36, 0x60000020)
                    if fault != 'missing-template':
                        template.write_bytes(image)
                    if fault in ('identity', 'signed-cache'):
                        stored = source / ('var/lib/shim-signed/mok/MOK.priv' if fault == 'identity'
                                           else f'var/lib/anduinos-grub/grub{suffix}.efi')
                        stored.parent.mkdir(parents=True)
                        stored.write_text('fixture, not a real identity')
                    live = root / 'image/LiveOS'
                    live.mkdir(parents=True)
                    subprocess.run(['mksquashfs', str(source), str(live / 'rootfs.squashfs'),
                                    '-noappend', '-processors', '1'], check=True, capture_output=True)
                    iso = root / 'fixture.iso'
                    subprocess.run(['xorriso', '-as', 'mkisofs', '-quiet', '-o', str(iso), str(live.parent)],
                                   check=True, capture_output=True)
                    if fault == 'none':
                        _validate_rootfs_boot_stack(iso, arch)
                    else:
                        with self.assertRaises(ConfigurationError):
                            _validate_rootfs_boot_stack(iso, arch)
