"""User creation, password, GDM login, and cursor evidence oracles."""

import json
import re

from framework.errors import TestFailure


def _validate_account_record(output: str, username: str) -> None:
    required = {
        f"account={username}",
        "passwd=present",
        "standard-user=yes",
        "password=usable",
    }
    observed = {line.strip() for line in output.splitlines()}
    missing = sorted(required - observed)
    if missing:
        raise TestFailure(
            "The GNOME-created account record is incomplete: " + ", ".join(missing)
        )


def _validate_account_creation_events(output: str) -> None:
    """Require the real two-stage GNOME Accounts creation workflow.

    Passwords are deliberately absent from this transcript.  The observable
    contract is the semantic route through the UI: choose the explicit
    password policy, advance the details page with Next, submit the password
    page with Add, and observe the created user in Settings.
    """

    events: list[dict[str, object]] = []
    for line in output.splitlines():
        try:
            value = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            events.append(value)

    def index_of(**required: object) -> int:
        for index, event in enumerate(events):
            if all(event.get(key) == value for key, value in required.items()):
                return index
        description = ", ".join(f"{key}={value!r}" for key, value in required.items())
        raise TestFailure(
            "GNOME account creation missed a required semantic UI event: "
            + description
        )

    opened = index_of(
        event="focused-activation",
        target="add_user",
        method="localized-mnemonic",
    )
    radio = index_of(event="set-radio", target="set_password_now")
    details = index_of(
        event="focused-activation",
        target="next",
        method="localized-mnemonic",
    )
    initial = index_of(event="qmp-secret", request="accounts-initial-password")
    confirmation = index_of(
        event="qmp-secret",
        request="accounts-initial-confirmation",
    )
    accepted = index_of(event="password-pair-accepted", context="account-create")
    password = index_of(
        event="focused-activation",
        target="add",
        method="atspi-action",
    )
    password_event = events[password]
    if _normalized_accessible_label(password_event.get("accessible_name")) not in {
        "add",
        "添加",
    }:
        raise TestFailure(
            "GNOME account creation did not activate the exact final Add control"
        )
    if password_event.get("action") not in {"click", "activate", "press"}:
        raise TestFailure(
            "GNOME account creation did not use a real accessible button action"
        )
    if not isinstance(password_event.get("mnemonic_owner_count"), int) or int(
        password_event["mnemonic_owner_count"]
    ) < 2:
        raise TestFailure(
            "GNOME account creation did not prove the duplicate mnemonic was avoided"
        )
    created = index_of(event="user-created")
    if not opened < radio < details < initial < confirmation < accepted < password < created:
        raise TestFailure(
            "GNOME account creation events are out of order; expected "
            "Add User, password policy, Next, both secret requests, password "
            "acceptance, Add, then the created user"
        )


def _normalized_accessible_label(value: object) -> str:
    if not isinstance(value, str):
        return ""
    return re.sub(r"\([A-Za-z]\)", "", value).rstrip(" .…").strip().casefold()


def _validate_graphical_login(output: str, username: str) -> None:
    required = {
        f"graphical-user={username}",
        f"session-name={username}",
        "session-class=user",
        "session-type=wayland",
        "session-active=yes",
        "session-remote=no",
        f"home-owner={username}",
    }
    observed = {line.strip() for line in output.splitlines()}
    missing = sorted(required - observed)
    if missing:
        raise TestFailure(
            "The graphical login evidence is incomplete: " + ", ".join(missing)
        )


