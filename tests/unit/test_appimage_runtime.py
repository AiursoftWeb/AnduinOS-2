"""AppImage compatibility fixtures follow the current upstream runtime."""

import io
import tempfile
import unittest
import urllib.error
from pathlib import Path
from unittest.mock import patch

from fixtures.builder import _download_runtime
from framework.errors import ConfigurationError


class AppImageRuntimeTests(unittest.TestCase):
    def test_upstream_updates_replace_previous_runtime_without_a_hash_gate(self):
        for name in ("runtime-x86_64", "runtime-aarch64"):
            with self.subTest(name=name), tempfile.TemporaryDirectory() as directory:
                destination = Path(directory) / name
                for content in (b"first upstream runtime", b"updated upstream runtime"):
                    with patch("fixtures.builder.urllib.request.urlopen",
                               return_value=io.BytesIO(content)) as download:
                        _download_runtime(name, destination)
                    self.assertEqual(destination.read_bytes(), content)
                    self.assertTrue(download.call_args.args[0].endswith("/" + name))

    def test_download_failure_is_reported_instead_of_using_stale_runtime(self):
        with tempfile.TemporaryDirectory() as directory:
            destination = Path(directory) / "runtime-x86_64"
            destination.write_bytes(b"old runtime")
            with patch("fixtures.builder.urllib.request.urlopen",
                       side_effect=urllib.error.URLError("unavailable")):
                with self.assertRaisesRegex(ConfigurationError, "Cannot download"):
                    _download_runtime("runtime-x86_64", destination)
