"""Release contracts for packages forbidden in Live and installed images."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from iso_test.assertions import (
    FORBIDDEN_IMAGE_PACKAGES,
    assert_no_image_junk,
    is_forbidden_image_package,
)
from iso_test.model import TestMatrix
from iso_test.runner import scenario_check_ids
from iso_test.serial import CommandResult


ROOT = Path(__file__).parent


class _CaptureConsole:
    def __init__(self):
        self.scripts: list[str] = []

    def run(self, script: str, **_options) -> CommandResult:
        self.scripts.append(script)
        return CommandResult("", 0)


class ImagePackagePolicyTests(unittest.TestCase):
    def test_every_complete_installation_checks_live_and_target_packages(self):
        matrix = TestMatrix.load(ROOT / "matrix.json")
        for scenario in matrix.scenarios:
            with self.subTest(scenario=scenario.id):
                checks = scenario_check_ids(scenario)
                self.assertIn("packages.live-image-junk-absent", checks)
                self.assertIn("packages.installed-junk-absent", checks)
                self.assertLess(
                    checks.index("live-boot"),
                    checks.index("packages.live-image-junk-absent"),
                )
                self.assertLess(
                    checks.index("installed-boot"),
                    checks.index("packages.installed-junk-absent"),
                )

    def test_policy_subsumes_the_deleted_build_cleanup_mod(self):
        exact_legacy_packages = {
            "ubuntu-desktop",
            "ubuntu-desktop-minimal",
            "snapd",
            "snap",
            "snap-store",
            "ubuntu-session",
            "yaru-theme-gnome-shell",
            "yaru-theme-unity",
            "yaru-theme-icon",
            "yaru-theme-gtk",
            "ubuntu-wallpapers",
            "ubuntu-wallpaper",
            "ubuntu-pro-client",
            "ubuntu-advantage-desktop-daemon",
            "ubuntu-advantage-tools",
            "ubuntu-pro-client-l10n",
            "ubuntu-release-upgrader-core",
            "ubuntu-release-upgrader-gtk",
            "update-notifier",
            "update-notifier-common",
            "update-manager",
            "update-manager-core",
            "apport",
            "popularity-contest",
            "ubuntu-report",
            "whoopsie",
            "gnome-shell-ubuntu-extensions",
            "gnome-shell-extension-ubuntu-dock",
            "gnome-shell-extension-appindicator",
            "gnome-shell-extension-dash-to-panel",
            "gnome-shell-extension-desktop-icons-ng",
            "gnome-shell-extension-gtk4-desktop-icons-ng",
            "ubiquity",
            "ubiquity-casper",
            "ubiquity-frontend-gtk",
            "ubiquity-ubuntu-artwork",
            "ubiquity-slideshow-ubuntu",
            "anduinos-installer-config",
            "anduinos-bwrap-hack",
            "firefox",
            "software-properties-common",
            "software-properties-gtk",
            "firmware-sof-signed",
            "alsa-ucm-conf",
            "plymouth-theme-spinner",
            "alacritty",
            "gnome-terminal",
            "tilix",
            "zutty",
            "xterm",
            "gnome-mahjongg",
            "gnome-mines",
            "gnome-sudoku",
            "aisleriot",
            "hitori",
            "gnome-initial-setup",
            "gnome-photos",
            "eog",
            "gnome-contacts",
            "gdb",
            "build-essential",
        }
        self.assertLessEqual(exact_legacy_packages, set(FORBIDDEN_IMAGE_PACKAGES))
        self.assertTrue(is_forbidden_image_package("libreoffice-writer"))

    def test_policy_rejects_the_accidental_dkms_build_environment(self):
        forbidden = {
            "dkms",
            "gcc",
            "gcc-15",
            "gcc-x86-64-linux-gnu",
            "gcc-15-x86-64-linux-gnu",
            "gcc-15-aarch64-linux-gnu",
            "g++",
            "g++-15-aarch64-linux-gnu",
            "cpp-15",
            "make",
            "make-guile",
            "dpkg-dev",
            "build-essential",
            "fakeroot",
            "libfakeroot",
            "binutils",
            "binutils-aarch64-linux-gnu",
            "libgcc-15-dev",
            "libstdc++-15-dev",
            "libasan8",
            "libtsan2",
            "libubsan1",
            "liblsan0",
            "libhwasan0",
            "libitm1",
            "libquadmath0",
        }
        for package in forbidden:
            with self.subTest(package=package):
                self.assertTrue(is_forbidden_image_package(package))

    def test_policy_keeps_runtime_and_hwe_kernel_packages_legal(self):
        allowed = {
            "gcc-15-base",
            "gcc-16-base",
            "libgcc-s1",
            "libstdc++6",
            "binutils-common",
            "linux-generic-hwe-26.04",
            "linux-headers-generic-hwe-26.04",
            "linux-headers-7.0.0-30",
            "linux-headers-7.0.0-30-generic",
        }
        for package in allowed:
            with self.subTest(package=package):
                self.assertFalse(is_forbidden_image_package(package))

    def test_live_and_installed_checks_use_the_same_dpkg_policy(self):
        with tempfile.TemporaryDirectory() as directory:
            evidence = Path(directory)
            scripts = {}
            for scope in ("live", "installed"):
                console = _CaptureConsole()
                assert_no_image_junk(console, evidence, scope)
                self.assertEqual(1, len(console.scripts))
                scripts[scope] = console.scripts[0]
                identifier = (
                    "packages-live-image-junk-absent"
                    if scope == "live"
                    else "packages-installed-junk-absent"
                )
                self.assertTrue((evidence / f"{identifier}.txt").is_file())

        for script in scripts.values():
            self.assertIn("dpkg-query -W", script)
            self.assertIn("Forbidden packages remain", script)
            self.assertIn("dkms", script)
            self.assertIn("fakeroot", script)
            self.assertIn("gcc", script)
            self.assertIn("make", script)
            self.assertIn(r"dpkg\-dev", script)
            self.assertNotIn(r"dpkg\\-dev", script)

    def test_invalid_package_assertion_scope_fails_closed(self):
        with tempfile.TemporaryDirectory() as directory, self.assertRaisesRegex(
            ValueError,
            "Unknown package-junk assertion scope",
        ):
            assert_no_image_junk(
                _CaptureConsole(),
                Path(directory),
                "host",
            )

    def test_process_cleanup_mod_is_gone(self):
        self.assertFalse((ROOT.parent / "mods/78-ensure-no-junk").exists())


if __name__ == "__main__":
    unittest.main()
