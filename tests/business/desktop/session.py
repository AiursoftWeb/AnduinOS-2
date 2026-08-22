"""Logged-in desktop, localization, shortcuts, and local-file behavior."""

from .context import *  # noqa: F403


class SessionChecks:
    def _exercise_theme_selector(
        self,
        vm: QemuVm,
        base: PromotedBase,
        artifacts: Path,
    ) -> None:
        """Exercise the localized Shell selector and establish a dark baseline."""

        self._prepare_theme_fixture(vm)
        self.phase_callback(
            base.scenario.id,
            "desktop-theme",
            "Selecting dark style through the localized GNOME Shell menu",
        )
        self._select_desktop_theme(vm, artifacts, "dark", "selector-baseline")

    def _exercise_alt_tab(
        self,
        vm: QemuVm,
        base: PromotedBase,
        artifacts: Path,
    ) -> None:
        """Prove Alt+Tab moves focus between two real, distinct GTK windows."""

        self._prepare_shell_fixture(vm, launch_windows=True)
        self._run_shell_driver(
            vm,
            base,
            artifacts,
            mode="shortcut-alt-tab",
            validator=_validate_alt_tab_events,
        )

    def _exercise_initial_overview(
        self,
        vm: QemuVm,
        base: PromotedBase,
        artifacts: Path,
    ) -> None:
        """Observe the untouched post-login Shell state before any shortcut."""

        self._run_shell_driver(
            vm,
            base,
            artifacts,
            mode="shell-initial-overview",
            validator=_validate_initial_overview_events,
        )

    def _exercise_super_tab(
        self,
        vm: QemuVm,
        base: PromotedBase,
        artifacts: Path,
    ) -> None:
        """Prove AnduinOS Super+Tab shows and then hides the real Overview."""

        self._run_shell_driver(
            vm,
            base,
            artifacts,
            mode="shortcut-super-tab",
            validator=_validate_super_tab_events,
        )

    def _exercise_super_i(
        self,
        vm: QemuVm,
        base: PromotedBase,
        artifacts: Path,
    ) -> None:
        """Prove Super+I opens a focused GNOME Settings window."""

        self._run_shell_driver(
            vm,
            base,
            artifacts,
            mode="shortcut-super-i",
            validator=_validate_super_i_events,
        )
        assert vm.serial is not None
        vm.serial.run(
            _desktop_command(
                self.username,
                ("pkill", "-f", "(^|/)gnome-control-center( |$)"),
            ),
            timeout=30,
            check=False,
        )

    def _exercise_settings_about_branding(
        self,
        vm: QemuVm,
        base: PromotedBase,
        artifacts: Path,
    ) -> None:
        """Prove Settings paints AnduinOS identity on its real About page."""

        def assert_visible_logo(frame: Path, validated: object) -> None:
            if not isinstance(validated, dict):
                raise TestFailure("The Settings About validator returned no evidence")
            remote_assets = validated.get("assets")
            if not isinstance(remote_assets, list):
                raise TestFailure("The Settings About event returned no logo assets")
            templates = []
            for value in remote_assets:
                if not isinstance(value, dict):
                    raise TestFailure("The Settings About logo asset is malformed")
                rendered = value.get("rendered_template")
                if not isinstance(rendered, str):
                    raise TestFailure("The Settings About asset has no rendered template")
                templates.append(
                    artifacts
                    / "guest-shell-evidence"
                    / "settings-about-branding"
                    / Path(rendered).name
                )
            if any(not template.is_file() for template in templates):
                raise TestFailure(
                    "The guest did not return both rendered Settings About assets"
                )
            bounds = validated.get("bounds")
            if not isinstance(bounds, list):
                raise TestFailure("The Settings About event has no semantic bounds")
            assert_settings_about_logo(
                frame,
                templates,
                bounds,
                artifacts / "settings-about-logo-analysis.json",
            )

        assert vm.serial is not None
        try:
            self._run_shell_driver(
                vm,
                base,
                artifacts,
                mode="settings-about-branding",
                validator=_validate_settings_about_events,
                screenshot_validator=assert_visible_logo,
            )
        finally:
            vm.serial.run(
                _desktop_command(
                    self.username,
                    ("pkill", "-f", "(^|/)gnome-control-center( |$)"),
                ),
                timeout=30,
                check=False,
            )

    def _exercise_localization_zh_cn(
        self,
        vm: QemuVm,
        base: PromotedBase,
        artifacts: Path,
    ) -> None:
        """Require Chinese UI on three independent desktop surfaces."""

        assert vm.serial is not None
        try:
            self._run_shell_driver(
                vm,
                base,
                artifacts,
                mode="localization-zh-cn",
                validator=_validate_localization_zh_cn_events,
            )
        finally:
            vm.serial.run(
                _desktop_command(
                    self.username,
                    ("pkill", "-f", "(^|/)gnome-control-center( |$)"),
                ),
                timeout=30,
                check=False,
            )

    def _exercise_swapcontrol_green(
        self,
        vm: QemuVm,
        base: PromotedBase,
        artifacts: Path,
    ) -> None:
        """Prove the real Swap Control dashboard paints its green state."""

        def assert_green(frame: Path, _validated: object) -> None:
            assert_swapcontrol_green(
                frame,
                artifacts / "swapcontrol-green-analysis.json",
            )

        assert vm.serial is not None
        try:
            self._run_shell_driver(
                vm,
                base,
                artifacts,
                mode="swapcontrol-green",
                validator=_validate_swapcontrol_events,
                secret_texts={"swapcontrol-auth-password": self.password},
                screenshot_validator=assert_green,
            )
        finally:
            vm.serial.run(
                _desktop_command(
                    self.username,
                    ("pkill", "-f", "(^|/)swapcontrol-gtk( |$)"),
                ),
                timeout=30,
                check=False,
            )

    def _prepare_file_fixtures(
        self,
        vm: QemuVm,
        artifacts: Path,
    ) -> tuple[str, object]:
        """Upload a content-addressed desktop file set exactly once."""

        assert vm.serial is not None
        fixtures = build_file_integration_fixtures(
            artifacts / "host-file-fixtures"
        )
        paths = (fixtures.image, fixtures.video, fixtures.deb, fixtures.text)
        manifest = {
            path.name: {
                "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                "size": path.stat().st_size,
            }
            for path in paths
        }
        (artifacts / "file-fixture-manifest.json").write_text(
            json.dumps(manifest, indent=2) + "\n",
            encoding="utf-8",
        )
        remote = "/run/anduinos-feature-files"
        ready = vm.serial.run(
            f"test -f {shlex.quote(remote + '/.prepared')}",
            timeout=15,
            check=False,
        )
        if ready.returncode == 0:
            return remote, fixtures
        downloads = f"/home/{self.username}/Downloads"
        vm.serial.run(
            f"install -d -m 0777 {shlex.quote(remote + '/evidence')}\n"
            f"install -d -o {shlex.quote(self.username)} "
            f"-g {shlex.quote(self.username)} -m 0755 {shlex.quote(downloads)}",
            timeout=30,
        )
        self.driver.upload(vm.serial, remote)
        for path in paths:
            vm.serial.upload(path, f"{downloads}/{path.name}", 0o644)
        quoted_files = " ".join(
            shlex.quote(f"{downloads}/{path.name}") for path in paths
        )
        prepared = vm.serial.run(
            "set -euo pipefail\n"
            f"chown {shlex.quote(self.username)}:{shlex.quote(self.username)} "
            f"{quoted_files}\n"
            f"sha256sum {quoted_files}\n"
            f"touch {shlex.quote(remote + '/.prepared')}\n"
            "printf 'file-fixtures=prepared\\n'",
            timeout=60,
            check=False,
        )
        (artifacts / "file-fixture-guest-sha256.txt").write_text(
            prepared.stdout + "\n", encoding="utf-8"
        )
        if prepared.returncode != 0 or "file-fixtures=prepared" not in prepared.stdout:
            raise TestFailure(
                "Could not prepare desktop file fixtures:\n"
                + prepared.stdout[-8000:]
            )
        return remote, fixtures

    def _run_file_driver(
        self,
        vm: QemuVm,
        base: PromotedBase,
        artifacts: Path,
        *,
        mode: str,
        validator: Callable[[str], dict[str, object]],
        thumbnail_name: str | None = None,
        require_visible_fixture: bool = False,
        text_inputs: dict[str, str] | None = None,
    ) -> dict[str, object]:
        """Drive one real Nautilus operation and retain visual/journal evidence."""

        assert vm.serial is not None and vm.qmp is not None
        remote, _fixtures = self._prepare_file_fixtures(vm, artifacts)
        cursors = self._journal_cursors(vm)
        command = _desktop_command(
            self.username,
            (
                "python3",
                f"{remote}/atspi_driver.py",
                mode,
                "--evidence",
                f"{remote}/evidence/{mode}",
            ),
        )
        result = _run_with_qmp_key_requests(
            vm,
            command,
            timeout=300,
            text_inputs=text_inputs,
            request_trace=artifacts / f"{mode}-qmp-requests.jsonl",
        )
        (artifacts / f"{mode}-events.jsonl").write_text(
            result.stdout + "\n", encoding="utf-8"
        )
        _retrieve_tree(vm.serial, remote, artifacts / "guest-file-evidence")
        if result.returncode != 0:
            raise TestFailure(
                f"Desktop file probe {mode!r} failed:\n" + result.stdout[-8000:]
            )
        validated = validator(result.stdout)
        frame = vm.screenshot(mode)
        if thumbnail_name is not None:
            cache_path = validated.get("cache_path")
            if not isinstance(cache_path, str):
                raise TestFailure("Thumbnail event returned no safe cache path")
            thumbnail = artifacts / thumbnail_name
            _retrieve_file(vm.serial, cache_path, thumbnail)
            if not thumbnail.is_file():
                raise TestFailure("The guest thumbnail could not be retrieved")
            assert_fixture_quadrants(
                thumbnail,
                artifacts / f"{Path(thumbnail_name).stem}-analysis.json",
            )
        if require_visible_fixture:
            assert_fixture_quadrants(
                frame,
                artifacts / f"{mode}-screen-analysis.json",
            )
        vm.qmp.send_key("alt-f4")
        time.sleep(1)
        self._assert_scoped_journal(
            vm,
            base,
            cursors,
            artifacts,
            scope=mode,
        )
        return validated

    def _exercise_image_thumbnail(
        self, vm: QemuVm, base: PromotedBase, artifacts: Path
    ) -> None:
        self._run_file_driver(
            vm,
            base,
            artifacts,
            mode="file-image-thumbnail",
            validator=lambda output: _validate_thumbnail_events(
                output, "AnduinOS-Image.png", self.username
            ),
            thumbnail_name="image-thumbnail.png",
        )

    def _exercise_video_thumbnail(
        self, vm: QemuVm, base: PromotedBase, artifacts: Path
    ) -> None:
        self._run_file_driver(
            vm,
            base,
            artifacts,
            mode="file-video-thumbnail",
            validator=lambda output: _validate_thumbnail_events(
                output, "AnduinOS-Video.mp4", self.username
            ),
            thumbnail_name="video-thumbnail.png",
        )

    def _exercise_image_open(
        self, vm: QemuVm, base: PromotedBase, artifacts: Path
    ) -> None:
        self._run_file_driver(
            vm,
            base,
            artifacts,
            mode="file-image-open",
            validator=_validate_image_open_events,
            require_visible_fixture=True,
        )

    def _exercise_video_open(
        self, vm: QemuVm, base: PromotedBase, artifacts: Path
    ) -> None:
        self._run_file_driver(
            vm,
            base,
            artifacts,
            mode="file-video-open",
            validator=_validate_video_open_events,
        )

    def _exercise_deb_software(
        self, vm: QemuVm, base: PromotedBase, artifacts: Path
    ) -> None:
        self._run_file_driver(
            vm,
            base,
            artifacts,
            mode="file-deb-software",
            validator=_validate_deb_software_events,
        )

    def _exercise_chinese_editor(
        self, vm: QemuVm, base: PromotedBase, artifacts: Path
    ) -> None:
        expected = "变角次亮采之门"
        assert vm.qmp is not None
        framebuffer = vm.qmp.framebuffer_size()
        if framebuffer != (1280, 800):
            raise TestFailure(
                "The Text Editor Save-row probe requires the acceptance "
                f"framebuffer to be 1280x800, observed {framebuffer[0]}x{framebuffer[1]}"
            )
        self._run_file_driver(
            vm,
            base,
            artifacts,
            mode="file-chinese-editor",
            validator=_validate_chinese_editor_events,
            text_inputs={
                f"chinese-editor-unicode-{index}-codepoint": f"{ord(character):x}"
                for index, character in enumerate(expected)
            },
        )

    def _exercise_super_u(
        self,
        vm: QemuVm,
        base: PromotedBase,
        artifacts: Path,
    ) -> None:
        """Prove Super+U exposes Network Stats and restores its initial state."""

        self._run_shell_driver(
            vm,
            base,
            artifacts,
            mode="shortcut-super-u",
            validator=_validate_super_u_events,
        )

    def _exercise_screenshot_shortcut(
        self,
        vm: QemuVm,
        base: PromotedBase,
        artifacts: Path,
    ) -> None:
        """Prove Super+Shift+S creates a real, decodable PNG screenshot."""

        event = self._run_shell_driver(
            vm,
            base,
            artifacts,
            mode="shortcut-screenshot",
            validator=_validate_screenshot_shortcut_events,
        )
        assert vm.serial is not None
        remote_path = event["path"]
        assert isinstance(remote_path, str)
        screenshot = artifacts / "shortcut-screenshot-created.png"
        _retrieve_file(vm.serial, remote_path, screenshot)
        if not screenshot.is_file() or screenshot.stat().st_size <= 1024:
            raise TestFailure(
                "The screenshot shortcut reported a PNG that the host could not retrieve"
            )
        try:
            with Image.open(screenshot) as image:
                if image.format != "PNG" or min(image.size) < 100:
                    raise TestFailure(
                        "The screenshot shortcut produced an implausible PNG image"
                    )
                image.verify()
        except (OSError, UnidentifiedImageError) as error:
            raise TestFailure(
                f"The screenshot shortcut produced an invalid PNG: {error}"
            ) from error

    def _exercise_tty6_branding(
        self,
        vm: QemuVm,
        base: PromotedBase,
        artifacts: Path,
    ) -> None:
        """Switch to the real tty6, inspect its visible cells, and return."""

        assert vm.serial is not None and vm.qmp is not None
        cursors = self._journal_cursors(vm)
        before = vm.serial.run(
            _graphical_vt_probe_command(self.username),
            timeout=60,
            check=False,
        )
        (artifacts / "tty6-before.txt").write_text(
            before.stdout + "\n", encoding="utf-8"
        )
        previous_vt = _validate_graphical_vt_evidence(
            before.stdout,
            before.returncode,
        )
        if previous_vt == 6:
            raise TestFailure("GNOME unexpectedly occupied tty6 before the shortcut")
        vm.screenshot("tty6-before")

        primary_error: BaseException | None = None
        restore_error: BaseException | None = None
        try:
            vm.qmp.send_key("ctrl-alt-f6")
            console = vm.serial.run(
                _tty6_probe_command(),
                timeout=60,
                check=False,
            )
            (artifacts / "tty6-console.txt").write_text(
                console.stdout + "\n", encoding="utf-8"
            )
            _validate_tty6_evidence(console.stdout, console.returncode)
            vm.screenshot("tty6-visible")
        except BaseException as error:
            primary_error = error
        finally:
            # A failed branding assertion must not strand later independent
            # checks on a text console. Return to the exact VT which owned the
            # active Wayland session rather than assuming that it is tty2.
            try:
                vm.qmp.send_key(f"ctrl-alt-f{previous_vt}")
                restored = vm.serial.run(
                    _graphical_vt_probe_command(
                        self.username,
                        wait_for=previous_vt,
                    ),
                    timeout=60,
                    check=False,
                )
                (artifacts / "tty6-restored.txt").write_text(
                    restored.stdout + "\n", encoding="utf-8"
                )
                _validate_graphical_vt_evidence(
                    restored.stdout,
                    restored.returncode,
                    expected_vt=previous_vt,
                )
                if _graphical_user(vm.serial) != self.username:
                    raise TestFailure(
                        "The original graphical user did not survive the tty6 round trip"
                    )
                vm.screenshot("tty6-restored")
            except BaseException as error:
                restore_error = error

        if primary_error is not None:
            if restore_error is not None:
                primary_error.add_note(
                    "Returning from tty6 also failed: "
                    f"{type(restore_error).__name__}: {restore_error}"
                )
            raise primary_error
        if restore_error is not None:
            raise restore_error
        self._assert_scoped_journal(
            vm,
            base,
            cursors,
            artifacts,
            scope="tty6-branding",
        )
