"""HyperFluent menu semantics captured from signed GRUB, plus ISO contracts."""

import tempfile
import unittest
from pathlib import Path

from PIL import Image

from framework.iso import _parse_live_entries, _parse_persistent_entry
from framework.visual import (
    grub_editor_layout,
    grub_frame_difference,
    grub_menu_layout,
)


ROOT = Path(__file__).resolve().parents[2]
FRAMES = ROOT / "tests/fixtures/hyperfluent"


class HyperfluentVisualTests(unittest.TestCase):
    def test_signed_grub_menu_scroll_and_editor_are_distinct(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            frames = {}
            for name in (
                "top", "submenu", "submenu-scrolled", "editor", "editor-down",
                "top-1024", "submenu-1024", "bios-16",
                "arm-uefi-top", "arm-uefi-submenu",
            ):
                destination = Path(temporary) / f"{name}.ppm"
                with Image.open(FRAMES / f"{name}.png") as image:
                    image.save(destination, format="PPM")
                frames[name] = destination

            top = grub_menu_layout(frames["top"])
            submenu = grub_menu_layout(frames["submenu"])
            scrolled = grub_menu_layout(frames["submenu-scrolled"])
            self.assertIsNotNone(top)
            self.assertIsNotNone(submenu)
            self.assertIsNotNone(scrolled)
            self.assertEqual(2, top.visible_unselected_entries)
            self.assertEqual(4, submenu.visible_unselected_entries)
            self.assertEqual(4, scrolled.visible_unselected_entries)
            self.assertNotEqual(submenu.highlight_center, scrolled.highlight_center)
            self.assertGreater(grub_frame_difference(frames["submenu"], frames["submenu-scrolled"]), 100)
            self.assertIsNone(grub_menu_layout(frames["editor"]))
            editor = grub_editor_layout(frames["editor"])
            self.assertIsNotNone(editor)
            self.assertGreaterEqual(editor.visible_command_lines, 4)
            self.assertGreater(grub_frame_difference(frames["editor"], frames["editor-down"]), 8)
            self.assertEqual(2, grub_menu_layout(frames["top-1024"]).visible_unselected_entries)
            self.assertEqual(4, grub_menu_layout(frames["submenu-1024"]).visible_unselected_entries)
            self.assertEqual(2, grub_menu_layout(frames["bios-16"]).visible_unselected_entries)
            self.assertEqual(2, grub_menu_layout(frames["arm-uefi-top"]).visible_unselected_entries)
            self.assertEqual(4, grub_menu_layout(frames["arm-uefi-submenu"]).visible_unselected_entries)

    def test_theme_does_not_change_live_kernel_contract(self) -> None:
        content = "\n".join(
            f'''menuentry "Language {index}" --class lang {{
    linux /LiveOS/vmlinuz root=live:CDLABEL=AOS_LIVE rd.live.dir=LiveOS rd.live.squashimg=rootfs.squashfs rd.overlay rd.anduinos.live=1 locale=en_US.UTF-8 timezone=UTC systemd.timezone=UTC rd.anduinos.keyboard=us
    initrd /LiveOS/initrd
}}'''
            for index in range(28)
        )
        content += '''
menuentry "AnduinOS To Go" --class anduinos {
    linux /LiveOS/vmlinuz root=live:CDLABEL=AOS_LIVE rd.overlay=LABEL=ANDUINOS-PERSIST
    initrd /LiveOS/initrd
}
'''
        self.assertEqual(28, len(_parse_live_entries(content)))
        self.assertEqual("AnduinOS To Go", _parse_persistent_entry(content).name)

    def test_build_copies_packaged_theme_before_manifest(self) -> None:
        build = (ROOT / "build.sh").read_text(encoding="utf-8")
        install = (ROOT / "mods/05-live-kernel-apps-installer/install.sh").read_text(
            encoding="utf-8"
        )
        self.assertIn("apt install -y anduinos-hyperfluent-grub-theme", install)
        self.assertLess(build.index("prepare_live_grub_theme\nbuild_iso"), build.index('echo "$0 - Build completed."'))
        self.assertIn("source /boot/grub/themes/anduinos-hyperfluent/live-grub.cfg", build)
        self.assertIn('gfxterm gfxmenu png all_video', build)
        self.assertIn("if loadfont unicode", build)
        self.assertIn('--size="16"', build)
        self.assertIn("/boot/grub/fonts/anduinos-unicode-16.pf2", build)
        self.assertIn("LIVE_MEDIA_LABEL=\"AOS_LIVE\"", build)


if __name__ == "__main__":
    unittest.main()
