"""Public catalog, executable, and TTY desktop oracles."""

from unit.support import *  # noqa: F403


class PublicDesktopOracleTests(FeatureOracleCase):
    def test_extension_journal_filter_cannot_ignore_shell_js_errors(self):
        self.assertTrue(
            _is_gnome_extension_entry(
                SimpleNamespace(
                    component_text="gnome-shell|/usr/bin/gnome-shell",
                    message="JS ERROR: extension exploded",
                )
            )
        )
        self.assertTrue(
            _is_gnome_extension_entry(
                SimpleNamespace(
                    component_text="unknown",
                    message="Extension example@test raised an exception",
                )
            )
        )
        self.assertFalse(
            _is_gnome_extension_entry(
                SimpleNamespace(
                    component_text="NetworkManager",
                    message="link became ready",
                )
            )
        )
    def test_tty6_oracle_accepts_the_active_kernel_screen_buffer(self):
        evidence = _validate_tty6_evidence(self._tty6_output(), 0)
        self.assertEqual(6, evidence["active_vt"])
        self.assertIn("AnduinOS", evidence["text"])
        self.assertEqual(
            2,
            _validate_graphical_vt_evidence(self._graphical_vt_output(), 0),
        )

    def test_tty6_oracle_rejects_wrong_vt_and_ubuntu_branding(self):
        with self.assertRaisesRegex(TestFailure, "Ctrl\\+Alt\\+F6"):
            _validate_tty6_evidence(
                self._tty6_output().replace("active-vt=6", "active-vt=5"),
                0,
            )
        with self.assertRaisesRegex(TestFailure, "Ubuntu branding"):
            _validate_tty6_evidence(
                self._tty6_output("AnduinOS Ubuntu tty6 login:"),
                0,
            )
        with self.assertRaisesRegex(TestFailure, "expected tty2"):
            _validate_graphical_vt_evidence(
                self._graphical_vt_output(3),
                0,
                expected_vt=2,
            )

    def test_tty6_guest_probes_are_bash_syntax_checked(self):
        for command in (
            _graphical_vt_probe_command("acceptance user"),
            _graphical_vt_probe_command("acceptance user", wait_for=2),
            _tty6_probe_command(),
        ):
            result = subprocess.run(
                ("bash", "-n"),
                input=command,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                check=False,
            )
            self.assertEqual(0, result.returncode, result.stdout)
            self.assertIn("/sys/class/tty/tty0/active", command)
            self.assertNotIn("fgconsole", command)
        with self.assertRaises(ValueError):
            _graphical_vt_probe_command("acceptance", wait_for=13)

    def test_tty6_exercise_sends_both_real_vt_chords(self):
        runner = object.__new__(FeatureSuiteRunner)
        runner.username = "acceptance"
        runner._journal_cursors = Mock(return_value={"system": "s", "user": "u"})
        runner._assert_scoped_journal = Mock()
        before = CommandResult(self._graphical_vt_output(), 0)
        tty6 = CommandResult(self._tty6_output(), 0)
        restored = CommandResult(self._graphical_vt_output(), 0)
        serial = Mock()
        serial.run.side_effect = (before, tty6, restored)
        qmp = Mock()
        vm = SimpleNamespace(serial=serial, qmp=qmp, screenshot=Mock())
        base = SimpleNamespace()
        with tempfile.TemporaryDirectory() as directory:
            with patch("business.desktop.session._graphical_user", return_value="acceptance"):
                runner._exercise_tty6_branding(vm, base, Path(directory))
        self.assertEqual(
            [call("ctrl-alt-f6"), call("ctrl-alt-f2")],
            qmp.send_key.call_args_list,
        )
        runner._assert_scoped_journal.assert_called_once()

    def test_tty6_exercise_restores_graphics_after_a_branding_failure(self):
        runner = object.__new__(FeatureSuiteRunner)
        runner.username = "acceptance"
        runner._journal_cursors = Mock(return_value={"system": "s", "user": "u"})
        runner._assert_scoped_journal = Mock()
        before = CommandResult(self._graphical_vt_output(), 0)
        failed = CommandResult("active-vt=6\nvcs-device=/dev/vcs6", 71)
        restored = CommandResult(self._graphical_vt_output(), 0)
        serial = Mock()
        serial.run.side_effect = (before, failed, restored)
        qmp = Mock()
        vm = SimpleNamespace(serial=serial, qmp=qmp, screenshot=Mock())
        with tempfile.TemporaryDirectory() as directory:
            with patch("business.desktop.session._graphical_user", return_value="acceptance"):
                with self.assertRaisesRegex(TestFailure, "login banner"):
                    runner._exercise_tty6_branding(
                        vm,
                        SimpleNamespace(),
                        Path(directory),
                    )
        self.assertEqual(
            [call("ctrl-alt-f6"), call("ctrl-alt-f2")],
            qmp.send_key.call_args_list,
        )
        runner._assert_scoped_journal.assert_not_called()

    def test_nextcloud_ppa_oracle_requires_the_real_signed_source(self):
        passing = "\n".join(
            (
                "invoking-user=anduinostest",
                "command=sudo add-apt-repository -y ppa:nextcloud-devs/client",
                "repository-command=passed",
                "os-release-codename=resolute",
                "source-count=1",
                "source-path=/etc/apt/sources.list.d/nextcloud-devs-ubuntu-client-resolute.sources",
                "source-uri=https://ppa.launchpadcontent.net/nextcloud-devs/client/ubuntu/",
                "source-suite=resolute",
                "source-signed-by=yes",
                "nextcloud-ppa-sudo-policy=removed",
            )
        )
        evidence = _validate_nextcloud_ppa_evidence(
            passing,
            0,
            "anduinostest",
        )
        self.assertEqual("resolute", evidence["codename"])
        for broken, message in (
            (passing.replace("source-signed-by=yes", "source-signed-by=no"), "signed"),
            (passing.replace("source-suite=resolute", "source-suite=questing"), "suite"),
            (
                passing.replace(
                    "source-uri=https://ppa.launchpadcontent.net/nextcloud-devs/client/ubuntu",
                    "source-uri=https://example.invalid/unrelated",
                ),
                "unrelated",
            ),
        ):
            with self.subTest(message=message):
                with self.assertRaises(TestFailure):
                    _validate_nextcloud_ppa_evidence(
                        broken,
                        0,
                        "anduinostest",
                    )
        with self.assertRaisesRegex(TestFailure, "command or source"):
            _validate_nextcloud_ppa_evidence(passing, 1, "anduinostest")

    def test_public_cpu_z_download_and_desktop_oracles_fail_closed(self):
        passing_download = "\n".join(
            (
                "cpu-z-http-code=200",
                "cpu-z-archive-preexisting=no",
                "cpu-z-member-preexisting=no",
                "cpu-z-version=2.20.2",
                "cpu-z-url=https://download.cpuid.com/cpu-z/cpu-z_2.20.2-en.zip",
                "cpu-z-archive=cpu-z_2.20.2-en.zip",
                "cpu-z-archive-sha256="
                "320e073a6f387464ac3faac5f010b5fe70e31fab30745883d023c8372e80f3c5",
                "cpu-z-member=cpuz_x64.exe",
                "cpu-z-member-sha256="
                "e1b0eda853641b75fa1a890e7811bc19b3be0ece0494c60f03d34247b7650126",
                "cpu-z-member-size=7428328",
                "cpu-z-mime=application/vnd.microsoft.portable-executable",
                "cpu-z-handler=com.anduinos.ExeRunner.desktop",
                "bottles=absent",
                "public-cpu-z=downloaded-and-verified",
            )
        )
        download = _validate_cpu_z_download_evidence(passing_download, 0)
        self.assertEqual(7_428_328, download["member_size"])
        alternate = _validate_cpu_z_download_evidence(
            passing_download.replace(
                "application/vnd.microsoft.portable-executable",
                "application/x-msdownload",
            ),
            0,
        )
        self.assertEqual("application/x-msdownload", alternate["mime_type"])
        for broken in (
            passing_download.replace("320e073a", "020e073a", 1),
            passing_download.replace(
                "com.anduinos.ExeRunner.desktop", "unrelated.desktop"
            ),
            passing_download.replace("bottles=absent", "bottles=installed"),
            passing_download.replace(
                "application/vnd.microsoft.portable-executable",
                "application/octet-stream",
            ),
        ):
            with self.assertRaises(TestFailure):
                _validate_cpu_z_download_evidence(broken, 0)
        with self.assertRaisesRegex(TestFailure, "download or file contract"):
            _validate_cpu_z_download_evidence(passing_download, 22)

        events = self._events(
            {
                "event": "file-thumbnail",
                "filename": "cpuz_x64.exe",
                "uri": "file:///home/anduinostest/Downloads/cpuz_x64.exe",
                "cache_path": (
                    "/home/anduinostest/.cache/thumbnails/large/"
                    + "a" * 32
                    + ".png"
                ),
                "cache_size": 4096,
                "visible_nodes": [
                    {"name": "cpuz_x64.exe", "role": "table row"}
                ],
            },
            {
                "event": "nautilus-open",
                "filename": "cpuz_x64.exe",
                "activation_method": "selected-item-qmp-enter",
                "observed": "Installing CPU-Z?",
            },
            {
                "event": "cpu-z-public-recommendation",
                "filename": "cpuz_x64.exe",
                "application": "AnduinOS Windows EXE Runner",
                "heading": "Installing CPU-Z?",
                "reason": (
                    "CPU-X is a native Linux application that perfectly mirrors "
                    "CPU-Z in functionality and interface, without the need for "
                    "Windows sandboxing."
                ),
                "controls": {
                    "cancel": {
                        "name": "Cancel",
                        "role": "button",
                        "enabled": True,
                        "showing": True,
                    },
                    "force_run": {
                        "name": "Force Run Anyway",
                        "role": "button",
                        "enabled": True,
                        "showing": True,
                    },
                    "cpux_get": {
                        "name": "Get CPU-X",
                        "role": "button",
                        "enabled": True,
                        "showing": True,
                    },
                },
                "bottles_installed": False,
                "runner_processes": [
                    "123 /usr/bin/python3 /usr/bin/anduinos-exe-runner "
                    "/home/anduinostest/Downloads/cpuz_x64.exe"
                ],
            },
        )
        desktop = _validate_cpu_z_events(events, "anduinostest")
        self.assertEqual(4096, desktop["cache_size"])
        with self.assertRaisesRegex(TestFailure, "unrelated desktop surface"):
            _validate_cpu_z_events(
                events.replace(
                    "Installing CPU-Z?",
                    "Unrelated Application",
                    1,
                ),
                "anduinostest",
            )

    def test_public_spotify_catalog_probe_and_classification_fail_closed(self):
        passing = "\n".join(
            (
                "flatpak-version=Flatpak 1.16.6",
                "spotify-public-remote-count=1",
                "spotify-public-remote-url=https://dl.flathub.org/repo/",
                "spotify-public-appstream-refresh=passed",
                "spotify-public-ref=app/com.spotify.Client/x86_64/stable",
                "spotify-public-commit=" + "a" * 64,
                "spotify-public-cached-entry="
                "com.spotify.Client\tapp/com.spotify.Client/x86_64/stable\t"
                "x86_64\tstable\tflathub",
                "spotify-public-app-id=com.spotify.Client",
                "spotify-public-remote=flathub",
                "spotify-public-arch=x86_64",
                "spotify-public-failure-class=none",
                "spotify-public-catalog=current-and-resolved",
            )
        )
        evidence = _validate_spotify_public_catalog_evidence(passing, 0)
        self.assertEqual("a" * 64, evidence["commit"])
        for broken in (
            passing.replace("https://dl.flathub.org/repo/", "http://example.invalid/"),
            passing.replace("com.spotify.Client/x86_64/stable", "unrelated/x86_64/stable", 1),
            passing.replace("a" * 64, "not-a-commit"),
            passing.replace("x86_64\tstable\tflathub", "x86_64\tstable\tunrelated"),
        ):
            with self.subTest(broken=broken[-120:]):
                with self.assertRaises(TestFailure):
                    _validate_spotify_public_catalog_evidence(broken, 0)

        for classification in ("external-catalog", "product-regression"):
            failure = "\n".join(
                (
                    "spotify-public-failure-reason=appstream-refresh-failed",
                    f"spotify-public-failure-class={classification}",
                )
            )
            with self.subTest(classification=classification):
                with self.assertRaisesRegex(TestFailure, classification):
                    _validate_spotify_public_catalog_evidence(failure, 85)
        with self.assertRaisesRegex(TestFailure, "without a valid classification"):
            _validate_spotify_public_catalog_evidence("network failed", 1)

        probe = _spotify_public_catalog_command()
        syntax = subprocess.run(
            ("bash", "-n"),
            input=probe,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            check=False,
        )
        self.assertEqual(0, syntax.returncode, syntax.stdout)
        self.assertIn("flatpak update --appstream --system", probe)
        self.assertIn("flatpak remote-info --system", probe)
        self.assertIn("flatpak remote-ls --system --cached", probe)
        self.assertIn("https://dl.flathub.org/repo/", probe)
        self.assertNotIn("/home/anduin", probe)

        source = _source_tree(ROOT / "business/desktop")
        body = source.split("def _exercise_spotify_public(", 1)[1].split(
            "def _exercise_nextcloud_ppa(", 1
        )[0]
        self.assertNotIn("set_link", body)
        self.assertIn("store.spotify-public", _SHELL_DRIVER_CHECKS)
        self.assertIn("systemctl --user stop gnome-software.service", body)
        self.assertIn('mode="shell-spotify-store"', body)

    def test_public_wechat_install_and_tray_oracles_fail_closed(self):
        commit = "b" * 64
        location = (
            "/var/lib/flatpak/app/com.tencent.WeChat/x86_64/stable/" + commit
        )
        passing_install = "\n".join(
            (
                "wechat-preinstalled=no",
                "wechat-remote-count=1",
                "wechat-remote-url=https://dl.flathub.org/repo/",
                "wechat-remote-ref=app/com.tencent.WeChat/x86_64/stable",
                f"wechat-remote-commit={commit}",
                "wechat-install-command=passed",
                "wechat-installed-ref=app/com.tencent.WeChat/x86_64/stable",
                f"wechat-installed-commit={commit}",
                "wechat-installed-origin=flathub",
                f"wechat-installed-location={location}",
                "wechat-desktop=/var/lib/flatpak/exports/share/applications/"
                "com.tencent.WeChat.desktop",
                f"wechat-desktop-resolved={location}/export/share/applications/"
                "com.tencent.WeChat.desktop",
                "wechat-app-id=com.tencent.WeChat",
                "wechat-arch=x86_64",
                "wechat-failure-class=none",
                "wechat-install=current-and-verified",
            )
        )
        install_evidence = _validate_wechat_install_evidence(passing_install, 0)
        self.assertEqual(commit, install_evidence["commit"])
        for broken in (
            passing_install.replace("wechat-preinstalled=no", "wechat-preinstalled=yes"),
            passing_install.replace(commit, "c" * 64, 1),
            passing_install.replace("wechat-installed-origin=flathub", "wechat-installed-origin=other"),
            passing_install.replace(
                f"wechat-desktop-resolved={location}",
                "wechat-desktop-resolved=/tmp/untrusted",
            ),
        ):
            with self.subTest(broken=broken[-160:]):
                with self.assertRaises(TestFailure):
                    _validate_wechat_install_evidence(broken, 0)
        for classification in (
            "external-catalog",
            "external-artifact",
            "product-regression",
        ):
            failure = "\n".join(
                (
                    "wechat-failure-reason=flatpak-install-failed",
                    f"wechat-failure-class={classification}",
                )
            )
            with self.subTest(classification=classification):
                with self.assertRaisesRegex(TestFailure, classification):
                    _validate_wechat_install_evidence(failure, 90)

        process = {
            "pid": 5010,
            "namespace_pid": 5011,
            "uid": 1000,
            "start_time_ticks": 987654,
            "command": "/app/extra/wechat/WeChatAppEx",
            "executable": "/app/extra/wechat/WeChatAppEx",
        }
        wechat_window = {
            "id": "0x2a00007",
            "title": "微信",
            "classes": ["wechat", "WeChat"],
            "pid": 5011,
            "state": "",
            "map_state": "IsViewable",
            "visible": True,
            "x": 500,
            "y": 185,
            "width": 280,
            "height": 382,
        }
        launch_events = self._events(
            {
                "event": "qmp-key",
                "request": "wechat-search-open",
                "key": "meta_l",
            },
            {"event": "qmp-text", "request": "wechat-search-text"},
            {
                "event": "start-search-result",
                "query": "WeChat",
                "accessible_name": "WeChat",
                "application": "gnome-shell",
                "stable_observations": 4,
            },
            {
                "event": "search-entry-focus",
                "query": "WeChat",
                "application": "gnome-shell",
                "focused": True,
            },
            {
                "event": "qmp-key",
                "request": "wechat-result-activate",
                "key": "ret",
            },
            {
                "event": "wechat-installed-launched",
                "search_result": "WeChat",
                "activation_method": "qmp-keyboard",
                "application": "com.tencent.WeChat",
                "observation": "ewmh-x11",
                "main_window": wechat_window,
                "windows": [wechat_window],
                "process": process,
                "visible": True,
            },
        )
        launch = _validate_wechat_install_events(launch_events)
        self.assertEqual(5010, launch["process"]["pid"])
        with self.assertRaisesRegex(TestFailure, "unrelated process"):
            _validate_wechat_install_events(
                launch_events.replace(
                    "/app/extra/wechat/WeChatAppEx",
                    "/usr/bin/unrelated",
                )
            )

        hidden = dict(process)
        tray_events = self._events(
            {
                "event": "wechat-tray-baseline",
                "application": "com.tencent.WeChat",
                "main_window": wechat_window,
                "windows": [wechat_window],
                "process": process,
            },
            {
                "event": "qmp-key",
                "request": "wechat-close-to-tray",
                "key": "alt-f4",
            },
            {
                "event": "wechat-indicator",
                "process": hidden,
                "indicator": {
                    "accessible_name": "WeChat",
                    "target_name": "WeChat",
                    "role": "button",
                    "application": "gnome-shell",
                    "bounds": [1100, 760, 24, 24],
                    "screen": [1280, 800],
                    "lower_right": True,
                },
                "visible": True,
            },
            {
                "event": "spice-double-click",
                "request": "wechat-indicator-restore",
                "target": "WeChat AppIndicator",
                "button": "left",
                "application": "gnome-shell",
                "clicks": 2,
            },
            {
                "event": "wechat-tray-restored",
                "application": "com.tencent.WeChat",
                "main_window": wechat_window,
                "windows": [wechat_window],
                "process": process,
                "same_process": True,
                "visible": True,
            },
        )
        tray = _validate_wechat_tray_events(tray_events)
        self.assertEqual(987654, tray["process"]["start_time_ticks"])
        with self.assertRaisesRegex(TestFailure, "same process"):
            _validate_wechat_tray_events(
                tray_events.replace('"start_time_ticks": 987654', '"start_time_ticks": 987655', 1)
            )
        with self.assertRaisesRegex(TestFailure, "lower-right"):
            _validate_wechat_tray_events(
                tray_events.replace('"lower_right": true', '"lower_right": false')
            )

        probe = _wechat_install_command()
        syntax = subprocess.run(
            ("bash", "-n"),
            input=probe,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            check=False,
        )
        self.assertEqual(0, syntax.returncode, syntax.stdout)
        self.assertIn("flatpak install --system --noninteractive", probe)
        self.assertIn("com.tencent.WeChat", probe)
        self.assertIn("flatpak remote-info --system", probe)
        self.assertIn("printf '\nwechat-install-command=passed\n'", probe)
        self.assertNotIn("/home/anduin", probe)
        driver = _source_tree(ROOT / "assertions/guest/ui")
        self.assertIn('"public-wechat-install"', driver)
        self.assertIn('"public-wechat-tray"', driver)
        self.assertIn("exercise_wechat_install(args.evidence)", driver)
        self.assertIn("exercise_wechat_tray(args.evidence)", driver)
        self.assertIn("def _wechat_process_identity", driver)
        self.assertIn('"start_time_ticks": int(fields[19])', driver)
        self.assertNotIn("def _one_wechat_instance", driver)
        self.assertIn('runtime.glob(".mutter-Xwaylandauth.*")', driver)
        self.assertIn('environment["XAUTHORITY"] = authority', driver)
        self.assertIn("app.wechat-install", _SHELL_DRIVER_CHECKS)
        self.assertNotIn("app.wechat-tray", _SHELL_DRIVER_CHECKS)

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            good = Image.new("RGB", (1280, 800), (20, 30, 45))
            draw = ImageDraw.Draw(good)
            left = int(wechat_window["x"])
            top = int(wechat_window["y"])
            width = int(wechat_window["width"])
            height = int(wechat_window["height"])
            draw.rectangle(
                (left, top, left + width - 1, top + height - 1),
                fill="white",
            )
            qr_left = left + round(width * 0.15)
            qr_top = top + round(height * 0.10)
            qr_right = left + round(width * 0.85)
            qr_bottom = top + round(height * 0.62)
            cell = 5
            for y in range(qr_top, qr_bottom, cell):
                for x in range(qr_left, qr_right, cell):
                    if ((x - qr_left) // cell + (y - qr_top) // cell) % 2 == 0:
                        draw.rectangle(
                            (x, y, min(x + cell - 1, qr_right), min(y + cell - 1, qr_bottom)),
                            fill="black",
                        )
            draw.rectangle(
                (left + 80, top + 250, left + 200, top + 270),
                fill=(0, 210, 80),
            )
            good_path = root / "wechat.png"
            good.save(good_path)
            assert_wechat_login_window(
                good_path,
                root / "wechat.json",
                {"main_window": wechat_window},
            )
            generic = Image.new("RGB", (1280, 800), "white")
            generic_path = root / "generic.png"
            generic.save(generic_path)
            with self.assertRaisesRegex(TestFailure, "QR login UI"):
                assert_wechat_login_window(
                    generic_path,
                    root / "generic.json",
                    {"main_window": wechat_window},
                )

    def test_public_cpu_z_probe_is_portable_and_thumbnail_is_content_specific(self):
        probe = _cpu_z_download_command()
        syntax = subprocess.run(
            ("bash", "-n"),
            input=probe,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            check=False,
        )
        self.assertEqual(0, syntax.returncode, syntax.stdout)
        self.assertIn("https://download.cpuid.com/cpu-z/", probe)
        self.assertIn("sha256sum", probe)
        self.assertIn("xdg-mime query default", probe)
        self.assertIn("application/x-msdownload", probe)
        self.assertIn("application/vnd.microsoft.portable-executable", probe)
        self.assertIn("flatpak info com.usebottles.bottles", probe)
        self.assertNotIn("/home/anduin", probe)

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            good = Image.new("RGB", (256, 256), (52, 18, 116))
            draw = ImageDraw.Draw(good)
            draw.rounded_rectangle((52, 52, 204, 204), radius=12, fill="white")
            draw.rectangle((75, 75, 181, 181), fill=(52, 18, 116))
            draw.rounded_rectangle((100, 100, 156, 156), radius=10, fill="white")
            good_path = root / "cpu-z.png"
            good.save(good_path)
            assert_cpu_z_thumbnail(good_path, root / "cpu-z.json")

            generic = root / "generic.png"
            Image.new("RGB", (256, 256), (52, 18, 116)).save(generic)
            with self.assertRaisesRegex(TestFailure, "white/purple artwork"):
                assert_cpu_z_thumbnail(generic, root / "generic.json")

        driver = _source_tree(ROOT / "assertions/guest/ui")
        self.assertIn('"public-cpuz-file"', driver)
        self.assertIn("verify_public_cpuz_file(args.filename, args.evidence)", driver)

    def test_local_pe_thumbnail_and_open_have_independent_oracles(self):
        cache = (
            "/home/anduinostest/.cache/thumbnails/large/"
            "0123456789abcdef0123456789abcdef.png"
        )
        thumbnail_output = json.dumps(
            {
                "event": "file-thumbnail",
                "filename": "cpu-z.exe",
                "uri": "file:///home/anduinostest/Downloads/cpu-z.exe",
                "cache_path": cache,
                "cache_size": 4096,
                "visible_nodes": [{"name": "cpu-z.exe", "role": "table row"}],
            }
        )
        evidence = _validate_windows_executable_thumbnail_events(
            thumbnail_output,
            "anduinostest",
        )
        self.assertEqual(cache, evidence["cache_path"])
        with self.assertRaisesRegex(TestFailure, "thumbnail event"):
            _validate_windows_executable_thumbnail_events(
                "",
                "anduinostest",
            )

        open_event = json.dumps(
            {
                "event": "nautilus-open",
                "filename": "cpu-z.exe",
                "activation_method": "host-spice-double-click",
                "observed": "CPU-Z has a native alternative",
            }
        )
        recommendation = json.dumps(
            {
                "event": "cpu-z-recommendation",
                "application": "AnduinOS Windows EXE Runner",
            }
        )
        _validate_windows_executable_open_events(
            "\n".join((open_event, recommendation))
        )
        with self.assertRaisesRegex(TestFailure, "out of order"):
            _validate_windows_executable_open_events(
                "\n".join((recommendation, open_event))
            )

    def test_nextcloud_ppa_exercise_uses_a_narrow_temporary_sudo_policy(self):
        source = _source_tree(ROOT / "business/desktop")
        body = source.split("def _exercise_nextcloud_ppa(", 1)[1].split(
            "def _graphical_session_id(",
            1,
        )[0]
        self.assertIn(r"ppa\:nextcloud-devs/client", body)
        self.assertIn(
            "sudo -n /usr/bin/add-apt-repository -y ",
            body,
        )
        self.assertIn("finally:", body)
        self.assertIn("rm -f", body)
        self.assertNotIn("sudo -S", body)
        probe = _nextcloud_ppa_source_probe_command()
        syntax = subprocess.run(
            ("bash", "-n"),
            input=probe,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            check=False,
        )
        self.assertEqual(0, syntax.returncode, syntax.stdout)
        self.assertIn("print(f'source-uri={uri_value}')", probe)
        self.assertNotIn("source-uri=https://", probe)
        self.assertNotIn("grep -F -m1", probe)
        self.assertNotIn("apt-get indextargets", probe)
