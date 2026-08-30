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
SCRIPT_DIR="$(dirname "$(readlink -f "$0")")"
export SCRIPT_DIR

#==========================
# Language Information
#==========================

# Build environment locale — strictly enforced to English.
# LC_ALL explicitly overrides all individual LC_* variables.
export LC_ALL=en_US.UTF-8
export LANG=en_US.UTF-8
export LANGUAGE=en_US:en

# ── Language pack codes ────────────────────────────────────────────────────
#
# 28 website languages map to 25 language-pack codes.
# (e.g., en-US/en-GB share 'en', pt-PT/pt-BR share 'pt', zh-TW/zh-HK share 'zh-hant')
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
# All verified present in Ubuntu apt repos.
export LANG_PACK_CODES="en de es fr it pt ru zh-hans ja zh-hant ko vi th ar nl sv pl tr ro da uk id fi hi el"
_LP=""
for _c in $LANG_PACK_CODES; do
    _LP="$_LP language-pack-$_c language-pack-$_c-base language-pack-gnome-$_c language-pack-gnome-$_c-base"
done
export LANGUAGE_PACKS="${_LP# }"
unset _LP _c

# ── GRUB / Live regional policy ────────────────────────────────────────────
#
# This policy configures the temporary Live environment only. The native
# installer's data/languages.json is an independent policy for the system that
# will be installed, so users may boot one region and install another.
#
# 28 entries — one per Live boot language.
# Format: locale_code|GRUB label|timezone|XKB layout
export SUPPORTED_LIVE_REGIONS="
en_US|English (United States)|America/New_York|us
en_GB|English (United Kingdom)|Europe/London|gb
zh_CN|Simplified Chinese (China Mainland)|Asia/Shanghai|us
zh_TW|Traditional Chinese (Taiwan)|Asia/Taipei|us
zh_HK|Traditional Chinese (Hong Kong)|Asia/Hong_Kong|us
ja_JP|Japanese|Asia/Tokyo|jp
ko_KR|Korean|Asia/Seoul|kr
vi_VN|Vietnamese|Asia/Ho_Chi_Minh|us
th_TH|Thai|Asia/Bangkok|th
de_DE|German|Europe/Berlin|de
fr_FR|French|Europe/Paris|fr
es_ES|Spanish|Europe/Madrid|es
ru_RU|Russian|Europe/Moscow|ru
it_IT|Italian|Europe/Rome|it
pt_PT|Portuguese|Europe/Lisbon|pt
pt_BR|Portuguese (Brazil)|America/Sao_Paulo|br
ar_SA|Arabic|Asia/Riyadh|ara
nl_NL|Dutch|Europe/Amsterdam|nl
sv_SE|Swedish|Europe/Stockholm|se
pl_PL|Polish|Europe/Warsaw|pl
tr_TR|Turkish|Europe/Istanbul|tr
ro_RO|Romanian|Europe/Bucharest|ro
da_DK|Danish|Europe/Copenhagen|dk
uk_UA|Ukrainian|Europe/Kiev|ua
id_ID|Indonesian|Asia/Jakarta|id
fi_FI|Finnish|Europe/Helsinki|fi
hi_IN|Hindi|Asia/Kolkata|us
el_GR|Greek|Europe/Athens|gr
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

# This is the apt source for both the build process and the live system.
# It can be any Ubuntu mirror that you prefer.
# The default is the Aiursoft mirror.
# You can change it to any other mirror that you prefer.
# See https://docs.anduinos.com/Install/Select-Best-Apt-Source.html
export APT_SOURCE="http://archive.ubuntu.com/ubuntu/"

# This is the name of the target OS.
# Must be lowercase without special characters and spaces
export TARGET_NAME="anduinos"

# This is the full display name of the target OS.
# Business name. No special characters or spaces
export TARGET_BUSINESS_NAME="AnduinOS"

# Version number. Must be in the format of x.y.z
export TARGET_BUILD_VERSION="2.0.2"

# Target CPU architecture.
#   amd64 — Intel / AMD 64-bit
#   arm64 — ARM 64-bit (Raspberry Pi, Snapdragon, Apple Silicon, etc.)
# Override on the command line:  TARGET_ARCH=arm64 ./build.sh
export TARGET_ARCH="${TARGET_ARCH:-$(dpkg --print-architecture)}"

#============================
# AnduinOS APKG server configuration
#============================

# AnduinOS APT config package name (can also be anduinos-apt-config-dev).
export APT_CONFIG_PACKAGE="anduinos-apt-config"

# APKG server URL for AnduinOS-branded overlay packages (dev: apkg-dev.aiursoft.com).
export APKG_SERVER="https://packages.anduinos.com"

# GPG certificate name on the APKG server (used to download and verify the repo).
# The cert is fetched from: $APKG_SERVER/artifacts/certs/$APKG_CERT_NAME
export APKG_CERT_NAME="anduinos"
