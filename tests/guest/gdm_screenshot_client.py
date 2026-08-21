#!/usr/bin/python3
"""Capture GDM through GNOME Shell's real trusted screenshot interface.

GNOME Shell intentionally accepts non-interactive screenshot calls only from
the media-keys daemon or the desktop portal. The acceptance overlay stops the
real media-keys target briefly, owns that exact well-known name on the same
session bus, performs one capture, and releases the name. The caller cannot
silently queue behind another owner, and the harness restarts GDM afterwards.
"""

from __future__ import annotations

import argparse
import json
import time


TRUSTED_NAME = "org.gnome.SettingsDaemon.MediaKeys"
DBUS_REQUEST_NAME_REPLY_PRIMARY_OWNER = 1
DBUS_REQUEST_NAME_FLAGS_DO_NOT_QUEUE = 4


def _require_primary_owner(reply: int) -> None:
    if reply != DBUS_REQUEST_NAME_REPLY_PRIMARY_OWNER:
        raise RuntimeError(
            f"Could not become the trusted screenshot sender: RequestName={reply}"
        )


def _require_screenshot_reply(
    success: bool,
    filename_used: str,
    requested: str,
) -> None:
    if not success:
        raise RuntimeError("GNOME Shell reported that screenshot capture failed")
    if filename_used != requested:
        raise RuntimeError(
            "GNOME Shell used an unexpected screenshot path: "
            f"requested={requested!r}, used={filename_used!r}"
        )


def capture(output: str) -> dict[str, object]:
    # Keep GI lazy: the pure failure-oracle helpers are imported by the host
    # unit suite, which must not initialize and finalize a second GLib runtime.
    from gi.repository import Gio, GLib

    connection = Gio.bus_get_sync(Gio.BusType.SESSION, None)
    requested = connection.call_sync(
        "org.freedesktop.DBus",
        "/org/freedesktop/DBus",
        "org.freedesktop.DBus",
        "RequestName",
        GLib.Variant(
            "(su)",
            (TRUSTED_NAME, DBUS_REQUEST_NAME_FLAGS_DO_NOT_QUEUE),
        ),
        GLib.VariantType.new("(u)"),
        Gio.DBusCallFlags.NONE,
        30_000,
        None,
    )
    owner_reply = int(requested.unpack()[0])
    _require_primary_owner(owner_reply)
    try:
        # Let GNOME Shell's NameOwnerChanged watcher observe our unique name
        # before the method call reaches its allow-list check.
        time.sleep(0.5)
        reply = connection.call_sync(
            "org.gnome.Shell.Screenshot",
            "/org/gnome/Shell/Screenshot",
            "org.gnome.Shell.Screenshot",
            "Screenshot",
            GLib.Variant("(bbs)", (True, False, output)),
            GLib.VariantType.new("(bs)"),
            Gio.DBusCallFlags.NONE,
            30_000,
            None,
        )
        success, filename_used = reply.unpack()
        _require_screenshot_reply(bool(success), str(filename_used), output)
        return {
            "trusted_name": TRUSTED_NAME,
            "request_name_reply": owner_reply,
            "include_cursor": True,
            "success": True,
            "filename": filename_used,
        }
    finally:
        connection.call_sync(
            "org.freedesktop.DBus",
            "/org/freedesktop/DBus",
            "org.freedesktop.DBus",
            "ReleaseName",
            GLib.Variant("(s)", (TRUSTED_NAME,)),
            GLib.VariantType.new("(u)"),
            Gio.DBusCallFlags.NONE,
            30_000,
            None,
        )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    print(json.dumps(capture(args.output), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
