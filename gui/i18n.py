#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""i18n.py — AnduinOS 构建配置器的轻量国际化模块。

设计要点
--------
* 默认界面语言为英文（en）。英文词条内置在 ENGLISH 字典中，即使 locales
  目录缺失，界面也能正常显示英文。
* 其它语言的译文存放为纯文本 UTF-8 JSON 文件，位于 ``gui/locales/`` 下，
  中文按明文（真实汉字）存储，不编译为 .mo 二进制，便于直接阅读与修改。
* 启动时自动扫描 ``locales/*.json``。任何新增的语言文件都会被自动发现，
  并出现在界面的语言下拉框中，无需修改代码。
* 语言文件结构::

      {
        "_meta": {"code": "zh_CN", "name": "Chinese (Simplified)",
                  "native": "中文（简体）"},
        "strings": { "app.title": "AnduinOS 构建配置器", ... }
      }

  ``_meta.name`` 为英文名称，``_meta.native`` 为该语言自身名称（用于下拉框
  显示）。缺少 ``_meta`` 时会根据文件名推断。
* 译文使用 ``%(name)s`` 形式的命名占位符，通过 ``tr(key, **kwargs)`` 填充。
  词条缺失时回退到内置英文，再回退到 key 本身，保证界面不会出现空白。
"""

from __future__ import annotations

import json
import os

DEFAULT_LANGUAGE = "en"
LOCALES_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "locales")

# 内置英文词条：默认界面语言，也是所有译文的键集合与最终兜底。
ENGLISH: dict[str, str] = {
    # ---- 通用 / 标题 ----
    "app.title": "AnduinOS Build Configurator",
    "header.title": "AnduinOS Build Configurator",
    "header.subtitle": "Graphical editor for args.sh  |  package customization  |  custom scripts  |  resume support",
    "misc.colon": ":",
    "misc.on": "on",
    "misc.off": "off",
    "language.label": "Language",

    # ---- 配置文件选择区 ----
    "frame.config_file": "Configuration File",
    "btn.browse": "Browse…",
    "btn.reload": "Reload",
    "dialog.open.title": "Select args.sh",
    "btn.open": "Open",
    "btn.cancel": "Cancel",
    "msg.unsaved_open": "There are unsaved changes. Open another file anyway?",

    # ---- 标签页 ----
    "tab.packages": "Package Management",
    "tab.hooks": "Custom Scripts",

    # ---- 分区标题 ----
    "section.os": "System Information",
    "section.repos": "Package Sources",
    "section.build": "Build Options",
    "section.cache": "Download & Cache",
    "section.lang": "Language & Region",
    "section.env": "Build Environment",

    # ---- 字段标签 ----
    "field.ubuntu_version": "Ubuntu release codename",
    "field.target_name": "Short system name",
    "field.business_name": "Display name",
    "field.build_version": "Build version",
    "field.apt_source": "Ubuntu APT mirror",
    "field.apkg_server": "AnduinOS package server",
    "field.cert_name": "Signing certificate name",
    "field.apt_config": "APT config package",
    "field.arch": "Target architecture",
    "field.keep_debs": "Keep downloaded .deb packages",
    "field.lang_packs": "Language pack codes",
    "field.regions": "Live region policy",

    # ---- 字段帮助 ----
    "help.ubuntu_version": "Target Ubuntu suite codename. The build host codename must match it.",
    "help.target_name": "Lowercase, no spaces or special characters, e.g. anduinos. Used as the ISO identifier and output file name.",
    "help.business_name": "Distribution display name, e.g. AnduinOS.",
    "help.build_version": "Version string in x.y.z form (optionally with a suffix such as -beta1), e.g. 2.0.5.",
    "help.apt_source": "Ubuntu mirror used to assemble the root filesystem; replace with any working mirror.",
    "help.apkg_server": "APT server address for AnduinOS overlay packages.",
    "help.cert_name": "GPG certificate name used to download and verify the repository from the APKG server.",
    "help.apt_config": "APT configuration package name for AnduinOS sources (production / development).",
    "help.arch": "Architecture of the generated ISO: amd64 (Intel/AMD 64-bit) or arm64 (ARM 64-bit).",
    "help.keep_debs": (
        "Strongly recommended. When enabled, .deb packages downloaded by apt are persisted in "
        ".cache/apt-archives/ under the project directory, so a rebuild with an unstable network "
        "can reuse them. This directory is not included in the final ISO."
    ),
    "help.lang_packs": "Space-separated language pack codes; expanded into language-pack-* packages at build time.",
    "help.regions": (
        "Live boot menu region entries, one per line: locale|label|timezone|XKB layout. "
        "Exactly 29 entries are required and validated by the build script."
    ),
    "help.debian_frontend": "Non-interactive package installation mode; usually keep noninteractive.",
    "help.lc_all": "Locale of the build process, forced to English; independent of the languages selectable in the Live system.",
    "help.lang": "Language setting of the build process.",
    "help.language": "Language priority list of the build process.",

    # ---- 布尔开关与缓存面板 ----
    "bool.enable": "Enable",
    "status.deb_toggle": "Deb retention turned %(state)s; effective after saving",
    "panel.cache_status": "Local Cache Status",
    "btn.refresh": "Refresh",
    "btn.open_dir": "Open Folder",
    "btn.clear_cache": "Clear Cache",
    "cache.path": "Cache directory: %(path)s",
    "cache.count": "Cached .deb files: %(count)d",
    "cache.size": "Disk usage: %(size)s",
    "msg.cache_empty": "No .deb files in the cache directory.",
    "confirm.clear_cache": "This will delete %(count)d .deb files (%(size)s). This cannot be undone. Continue?",
    "msg.clear_failed": "Failed to clear the cache. Run manually: sudo rm -rf %(path)s",

    # ---- 软件包管理页 ----
    "pkg.intro": (
        "Check the packages to install; unchecked packages will be skipped. You can add extra "
        "package names. Changes are saved to packages.json in the project root and applied on "
        "the next build."
    ),
    "group.core": "Core / Kernel Packages",
    "group.desktop": "Desktop / Application Packages",
    "pkg.col.install": "Install",
    "pkg.col.name": "Package",
    "pkg.col.extra": "Extra packages to install",
    "btn.select_all": "Select All",
    "btn.select_none": "Select None",
    "btn.restore_default": "Restore Defaults",
    "entry.extra_placeholder": "Extra package name, e.g. htop",
    "btn.add_extra": "Add Extra Package",
    "btn.del_extra": "Remove Selected",
    "err.duplicate_extra": '"%(name)s" is already in the extra package list.',

    # ---- 自定义脚本页 ----
    "hooks.intro": (
        "Enter custom commands / scripts here. The chroot script runs after rootfs customization "
        "and before leaving chroot; the pre-ISO script runs on the host once image/ is ready but "
        "before xorriso packaging."
    ),
    "hooks.frame.chroot": "Chroot script (after packages are installed)",
    "hooks.frame.pre_iso": "Host script before ISO packaging (after image/ is ready)",

    # ---- 校验与保存 ----
    "err.target_name": "The short system name must be lowercase and contain only letters, digits, underscores or hyphens.",
    "err.business_name": "The display name cannot be empty.",
    "err.apt_source": "The Ubuntu APT mirror cannot be empty.",
    "confirm.regions": "The Live region policy currently has %(count)d entries; the build script requires 29. Save anyway?",
    "dialog.save_as.title": "Save Configuration As",
    "btn.save_as": "Save As…",
    "btn.save_dialog": "Save",
    "msg.save_failed": "Save failed: %(error)s",
    "msg.saved": "Saved %(name)s (args.sh.bak created)",
    "msg.save_as_failed": "Save As failed: %(error)s",
    "msg.saved_as": "Saved as %(path)s",

    # ---- 底部按钮与构建 ----
    "btn.quit": "Quit",
    "btn.view_command": "View Build Command",
    "btn.save_config": "Save Configuration",
    "btn.save_build": "Save Configuration & Start Build",
    "dialog.build.title": "Choose Build Mode",
    "btn.resume": "Resume from Interruption",
    "btn.fresh": "Fresh Build",
    "dialog.build.text": (
        "Configuration saved. Choose a build mode:\n\n"
        "Fresh build: clean old artifacts and build from scratch\n"
        "Resume from interruption: skip completed stages, useful after a script error"
    ),
    "msg.build_cancelled": "Build cancelled; configuration saved",
    "log.title": "AnduinOS Build Log",
    "msg.build_started": "Build started: %(command)s",
    "buildcmd.text": (
        "After saving the configuration, run in the project directory:\n\n"
        "  cd %(dir)s && make\n\n"
        "If the script fails midway, resume from the interruption:\n\n"
        "  cd %(dir)s && ./build.sh --resume\n\n"
        'You can also click "Save Configuration & Start Build" in the GUI.'
    ),
    "info.title": "Information",

    # ---- 构建日志窗口 ----
    "log.starting": "Starting…",
    "log.executing": "Executing: %(command)s",
    "log.start_failed": "Failed to start: %(error)s",
    "log.status_start_failed": "Start failed",
    "log.success": "Build completed (exit code 0)",
    "log.success_append": ">>> Build completed successfully",
    "log.failed": "Build failed (exit code %(code)d); you can resume",
    "log.failed_append": '>>> Build failed. Click "Resume from Interruption" to continue.',
    "log.resume_append": ">>> Resuming from interruption",
    "log.stop_append": ">>> Stop signal sent",
    "log.btn.resume": "Resume from Interruption",
    "log.btn.stop": "Stop",
    "log.btn.close": "Close",
    "confirm.close_running": "The build is still running. Close and terminate it?",

    # ---- 状态栏 / 退出 ----
    "status.reloaded": "Reloaded %(name)s",
    "status.legacy_upgrade": 'Legacy config detected: "Keep downloaded .deb packages" enabled by default. Save to apply.',
    "status.language_set": "Language set to %(name)s",
    "msg.unsaved_quit": "There are unsaved changes. Quit anyway?",

    # ---- 命令行 ----
    "cli.description": "Graphical configuration tool for AnduinOS-2",
    "cli.args_help": "path to args.sh",
}

# 常见语言代码的显示名兜底（当语言文件缺少 _meta 时使用）。
_FALLBACK_NAMES: dict[str, tuple[str, str]] = {
    "en": ("English", "English"),
    "zh_CN": ("Chinese (Simplified)", "中文（简体）"),
    "zh_TW": ("Chinese (Traditional)", "中文（繁體）"),
    "ja": ("Japanese", "日本語"),
    "ko": ("Korean", "한국어"),
    "fr": ("French", "Français"),
    "de": ("German", "Deutsch"),
    "es": ("Spanish", "Español"),
    "ru": ("Russian", "Русский"),
}


class I18n:
    """轻量翻译器：管理语言目录、词条目录与当前语言。"""

    def __init__(self, locales_dir: str = LOCALES_DIR, language: str | None = None):
        self.locales_dir = locales_dir
        self.catalogs: dict[str, dict[str, str]] = {DEFAULT_LANGUAGE: dict(ENGLISH)}
        self.languages: list[dict[str, str]] = [
            {"code": DEFAULT_LANGUAGE, "name": "English", "native": "English"}
        ]
        self._current = DEFAULT_LANGUAGE
        self._discover()
        if language and language in self.catalogs:
            self._current = language

    # ------------------------------------------------------------------
    def _discover(self) -> None:
        """扫描 locales 目录下所有 *.json，注册为可用语言。"""
        if not os.path.isdir(self.locales_dir):
            return
        for filename in sorted(os.listdir(self.locales_dir)):
            if not filename.endswith(".json"):
                continue
            code = filename[:-5]
            path = os.path.join(self.locales_dir, filename)
            try:
                with open(path, "r", encoding="utf-8") as fh:
                    data = json.load(fh)
            except (OSError, ValueError) as exc:
                # 单个损坏的翻译文件不应阻止界面启动。
                print("[i18n] 跳过无效的翻译文件 %s: %s" % (filename, exc), file=sys_stderr())
                continue
            if not isinstance(data, dict):
                continue
            meta = data.get("_meta") or {}
            if not isinstance(meta, dict):
                meta = {}
            strings = data.get("strings", data)
            if not isinstance(strings, dict):
                strings = {}
            strings = {str(k): str(v) for k, v in strings.items() if not str(k).startswith("_")}

            if code == DEFAULT_LANGUAGE:
                # en.json 可覆盖内置英文（便于定制），但始终以内置词条的键为准兜底。
                merged = dict(ENGLISH)
                merged.update(strings)
                self.catalogs[code] = merged
                continue

            self.catalogs[code] = strings
            fallback = _FALLBACK_NAMES.get(code, (code, code))
            self.languages.append(
                {
                    "code": code,
                    "name": str(meta.get("name", fallback[0])),
                    "native": str(meta.get("native", fallback[1])),
                }
            )

    # ------------------------------------------------------------------
    @property
    def current(self) -> str:
        return self._current

    @property
    def current_name(self) -> str:
        for lang in self.languages:
            if lang["code"] == self._current:
                return lang["native"]
        return self._current

    def set_language(self, code: str) -> None:
        if code in self.catalogs:
            self._current = code

    def tr(self, key: str, **kwargs) -> str:
        """返回当前语言的译文；缺失时回退英文，再回退 key。"""
        text = self.catalogs.get(self._current, {}).get(key)
        if text is None:
            text = ENGLISH.get(key, key)
        if kwargs:
            try:
                return text % kwargs
            except (KeyError, TypeError, ValueError):
                return text
        return text


def sys_stderr():
    """避免在模块顶层强依赖 sys（保持导入轻量）。"""
    import sys

    return sys.stderr
