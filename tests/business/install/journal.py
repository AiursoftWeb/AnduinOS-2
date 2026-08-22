"""Action-scoped, idle-boot journal, and passive Plymouth behavior."""

from .context import *  # noqa: F403


class JournalChecks:
    def _capture_journal_cursors(self, vm: QemuVm) -> dict[str, str]:
        assert vm.serial is not None
        command = (
            "journalctl -b -n 0 --show-cursor --no-pager | "
            "sed -n 's/^-- cursor: //p'"
        )
        system = vm.serial.run(command, timeout=30, check=False)
        user = vm.serial.run(
            _desktop_command(
                self.defaults.username,
                ("bash", "-lc", command),
            ),
            timeout=30,
            check=False,
        )
        system_values = system.stdout.strip().splitlines()
        user_values = user.stdout.strip().splitlines()
        if (
            system.returncode != 0
            or user.returncode != 0
            or not system_values
            or not user_values
        ):
            raise TestFailure("Could not establish installed desktop journal cursors")
        return {"system": system_values[-1], "user": user_values[-1]}

    def _assert_action_scoped_journal(
        self,
        vm: QemuVm,
        scenario: Scenario,
        cursors: dict[str, str],
        artifacts: Path,
    ) -> None:
        """Classify only messages created by the installed desktop exercises."""

        assert vm.serial is not None
        if set(cursors) != {"system", "user"} or not all(cursors.values()):
            raise TestFailure("Installed desktop journal cursors are incomplete")
        policy = self.journal_policy
        system = vm.serial.run(
            render_guest_collection_script(
                policy,
                after_cursor=cursors["system"],
            ),
            timeout=180,
            check=False,
        )
        user = vm.serial.run(
            _desktop_command(
                self.defaults.username,
                (
                    "bash",
                    "-lc",
                    render_guest_collection_script(
                        policy,
                        user=True,
                        after_cursor=cursors["user"],
                    ),
                ),
            ),
            timeout=180,
            check=False,
        )
        (artifacts / "desktop-actions-system-journal.jsonl").write_text(
            system.stdout + "\n", encoding="utf-8"
        )
        (artifacts / "desktop-actions-user-journal.jsonl").write_text(
            user.stdout + "\n", encoding="utf-8"
        )
        if system.returncode != 0 or user.returncode != 0:
            raise TestFailure("Could not collect action-scoped desktop journal")
        packages = " ".join(shlex.quote(item) for item in policy.packages)
        package_result = vm.serial.run(
            "set -uo pipefail\n"
            f"for package in {packages}; do\n"
            "  dpkg-query -W -f='${Package}\\t${Version}\\n' \"$package\" "
            "2>/dev/null || true\n"
            "done",
            timeout=60,
            check=False,
        )
        if package_result.returncode != 0:
            raise TestFailure("Could not collect action-journal package versions")
        entries = (
            *parse_journal_jsonl(system.stdout, "system"),
            *parse_journal_jsonl(user.stdout, "user"),
        )
        verdict = policy.classify(
            entries,
            scenario,
            parse_package_versions(package_result.stdout),
            action_scope="installed-desktop-contracts",
        )
        (artifacts / "desktop-actions-journal-verdict.json").write_text(
            json.dumps(verdict.to_dict(), ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        (artifacts / "desktop-actions-journal-verdict.txt").write_text(
            render_verdict(verdict), encoding="utf-8"
        )
        if not verdict.passed:
            raise TestFailure(
                f"Installed desktop actions produced {len(verdict.blockers)} "
                "release-blocking journal error(s); inspect "
                "desktop-actions-journal-verdict.json"
            )

    def _assert_journal_health(
        self,
        vm: QemuVm,
        scenario: Scenario,
        artifacts: Path,
    ) -> None:
        assert vm.serial is not None
        self.status(
            scenario.id,
            "Classifying journal blockers and versioned known diagnostics",
        )
        policy = self.journal_policy
        shutil.copy2(
            Path(__file__).parents[2] / "assertions/journal-policy.json",
            artifacts / "journal-policy.json",
        )
        system_journal = vm.serial.run(
            render_guest_collection_script(policy),
            timeout=180,
            check=False,
        )
        user_journal = vm.serial.run(
            _desktop_command(
                self.defaults.username,
                (
                    "bash",
                    "-lc",
                    render_guest_collection_script(policy, user=True),
                ),
            ),
            timeout=180,
            check=False,
        )
        (artifacts / "installed-system-journal.jsonl").write_text(
            system_journal.stdout + "\n", encoding="utf-8"
        )
        (artifacts / "installed-user-journal.jsonl").write_text(
            user_journal.stdout + "\n", encoding="utf-8"
        )
        if system_journal.returncode != 0 or user_journal.returncode != 0:
            raise TestFailure(
                "Could not collect structured system and user journal evidence"
            )

        system_units = vm.serial.run(
            "systemctl --failed --no-legend --plain",
            timeout=60,
            check=False,
        )
        user_units = vm.serial.run(
            _desktop_command(
                self.defaults.username,
                (
                    "bash",
                    "-lc",
                    "systemctl --user --failed --no-legend --plain",
                ),
            ),
            timeout=60,
            check=False,
        )
        if system_units.returncode != 0 or user_units.returncode != 0:
            raise TestFailure("Could not query failed systemd units")

        packages = " ".join(shlex.quote(item) for item in policy.packages)
        package_result = vm.serial.run(
            "set -uo pipefail\n"
            f"for package in {packages}; do\n"
            "  dpkg-query -W -f='${Package}\\t${Version}\\n' "
            '"$package" 2>/dev/null || true\n'
            "done",
            timeout=60,
        )
        package_versions = parse_package_versions(package_result.stdout)
        (artifacts / "installed-journal-package-versions.txt").write_text(
            package_result.stdout + "\n", encoding="utf-8"
        )

        functional_script = r"""
set -euo pipefail
shell_pid=$(pgrep -n -x gnome-shell)
keyboard_pid=$(pgrep -n -x gsd-keyboard)
keyring_pid=$(pgrep -n -x gnome-keyring-d)
ding_pid=$(pgrep -n -f '^gjs .*/ding@rastersoft\.com/app/ding\.js( |$)')
test -n "$shell_pid"
test -n "$keyboard_pid"
test -n "$keyring_pid"
test -n "$ding_pid"
sources=$(gsettings get org.gnome.desktop.input-sources sources)
printf 'gnome-shell-pid=%s\n' "$shell_pid"
printf 'gsd-keyboard-pid=%s\n' "$keyboard_pid"
printf 'gnome-keyring-pid=%s\n' "$keyring_pid"
printf 'ding-pid=%s\n' "$ding_pid"
printf 'input-sources=%s\n' "$sources"
"""
        if scenario.rime:
            functional_script += "printf '%s' \"$sources\" | grep -q \"'ibus', 'rime'\"\n"
        functional = vm.serial.run(
            _desktop_command(
                self.defaults.username,
                ("bash", "-lc", functional_script),
            ),
            timeout=60,
            check=False,
        )
        (artifacts / "installed-journal-functional-health.txt").write_text(
            functional.stdout + "\n", encoding="utf-8"
        )

        entries = parse_journal_jsonl(system_journal.stdout, "system") + (
            parse_journal_jsonl(user_journal.stdout, "user")
        )
        verdict = policy.classify(
            entries,
            scenario,
            package_versions,
            failed_system_units=system_units.stdout.splitlines(),
            failed_user_units=user_units.stdout.splitlines(),
        )
        report = render_verdict(verdict)
        (artifacts / "installed-journal-verdict.json").write_text(
            json.dumps(verdict.to_dict(), indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        (artifacts / "installed-system-journal-gate.txt").write_text(
            "=== systemctl --failed ===\n"
            + (system_units.stdout or "none")
            + "\n\n"
            + report,
            encoding="utf-8",
        )
        (artifacts / "installed-user-journal-gate.txt").write_text(
            "=== systemctl --user --failed ===\n"
            + (user_units.stdout or "none")
            + "\n\n"
            + report,
            encoding="utf-8",
        )
        self.status(
            scenario.id,
            f"Journal: {len(verdict.blockers)} blockers, "
            f"{len(verdict.known_diagnostics)} known diagnostics",
        )
        self._check_note(
            scenario,
            "journal.boot-and-idle",
            f"{len(verdict.blockers)} blockers; "
            f"{len(verdict.known_diagnostics)} known diagnostics",
        )
        failures = []
        if functional.returncode != 0:
            failures.append(
                "GNOME Shell, keyboard, keyring, or input-source functional "
                "health check failed"
            )
        if not verdict.passed:
            failures.append(
                f"{len(verdict.blockers)} unexpected journal/systemd blocker(s)"
            )
        if failures:
            raise TestFailure(
                "; ".join(failures)
                + "; inspect installed-journal-verdict.json and "
                "installed-journal-functional-health.txt"
            )

    def _assert_passive_plymouth_boot(
        self,
        vm: QemuVm,
        scenario: Scenario,
        artifacts: Path,
    ) -> None:
        """Observe an ordinary installed boot without editing or driving GRUB."""

        watermark = artifacts / "plymouth-watermark.png"
        if not watermark.is_file() or not watermark.stat().st_size:
            raise TestFailure("Installed AnduinOS Plymouth watermark is missing")
        self.status(
            scenario.id,
            "Watching an unmodified installed boot for the AnduinOS Plymouth logo",
        )
        vm.start(attach_iso=False, phase="plymouth-passive")
        deadline = time.monotonic() + self.options.boot_timeout_seconds
        probe = artifacts / "plymouth-probe.png"
        observations: list[dict[str, object]] = []
        matched: dict[str, object] | None = None
        try:
            while time.monotonic() < deadline and vm.running:
                try:
                    probe = vm.screenshot("plymouth-probe")
                    result = plymouth_match(probe, watermark)
                    result["seconds"] = round(
                        self.options.boot_timeout_seconds
                        - (deadline - time.monotonic()),
                        2,
                    )
                    observations.append(result)
                    if result.get("matched") is True:
                        matched = result
                        shutil.copy2(probe, artifacts / "plymouth-branding.png")
                        break
                except (OSError, ProtocolError):
                    pass
                time.sleep(0.2 if self.architecture is Architecture.AMD64 else 0.5)
        finally:
            vm.stop()
        report = {
            "matched": matched is not None,
            "match": matched,
            "observations": observations,
            "boot_mode": "passive; ISO detached; no GRUB or guest input",
        }
        (artifacts / "plymouth-analysis.json").write_text(
            json.dumps(report, indent=2) + "\n", encoding="utf-8"
        )
        probe.unlink(missing_ok=True)
        if matched is None:
            raise TestFailure(
                "An ordinary installed boot never displayed the installed "
                "AnduinOS Plymouth watermark"
            )
