"""Session shortcut, localization, file, and appearance oracles."""

from unit.support import *  # noqa: F403


class DesktopSessionOracleTests(FeatureOracleCase):
    def test_alt_tab_oracle_rejects_unchanged_focus(self):
        passing = self._events(
            {
                "event": "shortcut-focus",
                "shortcut": "alt-tab",
                "phase": "before",
                "window": "AnduinOS Shortcut Window Beta",
            },
            {
                "event": "qmp-key",
                "request": "shortcut-alt-tab-forward",
                "key": "alt-tab",
            },
            {
                "event": "shortcut-focus",
                "shortcut": "alt-tab",
                "phase": "after",
                "window": "AnduinOS Shortcut Window Alpha",
            },
            {
                "event": "qmp-key",
                "request": "shortcut-alt-tab-restore",
                "key": "alt-tab",
            },
            {
                "event": "shortcut-focus",
                "shortcut": "alt-tab",
                "phase": "restored",
                "window": "AnduinOS Shortcut Window Beta",
            },
        )
        _validate_alt_tab_events(passing)
        with self.assertRaisesRegex(TestFailure, "both fixed fixture windows"):
            _validate_alt_tab_events(
                passing.replace(
                    "AnduinOS Shortcut Window Alpha",
                    "AnduinOS Shortcut Window Beta",
                )
            )

    def test_super_tab_oracle_rejects_missing_overview(self):
        passing = self._events(
            {"event": "overview", "phase": "before", "visible": False},
            {
                "event": "qmp-key",
                "request": "shortcut-super-tab-show",
                "key": "meta_l-tab",
            },
            {
                "event": "overview",
                "phase": "shown",
                "visible": True,
                "nodes": [["panel", "概览"]],
            },
            {
                "event": "qmp-key",
                "request": "shortcut-super-tab-hide",
                "key": "meta_l-tab",
            },
            {"event": "overview", "phase": "restored", "visible": False},
        )
        _validate_super_tab_events(passing)
        lines = passing.splitlines()
        shown = json.loads(lines[2])
        shown["nodes"] = []
        lines[2] = json.dumps(shown)
        with self.assertRaisesRegex(TestFailure, "semantic Overview"):
            _validate_super_tab_events("\n".join(lines))

    def test_initial_overview_oracle_rejects_visible_or_unproven_absence(self):
        passing = self._events(
            {
                "event": "initial-overview",
                "phase": "post-login",
                "visible": False,
                "stable_observations": 8,
                "overview_nodes": [],
                "shell_ready_markers": [["push button", "ArcMenu"]],
            }
        )
        _validate_initial_overview_events(passing)
        for mutation, message in (
            ({"visible": True}, "visible automatically"),
            ({"shell_ready_markers": []}, "before GNOME Shell"),
            ({"stable_observations": 1}, "eight observations"),
        ):
            value = json.loads(passing)
            value.update(mutation)
            with self.assertRaisesRegex(TestFailure, message):
                _validate_initial_overview_events(json.dumps(value))

    def test_initial_overview_guest_probe_is_observation_only(self):
        source = _source_tree(ROOT / "assertions/guest/ui")
        body = source.split("def assert_initial_overview_hidden", 1)[1].split(
            "def exercise_super_tab", 1
        )[0]
        self.assertIn('_wait_shell_named("start_button", True', body)
        self.assertIn("_overview_nodes()", body)
        self.assertNotIn("dismiss_initial_setup", body)
        self.assertNotIn('event("qmp-key"', body)

    def test_default_desktop_icon_oracle_rejects_incomplete_or_fake_icons(self):
        passing = self._events(
            {
                "event": "desktop-default-icons",
                "stable_observations": 4,
                "icons": [
                    {
                        "name": "主目录",
                        "role": "label",
                        "application": "gjs",
                        "bounds": [48, 40, 64, 22],
                    },
                    {
                        "name": "回收站",
                        "role": "label",
                        "application": "gjs",
                        "bounds": [48, 152, 64, 22],
                    },
                ],
                "desktop_frame": {
                    "name": "Desktop Icons 1",
                    "role": "frame",
                    "application": "gjs",
                    "bounds": [0, 0, 1280, 752],
                },
            }
        )
        _validate_desktop_icon_events(passing)
        mutations = (
            (lambda value: value["icons"].pop(), "incomplete"),
            (lambda value: value["icons"][0].update(application="gnome-shell"), "DING"),
            (lambda value: value.update(stable_observations=1), "four observations"),
            (lambda value: value["desktop_frame"].update(role="panel"), "desktop frame"),
        )
        for mutate, message in mutations:
            value = json.loads(passing)
            mutate(value)
            with self.assertRaisesRegex(TestFailure, message):
                _validate_desktop_icon_events(json.dumps(value, ensure_ascii=False))

    def test_desktop_terminal_oracle_rejects_wrong_target_or_application(self):
        passing = self._events(
            {
                "event": "desktop-foreground",
                "request": "desktop-terminal-show-desktop",
                "shortcut_sent": True,
                "blockers_before": [["gnome-control-center", "frame", "设置"]],
                "blockers_after": [],
                "ding_frames": 1,
            },
            {
                "event": "qmp-click",
                "request": "desktop-background-context",
                "target": "desktop-background",
                "button": "right",
                "role": "frame",
                "application": "gjs",
                "bounds": [0, 0, 1280, 752],
            },
            {
                "event": "desktop-context-menu-plan",
                "target": "desktop_open_terminal",
                "package": "gnome-shell-extension-desktop-icons-ng-anduinos",
                "package_version": "2.0.2-2+resolute",
                "source": "/usr/share/gnome-shell/extensions/ding@rastersoft.com/app/desktopMenu.js",
                "action_tail": [
                    "open-in-terminal-desktop",
                    "change-background",
                    "show-settings",
                    "display-settings",
                ],
                "focus_origin": "first-menu-row",
                "up_presses": 4,
                "atspi_rows_exposed": False,
            },
            {
                "event": "qmp-key",
                "request": "desktop-terminal-menu-up-1",
                "key": "up",
            },
            {
                "event": "qmp-key",
                "request": "desktop-terminal-menu-up-2",
                "key": "up",
            },
            {
                "event": "qmp-key",
                "request": "desktop-terminal-menu-up-3",
                "key": "up",
            },
            {
                "event": "qmp-key",
                "request": "desktop-terminal-menu-up-4",
                "key": "up",
            },
            {
                "event": "qmp-key",
                "request": "desktop-terminal-menu-activate",
                "key": "ret",
            },
            {
                "event": "desktop-terminal",
                "phase": "opened",
                "visible": True,
                "application": "ptyxis",
                "windows": [["ptyxis", "frame", "Desktop"]],
                "directory": "/home/anduinostest/Desktop",
                "observed_cwds": ["/home/anduinostest/Desktop"],
                "activation": "desktop-context-menu-versioned-keyboard",
            },
            {
                "event": "qmp-key",
                "request": "desktop-terminal-close",
                "key": "alt-f4",
            },
            {
                "event": "desktop-terminal",
                "phase": "closed",
                "visible": False,
            },
        )
        _validate_desktop_terminal_events(passing)
        mutations = (
            (1, "target", "主目录", "exactly one semantic event"),
            (1, "application", "gnome-shell", "target DING"),
            (2, "package_version", "2.0.2-3+resolute", "unvalidated DING"),
            (3, "key", "down", "exactly one semantic event"),
            (8, "application", "org.gnome.Nautilus", "open Ptyxis"),
            (8, "observed_cwds", [], "open Ptyxis"),
        )
        for index, key, replacement, message in mutations:
            values = [json.loads(line) for line in passing.splitlines()]
            values[index][key] = replacement
            output = "\n".join(json.dumps(value) for value in values)
            with self.assertRaisesRegex(TestFailure, message):
                _validate_desktop_terminal_events(output)

    def test_desktop_background_probe_uses_ding_frame_not_fixed_coordinates(self):
        source = _source_tree(ROOT / "assertions/guest/ui")
        body = source.split("def exercise_desktop_terminal", 1)[1].split(
            "def exercise_desktop_shortcut", 1
        )[0]
        self.assertIn("frames = _desktop_frames()", body)
        self.assertIn(
            '_ensure_desktop_foreground("desktop-terminal-show-desktop")',
            body,
        )
        self.assertIn("request_node_click(", body)
        self.assertIn('semantic_target="desktop-background"', body)
        self.assertNotRegex(body, r"x_px\s*=|y_px\s*=")

    def test_desktop_shortcut_probe_avoids_ding_broken_label_coordinates(self):
        source = _source_tree(ROOT / "assertions/guest/ui")
        wait_body = source.split("def _wait_desktop_fixture_node", 1)[1].split(
            "def _desktop_frames", 1
        )[0]
        shortcut_body = source.split("def exercise_desktop_shortcut", 1)[1].split(
            "def exercise_spotify_store", 1
        )[0]
        self.assertIn('owning_application(item) == "gjs"', wait_body)
        self.assertIn('role(item) == "label"', wait_body)
        self.assertIn('"desktop-shortcut-visible"', shortcut_body)
        self.assertIn("frames = _desktop_frames()", shortcut_body)
        self.assertIn('"desktop-shortcut-ding-search-text"', shortcut_body)
        self.assertIn('activation="ding-keyboard-find"', shortcut_body)
        self.assertNotIn("request_node_double_click(", shortcut_body)
        self.assertNotIn("get_parent()", shortcut_body)

    def test_super_i_oracle_rejects_an_unrelated_window(self):
        passing = self._events(
            {
                "event": "qmp-key",
                "request": "shortcut-super-i",
                "key": "meta_l-i",
            },
            {
                "event": "shortcut-window",
                "shortcut": "super-i",
                "application": "gnome-control-center",
                "window": "设置",
                "focused": True,
            },
        )
        _validate_super_i_events(passing)
        with self.assertRaisesRegex(TestFailure, "unrelated application"):
            _validate_super_i_events(passing.replace("gnome-control-center", "firefox"))

    def test_super_u_oracle_rejects_a_non_restored_extension(self):
        passing = self._events(
            {
                "event": "network-stats",
                "phase": "before",
                "state": "INITIALIZED",
                "visible": False,
            },
            {
                "event": "qmp-key",
                "request": "shortcut-super-u-show",
                "key": "meta_l-u",
            },
            {
                "event": "network-stats",
                "phase": "shown",
                "state": "ACTIVE",
                "visible": True,
                "nodes": [["label", "↑ 1 KB/s"]],
            },
            {
                "event": "qmp-key",
                "request": "shortcut-super-u-hide",
                "key": "meta_l-u",
            },
            {
                "event": "network-stats",
                "phase": "restored",
                "state": "INACTIVE",
                "visible": False,
            },
        )
        _validate_super_u_events(passing)
        lines = passing.splitlines()
        lines[-1] = lines[-1].replace("INACTIVE", "ACTIVE")
        with self.assertRaisesRegex(TestFailure, "restore Network Stats"):
            _validate_super_u_events("\n".join(lines))

    def test_screenshot_shortcut_oracle_rejects_a_fake_png(self):
        passing = self._events(
            {
                "event": "qmp-key",
                "request": "shortcut-screenshot-open",
                "key": "meta_l-shift-s",
            },
            {
                "event": "screenshot-ui",
                "visible": True,
                "modes": ["选区", "屏幕", "窗口"],
                "completion": "focused-default-action",
            },
            {
                "event": "qmp-key",
                "request": "shortcut-screenshot-capture",
                "key": "ret",
            },
            {
                "event": "screenshot-created",
                "path": "/home/user/Pictures/Screenshot.png",
                "size": 4096,
                "png_signature": True,
            },
        )
        result = _validate_screenshot_shortcut_events(passing)
        self.assertEqual("/home/user/Pictures/Screenshot.png", result["path"])
        missing_mode = passing.replace(
            '["\\u9009\\u533a", "\\u5c4f\\u5e55", "\\u7a97\\u53e3"]',
            '["\\u9009\\u533a", "\\u5c4f\\u5e55"]',
        )
        with self.assertRaisesRegex(TestFailure, "all three modes"):
            _validate_screenshot_shortcut_events(missing_mode)
        with self.assertRaisesRegex(TestFailure, "png_signature=True"):
            _validate_screenshot_shortcut_events(
                passing.replace('"png_signature": true', '"png_signature": false')
            )

    def test_start_button_oracle_rejects_a_non_anduinos_render(self):
        asset = (
            "/usr/share/gnome-shell/extensions/arcmenu@arcmenu.com/icons/"
            "anduinos-logo.svg"
        )
        digest = "a" * 64
        passing = self._events(
            {
                "event": "start-button",
                "accessible_name": "显示应用",
                "role": "toggle button",
                "bounds": [10, 10, 30, 30],
                "bounds_usable": True,
                "asset": asset,
                "asset_sha256": digest,
                "rendered_template": "/tmp/start-button-installed-logo.png",
                "rendered_size": [20, 20],
            },
            {
                "event": "qmp-key",
                "request": "start-button-open",
                "key": "meta_l",
            },
            {
                "event": "start-menu",
                "phase": "shown",
                "markers": ["已固定", "所有应用程序"],
                "marker_roles": ["label"],
                "overview_visible": False,
            },
            {
                "event": "qmp-key",
                "request": "start-button-close",
                "key": "esc",
            },
            {"event": "start-menu", "phase": "restored", "visible": False},
        )
        event = _validate_start_button_events(passing)
        _validate_start_button_contract(
            "\n".join(
                (
                    f"menu-button-icon='{asset}'",
                    f"custom-menu-button-icon='{asset}'",
                    "menu-button-icon-size=34",
                    f"{digest}  {asset}",
                )
            ),
            event,
        )
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            template = Image.new("RGBA", (20, 20), (0, 0, 0, 0))
            draw = ImageDraw.Draw(template)
            draw.rectangle((5, 2, 14, 17), fill=(62, 141, 245, 255))
            draw.rectangle((2, 6, 17, 13), fill=(53, 124, 244, 255))
            template_path = root / "logo.png"
            template.save(template_path)
            good = Image.new("RGB", (80, 100), (28, 28, 32))
            good.paste(template, (15, 15), template)
            good.paste(template, (30, 72), template)
            good_path = root / "good.png"
            good.save(good_path)
            assert_start_button_logo(
                good_path,
                template_path,
                [10, 10, 30, 30],
                root / "good.json",
            )
            assert_start_button_logo(
                good_path,
                template_path,
                [0, 0, 0, 0],
                root / "good-fallback.json",
            )
            bad = Image.new("RGB", (80, 100), (28, 28, 32))
            ImageDraw.Draw(bad).rectangle((15, 15, 34, 34), fill=(220, 40, 40))
            bad_path = root / "bad.png"
            bad.save(bad_path)
            with self.assertRaisesRegex(
                TestFailure, "did not match|contains no AnduinOS-blue"
            ):
                assert_start_button_logo(
                    bad_path,
                    template_path,
                    [10, 10, 30, 30],
                    root / "bad.json",
                )

    def test_localization_oracle_requires_chinese_on_three_desktop_surfaces(self):
        passing = self._events(
            {
                "event": "localization-zh-cn",
                "settings_labels": ["关于", "操作系统"],
                "desktop_labels": ["主目录", "回收站"],
                "arcmenu_labels": ["已固定", "所有应用程序"],
            }
        )
        _validate_localization_zh_cn_events(passing)
        for field, missing in (
            ("settings_labels", "操作系统"),
            ("desktop_labels", "回收站"),
            ("arcmenu_labels", "所有应用程序"),
        ):
            value = json.loads(passing)
            value[field].remove(missing)
            with self.subTest(field=field), self.assertRaisesRegex(
                TestFailure,
                field,
            ):
                _validate_localization_zh_cn_events(json.dumps(value))

    def test_settings_about_oracle_requires_visible_anduinos_identity(self):
        assets = [
            {
                "path": "/usr/share/pixmaps/ubuntu-logo-text.svg",
                "sha256": "a" * 64,
                "brand_markers": ["ANDUINOS", "anduinos"],
                "rendered_template": "/tmp/settings-about-light-logo.png",
            },
            {
                "path": "/usr/share/pixmaps/ubuntu-logo-text-dark.svg",
                "sha256": "b" * 64,
                "brand_markers": ["ANDUINOS", "anduinos"],
                "rendered_template": "/tmp/settings-about-dark-logo.png",
            },
        ]
        passing = self._events(
            {
                "event": "settings-about-branding",
                "application": "设置",
                "page": "about",
                "operating_system": "AnduinOS 2.0.1",
                # GNOME 50 exposes GtkPicture as an unnamed AT-SPI image even
                # when the UI resource supplies alternative-text.
                "logo_name": "",
                "logo_role": "image",
                "coordinate_space": "window",
                "bounds": [100, 80, 400, 82],
                "assets": assets,
            }
        )
        event = _validate_settings_about_events(passing)
        self.assertEqual("AnduinOS 2.0.1", event["operating_system"])
        with self.assertRaisesRegex(TestFailure, "identify AnduinOS"):
            _validate_settings_about_events(
                passing.replace("AnduinOS 2.0.1", "Ubuntu 26.10")
            )
        with self.assertRaisesRegex(TestFailure, "semantic About logo"):
            _validate_settings_about_events(
                passing.replace("[100, 80, 400, 82]", "[0, 0, 0, 0]")
            )
        with self.assertRaisesRegex(TestFailure, "verifiable AnduinOS identity"):
            _validate_settings_about_events(
                passing.replace(
                    '["ANDUINOS", "anduinos"]', '["Ubuntu", "ubuntu"]', 1
                )
            )

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            light = Image.new("RGBA", (80, 20), (0, 0, 0, 0))
            draw = ImageDraw.Draw(light)
            draw.rectangle((2, 2, 17, 17), fill=(53, 124, 244, 255))
            draw.rectangle((22, 4, 76, 16), fill=(60, 60, 60, 255))
            dark = Image.new("RGBA", (80, 20), (0, 0, 0, 0))
            draw = ImageDraw.Draw(dark)
            draw.rectangle((2, 2, 17, 17), fill=(53, 124, 244, 255))
            draw.rectangle((22, 4, 76, 16), fill=(245, 245, 245, 255))
            light_path = root / "light.png"
            dark_path = root / "dark.png"
            light.save(light_path)
            dark.save(dark_path)
            screen = Image.new("RGB", (160, 100), (245, 245, 245))
            screen.paste(light, (40, 30), light)
            good_path = root / "good.png"
            screen.save(good_path)
            assert_settings_about_logo(
                good_path,
                [light_path, dark_path],
                [30, 20, 100, 40],
                root / "good.json",
            )
            bad_path = root / "bad.png"
            Image.new("RGB", (160, 100), (245, 245, 245)).save(bad_path)
            with self.assertRaisesRegex(TestFailure, "matched neither"):
                assert_settings_about_logo(
                    bad_path,
                    [light_path, dark_path],
                    [30, 20, 100, 40],
                    root / "bad.json",
                )

        driver = _source_tree(ROOT / "assertions/guest/ui")
        about = driver.split("def exercise_settings_about_branding", 1)[1].split(
            "def _extension_state", 1
        )[0]
        self.assertIn('"gnome-control-center",\n            "system",\n            "about"', about)
        self.assertIn("get_extents(Atspi.CoordType.WINDOW)", about)
        self.assertIn("GdkPixbuf.Pixbuf.new_from_file_at_scale", about)
        self.assertNotIn("qmp-click", about)
        runner = _source_tree(ROOT / "business/desktop")
        self.assertIn('("pkill", "-f", "(^|/)gnome-control-center( |$)")', runner)
        self.assertNotIn('("pkill", "-x", "gnome-control-center")', runner)

    def test_swapcontrol_oracle_requires_real_green_dashboard(self):
        passing = self._events(
            {
                "event": "secret-focus",
                "request": "swapcontrol-auth-password",
                "target": "password",
                "method": "polkit-initial-password-focus",
            },
            {
                "event": "qmp-secret",
                "request": "swapcontrol-auth-password",
            },
            {
                "event": "qmp-key",
                "request": "swapcontrol-auth-submit",
                "key": "ret",
            },
            {
                "event": "swapcontrol-authentication",
                "outcome": "authenticated",
            },
            {
                "event": "swapcontrol-dashboard",
                "application": "swapcontrol-gtk",
                "page": "dashboard",
                "markers": ["dashboard", "memory-overview", "swap", "zram"],
                "observed_labels": {
                    "dashboard": "仪表板",
                    "memory-overview": "内存概览",
                    "swap": "虚拟内存",
                    "zram": "压缩内存段",
                },
                "authentication": "authenticated",
                "accessibility_focus": False,
                "coordinate_space": "window",
                "bounds": [0, 0, 1100, 650],
            }
        )
        event = _validate_swapcontrol_events(passing)
        self.assertEqual("dashboard", event["page"])
        with self.assertRaisesRegex(TestFailure, "real dashboard"):
            _validate_swapcontrol_events(
                passing.replace('"zram"', '"unrelated"', 1)
            )

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            good = Image.new("RGB", (200, 120), (35, 35, 35))
            ImageDraw.Draw(good).rectangle((40, 20, 119, 99), fill=(42, 170, 75))
            good_path = root / "good.png"
            good.save(good_path)
            assert_swapcontrol_green(good_path, root / "good.json")

            bad_path = root / "bad.png"
            Image.new("RGB", (200, 120), (90, 90, 90)).save(bad_path)
            with self.assertRaisesRegex(TestFailure, "green dashboard"):
                assert_swapcontrol_green(bad_path, root / "bad.json")

        driver = _source_tree(ROOT / "assertions/guest/ui")
        self.assertIn('"swapcontrol-green"', driver)
        self.assertIn("exercise_swapcontrol_green(args.evidence)", driver)

    def test_file_integration_oracles_require_content_and_real_applications(self):
        thumbnail = self._events(
            {
                "event": "file-thumbnail",
                "filename": "AnduinOS-Image.png",
                "uri": "file:///home/anduinostest/Downloads/AnduinOS-Image.png",
                "cache_path": (
                    "/home/anduinostest/.cache/thumbnails/large/"
                    + "a" * 32
                    + ".png"
                ),
                "cache_size": 4096,
                "visible_nodes": [
                    {"name": "AnduinOS-Image.png", "role": "table row"}
                ],
            }
        )
        value = _validate_thumbnail_events(
            thumbnail,
            "AnduinOS-Image.png",
            "anduinostest",
        )
        self.assertEqual(4096, value["cache_size"])
        with self.assertRaisesRegex(TestFailure, "invalid thumbnail"):
            _validate_thumbnail_events(
                thumbnail.replace('"cache_size": 4096', '"cache_size": 0'),
                "AnduinOS-Image.png",
                "anduinostest",
            )

        image = self._events(
            {
                "event": "image-opened",
                "filename": "AnduinOS-Image.png",
                "application": "loupe",
                "process_running": True,
                "visible_names": ["AnduinOS-Image.png"],
            }
        )
        _validate_image_open_events(image)
        with self.assertRaisesRegex(TestFailure, "real visible image"):
            _validate_image_open_events(
                image.replace('"process_running": true', '"process_running": false')
            )

        video = self._events(
            {
                "event": "video-opened",
                "filename": "AnduinOS-Video.mp4",
                "application": "celluloid",
                "mpris_destination": "org.mpris.MediaPlayer2.celluloid.instance1",
                "playback_status": "Playing",
                "position_microseconds": 500000,
                "metadata_identifies_fixture": True,
            }
        )
        _validate_video_open_events(video)
        with self.assertRaisesRegex(TestFailure, "exact video"):
            _validate_video_open_events(
                video.replace("500000", "0")
            )

        deb = self._events(
            {
                "event": "deb-software",
                "filename": "anduinos-acceptance-fixture_1.0_all.deb",
                "application": "软件",
                "detail_names": ["AnduinOS Acceptance Fixture"],
                "package_installed": False,
            }
        )
        _validate_deb_software_events(deb)
        with self.assertRaisesRegex(TestFailure, "harmless DEB safely"):
            _validate_deb_software_events(
                deb.replace('"package_installed": false', '"package_installed": true')
            )

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            good = Image.new("RGB", (160, 120), (0, 0, 0))
            draw = ImageDraw.Draw(good)
            draw.rectangle((0, 0, 79, 59), fill=(235, 45, 55))
            draw.rectangle((80, 0, 159, 59), fill=(45, 210, 90))
            draw.rectangle((0, 60, 79, 119), fill=(45, 100, 235))
            draw.rectangle((80, 60, 159, 119), fill=(245, 210, 40))
            good_path = root / "good.png"
            good.save(good_path)
            assert_fixture_quadrants(good_path, root / "good.json")
            contaminated = Image.new("RGB", (400, 220), (28, 28, 32))
            draw = ImageDraw.Draw(contaminated)
            draw.rectangle((260, 0, 399, 219), fill=(35, 95, 220))
            draw.rectangle((20, 20, 119, 99), fill=(235, 45, 55))
            draw.rectangle((120, 20, 219, 99), fill=(45, 210, 90))
            draw.rectangle((20, 100, 119, 179), fill=(45, 100, 235))
            draw.rectangle((120, 100, 219, 179), fill=(245, 210, 40))
            contaminated_path = root / "contaminated.png"
            contaminated.save(contaminated_path)
            assert_fixture_quadrants(
                contaminated_path,
                root / "contaminated.json",
            )
            bad_path = root / "bad.png"
            Image.new("RGB", (160, 120), (128, 128, 128)).save(bad_path)
            with self.assertRaisesRegex(TestFailure, "content quadrants"):
                assert_fixture_quadrants(bad_path, root / "bad.json")

    def test_chinese_editor_oracle_requires_exact_saved_utf8_and_host_save(self):
        expected = "变角次亮采之门"
        unicode_input = []
        for index, _character in enumerate(expected):
            unicode_input.extend(
                (
                    {
                        "event": "qmp-key",
                        "request": f"chinese-editor-unicode-{index}-start",
                        "key": "ctrl-shift-u",
                    },
                    {
                        "event": "qmp-text",
                        "request": f"chinese-editor-unicode-{index}-codepoint",
                    },
                    {
                        "event": "qmp-key",
                        "request": f"chinese-editor-unicode-{index}-commit",
                        "key": "ret",
                    },
                )
            )
        passing = self._events(
            *unicode_input,
            {
                "event": "qmp-key",
                "request": "chinese-editor-save",
                "key": "ctrl-s",
                "attempt": 1,
            },
            {
                "event": "chinese-editor",
                "filename": "AnduinOS-Chinese.txt",
                "application": "文本编辑器",
                "expected": expected,
                "observed": expected,
                "save_accessible_name": "Ctrl+S",
                "character_count": len(expected),
                "utf8_sha256": hashlib.sha256(
                    (expected + "\n").encode("utf-8")
                ).hexdigest(),
                "implicit_trailing_newline": True,
                "save_attempts": 1,
                "process_running": True,
                "saved": True,
            },
        )
        _validate_chinese_editor_events(passing)
        with self.assertRaisesRegex(TestFailure, "exact normalized Chinese"):
            _validate_chinese_editor_events(
                passing.replace(
                    json.dumps(expected),
                    json.dumps("变角次亮采之问"),
                    1,
                )
            )
        with self.assertRaisesRegex(TestFailure, "Ctrl.S"):
            _validate_chinese_editor_events(
                passing.replace('"key": "ctrl-s"', '"key": "ctrl-o"')
            )
        with self.assertRaisesRegex(TestFailure, "Unicode text"):
            _validate_chinese_editor_events(
                passing.replace('"key": "ctrl-shift-u"', '"key": "spc"', 1)
            )
