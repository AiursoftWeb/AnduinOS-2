"""Snapshots, fonts, files, editors, executables, and Rime behavior."""

from .core import *  # noqa: F403
from .installer import wait_application


def verify_snapshots_manager(evidence: Path) -> None:
    dismiss_initial_setup()
    subprocess.Popen(
        ["gtk-launch", "org.anduinos.BtrfsSnapshotsManager"],
        stdin=subprocess.DEVNULL,
        stdout=open("/tmp/anduinos-snapshots-manager.stdout", "wb"),
        stderr=subprocess.STDOUT,
        start_new_session=True,
    )
    application = wait_application(
        (
            "Disk Snapshots Manager",
            "BtrfsSnapshotsManager",
            "anduinos-btrfs-snapshots-manager",
        ),
        timeout=90,
    )
    find("snapshots_manager", timeout=30)
    dump_accessibility(evidence / "snapshots-manager.txt")
    event("snapshots-manager", application=application)


def arm_snapshot_restore(title: str, evidence: Path) -> None:
    """Choose one exact deployment in the real GUI and arm its rollback."""

    dismiss_initial_setup()
    subprocess.Popen(
        ["gtk-launch", "org.anduinos.BtrfsSnapshotsManager"],
        stdin=subprocess.DEVNULL,
        stdout=open("/tmp/anduinos-snapshots-manager.stdout", "ab"),
        stderr=subprocess.STDOUT,
        start_new_session=True,
    )
    wait_application(
        (
            "Disk Snapshots Manager",
            "BtrfsSnapshotsManager",
            "anduinos-btrfs-snapshots-manager",
        ),
        timeout=90,
    )
    deadline = time.monotonic() + 90
    snapshot = None
    while time.monotonic() < deadline:
        # GTK exposes a list item's title twice: once as the semantic list
        # item name and again as its implementation label.  Count only the
        # owning rows so one real snapshot cannot look like two deployments.
        rows = [
            item
            for item in visible_nodes()
            if role(item) == "list item" and name(item) == title and showing(item)
        ]
        if len(rows) == 1:
            snapshot = rows[0]
            break
        if len(rows) > 1:
            dump_accessibility(evidence / "snapshot-restore-ambiguous.txt")
            raise UiFailure(
                f"Multiple snapshot rows have the exact title {title!r}"
            )
        time.sleep(0.5)
    if snapshot is None:
        dump_accessibility(evidence / "snapshot-restore-missing.txt")
        raise UiFailure(f"Snapshot {title!r} did not appear in the recovery UI")

    # Invoke the Roll Back button *inside this exact row*. A global text lookup
    # would silently choose the first snapshot's button when multiple rows are
    # present and could roll back to the wrong deployment.
    rollback_buttons = [
        item
        for item in walk(snapshot, maximum=200)
        if role(item) == "button"
        and name(item) in {"Roll Back", "回滚"}
        and showing(item)
    ]
    if len(rollback_buttons) != 1:
        dump_accessibility(evidence / "snapshot-restore-button-failure.txt")
        raise UiFailure(
            f"Snapshot {title!r} exposes {len(rollback_buttons)} semantic "
            "Roll Back buttons"
        )
    target = actionable(rollback_buttons[0])
    if not perform_action(target, 0):
        raise UiFailure(f"Could not invoke Roll Back for snapshot {title!r}")
    event(
        "snapshot-rollback-click",
        title=title,
        row_role=role(snapshot),
        button=name(rollback_buttons[0]),
    )
    confirmation = find_candidates(
        (f"Roll Back to {title}?", f"回滚到 {title}？"),
        label=f"rollback confirmation for {title}",
        timeout=30,
    )
    event(
        "snapshot-rollback-confirmation",
        title=title,
        accessible_name=name(confirmation),
    )
    dump_accessibility(evidence / "snapshot-restore-confirmation.txt")
    click("snapshot_prepare_restart", timeout=30)
    if find_optional("polkit", timeout=8) is not None:
        # The password is deliberately never passed into this process or its
        # serial transcript. The host recognizes this opaque request and types
        # its in-memory secret directly through QMP.
        event("qmp-secret", request="snapshot-polkit-password")
        event("qmp-key", request="snapshot-polkit-submit", key="ret")
    find("snapshot_armed", timeout=90)
    find("snapshot_restart_now", timeout=30, require_enabled=True)
    dump_accessibility(evidence / "snapshot-rollback-armed.txt")
    event(
        "snapshot-rollback-armed",
        title=title,
        restart="automatic-countdown-visible",
    )


