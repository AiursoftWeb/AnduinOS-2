#!/bin/bash

#=================================================
#           PLEASE READ THIS BEFORE EDITING
#=================================================
# This file is used to set the environment variables for the build process.
# Before building AnduinOS, you should edit this file to customize the build process.
# It is sourced by the build script and should not be executed directly.
# You can edit this file to customize the build process.
# However, you should not change the variable names or the structure of the file.
# After editing this file, you can run the build script `make` to start the build process.

#==========================
# Builder Environment Variables
#==========================
export DEBIAN_FRONTEND=noninteractive
export SCRIPT_DIR="$(dirname "$(readlink -f "$0")")"
export HOME=/root

# Set if build in an interactive way.
# Can be: "-y" or ""
export INTERACTIVE="-y"

#==========================
# Language Information
#==========================


# Build environment locale — always en_US.UTF-8 regardless of DEFAULT_LANG.
# The build scripts need a predictable, English locale to run correctly.
export LC_ALL=en_US.UTF-8
export LC_CTYPE=en_US.UTF-8
export LC_TIME=en_US.UTF-8
export LC_NAME=en_US.UTF-8
export LC_ADDRESS=en_US.UTF-8
export LC_TELEPHONE=en_US.UTF-8
export LC_MEASUREMENT=en_US.UTF-8
export LC_IDENTIFICATION=en_US.UTF-8
export LC_NUMERIC=en_US.UTF-8
export LC_PAPER=en_US.UTF-8
export LC_MONETARY=en_US.UTF-8
export LANG=en_US.UTF-8
export LANGUAGE=en_US:en

# ── Language pack codes ────────────────────────────────────────────────────
#
# 28 website languages (25 language-pack codes — en/pt/zh-hans/zh-hant
# each cover two website options):
#
#   en-US English (US)    zh-CN 中文 (CN)       de-DE Deutsch
#   en-GB English (UK)    zh-TW 中文 (TW)       fr-FR Français
#                         zh-HK 中文 (HK)       es-ES Español
#   ja-JP 日本語           ko-KR 한국어          it-IT Italiano
#   vi-VN Tiếng Việt      th-TH ภาษาไทย        pt-PT Português
#   ar-SA العربية          nl-NL Nederlands      pt-BR Português (Brasil)
#   sv-SE Svenska          pl-PL Polski          ru-RU Русский
#   tr-TR Türkçe           ro-RO Română          da-DK Dansk
#   uk-UA Українська       id-ID Bahasa Indonesia
#   fi-FI Suomi            hi-IN हिन्दी          el-GR Ελληνικά
#
# All verified present in Ubuntu apt repos (2026-06).
# Ubiquity will dynamically fetch unlisted languages if chosen online.
export LANG_PACK_CODES="en de es fr it pt ru zh-hans ja zh-hant ko vi th ar nl sv pl tr ro da uk id fi hi el"
_LP=""
for _c in $LANG_PACK_CODES; do
    _LP="$_LP language-pack-$_c language-pack-$_c-base language-pack-gnome-$_c language-pack-gnome-$_c-base"
done
export LANGUAGE_PACKS="${_LP# }"
unset _LP _c

# ── GRUB boot menu locale submenu ──────────────────────────────────────────
#
# 28 entries — one per website language. Rendered under
# "Try and Install in Other Languages..." on the live ISO boot screen.
# Format: locale_code|Display Label
export GRUB_LOCALES="
en_US|English (United States)
en_GB|English (United Kingdom)
zh_CN|中文 (中国大陆)
zh_TW|中文 (台灣)
zh_HK|中文 (香港)
ja_JP|日本語
ko_KR|한국어
vi_VN|Tiếng Việt
th_TH|ภาษาไทย
de_DE|Deutsch
fr_FR|Français
es_ES|Español
ru_RU|Русский
it_IT|Italiano
pt_PT|Português
pt_BR|Português (Brasil)
ar_SA|العربية
nl_NL|Nederlands
sv_SE|Svenska
pl_PL|Polski
tr_TR|Türkçe
ro_RO|Română
da_DK|Dansk
uk_UA|Українська
id_ID|Bahasa Indonesia
fi_FI|Suomi
hi_IN|हिन्दी
el_GR|Ελληνικά
"

#==========================
# OS system information
#==========================

# This is the target Ubuntu version code name for the build.
# It should match the Ubuntu version you are building against.
# For example, if you are building against Ubuntu 22.04 LTS, this should be "jammy".
# If you are building against Ubuntu 24.04 LTS, this should be "noble".
# If you are building against Ubuntu 24.10, this should be "oracular".
# If you are building against Ubuntu 25.04, this should be "plucky".
# If you are building against Ubuntu 25.10, this should be "questing".
# If you are building against Ubuntu 26.04, this should be "resolute".
# Can be: jammy noble oracular plucky questing resolute
export TARGET_UBUNTU_VERSION="resolute"

