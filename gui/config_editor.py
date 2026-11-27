#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
config_editor.py — 读写 AnduinOS 的 args.sh 配置文件。

设计目标：
  * 只修改 `export KEY=...` 赋值行，完整保留文件中的注释、空行、for 循环
    和其它 shell 代码，不重新生成整个文件。
  * 通过 `bash source` 获取变量的"有效值"，与 build.sh / menuconfig.sh 的
    取值方式保持一致（例如 TARGET_ARCH 的 ${TARGET_ARCH:-...} 默认值）。
  * 当某个键在 args.sh 中不存在时（例如新增的 KEEP_DOWNLOADED_DEBS），
    在文件末尾追加一个带注释的赋值块。
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import tempfile
from typing import Dict, Iterable, List, Optional, Tuple


class ConfigError(Exception):
    """配置文件读写或校验失败。"""


_EXPORT_RE = re.compile(r"^export\s+([A-Za-z_][A-Za-z0-9_]*)=(.*)$", re.MULTILINE)
_RECORD_SEP = "\x1e"  # 用于 bash 输出多变量时的记录分隔符


def _line_ending(text: str) -> str:
    """返回文件主要使用的换行符。"""
    return "\r\n" if "\r\n" in text else "\n"


def _shell_escape(value: str) -> str:
    """把字面值转义为可安全放入 shell 双引号中的形式。"""
    return (
        value.replace("\\", "\\\\")
        .replace('"', '\\"')
        .replace("`", "\\`")
        .replace("$", "\\$")
    )


