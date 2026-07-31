#!/bin/bash
set -e                  # exit on error
set -o pipefail         # exit on pipeline error
set -u                  # treat unset variable as error
#==========================
# Install AnduinOS swap packages
#==========================

print_ok "Installing AnduinOS APT configuration and keyring packages..."
apt install -y \
    "$APT_CONFIG_PACKAGE" \
    anduinos-archive-keyring \
    base-files
judge "Install AnduinOS basic packages"

