#!/bin/bash
set -e                  # exit on error
set -o pipefail         # exit on pipeline error
set -u                  # treat unset variable as error
#==========================
# Install AnduinOS swap packages
#==========================


source /root/mods/shared.sh
source /root/mods/args.sh


# anduinos-apt-config Depends on anduinos-archive-keyring, so one
# apt install pulls both: keyring → trust → sources → pinning.
print_ok "Installing anduinos-apt-config (includes anduinos-archive-keyring)..."
apt install -y anduinos-apt-config
judge "Install anduinos-apt-config + anduinos-archive-keyring"

print_ok "Installing AnduinOS base-files (swap)..."
apt install -y base-files
judge "Install base-files (swap)"

