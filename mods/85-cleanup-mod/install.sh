#!/bin/bash

set -e                  # exit on error
set -o pipefail         # exit on pipeline error
set -u                  # treat unset variable as error

# Clean up root home
print_ok "Cleaning up /root/..."
rm -f /root/.config/mimeapps.list || true
rm -rf /root/.local/share/gnome-shell/extensions || true
rm -rf /root/.cache || true
judge "Clean up /root/"

# Clean up apt cache
print_ok "Cleaning up apt cache..."
find /var/cache/apt/archives -mindepth 1 -delete 2>/dev/null || true
rm -f /var/cache/apt/pkgcache.bin /var/cache/apt/srcpkgcache.bin || true
judge "Clean up apt cache"

# Clean up apt lists (save ~50-80MB in the squashfs; the installed system
# will re-fetch them on first apt update anyway)
print_ok "Cleaning up apt lists..."
find /var/lib/apt/lists -mindepth 1 -maxdepth 1 ! -name 'lock' ! -name 'partial' -delete 2>/dev/null || true
judge "Clean up apt lists"

# Clean up log files
print_ok "Cleaning up log files..."
find /var/log -mindepth 1 -delete 2>/dev/null || true
judge "Clean up log files"

# Truncate machine id
print_ok "Truncating machine id..."
truncate -s 0 /etc/machine-id || true
truncate -s 0 /var/lib/dbus/machine-id || true
judge "Truncate machine id"

# Ubuntu enables ssh.socket when openssh-server is first installed. The Live
# image must not expose a listener merely because it carries the payload. This
# is deliberately an image-finalization action, not a global systemd preset:
# installed machines retain administrator-selected SSH state across upgrades
# and preset-all operations.
print_ok "Disabling Secure Shell listeners in the Live image..."
systemctl disable ssh.service ssh.socket
judge "Disable Live Secure Shell listeners"

# SSH host keys identify one machine and must never be cloned through the
# SquashFS template. The native installer creates target-owned keys after the
# Live system has been copied.
print_ok "Removing build-time SSH host identity..."
if [[ -d /etc/ssh ]]; then
    find /etc/ssh -maxdepth 1 \
        \( -name 'ssh_host_*_key' -o -name 'ssh_host_*_key.pub' \) \
        -delete
fi
judge "Remove build-time SSH host identity"

# Remove timezone files (systemd.timezone= on kernel cmdline sets them at boot)
print_ok "Removing timezone files..."
rm -f /etc/localtime /etc/timezone || true
judge "Remove timezone files"

# Clean bash history and temp files
print_ok "Removing bash history and temporary files..."
find /tmp -mindepth 1 -delete 2>/dev/null || true
rm -f ~/.bash_history 2>/dev/null || true
export HISTSIZE=0
judge "Remove bash history and temporary files"

# Remove usr-is-merged folders
print_ok "Removing usr-is-merged folders..."
rm -rf /bin.usr-is-merged /lib.usr-is-merged /sbin.usr-is-merged || true
judge "Remove usr-is-merged folders"
