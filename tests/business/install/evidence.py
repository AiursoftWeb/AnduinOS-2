"""Boot, MOK, file-handler, and installed-region evidence oracles."""

from .shared import *  # noqa: F403


def _extract_boot_filename(output: str, key: str, prefix: str) -> str:
    matches = re.findall(rf"^{re.escape(key)}=(\S+)$", output, re.MULTILINE)
    if len(matches) != 1:
        raise TestFailure(f"Target discovery did not return exactly one {key}")
    filename = matches[0]
    if not filename.startswith(prefix) or re.fullmatch(
        r"[A-Za-z0-9][A-Za-z0-9._+-]*", filename
    ) is None:
        raise TestFailure(f"Target returned an unsafe boot filename: {filename!r}")
    return filename


def _validate_target_boot_integrity(output: str) -> None:
    """Reject a damaged installed kernel or an unreadable generated initramfs."""

    def exact_value(key: str) -> str:
        matches = re.findall(rf"^{re.escape(key)}=(\S+)$", output, re.MULTILINE)
        if len(matches) != 1:
            raise TestFailure(
                f"Target boot integrity probe did not return exactly one {key}"
            )
        return matches[0]

    target_hash = exact_value("ANDUINOS_TARGET_KERNEL_SHA256")
    iso_hash = exact_value("ANDUINOS_ISO_KERNEL_SHA256")
    for label, digest in (("target kernel", target_hash), ("ISO kernel", iso_hash)):
        if re.fullmatch(r"[0-9a-f]{64}", digest) is None:
            raise TestFailure(f"{label} returned an invalid SHA-256 digest")
    if target_hash != iso_hash:
        raise TestFailure(
            "Installed kernel differs byte-for-byte from the immutable ISO kernel"
        )
    if exact_value("ANDUINOS_INITRD_CHECK") != "ok":
        raise TestFailure("Installed initramfs did not pass structural validation")


def _validate_mok_lifecycle_evidence(
    pending_output: str,
    enrolled_output: str,
) -> None:
    """Correlate the pre-reboot pending certificate with the enrolled key."""

    def exact(output: str, key: str) -> str:
        matches = re.findall(rf"^{re.escape(key)}=(\S+)$", output, re.MULTILINE)
        if len(matches) != 1:
            raise TestFailure(f"MOK lifecycle evidence requires exactly one {key}")
        return matches[0]

    pending = exact(pending_output, "MOK_PENDING_FINGERPRINT")
    enrolled = exact(enrolled_output, "MOK_ENROLLED_FINGERPRINT")
    for label, fingerprint in (("pending", pending), ("enrolled", enrolled)):
        if re.fullmatch(r"[0-9A-F]{40}", fingerprint) is None:
            raise TestFailure(f"MOK {label} fingerprint is malformed")
    if exact(enrolled_output, "MOK_SECURE_BOOT") != "enabled":
        raise TestFailure("Secure Boot is not enabled after MOK enrollment")
    if exact(enrolled_output, "MOK_PENDING") != "none":
        raise TestFailure("MOK enrollment still has a pending certificate")
    if pending != enrolled:
        raise TestFailure(
            "The enrolled MOK fingerprint differs from the pre-reboot request"
        )

def _fixture_contract_values(
    output: str,
    required: set[str],
) -> dict[str, str]:
    values: dict[str, str] = {}
    for raw_line in output.splitlines():
        key, separator, value = raw_line.partition("=")
        if separator and key in required:
            if key in values:
                raise TestFailure(f"Duplicate desktop fixture evidence: {key}")
            values[key] = value.strip()
    missing = sorted(required - values.keys())
    if missing:
        raise TestFailure(
            "Desktop fixture evidence is incomplete: " + ", ".join(missing)
        )
    return values


def _validate_appimage_fixture_contract(output: str) -> None:
    """Validate native executable dispatch without inventing a MIME runner."""

    values = _fixture_contract_values(
        output,
        {
            "appimage-mime",
            "appimage-default",
            "appimage-runner-present",
            "appimage-mode",
            "appimage-blocked-mode",
        },
    )
    if values["appimage-mime"] not in {
        "application/vnd.appimage",
        "application/x-iso9660-appimage",
    }:
        raise TestFailure(
            "AppImage received an unsupported MIME type: "
            + values["appimage-mime"]
        )
    if values["appimage-default"]:
        raise TestFailure(
            "Executable AppImage unexpectedly depends on a MIME handler: "
            + values["appimage-default"]
        )
    if values["appimage-runner-present"] != "no":
        raise TestFailure("The obsolete AppImage MIME runner is still installed")
    if values["appimage-mode"] != "755":
        raise TestFailure(
            "The positive AppImage fixture is not explicitly executable: "
            + values["appimage-mode"]
        )
    if values["appimage-blocked-mode"] != "644":
        raise TestFailure(
            "The negative AppImage fixture accidentally has execute permission: "
            + values["appimage-blocked-mode"]
        )


