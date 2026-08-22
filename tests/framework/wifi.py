"""Disposable in-guest Wi-Fi lab and credential-migration oracles."""

from __future__ import annotations

import json
import re
import secrets
import shlex
import stat
from dataclasses import dataclass, field
from pathlib import Path

from .errors import TestFailure
from .serial import SerialConsole


WIFI_LAB_SSID = "AnduinOS-Acceptance-WiFi"
WIFI_LAB_GATEWAY = "10.77.0.1"
_LAB_PREFIX = "WIFI_LAB_JSON="
_PROFILE_PREFIX = "WIFI_PROFILE_JSON="
_RECONNECT_PREFIX = "WIFI_RECONNECT_JSON="
_UUID = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-"
    r"[0-9a-f]{4}-[0-9a-f]{12}$"
)


@dataclass(frozen=True)
class WifiLabState:
    client_device: str
    ap_device: str
    ssid: str
    bssid: str


@dataclass
class WifiLab:
    """Own one random WPA2 secret without persisting it in test metadata."""

    ssid: str = WIFI_LAB_SSID
    password: str = field(
        default_factory=lambda: secrets.token_hex(16),
        repr=False,
    )
    live_profile_uuid: str | None = None

    def start(
        self,
        console: SerialConsole,
        evidence: Path,
        *,
        require_client_disconnected: bool = True,
    ) -> WifiLabState:
        """Create two hwsim radios and a local-only WPA2 AP in the guest."""

        result = console.run(
            self._setup_script(
                require_client_disconnected=require_client_disconnected,
            ),
            timeout=150,
        )
        evidence.write_text(result.stdout + "\n", encoding="utf-8")
        payload = _extract_json(result.stdout, _LAB_PREFIX)
        expected = {
            "schema_version",
            "client_device",
            "ap_device",
            "ssid",
            "bssid",
            "security",
            "visible",
            "ethernet_carrier",
            "client_policy",
        }
        if set(payload) != expected:
            raise TestFailure("Wi-Fi lab returned an invalid evidence shape")
        if (
            payload["schema_version"] != 1
            or payload["ssid"] != self.ssid
            or payload["security"] != "WPA2"
            or payload["visible"] is not True
            or payload["ethernet_carrier"] != "down"
            or payload["client_policy"]
            != (
                "must-start-disconnected"
                if require_client_disconnected
                else "automatic-reconnect-allowed"
            )
        ):
            raise TestFailure("Wi-Fi lab did not expose the required isolated WPA2 AP")
        client = payload["client_device"]
        ap = payload["ap_device"]
        bssid = payload["bssid"]
        if (
            not isinstance(client, str)
            or not re.fullmatch(r"[A-Za-z0-9_.-]+", client)
            or not isinstance(ap, str)
            or not re.fullmatch(r"[A-Za-z0-9_.-]+", ap)
            or client == ap
            or not isinstance(bssid, str)
            or re.fullmatch(r"(?:[0-9A-F]{2}:){5}[0-9A-F]{2}", bssid) is None
        ):
            raise TestFailure("Wi-Fi lab returned unsafe radio identities")
        return WifiLabState(client, ap, self.ssid, bssid)

    def capture_live_profile(
        self,
        console: SerialConsole,
        state: WifiLabState,
        evidence: Path,
    ) -> str:
        """Freeze the UI-created profile identity without reading its secret."""

        result = console.run(
            _live_profile_script(self.ssid, state.client_device),
            timeout=60,
        )
        evidence.write_text(result.stdout + "\n", encoding="utf-8")
        payload = _extract_json(result.stdout, _PROFILE_PREFIX)
        expected = {
            "schema_version",
            "uuid",
            "ssid",
            "device",
            "active",
            "profile_regular",
            "profile_symlink",
            "profile_uid",
            "profile_gid",
            "profile_mode",
        }
        if set(payload) != expected:
            raise TestFailure("Live Wi-Fi profile returned an invalid evidence shape")
        uuid = payload["uuid"]
        if (
            payload["schema_version"] != 1
            or not isinstance(uuid, str)
            or _UUID.fullmatch(uuid) is None
            or payload["ssid"] != self.ssid
            or payload["device"] != state.client_device
            or payload["active"] is not True
            or payload["profile_regular"] is not True
            or payload["profile_symlink"] is not False
            or payload["profile_uid"] != 0
            or payload["profile_gid"] != 0
            or payload["profile_mode"] != "0600"
        ):
            raise TestFailure("Live Wi-Fi profile is not safely persisted by NetworkManager")
        self.live_profile_uuid = uuid
        return uuid

    def assert_installed_reconnect(
        self,
        console: SerialConsole,
        evidence: Path,
    ) -> None:
        """Prove automatic target reconnect without sending the password again."""

        if self.live_profile_uuid is None:
            raise TestFailure("No Live Wi-Fi profile identity was captured")
        result = console.run(
            _installed_reconnect_script(self.ssid, self.live_profile_uuid),
            timeout=150,
        )
        evidence.write_text(result.stdout + "\n", encoding="utf-8")
        payload = _extract_json(result.stdout, _RECONNECT_PREFIX)
        validate_reconnect_evidence(
            payload,
            expected_ssid=self.ssid,
            expected_uuid=self.live_profile_uuid,
        )

    def assert_not_leaked(self, artifacts: Path) -> None:
        assert_secret_absent(artifacts, self.password)

    def _setup_script(
        self,
        *,
        require_client_disconnected: bool = True,
    ) -> str:
        ssid = shlex.quote(self.ssid)
        password = shlex.quote(self.password)
        disconnected_check = (
            """if nmcli --terse --escape no --fields TYPE connection show --active | grep -Eq '^(802-11-wireless|wifi)$'; then
    echo 'Wi-Fi client connected before the installer UI supplied credentials' >&2
    exit 1
fi"""
            if require_client_disconnected
            else ": # The installed profile may reconnect as soon as the AP appears."
        )
        client_policy = (
            "must-start-disconnected"
            if require_client_disconnected
            else "automatic-reconnect-allowed"
        )
        # Keep the first line secret-free: SerialConsole includes it in an
        # exception if the guest command fails. stty echo is already disabled.
        return f"""set -euo pipefail
trap 'rc=$?; printf "wifi-lab-step-failed line=%s rc=%s\\n" "$LINENO" "$rc" >&2; exit "$rc"' ERR
ssid={ssid}
wifi_password={password}
gateway={shlex.quote(WIFI_LAB_GATEWAY)}
if [ -d /sys/module/mac80211_hwsim ]; then
    test "$(find /sys/class/ieee80211 -mindepth 1 -maxdepth 1 | wc -l)" -eq 2
else
    modprobe mac80211_hwsim radios=2
fi
udevadm settle
mapfile -t phys < <(find /sys/class/ieee80211 -mindepth 1 -maxdepth 1 -printf '%f\\n' | sort -V)
test "${{#phys[@]}}" -eq 2
client_device=$(find "/sys/class/ieee80211/${{phys[0]}}/device/net" -mindepth 1 -maxdepth 1 -printf '%f\\n' | sort | head -n1)
ap_device=$(find "/sys/class/ieee80211/${{phys[1]}}/device/net" -mindepth 1 -maxdepth 1 -printf '%f\\n' | sort | head -n1)
test -n "$client_device"
test -n "$ap_device"
test "$client_device" != "$ap_device"
nmcli device set "$ap_device" managed no
install -d -m 0700 /run/anduinos-wifi-lab /run/anduinos-wifi-lab/control
{{
    printf '%s\\n' \
        'ctrl_interface=/run/anduinos-wifi-lab/control' \
        'ap_scan=2' \
        'network={{'
    printf '    ssid="%s"\\n' "$ssid"
    printf '%s\\n' \
        '    mode=2' \
        '    frequency=2412' \
        '    key_mgmt=WPA-PSK' \
        '    proto=RSN' \
        '    pairwise=CCMP' \
        '    group=CCMP'
    printf '    psk="%s"\\n' "$wifi_password"
    printf '%s\\n' '}}'
}} > /run/anduinos-wifi-lab/ap.conf
chmod 0600 /run/anduinos-wifi-lab/ap.conf
ip link set "$ap_device" up
wpa_supplicant -B -D nl80211 -i "$ap_device" \
    -c /run/anduinos-wifi-lab/ap.conf \
    -P /run/anduinos-wifi-lab/wpa.pid \
    -f /run/anduinos-wifi-lab/wpa.log
ip address add "$gateway/24" dev "$ap_device"
dnsmasq --interface="$ap_device" --bind-interfaces --port=0 \
    --dhcp-range=10.77.0.10,10.77.0.99,255.255.255.0,1h \
    --dhcp-option=3 --dhcp-option=6 \
    --pid-file=/run/anduinos-wifi-lab/dnsmasq.pid \
    --log-facility=/run/anduinos-wifi-lab/dnsmasq.log
nmcli radio wifi on
nmcli device set "$client_device" managed yes
visible=no
for _attempt in $(seq 1 30); do
    nmcli device wifi rescan ifname "$client_device" >/dev/null 2>&1 || true
    if nmcli --terse --escape no --fields SSID device wifi list ifname "$client_device" | grep -Fx "$ssid" >/dev/null; then
        visible=yes
        break
    fi
    sleep 1
done
test "$visible" = yes
bssid=$(iw dev "$ap_device" info | awk '$1 == "addr" {{ print toupper($2); exit }}')
test -n "$bssid"
{disconnected_check}
ethernet_carrier=down
while IFS=: read -r device type _state; do
    [ "$type" = ethernet ] || continue
    if [ "$(cat "/sys/class/net/$device/carrier" 2>/dev/null || printf 0)" != 0 ]; then
        ethernet_carrier=up
    fi
done < <(nmcli --terse --escape no --fields DEVICE,TYPE,STATE device status)
test "$ethernet_carrier" = down
CLIENT_DEVICE="$client_device" AP_DEVICE="$ap_device" SSID="$ssid" BSSID="$bssid" CLIENT_POLICY={shlex.quote(client_policy)} \
python3 - <<'PY'
import json
import os
print("{_LAB_PREFIX}" + json.dumps({{
    "schema_version": 1,
    "client_device": os.environ["CLIENT_DEVICE"],
    "ap_device": os.environ["AP_DEVICE"],
    "ssid": os.environ["SSID"],
    "bssid": os.environ["BSSID"],
    "security": "WPA2",
    "visible": True,
    "ethernet_carrier": "down",
    "client_policy": os.environ["CLIENT_POLICY"],
}}, sort_keys=True))
PY
"""


