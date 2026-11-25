#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
packages_config.py — 自定义「安装哪些软件包 / 不安装哪些软件包」。

配置文件 packages.json 位于工程根目录，结构：
{
  "version": 1,
  "core":    {"包名": true/false, ...},
  "desktop": {"包名": true/false, ...},
  "extra_core": [...],
  "extra_desktop": [...]
}

build.sh 通过本模块的 --generate 把勾选结果导出为纯文本包列表，
再由 mods/05 读取，避免 chroot 内依赖 python3/json。
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile

# 与 mods/05-live-kernel-apps-installer/install.sh 中的 apt install 列表一致。
DEFAULT_CORE = [
    "anduinos-core-system",
    "anduinos-grub",
    "anduinos-shim-signed",
    "dracut",
    "dracut-core",
    "dracut-install",
    "discover",
    "laptop-detect",
    "os-prober",
    "keyutils",
]

DEFAULT_DESKTOP = [
    "anduinos-live-layers",
    "anduinos-desktop",
    "anduinos-desktop-apps",
    "anduinos-gnome-extensions",
    "anduinos-appstore",
    "anduinos-theme",
    "anduinos-wallpapers",
    "anduinos-fonts",
    "anduinos-no-snapd",
    "anduinos-session",
    "anduinos-software-properties-common",
    "anduinos-system-tweaks",
    "firefox-anduinos",
    "gnome-shell-extension-appindicator-anduinos",
    "gnome-shell-extension-dash-to-panel-anduinos",
    "plymouth-anduinos",
    "alsa-ucm-conf-anduinos",
    "firmware-sof-anduinos",
    "anduinos-hyperfluent-grub-theme",
    "anduinos-installer-beta",
    "anduinos-btrfs-snapshots-manager",
    "anduinos-recovery-env",
    "open-vm-tools-desktop",
]


def default_config() -> dict:
    return {
        "version": 1,
        "core": {name: True for name in DEFAULT_CORE},
        "desktop": {name: True for name in DEFAULT_DESKTOP},
        "extra_core": [],
        "extra_desktop": [],
    }


def load(path: str) -> dict:
    """读取配置；文件不存在时返回默认配置。缺失的包键补为 True。"""
    result = default_config()
    if not os.path.isfile(path):
        return result
    try:
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        return result
    if not isinstance(data, dict):
        return result

    for group, defaults in (("core", DEFAULT_CORE), ("desktop", DEFAULT_DESKTOP)):
        raw = data.get(group, {})
        if isinstance(raw, dict):
            for name in defaults:
                if name in raw:
                    result[group][name] = bool(raw[name])
        for key in ("extra_%s" % group,):
            extra = data.get(key, [])
            if isinstance(extra, list):
                result[key] = [str(x).strip() for x in extra if str(x).strip()]
    return result


def save(path: str, data: dict) -> None:
    """原子写入 packages.json。"""
    directory = os.path.dirname(os.path.abspath(path)) or "."
    fd, tmp = tempfile.mkstemp(prefix=".packages-", dir=directory, text=True)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(data, fh, indent=2, ensure_ascii=False)
            fh.write("\n")
        os.replace(tmp, path)
    except Exception:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise


def selected_packages(data: dict, group: str) -> list[str]:
    """返回该组勾选的包 + 额外包（保持默认顺序，去重）。"""
    names = [name for name, enabled in data.get(group, {}).items() if enabled]
    extra = data.get("extra_%s" % group, []) or []
    seen = set()
    result = []
    for name in names + list(extra):
        name = str(name).strip()
        if name and name not in seen:
            seen.add(name)
            result.append(name)
    return result


def generate_lists(packages_path: str, out_core: str, out_desktop: str) -> None:
    data = load(packages_path)
    for out, group in ((out_core, "core"), (out_desktop, "desktop")):
        os.makedirs(os.path.dirname(os.path.abspath(out)) or ".", exist_ok=True)
        names = selected_packages(data, group)
        with open(out, "w", encoding="utf-8") as fh:
            for name in names:
                fh.write(name + "\n")
        print("[PACKAGES] %s: %d 个包 -> %s" % (group, len(names), out))


def main() -> int:
    parser = argparse.ArgumentParser(description="软件包配置工具")
    parser.add_argument("--generate", action="store_true", help="生成构建所用的包列表文件")
    parser.add_argument("--root", default=".", help="工程根目录")
    parser.add_argument("--config", default=None, help="packages.json 路径")
    parser.add_argument("--out-core", default=None, help="core 包列表输出路径")
    parser.add_argument("--out-desktop", default=None, help="desktop 包列表输出路径")
    opts = parser.parse_args()

    root = os.path.abspath(opts.root)
    config = opts.config or os.path.join(root, "packages.json")
    if opts.generate:
        out_core = opts.out_core or os.path.join(root, ".cache", "build", "core_packages.txt")
        out_desktop = opts.out_desktop or os.path.join(root, ".cache", "build", "desktop_packages.txt")
        generate_lists(config, out_core, out_desktop)
        return 0

    # 默认：以 JSON 打印当前配置（便于调试）
    print(json.dumps(load(config), indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
