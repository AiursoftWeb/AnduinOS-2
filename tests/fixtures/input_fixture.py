#!/usr/bin/python3
"""Single real GTK input surface for IBus/Rime end-to-end acceptance."""

from __future__ import annotations

import gi

gi.require_version("Gtk", "4.0")
from gi.repository import Gtk


class InputFixture(Gtk.Application):
    def __init__(self) -> None:
        super().__init__(application_id="com.anduinos.AcceptanceInputFixture")

    def do_activate(self) -> None:
        window = Gtk.ApplicationWindow(
            application=self,
            title="AnduinOS Rime Input Fixture",
        )
        window.set_default_size(720, 240)
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=18)
        box.set_margin_top(36)
        box.set_margin_bottom(36)
        box.set_margin_start(36)
        box.set_margin_end(36)
        label = Gtk.Label(label="AnduinOS Rime Input Field")
        label.set_xalign(0)
        entry = Gtk.Entry()
        entry.set_placeholder_text("Type through the active input method")
        entry.set_hexpand(True)
        label.set_mnemonic_widget(entry)
        box.append(label)
        box.append(entry)
        window.set_child(box)
        window.present()
        entry.grab_focus()


if __name__ == "__main__":
    raise SystemExit(InputFixture().run())