def _live_profile_script(ssid: str, client_device: str) -> str:
    return f"""set -euo pipefail
expected_ssid={shlex.quote(ssid)}
client_device={shlex.quote(client_device)}
uuid=$(nmcli --terse --escape no --fields UUID,TYPE,DEVICE connection show --active | awk -F: -v device="$client_device" '$2 == "802-11-wireless" && $3 == device {{ print tolower($1) }}')
test -n "$uuid"
test "$(printf '%s\\n' "$uuid" | wc -l)" -eq 1
linked_ssid=$(iw dev "$client_device" link | sed -n 's/^\\s*SSID: //p')
test "$linked_ssid" = "$expected_ssid"
profile="/etc/netplan/90-NM-$uuid.yaml"
test -f "$profile"
test ! -L "$profile"
mode=$(stat -c '%a' "$profile")
uid=$(stat -c '%u' "$profile")
gid=$(stat -c '%g' "$profile")
test "$mode" = 600
test "$uid" = 0
test "$gid" = 0
UUID="$uuid" SSID="$linked_ssid" DEVICE="$client_device" MODE="$mode" UID_VALUE="$uid" GID_VALUE="$gid" \
python3 - <<'PY'
import json
import os
print("{_PROFILE_PREFIX}" + json.dumps({{
    "schema_version": 1,
    "uuid": os.environ["UUID"],
    "ssid": os.environ["SSID"],
    "device": os.environ["DEVICE"],
    "active": True,
    "profile_regular": True,
    "profile_symlink": False,
    "profile_uid": int(os.environ["UID_VALUE"]),
    "profile_gid": int(os.environ["GID_VALUE"]),
    "profile_mode": "0" + os.environ["MODE"],
}}, sort_keys=True))
PY
"""


