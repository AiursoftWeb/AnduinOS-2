#!/bin/bash
# 用 PyInstaller 将配置器打包为单个可执行文件。
# 用法: ./gui/build_standalone.sh
set -euo pipefail

HERE="$(cd "$(dirname "$(readlink -f "$0")")" && pwd)"
ROOT="$(dirname "$HERE")"
DIST="$ROOT/dist"
WORK="$ROOT/build/pyinstaller"

mkdir -p "$DIST" "$WORK"

# PyInstaller 要求 Python 以 --enable-shared 编译，且程序需要 GTK3 (PyGObject)。
# 自动挑选一个同时满足两个条件的解释器（pyenv 的 Python 往往没有共享库）。
PY=""
for candidate in python3 /usr/bin/python3; do
    if "$candidate" -c "import sysconfig, gi; gi.require_version('Gtk', '3.0'); from gi.repository import Gtk; assert sysconfig.get_config_var('Py_ENABLE_SHARED')" >/dev/null 2>&1; then
        PY="$candidate"
        break
    fi
done
if [ -z "$PY" ]; then
    echo "[ERROR] 未找到同时支持 GTK3 与共享库的 Python，无法使用 PyInstaller。" >&2
    echo "[INFO] 请改用 .deb 包：./gui/build_deb.sh" >&2
    exit 1
fi
echo "[PYINSTALLER] 使用解释器: $PY"

if ! "$PY" -c "import PyInstaller" >/dev/null 2>&1; then
    echo "[PYINSTALLER] 未检测到 PyInstaller，正在安装..."
    "$PY" -m pip install --quiet --break-system-packages pyinstaller
fi

echo "[PYINSTALLER] 正在构建独立程序 ..."
"$PY" -m PyInstaller \
    --onefile \
    --windowed \
    --name anduinos-config-ui \
    --distpath "$DIST" \
    --workpath "$WORK" \
    --specpath "$WORK" \
    --paths "$HERE" \
    --hidden-import config_editor \
    --hidden-import config_schema \
    --hidden-import packages_config \
    --hidden-import i18n \
    --add-data "$HERE/locales:locales" \
    --clean \
    "$HERE/anduinos_config_ui.py"

chmod +x "$DIST/anduinos-config-ui"
echo "[PYINSTALLER] 已生成: $DIST/anduinos-config-ui"
