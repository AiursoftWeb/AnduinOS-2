"""GNOME extension state and dynamic display-resolution behavior."""

from .context import *  # noqa: F403


class DesktopIntegrationChecks:
    def _assert_gnome_extensions(
        self,
        vm: QemuVm,
        scenario: Scenario,
        artifacts: Path,
    ) -> None:
        assert vm.serial is not None
        self.status(scenario.id, "Checking every default GNOME extension's live state")
        excluded = (
            "simple-weather@romanlefler.com",
            "network-stats@gnome.noroadsleft.xyz",
        )
        script = f"""
set -euo pipefail
installed=$(find /usr/share/gnome-shell/extensions -mindepth 1 -maxdepth 1 -type d -printf '%f\\n' | sort)
configured=$(gsettings get org.gnome.shell enabled-extensions | tr "'[]," '\\n' | sed 's/^[[:space:]]*//;s/[[:space:]]*$//' | sed '/^$/d' | sort)
expected=$(printf '%s\\n' "$installed" | grep -Fvx {shlex.quote(excluded[0])} | grep -Fvx {shlex.quote(excluded[1])})
printf '%s\\n' "$installed" > /tmp/anduinos-extensions-installed
printf '%s\\n' "$configured" > /tmp/anduinos-extensions-configured
printf '%s\\n' "$expected" > /tmp/anduinos-extensions-expected
diff -u /tmp/anduinos-extensions-expected /tmp/anduinos-extensions-configured
for uuid in $expected; do
    info=$(LC_ALL=C gnome-extensions info "$uuid")
    printf '\\n[%s]\\n%s\\n' "$uuid" "$info"
    printf '%s\\n' "$info" | grep -Eq '^[[:space:]]*State:[[:space:]]+ACTIVE[[:space:]]*$'
done
for uuid in {shlex.quote(excluded[0])} {shlex.quote(excluded[1])}; do
    printf '%s\\n' "$installed" | grep -Fx "$uuid"
    info=$(LC_ALL=C gnome-extensions info "$uuid")
    printf '\\n[%s]\\n%s\\n' "$uuid" "$info"
    ! printf '%s\\n' "$info" | grep -Eq '^[[:space:]]*State:[[:space:]]+ACTIVE[[:space:]]*$'
done
"""
        result = vm.serial.run(
            _desktop_command(
                self.defaults.username,
                ("bash", "-lc", script),
            ),
            timeout=180,
            check=False,
        )
        (artifacts / "installed-gnome-extensions.txt").write_text(
            result.stdout + "\n", encoding="utf-8"
        )
        if result.returncode != 0:
            raise TestFailure(
                "Default GNOME extension inventory/state is invalid:\n"
                + result.stdout[-8000:]
            )

    def _assert_gnome_extension_errors(
        self,
        vm: QemuVm,
        scenario: Scenario,
        artifacts: Path,
    ) -> None:
        """Fail on GNOME Shell/extension errors even when every UUID is active."""

        assert vm.serial is not None
        policy = self.journal_policy
        system = vm.serial.run(
            render_guest_collection_script(policy),
            timeout=180,
            check=False,
        )
        user = vm.serial.run(
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
        (artifacts / "extension-system-journal.jsonl").write_text(
            system.stdout + "\n", encoding="utf-8"
        )
        (artifacts / "extension-user-journal.jsonl").write_text(
            user.stdout + "\n", encoding="utf-8"
        )
        if system.returncode != 0 or user.returncode != 0:
            raise TestFailure("Could not collect GNOME extension journal evidence")

        entries = (
            *parse_journal_jsonl(system.stdout, "system"),
            *parse_journal_jsonl(user.stdout, "user"),
        )
        extension_entries = tuple(
            entry for entry in entries if _is_gnome_extension_entry(entry)
        )
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
            raise TestFailure("Could not collect extension-policy package versions")
        versions = parse_package_versions(package_result.stdout)
        verdict = policy.classify(extension_entries, scenario, versions)
        (artifacts / "extension-journal-verdict.json").write_text(
            json.dumps(verdict.to_dict(), ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        (artifacts / "extension-journal-verdict.txt").write_text(
            render_verdict(verdict), encoding="utf-8"
        )
        if not verdict.passed:
            raise TestFailure(
                f"GNOME Shell/extensions produced {len(verdict.blockers)} "
                "release-blocking journal error(s); inspect "
                "extension-journal-verdict.json"
            )

    def _exercise_dynamic_resolution(
        self,
        vm: QemuVm,
        scenario: Scenario,
        artifacts: Path,
    ) -> None:
        assert vm.serial is not None
        self.status(scenario.id, "Resizing a real SPICE client and querying Mutter")
        agent = vm.serial.run(
            "set -e\n"
            "pgrep -a spice-vdagent\n"
            "test -c /dev/virtio-ports/com.redhat.spice.0\n",
            timeout=60,
        )
        observations: list[dict[str, object]] = []
        with SpiceDisplayController(vm.spice_socket, artifacts) as viewer:
            baseline, baseline_raw = self._wait_for_display_mode(vm, previous=None)
            for width, height in ((1000, 760), (1420, 920)):
                viewer.resize(width, height)
                mode, raw = self._wait_for_display_mode(
                    vm,
                    previous=(
                        tuple(observations[-1]["mode"])
                        if observations
                        else baseline
                    ),
                )
                observations.append(
                    {
                        "requested_window": [width, height],
                        "mode": list(mode),
                        "gdctl": raw,
                    }
                )
        first = tuple(observations[0]["mode"])
        second = tuple(observations[1]["mode"])
        if first == second or second[0] <= first[0] or second[1] <= first[1]:
            raise TestFailure(
                f"Mutter did not follow increasing SPICE client sizes: {first} -> {second}"
            )
        for observation in observations:
            requested = observation["requested_window"]
            mode = observation["mode"]
            if abs(requested[0] - mode[0]) > 180 or abs(requested[1] - mode[1]) > 180:
                raise TestFailure(
                    "SPICE/Mutter mode is not close to the client geometry: "
                    f"requested={requested}, mode={mode}"
                )
        (artifacts / "installed-spice-resolution.json").write_text(
            json.dumps(
                {
                    "spice_agent": agent.stdout,
                    "baseline": {"mode": list(baseline), "gdctl": baseline_raw},
                    "observations": observations,
                },
                ensure_ascii=False,
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )

    def _wait_for_display_mode(
        self,
        vm: QemuVm,
        previous: tuple[int, int] | None,
    ) -> tuple[tuple[int, int], str]:
        assert vm.serial is not None
        deadline = time.monotonic() + 45
        last = ""
        while time.monotonic() < deadline:
            result = vm.serial.run(
                _desktop_command(
                    self.defaults.username,
                    ("bash", "-lc", "LC_ALL=C gdctl show"),
                ),
                timeout=30,
                check=False,
            )
            last = result.stdout
            match = re.search(r"Current mode.*?([0-9]{3,5})x([0-9]{3,5})@", last, re.DOTALL)
            if result.returncode == 0 and match is not None:
                mode = (int(match.group(1)), int(match.group(2)))
                if previous is None or mode != previous:
                    return mode, last
            time.sleep(1)
        raise TestFailure(
            "Mutter did not report a changed current mode after SPICE resize:\n"
            + last[-4000:]
        )