def _installed_reconnect_script(ssid: str, uuid: str) -> str:
    return f"""set -euo pipefail
EXPECTED_SSID={shlex.quote(ssid)} EXPECTED_UUID={shlex.quote(uuid)} GATEWAY={shlex.quote(WIFI_LAB_GATEWAY)} \
python3 - <<'PY'
import glob
import json
import os
import re
import stat
import subprocess
import time

expected_ssid = os.environ["EXPECTED_SSID"]
expected_uuid = os.environ["EXPECTED_UUID"]
gateway = os.environ["GATEWAY"]

def run(*command, check=True):
    return subprocess.run(
        command,
        check=check,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=30,
    )

active = None
address = None
deadline = time.monotonic() + 90
while time.monotonic() < deadline:
    rows = run(
        "nmcli", "--terse", "--escape", "no", "--fields",
        "UUID,TYPE,DEVICE", "connection", "show", "--active",
    ).stdout.splitlines()
    matches = []
    for row in rows:
        fields = row.split(":")
        if len(fields) == 3 and fields[1] in ("802-11-wireless", "wifi"):
            matches.append((fields[0].lower(), fields[2]))
    if len(matches) == 1:
        candidate_uuid, candidate_device = matches[0]
        state = run(
            "nmcli", "--get-values", "GENERAL.STATE", "device", "show",
            candidate_device,
        ).stdout.strip()
        ipv4 = run(
            "ip", "-4", "-o", "address", "show", "dev", candidate_device,
        ).stdout
        candidate_address = re.search(
            r"\\binet (10\\.77\\.0\\.[0-9]+/[0-9]+)\\b", ipv4
        )
        if state.startswith("100") and candidate_address is not None:
            active = (candidate_uuid, candidate_device)
            address = candidate_address
            break
    time.sleep(1)
if active is None:
    raise SystemExit("installed NetworkManager did not reconnect to Wi-Fi")
active_uuid, device = active
if active_uuid != expected_uuid:
    raise SystemExit("installed Wi-Fi UUID differs from the Live profile")

link = run("iw", "dev", device, "link").stdout
match = re.search(r"^\\s*SSID: (.+)$", link, re.MULTILINE)
if match is None or match.group(1) != expected_ssid:
    raise SystemExit("installed Wi-Fi associated with the wrong SSID")

if address is None:
    raise SystemExit("installed Wi-Fi did not complete local DHCP")

ethernet_carrier = "down"
devices = run(
    "nmcli", "--terse", "--escape", "no", "--fields",
    "DEVICE,TYPE,STATE", "device", "status",
).stdout.splitlines()
for row in devices:
    fields = row.split(":", 2)
    if len(fields) != 3 or fields[1] != "ethernet":
        continue
    carrier_path = f"/sys/class/net/{{fields[0]}}/carrier"
    try:
        carrier = open(carrier_path, encoding="ascii").read().strip()
    except OSError:
        carrier = "0"
    if carrier != "0" or fields[2].startswith("connected"):
        ethernet_carrier = "up"
if ethernet_carrier != "down":
    raise SystemExit("installed target used Ethernet instead of migrated Wi-Fi")

run("ping", "-c", "2", "-W", "2", gateway)
profiles = glob.glob("/etc/netplan/90-NM-*.yaml")
expected_profile = f"/etc/netplan/90-NM-{{expected_uuid}}.yaml"
if profiles != [expected_profile]:
    raise SystemExit("installed target did not retain exactly the expected Netplan profile")
info = os.lstat(expected_profile)
if (
    not stat.S_ISREG(info.st_mode)
    or os.path.islink(expected_profile)
    or info.st_uid != 0
    or info.st_gid != 0
    or stat.S_IMODE(info.st_mode) != 0o600
):
    raise SystemExit("installed Wi-Fi Netplan profile metadata is unsafe")
run("netplan", "generate", "--mapping", f"NM-{{expected_uuid}}")

print("{_RECONNECT_PREFIX}" + json.dumps({{
    "schema_version": 1,
    "auto_reconnected": True,
    "ssid": expected_ssid,
    "uuid": active_uuid,
    "device": device,
    "ipv4": address.group(1),
    "gateway_reachable": True,
    "ethernet_carrier": ethernet_carrier,
    "profile_path": expected_profile,
    "profile_regular": True,
    "profile_symlink": False,
    "profile_uid": info.st_uid,
    "profile_gid": info.st_gid,
    "profile_mode": "0600",
    "netplan_mapping": "valid",
}}, sort_keys=True))
PY
"""


