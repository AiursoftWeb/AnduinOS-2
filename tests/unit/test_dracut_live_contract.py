from pathlib import Path
import struct
import tempfile
import unittest

from framework.errors import ConfigurationError
from framework.iso import _pe_machine, _validate_dracut_live_contract


ROOT = Path(__file__).resolve().parents[2]


class DracutLiveContractTests(unittest.TestCase):
    def test_iso_uses_one_direct_squashfs_under_liveos(self) -> None:
        build = (ROOT / "build.sh").read_text()
        self.assertIn("image/{LiveOS,isolinux,.disk}", build)
        self.assertIn("image/LiveOS/rootfs.squashfs", build)
        self.assertEqual(build.count("mksquashfs new_building_os"), 1)
        self.assertIn('-e "boot/anduinos-live-initrd.img"', build)
        self.assertNotIn("image/casper", build)
        self.assertNotIn("/casper/", build)

    def test_every_live_entry_uses_the_dracut_contract(self) -> None:
        build = (ROOT / "build.sh").read_text()
        common = (
            "root=live:CDLABEL=$TARGET_NAME rd.live.dir=LiveOS "
            "rd.live.squashimg=rootfs.squashfs rd.overlay "
            "rd.anduinos.live=1"
        )
        self.assertIn(f'LIVE_BOOT_ARGS="{common}"', build)
        self.assertIn("rd.overlay=LABEL=ANDUINOS-PERSIST", build)
        self.assertNotIn("ANDUINOS-PERSISTENCE", build)
        self.assertIn("rd.live.overlay.cowfs=ext4", build)
        self.assertIn("rd.live.check=1", build)
        self.assertEqual(build.count("-partition_offset 16"), 2)
        self.assertIn("implantisomd5 --force", build)
        self.assertNotIn("boot=casper", build)

    def test_dedicated_live_initrd_is_non_host_only_and_module_complete(self) -> None:
        script = (ROOT / "mods/80-dracut-live-image/install.sh").read_text()
        self.assertIn("--no-hostonly", script)
        self.assertIn("--no-hostonly-cmdline", script)
        for module in (
            "dmsquash-live",
            "dmsquash-live-autooverlay",
            "overlayfs",
            "anduinos-live-layers",
        ):
            self.assertIn(module, script)
        self.assertIn("/boot/anduinos-live-initrd.img", script)
        self.assertIn("lsinitrd -m", script)
        self.assertIn(
            "var/lib/dracut/hooks/pre-pivot/90-anduinos-live-prepare.sh",
            script,
        )
        self.assertIn("usr/sbin/dmsquash-live-root", script)
        self.assertIn("usr/sbin/create-overlay.upstream", script)
        self.assertIn("parted --script --fix", script)
        self.assertIn("LABEL=ANDUINOS-PERSIST", script)
        self.assertIn("dpkg-query -S /usr/sbin/update-initramfs", script)
        self.assertIn("dracut: /usr/sbin/update-initramfs", script)
        self.assertNotIn("test ! -e /usr/sbin/update-initramfs", script)
        self.assertFalse((ROOT / "mods/46-casper-patch/install.sh").exists())
        self.assertFalse((ROOT / "mods/80-initramfs-update/install.sh").exists())

    def test_build_dependencies_include_media_check_implanter(self) -> None:
        makefile = (ROOT / "makefile").read_text()
        self.assertIn("isomd5sum", makefile)

    def test_arm64_cross_build_uses_target_root_secure_boot_payload(self) -> None:
        makefile = (ROOT / "makefile").read_text()
        build = (ROOT / "build.sh").read_text()
        arm64_dependencies = makefile.split("DEPS_arm64 :=", 1)[1].split(
            "HOST_ARCH", 1
        )[0]

        self.assertNotIn("shim-signed", arm64_dependencies)
        self.assertNotIn("grub-efi-arm64", arm64_dependencies)
        self.assertIn("qemu-user-binfmt", makefile)
        self.assertIn("ifneq ($(HOST_ARCH),$(TARGET_ARCH))", makefile)
        for payload in (
            "gcdaa64.efi.signed",
            "shimaa64.efi.signed.latest",
            "mmaa64.efi",
        ):
            self.assertIn(payload, build)
        self.assertIn("mmd -i efiboot.img ::/EFI ::/EFI/BOOT", build)
        self.assertIn("::/EFI/BOOT/BOOTAA64.EFI", build)
        self.assertIn("::/EFI/BOOT/grubaa64.efi", build)
        self.assertIn("::/EFI/BOOT/mmaa64.efi", build)
        self.assertIn("search --no-floppy --label --set=anduinos_iso", build)
        self.assertIn("configfile \\$prefix/grub.cfg", build)
        self.assertIn("sbverify --list", build)
        self.assertIn("fsck.vfat -vn efiboot.img", build)

    def test_grub_acceptance_contract_covers_temporary_and_persistent_modes(self) -> None:
        common = (
            "root=live:CDLABEL=anduinos rd.live.dir=LiveOS "
            "rd.live.squashimg=rootfs.squashfs rd.anduinos.live=1"
        )
        entries = [
            f"linux /LiveOS/vmlinuz {common} rd.overlay locale=l{index}\n"
            "initrd /LiveOS/initrd"
            for index in range(28)
        ]
        entries.extend(
            (
                f"linux /LiveOS/vmlinuz {common} rd.overlay nomodeset\n"
                "initrd /LiveOS/initrd",
                f"linux /LiveOS/vmlinuz {common} "
                "rd.overlay=LABEL=ANDUINOS-PERSIST "
                "rd.live.overlay.cowfs=ext4\ninitrd /LiveOS/initrd",
                f"linux /LiveOS/vmlinuz {common} rd.overlay rd.live.check=1\n"
                "initrd /LiveOS/initrd",
            )
        )
        _validate_dracut_live_contract("\n".join(entries))
        with self.assertRaises(ConfigurationError):
            _validate_dracut_live_contract("\n".join(entries).replace(
                "rd.overlay=LABEL=ANDUINOS-PERSIST", "persistent"
            ))

    def test_efi_inspector_reads_the_pe_machine_contract(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            payload = Path(directory) / "BOOTAA64.EFI"
            image = bytearray(0x88)
            image[:2] = b"MZ"
            struct.pack_into("<I", image, 0x3C, 0x80)
            image[0x80:0x84] = b"PE\0\0"
            struct.pack_into("<H", image, 0x84, 0xAA64)
            payload.write_bytes(image)

            self.assertEqual(0xAA64, _pe_machine(payload))
            payload.write_bytes(b"not a PE image")
            with self.assertRaisesRegex(ConfigurationError, "not a PE image"):
                _pe_machine(payload)


if __name__ == "__main__":
    unittest.main()