def _validate_gdm_login_events(output: str, account: str, full_name: str) -> None:
    events: list[dict[str, object]] = []
    for line in output.splitlines():
        try:
            value = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            events.append(value)

    def locate(**required: object) -> int:
        for index, event in enumerate(events):
            if all(event.get(key) == value for key, value in required.items()):
                return index
        description = ", ".join(f"{key}={value!r}" for key, value in required.items())
        raise TestFailure("GDM login missed a required UI event: " + description)

    target = locate(event="gdm-user-target", account=account)
    selected = locate(event="gdm-user-selected", account=account)
    selection = events[selected]
    if _normalized_accessible_label(selection.get("accessible_name")) not in {
        account.casefold(),
        full_name.casefold(),
    }:
        raise TestFailure("GDM selected an unrelated accessible user label")
    method = selection.get("method")
    if method not in {
        "atspi-action",
        "qmp-atspi-bounds",
        "qmp-atspi-bounds-keyboard",
    }:
        raise TestFailure("GDM user selection was not derived from semantic AT-SPI data")
    selection_attempts = selection.get("selection_attempts")
    if (
        not isinstance(selection_attempts, int)
        or isinstance(selection_attempts, bool)
        or not 1 <= selection_attempts <= 3
    ):
        raise TestFailure("GDM user selection reported an invalid retry count")
    if method == "atspi-action":
        if selection_attempts != 1:
            raise TestFailure("GDM semantic action reported an invalid attempt count")
        click = locate(event="gdm-user-action", account=account)
        action = events[click]
        if action.get("action") not in {"click", "activate", "press"}:
            raise TestFailure("GDM user selection used an unrelated AT-SPI action")
        if action.get("owner_role") not in {"button", "list item"}:
            raise TestFailure("GDM user selection action did not belong to a user tile")
        keyboard = click
    else:
        bounds = selection.get("bounds")
        if (
            not isinstance(bounds, list)
            or len(bounds) != 4
            or any(not isinstance(value, (int, float)) for value in bounds)
            or bounds[0] < 0
            or bounds[1] < 0
            or bounds[2] < 2
            or bounds[3] < 2
        ):
            raise TestFailure("GDM semantic pointer selection has invalid AT-SPI bounds")
        click = locate(event="qmp-click", request="gdm-select-user")
        selection_clicks = [
            event
            for event in events
            if event.get("event") == "qmp-click"
            and event.get("target") == account
            and isinstance(event.get("attempt"), int)
        ]
        if [event.get("attempt") for event in selection_clicks] != list(
            range(1, selection_attempts + 1)
        ):
            raise TestFailure(
                "GDM user selection retries were not derived afresh in order"
            )
        if method == "qmp-atspi-bounds-keyboard":
            keyboard = locate(
                event="qmp-key",
                request="gdm-select-user-submit",
                key="ret",
            )
            keyboard_event = events[keyboard]
            if (
                keyboard_event.get("target") != account
                or keyboard_event.get("attempt") != selection_attempts
            ):
                raise TestFailure(
                    "GDM keyboard activation was not bound to the selected account"
                )
        else:
            keyboard = click
    prompt = locate(event="gdm-password-prompt", account=account)
    prompt_event = events[prompt]
    if (
        prompt_event.get("display_name") != full_name
        or prompt_event.get("cancel_controls") != 1
        or prompt_event.get("account_label_present") is not True
        or prompt_event.get("editable_exposed") is not False
        or prompt_event.get("selection_attempts") != selection_attempts
    ):
        raise TestFailure("GDM did not prove the selected user's hidden password prompt")
    if not target < click <= keyboard < prompt < selected:
        raise TestFailure("GDM semantic user selection events are out of order")
    password = locate(event="qmp-secret", request="gdm-password")
    submitted = locate(
        event="qmp-key",
        request="gdm-password-submit",
        key="ret",
    )
    if not target < click < prompt < selected < password < submitted:
        raise TestFailure(
            "GDM login events are out of order; expected user selection, "
            "password entry, then submission"
        )


def _validate_password_fingerprint_change(before: str, after: str) -> None:
    valid = lambda value: len(value) == 64 and all(  # noqa: E731
        character in "0123456789abcdef" for character in value
    )
    if not valid(before) or not valid(after):
        raise TestFailure("Password fingerprints are malformed")
    if before == after:
        raise TestFailure("GNOME Settings did not change the password hash")