def verify_font_rendering(evidence: Path) -> None:
    """Open the production GTK/Pango stack and expose exact text over AT-SPI."""

    dismiss_initial_setup()
    fixture = Path(__file__).resolve().parent.parent / "font_fixture.py"
    if not fixture.is_file():
        raise UiFailure(f"Font rendering fixture is missing: {fixture}")
    output_path = Path("/tmp/anduinos-font-fixture.stdout")
    output_stream = output_path.open("wb")
    process = subprocess.Popen(
        [sys.executable, str(fixture)],
        stdin=subprocess.DEVNULL,
        stdout=output_stream,
        stderr=subprocess.STDOUT,
        start_new_session=True,
    )
    deadline = time.monotonic() + 90
    while time.monotonic() < deadline:
        if any(
            name(item) == "AnduinOS Font Rendering Fixture"
            for item in visible_nodes()
        ):
            break
        if process.poll() is not None:
            output_stream.close()
            output = output_path.read_text(encoding="utf-8", errors="replace")
            raise UiFailure(
                f"Font fixture exited with {process.returncode}: {output[-4000:]}"
            )
        time.sleep(0.25)
    else:
        output_stream.close()
        raise UiFailure("AT-SPI did not discover the font fixture window")
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        visible_names = {name(item) for item in visible_nodes() if name(item)}
        if {"🤓 🍔 🔫 👽 ✨", "变角次亮采之门"} <= visible_names:
            (evidence / "font-rendering-text.txt").write_text(
                "🤓 🍔 🔫 👽 ✨\n变角次亮采之门\n",
                encoding="utf-8",
            )
            break
        time.sleep(0.25)
    else:
        dump_accessibility(evidence / "font-rendering-failure.txt")
        raise UiFailure("Font fixture did not expose the exact test strings")
    dump_accessibility(evidence / "font-rendering.txt")
    event(
        "font-rendering",
        application="AnduinOS Font Rendering Fixture",
        emoji="🤓 🍔 🔫 👽 ✨",
        chinese="变角次亮采之门",
    )


def _select_download_in_nautilus(filename: str) -> tuple[Path, list]:
    """Select one exact Downloads item and return its accessible candidates."""

    downloads = Path.home() / "Downloads"
    target_path = downloads / filename
    if not target_path.is_file():
        raise UiFailure(f"Desktop fixture is missing: {target_path}")
    subprocess.Popen(
        ["nautilus", "--new-window", "--select", str(target_path)],
        stdin=subprocess.DEVNULL,
        stdout=open("/tmp/anduinos-nautilus.stdout", "ab"),
        stderr=subprocess.STDOUT,
        start_new_session=True,
    )
    wait_application(("Files", "Nautilus", "文件"), timeout=90)
    deadline = time.monotonic() + 60
    candidates = []
    while time.monotonic() < deadline:
        candidates = [
            item
            for item in visible_nodes()
            if name(item) == filename or name(item).startswith(filename + ".")
        ]
        if candidates:
            priority = {"table row": 0, "table cell": 1, "label": 2}
            candidates.sort(key=lambda item: priority.get(role(item), 3))
            break
        time.sleep(0.25)
    if not candidates:
        raise UiFailure(f"Nautilus did not expose {filename!r}")
    return target_path, candidates


