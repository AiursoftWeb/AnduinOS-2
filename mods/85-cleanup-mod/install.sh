set -e                  # exit on error
set -o pipefail         # exit on pipeline error
set -u                  # treat unset variable as error

# Clean up apt cache
print_ok "Cleaning up apt cache..."
apt update
apt clean -y
rm -rf /var/cache/apt/archives/*
judge "Clean up apt cache"

# Clean up log files
print_ok "Cleaning up log files..."
rm -rf /var/log/*
judge "Clean up log files"

# Truncate machine id
print_ok "Truncating machine id..."
truncate -s 0 /etc/machine-id
truncate -s 0 /var/lib/dbus/machine-id
judge "Truncate machine id"

# Remove initctl diversion
print_ok "Removing diversion..."
rm /sbin/initctl
dpkg-divert --rename --remove /sbin/initctl
judge "Remove diversion"

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
