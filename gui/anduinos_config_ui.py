#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
AnduinOS 构建配置器 — GTK3 图形界面 (PyGObject)

功能：
  * 图形化编辑 args.sh（另存为、保存并开始构建）
  * 「软件包管理」页：勾选安装哪些包 / 不安装哪些包，并可添加额外包
  * 「自定义脚本」页：chroot 内 hook、打包 ISO 前宿主机 hook
  * 构建日志窗口（实时输出、失败后可从中断处继续）
  * i18n：默认英文，中文以明文 JSON 存储，顶部下拉框可随时切换语言；
    新增 locales/*.json 会被自动发现并加入下拉框。

用法：
    python3 anduinos_config_ui.py [--args /path/to/args.sh]
"""

from __future__ import annotations

import argparse
import os
import re
import signal
import subprocess
import sys
import threading

import gi

gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
from gi.repository import Gdk, GLib, GObject, Gtk, Pango  # noqa: E402

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from config_editor import (  # noqa: E402
    ArgsConfig,
    ConfigError,
    cache_directory,
    cache_stats,
    human_size,
)
from config_schema import (  # noqa: E402
    ALL_KEYS,
    SECTIONS,
    bool_from_value,
    bool_to_value,
)
import packages_config  # noqa: E402
from i18n import I18n  # noqa: E402

APP_TITLE = "AnduinOS Build Configurator"
APP_VERSION = "2.0.0"


def default_args_path() -> str:
    here = os.path.dirname(os.path.abspath(__file__))
    for path in (
        os.path.join(os.getcwd(), "args.sh"),
        os.path.join(here, os.pardir, "args.sh"),
        os.path.join(here, "args.sh"),
    ):
        if os.path.isfile(path):
            return os.path.abspath(path)
    return os.path.abspath(os.path.join(os.getcwd(), "args.sh"))


def add_dim_label(text: str) -> Gtk.Label:
    label = Gtk.Label(label=text, xalign=0.0, wrap=True, max_width_chars=88)
    label.set_line_wrap(True)
    label.get_style_context().add_class("dim-label")
    return label


# ===========================================================================
# 构建日志窗口
# ===========================================================================
class BuildLogWindow(Gtk.Window):
    """显示构建过程的实时输出，并提供失败后续跑入口。"""

    def __init__(self, root_dir: str, command: list[str], i18n: I18n,
                 title: str | None = None):
        self.i18n = i18n
        Gtk.Window.__init__(self, title=title or self.tr("log.title"))
        self.set_default_size(820, 560)
        self.set_position(Gtk.WindowPosition.CENTER)
        self.root_dir = root_dir
        self.command = command
        self.proc: subprocess.Popen | None = None
        self.finished_ok: bool | None = None
        self._bindings: list[tuple] = []
        self._status_key = "log.starting"
        self._status_kwargs: dict = {}

        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8, margin=10)
        self.add(box)

        self.status_label = Gtk.Label(xalign=0.0)
        self._bind(self.status_label.set_label, "log.starting")
        box.pack_start(self.status_label, False, False, 0)

        scrolled = Gtk.ScrolledWindow()
        scrolled.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
        scrolled.set_shadow_type(Gtk.ShadowType.IN)
        self.textview = Gtk.TextView()
        self.textview.set_editable(False)
        self.textview.set_monospace(True)
        self.buffer = self.textview.get_buffer()
        self.end_mark = self.buffer.create_mark(None, self.buffer.get_end_iter(), False)
        scrolled.add(self.textview)
        box.pack_start(scrolled, True, True, 0)

        btn_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        btn_box.set_halign(Gtk.Align.END)
        box.pack_start(btn_box, False, False, 0)

        self.resume_btn = Gtk.Button()
        self._bind(self.resume_btn.set_label, "log.btn.resume")
        self.resume_btn.connect("clicked", self.on_resume)
        btn_box.pack_start(self.resume_btn, False, False, 0)

        self.stop_btn = Gtk.Button()
        self._bind(self.stop_btn.set_label, "log.btn.stop")
        self.stop_btn.connect("clicked", self.on_stop)
        btn_box.pack_start(self.stop_btn, False, False, 0)

        self.close_btn = Gtk.Button()
        self._bind(self.close_btn.set_label, "log.btn.close")
        self.close_btn.connect("clicked", lambda _w: self.destroy())
        btn_box.pack_start(self.close_btn, False, False, 0)

        self.connect("delete-event", self.on_delete)
        self.show_all()
        self.start(command)

    # ---- i18n 辅助 ----
    def tr(self, key: str, **kwargs) -> str:
        return self.i18n.tr(key, **kwargs)

    def _bind(self, setter, key: str, **kwargs) -> None:
        self._bindings.append((setter, key, dict(kwargs)))
        setter(self.tr(key, **kwargs))

    def set_status(self, key: str, **kwargs) -> None:
        self._status_key = key
        self._status_kwargs = dict(kwargs)
        self.status_label.set_label(self.tr(key, **kwargs))

    def apply_language(self) -> None:
        for setter, key, kwargs in self._bindings:
            setter(self.tr(key, **kwargs))
        self.set_status(self._status_key, **self._status_kwargs)

    # ------------------------------------------------------------------
    def start(self, command: list[str]) -> None:
        self.command = command
        self.finished_ok = None
        self.resume_btn.set_sensitive(False)
        self.set_status("log.executing", command=" ".join(command))
        self._append("\n>>> " + " ".join(command) + "\n")
        try:
            self.proc = subprocess.Popen(
                command,
                cwd=self.root_dir,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
                preexec_fn=os.setsid,
            )
        except OSError as exc:
            self._append(self.tr("log.start_failed", error=exc) + "\n")
            self.set_status("log.status_start_failed")
            return
        threading.Thread(target=self._reader, daemon=True).start()

    def _reader(self) -> None:
        assert self.proc is not None
        assert self.proc.stdout is not None
        for line in self.proc.stdout:
            GLib.idle_add(self._append, line)
        returncode = self.proc.wait()
        GLib.idle_add(self._on_finished, returncode)

    def _append(self, text: str) -> None:
        self.buffer.insert(self.buffer.get_end_iter(), text)
        self.textview.scroll_to_mark(self.end_mark, 0.0, False, 0.0, 1.0)

    def _on_finished(self, returncode: int) -> None:
        self.finished_ok = returncode == 0
        if returncode == 0:
            self.set_status("log.success")
            self._append("\n>>> " + self.tr("log.success_append") + "\n")
        else:
            self.set_status("log.failed", code=returncode)
            self._append("\n>>> " + self.tr("log.failed_append") + "\n")
            self.resume_btn.set_sensitive(True)

    def on_resume(self, _widget: Gtk.Widget) -> None:
        if self.proc and self.proc.poll() is None:
            return
        self._append("\n>>> " + self.tr("log.resume_append") + "\n")
        resume_cmd = [os.path.join(self.root_dir, "build.sh"), "--resume"]
        self.start(resume_cmd)

    def on_stop(self, _widget: Gtk.Widget) -> None:
        if self.proc and self.proc.poll() is None:
            try:
                os.killpg(os.getpgid(self.proc.pid), signal.SIGTERM)
            except OSError:
                pass
            self._append("\n>>> " + self.tr("log.stop_append") + "\n")

    def on_delete(self, _widget: Gtk.Widget, _event: Gdk.Event) -> bool:
        if self.proc and self.proc.poll() is None:
            dialog = Gtk.MessageDialog(
                parent=self,
                flags=Gtk.DialogFlags.MODAL,
                type=Gtk.MessageType.QUESTION,
                buttons=Gtk.ButtonsType.YES_NO,
                message_format=self.tr("confirm.close_running"),
            )
            response = dialog.run()
            dialog.destroy()
            if response != Gtk.ResponseType.YES:
                return True
            self.on_stop(None)
        self.destroy()
        return True


# ===========================================================================
# 主窗口
# ===========================================================================
class ConfigWindow(Gtk.Window):
    def __init__(self, args_path: str, i18n: I18n | None = None):
        self.i18n = i18n or I18n()
        self._bindings: list[tuple] = []
        Gtk.Window.__init__(self, title="%s v%s" % (self.tr("app.title"), APP_VERSION))
        self.set_default_size(980, 760)
        self.set_position(Gtk.WindowPosition.CENTER)

        self.args_path = os.path.abspath(args_path)
        self.cfg = ArgsConfig(self.args_path)
        self.widgets: dict[str, Gtk.Widget] = {}
        self.bool_vars: dict[str, Gtk.CheckButton] = {}
        self.dirty = False
        self.cache_dir = cache_directory(self.args_path)
        self.packages_path = os.path.join(self.repo_root, "packages.json")
        self.hooks_path = os.path.join(self.repo_root, "custom_hooks.sh")
        self.pre_iso_path = os.path.join(self.repo_root, "custom_pre_iso.sh")
        self.package_store: dict[str, Gtk.ListStore] = {}
        self.extra_store: dict[str, Gtk.ListStore] = {}
        self.log_window: BuildLogWindow | None = None

        self._build_ui()
        self.reload_config(show_message=False)
        self.connect("delete-event", self.on_delete)
        self.show_all()

    # ---- i18n 辅助 ----
    def tr(self, key: str, **kwargs) -> str:
        return self.i18n.tr(key, **kwargs)

    def _bind(self, setter, key: str, **kwargs) -> None:
        """登记一个可随语言切换而刷新的文本控件。"""
        self._bindings.append((setter, key, dict(kwargs)))
        setter(self.tr(key, **kwargs))

    def _apply_language(self) -> None:
        for setter, key, kwargs in self._bindings:
            setter(self.tr(key, **kwargs))
        self.update_cache_info()
        if self.log_window is not None:
            self.log_window.apply_language()

    def on_language_changed(self, combo: Gtk.ComboBoxText) -> None:
        idx = combo.get_active()
        if idx < 0 or idx >= len(self.lang_codes):
            return
        code = self.lang_codes[idx]
        if code == self.i18n.current:
            return
        self.i18n.set_language(code)
        self._apply_language()
        self.set_status(self.tr("status.language_set", name=self.i18n.current_name))

    # ------------------------------------------------------------------
    @property
    def repo_root(self) -> str:
        return os.path.dirname(self.args_path)

    # ------------------------------------------------------------------
    def _build_ui(self) -> None:
        outer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        self.add(outer)

        # 顶部标题 + 语言下拉框
        header = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12, margin=12)
        title = Gtk.Label(xalign=0.0)
        title.modify_font(Pango.FontDescription("Sans 18 bold"))
        self._bind(title.set_label, "header.title")
        header.pack_start(title, False, False, 0)
        subtitle = add_dim_label("")
        self._bind(subtitle.set_label, "header.subtitle")
        header.pack_start(subtitle, False, False, 0)

        lang_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        lang_label = Gtk.Label()
        self._bind(lang_label.set_label, "language.label")
        lang_box.pack_start(lang_label, False, False, 0)
        self.lang_combo = Gtk.ComboBoxText()
        self.lang_codes: list[str] = []
        for lang in self.i18n.languages:
            self.lang_combo.append_text(lang["native"])
            self.lang_codes.append(lang["code"])
        try:
            active = self.lang_codes.index(self.i18n.current)
        except ValueError:
            active = 0
        self.lang_combo.set_active(active)
        self.lang_combo.connect("changed", self.on_language_changed)
        lang_box.pack_start(self.lang_combo, False, False, 0)
        header.pack_end(lang_box, False, False, 0)
        outer.pack_start(header, False, False, 0)

        # 配置文件选择
        frame = Gtk.Frame(margin_left=12, margin_right=12)
        self._bind(frame.set_label, "frame.config_file")
        fb = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8, margin=10)
        frame.add(fb)
        self.path_entry = Gtk.Entry()
        self.path_entry.set_text(self.args_path)
        self.path_entry.set_hexpand(True)
        fb.pack_start(self.path_entry, True, True, 0)
        browse_btn = Gtk.Button()
        self._bind(browse_btn.set_label, "btn.browse")
        browse_btn.connect("clicked", self.on_browse)
        fb.pack_start(browse_btn, False, False, 0)
        reload_btn = Gtk.Button()
        self._bind(reload_btn.set_label, "btn.reload")
        reload_btn.connect("clicked", lambda _w: self.reload_config())
        fb.pack_start(reload_btn, False, False, 0)
        outer.pack_start(frame, False, False, 0)

        # 标签页
        self.notebook = Gtk.Notebook()
        self.notebook.set_margin_left(12)
        self.notebook.set_margin_right(12)
        self.notebook.set_margin_top(10)
        outer.pack_start(self.notebook, True, True, 0)

        for section in SECTIONS:
            page = self._build_section(section)
            tab = Gtk.Label()
            self._bind(tab.set_label, section.get("label_key", section["label"]))
            self.notebook.append_page(page, tab)

        pkg_tab = Gtk.Label()
        self._bind(pkg_tab.set_label, "tab.packages")
        self.notebook.append_page(self._build_packages_page(), pkg_tab)

        hooks_tab = Gtk.Label()
        self._bind(hooks_tab.set_label, "tab.hooks")
        self.notebook.append_page(self._build_hooks_page(), hooks_tab)

        # 底部按钮
        actions = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8, margin=12)
        quit_btn = Gtk.Button()
        self._bind(quit_btn.set_label, "btn.quit")
        quit_btn.connect("clicked", lambda _w: self.destroy())
        actions.pack_start(quit_btn, False, False, 0)

        cmd_btn = Gtk.Button()
        self._bind(cmd_btn.set_label, "btn.view_command")
        cmd_btn.connect("clicked", self.show_build_command)
        actions.pack_start(cmd_btn, False, False, 0)

        actions.pack_start(Gtk.Label(), True, True, 0)  # 弹簧

        save_btn = Gtk.Button()
        self._bind(save_btn.set_label, "btn.save_config")
        save_btn.connect("clicked", lambda _w: self.save_config())
        actions.pack_start(save_btn, False, False, 0)

        saveas_btn = Gtk.Button()
        self._bind(saveas_btn.set_label, "btn.save_as")
        saveas_btn.connect("clicked", self.on_save_as)
        actions.pack_start(saveas_btn, False, False, 0)

        build_btn = Gtk.Button()
        self._bind(build_btn.set_label, "btn.save_build")
        build_btn.get_style_context().add_class("suggested-action")
        build_btn.connect("clicked", self.on_save_and_build)
        actions.pack_start(build_btn, False, False, 0)
        outer.pack_start(actions, False, False, 0)

        # 状态栏
        self.statusbar = Gtk.Statusbar()
        self.status_context = self.statusbar.get_context_id("main")
        outer.pack_start(self.statusbar, False, False, 0)

        # 窗口标题随语言刷新
        self._bind(
            lambda text: self.set_title("%s v%s" % (text, APP_VERSION)),
            "app.title",
        )

    # ------------------------------------------------------------------
    def _build_section(self, section: dict) -> Gtk.Widget:
        grid = Gtk.Grid(row_spacing=6, column_spacing=14, margin=16)
        row = 0
        for item in section["items"]:
            key = item["key"]
            label = Gtk.Label(xalign=1.0)
            item_key = item.get("label_key", item["label"])
            self._bind(
                lambda text, w=label: w.set_label(text + self.tr("misc.colon")),
                item_key,
            )
            grid.attach(label, 0, row, 1, 1)

            kind = item["type"]
            if kind == "combo":
                widget = Gtk.ComboBoxText()
                for option in item["options"]:
                    widget.append_text(option)
                widget.connect("changed", lambda _w: self._mark_dirty())
            elif kind == "text":
                widget = Gtk.Entry()
                widget.set_width_chars(64)
                widget.connect("changed", lambda _w: self._mark_dirty())
            elif kind == "bool":
                widget = Gtk.CheckButton()
                self._bind(widget.set_label, "bool.enable")
                widget.connect("toggled", lambda _w: self._mark_dirty())
                self.bool_vars[key] = widget
                if key == "KEEP_DOWNLOADED_DEBS":
                    widget.connect("toggled", self._on_keep_debs_toggled)
            elif kind == "textblock":
                scrolled = Gtk.ScrolledWindow()
                scrolled.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
                scrolled.set_min_content_height(220)
                scrolled.set_shadow_type(Gtk.ShadowType.IN)
                textview = Gtk.TextView()
                textview.set_monospace(True)
                scrolled.add(textview)
                widget = scrolled
                textview.get_buffer().connect("changed", lambda _b: self._mark_dirty())

            grid.attach(widget, 1, row, 1, 1)
            self.widgets[key] = widget
            help_label = add_dim_label("")
            self._bind(help_label.set_label, item.get("help_key", item["help"]))
            grid.attach(help_label, 0, row + 1, 2, 1)
            row += 2

        if section["id"] == "cache":
            panel = Gtk.Frame(margin_top=14)
            self._bind(panel.set_label, "panel.cache_status")
            pb = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8, margin=12)
            panel.add(pb)
            self.cache_path_label = Gtk.Label(label="", xalign=0.0)
            self.cache_count_label = Gtk.Label(label="", xalign=0.0)
            self.cache_size_label = Gtk.Label(label="", xalign=0.0)
            pb.pack_start(self.cache_path_label, False, False, 0)
            pb.pack_start(self.cache_count_label, False, False, 0)
            pb.pack_start(self.cache_size_label, False, False, 0)
            btn_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
            for key, handler in (
                ("btn.refresh", lambda _w: self.update_cache_info()),
                ("btn.open_dir", lambda _w: self.open_cache_directory()),
                ("btn.clear_cache", lambda _w: self.clear_cache()),
            ):
                btn = Gtk.Button()
                self._bind(btn.set_label, key)
                btn.connect("clicked", handler)
                btn_box.pack_start(btn, False, False, 0)
            pb.pack_start(btn_box, False, False, 0)
            grid.attach(panel, 0, row, 2, 1)

        return grid

    def _on_keep_debs_toggled(self, widget: Gtk.CheckButton) -> None:
        state = self.tr("misc.on") if widget.get_active() else self.tr("misc.off")
        self.set_status(self.tr("status.deb_toggle", state=state))

    # ------------------------------------------------------------------
    def _build_packages_page(self) -> Gtk.Widget:
        outer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8, margin=12)
        intro = add_dim_label("")
        self._bind(intro.set_label, "pkg.intro")
        outer.pack_start(intro, False, False, 0)

        inner = Gtk.Notebook()
        outer.pack_start(inner, True, True, 0)

        for group, title_key in (("core", "group.core"), ("desktop", "group.desktop")):
            box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8, margin=8)
            store = Gtk.ListStore(GObject.TYPE_BOOLEAN, GObject.TYPE_STRING)
            self.package_store[group] = store
            tree = Gtk.TreeView(model=store)
            renderer_toggle = Gtk.CellRendererToggle()
            renderer_toggle.connect("toggled", self.on_package_toggled, store)
            col_toggle = Gtk.TreeViewColumn("", renderer_toggle, active=0)
            self._bind(col_toggle.set_title, "pkg.col.install")
            tree.append_column(col_toggle)
            col_name = Gtk.TreeViewColumn("", Gtk.CellRendererText(), text=1)
            self._bind(col_name.set_title, "pkg.col.name")
            tree.append_column(col_name)
            scrolled = Gtk.ScrolledWindow()
            scrolled.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
            scrolled.set_min_content_height(280)
            scrolled.add(tree)
            box.pack_start(scrolled, True, True, 0)

            ctrl = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
            for key, handler in (
                ("btn.select_all", lambda _w, g=group, s=store: self._set_all(g, s, True)),
                ("btn.select_none", lambda _w, g=group, s=store: self._set_all(g, s, False)),
                ("btn.restore_default", lambda _w, g=group: self._restore_default(g)),
            ):
                btn = Gtk.Button()
                self._bind(btn.set_label, key)
                btn.connect("clicked", handler)
                ctrl.pack_start(btn, False, False, 0)
            box.pack_start(ctrl, False, False, 0)

            extra_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
            entry = Gtk.Entry()
            self._bind(
                lambda text, e=entry: e.set_placeholder_text(text),
                "entry.extra_placeholder",
            )
            extra_box.pack_start(entry, True, True, 0)
            add_btn = Gtk.Button()
            self._bind(add_btn.set_label, "btn.add_extra")
            add_btn.connect("clicked", self._make_add_extra(group, entry))
            extra_box.pack_start(add_btn, False, False, 0)
            box.pack_start(extra_box, False, False, 0)

            extra_store = Gtk.ListStore(GObject.TYPE_STRING)
            self.extra_store[group] = extra_store
            extra_tree = Gtk.TreeView(model=extra_store)
            extra_col = Gtk.TreeViewColumn("", Gtk.CellRendererText(), text=0)
            self._bind(extra_col.set_title, "pkg.col.extra")
            extra_tree.append_column(extra_col)
            extra_scrolled = Gtk.ScrolledWindow()
            extra_scrolled.set_min_content_height(90)
            extra_scrolled.add(extra_tree)
            box.pack_start(extra_scrolled, False, False, 0)
            del_btn = Gtk.Button()
            self._bind(del_btn.set_label, "btn.del_extra")
            del_btn.connect("clicked", self._make_del_extra(group, extra_tree))
            box.pack_start(del_btn, False, False, 0)

            tab = Gtk.Label()
            self._bind(tab.set_label, title_key)
            inner.append_page(box, tab)

        return outer

    def _build_hooks_page(self) -> Gtk.Widget:
        outer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10, margin=12)
        intro = add_dim_label("")
        self._bind(intro.set_label, "hooks.intro")
        outer.pack_start(intro, False, False, 0)

        self.hooks_view, hooks_sw = self._make_script_editor("hooks.frame.chroot", 240)
        self.pre_iso_view, pre_iso_sw = self._make_script_editor("hooks.frame.pre_iso", 200)
        outer.pack_start(hooks_sw, True, True, 0)
        outer.pack_start(pre_iso_sw, True, True, 0)
        return outer

    def _make_script_editor(self, title_key: str, height: int):
        frame = Gtk.Frame()
        self._bind(frame.set_label, title_key)
        scrolled = Gtk.ScrolledWindow()
        scrolled.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
        scrolled.set_min_content_height(height)
        scrolled.set_shadow_type(Gtk.ShadowType.IN)
        textview = Gtk.TextView()
        textview.set_monospace(True)
        scrolled.add(textview)
        frame.add(scrolled)
        return textview, frame

    # ------------------------------------------------------------------
    # 配置加载 / 收集
    # ------------------------------------------------------------------
    def reload_config(self, show_message: bool = True) -> None:
        try:
            self.cfg = ArgsConfig(self.args_path).load()
            values = self.cfg.evaluate(ALL_KEYS)
        except ConfigError as exc:
            self._error(str(exc))
            return

        upgraded = False
        for key in ALL_KEYS:
            widget = self.widgets[key]
            value = values.get(key, "")
            if isinstance(widget, Gtk.ComboBoxText):
                texts = [row[0] for row in widget.get_model()]
                if value in texts:
                    widget.set_active(texts.index(value))
                else:
                    widget.set_active(0)
            elif isinstance(widget, Gtk.Entry):
                widget.set_text(value)
            elif isinstance(widget, Gtk.CheckButton):
                if key == "KEEP_DOWNLOADED_DEBS" and key not in self.cfg.present:
                    widget.set_active(True)
                    upgraded = True
                else:
                    widget.set_active(bool_from_value(value))
            elif isinstance(widget, Gtk.ScrolledWindow):
                textview = widget.get_child()
                buf = textview.get_buffer()
                buf.set_text(value)

        # 软件包
        packages = packages_config.load(self.packages_path)
        for group in ("core", "desktop"):
            store = self.package_store[group]
            store.clear()
            for name, enabled in packages[group].items():
                store.append([bool(enabled), name])
            extra_store = self.extra_store[group]
            extra_store.clear()
            for name in packages.get("extra_%s" % group, []):
                extra_store.append([name])

        # 自定义脚本
        for path, view in ((self.hooks_path, self.hooks_view), (self.pre_iso_path, self.pre_iso_view)):
            text = ""
            if os.path.isfile(path):
                try:
                    with open(path, "r", encoding="utf-8") as fh:
                        text = fh.read()
                except OSError:
                    text = ""
            buf = view.get_buffer()
            buf.set_text(text)

        self.cache_dir = cache_directory(self.args_path)
        self.cache_path_label.set_label(self.tr("cache.path", path=self.cache_dir))
        self.update_cache_info()

        self.dirty = upgraded
        if upgraded:
            self.set_status(self.tr("status.legacy_upgrade"))
        elif show_message:
            self.set_status(self.tr("status.reloaded", name=os.path.basename(self.args_path)))

    def _collect_values(self) -> dict[str, str]:
        values: dict[str, str] = {}
        for key in ALL_KEYS:
            widget = self.widgets[key]
            if isinstance(widget, Gtk.ComboBoxText):
                values[key] = widget.get_active_text() or ""
            elif isinstance(widget, Gtk.Entry):
                values[key] = widget.get_text().strip()
            elif isinstance(widget, Gtk.CheckButton):
                values[key] = bool_to_value(widget.get_active())
            elif isinstance(widget, Gtk.ScrolledWindow):
                buf = widget.get_child().get_buffer()
                values[key] = buf.get_text(buf.get_start_iter(), buf.get_end_iter(), False).strip("\n")
        return values

    def _collect_packages(self) -> dict:
        data = packages_config.default_config()
        for group in ("core", "desktop"):
            for row in self.package_store[group]:
                data[group][row[1]] = bool(row[0])
            data["extra_%s" % group] = [row[0] for row in self.extra_store[group]]
        return data

    def _validate(self, values: dict[str, str]) -> bool:
        if not values.get("TARGET_NAME") or not re.fullmatch(r"[a-z0-9_-]+", values["TARGET_NAME"]):
            self._error(self.tr("err.target_name"))
            return False
        if not values.get("TARGET_BUSINESS_NAME"):
            self._error(self.tr("err.business_name"))
            return False
        if not values.get("APT_SOURCE"):
            self._error(self.tr("err.apt_source"))
            return False
        count = len([line for line in values.get("SUPPORTED_LIVE_REGIONS", "").splitlines() if line.strip()])
        if count and count != 29:
            dialog = Gtk.MessageDialog(
                parent=self,
                flags=Gtk.DialogFlags.MODAL,
                type=Gtk.MessageType.QUESTION,
                buttons=Gtk.ButtonsType.YES_NO,
                message_format=self.tr("confirm.regions", count=count),
            )
            response = dialog.run()
            dialog.destroy()
            return response == Gtk.ResponseType.YES
        return True

    def _write_all(self, target_args: str, backup: bool) -> bool:
        values = self._collect_values()
        if not self._validate(values):
            return False
        cfg = ArgsConfig(target_args)
        cfg.load().save(values, backup=backup)
        packages_config.save(self.packages_path, self._collect_packages())
        for path, view in ((self.hooks_path, self.hooks_view), (self.pre_iso_path, self.pre_iso_view)):
            buf = view.get_buffer()
            text = buf.get_text(buf.get_start_iter(), buf.get_end_iter(), False)
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(text)
        self.args_path = target_args
        self.cfg = ArgsConfig(target_args).load()
        self.dirty = False
        return True

    def save_config(self) -> None:
        try:
            if not self._write_all(self.args_path, backup=True):
                return
        except (ConfigError, OSError) as exc:
            self._error(self.tr("msg.save_failed", error=exc))
            return
        self.path_entry.set_text(self.args_path)
        self.update_cache_info()
        self.set_status(self.tr("msg.saved", name=os.path.basename(self.args_path)))

    def on_save_as(self, _widget: Gtk.Widget) -> None:
        dialog = Gtk.FileChooserDialog(
            title=self.tr("dialog.save_as.title"),
            parent=self,
            action=Gtk.FileChooserAction.SAVE,
            buttons=(
                self.tr("btn.cancel"), Gtk.ResponseType.CANCEL,
                self.tr("btn.save_dialog"), Gtk.ResponseType.ACCEPT,
            ),
        )
        dialog.set_current_folder(self.repo_root)
        dialog.set_current_name("args.sh")
        response = dialog.run()
        if response != Gtk.ResponseType.ACCEPT:
            dialog.destroy()
            return
        filename = dialog.get_filename()
        dialog.destroy()
        if not filename:
            return
        # 另存为等同于切换到新工程目录：先把附属文件路径指向新目录，
        # 再一次性写入，保证 packages.json / hooks 与新的 args.sh 放在一起。
        self.args_path = filename
        self.packages_path = os.path.join(self.repo_root, "packages.json")
        self.hooks_path = os.path.join(self.repo_root, "custom_hooks.sh")
        self.pre_iso_path = os.path.join(self.repo_root, "custom_pre_iso.sh")
        try:
            if not self._write_all(filename, backup=False):
                return
        except (ConfigError, OSError) as exc:
            self._error(self.tr("msg.save_as_failed", error=exc))
            return
        self.path_entry.set_text(filename)
        self.reload_config(show_message=False)
        self.set_status(self.tr("msg.saved_as", path=filename))

    def on_save_and_build(self, _widget: Gtk.Widget) -> None:
        try:
            if not self._write_all(self.args_path, backup=True):
                return
        except (ConfigError, OSError) as exc:
            self._error(self.tr("msg.save_failed", error=exc))
            return
        self.path_entry.set_text(self.args_path)

        dialog = Gtk.Dialog(title=self.tr("dialog.build.title"), parent=self,
                            flags=Gtk.DialogFlags.MODAL)
        dialog.add_button(self.tr("btn.cancel"), Gtk.ResponseType.CANCEL)
        dialog.add_button(self.tr("btn.resume"), Gtk.ResponseType.APPLY)
        dialog.add_button(self.tr("btn.fresh"), Gtk.ResponseType.ACCEPT)
        label = Gtk.Label(label=self.tr("dialog.build.text"), margin=16)
        dialog.get_content_area().pack_start(label, False, False, 0)
        dialog.show_all()
        response = dialog.run()
        dialog.destroy()
        if response == Gtk.ResponseType.ACCEPT:
            command = ["make"]
        elif response == Gtk.ResponseType.APPLY:
            command = [os.path.join(self.repo_root, "build.sh"), "--resume"]
        else:
            self.set_status(self.tr("msg.build_cancelled"))
            return

        self.log_window = BuildLogWindow(
            self.repo_root, command, self.i18n, title=self.tr("log.title")
        )
        self.set_status(self.tr("msg.build_started", command=" ".join(command)))

    # ------------------------------------------------------------------
    # 软件包页回调
    # ------------------------------------------------------------------
    def on_package_toggled(self, _renderer, path, store: Gtk.ListStore) -> None:
        row = store[path]
        row[0] = not row[0]
        self._mark_dirty()

    def _set_all(self, group: str, store: Gtk.ListStore, enabled: bool) -> None:
        for row in store:
            row[0] = enabled
        self._mark_dirty()

    def _restore_default(self, group: str) -> None:
        defaults = packages_config.default_config()[group]
        store = self.package_store[group]
        for row in store:
            row[0] = defaults.get(row[1], True)
        self._mark_dirty()

    def _make_add_extra(self, group: str, entry: Gtk.Entry):
        def handler(_widget: Gtk.Widget) -> None:
            name = entry.get_text().strip()
            if not name:
                return
            store = self.extra_store[group]
            if any(row[0] == name for row in store):
                self._error(self.tr("err.duplicate_extra", name=name))
                return
            store.append([name])
            entry.set_text("")
            self._mark_dirty()
        return handler

    def _make_del_extra(self, group: str, tree: Gtk.TreeView):
        def handler(_widget: Gtk.Widget) -> None:
            model, paths = tree.get_selection().get_selected_rows()
            store = self.extra_store[group]
            for path in reversed(paths):
                del store[path]
            self._mark_dirty()
        return handler

    # ------------------------------------------------------------------
    # 缓存管理
    # ------------------------------------------------------------------
    def update_cache_info(self) -> None:
        count, size = cache_stats(self.cache_dir)
        self.cache_count_label.set_label(self.tr("cache.count", count=count))
        self.cache_size_label.set_label(self.tr("cache.size", size=human_size(size)))
        self.cache_path_label.set_label(self.tr("cache.path", path=self.cache_dir))

    def open_cache_directory(self) -> None:
        if not os.path.isdir(self.cache_dir):
            os.makedirs(self.cache_dir, exist_ok=True)
        try:
            subprocess.Popen(["xdg-open", self.cache_dir])
        except OSError:
            pass

    def clear_cache(self) -> None:
        count, size = cache_stats(self.cache_dir)
        if count == 0:
            self._info(self.tr("msg.cache_empty"))
            return
        dialog = Gtk.MessageDialog(
            parent=self,
            flags=Gtk.DialogFlags.MODAL,
            type=Gtk.MessageType.QUESTION,
            buttons=Gtk.ButtonsType.YES_NO,
            message_format=self.tr("confirm.clear_cache", count=count, size=human_size(size)),
        )
        response = dialog.run()
        dialog.destroy()
        if response != Gtk.ResponseType.YES:
            return
        result = subprocess.run(["sudo", "rm", "-rf", self.cache_dir], check=False)
        if result.returncode == 0:
            os.makedirs(os.path.join(self.cache_dir, "partial"), exist_ok=True)
        else:
            self._error(self.tr("msg.clear_failed", path=self.cache_dir))
        self.update_cache_info()

    # ------------------------------------------------------------------
    # 通用
    # ------------------------------------------------------------------
    def on_browse(self, _widget: Gtk.Widget) -> None:
        dialog = Gtk.FileChooserDialog(
            title=self.tr("dialog.open.title"),
            parent=self,
            action=Gtk.FileChooserAction.OPEN,
            buttons=(
                self.tr("btn.cancel"), Gtk.ResponseType.CANCEL,
                self.tr("btn.open"), Gtk.ResponseType.ACCEPT,
            ),
        )
        dialog.set_current_folder(self.repo_root)
        response = dialog.run()
        if response != Gtk.ResponseType.ACCEPT:
            dialog.destroy()
            return
        filename = dialog.get_filename()
        dialog.destroy()
        if not filename:
            return
        if self.dirty and not self._confirm(self.tr("msg.unsaved_open")):
            return
        self.args_path = filename
        self.path_entry.set_text(filename)
        self.packages_path = os.path.join(self.repo_root, "packages.json")
        self.hooks_path = os.path.join(self.repo_root, "custom_hooks.sh")
        self.pre_iso_path = os.path.join(self.repo_root, "custom_pre_iso.sh")
        self.reload_config(show_message=False)

    def show_build_command(self, _widget: Gtk.Widget) -> None:
        directory = self.repo_root
        text = self.tr("buildcmd.text", dir=directory)
        self._info(text, title=self.tr("btn.view_command"))

    def _mark_dirty(self) -> None:
        self.dirty = True

    def set_status(self, text: str) -> None:
        self.statusbar.pop(self.status_context)
        self.statusbar.push(self.status_context, text)

    def _error(self, message: str) -> None:
        dialog = Gtk.MessageDialog(
            parent=self,
            flags=Gtk.DialogFlags.MODAL,
            type=Gtk.MessageType.ERROR,
            buttons=Gtk.ButtonsType.OK,
            message_format=message,
        )
        dialog.run()
        dialog.destroy()

    def _info(self, message: str, title: str | None = None) -> None:
        dialog = Gtk.MessageDialog(
            parent=self,
            flags=Gtk.DialogFlags.MODAL,
            type=Gtk.MessageType.INFO,
            buttons=Gtk.ButtonsType.OK,
            message_format=message,
        )
        dialog.set_title(title or self.tr("info.title"))
        dialog.run()
        dialog.destroy()

    def _confirm(self, message: str) -> bool:
        dialog = Gtk.MessageDialog(
            parent=self,
            flags=Gtk.DialogFlags.MODAL,
            type=Gtk.MessageType.QUESTION,
            buttons=Gtk.ButtonsType.YES_NO,
            message_format=message,
        )
        response = dialog.run()
        dialog.destroy()
        return response == Gtk.ResponseType.YES

    def on_delete(self, _widget: Gtk.Widget, _event) -> bool:
        if self.dirty and not self._confirm(self.tr("msg.unsaved_quit")):
            return True
        Gtk.main_quit()
        return False


def main() -> int:
    i18n = I18n()
    parser = argparse.ArgumentParser(description=i18n.tr("cli.description"))
    parser.add_argument("--args", dest="args_path", default=None,
                        help=i18n.tr("cli.args_help"))
    parser.add_argument("--version", action="version",
                        version="%s %s" % (i18n.tr("app.title"), APP_VERSION))
    opts = parser.parse_args()
    ConfigWindow(opts.args_path or default_args_path(), i18n=i18n)
    Gtk.main()
    return 0


if __name__ == "__main__":
    sys.exit(main())
