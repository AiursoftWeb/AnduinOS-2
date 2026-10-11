"""Execute the guest extension-state gate with isolated GNOME CLI fixtures."""

import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

from business.install.desktop import _gnome_extension_policy_script


class ExtensionPolicyTests(unittest.TestCase):
    def _run_gate(self, *, desktop="ACTIVE", unlock="INITIALIZED",
                  enabled=True, modes=None, missing=False, optional="INACTIVE",
                  malformed=False):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            extensions = root / "extensions"
            extensions.mkdir()
            optional_ids = ("simple-weather@romanlefler.com",
                            "network-stats@gnome.noroadsleft.xyz")
            states = {"desktop@example.com": desktop,
                      "unlock-theme@anduinos.com": unlock,
                      **dict.fromkeys(optional_ids, optional)}
            for uuid in states:
                folder = extensions / uuid
                folder.mkdir()
                metadata = {"uuid": uuid}
                if uuid == "unlock-theme@anduinos.com":
                    metadata["session-modes"] = modes if modes is not None else ["unlock-dialog"]
                (folder / "metadata.json").write_text(json.dumps(metadata))
            if malformed:
                (extensions / "unlock-theme@anduinos.com/metadata.json").write_text("{")
            configured = [uuid for uuid in states if uuid not in optional_ids]
            if missing:
                configured.remove("unlock-theme@anduinos.com")
            commands = root / "bin"
            commands.mkdir()
            for name, body in {
                "gsettings": "import os\nprint(os.environ['CONFIGURED'])\n",
                "gnome-extensions": (
                    "import json, os, sys\n"
                    "uuid = sys.argv[2]\n"
                    "states = json.loads(os.environ['STATES'])\n"
                    "enabled = uuid not in json.loads(os.environ['DISABLED'])\n"
                    "print(uuid)\n"
                    "print('  Enabled: ' + ('Yes' if enabled else 'No'))\n"
                    "print('  State: ' + states[uuid])\n"
                ),
            }.items():
                command = commands / name
                command.write_text("#!/usr/bin/python3\n" + body)
                command.chmod(0o755)
            disabled = [*optional_ids, *([] if enabled else ["unlock-theme@anduinos.com"])]
            return subprocess.run(
                ["bash", "-c", _gnome_extension_policy_script(extensions, root)],
                env={**os.environ, "PATH": f"{commands}:{os.environ['PATH']}",
                     "CONFIGURED": repr(configured), "STATES": json.dumps(states),
                     "DISABLED": json.dumps(disabled)},
                capture_output=True, text=True, timeout=10,
            )

    def test_lock_only_extension_may_wait_or_be_inactive_after_unlock(self):
        for state in ("INITIALIZED", "INACTIVE"):
            with self.subTest(state=state):
                result = self._run_gate(unlock=state)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_desktop_extensions_still_have_to_be_active(self):
        for state in ("INITIALIZED", "INACTIVE", "ERROR", "OUT OF DATE"):
            with self.subTest(state=state):
                self.assertNotEqual(self._run_gate(desktop=state).returncode, 0)

    def test_lock_only_exception_never_accepts_errors_or_desktop_activation(self):
        for state in ("ERROR", "OUT OF DATE", "DISABLED", "UNINSTALLED", "ACTIVE"):
            with self.subTest(state=state):
                self.assertNotEqual(self._run_gate(unlock=state).returncode, 0)

    def test_lock_only_extension_must_remain_enabled_and_configured(self):
        self.assertNotEqual(self._run_gate(enabled=False).returncode, 0)
        self.assertNotEqual(self._run_gate(missing=True).returncode, 0)

    def test_session_modes_not_uuid_determine_the_expected_state(self):
        result = self._run_gate(modes=["user", "unlock-dialog"], unlock="ACTIVE")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertNotEqual(self._run_gate(modes=["user", "unlock-dialog"]).returncode, 0)

    def test_malformed_metadata_fails_closed(self):
        self.assertNotEqual(self._run_gate(malformed=True).returncode, 0)
        self.assertNotEqual(self._run_gate(modes="unlock-dialog").returncode, 0)

    def test_optional_extensions_still_must_not_be_active(self):
        self.assertNotEqual(self._run_gate(optional="ACTIVE").returncode, 0)
