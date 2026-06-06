set -e                  # exit on error
set -o pipefail         # exit on pipeline error
set -u                  # treat unset variable as error

# Clean up root home
print_ok "Cleaning up /root/..."
rm /root/.config/mimeapps.list 2>/dev/null || true
rm /root/.local/share/gnome-shell/extensions -rf 2>/dev/null || true
rm /root/.cache -rf 2>/dev/null || true
judge "Clean up /root/"

# Clean up apt cache
print_ok "Cleaning up apt cache..."
apt clean -y
rm -rf /var/cache/apt/archives/*
judge "Clean up apt cache"

# Clean up apt lists (save ~50-80MB in the squashfs; the installed system
# will re-fetch them on first apt update anyway)
print_ok "Cleaning up apt lists..."
find /var/lib/apt/lists -mindepth 1 -maxdepth 1 ! -name 'lock' ! -name 'partial' -delete 2>/dev/null || true
judge "Clean up apt lists"

# Clean up log files
print_ok "Cleaning up log files..."
rm -rf /var/log/*
judge "Clean up log files"

# Truncate machine id
print_ok "Truncating machine id..."
truncate -s 0 /etc/machine-id
truncate -s 0 /var/lib/dbus/machine-id
judge "Truncate machine id"

# Clean bash history and temp files
print_ok "Removing bash history and temporary files..."
rm -rf /tmp/* ~/.bash_history
export HISTSIZE=0
judge "Remove bash history and temporary files"

# Remove usr-is-merged folders
print_ok "Removing some usr-is-merged folders..."
rm -rf /bin.usr-is-merged
rm -rf /lib.usr-is-merged
rm -rf /sbin.usr-is-merged
judge "Remove some usr-is-merged folders"
