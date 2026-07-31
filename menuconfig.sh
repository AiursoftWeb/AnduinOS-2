#!/bin/bash
# menuconfig.sh — TUI for editing AnduinOS build configuration (args.sh)
set -euo pipefail

DIALOG=${DIALOG:-whiptail}
ARGS_FILE="$(dirname "$(readlink -f "$0")")/args.sh"
BACKUP_FILE=$(mktemp)
SAVE_CHANGES=false

cp -- "$ARGS_FILE" "$BACKUP_FILE"

cleanup() {
    if [ "$SAVE_CHANGES" != true ]; then
        cp -- "$BACKUP_FILE" "$ARGS_FILE"
    fi
    rm -f -- "$BACKUP_FILE"
}
trap cleanup EXIT
trap 'exit 129' HUP
trap 'exit 130' INT
trap 'exit 143' TERM

# ---------------------------------------------------------------------------
# Helpers: get current value, set new value
# ---------------------------------------------------------------------------
get() {
    local key="$1"
    (
        # Evaluate computed defaults without leaking args.sh environment
        # changes (HOME, locale, etc.) into the menuconfig process.
        # shellcheck disable=SC1090
        source "$ARGS_FILE"
        printf '%s\n' "${!key}"
    )
}
set_val() {
    local key="$1" val="$2"
    # Escape forward slashes for sed
    local escaped
    escaped=$(printf '%s\n' "$val" | sed 's/[\/&]/\\&/g')
    sed -i "s|^export ${key}=.*|export ${key}=\"${escaped}\"|" "$ARGS_FILE"
}

# ---------------------------------------------------------------------------
# Dialog wrapper
# ---------------------------------------------------------------------------
inputbox() {
    local title="$1" text="$2" init="$3"
    local rc=0
    result=$($DIALOG --title "$title" --inputbox "$text" 10 60 "$init" 3>&1 1>&2 2>&3) || rc=$?
    return $rc
}
menubox() {
    local title="$1" text="$2"
    shift 2
    local rc=0
    result=$($DIALOG --title "$title" --menu "$text" 0 0 0 "$@" 3>&1 1>&2 2>&3) || rc=$?
    return $rc
}
msg() {
    $DIALOG --title "$1" --msgbox "$2" 0 0
}

# ---------------------------------------------------------------------------
# Sub-menus
# ---------------------------------------------------------------------------
edit_os() {
    while true; do
        result=""
        menubox "OS Information" "Select to edit:" \
            "codename"  "Ubuntu codename       [$(get TARGET_UBUNTU_VERSION)]" \
            "name"      "OS short name         [$(get TARGET_NAME)]" \
            "business"  "OS display name       [$(get TARGET_BUSINESS_NAME)]" \
            "version"   "Build version         [$(get TARGET_BUILD_VERSION)]" \
            "back"      "< Back"
        case "$result" in
            codename)
                inputbox "Ubuntu Codename" "Release codename (jammy/noble/oracular/plucky/questing/resolute):" "$(get TARGET_UBUNTU_VERSION)" || continue
                set_val TARGET_UBUNTU_VERSION "$result" ;;
            name)
                inputbox "OS Short Name" "Lowercase, no spaces/special chars:" "$(get TARGET_NAME)" || continue
                set_val TARGET_NAME "$result" ;;
            business)
                inputbox "OS Display Name" "Business name, no special chars:" "$(get TARGET_BUSINESS_NAME)" || continue
                set_val TARGET_BUSINESS_NAME "$result" ;;
            version)
                inputbox "Build Version" "Version string (e.g. 2.0.0, 2.0.0-beta1):" "$(get TARGET_BUILD_VERSION)" || continue
                set_val TARGET_BUILD_VERSION "$result" ;;
            back|"") return ;;
        esac
    done
}

edit_repos() {
    while true; do
        result=""
        menubox "Repositories" "Select to edit:" \
            "apt"       "APT mirror            [$(get APT_SOURCE)]" \
            "apkg"      "APKG server           [$(get APKG_SERVER)]" \
            "cert"      "APKG cert name        [$(get APKG_CERT_NAME)]" \
            "aptcfg"    "APT config package    [$(get APT_CONFIG_PACKAGE)]" \
            "back"      "< Back"
        case "$result" in
            apt)
                inputbox "APT Mirror" "Ubuntu mirror URL:" "$(get APT_SOURCE)" || continue
                set_val APT_SOURCE "$result" ;;
            apkg)
                local choice
                choice=$($DIALOG --title "APKG Server" --menu "Choose:" 0 0 2 \
                    "https://packages.anduinos.com"      "Production" \
                    "https://apkg-dev.aiursoft.com"      "Development" 3>&1 1>&2 2>&3) && set_val APKG_SERVER "$choice"
                ;;
            cert)
                inputbox "APKG Cert" "GPG certificate name:" "$(get APKG_CERT_NAME)" || continue
                set_val APKG_CERT_NAME "$result" ;;
            aptcfg)
                local choice
                choice=$($DIALOG --title "APT Config Package" --menu "Choose:" 0 0 2 \
                    "anduinos-apt-config"     "Production" \
                    "anduinos-apt-config-dev" "Development" 3>&1 1>&2 2>&3) && set_val APT_CONFIG_PACKAGE "$choice"
                ;;
            back|"") return ;;
        esac
    done
}

edit_build() {
    while true; do
        result=""
        menubox "Build Options" "Select to edit:" \
            "arch" "Target architecture   [$(get TARGET_ARCH)]" \
            "back" "< Back"
        case "$result" in
            arch)
                local choice
                choice=$($DIALOG --title "Target Architecture" --menu "Choose CPU architecture:" 0 0 2 \
                    "amd64" "Intel / AMD 64-bit (x86_64)" \
                    "arm64" "ARM 64-bit (Snapdragon, Apple Silicon, Raspberry Pi)" 3>&1 1>&2 2>&3) && set_val TARGET_ARCH "$choice"
                ;;
            back|"") return ;;
        esac
    done
}

# ---------------------------------------------------------------------------
# Main loop
# ---------------------------------------------------------------------------
while true; do
    result=""
    menubox "AnduinOS Build Configuration" "make menuconfig — edit args.sh" \
        "os"        "OS Information" \
        "repos"     "Repositories" \
        "build"     "Build Options" \
        "save"      "Save & Exit" \
        "exit"      "Exit without saving"
    case "$result" in
        os)     edit_os ;;
        repos)  edit_repos ;;
        build)  edit_build ;;
        save)
            SAVE_CHANGES=true
            msg "Saved" "Configuration saved to args.sh.\nRun 'make' to build."
            exit 0 ;;
        exit|"")
            exit 0 ;;
    esac
done
