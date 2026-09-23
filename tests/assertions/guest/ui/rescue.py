"""Drive the Live-only Rescue Center with real host pointer requests."""

from .core import *  # noqa: F403


def _parent(node):
    try:
        return node.get_parent()
    except Exception:
        return None


def _ancestor_containing(node, candidate_name: str, candidate_role: str = ""):
    current = node
    for _ in range(10):
        if current is None:
            break
        descendants = tuple(walk(current, maximum=200))
        if any(
            name(item) == candidate_name
            and (not candidate_role or role(item) == candidate_role)
            for item in descendants
        ):
            return current
        current = _parent(current)
    raise UiFailure(
        f"Could not associate {candidate_name!r} with {name(node)!r}"
    )


def _named_descendant(container, candidate_name: str, candidate_role: str = ""):
    for item in walk(container, maximum=300):
        if name(item) != candidate_name:
            continue
        if candidate_role and role(item) != candidate_role:
            continue
        if showing(item) and enabled(item):
            return item
    raise UiFailure(
        f"Could not find enabled {candidate_name!r} below {name(container)!r}"
    )


def _rescue_window_origin(target) -> tuple[float, float]:
    """Locate a GTK Wayland window via GNOME Shell's screen geometry."""

    frame = target
    while frame is not None and role(frame) != "frame":
        frame = _parent(frame)
    if frame is None:
        raise UiFailure("Rescue control has no accessible window frame")
    window = frame.get_extents(Atspi.CoordType.WINDOW)
    if window.width < 200 or window.height < 100:
        raise UiFailure("Rescue window returned invalid local dimensions")

    matches = []
    # GNOME Shell marks a Wayland window's compositor node as not SHOWING
    # outside Overview even while the GTK window itself is visibly painted.
    for item in walk(desktop()):
        if name(item) != "Wayland window" or owning_application(item) != "gnome-shell":
            continue
        rectangle = item.get_extents(Atspi.CoordType.SCREEN)
        width_extra = rectangle.width - window.width
        height_extra = rectangle.height - window.height
        # Mutter's accessible window includes its shadow.  The real GTK
        # window is centered in that rectangle (50 px larger on both axes in
        # the observed Live session); reject unrelated compositor surfaces.
        if not (0 <= width_extra <= 100 and 0 <= height_extra <= 100):
            continue
        if rectangle.x < 0 or rectangle.y < 0:
            continue
        matches.append(
            (
                rectangle.x + width_extra / 2,
                rectangle.y + height_extra / 2,
            )
        )
    if len(matches) != 1:
        raise UiFailure(
            f"Expected one matching Wayland window for {name(frame)!r}, "
            f"found {len(matches)}"
        )
    return matches[0]


def restore_offline_system(
    system_name: str,
    snapshot_title: str,
    evidence: Path,
) -> None:
    """Restore one exact snapshot using only real pointer requests."""

    # The Live session launches the installer automatically.  Close that
    # unrelated window before testing pointer coordinates in Rescue Center;
    # otherwise Mutter can leave the newly launched rescue window behind it,
    # and GTK reports the hidden row at (0, 0).
    for item in visible_nodes():
        if role(item) != "frame" or name(item) != "AnduinOS Installer":
            continue
        close = _named_descendant(item, "Close", "button")
        if not perform_action(close, 0):
            raise UiFailure("Could not close the Live installer before rescue")
        break

    find_candidates(
        ("Choose an AnduinOS installation",),
        label="Rescue Center installation chooser",
        timeout=180,
    )
    installation = find_candidates(
        (system_name,),
        label="detected AnduinOS installation",
        timeout=180,
        require_enabled=True,
    )
    request_node_click(
        installation,
        "rescue-select-installation",
        semantic_target=f"installation:{system_name}",
        window_origin=_rescue_window_origin(installation),
    )

    snapshots = find_candidates(
        ("Manage Btrfs snapshots",),
        label="Btrfs snapshot manager action",
        timeout=180,
        require_enabled=True,
    )
    request_node_click(
        snapshots,
        "rescue-open-snapshots",
        semantic_target="Manage Btrfs snapshots",
        window_origin=_rescue_window_origin(snapshots),
    )

    snapshot = find_candidates(
        (snapshot_title,),
        label="selected Rescue Center snapshot",
        timeout=180,
        require_enabled=True,
    )
    row = _ancestor_containing(snapshot, "Restore")
    restore = _named_descendant(row, "Restore")
    request_node_click(
        restore,
        "rescue-select-snapshot",
        semantic_target=f"Restore snapshot:{snapshot_title}",
        window_origin=_rescue_window_origin(restore),
    )

    confirmation = find_candidates(
        (f"Restore {snapshot_title}?",),
        label="offline restore confirmation",
        timeout=60,
    )
    protect = find_candidates(
        ("Create a safety snapshot of the current system first",),
        label="offline restore safety snapshot",
        timeout=30,
        require_enabled=True,
    )
    if not checked(protect):
        raise UiFailure("Rescue Center safety snapshot is not enabled by default")
    event(
        "rescue-safety-snapshot",
        checked=True,
        confirmation=name(confirmation),
    )
    submit = find_candidates(
        ("Restore system",),
        label="offline restore submit button",
        timeout=30,
        require_enabled=True,
    )
    request_node_click(
        submit,
        "rescue-confirm-restore",
        semantic_target="Restore system",
        window_origin=_rescue_window_origin(submit),
    )

    complete = find_candidates(
        ("System restore complete",),
        label="offline restore completion",
        timeout=900,
    )
    dump_accessibility(evidence / "rescue-center-restored.txt")
    event(
        "rescue-offline-restore-complete",
        system=system_name,
        snapshot=snapshot_title,
        heading=name(complete),
        safety_snapshot=True,
    )
