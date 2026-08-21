#!/usr/bin/python3
"""A deterministic GTK4 StatusNotifierItem used by the ISO acceptance gate.

The fixture deliberately speaks the freedesktop/KDE D-Bus protocols directly.
It therefore exercises the same GNOME Shell AppIndicator extension path used by
real applications without adding a test-only AppIndicator binding to the ISO.
"""

from __future__ import annotations

import os

import gi

gi.require_version("Gtk", "4.0")
from gi.repository import Gio, GLib, Gtk


APPLICATION_ID = "com.anduinos.AcceptanceIndicatorFixture"
WINDOW_TITLE = "AnduinOS Indicator Fixture Window"
INDICATOR_TITLE = "AnduinOS Acceptance Indicator"
ITEM_PATH = "/StatusNotifierItem"
MENU_PATH = "/MenuBar"

ITEM_XML = """
<node>
  <interface name="org.kde.StatusNotifierItem">
    <property name="Category" type="s" access="read"/>
    <property name="Id" type="s" access="read"/>
    <property name="Title" type="s" access="read"/>
    <property name="Status" type="s" access="read"/>
    <property name="WindowId" type="i" access="read"/>
    <property name="IconThemePath" type="s" access="read"/>
    <property name="Menu" type="o" access="read"/>
    <property name="ItemIsMenu" type="b" access="read"/>
    <property name="IconName" type="s" access="read"/>
    <property name="IconPixmap" type="a(iiay)" access="read"/>
    <property name="OverlayIconName" type="s" access="read"/>
    <property name="OverlayIconPixmap" type="a(iiay)" access="read"/>
    <property name="AttentionIconName" type="s" access="read"/>
    <property name="AttentionIconPixmap" type="a(iiay)" access="read"/>
    <property name="AttentionMovieName" type="s" access="read"/>
    <method name="ContextMenu"><arg type="i" direction="in"/><arg type="i" direction="in"/></method>
    <method name="Activate"><arg type="i" direction="in"/><arg type="i" direction="in"/></method>
    <method name="ProvideXdgActivationToken"><arg type="s" direction="in"/></method>
    <method name="SecondaryActivate"><arg type="i" direction="in"/><arg type="i" direction="in"/></method>
    <method name="XAyatanaSecondaryActivate"><arg type="u" direction="in"/></method>
    <method name="Scroll"><arg type="i" direction="in"/><arg type="s" direction="in"/></method>
  </interface>
</node>
"""

MENU_XML = """
<node>
  <interface name="com.canonical.dbusmenu">
    <property name="Version" type="u" access="read"/>
    <property name="TextDirection" type="s" access="read"/>
    <property name="Status" type="s" access="read"/>
    <property name="IconThemePath" type="as" access="read"/>
    <method name="GetLayout">
      <arg type="i" direction="in"/><arg type="i" direction="in"/><arg type="as" direction="in"/>
      <arg type="u" direction="out"/><arg type="(ia{sv}av)" direction="out"/>
    </method>
    <method name="GetGroupProperties">
      <arg type="ai" direction="in"/><arg type="as" direction="in"/>
      <arg type="a(ia{sv})" direction="out"/>
    </method>
    <method name="GetProperty">
      <arg type="i" direction="in"/><arg type="s" direction="in"/><arg type="v" direction="out"/>
    </method>
    <method name="Event">
      <arg type="i" direction="in"/><arg type="s" direction="in"/>
      <arg type="v" direction="in"/><arg type="u" direction="in"/>
    </method>
    <method name="EventGroup">
      <arg type="a(isvu)" direction="in"/><arg type="ai" direction="out"/>
    </method>
    <method name="AboutToShow"><arg type="i" direction="in"/><arg type="b" direction="out"/></method>
    <method name="AboutToShowGroup">
      <arg type="ai" direction="in"/><arg type="ai" direction="out"/><arg type="ai" direction="out"/>
    </method>
  </interface>
</node>
"""


