"""Taskbar, AppIndicator, desktop shortcut, and store oracles."""

from unit.support import *  # noqa: F403


class DesktopShellOracleTests(FeatureOracleCase):
    def test_panel_pin_oracle_rejects_missing_session_persistence(self):
        initial_output = self._events(
            {
                "event": "qmp-key",
                "request": "panel-pin-search-open",
                "key": "meta_l",
            },
            {"event": "qmp-text", "request": "panel-pin-search-text"},
            {
                "event": "start-search-result",
                "query": "AnduinOS Panel Acceptance Fixture",
                "accessible_name": "AnduinOS Panel Acceptance Fixture",
                "role": "text",
                "application": "gnome-shell",
                "stable_observations": 4,
            },
            {
                "event": "search-entry-focus",
                "query": "AnduinOS Panel Acceptance Fixture",
                "role": "text",
                "application": "gnome-shell",
                "focused": True,
            },
            {
                "event": "search-result-context",
                "target": "AnduinOS Panel Acceptance Fixture",
                "query": "AnduinOS Panel Acceptance Fixture",
                "application": "gnome-shell",
                "focused": True,
                "method": "search-entry-popup-menu",
            },
            {
                "event": "qmp-key",
                "request": "panel-pin-context",
                "key": "shift-f10",
            },
            *self._context_action_events(
                "taskbar_pin",
                "添加到任务栏",
                "panel-pin-action",
                [
                    "新建窗口",
                    "创建桌面快捷方式",
                    "添加到任务栏",
                    "固定到开始菜单",
                    "应用详细信息",
                ],
                2,
            ),
            {
                "event": "panel-pinned",
                "application": "AnduinOS Panel Acceptance Fixture",
                "menu_label": "添加到任务栏",
                "launcher_name": "AnduinOS Panel Acceptance Fixture",
                "launcher_role": "button",
            },
        )
        persisted_output = self._events(
            {
                "event": "panel-pinned-after-login",
                "application": "AnduinOS Panel Acceptance Fixture",
                "launcher_name": "AnduinOS Panel Acceptance Fixture",
                "launcher_role": "button",
                "visible": True,
            }
        )
        initial = _validate_panel_pin_initial_events(initial_output)
        with self.assertRaisesRegex(TestFailure, "unstable ArcMenu"):
            _validate_panel_pin_initial_events(
                initial_output.replace('"stable_observations": 4', '"stable_observations": 1')
            )
        persisted = _validate_panel_pin_persisted_events(persisted_output)
        _validate_panel_pin_roundtrip(
            initial,
            persisted,
            before_session="2",
            after_session="4",
        )
        with self.assertRaisesRegex(TestFailure, "fresh Shell session"):
            _validate_panel_pin_roundtrip(
                initial,
                persisted,
                before_session="2",
                after_session="2",
            )

    def test_panel_remove_oracle_rejects_an_unlocalized_action(self):
        passing = self._events(
            {
                "event": "qmp-click",
                "request": "panel-remove-context",
                "target": "AnduinOS Panel Acceptance Fixture",
                "button": "right",
            },
            *self._context_action_events(
                "taskbar_unpin",
                "从任务栏中移除",
                "panel-remove-action",
                ["新建窗口", "从任务栏中移除"],
                1,
            ),
            {
                "event": "panel-removed",
                "application": "AnduinOS Panel Acceptance Fixture",
                "localized_label": "从任务栏中移除",
                "launcher_visible": False,
            },
        )
        _validate_panel_remove_events(passing)
        unlocalized = []
        for line in passing.splitlines():
            value = json.loads(line)
            if value.get("accessible_name") == "从任务栏中移除":
                value["accessible_name"] = "Unpin"
            if value.get("localized_label") == "从任务栏中移除":
                value["localized_label"] = "Unpin"
            unlocalized.append(json.dumps(value))
        with self.assertRaisesRegex(TestFailure, "exactly one semantic event"):
            _validate_panel_remove_events("\n".join(unlocalized))

    def test_appindicator_oracle_requires_lower_right_same_process_roundtrip(self):
        process = {
            "pid": 5010,
            "uid": 1000,
            "start_time_ticks": 987654,
            "command": "python3 /usr/local/lib/anduinos-acceptance-shell/indicator_fixture.py",
        }
        window = {
            "accessible_name": "AnduinOS Indicator Fixture Window",
            "role": "frame",
            "application": "python3",
        }
        passing = self._events(
            {
                "event": "appindicator-baseline",
                "window": window,
                "process": process,
                "visible": True,
            },
            {
                "event": "qmp-key",
                "request": "appindicator-close-window",
                "key": "alt-f4",
            },
            {
                "event": "appindicator-hidden",
                "indicator": {
                    "accessible_name": "AnduinOS Acceptance Indicator",
                    "target_name": "AnduinOS Acceptance Indicator",
                    "role": "menu",
                    "application": "gnome-shell",
                    "bounds": [2104, 1392, 48, 48],
                    "screen": [2560, 1440],
                    "lower_right": True,
                },
                "process": process,
                "window_visible": False,
            },
            {
                "event": "spice-double-click",
                "request": "appindicator-restore-window",
                "target": "AnduinOS Acceptance Indicator",
                "button": "left",
                "application": "gnome-shell",
                "clicks": 2,
            },
            {
                "event": "appindicator-restored",
                "window": window,
                "process": process,
                "same_process": True,
                "visible": True,
            },
        )
        value = _validate_appindicator_roundtrip_events(passing)
        self.assertEqual(5010, value["process"]["pid"])
        with self.assertRaisesRegex(TestFailure, "same process"):
            _validate_appindicator_roundtrip_events(
                passing.replace('"start_time_ticks": 987654', '"start_time_ticks": 987655', 1)
            )
        with self.assertRaisesRegex(TestFailure, "lower-right"):
            _validate_appindicator_roundtrip_events(
                passing.replace('"lower_right": true', '"lower_right": false')
            )

        fixture = (ROOT / "fixtures/indicator_fixture.py").read_text(encoding="utf-8")
        self.assertIn("org.kde.StatusNotifierItem", fixture)
        self.assertIn("com.canonical.dbusmenu", fixture)
        self.assertIn("RegisterStatusNotifierItem", fixture)
        self.assertIn('os.environ.setdefault("GDK_DEBUG", "no-portals")', fixture)
        self.assertIn('print("indicator-window=visible", flush=True)', fixture)
        self.assertNotIn("AyatanaAppIndicator", fixture)
        self.assertNotIn("AppIndicator3", fixture)

        runner = _source_tree(ROOT / "business/desktop")
        self.assertIn("--setenv=GDK_DEBUG=no-portals", runner)
        self.assertIn("indicator-window=visible", runner)

    def test_desktop_shortcut_oracle_rejects_an_untrusted_launcher(self):
        passing = self._events(
            {
                "event": "qmp-key",
                "request": "desktop-shortcut-search-open",
                "key": "meta_l",
            },
            {"event": "qmp-text", "request": "desktop-shortcut-search-text"},
            {
                "event": "start-search-result",
                "query": "AnduinOS Panel Acceptance Fixture",
                "accessible_name": "AnduinOS Panel Acceptance Fixture",
                "application": "gnome-shell",
                "stable_observations": 4,
            },
            {
                "event": "search-entry-focus",
                "query": "AnduinOS Panel Acceptance Fixture",
                "role": "text",
                "application": "gnome-shell",
                "focused": True,
            },
            {
                "event": "search-result-context",
                "target": "AnduinOS Panel Acceptance Fixture",
                "query": "AnduinOS Panel Acceptance Fixture",
                "application": "gnome-shell",
                "focused": True,
                "method": "search-entry-popup-menu",
            },
            {
                "event": "qmp-key",
                "request": "desktop-shortcut-context",
                "key": "shift-f10",
            },
            *self._context_pointer_events(
                "desktop_shortcut_create",
                "创建桌面快捷方式",
                "desktop-shortcut-action",
            ),
            {
                "event": "desktop-shortcut-visible",
                "accessible_name": "AnduinOS Panel Acceptance Fixture",
                "role": "label",
                "application": "gjs",
            },
            {
                "event": "desktop-foreground",
                "request": "desktop-shortcut-show-desktop",
                "shortcut_sent": True,
                "blockers_before": [["gnome-control-center", "frame", "设置"]],
                "blockers_after": [],
                "ding_frames": 1,
            },
            {
                "event": "qmp-click",
                "request": "desktop-shortcut-focus",
                "target": "desktop-background",
                "accessible_name": "Desktop Icons 0",
                "role": "frame",
                "application": "gjs",
                "button": "left",
                "x_px": 640.0,
                "y_px": 376.0,
                "bounds": [0, 0, 1280, 752],
            },
            {
                "event": "qmp-text",
                "request": "desktop-shortcut-ding-search-text",
            },
            {
                "event": "qmp-key",
                "request": "desktop-shortcut-ding-search-accept",
                "key": "ret",
            },
            {
                "event": "qmp-key",
                "request": "desktop-shortcut-launch",
                "key": "ret",
            },
            {
                "event": "desktop-shortcut",
                "application": "AnduinOS Panel Acceptance Fixture",
                "localized_label": "创建桌面快捷方式",
                "path": "/home/user/桌面/com.anduinos.AcceptancePanelFixture.desktop",
                "executable": True,
                "trusted": True,
                "visible": True,
                "activation": "ding-keyboard-find",
                "launched_windows": [
                    "AnduinOS Panel Fixture Window",
                ],
            },
        )
        _validate_desktop_shortcut_events(passing)
        with self.assertRaisesRegex(TestFailure, "unstable ArcMenu"):
            _validate_desktop_shortcut_events(
                passing.replace('"stable_observations": 4', '"stable_observations": 1')
            )
        with self.assertRaisesRegex(TestFailure, "exactly one semantic event"):
            _validate_desktop_shortcut_events(
                passing.replace('"trusted": true', '"trusted": false')
            )

        with self.assertRaisesRegex(TestFailure, "exactly one semantic event"):
            _validate_desktop_shortcut_events(
                passing.replace(
                    '"request": "desktop-shortcut-ding-search-text"',
                    '"request": "unrelated-ding-search-text"',
                )
            )

        with self.assertRaisesRegex(TestFailure, "desktop frame"):
            _validate_desktop_shortcut_events(
                passing.replace('"bounds": [0, 0, 1280, 752]', '"bounds": [0, 0, 10, 10]')
            )

    def test_spotify_store_oracle_rejects_an_unrelated_details_page(self):
        passing = self._events(
            {
                "event": "qmp-key",
                "request": "spotify-search-open",
                "key": "meta_l",
            },
            {"event": "qmp-text", "request": "spotify-search-text"},
            {
                "event": "start-search-result",
                "query": "Spotify",
                "accessible_name": "Spotify",
                "role": "text",
                "application": "gnome-shell",
                "stable_observations": 4,
            },
            {
                "event": "search-entry-focus",
                "query": "Spotify",
                "role": "text",
                "application": "gnome-shell",
                "focused": True,
            },
            {
                "event": "qmp-key",
                "request": "spotify-result-activate",
                "key": "ret",
            },
            {
                "event": "spotify-result-activated",
                "accessible_name": "Spotify",
                "role": "text",
                "method": "qmp-keyboard",
            },
            {
                "event": "spotify-store",
                "application": "gnome-software",
                "detail_names": ["Spotify"],
                "visible": True,
            },
        )
        _validate_spotify_store_events(passing)
        with self.assertRaisesRegex(TestFailure, "unstable ArcMenu"):
            _validate_spotify_store_events(
                passing.replace('"stable_observations": 4', '"stable_observations": 1')
            )
        with self.assertRaisesRegex(TestFailure, "real Software details page"):
            _validate_spotify_store_events(
                passing.replace('"application": "gnome-software"', '"application": "firefox"')
            )
