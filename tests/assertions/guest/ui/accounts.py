"""GNOME users, GDM account selection, and Secure Shell controls."""

from .core import *  # noqa: F403
from .installer import wait_application


def prepare_user_accounts(evidence: Path) -> None:
    """Open GNOME 50's real nested System/Users panel."""

    dismiss_initial_setup()
    environment = [
        f"--setenv={key}={value}"
        for key in (
            "HOME",
            "XDG_RUNTIME_DIR",
            "DBUS_SESSION_BUS_ADDRESS",
            "WAYLAND_DISPLAY",
            "DISPLAY",
            "NO_AT_BRIDGE",
            "XDG_CURRENT_DESKTOP",
            "XDG_SESSION_DESKTOP",
            "DESKTOP_SESSION",
            "GDMSESSION",
        )
        if (value := os.environ.get(key)) is not None
    ]
    runtime_text = os.environ.get("XDG_RUNTIME_DIR", "")
    runtime = Path(runtime_text)
    if not runtime_text or not runtime.is_dir():
        raise UiFailure("The graphical user's XDG runtime directory is unavailable")
    # This driver runs once as the installed user and again as the newly
    # created user.  A shared /tmp log is not writable by the second UID, and
    # a fixed transient-unit name can retain stale state after a failed run.
    # Keep both resources private to the current user and process.
    unit = f"anduinos-acceptance-user-accounts-{os.getpid()}"
    application_log = runtime / f"{unit}.log"
    application_log.unlink(missing_ok=True)

    def launch_diagnostics() -> str:
        status = subprocess.run(
            ("systemctl", "--user", "status", unit, "--no-pager", "--full"),
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        ).stdout
        log = (
            application_log.read_text(encoding="utf-8", errors="replace")
            if application_log.exists()
            else ""
        )
        diagnostics = f"systemd status:\n{status}\napplication output:\n{log}\n"
        (evidence / "gnome-users-launch-failure.txt").write_text(
            diagnostics, encoding="utf-8"
        )
        return diagnostics

    launched = subprocess.run(
        [
            "systemd-run",
            "--user",
            f"--unit={unit}",
            "--collect",
            "--property=Type=exec",
            f"--property=StandardOutput=append:{application_log}",
            f"--property=StandardError=append:{application_log}",
            *environment,
            "--",
            "gnome-control-center",
            "system",
            "users",
        ],
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    event("users-settings-launched", returncode=launched.returncode, unit=unit)
    if launched.returncode != 0:
        diagnostics = launch_diagnostics()
        raise UiFailure(
            "Could not execute GNOME Settings transient unit:\n"
            + launched.stdout
            + diagnostics[-8000:]
        )
    try:
        wait_application(("gnome-control-center", "Settings", "设置"), timeout=90)
    except UiFailure as error:
        diagnostics = launch_diagnostics()
        raise UiFailure(
            "GNOME Settings did not become accessible after launch:\n"
            + diagnostics[-8000:]
        ) from error
    find("users_panel", timeout=60)
    dump_accessibility(evidence / "users-panel.txt")
    event("users-panel-ready")


def authenticate_user_panel(evidence: Path) -> None:
    click("unlock", timeout=30)
    find("polkit", timeout=30)
    dump_accessibility(evidence / "users-polkit.txt")
    # GNOME's Polkit agent deliberately hides its password entry from AT-SPI;
    # the dialog itself owns keyboard focus.  Request opaque QMP input exactly
    # as the Secure Shell toggle path does instead of inventing an inaccessible
    # text control or falling back to screen coordinates.
    event("qmp-secret", request="accounts-polkit-password")
    event("qmp-key", request="accounts-polkit-submit", key="ret")
    wait_absent("polkit", timeout=90)
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        try:
            if enabled(find("add_user", timeout=1)):
                event("users-panel-unlocked")
                return
        except UiFailure:
            pass
        time.sleep(0.25)
    raise UiFailure("GNOME Users panel did not unlock after authentication")


def create_user(account: str, full_name: str, evidence: Path) -> None:
    prepare_user_accounts(evidence)
    authenticate_user_panel(evidence)
    request_focused_activation("add_user", "accounts-add-user", timeout=30)
    find("add_user", timeout=30)
    dump_accessibility(evidence / "add-user-dialog.txt")
    set_text("full_name", full_name)
    set_text("username", account)
    set_radio("set_password_now")
    # Selecting "Set password now" turns the dialog into a two-stage
    # assistant.  The details page action is Next; Add belongs to the password
    # page.  Keeping those semantic actions distinct makes a GNOME UI change
    # fail at the exact stage instead of tabbing around an unrelated control.
    request_focused_activation("next", "accounts-add-details", timeout=30)
    find("set_password_page", timeout=30)
    request_secret("password", "accounts-initial-password")
    request_secret("confirm_password", "accounts-initial-confirmation")
    deadline = time.monotonic() + 60
    while time.monotonic() < deadline:
        if enabled(control("add")):
            event("password-pair-accepted", context="account-create")
            break
        time.sleep(0.25)
    else:
        raise UiFailure("GNOME rejected the matching account password fields")
    request_focused_activation("add", "accounts-add-password", timeout=30)
    wait_absent("set_password_page", timeout=90)
    find(full_name, timeout=60)
    dump_accessibility(evidence / "created-user.txt")
    event("user-created", account=account, full_name=full_name)


def change_own_password(evidence: Path) -> None:
    prepare_user_accounts(evidence)
    request_focused_activation(
        "password",
        "accounts-open-change-password",
        timeout=30,
    )
    find("change_password", timeout=30)
    dump_accessibility(evidence / "change-password-dialog.txt")
    # GNOME 50 rejects grab_focus(), omits FOCUSED and character counts, and
    # reports Wayland surface-local coordinates as SCREEN coordinates. Discover
    # the current field through the product's own authentication transition;
    # after that succeeds, focus remains in the current entry and each
    # PasswordEntryRow contributes its reveal button before the next entry.
    discover_current_password_focus()
    request_dialog_secret(
        "new_password", "accounts-new-password", tab_count=2
    )
    request_dialog_secret(
        "confirm_password", "accounts-new-confirmation", tab_count=2
    )
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        if enabled(control("change")):
            event("password-pair-accepted", context="account-change")
            break
        time.sleep(0.1)
    else:
        raise UiFailure("GNOME rejected the matching replacement passwords")
    # The Users panel behind the modal also exposes "Change Avatar".  Resolve
    # the exact mnemonic-normalized dialog button and invoke that accessible
    # action; a global substring lookup can silently click the avatar instead.
    request_focused_activation(
        "change",
        "accounts-change-password-submit",
        timeout=30,
    )
    wait_absent("change_password", timeout=90)
    dump_accessibility(evidence / "password-changed.txt")
    event("password-changed")


def dynamic_user_node(account: str, full_name: str, timeout: float = 60):
    deadline = time.monotonic() + timeout
    last_nodes: list[tuple[str, str]] = []
    while time.monotonic() < deadline:
        nodes = visible_nodes()
        last_nodes = [
            (role(item), name(item)) for item in nodes if name(item)
        ][-80:]
        # GDM exposes the account as the text rendered inside the clickable
        # tile and the full name as an auxiliary accessible label.  Prefer the
        # visible account label so any AT-SPI-derived pointer target lands in
        # the real tile; retain the full name as a compatibility fallback.
        for expected in (account.casefold(), full_name.casefold()):
            exact = [item for item in nodes if name(item).casefold() == expected]
            if len(exact) == 1:
                return exact[0]
        time.sleep(0.25)
    raise UiFailure(
        f"GDM did not expose one unambiguous user label for "
        f"{account!r}/{full_name!r}; visible={last_nodes!r}"
    )


def select_gdm_user(account: str, full_name: str, evidence: Path) -> None:
    target = None
    selection_method = ""
    selection_bounds: list[int] = []
    # GNOME Shell intentionally does not expose GDM's password entry as an
    # editable AT-SPI object.  Prove the user tile transitioned to its password
    # page instead: the selected account and display name remain, and exactly
    # one Cancel button appears.  GNOME 50 keeps the selected account label in
    # its accessible cache even though only the full name is painted.  The
    # hidden entry owns keyboard focus, just like the Polkit prompt above.
    prompt_cancel_count = 0
    account_label_present = False
    display_name_present = False
    selection_attempts = 0

    def wait_password_prompt(timeout: float) -> bool:
        nonlocal prompt_cancel_count
        nonlocal account_label_present
        nonlocal display_name_present

        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            nodes = visible_nodes()
            prompt_cancel_count = sum(
                1
                for item in nodes
                if role(item) == "button" and matches(item, aliases("cancel"))
            )
            account_label_present = any(
                name(item).casefold() == account.casefold() for item in nodes
            )
            display_name_present = any(
                name(item).casefold() == full_name.casefold() for item in nodes
            )
            if (
                prompt_cancel_count == 1
                and account_label_present
                and display_name_present
            ):
                return True
            time.sleep(0.25)
        return False

    # Prefer the exact user tile's real accessible action. GNOME Shell usually
    # exposes it on an ancestor of the account label, and invoking that action
    # avoids pointer timing entirely. The coordinate fallback below remains
    # available for Shell builds that omit an actionable tile interface.
    target = dynamic_user_node(account, full_name)
    event(
        "gdm-user-target",
        account=account,
        accessible_name=name(target),
        role=role(target),
        focused=has_state(target, Atspi.StateType.FOCUSED),
        attempt=1,
    )
    try:
        semantic_target = actionable(target)
        semantic_action = perform_named_activation(semantic_target)
    except Exception:
        semantic_target = None
        semantic_action = None
    if semantic_target is not None and semantic_action is not None:
        event(
            "gdm-user-action",
            account=account,
            accessible_name=name(target),
            owner_role=role(semantic_target),
            action=semantic_action,
        )
        if wait_password_prompt(5):
            selection_method = "atspi-action"
            selection_attempts = 1

    # A freshly returned GDM greeter can consume the pointer click as selection
    # rather than activation. Bind one click to this exact account's live
    # AT-SPI bounds. If the password page does not open, activate the selected
    # tile once with Enter. Repeated pointer clicks are unsafe here: Shell may
    # begin its page transition while a later click is still queued against
    # coordinates that no longer represent a user tile.
    for attempt in (range(1) if not selection_method else ()):
        target = dynamic_user_node(account, full_name)
        selection_attempts = attempt + 1
        event(
            "gdm-user-target",
            account=account,
            accessible_name=name(target),
            role=role(target),
            focused=has_state(target, Atspi.StateType.FOCUSED),
            attempt=selection_attempts,
        )
        try:
            if not target.is_component():
                raise UiFailure("the semantic user label has no Component interface")
            bounds = target.get_extents(Atspi.CoordType.SCREEN)
        except Exception as error:
            raise UiFailure(
                f"Could not derive a click target for GDM user {account!r}: {error}"
            ) from error
        selection_bounds = [bounds.x, bounds.y, bounds.width, bounds.height]
        if (
            bounds.x < 0
            or bounds.y < 0
            or bounds.width < 2
            or bounds.height < 2
        ):
            raise UiFailure(
                f"GDM returned unusable bounds for {account!r}: "
                f"{selection_bounds!r}"
            )
        event(
            "qmp-click",
            request="gdm-select-user",
            target=account,
            accessible_name=name(target),
            x_px=round(bounds.x + bounds.width / 2, 3),
            y_px=round(bounds.y + bounds.height / 2, 3),
            bounds=selection_bounds,
            attempt=selection_attempts,
        )
        if wait_password_prompt(5):
            selection_method = "qmp-atspi-bounds"
            break
        event(
            "qmp-key",
            request="gdm-select-user-submit",
            key="ret",
            target=account,
            attempt=selection_attempts,
        )
        if wait_password_prompt(20):
            selection_method = "qmp-atspi-bounds-keyboard"
            break
    else:
        if not selection_method:
            raise UiFailure(
                f"GDM did not expose the password page for {account!r}; "
                f"cancel_count={prompt_cancel_count}, "
                f"account_label_present={account_label_present}, "
                f"selection_attempts={selection_attempts}"
            )
    assert target is not None
    dump_accessibility(evidence / f"gdm-selected-{account}.txt")
    event(
        "gdm-password-prompt",
        account=account,
        display_name=full_name,
        cancel_controls=prompt_cancel_count,
        account_label_present=account_label_present,
        editable_exposed=False,
        selection_attempts=selection_attempts,
    )
    event(
        "gdm-user-selected",
        account=account,
        accessible_name=name(target),
        method=selection_method,
        bounds=selection_bounds,
        selection_attempts=selection_attempts,
    )
    event("qmp-secret", request="gdm-password")
    event("qmp-key", request="gdm-password-submit", key="ret")


def audit_gdm_users(
    account: str,
    full_name: str,
    original_account: str,
    original_full_name: str,
    evidence: Path,
) -> None:
    nodes = visible_nodes()
    names = {name(item).casefold() for item in nodes if name(item)}
    expected = (
        (account, full_name),
        (original_account, original_full_name),
    )
    missing = [
        user
        for user, display in expected
        if user.casefold() not in names and display.casefold() not in names
    ]
    dump_accessibility(evidence / "gdm-users.txt")
    if missing:
        raise UiFailure("GDM user list is missing: " + ", ".join(missing))
    event(
        "gdm-users",
        accounts=[original_account, account],
        count=2,
    )


def probe_secure_shell_row(evidence: Path) -> None:
    matches_found = [
        item
        for item in visible_nodes()
        if role(item) == "button" and matches(item, aliases("secure_shell"))
    ]
    if len(matches_found) != 1:
        dump_accessibility(evidence / "secure-shell-row-failure.txt")
        raise UiFailure(
            "System panel did not expose exactly one Secure Shell button"
        )
    dump_accessibility(evidence / "secure-shell-row.txt")
    event(
        "secure-shell-row",
        count=1,
        focused=has_state(matches_found[0], Atspi.StateType.FOCUSED),
    )


def probe_secure_shell_switch(evidence: Path) -> None:
    target = associated_toggle("secure_shell", timeout=60)
    dump_accessibility(evidence / "secure-shell-panel.txt")
    focused = [
        {"role": role(item), "name": name(item)}
        for item in visible_nodes()
        if has_state(item, Atspi.StateType.FOCUSED)
    ]
    event(
        "secure-shell-switch",
        active=checked(target),
        enabled=enabled(target),
        focused=focus_within(target),
        focused_nodes=focused,
    )
def toggle_secure_shell(active: bool, evidence: Path) -> None:
    target = associated_toggle("secure_shell", timeout=60)
    if checked(target) != active:
        leaves = [
            item
            for item in list(walk(target, maximum=100))[1:]
            if role(item) in {"switch", "toggle button", "check box"}
            and not any(
                role(descendant) in {"switch", "toggle button", "check box"}
                for descendant in list(walk(item, maximum=100))[1:]
            )
        ]
        if len(leaves) != 1:
            raise UiFailure("Secure Shell row has no unique inner GTK switch")
        inner = actionable(leaves[0])
        if not perform_action(inner, 0):
            raise UiFailure("Could not activate the inner Secure Shell switch")
        deadline = time.monotonic() + 15
        while checked(target) != active and time.monotonic() < deadline:
            time.sleep(0.25)
        if find_optional("polkit", timeout=3) is not None:
            dump_accessibility(evidence / "polkit-authentication.txt")
            # GNOME Polkit exposes its hidden Caps Lock warning as SHOWING in
            # AT-SPI even when the warning is not painted. It is therefore not
            # a trustworthy keyboard-state signal for automation.
            event("polkit-required")
            return
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            current = associated_toggle("secure_shell", timeout=2)
            if checked(current) == active:
                target = current
                break
            time.sleep(0.25)
    if checked(target) != active:
        raise UiFailure(f"GNOME Secure Shell switch did not reach active={active}")
    dump_accessibility(evidence / "secure-shell-panel.txt")
    event("secure-shell", active=active)


def assert_secure_shell(active: bool, evidence: Path) -> None:
    # Polkit closes asynchronously after the password is submitted.  Waiting a
    # fixed number of seconds here made the test race the authentication agent
    # on slower guests.  The switch state is the contract we care about, so
    # wait until both the dialog has gone and GNOME exposes the final state.
    deadline = time.monotonic() + 90
    last_state: bool | None = None
    while time.monotonic() < deadline:
        if find_optional("polkit", timeout=0.5) is None:
            try:
                target = associated_toggle("secure_shell", timeout=2)
                last_state = checked(target)
                if last_state == active:
                    break
            except UiFailure:
                pass
        time.sleep(0.5)
    else:
        dump_accessibility(evidence / "secure-shell-authentication-timeout.txt")
        raise UiFailure(
            "Secure Shell authentication did not finish with "
            f"active={active}; last observed state was {last_state}"
        )
    dump_accessibility(evidence / "secure-shell-panel.txt")
    event("secure-shell", active=active, authenticated=True)


def associated_toggle(key: str, timeout: float):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        label = find_optional(key, timeout=0.25)
        if label is None:
            continue
        current = label
        for _ in range(10):
            toggles = [
                item
                for item in walk(current, maximum=500)
                if role(item) in {"switch", "toggle button", "check box"}
            ]
            semantic = semantic_toggles(toggles)
            if len(semantic) == 1:
                return semantic[0]
            try:
                current = current.get_parent()
            except Exception:
                break
            if current is None:
                break
        named = [
            item
            for item in visible_nodes()
            if role(item) in {"switch", "toggle button", "check box"}
            and matches(item, aliases(key))
        ]
        semantic = semantic_toggles(named)
        if len(semantic) == 1:
            return semantic[0]
        all_switches = [item for item in visible_nodes() if role(item) == "switch"]
        semantic = semantic_toggles(all_switches)
        if len(semantic) == 1:
            return semantic[0]
        time.sleep(0.25)
    dump_accessibility(Path("/tmp/secure-shell-panel-failure.txt"))
    raise UiFailure("Secure Shell panel has no unambiguous accessible switch")
__all__ = tuple(name for name in globals() if not name.startswith("__"))
