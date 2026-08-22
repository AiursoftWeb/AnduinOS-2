#!/usr/bin/python3
"""One real GTK window launched from taskbar and desktop acceptance flows."""

from __future__ import annotations

import gi

gi.require_version("Gtk", "4.0")
from gi.repository import Gtk


APPLICATION_ID = "com.anduinos.AcceptancePanelFixture"
WINDOW_TITLE = "AnduinOS Panel Fixture Window"


class PanelFixture(Gtk.Application):
    def __init__(self) -> None:
        super().__init__(application_id=APPLICATION_ID)

    def do_activate(self) -> None:
        if self.get_windows():
            self.get_windows()[0].present()
            return
        window = Gtk.ApplicationWindow(application=self, title=WINDOW_TITLE)
        window.set_default_size(520, 320)
        marker = Gtk.Label(label="PANEL AND DESKTOP FIXTURE LAUNCHED")
        marker.add_css_class("title-1")
        marker.set_accessible_role(Gtk.AccessibleRole.HEADING)
        window.set_child(marker)
        window.present()


if __name__ == "__main__":
    raise SystemExit(PanelFixture().run())
