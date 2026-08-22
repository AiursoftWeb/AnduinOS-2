"""Accounts, GDM, password, and theme oracles."""

from unit.support import *  # noqa: F403


class DesktopAccountOracleTests(FeatureOracleCase):
    def test_account_creation_oracle_rejects_the_wrong_details_action(self):
        passing = "\n".join(
            json.dumps(event, ensure_ascii=False)
            for event in (
                {
                    "event": "focused-activation",
                    "target": "add_user",
                    "method": "localized-mnemonic",
                },
                {"event": "set-radio", "target": "set_password_now"},
                {
                    "event": "focused-activation",
                    "target": "next",
                    "method": "localized-mnemonic",
                },
                {
                    "event": "qmp-secret",
                    "request": "accounts-initial-password",
                },
                {
                    "event": "qmp-secret",
                    "request": "accounts-initial-confirmation",
                },
                {
                    "event": "password-pair-accepted",
                    "context": "account-create",
                },
                {
                    "event": "focused-activation",
                    "target": "add",
                    "accessible_name": "添加(A)",
                    "method": "atspi-action",
                    "action": "click",
                    "mnemonic": "alt-a",
                    "mnemonic_owner_count": 2,
                },
                {"event": "user-created", "account": "second"},
            )
        )
        _validate_account_creation_events(passing)
        with self.assertRaisesRegex(TestFailure, "target='next'"):
            _validate_account_creation_events(
                passing.replace('"target": "next"', '"target": "add"', 1)
            )
        with self.assertRaisesRegex(
            TestFailure,
            "accounts-initial-confirmation",
        ):
            _validate_account_creation_events(
                "\n".join(
                    line
                    for line in passing.splitlines()
                    if "accounts-initial-confirmation" not in line
                )
            )
        with self.assertRaisesRegex(TestFailure, "password-pair-accepted"):
            _validate_account_creation_events(
                "\n".join(
                    line
                    for line in passing.splitlines()
                    if "password-pair-accepted" not in line
                )
            )
        with self.assertRaisesRegex(TestFailure, "localized-mnemonic"):
            _validate_account_creation_events(
                passing.replace("localized-mnemonic", "keyboard-focus", 1)
            )
        with self.assertRaisesRegex(TestFailure, "exact final Add"):
            _validate_account_creation_events(
                passing.replace("添加(A)", "添加用户(A)", 1)
            )
        with self.assertRaisesRegex(TestFailure, "accessible button action"):
            _validate_account_creation_events(
                passing.replace('"action": "click"', '"action": "copy"', 1)
            )
        with self.assertRaisesRegex(TestFailure, "duplicate mnemonic"):
            _validate_account_creation_events(
                passing.replace('"mnemonic_owner_count": 2', '"mnemonic_owner_count": 1')
            )

    def test_theme_selector_oracle_rejects_an_unlocalized_label(self):
        passing = json.dumps(
            {
                "event": "theme-menu",
                "transition": "prefer-dark",
                "method": "opened",
            },
            ensure_ascii=False,
        ) + "\n" + json.dumps(
            {
                "event": "theme-selected",
                "expected": "dark",
                "color_scheme": "prefer-dark",
                "localized_label": "暗色样式",
                "transitions": ["prefer-dark"],
            },
            ensure_ascii=False,
        )
        _validate_theme_selection(passing, "dark")
        with self.assertRaisesRegex(TestFailure, "localized theme label"):
            _validate_theme_selection(passing.replace("暗色样式", "Dark Style"), "dark")

    def test_theme_selector_oracle_requires_shells_default_light_state(self):
        passing = json.dumps(
            {
                "event": "theme-menu",
                "transition": "default",
                "method": "already-open",
            },
            ensure_ascii=False,
        ) + "\n" + json.dumps(
            {
                "event": "theme-selected",
                "expected": "light",
                "color_scheme": "default",
                "localized_label": "暗色样式",
                "transitions": ["default"],
            },
            ensure_ascii=False,
        )
        _validate_theme_selection(passing, "light")
        with self.assertRaisesRegex(TestFailure, "expected interface color scheme"):
            _validate_theme_selection(
                passing.replace('"default"', '"prefer-light"'),
                "light",
            )
        with self.assertRaisesRegex(TestFailure, "real Shell menu"):
            _validate_theme_selection(passing.split("\n", 1)[1], "light")

    def test_theme_marker_oracle_rejects_a_stale_firefox_page(self):
        passing = json.dumps(
            {
                "event": "theme-marker",
                "expected": "FIREFOX LIGHT",
                "observed": "FIREFOX LIGHT",
                "application": "firefox",
            }
        )
        _validate_theme_marker(passing, "FIREFOX LIGHT")
        with self.assertRaisesRegex(TestFailure, "marker is wrong"):
            _validate_theme_marker(
                passing.replace("FIREFOX LIGHT", "FIREFOX DARK"),
                "FIREFOX LIGHT",
            )
        with self.assertRaisesRegex(TestFailure, "real browser"):
            _validate_theme_marker(passing.replace("firefox", "text-editor"), "FIREFOX LIGHT")

    def test_live_theme_oracle_rejects_a_restarted_qt_fixture(self):
        _validate_same_fixture_process(42, 42, "Qt")
        with self.assertRaisesRegex(TestFailure, "restarted"):
            _validate_same_fixture_process(42, 84, "Qt")

    def test_account_record_oracle_rejects_an_administrator(self):
        passing = "\n".join(
            (
                "account=second",
                "passwd=present",
                "groups=second",
                "standard-user=yes",
                "password=usable",
            )
        )
        _validate_account_record(passing, "second")
        with self.assertRaisesRegex(TestFailure, "standard-user=yes"):
            _validate_account_record(
                passing.replace("standard-user=yes", "standard-user=no"), "second"
            )

    def test_graphical_login_oracle_rejects_a_non_wayland_session(self):
        passing = (
            "graphical-user=second\n"
            "session-id=8\n"
            "session-name=second\n"
            "session-class=user\n"
            "session-type=wayland\n"
            "session-active=yes\n"
            "session-remote=no\n"
            "home-owner=second\n"
        )
        _validate_graphical_login(passing, "second")
        with self.assertRaisesRegex(TestFailure, "session-type=wayland"):
            _validate_graphical_login(
                passing.replace("session-type=wayland", "session-type=tty"),
                "second",
            )
        with self.assertRaisesRegex(TestFailure, "session-class=user"):
            _validate_graphical_login(
                passing.replace("session-class=user", "session-class=manager"),
                "second",
            )

    def test_gdm_login_oracle_rejects_a_missing_password_submission(self):
        passing = "\n".join(
            json.dumps(event, ensure_ascii=False)
            for event in (
                {
                    "event": "gdm-user-target",
                    "account": "second",
                    "accessible_name": "Second User",
                    "role": "label",
                    "focused": False,
                    "attempt": 1,
                },
                {
                    "event": "qmp-click",
                    "request": "gdm-select-user",
                    "target": "second",
                    "accessible_name": "Second User",
                    "x_px": 220,
                    "y_px": 224,
                    "bounds": [100, 200, 240, 48],
                    "attempt": 1,
                },
                {
                    "event": "gdm-password-prompt",
                    "account": "second",
                    "display_name": "Second User",
                    "cancel_controls": 1,
                    "account_label_present": True,
                    "editable_exposed": False,
                    "selection_attempts": 1,
                },
                {
                    "event": "gdm-user-selected",
                    "account": "second",
                    "accessible_name": "Second User",
                    "method": "qmp-atspi-bounds",
                    "bounds": [100, 200, 240, 48],
                    "selection_attempts": 1,
                },
                {"event": "qmp-secret", "request": "gdm-password"},
                {
                    "event": "qmp-key",
                    "request": "gdm-password-submit",
                    "key": "ret",
                },
            )
        )
        _validate_gdm_login_events(passing, "second", "Second User")
        semantic_events = [json.loads(line) for line in passing.splitlines()]
        semantic_events[1] = {
            "event": "gdm-user-action",
            "account": "second",
            "accessible_name": "Second User",
            "owner_role": "button",
            "action": "click",
        }
        semantic_events[3]["method"] = "atspi-action"
        semantic_events[3]["bounds"] = []
        semantic_output = "\n".join(json.dumps(event) for event in semantic_events)
        _validate_gdm_login_events(
            semantic_output,
            "second",
            "Second User",
        )
        with self.assertRaisesRegex(TestFailure, "unrelated AT-SPI action"):
            _validate_gdm_login_events(
                semantic_output.replace('"action": "click"', '"action": "copy"'),
                "second",
                "Second User",
            )
        keyboard_events = [json.loads(line) for line in passing.splitlines()]
        keyboard_events.insert(
            2,
            {
                "event": "qmp-key",
                "request": "gdm-select-user-submit",
                "key": "ret",
                "target": "second",
                "attempt": 1,
            },
        )
        keyboard_events[4]["method"] = "qmp-atspi-bounds-keyboard"
        keyboard_output = "\n".join(json.dumps(event) for event in keyboard_events)
        _validate_gdm_login_events(keyboard_output, "second", "Second User")
        with self.assertRaisesRegex(TestFailure, "gdm-select-user-submit"):
            _validate_gdm_login_events(
                "\n".join(
                    line
                    for line in keyboard_output.splitlines()
                    if "gdm-select-user-submit" not in line
                ),
                "second",
                "Second User",
            )
        with self.assertRaisesRegex(TestFailure, "gdm-password-submit"):
            _validate_gdm_login_events(
                "\n".join(
                    line
                    for line in passing.splitlines()
                    if "gdm-password-submit" not in line
                ),
                "second",
                "Second User",
            )
        with self.assertRaisesRegex(TestFailure, "semantic AT-SPI"):
            _validate_gdm_login_events(
                passing.replace("qmp-atspi-bounds", "hard-coded-coordinate"),
                "second",
                "Second User",
            )
        with self.assertRaisesRegex(TestFailure, "invalid AT-SPI bounds"):
            _validate_gdm_login_events(
                passing.replace("[100, 200, 240, 48]", "[100, 200, 0, 0]"),
                "second",
                "Second User",
            )
        with self.assertRaisesRegex(TestFailure, "hidden password prompt"):
            _validate_gdm_login_events(
                passing.replace('"cancel_controls": 1', '"cancel_controls": 0'),
                "second",
                "Second User",
            )
        with self.assertRaisesRegex(TestFailure, "invalid retry count"):
            _validate_gdm_login_events(
                passing.replace('"selection_attempts": 1', '"selection_attempts": 4'),
                "second",
                "Second User",
            )

    def test_gdm_identity_probe_retries_until_the_live_greeter_exists(self):
        runner = object.__new__(FeatureSuiteRunner)
        console = Mock()
        console.run.side_effect = (
            CommandResult("", 1),
            CommandResult("gdm-greeter\n", 0),
        )
        vm = SimpleNamespace(serial=console)
        with patch("business.desktop.time.sleep"):
            self.assertEqual("gdm-greeter", runner._gdm_user(vm))
        probe = console.run.call_args_list[0].args[0]
        self.assertLess(probe.index("gdm-greeter"), probe.index(" gdm;"))
        self.assertIn('test -S "$runtime/bus"', probe)
        self.assertIn("wayland-[0-9]*", probe)

    def test_password_change_oracle_rejects_an_unchanged_hash(self):
        before = "a" * 64
        _validate_password_fingerprint_change(before, "b" * 64)
        with self.assertRaisesRegex(TestFailure, "did not change"):
            _validate_password_fingerprint_change(before, before)

    def test_password_change_ui_oracle_rejects_missing_authentication(self):
        passing = "\n".join(
            json.dumps(event, ensure_ascii=False)
            for event in (
                {
                    "event": "secret-focus",
                    "request": "accounts-current-password-attempt-3",
                    "method": "gnome-dialog-tab-search",
                },
                {
                    "event": "qmp-secret",
                    "request": "accounts-current-password-attempt-3",
                },
                {"event": "current-password-authenticated", "tab_count": 3},
                {
                    "event": "secret-focus",
                    "request": "accounts-new-password",
                    "method": "gnome-dialog-focus-chain",
                },
                {"event": "qmp-secret", "request": "accounts-new-password"},
                {
                    "event": "secret-focus",
                    "request": "accounts-new-confirmation",
                    "method": "gnome-dialog-focus-chain",
                },
                {"event": "qmp-secret", "request": "accounts-new-confirmation"},
                {"event": "password-pair-accepted", "context": "account-change"},
                {
                    "event": "focused-activation",
                    "target": "change",
                    "accessible_name": "更改(A)",
                    "method": "atspi-action",
                    "action": "click",
                },
                {"event": "password-changed"},
            )
        )
        _validate_password_change_events(passing)
        without_authentication = "\n".join(
            line
            for line in passing.splitlines()
            if "current-password-authenticated" not in line
        )
        with self.assertRaisesRegex(TestFailure, "exactly one"):
            _validate_password_change_events(without_authentication)
        lines = passing.splitlines()
        out_of_order = "\n".join((*lines[:-2], lines[-1], lines[-2]))
        with self.assertRaisesRegex(TestFailure, "out of order"):
            _validate_password_change_events(out_of_order)
        with self.assertRaisesRegex(TestFailure, "exact modal Change"):
            _validate_password_change_events(passing.replace("更改(A)", "更改头像"))

    def test_gdm_user_oracle_rejects_a_missing_original_account(self):
        passing = json.dumps(
            {"event": "gdm-users", "accounts": ["first", "second"], "count": 2}
        )
        _validate_gdm_user_events(passing, "first", "second")
        with self.assertRaisesRegex(TestFailure, "wrong accounts"):
            _validate_gdm_user_events(
                json.dumps(
                    {"event": "gdm-users", "accounts": ["second"], "count": 1}
                ),
                "first",
                "second",
            )

    def test_gdm_cursor_contract_rejects_a_default_cursor(self):
        passing = "\n".join(
            (
                "cursor-theme='Fluent-dark-cursors'",
                "cursor-size=32",
                "gdm-brand-package=ii  2.0.0",
                "gdm-brand-asset=present",
            )
        )
        _validate_gdm_cursor_contract(passing)
        with self.assertRaisesRegex(TestFailure, "cursor-theme"):
            _validate_gdm_cursor_contract(
                passing.replace("Fluent-dark-cursors", "Adwaita")
            )

    def test_gdm_contract_keeps_serial_outputs_on_distinct_lines(self):
        self.assertEqual(
            "cursor-theme='Fluent-dark-cursors'\n"
            "cursor-size=32\n"
            "gdm-brand-package=ii  2.0.0\n"
            "gdm-brand-asset=present",
            _join_contract_outputs(
                "cursor-theme='Fluent-dark-cursors'\ncursor-size=32",
                "gdm-brand-package=ii  2.0.0\ngdm-brand-asset=present",
            ),
        )
