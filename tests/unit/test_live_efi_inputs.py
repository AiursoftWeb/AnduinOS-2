"""Official Live loaders are downloaded, never installed into the rootfs."""

import os
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[2]
LOADERS = {
    "amd64": ("BOOTX64.EFI", "grubx64.efi", "mmx64.efi"),
    "arm64": ("BOOTAA64.EFI", "grubaa64.efi", "mmaa64.efi"),
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

    def run_function(self, name, *args):
        # Load only the function under test, not build.sh's host configuration
        # or destructive main build pipeline.
        source = (ROOT / "build.sh").read_text()
        marker = f"function {name}()"
        function = marker + source.split(marker, 1)[1].split("\nfunction ", 1)[0]
        return subprocess.run(["bash", "-euo", "pipefail", "-c", function + f'\n{name} "$@"',
                               "test-live-efi", *map(str, args)], env=self.env,
                              cwd=self.work, capture_output=True, text=True)

    def download(self, arch="amd64"):
        return self.run_function("download_live_efi", self.target,
                                 self.output / arch, arch)

    def mock_steps(self, names):
        self.executable("print_ok", "#!/bin/sh\nexit 0\n")
        for name in names:
            self.executable(name, '''#!/usr/bin/python3
import json, os, pathlib, sys
name = pathlib.Path(sys.argv[0]).name
with pathlib.Path(os.environ["TEST_WORK"], "steps").open("a") as stream:
    stream.write(json.dumps([name, *sys.argv[1:]]) + "\\n")
raise SystemExit(23 if os.environ.get("FAIL_STEP") == name else 0)
''')

    def steps(self):
        return [json.loads(line) for line in (self.work / "steps").read_text().splitlines()]

    def test_ubuntu_workshop_uses_an_independent_root_and_propagates_failure(self):
        self.env.update(SCRIPT_DIR=str(self.work / "build root"),
                        TARGET_BUSINESS_NAME="AnduinOS 测试")
        self.mock_steps(["bootstrap_ubuntu_root", "configure_ubuntu_sources",
                         "sudo", "download_live_efi", "judge"])
        root = str(self.work / "build root/official_ubuntu_os")
        for arch in LOADERS:
            with self.subTest(architecture=arch):
                self.env["TARGET_ARCH"] = arch
                result = self.run_function("run_chroot_ubuntu")
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(self.steps()[-5:], [
                    ["bootstrap_ubuntu_root", root, "ca-certificates"],
                    ["configure_ubuntu_sources", root],
                    ["sudo", "chroot", root, "apt-get", "update"],
                    ["download_live_efi", root,
                     str(self.work / "build root/image/isolinux/live-efi"), arch],
                    ["judge", "Export official Ubuntu Live bootloaders"],
                ])
        for step in ("bootstrap_ubuntu_root", "configure_ubuntu_sources", "sudo", "download_live_efi"):
            with self.subTest(failed_step=step):
                self.env["FAIL_STEP"] = step
                self.assertEqual(self.run_function("run_chroot_ubuntu").returncode, 23)
                self.assertEqual(self.steps()[-1][0], step)

    def test_anduinos_workshop_unmounts_before_export_and_stops_on_mod_failure(self):
        steps = ["download_base_system", "mount_folders", "setup_apt",
                 "apply_anduinos_mods", "umount_folders", "prepare_live_grub_font",
                 "prepare_live_grub_theme", "export_anduinos_payload"]
        self.mock_steps(steps)
        result = self.run_function("run_chroot_anduinos")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.steps(), [[step] for step in steps])
        (self.work / "steps").unlink()
        self.env["FAIL_STEP"] = "apply_anduinos_mods"
        self.assertEqual(self.run_function("run_chroot_anduinos").returncode, 23)
        self.assertEqual(self.steps(), [[step] for step in steps[:4]])

    def test_both_workshops_bootstrap_the_configured_release_and_architecture(self):
        self.mock_steps(["sudo", "judge"])
        self.env.update(TARGET_UBUNTU_VERSION="resolute", APT_SOURCE="https://ubuntu.example/archive")
        for arch in LOADERS:
            self.env["TARGET_ARCH"] = arch
            result = self.run_function("bootstrap_ubuntu_root", self.target, "ca-certificates")
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(self.steps()[-2], ["sudo", "debootstrap", f"--arch={arch}",
                "--variant=minbase", "--include=ca-certificates", "resolute",
                str(self.target), "https://ubuntu.example/archive"])

    def test_shared_ubuntu_sources_contain_no_anduinos_repository(self):
        self.executable("sudo", '#!/bin/sh\nexec "$@"\n')
        self.executable("print_ok", "#!/bin/sh\nexit 0\n")
        self.executable("judge", "#!/bin/sh\nexit 0\n")
        self.env["APT_SOURCE"] = "https://ubuntu.example/archive"
        for suite in ("resolute", "stonking"):
            self.env["TARGET_UBUNTU_VERSION"] = suite
            result = self.run_function("configure_ubuntu_sources", self.target)
            self.assertEqual(result.returncode, 0, result.stderr)
            source = (self.target / "etc/apt/sources.list.d/ubuntu.sources").read_text()
            for suffix in ("", "-updates", "-backports", "-security"):
                self.assertIn(f"Suites: {suite}{suffix}\n", source)
            self.assertEqual(source.count("Signed-By: /usr/share/keyrings/ubuntu-archive-keyring.gpg"), 4)
            self.assertEqual(source.count("URIs: https://ubuntu.example/archive"), 4)
            self.assertNotIn("anduinos", source)

    @unittest.skipUnless(shutil.which("mksquashfs") and shutil.which("unsquashfs"), "squashfs-tools required")
    def test_anduinos_export_delivers_system_artifacts_without_ubuntu_workspace(self):
        root = self.work / "new_building_os"
        (root / "boot").mkdir(parents=True)
        (root / "boot/vmlinuz-test").write_bytes(b"kernel fixture")
        (root / "vmlinuz").symlink_to("boot/vmlinuz-test")
        (root / "boot/anduinos-live-initrd.img").write_bytes(b"live initrd fixture")
        (root / "system-marker").write_text("AnduinOS")
        (self.work / "official_ubuntu_os").mkdir()
        (self.work / "official_ubuntu_os/ubuntu-only-marker").write_text("never include")
        output = self.work / "image/LiveOS"
        output.mkdir(parents=True)
        self.executable("print_ok", "#!/bin/sh\nexit 0\n")
        self.executable("judge", "#!/bin/sh\nexit 0\n")
        self.executable("sudo", '''#!/usr/bin/python3
import subprocess, sys
command = sys.argv[1:]
if command[0] == "chroot":
    assert command[:4] == ["chroot", "new_building_os", "dpkg-query", "-W"]
    print("anduinos-grub 2.0.5")
else:
    if command[0] == "mksquashfs":
        command += ["-processors", "1"]
    raise SystemExit(subprocess.run(command).returncode)
''')
        result = self.run_function("export_anduinos_payload")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual({p.name for p in output.iterdir()}, {
            "rootfs.squashfs", "vmlinuz", "initrd", "filesystem.manifest", "filesystem.size"})
        self.assertEqual((output / "vmlinuz").read_bytes(), b"kernel fixture")
        self.assertEqual((output / "initrd").read_bytes(), b"live initrd fixture")
        self.assertEqual((output / "filesystem.manifest").read_text(), "anduinos-grub 2.0.5\n")
        self.assertGreater(int((output / "filesystem.size").read_text()), 0)
        listing = subprocess.check_output(["unsquashfs", "-l", str(output / "rootfs.squashfs")], text=True)
        self.assertIn("system-marker", listing)
        self.assertNotIn("ubuntu-only-marker", listing)
        self.assertNotIn("anduinos-live-initrd.img", listing)

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
                result = self.run_function("prepare_live_efi", image,
                                           self.output / arch, "AOS_LIVE")
                self.assertEqual(result.returncode, 0, result.stderr)
                for name in loaders:
                    result = subprocess.check_output(["mtype", "-i", str(image), f"::/EFI/BOOT/{name}"])
                    self.assertEqual(result, (self.output / arch / name).read_bytes())
                listing = subprocess.check_output(
                    ["mdir", "-b", "-i", str(image), "::/EFI/BOOT"], text=True)
                self.assertEqual(
                    {name.rsplit("/", 1)[-1] for name in listing.splitlines()},
                    {*loaders, "grub.cfg"},
                )
                config = subprocess.check_output(["mtype", "-i", str(image), "::/EFI/BOOT/grub.cfg"], text=True)
                self.assertIn("--label --set=anduinos_iso AOS_LIVE", config)
                self.assertIn("configfile $prefix/grub.cfg", config)

    def test_main_runs_two_workshops_then_assembles_only_their_outputs(self):
        source = (ROOT / "build.sh").read_text()
        main = source.split('# =============   main  ================', 1)[1]
        calls = [line.strip() for line in main.splitlines()
                 if line.startswith("    ") and line.strip().isidentifier()]
        self.assertEqual(calls, ["bind_signal", "clean", "prepare_iso_directory",
                                 "run_chroot_anduinos", "run_chroot_ubuntu", "build_iso"])
        self.assertNotIn("image/isolinux/live-efi", main)
        self.assertNotIn("arm64_grub=", source)
        self.assertIn("find live-efi -maxdepth 1 -type f -delete", source)
        self.assertIn("rmdir live-efi", source)
        assembly = source.split("function build_iso()", 1)[1].split("\nfunction ", 1)[0]
        for implementation in ("new_building_os", "official_ubuntu_os", "chroot", "mksquashfs"):
            self.assertNotIn(implementation, assembly)
        export = source.split("function export_anduinos_payload()", 1)[1].split("\nfunction ", 1)[0]
        self.assertIn("mksquashfs new_building_os image/LiveOS/rootfs.squashfs", export)
        self.assertIn("image/LiveOS/filesystem.manifest", export)
        self.assertNotIn("official_ubuntu_os", export.split("\n}", 1)[0])
        self.assertIn('"$SCRIPT_DIR/official_ubuntu_os"', (ROOT / "clean_all.sh").read_text())
        self.assertIn("official_ubuntu_os", (ROOT / ".gitignore").read_text().splitlines())
