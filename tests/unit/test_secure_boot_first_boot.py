"""Keep first-boot health assertions fail-closed, without a GTK dependency."""

import copy
from pathlib import Path
import unittest
from unittest.mock import patch

from assertions.guest.ui.secure_boot import ROW_STATES, REPAIR_ACTIONS, requires_own_bootloader, validate_status, validate_ui
from business.install.context import scenario_check_ids
from framework.model import TestMatrix


class SecureBootFirstBootTests(unittest.TestCase):
    def setUp(self):
        self.status = {
            "secure_boot": {
                "enabled": True, "status": "enabled", "key_present": True,
                "certificate_present": True, "enrolled": True,
                "configuration_present": True, "enrollment_pending": False,
                "signing_identity": {
                    "purpose": "unified", "enrollment": "enrolled",
                    "key_present": True, "defaults_ready": None,
                },
            },
            "dkms": {"untrusted_modules": []},
        }
        self.names = {text for pair in ROW_STATES for text in pair} | {"Trusted"}

    def test_fresh_certificate_without_any_dkms_modules_is_healthy(self):
        validate_status(self.status)
        validate_ui(self.names)

    def test_every_backend_health_boundary_is_required(self):
        for field in ("enabled", "key_present", "certificate_present", "enrolled", "configuration_present"):
            with self.subTest(field=field):
                payload = copy.deepcopy(self.status)
                payload["secure_boot"][field] = False
                with self.assertRaises(ValueError):
                    validate_status(payload)
        for field, value in (("status", "unknown"), ("enrollment_pending", True)):
            with self.subTest(field=field):
                payload = copy.deepcopy(self.status)
                payload["secure_boot"][field] = value
                with self.assertRaises(ValueError):
                    validate_status(payload)

    def test_old_certificate_and_incomplete_migration_are_rejected(self):
        for field, value in (("purpose", "module-only"), ("purpose", "expired"),
                             ("enrollment", "pending"), ("enrollment", "absent"),
                             ("key_present", False), ("defaults_ready", False)):
            with self.subTest(field=field, value=value):
                payload = copy.deepcopy(self.status)
                payload["secure_boot"]["signing_identity"][field] = value
                with self.assertRaises(ValueError):
                    validate_status(payload)
        self.status["dkms"]["untrusted_modules"] = ["xpadneo"]
        with self.assertRaises(ValueError):
            validate_status(self.status)

    def test_missing_backend_evidence_is_not_a_pass(self):
        with self.assertRaises((ValueError, KeyError)):
            validate_status({})

    def test_own_bootloader_requires_all_four_independent_boundaries(self):
        for architecture in ("x86_64", "aarch64"):
            with self.subTest(architecture=architecture), patch("platform.machine", return_value=architecture):
                self.setUp()
                with self.assertRaises(ValueError):
                    validate_status(self.status, require_bootloader=requires_own_bootloader())
                self.status['secure_boot']['grub'] = dict(installed=True, signature='valid',
                                                          enrollment='enrolled', deployment='ready')
                validate_status(self.status, require_bootloader=requires_own_bootloader())
                for field, value in [('installed', False), ('signature', 'missing'),
                                     ('enrollment', 'pending'), ('deployment', 'pending')]:
                    payload = copy.deepcopy(self.status)
                    payload['secure_boot']['grub'][field] = value
                    with self.subTest(field=field), self.assertRaises(ValueError):
                        validate_status(payload, require_bootloader=requires_own_bootloader())

    def test_own_bootloader_requires_the_visible_sixth_healthy_row(self):
        for architecture in ("x86_64", "aarch64"):
            with self.subTest(architecture=architecture), patch("platform.machine", return_value=architecture):
                self.setUp()
                with self.assertRaises(ValueError):
                    validate_ui(self.names, require_bootloader=requires_own_bootloader())
                names = self.names | {'AnduinOS Bootloader', 'AnduinOS GRUB is signed, trusted and deployed'}
                validate_ui(names, require_bootloader=requires_own_bootloader())
                with self.assertRaises(ValueError):
                    validate_ui(names | {'Repair AnduinOS Bootloader'}, require_bootloader=requires_own_bootloader())

    def test_every_ui_state_is_required(self):
        for text in self.names:
            with self.subTest(text=text), self.assertRaises(ValueError):
                validate_ui(self.names - {text})

    def test_repair_or_use_buttons_fail_even_with_all_healthy_labels(self):
        for action in REPAIR_ACTIONS:
            with self.subTest(action=action), self.assertRaises(ValueError):
                validate_ui(self.names | {action})

    def test_localized_ui_and_trusted_installed_modules(self):
        translate = lambda text: "translated:" + text
        names = {translate(text) for text in self.names}
        validate_ui(names, translate)
        names.remove(translate(ROW_STATES[-1][1]))
        names.add(translate("Drivers are signed and ready to load"))
        validate_ui(names, translate)
        with self.assertRaises(ValueError):
            validate_ui(names | {translate("Repair Module Signatures")}, translate)

    def test_offline_sb_case_and_all_mok_cases_assert_real_first_boot_ui(self):
        matrix = TestMatrix.load(Path(__file__).resolve().parents[1] / "cases/install.json")
        self.assertEqual("123456", matrix.defaults.mok_password)
        offline = next(case for case in matrix.scenarios if case.id == "uefi-sb-offline-btrfs")
        self.assertTrue(offline.mok_enrollment)
        self.assertTrue(offline.firmware.secure_boot)
        self.assertEqual("offline", offline.network.value)
        for case in matrix.scenarios:
            checks = scenario_check_ids(case)
            check = "secure-boot.first-boot-green"
            self.assertEqual(case.mok_enrollment, check in checks)
            if case.mok_enrollment:
                for prerequisite in ("mok-manager-workflow", "installed-boot", "mok-enrollment",
                                     "installed-contracts", "theme.cursor-user-session"):
                    self.assertLess(checks.index(prerequisite), checks.index(check))
