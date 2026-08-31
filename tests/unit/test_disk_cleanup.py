"""Fail-closed acceptance disk cleanup tests."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from framework.disk_cleanup import (
    EXPLICIT_RETENTION_TEXT,
    ActiveTestRunError,
    DiskCleanupError,
    reclaim_orphaned_disks,
    test_results_lease,
)


class DiskCleanupTests(unittest.TestCase):
    def test_reclaims_only_known_disks_and_preserves_evidence(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "test-results"
            case = root / "run" / "case"
            overlay = root / "run" / "feature-overlays" / "suite"
            case.mkdir(parents=True)
            overlay.mkdir(parents=True)
            target = self._disk(case / "target.qcow2", 8192)
            live_media = self._disk(case / "live-media.raw", 4096)
            feature_disk = self._disk(overlay / "overlay.qcow2", 16384)
            evidence = case / "result.json"
            evidence.write_text('{"passed": true}\n', encoding="utf-8")
            unrelated = self._disk(case / "debug.qcow2", 1024)
            misplaced = self._disk(root / "run" / "target.qcow2", 1024)

            with test_results_lease(root):
                report = reclaim_orphaned_disks(root)

            self.assertEqual(report.candidate_count, 3)
            self.assertGreater(report.reclaimed_bytes, 0)
            for disposable in (target, live_media, feature_disk):
                self.assertFalse(disposable.exists())
            self.assertTrue(evidence.exists())
            self.assertTrue(unrelated.exists())
            self.assertTrue(misplaced.exists())
            self.assertTrue(overlay.is_dir())

    def test_make_test_cleans_before_running_unit_and_acceptance_tests(self):
        repository = Path(__file__).resolve().parents[2]
        makefile = (repository / "makefile").read_text(encoding="utf-8")
        recipe = makefile.split("test:\n", 1)[1].split("\nclean:", 1)[0]
        cleanup = "python3 tests/run.py clean-disks --root test-results"
        units = "python3 -m unittest discover"
        acceptance = "python3 tests/run.py --iso"

        self.assertIn(cleanup, recipe)
        self.assertLess(recipe.index(cleanup), recipe.index(units))
        self.assertLess(recipe.index(units), recipe.index(acceptance))

    def test_dry_run_reports_without_removing(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "test-results"
            target = self._disk(root / "run" / "case" / "target.qcow2", 4096)

            with test_results_lease(root):
                report = reclaim_orphaned_disks(root, dry_run=True)

            self.assertTrue(report.dry_run)
            self.assertEqual(report.candidate_count, 1)
            self.assertTrue(target.exists())

    def test_preserves_explicitly_retained_target_but_cleans_overlay(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "test-results"
            case = root / "run" / "case"
            target = self._disk(case / "target.qcow2", 4096)
            (case / "target-disk-retention.txt").write_text(
                f"passed target disk {EXPLICIT_RETENTION_TEXT}\n",
                encoding="utf-8",
            )
            overlay = self._disk(
                root / "run" / "feature-overlays" / "suite" / "overlay.qcow2",
                4096,
            )

            with test_results_lease(root):
                report = reclaim_orphaned_disks(root)

            self.assertTrue(target.exists())
            self.assertIn(target, report.preserved_files)
            self.assertFalse(overlay.exists())

    def test_preserves_every_disk_in_the_excluded_current_run(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "test-results"
            current = root / "current"
            target = self._disk(current / "case" / "target.qcow2", 4096)
            overlay = self._disk(
                current / "feature-overlays" / "suite" / "overlay.qcow2",
                4096,
            )

            with test_results_lease(root):
                report = reclaim_orphaned_disks(
                    root,
                    exclude_roots=(current,),
                )

            self.assertEqual(report.candidate_count, 0)
            self.assertEqual(set(report.preserved_files), {target, overlay})
            self.assertTrue(target.exists())
            self.assertTrue(overlay.exists())

    def test_preserves_symlinked_disk_and_its_target(self):
        with tempfile.TemporaryDirectory() as directory:
            temporary = Path(directory)
            root = temporary / "test-results"
            external = self._disk(temporary / "external.qcow2", 4096)
            candidate = root / "run" / "case" / "target.qcow2"
            candidate.parent.mkdir(parents=True)
            candidate.symlink_to(external)

            with test_results_lease(root):
                report = reclaim_orphaned_disks(root)

            self.assertEqual(report.candidate_count, 0)
            self.assertIn(candidate, report.skipped_paths)
            self.assertTrue(candidate.is_symlink())
            self.assertTrue(external.exists())

    def test_unsafe_retention_note_fails_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            temporary = Path(directory)
            root = temporary / "test-results"
            case = root / "run" / "case"
            target = self._disk(case / "target.qcow2", 4096)
            external = temporary / "retention.txt"
            external.write_text("not retained\n", encoding="utf-8")
            note = case / "target-disk-retention.txt"
            note.symlink_to(external)

            with test_results_lease(root):
                report = reclaim_orphaned_disks(root)

            self.assertEqual(report.candidate_count, 0)
            self.assertIn(note, report.skipped_paths)
            self.assertIn(target, report.preserved_files)
            self.assertTrue(target.exists())

    def test_exclusive_lease_rejects_concurrent_cleanup(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "test-results"
            with test_results_lease(root), self.assertRaises(ActiveTestRunError):
                with test_results_lease(root):
                    self.fail("a second lease must never be granted")

    def test_rejects_symlinked_result_root(self):
        with tempfile.TemporaryDirectory() as directory:
            temporary = Path(directory)
            actual = temporary / "actual"
            actual.mkdir()
            root = temporary / "test-results"
            root.symlink_to(actual, target_is_directory=True)
            with self.assertRaises(DiskCleanupError):
                with test_results_lease(root):
                    self.fail("a symlinked root must never be leased")

    @staticmethod
    def _disk(path: Path, size: int) -> Path:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("wb") as stream:
            stream.write(b"x" * size)
        return path


if __name__ == "__main__":
    unittest.main()
