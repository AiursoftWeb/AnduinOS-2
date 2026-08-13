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

# The Live-settings package owns this capability declaratively. Verify the
# final composition without installing it a second time in the ISO builder.
print_ok "Verifying declarative Secure Shell package composition..."
if ! dpkg-query -W -f='${Status}\n' openssh-server 2>/dev/null |
    grep -Fxq 'install ok installed'; then
    print_error "Live package composition did not include openssh-server"
    exit 1
fi
judge "Verify declarative Secure Shell package composition"

# Removing template host keys is safe only when the installed native installer
# owns the matching target-provisioning step that regenerates them. Fail closed
# while package publication is temporarily split across CI jobs.
installer_version=$(dpkg-query -W -f='${Version}' anduinos-installer-beta 2>/dev/null || true)
if [[ -z "$installer_version" ]] ||
    ! dpkg --compare-versions "$installer_version" ge '2.0.1-66'; then
    print_error "Native installer cannot provision target-owned SSH host keys: ${installer_version:-missing}"
    exit 1
fi
judge "Verify Secure Shell installer capability"

# Ubuntu enables ssh.socket when openssh-server is first installed. The Live
# image must not expose a listener merely because it carries the payload. This
# is deliberately an image-finalization action, not a global systemd preset:
# installed machines retain administrator-selected SSH state across upgrades
# and preset-all operations.
print_ok "Disabling Secure Shell listeners in the Live image..."
systemctl disable ssh.service ssh.socket
for unit in ssh.service ssh.socket; do
    state=$(systemctl is-enabled "$unit" 2>/dev/null || true)
    if [[ "$state" != "disabled" ]]; then
        print_error "Live image Secure Shell state is unsafe: $unit=${state:-unknown}"
        exit 1
    fi
done
judge "Disable Live Secure Shell listeners"

# SSH host keys identify one machine and must never be cloned through the
# SquashFS template. The native installer creates target-owned keys after the
# Live system has been copied.
print_ok "Removing build-time SSH host identity..."
if [[ -d /etc/ssh ]]; then
    find /etc/ssh -maxdepth 1 \
        \( -name 'ssh_host_*_key' -o -name 'ssh_host_*_key.pub' \) \
        -delete
    if find /etc/ssh -maxdepth 1 \
        \( -name 'ssh_host_*_key' -o -name 'ssh_host_*_key.pub' \) \
        -print -quit | grep -q .; then
        print_error "SSH host identity remains after cleanup"
        exit 1
    fi
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