class ArgsConfig:
    """代表一个 args.sh 配置文件。"""

    def __init__(self, path: str):
        self.path = os.path.abspath(path)
        self.raw: str = ""
        self.values: Dict[str, str] = {}
        self.present: set[str] = set()
        self._eol: str = "\n"

    # ------------------------------------------------------------------
    # 读取
    # ------------------------------------------------------------------
    def load(self) -> "ArgsConfig":
        if not os.path.isfile(self.path):
            raise ConfigError("配置文件不存在：%s" % self.path)
        try:
            with open(self.path, "r", encoding="utf-8") as fh:
                self.raw = fh.read()
        except OSError as exc:
            raise ConfigError("读取 %s 失败：%s" % (self.path, exc)) from exc

        self._eol = _line_ending(self.raw)
        self.present = {
            m.group(1)
            for m in _EXPORT_RE.finditer(self.raw.replace("\r\n", "\n"))
        }
        return self

    def evaluate(self, keys: Iterable[str]) -> Dict[str, str]:
        """通过 bash source 获取这些变量的当前有效值。"""
        keys = list(dict.fromkeys(keys))  # 去重且保持顺序
        if not keys:
            return {}
        script = (
            'source "$1" >/dev/null 2>&1 || exit 1\n'
            'for k in "${@:2}"; do\n'
            '    printf "%s" "${!k-}"\n'
            '    printf "\\x1e"\n'
            'done\n'
        )
        try:
            proc = subprocess.run(
                ["bash", "-c", script, "bash", self.path, *keys],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                env={**os.environ, "DEBIAN_FRONTEND": "noninteractive"},
                check=False,
            )
        except OSError as exc:
            raise ConfigError("无法启动 bash 读取配置：%s" % exc) from exc
        if proc.returncode != 0:
            detail = proc.stderr.decode("utf-8", "replace").strip()
            raise ConfigError("解析 %s 失败：%s" % (self.path, detail or "bash 返回非零"))

        parts = proc.stdout.decode("utf-8", "replace").split(_RECORD_SEP)
        if len(parts) < len(keys):
            raise ConfigError("解析配置输出不完整（预期 %d 项，实际 %d 项）" % (len(keys), len(parts)))
        self.values.update(dict(zip(keys, parts[: len(keys)])))
        return self.values

    # ------------------------------------------------------------------
    # 辅助：定位赋值块
    # ------------------------------------------------------------------
    def _find_span(self, key: str) -> Optional[Tuple[int, int]]:
        """返回 key 对应赋值块在 raw 中的 (start, end) 字符区间。"""
        lines = self.raw.splitlines(keepends=True)
        offset = 0
        i = 0
        while i < len(lines):
            line = lines[i]
            stripped = line.rstrip("\r\n")
            m = _EXPORT_RE.match(stripped)
            if m and m.group(1) == key:
                start = offset
                value_part = m.group(2)
                # 单行闭合：export KEY="value"
                if value_part.startswith('"') and value_part.endswith('"') and len(value_part) >= 2:
                    return start, offset + len(line)
                # 多行值：export KEY=" ... " （直到单独一行的 "）
                if value_part.startswith('"'):
                    j = i + 1
                    while j < len(lines):
                        next_stripped = lines[j].rstrip("\r\n").strip()
                        end_offset = offset + sum(len(lines[k]) for k in range(i, j + 1))
                        if next_stripped == '"':
                            return start, end_offset
                        j += 1
                    raise ConfigError("变量 %s 的多行赋值缺少结束引号" % key)
                # 无引号或 ${...} 默认值表达式：单行替换整行
                return start, offset + len(line)
            offset += len(line)
            i += 1
        return None

    @staticmethod
    def _render_assignment(key: str, value: str, eol: str) -> str:
        if "\n" in value:
            body = eol.join(value.split("\n"))
            return 'export %s="%s%s"%s' % (key, eol, body, eol)
        return 'export %s="%s"%s' % (key, _shell_escape(value), eol)

    # ------------------------------------------------------------------
    # 写入
    # ------------------------------------------------------------------
    def save(self, updates: Dict[str, str], backup: bool = True) -> None:
        """把 updates 中的键值写回 args.sh（可选先备份）。"""
        if backup and os.path.isfile(self.path):
            backup_path = self.path + ".bak"
            try:
                shutil.copy2(self.path, backup_path)
            except OSError as exc:
                raise ConfigError("备份 %s 失败：%s" % (self.path, exc)) from exc

        text = self.raw
        appended: List[str] = []

        for key, value in updates.items():
            if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", key):
                raise ConfigError("非法变量名：%s" % key)
            rendered = self._render_assignment(key, str(value), self._eol)
            span = self._find_span(key)
            if span is None:
                if key == "KEEP_DOWNLOADED_DEBS":
                    appended.append(
                        self._eol.join(
                            [
                                "",
                                "#==============================",
                                "# Deb package cache (added by AnduinOS Config UI)",
                                "# Keep downloaded .deb packages between builds so that a",
                                "# retry after a network failure does not re-download everything.",
                                "# Cached packages live under <repo>/.cache/apt-archives on the host.",
                                'export KEEP_DOWNLOADED_DEBS="%s"' % _shell_escape(str(value)),
                                "",
                            ]
                        )
                    )
                else:
                    appended.append(rendered)
                continue
            start, end = span
            text = text[:start] + rendered + text[end:]
            # _find_span 基于 self.raw 计算区间，连续替换时必须同步，
            # 否则后续键的定位会落在错误的位置上。
            self.raw = text

        if appended:
            sep = "" if text.endswith(self._eol) else self._eol
            text = text + sep + self._eol.join(appended)

        # 原子写入，避免中途失败破坏原文件
        directory = os.path.dirname(self.path) or "."
        try:
            fd, tmp = tempfile.mkstemp(prefix=".args-", dir=directory, text=True)
            try:
                with os.fdopen(fd, "w", encoding="utf-8", newline="") as fh:
                    fh.write(text)
                os.replace(tmp, self.path)
            except Exception:
                if os.path.exists(tmp):
                    os.unlink(tmp)
                raise
        except OSError as exc:
            raise ConfigError("写入 %s 失败：%s" % (self.path, exc)) from exc

        self.raw = text
        self.present |= set(updates.keys())
        self.values.update({k: str(v) for k, v in updates.items()})


def cache_directory(args_path: str) -> str:
    """返回该工程用于持久化 deb 包的宿主机缓存目录。"""
    return os.path.join(os.path.dirname(os.path.abspath(args_path)), ".cache", "apt-archives")


def cache_stats(cache_dir: str) -> Tuple[int, int]:
    """统计缓存目录中的 deb 数量与总字节数。"""
    count = 0
    size = 0
    if not os.path.isdir(cache_dir):
        return 0, 0
    for root, _dirs, files in os.walk(cache_dir):
        for name in files:
            if name.endswith(".deb"):
                count += 1
                try:
                    size += os.path.getsize(os.path.join(root, name))
                except OSError:
                    pass
    return count, size


def human_size(num_bytes: int) -> str:
    value = float(num_bytes)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if abs(value) < 1024.0 or unit == "TB":
            if unit == "B":
                return "%d B" % int(value)
            return "%.1f %s" % (value, unit)
        value /= 1024.0
    return "%.1f TB" % value
