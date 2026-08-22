"""Public CPU-Z, Spotify, WeChat, and Nextcloud integration behavior."""

from .context import *  # noqa: F403


class PublicApplicationChecks:
    def _exercise_spotify_public(
        self,
        vm: QemuVm,
        base: PromotedBase,
        artifacts: Path,
    ) -> None:
        """Refresh Flathub, then open its current Spotify details in Software."""

        assert vm.serial is not None
        catalog = vm.serial.run(
            _spotify_public_catalog_command(),
            timeout=900,
            check=False,
        )
        (artifacts / "spotify-public-catalog.txt").write_text(
            catalog.stdout + "\n", encoding="utf-8"
        )
        try:
            _validate_spotify_public_catalog_evidence(
                catalog.stdout,
                catalog.returncode,
            )
        except TestFailure as error:
            try:
                classification = _last_value(
                    catalog.stdout,
                    "spotify-public-failure-class",
                )
            except TestFailure:
                classification = "product-regression"
            if classification not in {"external-catalog", "product-regression"}:
                classification = "product-regression"
            (artifacts / "spotify-public-classification.txt").write_text(
                f"classification={classification}\nphase=catalog\n",
                encoding="utf-8",
            )
            raise TestFailure(f"[{classification}] {error}") from error

        reload_result = vm.serial.run(
            _desktop_command(
                self.username,
                (
                    "bash",
                    "-lc",
                    "set -euo pipefail; "
                    "systemctl --user stop gnome-software.service; "
                    "systemctl --user start gnome-software.service; "
                    "for _ in $(seq 1 60); do "
                    "systemctl --user is-active --quiet gnome-software.service "
                    "&& break; sleep 1; done; "
                    "systemctl --user is-active gnome-software.service; "
                    "printf 'spotify-public-software-reload=passed\\n'",
                ),
            ),
            timeout=120,
            check=False,
        )
        (artifacts / "spotify-public-software-reload.txt").write_text(
            reload_result.stdout + "\n", encoding="utf-8"
        )
        if (
            reload_result.returncode != 0
            or _last_value(
                reload_result.stdout,
                "spotify-public-software-reload",
            )
            != "passed"
        ):
            (artifacts / "spotify-public-classification.txt").write_text(
                "classification=product-regression\nphase=software-reload\n",
                encoding="utf-8",
            )
            raise TestFailure(
                "[product-regression] GNOME Software did not reload after the "
                "public AppStream refresh:\n"
                + reload_result.stdout[-8000:]
            )

        try:
            self._run_shell_driver(
                vm,
                base,
                artifacts,
                mode="shell-spotify-store",
                validator=_validate_spotify_store_events,
                text_inputs={"spotify-search-text": "Spotify"},
            )
        except TestFailure as error:
            (artifacts / "spotify-public-classification.txt").write_text(
                "classification=product-regression\nphase=desktop-ui\n",
                encoding="utf-8",
            )
            raise TestFailure(
                "[product-regression] the current public catalog resolved Spotify, "
                "but ArcMenu/GNOME Software could not open its details page: "
                f"{error}"
            ) from error
        (artifacts / "spotify-public-classification.txt").write_text(
            "classification=none\nphase=passed\n",
            encoding="utf-8",
        )

    def _exercise_wechat_install(
        self,
        vm: QemuVm,
        base: PromotedBase,
        artifacts: Path,
    ) -> None:
        """Install current native WeChat and launch it from the real start menu."""

        assert vm.serial is not None
        installed = vm.serial.run(
            _wechat_install_command(),
            timeout=1800,
            check=False,
        )
        (artifacts / "wechat-install.txt").write_text(
            installed.stdout + "\n", encoding="utf-8"
        )
        try:
            _validate_wechat_install_evidence(installed.stdout, installed.returncode)
        except TestFailure as error:
            classification = _safe_failure_class(
                installed.stdout,
                "wechat-failure-class",
                {"external-catalog", "external-artifact", "product-regression"},
            )
            (artifacts / "wechat-classification.txt").write_text(
                f"classification={classification}\nphase=install\n",
                encoding="utf-8",
            )
            raise TestFailure(f"[{classification}] {error}") from error

        try:
            self._run_shell_driver(
                vm,
                base,
                artifacts,
                mode="public-wechat-install",
                validator=_validate_wechat_install_events,
                text_inputs={"wechat-search-text": "WeChat"},
                screenshot_validator=lambda frame, evidence: (
                    assert_wechat_login_window(
                        frame,
                        artifacts / "wechat-login-window-analysis.json",
                        evidence,
                    )
                ),
            )
        except TestFailure as error:
            (artifacts / "wechat-classification.txt").write_text(
                "classification=product-regression\nphase=launch\n",
                encoding="utf-8",
            )
            raise TestFailure(
                "[product-regression] WeChat installed successfully but did not "
                f"launch from ArcMenu: {error}"
            ) from error
        (artifacts / "wechat-classification.txt").write_text(
            "classification=none\nphase=launched\n",
            encoding="utf-8",
        )

    def _exercise_wechat_tray(
        self,
        vm: QemuVm,
        base: PromotedBase,
        artifacts: Path,
    ) -> None:
        """Close WeChat to its lower-right indicator and restore the same app."""

        try:
            self._run_shell_driver(
                vm,
                base,
                artifacts,
                mode="public-wechat-tray",
                validator=_validate_wechat_tray_events,
                screenshot_validator=lambda frame, evidence: (
                    assert_wechat_login_window(
                        frame,
                        artifacts / "wechat-restored-window-analysis.json",
                        evidence,
                    )
                ),
            )
        except TestFailure as error:
            (artifacts / "wechat-tray-classification.txt").write_text(
                "classification=product-regression\nphase=tray-roundtrip\n",
                encoding="utf-8",
            )
            raise TestFailure(
                "[product-regression] WeChat did not preserve and restore its "
                f"process through the lower-right AppIndicator: {error}"
            ) from error
        (artifacts / "wechat-tray-classification.txt").write_text(
            "classification=none\nphase=passed\n",
            encoding="utf-8",
        )

    def _exercise_nextcloud_ppa(
        self,
        vm: QemuVm,
        base: PromotedBase,
        artifacts: Path,
    ) -> None:
        """Add the public Nextcloud PPA through the installed user's sudo."""

        assert vm.serial is not None
        sudoers = "/etc/sudoers.d/anduinos-acceptance-nextcloud-ppa"
        rule = (
            f"{self.username} ALL=(root) NOPASSWD: "
            "/usr/bin/add-apt-repository -y "
            r"ppa\:nextcloud-devs/client"
        )
        payload = base64.b64encode((rule + "\n").encode("utf-8")).decode("ascii")
        setup = vm.serial.run(
            "set -euo pipefail\n"
            "command -v add-apt-repository\n"
            "dpkg-query -W software-properties-common\n"
            f"printf '%s' {shlex.quote(payload)} | base64 -d > {sudoers}\n"
            f"chmod 0440 {sudoers}\n"
            f"visudo -cf {sudoers}\n"
            "printf 'nextcloud-ppa-sudo-policy=ready\\n'",
            timeout=60,
            check=False,
        )
        (artifacts / "nextcloud-ppa-preflight.txt").write_text(
            setup.stdout + "\n", encoding="utf-8"
        )
        if setup.returncode != 0:
            raise TestFailure(
                "Could not prepare the exact Nextcloud PPA sudo command:\n"
                + setup.stdout[-8000:]
            )

        cursors = self._journal_cursors(vm)
        command = None
        source = None
        cleanup = None
        try:
            command = vm.serial.run(
                _desktop_command(
                    self.username,
                    (
                        "bash",
                        "-lc",
                        "set -euo pipefail; "
                        "printf 'invoking-user=%s\\n' \"$(id -un)\"; "
                        "printf '%s\\n' "
                        "'command=sudo add-apt-repository -y "
                        "ppa:nextcloud-devs/client'; "
                        "sudo -n /usr/bin/add-apt-repository -y "
                        "ppa:nextcloud-devs/client; "
                        "printf 'repository-command=passed\\n'",
                    ),
                ),
                timeout=600,
                check=False,
            )
            (artifacts / "nextcloud-ppa-command.txt").write_text(
                command.stdout + "\n", encoding="utf-8"
            )
            source = vm.serial.run(
                _nextcloud_ppa_source_probe_command(),
                timeout=120,
                check=False,
            )
            (artifacts / "nextcloud-ppa-source.txt").write_text(
                source.stdout + "\n", encoding="utf-8"
            )
        finally:
            cleanup = vm.serial.run(
                f"rm -f {sudoers}; "
                f"test ! -e {sudoers}; "
                "printf 'nextcloud-ppa-sudo-policy=removed\\n'",
                timeout=30,
                check=False,
            )
            (artifacts / "nextcloud-ppa-cleanup.txt").write_text(
                cleanup.stdout + "\n", encoding="utf-8"
            )

        assert command is not None and source is not None and cleanup is not None
        evidence = "\n".join((command.stdout, source.stdout, cleanup.stdout))
        _validate_nextcloud_ppa_evidence(
            evidence,
            command.returncode or source.returncode or cleanup.returncode,
            self.username,
        )
        self._assert_scoped_journal(
            vm,
            base,
            cursors,
            artifacts,
            scope="nextcloud-ppa",
        )

    def _exercise_public_cpu_z(
        self,
        vm: QemuVm,
        base: PromotedBase,
        artifacts: Path,
    ) -> None:
        """Download, preview, and dispatch the pinned real CPU-Z executable."""

        assert vm.serial is not None and vm.qmp is not None
        remote = "/run/anduinos-feature-public-cpuz"
        vm.serial.run(
            f"install -d -m 0777 {shlex.quote(remote + '/evidence')}",
            timeout=30,
        )
        self.driver.upload(vm.serial, remote)

        downloaded = vm.serial.run(
            _desktop_command(
                self.username,
                ("bash", "-lc", _cpu_z_download_command()),
            ),
            timeout=600,
            check=False,
        )
        (artifacts / "cpu-z-download.txt").write_text(
            downloaded.stdout + "\n", encoding="utf-8"
        )
        _validate_cpu_z_download_evidence(downloaded.stdout, downloaded.returncode)

        cursors = self._journal_cursors(vm)
        command = _desktop_command(
            self.username,
            (
                "python3",
                f"{remote}/atspi_driver.py",
                "public-cpuz-file",
                "--filename",
                _CPU_Z_MEMBER,
                "--evidence",
                f"{remote}/evidence",
            ),
        )
        result = _run_with_qmp_key_requests(
            vm,
            command,
            timeout=300,
            request_trace=artifacts / "cpu-z-qmp-requests.jsonl",
        )
        (artifacts / "cpu-z-events.jsonl").write_text(
            result.stdout + "\n", encoding="utf-8"
        )
        _retrieve_tree(vm.serial, remote, artifacts / "guest-cpu-z-evidence")
        if result.returncode != 0:
            raise TestFailure(
                "The real CPU-Z Nautilus workflow failed:\n"
                + result.stdout[-8000:]
            )
        evidence = _validate_cpu_z_events(result.stdout, self.username)
        cache_path = evidence["cache_path"]
        assert isinstance(cache_path, str)
        thumbnail = artifacts / "cpu-z-thumbnail.png"
        _retrieve_file(vm.serial, cache_path, thumbnail)
        assert_cpu_z_thumbnail(
            thumbnail,
            artifacts / "cpu-z-thumbnail-analysis.json",
        )
        vm.screenshot("cpu-z-exe-runner-prerequisite")
        vm.qmp.send_key("alt-f4")
        time.sleep(1)
        self._assert_scoped_journal(
            vm,
            base,
            cursors,
            artifacts,
            scope="public-cpu-z",
        )