def _open_download_in_nautilus(
    filename: str,
    expected: str | None,
    evidence: Path,
) -> None:
    """Open one selected Nautilus item through real host-delivered input."""

    target_path, candidates = _select_download_in_nautilus(filename)

    opened = False
    activation_method = ""
    # Wayland may deliberately withhold global coordinates. When it does
    # expose trustworthy screen bounds, ask the host SPICE client to deliver
    # the complete physical double-click. AT-SPI is only the semantic target
    # oracle; it must not synthesize the activation itself.
    for file_node in candidates:
        try:
            if not file_node.is_component():
                continue
            bounds = file_node.get_extents(Atspi.CoordType.SCREEN)
            if (
                # GTK4/Wayland may expose widget-relative rectangles such as
                # [0, 0, 662, 44] even when SCREEN was requested. Treat an
                # origin on either zero axis as non-global; the real trace
                # proved that accepting it double-clicks QEMU's top edge.
                bounds.x <= 0
                or bounds.y <= 0
                or bounds.width <= 0
                or bounds.height <= 0
            ):
                continue
            request_node_double_click(
                file_node,
                f"open-{filename}-double-click",
                semantic_target=filename,
            )
            event(
                "nautilus-open-attempt",
                filename=filename,
                method="host-spice-double-click",
                bounds=[bounds.x, bounds.y, bounds.width, bounds.height],
            )
            opened = True
            activation_method = "host-spice-double-click"
            break
        except Exception:
            continue

    # If Wayland hides coordinates, use Nautilus' coordinate-free keyboard
    # activation. The CLI selected the exact fixture before this point. Cycle
    # the real focus chain with QMP Tab until the selected row/content view is
    # observably focused, then let QMP deliver Enter. Never treat an AT-SPI
    # Action.do_action() return value as evidence that the file was opened.
    if not opened:
        selected_row = None
        for file_node in candidates:
            if role(file_node) != "table row":
                continue
            try:
                parent = file_node.get_parent()
                index = file_node.get_index_in_parent()
                if parent is None or not parent.is_selection():
                    continue
                if not parent.select_child(index):
                    continue
            except Exception:
                continue
            time.sleep(0.2)
            selected = has_state(file_node, Atspi.StateType.SELECTED)
            if not selected:
                continue
            selected_row = file_node
            break

        if selected_row is not None:
            for focus_attempt in range(40):
                if focus_within(selected_row):
                    event(
                        "qmp-key",
                        request=f"open-{filename}-ret",
                        key="ret",
                    )
                    event(
                        "nautilus-open-attempt",
                        filename=filename,
                        method="selected-item-qmp-enter",
                        focused=True,
                        focus_tabs=focus_attempt,
                    )
                    opened = True
                    activation_method = "selected-item-qmp-enter"
                    break
                event(
                    "qmp-key",
                    request=f"focus-{filename}-{focus_attempt}-tab",
                    key="tab",
                )
                time.sleep(0.2)

    if not opened:
        focused = [
            {
                "application": owning_application(item),
                "role": role(item),
                "name": name(item),
            }
            for item in visible_nodes()
            if has_state(item, Atspi.StateType.FOCUSED)
        ]
        raise UiFailure(
            "Nautilus could not focus the selected fixture for real host input: "
            f"{filename!r}; focused={focused!r}"
        )
    if expected is None:
        # Give Nautilus enough time to present any warning and, more
        # importantly, enough time for an incorrectly launched fixture to
        # expose either its process or its accessible GTK window.
        time.sleep(6)
        fixture_names = set(aliases("appimage_fixture"))
        fixture_window_visible = any(
            name(item) in fixture_names for item in visible_nodes()
        )
        filename_bytes = filename.encode("utf-8")
        target_resolved = target_path.resolve()
        direct_processes = []
        referencing_processes = []
        for command_line in Path("/proc").glob("[0-9]*/cmdline"):
            try:
                value = command_line.read_bytes()
            except (FileNotFoundError, PermissionError, ProcessLookupError):
                continue
            if filename_bytes not in value:
                continue
            process = command_line.parent
            arguments = [item for item in value.split(b"\0") if item]
            try:
                executable = (process / "exe").resolve(strict=True)
            except (FileNotFoundError, PermissionError, ProcessLookupError):
                executable = None
            direct = False
            if executable is not None:
                try:
                    direct = executable.samefile(target_resolved)
                except (FileNotFoundError, OSError):
                    direct = False
            if not direct and arguments:
                try:
                    argument_zero = Path(os.fsdecode(arguments[0]))
                    if argument_zero.is_absolute():
                        direct = argument_zero.samefile(target_resolved)
                except (FileNotFoundError, OSError, UnicodeError):
                    direct = False
            observation = {
                "pid": int(process.name),
                "argv0": os.fsdecode(arguments[0]) if arguments else "",
                "executable": str(executable) if executable is not None else "",
            }
            referencing_processes.append(observation)
            if direct:
                direct_processes.append(observation)
        process_running = bool(direct_processes)
        executable = os.access(target_path, os.X_OK)
        dump_accessibility(evidence / f"{filename}-blocked.txt")
        event(
            "nautilus-open-blocked",
            filename=filename,
            activation_method=activation_method,
            executable=executable,
            fixture_window_visible=fixture_window_visible,
            process_running=process_running,
            direct_processes=direct_processes,
            referencing_processes=referencing_processes,
        )
        if executable or fixture_window_visible or process_running:
            raise UiFailure(
                "Nautilus crossed the non-executable AppImage boundary: "
                f"executable={executable}, "
                f"fixture_window_visible={fixture_window_visible}, "
                f"process_running={process_running}"
            )
        # Nautilus is allowed to explain why execution was refused. Dismiss
        # that transient surface through real host input so it cannot obscure
        # the following independent PE dispatch check.
        event(
            "qmp-key",
            request=f"dismiss-{filename}-warning",
            key="esc",
        )
        time.sleep(0.5)
        return

    observed = name(find(expected, timeout=90))
    dump_accessibility(evidence / f"{filename}-opened.txt")
    event(
        "nautilus-open",
        filename=filename,
        activation_method=activation_method,
        observed=observed,
    )


