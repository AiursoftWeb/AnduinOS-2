"""Manual A/B layouts through the same controls used by a human installer."""

from .core import *  # noqa: F403


def dropdown_display_text(node) -> tuple[str, ...]:
    """Read the collapsed face, never an option in an open/hidden popup."""
    if not showing(node) or has_state(node, Atspi.StateType.EXPANDED):
        return ()
    pending = [node]
    values = []
    excluded = {"list", "list box", "list item", "menu", "menu item",
                "popup menu", "window", "dialog"}
    for _ in range(100):
        if not pending:
            return tuple(values)
        item = pending.pop()
        if not showing(item):
            continue
        if role(item) in excluded:
            return ()
        if name(item):
            values.append(name(item))
        pending.extend(children(item))
    raise UiFailure("Unexpectedly large ESP dropdown accessible tree")


def selected_esp_dropdown(expected_path: str):
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        matches = [
            item for item in visible_nodes()
            if role(item) == "combo box"
            and any(re.search(re.escape(expected_path) + r"(?=\s|\(|$)", value)
                    for value in dropdown_display_text(item))
        ]
        if len(matches) == 1:
            return matches[0]
        time.sleep(0.25)
    raise UiFailure(f"Cannot identify the ESP selector reusing {expected_path}")


def select_new_esp(expected_path: str) -> None:
    dropdown = selected_esp_dropdown(expected_path)
    # Existing partition rows can put this selector below the scroll viewport.
    # Follow keyboard focus until GTK scrolls the real selector into view.
    for attempt in range(80):
        if focus_within(dropdown):
            break
        event("qmp-key", request=f"focus-esp-selector-{attempt}", key="tab")
        time.sleep(0.3)
        dropdown = selected_esp_dropdown(expected_path)
    else:
        raise UiFailure("Could not focus/scroll the existing ESP dropdown")
    request_node_click(dropdown, "open-esp-selector")
    choices = ("Create a new ESP partition", "创建新的 ESP 分区")
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        nodes = [item for item in visible_nodes() if name(item) in choices]
        if nodes:
            # Use the actual option's accessible geometry, never fixed pixels.
            request_node_click(nodes[-1], "choose-new-esp")
            break
        time.sleep(0.25)
    else:
        raise UiFailure("New ESP option was not exposed by the dropdown")
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        displayed = dropdown_display_text(dropdown)
        if any(value in choices for value in displayed) and not any(
            re.search(re.escape(expected_path) + r"(?=\s|\(|$)", value)
            for value in displayed
        ):
            event("coexistence-new-esp-selected")
            return
        time.sleep(0.25)
    raise UiFailure("ESP dropdown did not select a new independent ESP")


def configure_coexistence(config: dict[str, object], evidence: Path) -> bool:
    """Return False only after observing the occupied-ESP rejection."""
    from .installer import wait_page

    stage = config.get("coexistence_stage")
    if stage not in ("a", "b-shared", "b-separate"):
        raise UiFailure(f"Invalid coexistence stage: {stage!r}")
    set_toggle("manual_strategy", True)
    click("next")
    wait_page("advanced_storage")
    click("edit_storage")
    if stage == "a":
        click("initialize_gpt")
        click("confirm_initialize_gpt")
    else:
        expected_esp = str(config["existing_esp_path"])
        selected_esp_dropdown(expected_esp)
        if stage == "b-separate":
            select_new_esp(expected_esp)
    # The editor advances ESP -> Root -> Swap. Each root is at the 50 GiB
    # recommendation; A leaves sufficient contiguous space for B (no shrink).
    sizes = (50 * 1024, 3072) if stage == "b-shared" else (1024, 50 * 1024, 3072)
    for size in sizes:
        set_numeric_value("partition_size", size)
        click_button("add_partition")
    dump_accessibility(evidence / "manual-coexistence-layout.txt")
    find("next", timeout=30, require_enabled=True)
    click("next")
    if stage != "b-shared":
        wait_page("user")
        event("coexistence-layout", stage=stage, root_mib=50 * 1024,
              new_esp_mib=1024, swap_mib=3072)
        return True
    find("separate_esp_required", timeout=90)
    dump_accessibility(evidence / "occupied-esp-dialog.txt")
    event("coexistence-esp-conflict-dialog")
    request_dialog_focused_activation(
        "separate_esp_required", "esp_conflict_ok", "dismiss-occupied-esp", timeout=30
    )
    wait_absent("separate_esp_required")
    wait_page("advanced_storage")
    if enabled(control("next")):
        raise UiFailure("Next remains enabled after rejecting the occupied ESP")
    if find_optional("user", 1) or find_optional("progress", 1):
        raise UiFailure("Occupied ESP advanced past manual partitioning")
    dump_accessibility(evidence / "occupied-esp-blocked.txt")
    event("coexistence-esp-rejected", next_enabled=False, stage="advanced-storage")
    return False
