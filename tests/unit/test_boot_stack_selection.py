"""The ISO boot-stack policy is architectural, not tied to a release name."""

from pathlib import Path
import subprocess
import unittest
from unittest.mock import patch

from assertions import install
from assertions.guest.ui.secure_boot import requires_own_bootloader
from framework.model import Architecture


class BootStackSelectionTests(unittest.TestCase):
    def test_rootfs_selects_own_stack_for_every_amd64_release(self):
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
                        self.assertEqual(package in result.stdout.splitlines(), arch == "amd64")

    def test_installed_package_assertion_has_no_release_fallback(self):
        for arch in (Architecture.AMD64, Architecture.ARM64):
            with self.subTest(architecture=arch), patch.object(install, "_record") as record:
                install._assert_boot_packages(None, arch, Path("unused"))
                script = record.call_args.args[1]
                self.assertNotIn("VERSION_CODENAME", script)
                self.assertEqual("boot_packages='anduinos-grub anduinos-shim-signed'" in script,
                                 arch is Architecture.AMD64)

    def test_first_boot_ui_requires_own_stack_without_reading_release(self):
        for arch in ("x86_64", "aarch64"):
            with (self.subTest(architecture=arch), patch("platform.machine", return_value=arch),
                  patch.object(Path, "read_text", side_effect=AssertionError("No release gate"))):
                self.assertEqual(requires_own_bootloader(), arch == "x86_64")
