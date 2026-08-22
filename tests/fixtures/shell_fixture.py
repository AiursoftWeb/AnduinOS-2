#!/usr/bin/python3
"""Two real GTK windows used by Shell, taskbar, and shortcut acceptance."""

from __future__ import annotations

import gi

gi.require_version("Gtk", "4.0")
from gi.repository import Gtk


APPLICATION_ID = "com.anduinos.AcceptanceShellFixture"
ALPHA_TITLE = "AnduinOS Shortcut Window Alpha"
BETA_TITLE = "AnduinOS Shortcut Window Beta"


class ShellFixture(Gtk.Application):
    def __init__(self) -> None:
        super().__init__(application_id=APPLICATION_ID)

    def _window(self, title: str, marker: str) -> Gtk.ApplicationWindow:
        window = Gtk.ApplicationWindow(application=self, title=title)
        window.set_default_size(520, 320)
        label = Gtk.Label(label=marker)
        label.add_css_class("title-1")
        label.set_accessible_role(Gtk.AccessibleRole.HEADING)
        window.set_child(label)
        # Mutter may ignore explicit placement on Wayland; distinct titles and
        # two real top-levels are the behavioral oracle, not their coordinates.
        window.present()
        return window

    def do_activate(self) -> None:
        if self.get_windows():
            self.get_windows()[-1].present()
            return
        self._window(ALPHA_TITLE, "SHELL FIXTURE ALPHA")
        beta = self._window(BETA_TITLE, "SHELL FIXTURE BETA")
        beta.present()


if __name__ == "__main__":
    raise SystemExit(ShellFixture().run())
