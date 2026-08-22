"""AppImage, Windows executable, and desktop file integration behavior."""

from .context import *  # noqa: F403


class FileIntegrationChecks:
    def _prepare_desktop_file_check(
        self,
        vm: QemuVm,
        remote_root: str,
    ) -> str:
        assert vm.serial is not None
        downloads = f"/home/{self.defaults.username}/Downloads"
        vm.serial.run(
            f"install -d -m 0777 {remote_root}/evidence\n"
            f"install -d -o {self.defaults.username} -g {self.defaults.username} "
            f"-m 0755 {shlex.quote(downloads)}"
        )
        self.driver.upload(vm.serial, remote_root)
        return downloads

    def _exercise_appimage_open(
        self,
        vm: QemuVm,
        scenario: Scenario,
        artifacts: Path,
    ) -> None:
        assert vm.serial is not None
        self.status(
            scenario.id,
            "Opening a real architecture-specific Type-2 AppImage through Nautilus",
        )
        fixture_root = artifacts / "host-appimage-fixture"
        appimage = build_appimage_fixture(self.architecture, fixture_root)
        remote_root = "/run/anduinos-acceptance-appimage"
        downloads = self._prepare_desktop_file_check(vm, remote_root)
        vm.serial.upload(appimage, f"{downloads}/{appimage.name}", 0o755)
        blocked_name = "AnduinOS-Blocked.AppImage"
        vm.serial.upload(appimage, f"{downloads}/{blocked_name}", 0o644)
        validation = vm.serial.run(
            f"set -euo pipefail\n"
            f"chown {self.defaults.username}:{self.defaults.username} "
            f"{shlex.quote(downloads)}/{appimage.name} "
            f"{shlex.quote(downloads)}/{blocked_name}\n"
            f"test \"$(dd if={shlex.quote(downloads)}/{appimage.name} "
            "bs=1 skip=8 count=3 status=none | base64 -w0)\" = QUkC\n"
            f"grep -a -q hsqs {shlex.quote(downloads)}/{appimage.name}\n"
            f"offset=$(runuser -u {self.defaults.username} -- "
            f"{shlex.quote(downloads)}/{appimage.name} --appimage-offset)\n"
            f"test \"$offset\" -gt 0\n"
            f"printf 'appimage-payload-offset=%s\\n' \"$offset\"\n"
            f"appimage_mime=$(runuser -u {self.defaults.username} -- "
            f"xdg-mime query filetype {shlex.quote(downloads)}/{appimage.name})\n"
            f"appimage_default=$(runuser -u {self.defaults.username} -- "
            f"xdg-mime query default \"$appimage_mime\")\n"
            "if test -e /usr/share/applications/"
            "com.anduinos.AppImageRunner.desktop; then "
            "appimage_runner_present=yes; else appimage_runner_present=no; fi\n"
            f"appimage_mode=$(stat -c %a {shlex.quote(downloads)}/{appimage.name})\n"
            f"appimage_blocked_mode=$(stat -c %a "
            f"{shlex.quote(downloads)}/{blocked_name})\n"
            f"printf 'appimage-mime=%s\\nappimage-default=%s\\n"
            "appimage-runner-present=%s\\nappimage-mode=%s\\n"
            "appimage-blocked-mode=%s\\n' "
            '"$appimage_mime" "$appimage_default" '
            '"$appimage_runner_present" "$appimage_mode" '
            '"$appimage_blocked_mode"\n'
            f"file {shlex.quote(downloads)}/{appimage.name}\n"
            f"sha256sum {shlex.quote(downloads)}/{appimage.name}",
            timeout=120,
            check=False,
        )
        (artifacts / "appimage-fixture.txt").write_text(
            validation.stdout + "\n", encoding="utf-8"
        )
        if validation.returncode != 0:
            raise TestFailure(
                "AppImage fixture structural validation failed before Nautilus "
                "activation:\n" + validation.stdout[-8000:]
            )
        _validate_appimage_fixture_contract(validation.stdout)
        command = _desktop_command(
            self.defaults.username,
            (
                "python3",
                f"{remote_root}/atspi_driver.py",
                "appimage-file",
                "--evidence",
                f"{remote_root}/evidence",
            ),
        )
        result = _run_with_qmp_key_requests(
            vm,
            command,
            timeout=180,
            request_trace=artifacts / "appimage-input-trace.jsonl",
        )
        (artifacts / "appimage-atspi-events.jsonl").write_text(
            result.stdout + "\n", encoding="utf-8"
        )
        _retrieve_tree(
            vm.serial,
            remote_root,
            artifacts / "guest-appimage-evidence",
        )
        _retrieve_file(
            vm.serial,
            "/tmp/anduinos-nautilus.stdout",
            artifacts / "appimage-nautilus.stdout",
        )
        if result.returncode != 0:
            direct = vm.serial.run(
                _desktop_command(
                    self.defaults.username,
                    (
                        "bash",
                        "-lc",
                        f"{shlex.quote(downloads)}/{appimage.name} "
                        ">/tmp/anduinos-appimage-direct.stdout 2>&1 & "
                        "child=$!; printf 'pid=%s\\n' \"$child\"; sleep 5; "
                        "if kill -0 \"$child\" 2>/dev/null; then "
                        "printf 'state=running\\n'; kill \"$child\"; "
                        "wait \"$child\" || true; "
                        "else wait \"$child\"; status=$?; "
                        "printf 'state=exited\\nexit=%s\\n' \"$status\"; fi; "
                        "cat /tmp/anduinos-appimage-direct.stdout",
                    ),
                ),
                timeout=30,
                check=False,
            )
            (artifacts / "appimage-direct-diagnostic.txt").write_text(
                direct.stdout + "\n", encoding="utf-8"
            )
            raise TestFailure(
                "AppImage desktop dispatch failed through Nautilus AT-SPI:\n"
                + result.stdout[-8000:]
            )
        blocked_command = _desktop_command(
            self.defaults.username,
            (
                "python3",
                f"{remote_root}/atspi_driver.py",
                "appimage-file-non-executable",
                "--evidence",
                f"{remote_root}/evidence/blocked",
            ),
        )
        blocked = _run_with_qmp_key_requests(
            vm,
            blocked_command,
            timeout=120,
            request_trace=artifacts / "appimage-blocked-input-trace.jsonl",
        )
        (artifacts / "appimage-blocked-atspi-events.jsonl").write_text(
            blocked.stdout + "\n", encoding="utf-8"
        )
        _retrieve_tree(
            vm.serial,
            remote_root,
            artifacts / "guest-appimage-evidence",
        )
        if blocked.returncode != 0:
            raise TestFailure(
                "A non-executable AppImage did not preserve the execution "
                "boundary:\n" + blocked.stdout[-8000:]
            )
        _validate_appimage_blocked_events(blocked.stdout)

    def _prepare_windows_executable_fixture(
        self,
        vm: QemuVm,
        artifacts: Path,
        remote_root: str,
        evidence_label: str,
    ) -> tuple[Path, str]:
        assert vm.serial is not None
        fixture_root = artifacts / f"host-windows-executable-{evidence_label}"
        pe = build_windows_executable_fixture(fixture_root)
        downloads = self._prepare_desktop_file_check(vm, remote_root)
        vm.serial.upload(pe, f"{downloads}/{pe.name}", 0o644)
        validation = vm.serial.run(
            f"set -euo pipefail\n"
            f"chown {self.defaults.username}:{self.defaults.username} "
            f"{shlex.quote(downloads)}/{pe.name}\n"
            f"test \"$(head -c2 {shlex.quote(downloads)}/{pe.name})\" = MZ\n"
            f"pe_mime=$(runuser -u {self.defaults.username} -- "
            f"xdg-mime query filetype {shlex.quote(downloads)}/{pe.name})\n"
            f"pe_default=$(runuser -u {self.defaults.username} -- "
            f"xdg-mime query default \"$pe_mime\")\n"
            f"printf 'pe-mime=%s\\npe-default=%s\\n' \"$pe_mime\" \"$pe_default\"\n"
            "command -v exe-thumbnailer\n"
            "test -f /usr/share/thumbnailers/exe-thumbnailer.thumbnailer\n"
            "grep -Fq 'application/vnd.microsoft.portable-executable' "
            "/usr/share/thumbnailers/exe-thumbnailer.thumbnailer\n"
            f"file {shlex.quote(downloads)}/{pe.name}\n"
            f"sha256sum {shlex.quote(downloads)}/{pe.name}",
            timeout=120,
            check=False,
        )
        (artifacts / f"windows-executable-{evidence_label}-fixture.txt").write_text(
            validation.stdout + "\n", encoding="utf-8"
        )
        if validation.returncode != 0:
            raise TestFailure(
                "Windows PE fixture structural validation failed before Nautilus "
                "activation:\n" + validation.stdout[-8000:]
            )
        _validate_windows_executable_fixture_contract(validation.stdout)
        return pe, downloads

    def _exercise_windows_executable_thumbnail(
        self,
        vm: QemuVm,
        scenario: Scenario,
        artifacts: Path,
    ) -> None:
        assert vm.serial is not None
        self.status(
            scenario.id,
            "Generating the embedded PE icon through Nautilus' thumbnailer",
        )
        remote_root = "/run/anduinos-acceptance-windows-thumbnail"
        self._prepare_windows_executable_fixture(
            vm,
            artifacts,
            remote_root,
            "thumbnail",
        )
        command = _desktop_command(
            self.defaults.username,
            (
                "python3",
                f"{remote_root}/atspi_driver.py",
                "windows-executable-thumbnail",
                "--evidence",
                f"{remote_root}/evidence",
            ),
        )
        result = vm.serial.run(command, timeout=180, check=False)
        (artifacts / "windows-executable-thumbnail-events.jsonl").write_text(
            result.stdout + "\n", encoding="utf-8"
        )
        _retrieve_tree(
            vm.serial,
            remote_root,
            artifacts / "guest-windows-thumbnail-evidence",
        )
        if result.returncode != 0:
            raise TestFailure(
                "Nautilus did not generate the local PE fixture thumbnail:\n"
                + result.stdout[-8000:]
            )
        desktop_evidence = _validate_windows_executable_thumbnail_events(
            result.stdout,
            self.defaults.username,
        )
        thumbnail_path = desktop_evidence["cache_path"]
        assert isinstance(thumbnail_path, str)
        thumbnail = artifacts / "windows-executable-thumbnail.png"
        _retrieve_file(vm.serial, thumbnail_path, thumbnail)
        assert_cpu_z_thumbnail(
            thumbnail,
            artifacts / "windows-executable-thumbnail-analysis.json",
        )

    def _exercise_windows_executable_open(
        self,
        vm: QemuVm,
        scenario: Scenario,
        artifacts: Path,
    ) -> None:
        assert vm.serial is not None
        self.status(
            scenario.id,
            "Opening a structurally valid CPU-Z-named PE through Nautilus",
        )
        remote_root = "/run/anduinos-acceptance-windows-open"
        pe, downloads = self._prepare_windows_executable_fixture(
            vm,
            artifacts,
            remote_root,
            "open",
        )
        command = _desktop_command(
            self.defaults.username,
            (
                "python3",
                f"{remote_root}/atspi_driver.py",
                "windows-executable-file",
                "--evidence",
                f"{remote_root}/evidence",
            ),
        )
        result = _run_with_qmp_key_requests(
            vm,
            command,
            timeout=180,
            request_trace=artifacts / "windows-executable-input-trace.jsonl",
        )
        (artifacts / "windows-executable-atspi-events.jsonl").write_text(
            result.stdout + "\n", encoding="utf-8"
        )
        _retrieve_tree(
            vm.serial,
            remote_root,
            artifacts / "guest-windows-executable-evidence",
        )
        _retrieve_file(
            vm.serial,
            "/tmp/anduinos-nautilus.stdout",
            artifacts / "windows-executable-nautilus.stdout",
        )
        if result.returncode != 0:
            diagnostic = vm.serial.run(
                _desktop_command(
                    self.defaults.username,
                    (
                        "bash",
                        "-lc",
                        f"mime=$(xdg-mime query filetype "
                        f"{shlex.quote(downloads)}/{pe.name}); "
                        "printf 'mime=%s\\ndefault=%s\\n' \"$mime\" "
                        "\"$(xdg-mime query default \"$mime\")\"; "
                        "pgrep -af anduinos-exe-runner || true",
                    ),
                ),
                timeout=30,
                check=False,
            )
            (artifacts / "windows-executable-direct-diagnostic.txt").write_text(
                diagnostic.stdout + "\n", encoding="utf-8"
            )
            raise TestFailure(
                "Windows executable desktop dispatch failed through Nautilus "
                "AT-SPI:\n" + result.stdout[-8000:]
            )
        _validate_windows_executable_open_events(result.stdout)
