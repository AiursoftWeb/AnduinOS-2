"""HyperFluent menu semantics captured from signed GRUB, plus ISO contracts."""

import tempfile
import unittest
from pathlib import Path

from PIL import Image, ImageDraw

from framework.iso import _parse_live_entries, _parse_persistent_entry
from framework.visual import (
    grub_editor_left_cursor_y,
    grub_editor_layout,
    grub_frame_difference,
    grub_menu_layout,
)


ROOT = Path(__file__).resolve().parents[2]
FRAMES = ROOT / "tests/fixtures/hyperfluent"


class HyperfluentVisualTests(unittest.TestCase):
    def test_full_hd_stock_grub_menu_is_visible_below_old_crop(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            frame = Path(temporary) / "full-hd-menu.ppm"
            image = Image.new("RGB", (1920, 1080), "black")
            draw = ImageDraw.Draw(image)
            draw.rectangle((21, 65, 1893, 962), outline=(190, 190, 190), width=2)
            draw.rectangle((24, 74, 1890, 90), fill=(180, 180, 180))
            draw.text((120, 77), "Try or Install AnduinOS", fill="black")
            draw.text((120, 97), "Advanced Options", fill="white")
            image.save(frame, format="PPM")

            layout = grub_menu_layout(frame)
            self.assertIsNotNone(layout)
            self.assertEqual((65, 962), (layout.top, layout.bottom))
            self.assertEqual(1, layout.visible_unselected_entries)
            self.assertIsNone(grub_editor_layout(frame))

    def test_left_editor_lower_border_below_three_quarters_is_detected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            frame = Path(temporary) / "left-editor.ppm"
            image = Image.new("RGB", (1440, 900), (18, 26, 42))
            draw = ImageDraw.Draw(image)
            draw.rectangle((1100, 400, 1320, 660), fill=(18, 52, 170))
            draw.rectangle((97, 298, 1018, 683), outline=(180, 180, 180), width=2)
            for index, command in enumerate(("setparams", "set gfxpayload", "linux", "initrd")):
                draw.text((110, 320 + index * 23), command, fill=(230, 230, 230))
            image.save(frame, format="PPM")
            layout = grub_editor_layout(frame)
            self.assertIsNotNone(layout)
            self.assertEqual((97, 1018, 298, 683),
                             (layout.left, layout.right, layout.top, layout.bottom))

    def test_signed_grub_menu_scroll_and_editor_are_distinct(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            frames = {}
            for name in (
                "top", "submenu", "submenu-scrolled", "editor", "editor-down",
                "top-1024", "submenu-1024",
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
            with Image.open(FRAMES / "editor.png") as image:
                self.assertLess(editor.left, image.width // 8)
            self.assertGreater(grub_frame_difference(frames["editor"], frames["editor-down"]), 8)
            self.assertIsNotNone(grub_editor_left_cursor_y(frames["editor"]))
            self.assertGreater(grub_editor_left_cursor_y(frames["editor-down"]),
                               grub_editor_left_cursor_y(frames["editor"]))
            self.assertEqual(2, grub_menu_layout(frames["top-1024"]).visible_unselected_entries)
            self.assertEqual(4, grub_menu_layout(frames["submenu-1024"]).visible_unselected_entries)
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
        self.assertIn("if regexp '^cd[0-9]+$' \"\\$root\"; then", build)
        self.assertIn("This boot medium is not supported. Powering off in 15 seconds.", build)

    def test_live_grub_prefers_16_by_9_without_dropping_16_by_10(self) -> None:
        build = (ROOT / "build.sh").read_text(encoding="utf-8")
        self.assertIn(
            "set gfxmode=1920x1080,1600x900,1280x720,1440x900,1280x800,1024x768,auto",
            build,
        )


if __name__ == "__main__":
    unittest.main()
