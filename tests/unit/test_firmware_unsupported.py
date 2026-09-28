"""Regression contracts for UEFI which does not implement Secure Boot."""
from pathlib import Path
import tempfile
import unittest

from framework.firmware import FirmwareOverrides, resolve_firmware
from framework.model import Architecture, Firmware, TestMatrix
from framework.errors import ConfigurationError
from assertions.install import _UNSUPPORTED_FIRMWARE_ASSERTION


class UnsupportedFirmwareTests(unittest.TestCase):
    def test_explicit_unsupported_firmware_does_not_use_secure_boot_override(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            code, secure_code, variables = (root / name for name in ('plain.fd', 'secure.fd', 'vars.fd'))
            for path in (code, secure_code, variables):
                path.touch()
            result = resolve_firmware(Architecture.AMD64, Firmware.UEFI_UNSUPPORTED,
                FirmwareOverrides(uefi_code=secure_code, uefi_unsupported_code=code,
                                  uefi_vars_no_secure_boot=variables))
        self.assertEqual(result.code, code)
        self.assertEqual(result.variables_template, variables)

    def test_unsupported_arm_fixture_is_not_silently_replaced_with_disabled(self):
        with self.assertRaises(ConfigurationError):
            resolve_firmware(Architecture.ARM64, Firmware.UEFI_UNSUPPORTED, FirmwareOverrides())

    def test_matrix_requires_both_filesystems_without_mok_enrollment(self):
        matrix = TestMatrix.load(Path(__file__).parents[1] / 'cases/install.json')
        cases = [c for c in matrix.scenarios if c.firmware is Firmware.UEFI_UNSUPPORTED]
        self.assertEqual({c.filesystem.value for c in cases}, {'btrfs', 'ext4'})
        self.assertTrue(all(c.architectures == (Architecture.AMD64,) for c in cases))
        self.assertTrue(all(not c.mok_enrollment for c in cases))

    def test_guest_evidence_requires_variable_absence_and_real_customer_exit(self):
        self.assertIn('secureboot-variable-absent', _UNSUPPORTED_FIRMWARE_ASSERTION)
        self.assertIn('result.returncode == 255', _UNSUPPORTED_FIRMWARE_ASSERTION)
        self.assertIn('not in os.listdir(variables)', _UNSUPPORTED_FIRMWARE_ASSERTION)
        self.assertIn("glob('MokNew-*')", _UNSUPPORTED_FIRMWARE_ASSERTION)