def verify_appimage_file(evidence: Path) -> None:
    dismiss_initial_setup()
    Path("/tmp/anduinos-nautilus.stdout").unlink(missing_ok=True)
    try:
        _open_download_in_nautilus(
            "AnduinOS-Acceptance.AppImage",
            "appimage_fixture",
            evidence,
        )
    finally:
        subprocess.run(
            ["pkill", "-f", "AnduinOS-Acceptance.AppImage"],
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        subprocess.run(
            ["pkill", "-x", "zenity"],
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )


def verify_non_executable_appimage_file(evidence: Path) -> None:
    dismiss_initial_setup()
    Path("/tmp/anduinos-nautilus.stdout").unlink(missing_ok=True)
    _open_download_in_nautilus(
        "AnduinOS-Blocked.AppImage",
        None,
        evidence,
    )


def verify_file_thumbnail(filename: str, evidence: Path) -> None:
    """Require Nautilus to generate a content thumbnail for one exact URI."""

    dismiss_initial_setup()
    target_path, candidates = _select_download_in_nautilus(filename)
    uri = target_path.resolve().as_uri()
    digest = hashlib.md5(uri.encode("utf-8"), usedforsecurity=False).hexdigest()
    cache_roots = (
        Path.home() / ".cache" / "thumbnails" / size
        for size in ("normal", "large", "x-large", "xx-large")
    )
    thumbnail = None
    deadline = time.monotonic() + 120
    while time.monotonic() < deadline:
        for root in cache_roots:
            candidate = root / f"{digest}.png"
            if candidate.is_file() and candidate.stat().st_size > 128:
                thumbnail = candidate
                break
        if thumbnail is not None:
            break
        # Recreate the generator because cache_roots is deliberately lazy.
        cache_roots = (
            Path.home() / ".cache" / "thumbnails" / size
            for size in ("normal", "large", "x-large", "xx-large")
        )
        time.sleep(0.5)
    if thumbnail is None:
        dump_accessibility(evidence / f"{filename}-thumbnail-missing.txt")
        raise UiFailure(f"Nautilus generated no thumbnail for {filename!r}")
    visible = [
        {"name": name(item), "role": role(item)}
        for item in candidates
        if showing(item)
    ]
    if not visible:
        raise UiFailure(f"Nautilus hid {filename!r} while generating its thumbnail")
    dump_accessibility(evidence / f"{filename}-thumbnail-visible.txt")
    event(
        "file-thumbnail",
        filename=filename,
        uri=uri,
        cache_path=str(thumbnail),
        cache_size=thumbnail.stat().st_size,
        visible_nodes=visible,
    )


def verify_image_open(evidence: Path) -> None:
    dismiss_initial_setup()
    filename = "AnduinOS-Image.png"
    _open_download_in_nautilus(filename, filename, evidence)
    application = wait_application(("loupe", "image viewer", "图像查看器"), timeout=90)
    running = subprocess.run(
        ("pgrep", "-x", "loupe"),
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        text=True,
    ).returncode == 0
    windows = sorted(
        {
            name(item)
            for item in visible_nodes()
            if owning_application(item) == application and name(item)
        }
    )
    if not running or not windows:
        raise UiFailure("Loupe did not expose the opened image fixture")
    event(
        "image-opened",
        filename=filename,
        application=application,
        process_running=running,
        visible_names=windows,
    )


def _gdbus_call(*arguments: str) -> str:
    result = subprocess.run(
        ("gdbus", "call", "--session", *arguments),
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        timeout=15,
    )
    if result.returncode != 0:
        raise UiFailure("D-Bus query failed: " + result.stdout)
    return result.stdout


def verify_video_open(evidence: Path) -> None:
    dismiss_initial_setup()
    filename = "AnduinOS-Video.mp4"
    _open_download_in_nautilus(filename, filename, evidence)
    application = wait_application(("celluloid",), timeout=90)
    names = _gdbus_call(
        "--dest",
        "org.freedesktop.DBus",
        "--object-path",
        "/org/freedesktop/DBus",
        "--method",
        "org.freedesktop.DBus.ListNames",
    )
    matches = sorted(
        set(
            re.findall(
                r"org\.mpris\.MediaPlayer2\.[^'\s,)]*celluloid[^'\s,)]*",
                names,
                re.IGNORECASE,
            )
        )
    )
    if len(matches) != 1:
        raise UiFailure(f"Celluloid exposed no unique MPRIS identity: {matches!r}")
    destination = matches[0]

    def property_value(property_name: str) -> str:
        return _gdbus_call(
            "--dest",
            destination,
            "--object-path",
            "/org/mpris/MediaPlayer2",
            "--method",
            "org.freedesktop.DBus.Properties.Get",
            "org.mpris.MediaPlayer2.Player",
            property_name,
        )

    metadata = property_value("Metadata")
    if filename not in metadata:
        raise UiFailure("Celluloid MPRIS metadata does not identify the fixture")
    position = 0
    status = ""
    deadline = time.monotonic() + 30
    requested_play = False
    while time.monotonic() < deadline:
        status_output = property_value("PlaybackStatus")
        status_match = re.search(r"(?:Playing|Paused|Stopped)", status_output)
        status = status_match.group(0) if status_match else ""
        position_output = property_value("Position")
        position_match = re.search(r"(?:u?int64)\s+(\d+)", position_output)
        position = int(position_match.group(1)) if position_match else 0
        if position > 100_000:
            break
        if status == "Paused" and not requested_play:
            event("qmp-key", request="celluloid-start-playback", key="spc")
            requested_play = True
        time.sleep(0.5)
    if position <= 100_000:
        raise UiFailure(
            f"Celluloid playback never advanced: status={status!r}, position={position}"
        )
    event(
        "video-opened",
        filename=filename,
        application=application,
        mpris_destination=destination,
        playback_status=status,
        position_microseconds=position,
        metadata_identifies_fixture=True,
    )


def verify_deb_software(evidence: Path) -> None:
    dismiss_initial_setup()
    filename = "anduinos-acceptance-fixture_1.0_all.deb"
    _open_download_in_nautilus(filename, filename, evidence)
    application = wait_application(("gnome-software", "software", "软件"), timeout=120)
    deadline = time.monotonic() + 120
    details = []
    while time.monotonic() < deadline:
        details = [
            name(item)
            for item in visible_nodes()
            if owning_application(item) == application
            and (
                "anduinos acceptance fixture" in name(item).casefold()
                or "anduinos-acceptance-fixture" in name(item).casefold()
            )
        ]
        if details:
            break
        time.sleep(0.5)
    installed = subprocess.run(
        ("dpkg-query", "-W", "-f=${db:Status-Abbrev}", "anduinos-acceptance-fixture"),
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        text=True,
    ).stdout.strip().startswith("ii ")
    if not details or installed:
        dump_accessibility(evidence / "deb-software-page-missing.txt")
        raise UiFailure(
            f"GNOME Software did not expose the harmless DEB without installing it: "
            f"details={details!r}, installed={installed}"
        )
    event(
        "deb-software",
        filename=filename,
        application=application,
        detail_names=sorted(set(details)),
        package_installed=installed,
    )


def verify_chinese_editor(evidence: Path) -> None:
    """Edit and save the exact acceptance phrase in GNOME Text Editor."""

    dismiss_initial_setup()
    filename = "AnduinOS-Chinese.txt"
    target_path = Path.home() / "Downloads" / filename
    _open_download_in_nautilus(filename, filename, evidence)
    application = wait_application(
        ("gnome-text-editor", "text editor", "文本编辑器"),
        timeout=90,
    )
    deadline = time.monotonic() + 60
    editables = []
    while time.monotonic() < deadline:
        editables = []
        for item in visible_nodes():
            if owning_application(item) != application:
                continue
            try:
                if item.is_editable_text() and showing(item):
                    editables.append(item)
            except Exception:
                continue
        if editables:
            break
        time.sleep(0.25)
    if not editables:
        dump_accessibility(evidence / "chinese-editor-missing.txt")
        raise UiFailure("GNOME Text Editor exposed no editable document surface")

    def editable_area(item) -> int:
        try:
            bounds = item.get_extents(Atspi.CoordType.WINDOW)
            return max(0, bounds.width) * max(0, bounds.height)
        except Exception:
            return 0

    target = max(editables, key=editable_area)
    expected = "变角次亮采之门"
    try:
        target.grab_focus()
    except Exception:
        pass
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        if has_state(target, Atspi.StateType.FOCUSED):
            break
        time.sleep(0.1)
    else:
        raise UiFailure("GNOME Text Editor document surface did not gain focus")

    text_interface = target.get_text()
    initial_count = Atspi.Text.get_character_count(text_interface)
    initial = Atspi.Text.get_text(text_interface, 0, initial_count)
    if initial:
        raise UiFailure(
            f"GNOME Text Editor fixture was not initially empty: {initial!r}"
        )
    # Type every non-ASCII character through Linux's standard Unicode input
    # sequence. The host supplies the physical Ctrl+Shift+U, hexadecimal code
    # point, and Enter events; AT-SPI only verifies focus and the final text.
    for index, character in enumerate(expected):
        event(
            "qmp-key",
            request=f"chinese-editor-unicode-{index}-start",
            key="ctrl-shift-u",
        )
        event("qmp-text", request=f"chinese-editor-unicode-{index}-codepoint")
        event(
            "qmp-key",
            request=f"chinese-editor-unicode-{index}-commit",
            key="ret",
        )
    deadline = time.monotonic() + 30
    observed = ""
    while time.monotonic() < deadline:
        count = Atspi.Text.get_character_count(text_interface)
        observed = Atspi.Text.get_text(text_interface, 0, count)
        observed = unicodedata.normalize("NFC", observed)
        if observed == expected:
            break
        time.sleep(0.1)
    else:
        raise UiFailure(
            f"GNOME Text Editor returned {observed!r}, expected {expected!r}"
        )
    def activate_editor_control(names: tuple[str, ...], purpose: str) -> str:
        semantic_names = {semantic_name(value) for value in names}
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            for item in visible_nodes():
                if (
                    owning_application(item) != application
                    or semantic_name(name(item)) not in semantic_names
                    or not showing(item)
                ):
                    continue
                try:
                    control = actionable(item)
                    actions = [
                        action_name(control, action_index)
                        for action_index in range(action_count(control))
                    ]
                except Exception:
                    continue
                if perform_action(control, 0):
                    event(
                        "text-editor-action",
                        purpose=purpose,
                        accessible_name=name(item),
                        actions=actions,
                    )
                    time.sleep(0.35)
                    return name(item)
            time.sleep(0.25)
        raise UiFailure(
            f"GNOME Text Editor exposed no actionable {purpose}: {names!r}"
        )

    # GTK 4 does not expose ordinary GMenu rows (including Save) through
    # AT-SPI, and the popover's custom children incorrectly report 0,0 for
    # SCREEN coordinates. The title-bar menu button does expose correct screen
    # bounds. This acceptance VM has an explicitly verified 1280x800
    # framebuffer, and Text Editor opens at a deterministic centered size.
    # Click the rendered Save row in that fixed viewport. A future resolution
    # or layout change fails the host precondition or the exact-byte oracle.
    save_name = "Save menu row"
    # GNOME Text Editor deliberately enables GtkSourceBuffer's implicit
    # trailing newline by default. The visible document remains exactly the
    # requested seven characters; its normal serialized form contains one
    # additional LF and nothing else.
    serialized = (expected + "\n").encode("utf-8")
    saved = b""
    menu_name = ""
    save_attempts = 0
    for save_attempts in range(1, 4):
        menu_name = activate_editor_control(("Main Menu", "主菜单"), "main-menu")
        event(
            "qmp-click",
            request="chinese-editor-save-menu-row",
            target="Save",
            anchor="fixed-1280x800-framebuffer",
            x_px=852,
            y_px=364,
            button="left",
            framebuffer=[1280, 800],
            attempt=save_attempts,
        )
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            try:
                saved = target_path.read_bytes()
            except OSError:
                saved = b""
            if saved == serialized:
                break
            time.sleep(0.25)
        if saved == serialized:
            break
    if saved != serialized:
        raise UiFailure(
            "GNOME Text Editor did not save the exact normalized UTF-8 text "
            f"with its one implicit trailing newline after {save_attempts} attempts; "
            f"observed {len(saved)} bytes with SHA-256 {hashlib.sha256(saved).hexdigest()}"
        )
    running = subprocess.run(
        ("pgrep", "-f", "(^|/)gnome-text-editor( |$)"),
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        text=True,
    ).returncode == 0
    if not running:
        raise UiFailure("GNOME Text Editor exited while saving the fixture")
    dump_accessibility(evidence / "chinese-editor-saved.txt")
    event(
        "chinese-editor",
        filename=filename,
        application=application,
        expected=expected,
        observed=observed,
        menu_accessible_name=menu_name,
        save_accessible_name=save_name,
        character_count=len(observed),
        utf8_sha256=hashlib.sha256(saved).hexdigest(),
        implicit_trailing_newline=True,
        save_attempts=save_attempts,
        process_running=running,
        saved=True,
    )


def verify_windows_executable_file(evidence: Path) -> None:
    dismiss_initial_setup()
    Path("/tmp/anduinos-nautilus.stdout").unlink(missing_ok=True)
    _open_download_in_nautilus("cpu-z.exe", "cpuz_recommendation", evidence)
    find("mission_center", timeout=30)
    event("cpu-z-recommendation", application="AnduinOS Windows EXE Runner")


def verify_windows_executable_thumbnail(evidence: Path) -> None:
    verify_file_thumbnail("cpu-z.exe", evidence)


def verify_public_cpuz_file(filename: str, evidence: Path) -> None:
    """Preview and dispatch the pinned public CPU-Z binary on a clean system."""

    if filename != "cpuz_x64.exe":
        raise UiFailure(f"Unsupported public CPU-Z member: {filename!r}")
    dismiss_initial_setup()
    Path("/tmp/anduinos-nautilus.stdout").unlink(missing_ok=True)
    verify_file_thumbnail(filename, evidence)
    _open_download_in_nautilus(filename, "cpuz_installing", evidence)

    reason = find("cpuz_native_reason", timeout=30)
    controls = {
        key: find(key, timeout=30)
        for key in ("cancel", "force_run", "cpux_get")
    }
    control_evidence = {
        key: {
            "name": name(node),
            "role": role(node),
            "enabled": enabled(node),
            "showing": showing(node),
        }
        for key, node in controls.items()
    }
    if any(
        value["role"] not in {"button", "push button"}
        or value["enabled"] is not True
        or value["showing"] is not True
        for value in control_evidence.values()
    ):
        dump_accessibility(evidence / "cpuz-recommendation-controls-failed.txt")
        raise UiFailure(
            "CPU-Z native recommendation has unusable semantic controls: "
            f"{control_evidence!r}"
        )

    bottles = subprocess.run(
        ("flatpak", "info", "com.usebottles.bottles"),
        check=False,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    ).returncode == 0
    runner = subprocess.run(
        ("pgrep", "-af", "anduinos-exe-runner"),
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        text=True,
    )
    runner_lines = [
        line
        for line in runner.stdout.splitlines()
        if filename in line and "pgrep -af" not in line
    ]
    if bottles or not runner_lines:
        dump_accessibility(evidence / "cpuz-runner-precondition-failed.txt")
        raise UiFailure(
            "CPU-Z did not reach its native-alternative EXE Runner page: "
            f"bottles_installed={bottles}, runner_lines={runner_lines!r}"
        )
    dump_accessibility(evidence / "cpuz-runner-opened.txt")
    event(
        "cpu-z-public-recommendation",
        filename=filename,
        application="AnduinOS Windows EXE Runner",
        heading=name(find("cpuz_installing", timeout=3)),
        reason=name(reason),
        controls=control_evidence,
        bottles_installed=bottles,
        runner_processes=runner_lines,
    )


def _rime_fixture_entry(evidence: Path):
    deadline = time.monotonic() + 90
    while time.monotonic() < deadline:
        for window in visible_nodes():
            if name(window) != "AnduinOS Rime Input Fixture":
                continue
            editables = []
            for item in walk(window, maximum=1000):
                try:
                    if item.is_editable_text() and showing(item):
                        editables.append(item)
                except Exception:
                    continue
            if len(editables) == 1:
                return editables[0]
            if editables:
                dump_accessibility(evidence / "rime-input-ambiguous.txt")
                raise UiFailure(
                    f"Rime fixture exposed {len(editables)} editable controls"
                )
        time.sleep(0.25)
    dump_accessibility(evidence / "rime-input-missing.txt")
    raise UiFailure("AT-SPI did not discover the Rime input fixture")


def prepare_rime_input(evidence: Path) -> None:
    dismiss_initial_setup()
    target = _rime_fixture_entry(evidence)
    if not target.set_text_contents(""):
        raise UiFailure("Could not clear the Rime input fixture")
    focused = has_state(target, Atspi.StateType.FOCUSED)
    if not focused:
        try:
            target.grab_focus()
        except Exception:
            pass
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        if has_state(target, Atspi.StateType.FOCUSED):
            break
        time.sleep(0.1)
    else:
        raise UiFailure("Rime input fixture never received keyboard focus")
    dump_accessibility(evidence / "rime-input-prepared.txt")
    event("rime-input-prepared", focused=True)


def assert_rime_input(expected: str, evidence: Path) -> None:
    target = _rime_fixture_entry(evidence)
    # Atspi.Accessible.get_text() returns the Text interface in current GI.
    # Calling the old range-taking form on Accessible itself fails on GNOME 50.
    text_interface = target.get_text()
    count = Atspi.Text.get_character_count(text_interface)
    # Accessible and Text both export a method named get_text. Invoke the
    # interface method explicitly so PyGObject cannot resolve the proxy back
    # to Accessible.get_text() and reject the range arguments.
    observed = Atspi.Text.get_text(text_interface, 0, count)
    normalized_expected = unicodedata.normalize("NFC", expected)
    normalized_observed = unicodedata.normalize("NFC", observed)
    (evidence / "rime-input-result.json").write_text(
        json.dumps(
            {
                "expected": normalized_expected,
                "observed": normalized_observed,
                "exact": normalized_observed == normalized_expected,
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    if normalized_observed != normalized_expected:
        dump_accessibility(evidence / "rime-input-wrong-text.txt")
        raise UiFailure(
            f"Rime produced {normalized_observed!r}, expected "
            f"{normalized_expected!r}"
        )
    event("rime-input-result", expected=normalized_expected, observed=normalized_observed)
__all__ = tuple(name for name in globals() if not name.startswith("__"))
