"""Rime input and action-scoped journal behavior."""

from .context import *  # noqa: F403


class InputChecks:
    def _exercise_rime_input(
        self,
        vm: QemuVm,
        base: PromotedBase,
        artifacts: Path,
    ) -> None:
        assert vm.serial is not None and vm.qmp is not None
        remote = "/run/anduinos-feature-rime"
        vm.serial.run(f"install -d -m 0777 {remote}/evidence")
        self.driver.upload(vm.serial, remote)
        vm.serial.upload(self.input_fixture, f"{remote}/input_fixture.py", 0o755)

        precondition = vm.serial.run(
            _desktop_command(
                self.username,
                (
                    "bash",
                    "-lc",
                    "set -e; sources=$(gsettings get org.gnome.desktop.input-sources sources); "
                    "engine=$(ibus engine); printf 'sources=%s\\nengine=%s\\n' \"$sources\" \"$engine\"; "
                    "printf '%s\\n' 'user-manager-input-environment:'; "
                    "systemctl --user show-environment | "
                    "grep -E '^(GTK_IM_MODULE|QT_IM_MODULE|QT_IM_MODULES|XMODIFIERS|IBUS)=' || true; "
                    "printf '%s' \"$sources\" | grep -q \"'ibus', 'rime'\"; "
                    "test \"$engine\" != rime",
                ),
            ),
            timeout=60,
        )
        (artifacts / "rime-precondition.txt").write_text(
            precondition.stdout + "\n", encoding="utf-8"
        )
        original_engine = _last_value(precondition.stdout, "engine")

        launch = _desktop_command(
            self.username,
            (
                "bash",
                "-lc",
                "systemd-run --user --unit=anduinos-rime-input-fixture "
                "--collect --property=Type=exec "
                "--setenv=HOME=\"$HOME\" "
                "--setenv=XDG_RUNTIME_DIR=\"$XDG_RUNTIME_DIR\" "
                "--setenv=DBUS_SESSION_BUS_ADDRESS=\"$DBUS_SESSION_BUS_ADDRESS\" "
                "--setenv=WAYLAND_DISPLAY=\"$WAYLAND_DISPLAY\" "
                "--setenv=DISPLAY=\"$DISPLAY\" --setenv=NO_AT_BRIDGE=0 "
                f"python3 {remote}/input_fixture.py",
            ),
        )
        vm.serial.run(launch, timeout=60)
        prepared = vm.serial.run(
            _desktop_command(
                self.username,
                (
                    "python3",
                    f"{remote}/atspi_driver.py",
                    "rime-input-prepare",
                    "--evidence",
                    f"{remote}/evidence",
                ),
            ),
            timeout=120,
            check=False,
        )
        (artifacts / "rime-atspi-events.jsonl").write_text(
            prepared.stdout + "\n", encoding="utf-8"
        )
        if prepared.returncode != 0:
            _retrieve_tree(vm.serial, remote, artifacts / "guest-rime-evidence")
            raise TestFailure(
                "Could not focus the real GTK Rime fixture:\n"
                + prepared.stdout[-8000:]
            )

        cursors = self._journal_cursors(vm)
        vm.qmp.send_key("meta_l-spc")
        self._wait_for_ibus_engine(vm, "rime")
        self._wait_for_rime_ready(vm, artifacts)
        vm.qmp.type_text("nihao", interval=0.10)
        vm.qmp.send_key("spc")
        time.sleep(2)
        asserted = vm.serial.run(
            _desktop_command(
                self.username,
                (
                    "python3",
                    f"{remote}/atspi_driver.py",
                    "rime-input-assert",
                    "--expected",
                    "你好",
                    "--evidence",
                    f"{remote}/evidence",
                ),
            ),
            timeout=120,
            check=False,
        )
        with (artifacts / "rime-atspi-events.jsonl").open(
            "a", encoding="utf-8"
        ) as stream:
            stream.write(asserted.stdout + "\n")
        if asserted.returncode != 0:
            _retrieve_tree(vm.serial, remote, artifacts / "guest-rime-evidence")
            raise TestFailure(
                "Rime did not commit the exact expected Chinese text:\n"
                + asserted.stdout[-8000:]
            )
        _retrieve_tree(vm.serial, remote, artifacts / "guest-rime-evidence")
        _validate_rime_evidence(
            artifacts / "guest-rime-evidence" / "rime-input-result.json",
            "你好",
        )

        vm.qmp.send_key("meta_l-spc")
        self._wait_for_ibus_engine(vm, original_engine)
        self._assert_scoped_journal(vm, base, cursors, artifacts)
        vm.screenshot("rime-committed-chinese")
        vm.serial.run(
            _desktop_command(
                self.username,
                ("systemctl", "--user", "stop", "anduinos-rime-input-fixture.service"),
            ),
            timeout=30,
            check=False,
        )

    def _wait_for_ibus_engine(
        self,
        vm: QemuVm,
        expected: str,
        timeout: float = 30,
    ) -> None:
        assert vm.serial is not None
        deadline = time.monotonic() + timeout
        observed = ""
        while time.monotonic() < deadline:
            result = vm.serial.run(
                _desktop_command(self.username, ("ibus", "engine")),
                timeout=30,
                check=False,
            )
            observed = result.stdout.strip().splitlines()[-1] if result.stdout.strip() else ""
            if result.returncode == 0 and observed == expected:
                return
            time.sleep(0.5)
        raise TestFailure(
            f"IBus engine did not become {expected!r}; last observed {observed!r}"
        )

    def _wait_for_rime_ready(self, vm: QemuVm, artifacts: Path) -> None:
        """Wait for first-use deployment, not merely the IBus engine name.

        Rime compiles its schema and large dictionaries the first time a fresh
        account activates the engine.  ``ibus engine`` changes before that
        deployment is complete, so sending keys immediately races the real
        input method and can make a healthy installation look like raw ASCII
        input.  The generated schema and binary dictionaries are the durable
        readiness contract used by the engine itself.
        """

        assert vm.serial is not None
        command = _desktop_command(
            self.username,
            (
                "bash",
                "-lc",
                "set -e; root=$HOME/.config/ibus/rime; "
                "deadline=$((SECONDS + 180)); "
                "while ! { test -s \"$root/build/rime_ice.schema.yaml\" && "
                "test -s \"$root/build/rime_ice.table.bin\" && "
                "test -s \"$root/build/rime_ice.prism.bin\" && "
                "test -s \"$root/user.yaml\"; }; do "
                "if (( SECONDS >= deadline )); then "
                "printf '%s\\n' 'Rime first-use deployment did not finish'; "
                "find \"$root\" -maxdepth 2 -type f -printf '%s %p\\n' 2>/dev/null | sort; "
                "exit 1; fi; sleep 1; done; "
                "printf '%s\\n' 'Rime first-use deployment is ready'; "
                "find \"$root\" -maxdepth 2 -type f -printf '%s %p\\n' | sort",
            ),
        )
        result = vm.serial.run(command, timeout=210, check=False)
        (artifacts / "rime-deployment.txt").write_text(
            result.stdout + "\n", encoding="utf-8"
        )
        if result.returncode != 0:
            raise TestFailure(
                "Rime did not finish its first-use deployment:\n"
                + result.stdout[-8000:]
            )

    def _journal_cursors(self, vm: QemuVm) -> dict[str, str]:
        assert vm.serial is not None
        script = "journalctl -b -n 0 --show-cursor --no-pager | sed -n 's/^-- cursor: //p'"
        system = vm.serial.run(script, timeout=30).stdout.strip().splitlines()
        user = vm.serial.run(
            _desktop_command(self.username, ("bash", "-lc", script)),
            timeout=30,
        ).stdout.strip().splitlines()
        if not system or not user:
            raise TestFailure("Could not establish system and user journal cursors")
        return {"system": system[-1], "user": user[-1]}

    def _assert_scoped_journal(
        self,
        vm: QemuVm,
        base: PromotedBase,
        cursors: dict[str, str],
        artifacts: Path,
        *,
        scope: str = "rime",
    ) -> None:
        assert vm.serial is not None
        system = vm.serial.run(
            render_guest_collection_script(
                self.journal_policy,
                after_cursor=cursors["system"],
            ),
            timeout=120,
            check=False,
        )
        user = vm.serial.run(
            _desktop_command(
                self.username,
                (
                    "bash",
                    "-lc",
                    render_guest_collection_script(
                        self.journal_policy,
                        user=True,
                        after_cursor=cursors["user"],
                    ),
                ),
            ),
            timeout=120,
            check=False,
        )
        (artifacts / f"{scope}-system-journal.jsonl").write_text(
            system.stdout + "\n", encoding="utf-8"
        )
        (artifacts / f"{scope}-user-journal.jsonl").write_text(
            user.stdout + "\n", encoding="utf-8"
        )
        if system.returncode != 0 or user.returncode != 0:
            raise TestFailure("Could not collect action-scoped Rime journal evidence")
        packages = " ".join(shlex.quote(item) for item in self.journal_policy.packages)
        package_result = vm.serial.run(
            "set -uo pipefail\n"
            f"for package in {packages}; do\n"
            "  dpkg-query -W -f='${Package}\\t${Version}\\n' \"$package\" "
            "2>/dev/null || true\n"
            "done",
            timeout=60,
        )
        versions = parse_package_versions(package_result.stdout)
        entries = (
            *parse_journal_jsonl(system.stdout, "system"),
            *parse_journal_jsonl(user.stdout, "user"),
        )
        verdict = self.journal_policy.classify(
            entries,
            base.scenario,
            versions,
            action_scope=scope,
        )
        (artifacts / f"{scope}-journal-verdict.json").write_text(
            json.dumps(verdict.to_dict(), ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        (artifacts / f"{scope}-journal-verdict.txt").write_text(
            render_verdict(verdict) + "\n", encoding="utf-8"
        )
        shutil.copy2(
            self.framework_root / "assertions/journal-policy.json",
            artifacts / "journal-policy.json",
        )
        if not verdict.passed:
            raise TestFailure(
                f"{scope} produced action-scoped journal blockers:\n"
                + render_verdict(verdict)
            )
