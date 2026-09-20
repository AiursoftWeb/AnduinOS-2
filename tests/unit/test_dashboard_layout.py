"""Responsive layout and aggregate presentation, without starting any VM."""

import copy
import io
import os
from pathlib import Path
import unittest
from unittest.mock import patch

from framework.dashboard import AcceptanceDashboard
from framework.dashboard_render import case_state, display_width, render_dashboard


def sample_dashboard():
    ids = ("bios-offline-btrfs", "bios-online-btrfs", "bios-online-ext4",
           "uefi-nosb-offline-btrfs", "uefi-nosb-online-btrfs-ssh-enabled",
           "uefi-nosb-online-btrfs-ssh-toggle", "uefi-nosb-online-btrfs-japanese-live-chinese-installed",
           "uefi-nosb-offline-ext4", "uefi-nosb-wifi-btrfs", "uefi-sb-offline-btrfs",
           "uefi-sb-online-btrfs", "uefi-sb-online-ext4", "uefi-nosb-offline-manual-small-disk")
    suite_names = ("input-and-appearance", "file-integration", "accounts-gdm", "desktop-theme",
                   "shell-shortcuts", "shell-start-menu", "shell-panel-taskbar",
                   "shell-desktop-shortcut", "shell-spotify-store", "public-ecosystem", "public-ghex")
    suites = {name: (name + ".check",) for name in suite_names}
    suites["desktop-theme"] = ("appearance.theme-menu-localized", "appearance.theme-gtk",
                               "appearance.theme-qt", "appearance.theme-firefox")
    dashboard = AcceptanceDashboard(
        ids, iso=Path("AnduinOS-2.0.3-2609190323-amd64.iso"), architecture="amd64",
        artifacts=Path("/home/anduin/Source/Repos/Aiursoft/bash-app/AnduinOS-2/test-results/example"),
        checks={name: ("live-boot", "installed-boot") for name in ids},
        suites={ids[1]: suites, ids[4]: {f"recovery-{i}": (f"reset-{i}",) for i in range(6)}},
        stream=io.StringIO(), live=False,
    )
    dashboard.color = False
    dashboard.complete(ids[0], "passed", 242)
    dashboard.complete(ids[1], "passed", 303)
    for suite in suite_names[:3]:
        dashboard.suite_check(ids[1], suite, suite + ".check", "passed")
        dashboard.complete_suite(ids[1], suite, "passed", 40)
    dashboard.begin_suite(ids[1], "desktop-theme")
    for check in suites["desktop-theme"][:3]:
        dashboard.suite_check(ids[1], "desktop-theme", check, "passed")
    dashboard.suite_check(ids[1], "desktop-theme", suites["desktop-theme"][-1], "running",
                          "Checking Firefox theme")
    return dashboard


