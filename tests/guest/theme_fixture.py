#!/usr/bin/python3
"""Long-lived GTK fixture for the installed appearance acceptance suite."""

from __future__ import annotations

import gi

gi.require_version("Gtk", "4.0")
from gi.repository import Gio, GLib, Gtk


class ThemeFixture(Gtk.Application):
    def __init__(self) -> None:
        super().__init__(application_id="com.anduinos.AcceptanceThemeFixture")
        self._label: Gtk.Label | None = None
        self._interface = Gio.Settings.new("org.gnome.desktop.interface")
        self._interface.connect("changed::color-scheme", self._refresh)
        self._interface.connect("changed::gtk-theme", self._refresh)

    def do_activate(self) -> None:
        window = self.props.active_window
        if window is None:
            window = Gtk.ApplicationWindow(
                application=self,
                title="AnduinOS GTK Theme Acceptance Fixture",
            )
            window.set_default_size(900, 600)
            box = Gtk.Box(
                orientation=Gtk.Orientation.VERTICAL,
                spacing=24,
                halign=Gtk.Align.FILL,
                valign=Gtk.Align.FILL,
                hexpand=True,
                vexpand=True,
                margin_top=96,
                margin_bottom=96,
                margin_start=96,
                margin_end=96,
            )
            heading = Gtk.Label(label="GTK THEME FIXTURE")
            heading.add_css_class("title-1")
            heading.set_accessible_role(Gtk.AccessibleRole.HEADING)
            self._label = Gtk.Label()
            self._label.add_css_class("title-2")
            box.append(heading)
            box.append(self._label)
            window.set_child(box)
            self._refresh()
            window.maximize()
        window.present()

    def _refresh(self, *_args) -> None:
        if self._label is None:
            return
        scheme = self._interface.get_string("color-scheme")
        theme = self._interface.get_string("gtk-theme")
        marker = f"GTK SCHEME {scheme} THEME {theme}"
        self._label.set_label(marker)
        print(marker, flush=True)


if __name__ == "__main__":
    raise SystemExit(ThemeFixture().run())
