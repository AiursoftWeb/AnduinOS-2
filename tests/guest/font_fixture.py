#!/usr/bin/python3
"""Deterministic full-screen fixture for real guest font rendering checks."""

from __future__ import annotations

import gi

gi.require_version("Gtk", "4.0")
from gi.repository import Gtk, Gdk


EMOJI_SAMPLE = "🤓 🍔 🔫 👽 ✨"
CHINESE_SAMPLE = "变角次亮采之门"


class FontFixture(Gtk.Application):
    def __init__(self) -> None:
        super().__init__(application_id="com.anduinos.AcceptanceFontFixture")

    def do_activate(self) -> None:
        css = Gtk.CssProvider()
        css.load_from_data(
            b"""
            window { background: #ffffff; }
            label { color: #111111; }
            .gun { font-size: 180px; padding: 12px; }
            .emoji-sample { font-size: 62px; padding: 12px; }
            .chinese-sample { font-size: 72px; padding: 24px; }
            """
        )
        Gtk.StyleContext.add_provider_for_display(
            Gdk.Display.get_default(),
            css,
            Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION,
        )
        window = Gtk.ApplicationWindow(
            application=self,
            title="AnduinOS Font Rendering Fixture",
        )
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        box.set_halign(Gtk.Align.CENTER)
        box.set_valign(Gtk.Align.CENTER)

        gun = Gtk.Label(label="🔫")
        gun.add_css_class("gun")
        emoji = Gtk.Label(label=EMOJI_SAMPLE)
        emoji.add_css_class("emoji-sample")
        chinese = Gtk.Label(label=CHINESE_SAMPLE)
        chinese.add_css_class("chinese-sample")

        box.append(gun)
        box.append(emoji)
        box.append(chinese)
        window.set_child(box)
        window.fullscreen()
        window.present()


if __name__ == "__main__":
    raise SystemExit(FontFixture().run())