def _validate_password_change_events(output: str) -> None:
    """Require the real GNOME password dialog's authenticated workflow."""

    events: list[dict[str, object]] = []
    for line in output.splitlines():
        try:
            value = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            events.append(value)

    def locate(**required: object) -> int:
        for index, event in enumerate(events):
            if all(event.get(key) == value for key, value in required.items()):
                return index
        description = ", ".join(
            f"{key}={value!r}" for key, value in required.items()
        )
        raise TestFailure(
            "GNOME password change missed a required UI event: " + description
        )

    authenticated_events = [
        (index, event)
        for index, event in enumerate(events)
        if event.get("event") == "current-password-authenticated"
    ]
    if len(authenticated_events) != 1:
        raise TestFailure(
            "GNOME password change must prove exactly one current-password "
            "authentication transition"
        )
    authenticated, authentication = authenticated_events[0]
    tab_count = authentication.get("tab_count")
    if not isinstance(tab_count, int) or isinstance(tab_count, bool) or not (
        0 <= tab_count < 12
    ):
        raise TestFailure(
            "GNOME password change reported an invalid focus-search attempt"
        )
    current_request = f"accounts-current-password-attempt-{tab_count}"
    current_focus = locate(
        event="secret-focus",
        request=current_request,
        method="gnome-dialog-tab-search",
    )
    current_secret = locate(event="qmp-secret", request=current_request)
    new_focus = locate(
        event="secret-focus",
        request="accounts-new-password",
        method="gnome-dialog-focus-chain",
    )
    new_secret = locate(event="qmp-secret", request="accounts-new-password")
    confirmation_focus = locate(
        event="secret-focus",
        request="accounts-new-confirmation",
        method="gnome-dialog-focus-chain",
    )
    confirmation_secret = locate(
        event="qmp-secret",
        request="accounts-new-confirmation",
    )
    accepted = locate(event="password-pair-accepted", context="account-change")
    submitted = locate(
        event="focused-activation",
        target="change",
        method="atspi-action",
    )
    submission = events[submitted]
    if _normalized_accessible_label(submission.get("accessible_name")) not in {
        "change",
        "更改",
    }:
        raise TestFailure(
            "GNOME password change did not activate the exact modal Change control"
        )
    if submission.get("action") not in {"click", "activate", "press"}:
        raise TestFailure(
            "GNOME password change did not use a real accessible button action"
        )
    changed = locate(event="password-changed")
    if not (
        current_focus
        < current_secret
        < authenticated
        < new_focus
        < new_secret
        < confirmation_focus
        < confirmation_secret
        < accepted
        < submitted
        < changed
    ):
        raise TestFailure(
            "GNOME password change events are out of order; expected current "
            "authentication, both replacement secrets, password acceptance, "
            "the exact modal submission, then completion"
        )


def _validate_gdm_user_events(output: str, original: str, secondary: str) -> None:
    events = []
    for line in output.splitlines():
        try:
            value = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict) and value.get("event") == "gdm-users":
            events.append(value)
    if len(events) != 1:
        raise TestFailure("GDM audit did not produce one user-list event")
    accounts = events[0].get("accounts")
    if not isinstance(accounts, list) or set(accounts) != {original, secondary}:
        raise TestFailure(
            f"GDM audit returned the wrong accounts: {accounts!r}"
        )


def _validate_gdm_cursor_contract(output: str) -> None:
    required = {
        "cursor-theme='Fluent-dark-cursors'",
        "cursor-size=32",
        "gdm-brand-asset=present",
    }
    observed = {line.strip() for line in output.splitlines()}
    missing = sorted(required - observed)
    package = any(line.startswith("gdm-brand-package=ii ") for line in observed)
    if missing or not package:
        detail = missing + ([] if package else ["gdm-brand-package=ii …"])
        raise TestFailure(
            "The GDM branding/cursor contract is incomplete: " + ", ".join(detail)
        )


def _join_contract_outputs(*outputs: str) -> str:
    """Keep serial command outputs as separate line-oriented evidence."""

    return "\n".join(output.strip("\n") for output in outputs if output.strip("\n"))


__all__ = tuple(name for name in globals() if name.startswith("_"))