def validate_reconnect_evidence(
    payload: object,
    *,
    expected_ssid: str,
    expected_uuid: str,
) -> None:
    """Strict host-side oracle, kept pure for fault-injection tests."""

    expected_keys = {
        "schema_version",
        "auto_reconnected",
        "ssid",
        "uuid",
        "device",
        "ipv4",
        "gateway_reachable",
        "ethernet_carrier",
        "profile_path",
        "profile_regular",
        "profile_symlink",
        "profile_uid",
        "profile_gid",
        "profile_mode",
        "netplan_mapping",
    }
    if not isinstance(payload, dict) or set(payload) != expected_keys:
        raise TestFailure("Installed Wi-Fi reconnect evidence has an invalid shape")
    uuid = payload["uuid"]
    device = payload["device"]
    if (
        payload["schema_version"] != 1
        or payload["auto_reconnected"] is not True
        or payload["ssid"] != expected_ssid
        or uuid != expected_uuid
        or not isinstance(uuid, str)
        or _UUID.fullmatch(uuid) is None
        or not isinstance(device, str)
        or re.fullmatch(r"[A-Za-z0-9_.-]+", device) is None
        or not isinstance(payload["ipv4"], str)
        or re.fullmatch(r"10\.77\.0\.(?:[1-9]|[1-9][0-9]|1[0-9]{2}|2[0-4][0-9]|25[0-4])/[0-9]+", payload["ipv4"])
        is None
        or payload["gateway_reachable"] is not True
        or payload["ethernet_carrier"] != "down"
        or payload["profile_path"] != f"/etc/netplan/90-NM-{uuid}.yaml"
        or payload["profile_regular"] is not True
        or payload["profile_symlink"] is not False
        or payload["profile_uid"] != 0
        or payload["profile_gid"] != 0
        or payload["profile_mode"] != "0600"
        or payload["netplan_mapping"] != "valid"
    ):
        raise TestFailure("Installed target did not prove safe automatic Wi-Fi reconnect")


