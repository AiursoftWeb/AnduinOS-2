import json
import re
import unittest
from pathlib import Path


ROOT = Path(__file__).parent


class ArchitectureCoveragePlanTests(unittest.TestCase):
    def setUp(self):
        self.plan = json.loads(
            (ROOT / "coverage-plan.json").read_text(encoding="utf-8")
        )

    def test_plan_has_a_closed_valid_shape(self):
        self.assertEqual(
            set(self.plan),
            {
                "schema_version",
                "kind",
                "profiles",
                "requirements",
                "suites",
            },
        )
        self.assertEqual(self.plan["schema_version"], 1)
        self.assertEqual(self.plan["kind"], "architecture-coverage-plan")
        profiles = self.plan["profiles"]
        self.assertEqual(len(profiles), len(set(profiles)))
        self.assertEqual(
            set(profiles),
            {
                "unit",
                "install",
                "release-gate",
                "nightly-online",
                "platform-lab",
            },
        )

        suite_ids = []
        check_ids = []
        for suite in self.plan["suites"]:
            self.assertEqual(
                set(suite),
                {
                    "id",
                    "profiles",
                    "source",
                    "isolation",
                    "observation_modes",
                    "checks",
                },
            )
            suite_ids.append(suite["id"])
            self.assertTrue(suite["source"])
            self.assertTrue(suite["checks"])
            self.assertLessEqual(set(suite["profiles"]), set(profiles))
            self.assertIn(
                suite["isolation"],
                {"per-check", "overlay", "fresh-install", "platform"},
            )
            self.assertLessEqual(
                set(suite["observation_modes"]),
                {"passive", "controlled", "platform"},
            )
            check_ids.extend(suite["checks"])

        self.assertEqual(len(suite_ids), len(set(suite_ids)))
        self.assertEqual(len(check_ids), len(set(check_ids)))
        self.assertEqual(len(check_ids), 60)
        self.assertTrue(all("." in identifier for identifier in check_ids))

        requirement_ids = []
        referenced_checks = []
        for requirement in self.plan["requirements"]:
            self.assertEqual(set(requirement), {"id", "summary", "checks"})
            requirement_ids.append(requirement["id"])
            self.assertTrue(requirement["summary"])
            self.assertTrue(requirement["checks"])
            self.assertLessEqual(set(requirement["checks"]), set(check_ids))
            referenced_checks.extend(requirement["checks"])
        self.assertEqual(
            requirement_ids,
            [f"R{number:02d}" for number in range(1, 46)],
        )
        self.assertEqual(set(referenced_checks), set(check_ids))

    def test_architecture_document_and_plan_have_the_same_checks(self):
        document = (ROOT / "ARCHITECTURE.md").read_text(encoding="utf-8")
        documented = {
            identifier
            for identifier in re.findall(
                r"^\| `([a-z0-9][a-z0-9.-]+)` \|", document, re.MULTILINE
            )
            if "." in identifier
        }
        planned = {
            identifier
            for suite in self.plan["suites"]
            for identifier in suite["checks"]
        }
        self.assertEqual(documented, planned)

    def test_public_and_platform_checks_cannot_enter_release_gate(self):
        suites = {suite["id"]: suite for suite in self.plan["suites"]}
        self.assertEqual(
            suites["public-ecosystem"]["profiles"], ["nightly-online"]
        )
        self.assertEqual(
            suites["platform-host-integration"]["profiles"],
            ["platform-lab"],
        )
        for identifier in (
            "login-installation-policy",
            "wifi-installation-policy",
        ):
            self.assertEqual(suites[identifier]["isolation"], "fresh-install")


if __name__ == "__main__":
    unittest.main()