# This is the apt source for the build.
# It can be any Ubuntu mirror that you prefer.
# The default is the Aiursoft mirror.
# You can change it to any other mirror that you prefer.
# See https://docs.anduinos.com/Install/Select-Best-Apt-Source.html
export BUILD_UBUNTU_MIRROR="https://mirror.aiursoft.com/ubuntu/"

# This is the name of the target OS.
# Must be lowercase without special characters and spaces
export TARGET_NAME="anduinos"

# This is the full display name of the target OS.
# Business name. No special characters or spaces
export TARGET_BUSINESS_NAME="AnduinOS"

# Version number. Must be in the format of x.y.z
export TARGET_BUILD_VERSION="2.0.0"

#===========================
# Installer customization
#===========================

# Packages will be uninstalled during the installation process
export TARGET_PACKAGE_REMOVE="
    ubiquity \
    casper \
    discover \
    laptop-detect \
    os-prober \
    gparted \
    anduinos-installer-config \
    anduinos-bwrap-hack \
"

#============================
# Browser configuration
#============================

# How to install Firefox. Can be: "none", "official_apt"
# none:         no firefox
# official_apt: install firefox from the official Mozilla APT repository
export FIREFOX_PROVIDER="official_apt"

# Build-time mirror for the Mozilla APT repository.
# If set, replaces packages.mozilla.org during build.
# Sample: mirror-packages.aiursoft.com
export BUILD_FIREFOX_MIRROR=""

# Live-system mirror for the Mozilla APT repository.
# If set together with BUILD_FIREFOX_MIRROR, replaces the build mirror in the final image.
# If set alone, replaces packages.mozilla.org in the final image.
export LIVE_FIREFOX_MIRROR=""

# Optional locale package for Firefox (e.g. firefox-locale-zh-hans)
export FIREFOX_LOCALE_PACKAGE=""
#============================
# Input method configuration
#============================

# Packages will be installed during the installation process
# Can be:
# * ibus-rime
# * ibus-libpinyin
# * ibus-chewing
# * ibus-table-cangjie
# * ibus-mozc
# * ibus-hangul
# * ibus-unikey
# * ibus-libthai
export INPUT_METHOD_INSTALL=""

# Boolean indicator for whether to install anduinos-ibus-rime
export CONFIG_IBUS_RIME="false"
if [[ "$CONFIG_IBUS_RIME" == "true" && "$INPUT_METHOD_INSTALL" != *"ibus-rime"* ]]; then
    echo "Error: CONFIG_IBUS_RIME is set to true, but INPUT_METHOD_INSTALL is not set to ibus-rime"
    exit 1
fi

# The default keyboard layout. Can be:
# * [('xkb', 'us')]
# * [('xkb', 'us'), ('ibus', 'rime')]
# * [('xkb', 'us'), ('ibus', 'chewing')]
# * [('xkb', 'us'), ('xkb', 'fr')]
export CONFIG_INPUT_METHOD="[('xkb', 'us')]"

#============================
# Software properties configuration
#============================

# To install software-properties-gtk, set to "true" or "false"
export INSTALL_MODIFIED_SOFTWARE_PROPERTIES_GTK="true"

#============================
# Time zone configuration
#============================

# The timezone for the new OS being built (In chroot environment)
# To view available options, run: `ls /usr/share/zoneinfo/`
export TIMEZONE="America/Los_Angeles"

#============================
# Weather plugin configuration
#============================

# This will affect the default weather location in the weather plugin.
export CONFIG_WEATHER_LOCATION="['{\"name\":\"San Francisco, California, United States\",\"lat\":37.7749295,\"lon\":-122.4194155}']"

#============================
# AnduinOS APKG server configuration
#============================

# This is the APKG server URL for AnduinOS-branded overlay packages.
# It serves the anduinos-* packages (keyring, apt-config, branding, etc.).
export APKG_SERVER="https://apkg-dev.aiursoft.com"

# GPG certificate name on the APKG server (used to download and verify the repo).
# The cert is fetched from: $APKG_SERVER/artifacts/certs/$APKG_CERT_NAME
export APKG_CERT_NAME="anduinos"

#============================
# Live system configuration
#============================

# This is the default apt server in the live system.
# It can be any Ubuntu mirror that you prefer.
export LIVE_UBUNTU_MIRROR="https://mirror.aiursoft.com/ubuntu/"


# Default CLI tools have been moved into the anduinos-core-system metapackage.