def assert_secret_absent(root: Path, secret: str) -> None:
    """Reject a Wi-Fi PSK copied into any durable test artifact."""

    if not secret:
        raise TestFailure("Wi-Fi lab secret must not be empty")
    needle = secret.encode("utf-8")
    for path in root.rglob("*"):
        try:
            info = path.lstat()
        except OSError:
            continue
        if not stat.S_ISREG(info.st_mode):
            continue
        overlap = b""
        try:
            with path.open("rb") as stream:
                while chunk := stream.read(1024 * 1024):
                    sample = overlap + chunk
                    if needle in sample:
                        raise TestFailure(
                            "Wi-Fi credential leaked into durable test artifact: "
                            f"{path.relative_to(root)}"
                        )
                    overlap_size = len(needle) - 1
                    overlap = sample[-overlap_size:] if overlap_size else b""
        except OSError as error:
            raise TestFailure(f"Cannot audit Wi-Fi artifacts for secrets: {error}") from error


def _extract_json(output: str, prefix: str) -> dict[str, object]:
    matches = [
        line[len(prefix) :]
        for line in output.splitlines()
        if line.startswith(prefix)
    ]
    if len(matches) != 1:
        raise TestFailure(f"Guest did not return exactly one {prefix.rstrip('=')} record")
    try:
        payload = json.loads(matches[0])
    except json.JSONDecodeError as error:
        raise TestFailure("Guest returned malformed Wi-Fi JSON evidence") from error
    if not isinstance(payload, dict):
        raise TestFailure("Guest Wi-Fi JSON evidence must be an object")
    return payload
