import unittest
import subprocess
import tempfile
import io
import json
import xml.etree.ElementTree as ET
from contextlib import redirect_stdout
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from PIL import Image

from framework.dashboard import AcceptanceDashboard
from framework.errors import TestFailure
from framework.feature_model import FeatureSuiteRegistry
from framework.model import Architecture, TestMatrix
from framework.usb_iso import rewrite_config, assert_preserved_arguments
from business.acceptance import _parser, main
from business.install import scenario_check_ids
from business.live_usb import USB_CASE_ID, live_usb_suite_checks, run_live_usb


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

    def test_usb_suite_inventory_keeps_two_distinct_labels(self):
        inspection = SimpleNamespace(path=Path('image.iso'))
        with patch('business.live_usb.volume_label', return_value='CUSTOM_USB'):
            suites = live_usb_suite_checks(inspection)
        self.assertEqual(('live-usb-iso-mode-CUSTOM_USB',
                          'live-usb-iso-mode-ALT_USB',
                          'live-usb-to-go-optical-rejected'), tuple(suites))

    def test_usb_checks_use_the_acceptance_dashboard_before_installation(self):
        inspection = SimpleNamespace(path=Path('image.iso'), sha256='fixture',
                                     architecture=Architecture.AMD64)
        with patch('business.live_usb.volume_label', return_value='AOS_LIVE'):
            checks = live_usb_suite_checks(inspection)
        dashboards = []

        def make_dashboard(*args, **kwargs):
            dashboard = AcceptanceDashboard(*args, **{**kwargs, 'stream': io.StringIO()})
            dashboards.append(dashboard)
            return dashboard

        def run_usb(_inspection, artifacts, _overrides, **kwargs):
            dashboard = kwargs['dashboard']
            dashboard.begin(USB_CASE_ID)
            for suite_id, case_checks in checks.items():
                dashboard.begin_suite(USB_CASE_ID, suite_id)
                for check in case_checks:
                    dashboard.suite_check(USB_CASE_ID, suite_id, check, 'passed')
                dashboard.complete_suite(USB_CASE_ID, suite_id, 'passed', 1)
            dashboard.complete(USB_CASE_ID, 'passed', 3)
            artifacts.mkdir()
            (artifacts / 'summary.json').write_text(json.dumps({
                'results': [dashboard.case_result(USB_CASE_ID)]}))
            return True

        with tempfile.TemporaryDirectory() as directory:
            matrix = Mock()
            matrix.select.return_value = ()
            matrix.defaults.boot_timeout_seconds = 600
            registry = Mock()
            registry.select.return_value = ()
            with (patch('business.acceptance.TestMatrix.load', return_value=matrix),
                  patch('business.acceptance.FeatureSuiteRegistry.load', return_value=registry),
                  patch('business.acceptance.inspect_iso', return_value=inspection),
                  patch('business.acceptance.AcceptanceDashboard', side_effect=make_dashboard),
                  patch('business.live_usb.volume_label', return_value='AOS_LIVE'),
                  patch('business.live_usb.run_live_usb', side_effect=run_usb)):
                result = main(['--iso', 'image.iso', '--arch', 'amd64', '--live-usb-only',
                               '--no-tui', '--artifacts', str(Path(directory) / 'run')])
        self.assertEqual(0, result)
        self.assertEqual((USB_CASE_ID,), tuple(dashboards[0].cases))
        self.assertEqual(tuple(checks), tuple(dashboards[0].cases[USB_CASE_ID].suites))
        self.assertTrue(dashboards[0]._closed)
        self.assertTrue(all(case.state == 'passed' for case in dashboards[0].cases.values()))

    def test_usb_workflows_report_case_suite_and_real_check_levels(self):
        class FakeVm:
            def __init__(self, config):
                self.config = config
                self.qmp = object()
                self.serial = SimpleNamespace(
                    wait_for_shell=lambda _timeout: None,
                    run=lambda *_args, **_kwargs: SimpleNamespace(
                        returncode=0, stdout='ISO_USB_DESKTOP_PASSED'))
                self.process = SimpleNamespace(poll=lambda: None)

            def create_disk(self):
                pass

            def start(self, *, attach_iso):
                self.assert_attach_iso = attach_iso

            def screenshot(self, name):
                path = self.config.artifacts / f'{name}.png'
                image = Image.new('RGB', (1920, 1080))
                image.paste((160, 160, 160), (250, 295, 450, 305))
                image.save(path)
                return path

            def wait(self, *, timeout):
                return 0

            def stop(self):
                pass

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            variables = root / 'vars-template.fd'
            variables.write_bytes(b'fixture')
            inspection = SimpleNamespace(path=root / 'image.iso', sha256='fixture',
                                         architecture=Architecture.AMD64)
            with patch('business.live_usb.volume_label', return_value='AOS_LIVE'):
                suites = live_usb_suite_checks(inspection)
                dashboard = AcceptanceDashboard(
                    (USB_CASE_ID,), iso=inspection.path, architecture='amd64',
                    artifacts=root / 'run', suites={USB_CASE_ID: suites},
                    stream=io.StringIO(), live=False)
                dashboard.start()
                with (patch('business.live_usb.resolve_firmware', return_value=SimpleNamespace(
                          variables_template=variables)),
                      patch('business.live_usb.resolve_qemu', return_value=('qemu', 'kvm')),
                      patch('business.live_usb.prepare_iso_usb', side_effect=lambda _iso, work, _label: work / 'media.raw'),
                      patch('business.live_usb.QemuVm', FakeVm),
                      patch('business.live_usb.boot_iso_with_debug_shell')):
                    passed = run_live_usb(inspection, root / 'run-live-usb', Mock(),
                                          dashboard=dashboard)
                dashboard.close()
            summary = json.loads((root / 'run-live-usb' / 'summary.json').read_text())
            junit = ET.parse(root / 'run-live-usb' / 'junit.xml').getroot()
        self.assertTrue(passed)
        self.assertEqual(2, summary['schema_version'])
        self.assertEqual([USB_CASE_ID], [item['id'] for item in summary['results']])
        self.assertEqual(list(suites), [item['id'] for item in summary['results'][0]['suites']])
        self.assertTrue(all(check['status'] == 'passed'
                            for suite in summary['results'][0]['suites']
                            for check in suite['checks']))
        self.assertEqual('10', junit.get('tests'))
        self.assertEqual('0', junit.get('failures'))

    def test_full_acceptance_summary_keeps_usb_and_installation_in_one_tree(self):
        matrix = TestMatrix.load(Path(__file__).resolve().parents[1] / 'cases/install.json')
        scenario = next(item for item in matrix.select(Architecture.AMD64, ())
                        if item.id == 'bios-online-btrfs')
        feature = next(item for item in FeatureSuiteRegistry.load(
            Path(__file__).resolve().parents[1] / 'cases/desktop.json', matrix
        ).select(Architecture.AMD64) if item.source_for(Architecture.AMD64) == scenario.id)
        selected = SimpleNamespace(select=lambda *_args: (scenario,), defaults=matrix.defaults)
        registry = Mock()
        registry.select.return_value = (feature,)

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            iso = root / 'image.iso'
            iso.write_bytes(b'fixture')
            artifacts = root / 'run'
            inspection = SimpleNamespace(path=iso, sha256='fixture',
                                         architecture=Architecture.AMD64)
            storage = SimpleNamespace(backend='fixture', root=root, reason='fixture')
            options = SimpleNamespace(artifacts_root=artifacts, disk_storage=storage,
                                      disk_gib=1, free_space_reserve_gib=1, memory_mib=1024)

            def make_dashboard(*args, **kwargs):
                return AcceptanceDashboard(*args, **{**kwargs, 'stream': io.StringIO()})

            def run_usb(_inspection, destination, _overrides, **kwargs):
                dashboard = kwargs['dashboard']
                dashboard.begin(USB_CASE_ID)
                for suite_id, checks in live_usb_suite_checks(inspection).items():
                    dashboard.begin_suite(USB_CASE_ID, suite_id)
                    for check in checks:
                        dashboard.suite_check(USB_CASE_ID, suite_id, check, 'passed')
                    dashboard.complete_suite(USB_CASE_ID, suite_id, 'passed', 1)
                dashboard.complete(USB_CASE_ID, 'passed', 3)
                destination.mkdir()
                (destination / 'summary.json').write_text(json.dumps({
                    'results': [dashboard.case_result(USB_CASE_ID)]}))
                return True

            class FakeRunner:
                def __init__(self, *_args, check_callback, **_kwargs):
                    self.check_callback = check_callback

                def run(self, selected_scenario, *, promote):
                    self.assert_promote = promote
                    for check in scenario_check_ids(selected_scenario):
                        self.check_callback(selected_scenario.id, check, 'passed', 'fixture')
                    (artifacts / selected_scenario.id).mkdir()
                    return SimpleNamespace(id=selected_scenario.id, status='passed',
                                           seconds=1, error='', artifacts=artifacts / selected_scenario.id,
                                           promoted_base=SimpleNamespace(cleanup=lambda: None))

            class FakeFeatureRunner:
                def __init__(self, *_args, check_callback, **_kwargs):
                    self.check_callback = check_callback

                def run(self, _base, selected_suite):
                    for check in selected_suite.checks:
                        self.check_callback(scenario.id, selected_suite.id, check,
                                            'passed', 'fixture')
                    return SimpleNamespace(id=selected_suite.id, source_case=scenario.id,
                                           status='passed', seconds=1, error='',
                                           artifacts=artifacts / scenario.id / 'feature-suites' /
                                           selected_suite.id)

            with (patch('business.acceptance.TestMatrix.load', return_value=selected),
                  patch('business.acceptance.FeatureSuiteRegistry.load', return_value=registry),
                  patch('business.acceptance.inspect_iso', return_value=inspection),
                  patch('business.acceptance.AcceptanceDashboard', side_effect=make_dashboard),
                  patch('business.acceptance._preflight'),
                  patch('business.acceptance._options', return_value=options),
                  patch('business.acceptance.assert_disk_storage_ready'),
                  patch('business.acceptance.prepare_disk_storage'),
                  patch('business.acceptance.cleanup_disk_storage'),
                  patch('business.acceptance.ScenarioRunner', FakeRunner),
                  patch('business.acceptance.FeatureSuiteRunner', FakeFeatureRunner),
                  patch('business.live_usb.volume_label', return_value='AOS_LIVE'),
                  patch('business.live_usb.run_live_usb', side_effect=run_usb),
                  redirect_stdout(io.StringIO())):
                result = main(['--iso', str(iso), '--arch', 'amd64', '--no-tui',
                               '--artifacts', str(artifacts)])
            summary = json.loads((artifacts / 'summary.json').read_text())
            junit = ET.parse(artifacts / 'junit.xml').getroot()
        self.assertEqual(0, result)
        self.assertEqual(2, summary['schema_version'])
        self.assertEqual([USB_CASE_ID, scenario.id],
                         [item['id'] for item in summary['results']])
        self.assertNotIn('feature_suites', summary)
        self.assertEqual(['installation', feature.id],
                         [suite['id'] for suite in summary['results'][1]['suites']])
        self.assertEqual(list(scenario_check_ids(scenario)),
                         [check['id'] for check in summary['results'][1]['suites'][0]['checks']])
        self.assertEqual(list(feature.checks),
                         [check['id'] for check in summary['results'][1]['suites'][1]['checks']])
        self.assertEqual('0', junit.get('failures'))

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