class DashboardLayoutTests(unittest.TestCase):
    def test_wide_layout_has_cases_left_suites_and_checks_right(self):
        dashboard = sample_dashboard()
        frame = render_dashboard(dashboard, os.terminal_size((150, 40)))
        lines = frame.splitlines()
        heading = next(line for line in lines if "Installation cases" in line)
        self.assertIn("Feature suites — bios-online-btrfs", heading)
        divider = heading.index("│", 1)
        check_heading = next(line for line in lines if "Checks — desktop-theme" in line)
        self.assertGreater(check_heading.index("Checks —"), divider)
        self.assertIn("▶ ● bios-online-btrfs", frame)
        self.assertIn("TESTING · Install OK · Suites 3/11", frame)
        self.assertIn("✓ bios-offline-btrfs", frame)
        self.assertIn("ALL PASSED · Install OK · Suites —", frame)
        self.assertIn("QUEUED", frame)
        self.assertNotIn("Waiting for installation base", frame)
        self.assertIn("RUNNING 3/4", frame)
        self.assertIn("appearance.theme-firefox", frame)
        self.assertIn("5/30 · ✓ 5 · ✗ 0", frame)
        self.assertIn("Elapsed", lines[-3])
        self.assertIn("Artifacts:", lines[-2])

    def test_installation_pass_does_not_pass_pending_or_failed_suites(self):
        dashboard = sample_dashboard()
        case = dashboard.cases["uefi-nosb-online-btrfs-ssh-enabled"]
        self.assertEqual("pending", case_state(case))
        dashboard.begin(case.identifier)
        self.assertEqual("running", case_state(case))
        dashboard.complete(case.identifier, "passed", 1)
        self.assertEqual("running", case_state(case))
        suites = tuple(case.suites)
        for suite in suites[:-1]:
            dashboard.complete_suite(case.identifier, suite, "passed", 1)
            self.assertEqual("running", case_state(case))
        dashboard.complete_suite(case.identifier, suites[-1], "failed", 1, "recovery failed")
        self.assertEqual("failed", case_state(case))
        # Reporting APIs keep the independent installation and suite verdicts.
        self.assertEqual("passed", dashboard.case_result(case.identifier)["status"])
        self.assertEqual("failed", dashboard.suite_results(case.identifier)[-1]["status"])

    def test_case_turns_green_only_after_all_assigned_suites_pass(self):
        dashboard = sample_dashboard()
        case = dashboard.cases["bios-online-btrfs"]
        for name in tuple(case.suites)[3:]:
            dashboard.complete_suite(case.identifier, name, "passed", 1)
        self.assertEqual("passed", case_state(case))
        dashboard.color = True
        frame = render_dashboard(dashboard, os.terminal_size((150, 40)))
        row = next(line for line in frame.splitlines() if "▶ ✓ bios-online-btrfs" in line)
        self.assertIn("\x1b[1;32m", row)
        self.assertIn("ALL PASSED · Install OK · Suites 11/11", frame)

    def test_running_case_is_highlighted_cyan_and_failed_suite_makes_it_red(self):
        dashboard = sample_dashboard()
        dashboard.color = True
        frame = render_dashboard(dashboard, os.terminal_size((150, 40)))
        row = next(line for line in frame.splitlines() if "▶ ● bios-online-btrfs" in line)
        self.assertIn("\x1b[1;36m\x1b[7m", row)
        dashboard.complete_suite("bios-online-btrfs", "desktop-theme", "failed", 1, "bad theme")
        frame = render_dashboard(dashboard, os.terminal_size((150, 40)))
        row = next(line for line in frame.splitlines() if "▶ ✗ bios-online-btrfs" in line)
        self.assertIn("\x1b[1;31m\x1b[7m", row)
        self.assertIn("FAILED · Install OK · Suites 3/11", frame)

    def test_installing_case_shows_installation_checks(self):
        dashboard = sample_dashboard()
        dashboard.begin("bios-online-ext4")
        dashboard.check("bios-online-ext4", "installed-boot", "running", "Booting installed system")
        frame = render_dashboard(dashboard, os.terminal_size((150, 40)))
        self.assertIn("Checks — bios-online-ext4", frame)
        self.assertIn("installed-boot", frame)
        self.assertIn("No feature suites assigned", frame)
        self.assertIn("INSTALLING", frame)
        self.assertNotIn("appearance.theme-firefox", frame)

    def test_resize_stacks_panels_and_keeps_the_current_check_visible(self):
        dashboard = sample_dashboard()
        for columns in (72, 80, 110, 119, 120, 150, 180):
            with self.subTest(columns=columns):
                frame = render_dashboard(dashboard, os.terminal_size((columns, 30)))
                self.assertEqual(columns >= 120, "┬" in frame)
                self.assertIn("appearance.theme-firefox", frame)
                self.assertIn("▶ ● bios-online-btrfs", frame)
                if columns < 120:
                    self.assertLess(frame.index("Installation cases"), frame.index("Feature suites"))
                    self.assertLess(frame.index("Feature suites"), frame.index("Checks —"))

    def test_frames_fit_terminal_including_colors_and_unicode(self):
        dashboard = sample_dashboard()
        dashboard.suite_check("bios-online-btrfs", "desktop-theme", "appearance.theme-firefox",
                              "running", "检查主题：正确 e\u0301 · 窗口\nnew line\x1b[2J")
        for color in (False, True):
            dashboard.color = color
            for columns in (30, 40, 72, 80, 119, 120, 150, 180, 220):
                for height in (12, 18, 20, 24, 30, 43):
                    with self.subTest(color=color, columns=columns, height=height):
                        frame = render_dashboard(dashboard, os.terminal_size((columns, height)))
                        self.assertLessEqual(len(frame.splitlines()), height - 1)
                        for line in frame.splitlines():
                            self.assertLessEqual(display_width(line), columns)
                            if columns >= 40 and height >= 18:
                                self.assertEqual(display_width(line), min(180, columns))
                        self.assertNotIn("\x1b[2J", frame)

    def test_rendering_leaves_execution_and_report_state_unchanged(self):
        dashboard = sample_dashboard()
        before = copy.deepcopy(dashboard.cases)
        reports = [dashboard.case_result(name) for name in dashboard.cases]
        for columns in (40, 80, 150):
            render_dashboard(dashboard, os.terminal_size((columns, 30)))
        self.assertEqual(before, dashboard.cases)
        self.assertEqual(reports, [dashboard.case_result(name) for name in dashboard.cases])

    def test_scrolling_keeps_late_cases_suites_and_checks_in_view(self):
        dashboard = sample_dashboard()
        last = tuple(dashboard.cases)[-1]
        dashboard.begin(last)
        dashboard.check(last, "installed-boot", "running", "Checking the last installation")
        frame = render_dashboard(dashboard, os.terminal_size((80, 24)))
        self.assertIn("▶ ● " + last, frame)
        self.assertIn("Showing 13-13/13", frame)
        self.assertIn("installed-boot", frame)
        dashboard.begin_suite("bios-online-btrfs", "public-ghex")
        dashboard.suite_check("bios-online-btrfs", "public-ghex", "public-ghex.check", "running")
        frame = render_dashboard(dashboard, os.terminal_size((80, 24)))
        self.assertIn("showing 10-11", frame)
        self.assertIn("Checks — public-ghex", frame)
        self.assertIn("public-ghex.check", frame)

    def test_suite_failure_before_checks_still_displays_the_cause(self):
        dashboard = sample_dashboard()
        dashboard.begin_suite("bios-online-btrfs", "public-ghex")
        dashboard.complete_suite("bios-online-btrfs", "public-ghex", "failed", 1, "Cannot boot overlay")
        frame = render_dashboard(dashboard, os.terminal_size((80, 24)))
        self.assertIn("FAILED: Cannot boot overlay", frame)
        self.assertIn("▶ ✗ bios-online-btrfs", frame)

    def test_live_render_uses_current_terminal_size_each_time(self):
        dashboard = sample_dashboard()
        for columns in (150, 80, 150):
            with patch("framework.dashboard.shutil.get_terminal_size",
                       return_value=os.terminal_size((columns, 30))):
                dashboard.stream.seek(0)
                dashboard.stream.truncate()
                dashboard._render_locked()
                output = dashboard.stream.getvalue()
                self.assertTrue(output.startswith("\x1b[2J\x1b[H"))
                self.assertEqual(columns >= 120, "┬" in output)

    def test_no_active_case_and_no_cases_are_renderable(self):
        dashboard = AcceptanceDashboard((), iso=Path("test.iso"), architecture="amd64",
                                        artifacts=Path("test-results"), stream=io.StringIO(), live=False)
        frame = render_dashboard(dashboard, os.terminal_size((150, 30)))
        self.assertIn("Waiting for an installation case", frame)
        self.assertIn("0/0", frame)
