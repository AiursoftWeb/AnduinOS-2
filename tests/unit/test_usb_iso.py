import unittest
import subprocess
import tempfile
from pathlib import Path

from framework.errors import TestFailure
from framework.usb_iso import rewrite_config, assert_preserved_arguments
from business.acceptance import _parser


class RufusIsoModeTests(unittest.TestCase):
    def config(self, label):
        return (f' linux /LiveOS/vmlinuz root=live:CDLABEL={label} '
                'rd.live.dir=LiveOS rd.live.squashimg=rootfs.squashfs '
                'rd.anduinos.live=1 rd.anduinos.keyboard=us '
                'rd.overlay=LABEL=ANDUINOS-PERSIST\n')

    def test_old_label_reproduces_live_parameter_corruption(self):
        before = self.config('anduinos')
        after = rewrite_config(before, 'anduinos', 'ANDUINOS')
        self.assertIn('rd.ANDUINOS.live=1', after)
        with self.assertRaises(TestFailure):
            assert_preserved_arguments(before, after, 'anduinos', 'ANDUINOS')

    def test_uppercase_brand_label_still_corrupts_persistence_on_rename(self):
        before = self.config('ANDUINOS')
        after = rewrite_config(before, 'ANDUINOS', 'CUSTOM_USB')
        self.assertIn('LABEL=CUSTOM_USB-PERSIST', after)
        with self.assertRaises(TestFailure):
            assert_preserved_arguments(before, after, 'ANDUINOS', 'CUSTOM_USB')

    def test_dedicated_label_preserves_every_non_label_argument(self):
        build = (Path(__file__).resolve().parents[2] / 'build.sh').read_text()
        self.assertIn('LIVE_MEDIA_LABEL="AOS_LIVE"', build)
        self.assertNotIn('CDLABEL=$TARGET_NAME', build)
        self.assertEqual(build.count('-volid "$LIVE_MEDIA_LABEL"'), 2)
        self.assertIn('search --no-floppy --label --set=anduinos_iso $LIVE_MEDIA_LABEL', build)
        for label in ('AOS_LIVE', 'CUSTOM_USB'):
            before = self.config('AOS_LIVE')
            after = rewrite_config(before, 'AOS_LIVE', label)
            assert_preserved_arguments(before, after, 'AOS_LIVE', label)

    def test_replacement_matches_rufus_token_and_occurrence_limits(self):
        before = '  LiNuX anduinos anduinos anduinos anduinos anduinos\nset x=anduinos\n'
        self.assertEqual(rewrite_config(before, 'anduinos', 'USB'),
                         '  LiNuX USB USB USB USB anduinos\nset x=anduinos\n')

    def test_targeted_cli_is_explicit_and_default_keeps_regression(self):
        args = ['--iso', 'test.iso', '--arch', 'amd64']
        self.assertFalse(_parser().parse_args(args).live_usb_only)
        self.assertTrue(_parser().parse_args(args + ['--live-usb-only']).live_usb_only)

    def test_file_manifest_exempts_only_expected_mutable_boot_files(self):
        build = (Path(__file__).resolve().parents[2] / 'build.sh').read_text()
        command = next(line.split("-c '", 1)[1][:-1] for line in build.splitlines()
                       if "-c 'find . -type f" in line)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for name in ('LiveOS/rootfs.squashfs', 'LiveOS/initrd', 'LiveOS/vmlinuz',
                         'LiveOS/filesystem.manifest', 'isolinux/grub.cfg',
                         'isolinux/other.cfg', 'EFI/efiboot.img', 'isolinux/bios.img'):
                path = root / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text('fixture')
            subprocess.run(['bash', '-o', 'pipefail', '-c', command], cwd=root, check=True)
            manifest = (root/'md5sum.txt').read_text()
            for name in ('rootfs.squashfs', 'initrd', 'vmlinuz', 'filesystem.manifest', 'other.cfg'):
                self.assertIn(name, manifest)
            for name in ('grub.cfg', 'efiboot.img', 'bios.img', 'md5sum.txt'):
                self.assertNotIn(name, manifest)


if __name__ == '__main__':
    unittest.main()
