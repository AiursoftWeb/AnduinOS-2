#!/bin/bash

set -e                  # exit on error
set -o pipefail         # exit on pipeline error
set -u                  # treat unset variable as error

print_ok "Setting up hostname..."
echo "$TARGET_NAME" > /etc/hostname
judge "Set up hostname to $TARGET_NAME"

print_ok "Filtering available language packs..."
VALID_PACKAGES=()
for pkg in $LANGUAGE_PACKS; do
    if apt-get install -s -y "$pkg" >/dev/null 2>&1; then
        VALID_PACKAGES+=("$pkg")
    else
        print_warn "Package $pkg is not installable (no candidate or broken), skipping."
    fi
done

print_ok "Installing available language packs..."
if [ "${#VALID_PACKAGES[@]}" -gt 0 ]; then
    apt install -y "${VALID_PACKAGES[@]}" \
        --no-install-recommends
    judge "Install language packs"
else
    print_warn "No language packs were valid for installation."
fi