def _validate_appimage_blocked_events(output: str) -> None:
    events: list[dict[str, object]] = []
    for line in output.splitlines():
        try:
            value = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict) and isinstance(value.get("event"), str):
            events.append(value)
    blocked = [
        value
        for value in events
        if value.get("event") == "nautilus-open-blocked"
    ]
    if len(blocked) != 1:
        raise TestFailure("Nautilus returned no unique blocked AppImage event")
    value = blocked[0]
    if (
        value.get("filename") != "AnduinOS-Blocked.AppImage"
        or value.get("executable") is not False
        or value.get("fixture_window_visible") is not False
        or value.get("process_running") is not False
        or value.get("activation_method")
        not in {"host-spice-double-click", "selected-item-qmp-enter"}
    ):
        raise TestFailure("The non-executable AppImage crossed the execution boundary")


def _validate_windows_executable_fixture_contract(output: str) -> None:
    """Validate PE MIME dispatch without depending on the AppImage result."""

    values = _fixture_contract_values(output, {"pe-mime", "pe-default"})
    if values["pe-mime"] != "application/vnd.microsoft.portable-executable":
        raise TestFailure(
            "CPU-Z PE fixture received the wrong MIME type: " + values["pe-mime"]
        )
    if values["pe-default"] != "com.anduinos.ExeRunner.desktop":
        rendered = values["pe-default"] or "<none>"
        raise TestFailure(
            "CPU-Z PE default handler is missing or incorrect: " + rendered
        )


def _validate_windows_executable_thumbnail_events(
    output: str,
    username: str,
) -> dict[str, object]:
    """Require one visible, retrievable Nautilus thumbnail for the PE fixture."""

    events = _driver_events(output)
    thumbnails = [
        (index, value)
        for index, value in enumerate(events)
        if value.get("event") == "file-thumbnail"
        and value.get("filename") == "cpu-z.exe"
    ]
    if len(thumbnails) != 1:
        raise TestFailure("Windows PE workflow did not emit one thumbnail event")
    _, thumbnail = thumbnails[0]
    cache_path = thumbnail.get("cache_path")
    visible = thumbnail.get("visible_nodes")
    expected_uri = f"file:///home/{username}/Downloads/cpu-z.exe"
    if (
        thumbnail.get("uri") != expected_uri
        or not isinstance(cache_path, str)
        or re.fullmatch(
            rf"/home/{re.escape(username)}/\.cache/thumbnails/"
            r"(?:normal|large|x-large|xx-large)/[0-9a-f]{32}\.png",
            cache_path,
        )
        is None
        or isinstance(thumbnail.get("cache_size"), bool)
        or not isinstance(thumbnail.get("cache_size"), int)
        or thumbnail["cache_size"] <= 128
        or not isinstance(visible, list)
        or not any(
            isinstance(item, dict) and item.get("name") == "cpu-z.exe"
            for item in visible
        )
    ):
        raise TestFailure("Windows PE fixture returned invalid thumbnail evidence")
    return thumbnail


def _validate_windows_executable_open_events(output: str) -> None:
    """Require one real Nautilus activation followed by EXE Runner UI."""

    events = _driver_events(output)
    opened = [
        (index, value)
        for index, value in enumerate(events)
        if value.get("event") == "nautilus-open"
        and value.get("filename") == "cpu-z.exe"
    ]
    recommendations = [
        (index, value)
        for index, value in enumerate(events)
        if value.get("event") == "cpu-z-recommendation"
    ]
    if len(opened) != 1 or len(recommendations) != 1:
        raise TestFailure(
            "Windows PE workflow did not emit one open and EXE Runner "
            "recommendation event"
        )
    opened_index, activation = opened[0]
    recommendation_index, recommendation = recommendations[0]
    if (
        activation.get("activation_method")
        not in {"host-spice-double-click", "selected-item-qmp-enter"}
        or not isinstance(activation.get("observed"), str)
        or not activation["observed"]
        or recommendation.get("application") != "AnduinOS Windows EXE Runner"
    ):
        raise TestFailure("Windows PE fixture did not reach the real EXE Runner")
    if not opened_index < recommendation_index:
        raise TestFailure("Windows PE workflow events occurred out of order")


def _driver_events(output: str) -> list[dict[str, object]]:
    events: list[dict[str, object]] = []
    for line in output.splitlines():
        try:
            value = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict) and isinstance(value.get("event"), str):
            events.append(value)
    return events


def _validate_installed_region_ui_events(output: str) -> None:
    values = [
        value
        for value in _driver_events(output)
        if value.get("event") == "installed-region-zh-cn"
    ]
    if len(values) != 1:
        raise TestFailure(
            "Installed GNOME region probe did not emit one exact UI observation"
        )
    value = values[0]
    if value.get("application") != "gnome-shell" or value.get("markers") != [
        {"role": "menu", "name": "系统"},
        {"role": "toggle button", "name": "显示应用"},
    ]:
        raise TestFailure(
            "Installed GNOME Shell is not visibly localized to Simplified Chinese"
        )


__all__ = tuple(name for name in globals() if not name.startswith("__"))