class StatusNotifierItem:
    def __init__(self, application: "IndicatorFixture") -> None:
        self.application = application
        # The Shell extension also scans names beginning with
        # org.kde.StatusNotifierItem.  Using that prefix *and* performing the
        # protocol registration can create two watcher entries for one object.
        # A normal application bus name exercises only the normative explicit
        # RegisterStatusNotifierItem path.
        self.service = (
            "com.anduinos.AcceptanceIndicatorFixture.Status" f"{os.getpid()}"
        )
        self.connection: Gio.DBusConnection | None = None
        self.registrations: list[int] = []
        self.registered = False
        self.item_info = Gio.DBusNodeInfo.new_for_xml(ITEM_XML).interfaces[0]
        self.menu_info = Gio.DBusNodeInfo.new_for_xml(MENU_XML).interfaces[0]
        self.owner = Gio.bus_own_name(
            Gio.BusType.SESSION,
            self.service,
            Gio.BusNameOwnerFlags.NONE,
            self._bus_acquired,
            self._name_acquired,
            self._name_lost,
        )

    def _bus_acquired(self, connection: Gio.DBusConnection, _name: str) -> None:
        self.connection = connection
        self.registrations = [
            connection.register_object(
                ITEM_PATH,
                self.item_info,
                self._item_method,
                self._item_property,
                None,
            ),
            connection.register_object(
                MENU_PATH,
                self.menu_info,
                self._menu_method,
                self._menu_property,
                None,
            ),
        ]

    def _name_acquired(self, _connection: Gio.DBusConnection, _name: str) -> None:
        GLib.idle_add(self._register_with_watcher)

    def _name_lost(self, _connection: Gio.DBusConnection | None, name: str) -> None:
        print(f"indicator-name-lost={name}", flush=True)

    def _register_with_watcher(self) -> bool:
        if self.connection is None or self.registered:
            return GLib.SOURCE_REMOVE
        try:
            self.connection.call_sync(
                "org.kde.StatusNotifierWatcher",
                "/StatusNotifierWatcher",
                "org.kde.StatusNotifierWatcher",
                "RegisterStatusNotifierItem",
                GLib.Variant("(s)", (self.service,)),
                None,
                Gio.DBusCallFlags.NONE,
                5_000,
                None,
            )
        except GLib.Error as error:
            print(f"indicator-register-retry={error.message}", flush=True)
            GLib.timeout_add(500, self._register_with_watcher)
            return GLib.SOURCE_REMOVE
        self.registered = True
        print(f"indicator-registered={self.service}", flush=True)
        return GLib.SOURCE_REMOVE

    def _item_property(
        self,
        _connection: Gio.DBusConnection,
        _sender: str,
        _path: str,
        _interface: str,
        name: str,
    ) -> GLib.Variant:
        values = {
            "Category": GLib.Variant("s", "ApplicationStatus"),
            "Id": GLib.Variant("s", "anduinos-acceptance-indicator"),
            "Title": GLib.Variant("s", INDICATOR_TITLE),
            "Status": GLib.Variant("s", "Active"),
            "WindowId": GLib.Variant("i", 0),
            "IconThemePath": GLib.Variant("s", ""),
            "Menu": GLib.Variant("o", MENU_PATH),
            "ItemIsMenu": GLib.Variant("b", False),
            "IconName": GLib.Variant("s", "utilities-terminal-symbolic"),
            "IconPixmap": GLib.Variant("a(iiay)", []),
            "OverlayIconName": GLib.Variant("s", ""),
            "OverlayIconPixmap": GLib.Variant("a(iiay)", []),
            "AttentionIconName": GLib.Variant("s", ""),
            "AttentionIconPixmap": GLib.Variant("a(iiay)", []),
            "AttentionMovieName": GLib.Variant("s", ""),
        }
        return values[name]

    def _item_method(
        self,
        _connection: Gio.DBusConnection,
        _sender: str,
        _path: str,
        _interface: str,
        method: str,
        _parameters: GLib.Variant,
        invocation: Gio.DBusMethodInvocation,
    ) -> None:
        if method in {"Activate", "SecondaryActivate", "XAyatanaSecondaryActivate"}:
            self.application.present_window()
            print(f"indicator-activation={method}", flush=True)
        invocation.return_value(None)

    def _menu_property(
        self,
        _connection: Gio.DBusConnection,
        _sender: str,
        _path: str,
        _interface: str,
        name: str,
    ) -> GLib.Variant:
        values = {
            "Version": GLib.Variant("u", 3),
            "TextDirection": GLib.Variant("s", "ltr"),
            "Status": GLib.Variant("s", "normal"),
            "IconThemePath": GLib.Variant("as", []),
        }
        return values[name]

    def _menu_method(
        self,
        _connection: Gio.DBusConnection,
        _sender: str,
        _path: str,
        _interface: str,
        method: str,
        _parameters: GLib.Variant,
        invocation: Gio.DBusMethodInvocation,
    ) -> None:
        if method == "GetLayout":
            invocation.return_value(
                GLib.Variant("(u(ia{sv}av))", (1, (0, {}, [])))
            )
        elif method == "GetGroupProperties":
            invocation.return_value(GLib.Variant("(a(ia{sv}))", ([],)))
        elif method == "GetProperty":
            invocation.return_value(
                GLib.Variant("(v)", (GLib.Variant("s", ""),))
            )
        elif method == "EventGroup":
            invocation.return_value(GLib.Variant("(ai)", ([],)))
        elif method == "AboutToShow":
            invocation.return_value(GLib.Variant("(b)", (False,)))
        elif method == "AboutToShowGroup":
            invocation.return_value(GLib.Variant("(aiai)", ([], [])))
        else:
            invocation.return_value(None)

    def close(self) -> None:
        if self.connection is not None:
            for registration in self.registrations:
                self.connection.unregister_object(registration)
        Gio.bus_unown_name(self.owner)


class IndicatorFixture(Gtk.Application):
    def __init__(self) -> None:
        super().__init__(application_id=APPLICATION_ID)
        self.window: Gtk.ApplicationWindow | None = None
        self.indicator: StatusNotifierItem | None = None

    def do_activate(self) -> None:
        if self.indicator is None:
            self.indicator = StatusNotifierItem(self)
            self.hold()
        self.present_window()

    def present_window(self) -> None:
        if self.window is None:
            self.window = Gtk.ApplicationWindow(application=self, title=WINDOW_TITLE)
            self.window.set_default_size(520, 320)
            self.window.connect("close-request", self._hide_window)
            marker = Gtk.Label(label="APPINDICATOR ROUNDTRIP FIXTURE")
            marker.add_css_class("title-1")
            marker.set_accessible_role(Gtk.AccessibleRole.HEADING)
            self.window.set_child(marker)
        self.window.present()

    def _hide_window(self, window: Gtk.ApplicationWindow) -> bool:
        window.set_visible(False)
        print("indicator-window=hidden", flush=True)
        return True

    def do_shutdown(self) -> None:
        if self.indicator is not None:
            self.indicator.close()
        super().do_shutdown()


if __name__ == "__main__":
    raise SystemExit(IndicatorFixture().run())
