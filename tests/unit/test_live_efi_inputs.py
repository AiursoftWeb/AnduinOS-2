"""Official Live loaders are downloaded, never installed into the rootfs."""

import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[2]
TOOLS = ROOT / "build-tools"
LOADERS = {
    "amd64": ("BOOTX64.EFI", "grubx64.efi", "mmx64.efi"),
    "arm64": ("BOOTAA64.EFI", "grubaa64.efi", "mmaa64.efi", "BOOTAA64.CSV"),
}


class LiveEfiInputsTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.work = Path(temporary.name)
        self.target = self.work / "target"
        (self.target / "tmp").mkdir(parents=True)
        self.output = self.work / "loaders"
        self.bin = self.work / "bin"
        self.bin.mkdir()
        self.env = dict(os.environ, PATH=f"{self.bin}:{os.environ['PATH']}",
                        TEST_WORK=str(self.work))
        # Keep the actual inner shell and APT arguments, replacing only root
        # isolation and the network package source. No sudo/root is needed.
        self.executable("sudo", '''#!/usr/bin/python3
import os, subprocess, sys
assert sys.argv[1:3] == ["--preserve-env=HOME", "chroot"]
assert sys.argv[3] == f"--userspec={os.getuid()}:{os.getgid()}"
args = sys.argv[5:]
args[4] = sys.argv[4] + args[4]
raise SystemExit(subprocess.run(args).returncode)
''')
        self.executable("apt-get", '''#!/usr/bin/python3
import os, pathlib, shutil, sys
work = pathlib.Path(os.environ["TEST_WORK"])
(work / "apt-arguments").write_text("\\n".join(sys.argv[1:]))
if os.environ.get("FAIL_DOWNLOAD"):
    raise SystemExit(100)
shutil.copyfile(work / "fixture.deb", "download.deb")
''')
        self.payload = self.work / "package"
        control = self.payload / "DEBIAN/control"
        control.parent.mkdir(parents=True)
        control.write_text("Package: test-live-efi\nVersion: 1\nArchitecture: amd64\n"
                           "Maintainer: Test <test@example.com>\nDescription: EFI fixture\n")
        for name in ("usr/lib/grub/x86_64-efi-signed/gcdx64.efi.signed",
                     "usr/lib/shim/shimx64.efi.signed.latest", "usr/lib/shim/mmx64.efi",
                     "usr/lib/grub/arm64-efi-signed/gcdaa64.efi.signed",
                     "usr/lib/shim/shimaa64.efi.signed.latest", "usr/lib/shim/mmaa64.efi"):
            path = self.payload / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(name)
        self.build_fixture()

    def executable(self, name, content):
        path = self.bin / name
        path.write_text(content)
        path.chmod(0o755)

    def build_fixture(self):
        subprocess.run(["dpkg-deb", "--build", "--root-owner-group", str(self.payload),
                        str(self.work / "fixture.deb")], check=True, capture_output=True)

    def download(self, arch="amd64"):
        return subprocess.run(["bash", str(TOOLS / "download-live-efi.sh"),
                               str(self.target), str(self.output / arch), arch, "AnduinOS 测试"], env=self.env,
                              capture_output=True, text=True)

    def test_only_target_ubuntu_candidates_are_downloaded_and_exported(self):
        for arch, loaders in LOADERS.items():
            with self.subTest(architecture=arch):
                result = self.download(arch)
                self.assertEqual(result.returncode, 0, result.stderr)
                arguments = (self.work / "apt-arguments").read_text().splitlines()
                self.assertEqual(arguments, ["-o", "Dir::Etc::sourcelist=/etc/apt/sources.list.d/ubuntu.sources",
                                            "-o", "Dir::Etc::sourceparts=-", "download",
                                            f"grub-efi-{arch}-signed:{arch}", f"shim-signed:{arch}"])
                self.assertEqual(sorted(p.name for p in (self.output / arch).iterdir()), sorted(loaders))
                self.assertEqual(list((self.target / "tmp").iterdir()), [])
                self.assertFalse((self.target / "usr").exists())

    def test_download_failure_stops_without_export_or_rootfs_residue(self):
        self.env["FAIL_DOWNLOAD"] = "1"
        for arch in LOADERS:
            with self.subTest(architecture=arch):
                self.assertNotEqual(self.download(arch).returncode, 0)
        self.assertFalse(self.output.exists())
        self.assertEqual(list((self.target / "tmp").iterdir()), [])

    def test_missing_official_cd_loader_fails_instead_of_using_local_grub(self):
        (self.payload / "usr/lib/grub/x86_64-efi-signed/gcdx64.efi.signed").unlink()
        (self.payload / "usr/lib/grub/arm64-efi-signed/gcdaa64.efi.signed").unlink()
        self.build_fixture()
        for arch in LOADERS:
            with self.subTest(architecture=arch):
                self.assertNotEqual(self.download(arch).returncode, 0)
        self.assertEqual(list((self.target / "tmp").iterdir()), [])

    def test_unsupported_architecture_fails_before_downloading(self):
        self.assertNotEqual(self.download("riscv64").returncode, 0)
        self.assertFalse((self.work / "apt-arguments").exists())
        self.assertEqual(list((self.target / "tmp").iterdir()), [])

    @unittest.skipUnless(shutil.which("mcopy") and shutil.which("mkfs.vfat"), "mtools/dosfstools required")
    def test_fat_image_contains_exact_loaders_and_label_without_network(self):
        for arch in LOADERS:
            self.assertEqual(self.download(arch).returncode, 0)
        self.env["FAIL_DOWNLOAD"] = "1"
        for arch, loaders in LOADERS.items():
            with self.subTest(architecture=arch):
                image = self.work / f"{arch}.img"
                with image.open("wb") as stream:
                    stream.truncate(10 * 1024 * 1024)
                subprocess.run(["mkfs.vfat", str(image)], check=True, capture_output=True)
                subprocess.run(["bash", str(TOOLS / "prepare-live-efi.sh"),
                                str(image), str(self.output / arch), "AOS_LIVE"],
                               env=self.env, check=True, capture_output=True)
                for name in loaders:
                    result = subprocess.check_output(["mtype", "-i", str(image), f"::/EFI/BOOT/{name}"])
                    self.assertEqual(result, (self.output / arch / name).read_bytes())
                    if name.endswith(".CSV"):
                        self.assertEqual(result.decode("utf-16-le"),
                                         "shimaa64.efi,AnduinOS 测试,,This is the boot entry for AnduinOS 测试\n")
                config = subprocess.check_output(["mtype", "-i", str(image), "::/EFI/BOOT/grub.cfg"], text=True)
                self.assertIn("--label --set=anduinos_iso AOS_LIVE", config)
                self.assertIn("configfile $prefix/grub.cfg", config)

    def test_build_downloads_before_apt_cleanup_and_removes_staging(self):
        source = (ROOT / "build.sh").read_text()
        main = source.split('# =============   main  ================', 1)[1]
        self.assertLess(main.index("setup_apt"), main.index("download-live-efi.sh"))
        self.assertLess(main.index("prepare_iso_directory"), main.index("download-live-efi.sh"))
        self.assertLess(main.index("download-live-efi.sh"), main.index("run_chroot"))
        self.assertEqual(main.count("prepare_iso_directory"), 1)
        self.assertNotIn('if [ "$TARGET_ARCH"', main)
        self.assertIn('"$TARGET_ARCH" "$TARGET_BUSINESS_NAME"', main)
        self.assertNotIn("arm64_grub=", source)
        self.assertIn("find live-efi -maxdepth 1 -type f -delete", source)
        self.assertIn("rmdir live-efi", source)
