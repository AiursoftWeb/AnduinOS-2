#!/bin/bash

set -e
set -o pipefail
set -u

# spice-vdagent 0.23.0 can very occasionally ignore its normal stop request
# until systemd's 90-second service timeout expires.  The daemon carries no
# durable state, so retaining the distro unit while bounding only its stop
# phase is safer than allowing a desktop reboot to stall for several minutes.
print_ok "Bounding SPICE guest-agent shutdown latency..."

if ! dpkg-query -W -f='${db:Status-Abbrev}' spice-vdagent 2>/dev/null \
    | grep -q '^ii '; then
    print_error "spice-vdagent is missing from the desktop image"
    exit 1
fi

drop_in_dir=/etc/systemd/system/spice-vdagentd.service.d
drop_in="$drop_in_dir/20-anduinos-shutdown-timeout.conf"
install -d -m 0755 "$drop_in_dir"
cat > "$drop_in" <<'EOF'
[Service]
TimeoutStopSec=15s
EOF
chmod 0644 "$drop_in"

grep -Fxq '[Service]' "$drop_in"
grep -Fxq 'TimeoutStopSec=15s' "$drop_in"
judge "Bound SPICE guest-agent shutdown latency"
