#!/bin/bash
# 构建 AnduinOS 构建配置器的 .deb 安装包。
# 用法: ./gui/build_deb.sh
set -euo pipefail

HERE="$(cd "$(dirname "$(readlink -f "$0")")" && pwd)"
ROOT="$(dirname "$HERE")"
DIST="$ROOT/dist"
VERSION="2.0.0"
PKGNAME="anduinos-config-ui_${VERSION}_all"
PKGROOT="$DIST/$PKGNAME"

echo "[DEB] 构建 $PKGNAME.deb ..."
rm -rf "$PKGROOT"
mkdir -p "$DIST"
trap 'rm -rf "$PKGROOT"' EXIT

mkdir -p \
    "$PKGROOT/DEBIAN" \
    "$PKGROOT/usr/bin" \
    "$PKGROOT/usr/lib/anduinos-config-ui" \
    "$PKGROOT/usr/share/applications"

# ---- control ----
cat > "$PKGROOT/DEBIAN/control" <<EOF
Package: anduinos-config-ui
Version: $VERSION
Section: utils
Priority: optional
Architecture: all
Depends: python3, python3-gi, gir1.2-gtk-3.0
Maintainer: AnduinOS <dev@anduinos.com>
Description: GTK3 graphical configuration tool for AnduinOS-2 build
 A GTK3 GUI to edit args.sh for the AnduinOS-2 ISO builder. It covers all
 build settings, keeps downloaded .deb packages between builds, lets users
 choose which packages are installed, supports custom chroot/pre-ISO hooks,
 and can start a build or resume an interrupted one. It provides i18n with
 English as the default language and plain-text translation files.
EOF

# ---- 程序与模块 ----
install -m 0644 "$HERE/anduinos_config_ui.py" "$PKGROOT/usr/lib/anduinos-config-ui/anduinos_config_ui.py"
install -m 0644 "$HERE/config_editor.py" "$PKGROOT/usr/lib/anduinos-config-ui/config_editor.py"
install -m 0644 "$HERE/config_schema.py" "$PKGROOT/usr/lib/anduinos-config-ui/config_schema.py"
install -m 0644 "$HERE/packages_config.py" "$PKGROOT/usr/lib/anduinos-config-ui/packages_config.py"
install -m 0644 "$HERE/i18n.py" "$PKGROOT/usr/lib/anduinos-config-ui/i18n.py"
install -m 0755 "$HERE/run_build.sh" "$PKGROOT/usr/lib/anduinos-config-ui/run_build.sh"

# ---- 语言文件（明文 UTF-8 JSON，可任意增删，界面下拉框自动发现）----
mkdir -p "$PKGROOT/usr/lib/anduinos-config-ui/locales"
if [ -d "$HERE/locales" ]; then
    for locale_file in "$HERE"/locales/*.json; do
        [ -e "$locale_file" ] || continue
        install -m 0644 "$locale_file" "$PKGROOT/usr/lib/anduinos-config-ui/locales/"
    done
fi

# ---- 启动入口 ----
cat > "$PKGROOT/usr/bin/anduinos-config-ui" <<'EOF'
#!/bin/sh
# 若从工程目录启动，会自动定位该目录的 args.sh；也可用 --args 指定。
exec python3 /usr/lib/anduinos-config-ui/anduinos_config_ui.py "$@"
EOF
chmod 0755 "$PKGROOT/usr/bin/anduinos-config-ui"

# ---- 桌面入口 ----
cat > "$PKGROOT/usr/share/applications/anduinos-config-ui.desktop" <<'EOF'
[Desktop Entry]
Type=Application
Version=1.0
Name=AnduinOS Build Configurator
Comment=Configure AnduinOS-2: packages, deb cache, custom hooks, resume builds
Exec=anduinos-config-ui
Icon=preferences-system
Categories=System;Settings;
Terminal=false
EOF

dpkg-deb --build --root-owner-group "$PKGROOT" "$DIST/$PKGNAME.deb"
echo "[DEB] 已生成: $DIST/$PKGNAME.deb"
