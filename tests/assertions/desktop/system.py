"""System, network, public-catalog, Rime, and rollback evidence oracles."""

import hashlib
import json
import re
import shlex
from pathlib import Path

from framework.errors import TestFailure
from .catalog import *  # noqa: F403


def _validate_search_provider_preflight(output: str, returncode: int) -> None:
    """Reject a Software provider which crashed and merely restarted."""

    if returncode != 0:
        raise TestFailure(
            "GNOME Software search provider did not reach a stable session state:\n"
            + output[-8000:]
        )

    expected_packages = {
        "gnome-software",
        "gnome-software-plugin-deb",
        "packagekit",
        "libpackagekit-glib2-18",
    }
    versions = {
        match.group("package"): match.group("version")
        for match in re.finditer(
            r"^package=(?P<package>[^ ]+) version=(?P<version>[^ ]+)$",
            output,
            re.MULTILINE,
        )
    }
    if set(versions) != expected_packages or any(
        version == "missing" for version in versions.values()
    ):
        raise TestFailure(
            "GNOME Software preflight did not record every installed package version"
        )

    before = re.search(
        r"^before_pid=(?P<pid>[0-9]+) before_restarts=(?P<restarts>[0-9]+) "
        r"before_active=(?P<active>[^ ]+)$",
        output,
        re.MULTILINE,
    )
    after = re.search(
        r"^after_pid=(?P<pid>[0-9]+) after_restarts=(?P<restarts>[0-9]+) "
        r"after_active=(?P<active>[^ ]+)$",
        output,
        re.MULTILINE,
    )
    ready = re.search(
        r"^search-provider=ready pid=(?P<pid>[0-9]+) "
        r"restarts=(?P<restarts>[0-9]+)$",
        output,
        re.MULTILINE,
    )
    if before is None or after is None or ready is None:
        raise TestFailure(
            "GNOME Software preflight omitted its process-lifecycle evidence"
        )

    before_pid = int(before.group("pid"))
    before_restarts = int(before.group("restarts"))
    after_pid = int(after.group("pid"))
    after_restarts = int(after.group("restarts"))
    if before_restarts != 0 or after_restarts != 0:
        raise TestFailure(
            "GNOME Software crashed and restarted before the feature action"
        )
    if after.group("active") != "active" or after_pid == 0:
        raise TestFailure("GNOME Software search provider is not active")
    if before_pid != 0 and before_pid != after_pid:
        raise TestFailure(
            "GNOME Software process changed during search-provider preflight"
        )
    if int(ready.group("pid")) != after_pid or int(ready.group("restarts")) != 0:
        raise TestFailure(
            "GNOME Software ready marker contradicts its lifecycle evidence"
        )


def _validate_local_search_provider_isolation_configuration(
    output: str,
    returncode: int,
) -> None:
    """Require the exact Software provider to be disabled before login."""

    if returncode != 0:
        raise TestFailure(
            "Could not configure local-search provider isolation before login:\n"
            + output[-4000:]
        )
    if f"provider={_SOFTWARE_SEARCH_PROVIDER_ID}" not in output:
        raise TestFailure("Local-search isolation resolved an unexpected provider")
    configured = re.search(r"^configured=(?P<value>.+)$", output, re.MULTILINE)
    if configured is None or _SOFTWARE_SEARCH_PROVIDER_ID not in configured.group(
        "value"
    ):
        raise TestFailure("GNOME Software was not disabled for local ArcMenu search")


def _validate_local_search_provider_runtime_isolation(
    output: str,
    returncode: int,
) -> None:
    """Require an inactive runtime mask before a local-search action."""

    if returncode != 0:
        raise TestFailure(
            "Could not enforce local-search provider isolation:\n" + output[-4000:]
        )
    configured = re.search(r"^configured=(?P<value>.+)$", output, re.MULTILINE)
    after = re.search(
        r"^after_load=(?P<load>[^ ]+) after_state=(?P<state>[^ ]+) "
        r"after_pid=(?P<pid>[0-9]+)$",
        output,
        re.MULTILINE,
    )
    if configured is None or _SOFTWARE_SEARCH_PROVIDER_ID not in configured.group(
        "value"
    ):
        raise TestFailure("Local ArcMenu search lost its Software-provider isolation")
    if (
        after is None
        or after.group("load") != "masked"
        or after.group("state") != "inactive"
        or int(after.group("pid")) != 0
    ):
        raise TestFailure("GNOME Software was not masked for local ArcMenu search")


def _validate_local_search_provider_post_action_isolation(
    output: str,
    returncode: int,
) -> None:
    """Require Software to remain masked and inactive after the action."""

    if returncode != 0:
        raise TestFailure(
            "Could not verify local-search provider isolation:\n" + output[-4000:]
        )
    configured = re.search(r"^configured=(?P<value>.+)$", output, re.MULTILINE)
    state = re.search(
        r"^load=(?P<load>[^ ]+) state=(?P<state>[^ ]+) pid=(?P<pid>[0-9]+)$",
        output,
        re.MULTILINE,
    )
    if configured is None or _SOFTWARE_SEARCH_PROVIDER_ID not in configured.group(
        "value"
    ):
        raise TestFailure("Local ArcMenu search lost its Software-provider isolation")
    if (
        state is None
        or state.group("load") != "masked"
        or state.group("state") != "inactive"
        or int(state.group("pid")) != 0
    ):
        raise TestFailure("Local ArcMenu search activated GNOME Software")


def _last_value(output: str, key: str) -> str:
    prefix = key + "="
    values = [line[len(prefix) :] for line in output.splitlines() if line.startswith(prefix)]
    if not values or not values[-1]:
        raise TestFailure(f"Missing {key!r} in feature precondition evidence")
    return values[-1]


def _safe_failure_class(
    output: str,
    key: str,
    allowed: set[str],
) -> str:
    """Return a declared failure class without hiding malformed evidence."""

    try:
        classification = _last_value(output, key)
    except TestFailure:
        return "product-regression"
    if classification not in allowed:
        return "product-regression"
    return classification


def _graphical_vt_probe_command(
    username: str,
    *,
    wait_for: int | None = None,
) -> str:
    """Render a guest probe which binds the active VT to the Wayland session."""

    if wait_for is not None and not 1 <= wait_for <= 12:
        raise ValueError("A graphical VT must be within 1..12")
    wait = ""
    if wait_for is not None:
        wait = f"""
deadline=$((SECONDS + 30))
while test "$(active_vt 2>/dev/null || true)" != {wait_for}; do
    if (( SECONDS >= deadline )); then
        printf 'restore-timeout-vt=%s\\n' "$(active_vt 2>/dev/null || true)"
        exit 70
    fi
    sleep 0.25
done
"""
    user = shlex.quote(username)
    return f"""set -eu
active_vt() {{
    name=$(cat /sys/class/tty/tty0/active)
    case "$name" in
        tty[1-9]|tty1[0-2]) printf '%s\\n' "$name" | sed 's/^tty//' ;;
        *) printf 'unexpected active VT: %s\\n' "$name" >&2; return 1 ;;
    esac
}}
{wait}active=$(active_vt)
session=$(loginctl show-user {user} -p Display --value)
test -n "$session"
session_vt=$(loginctl show-session "$session" -p VTNr --value)
session_type=$(loginctl show-session "$session" -p Type --value)
session_active=$(loginctl show-session "$session" -p Active --value)
target=$(systemctl is-active graphical.target)
gdm=$(systemctl is-active gdm.service)
printf 'active-vt=%s\\n' "$active"
printf 'graphical-session=%s\\n' "$session"
printf 'graphical-session-vt=%s\\n' "$session_vt"
printf 'graphical-session-type=%s\\n' "$session_type"
printf 'graphical-session-active=%s\\n' "$session_active"
printf 'graphical-target=%s\\n' "$target"
printf 'gdm-service=%s\\n' "$gdm"
test "$active" = "$session_vt"
test "$session_type" = wayland
test "$session_active" = yes
test "$target" = active
test "$gdm" = active
"""


def _tty6_probe_command() -> str:
    """Render a bounded probe of the character cells actually shown on tty6."""

    return r"""set -eu
active_vt() {
    name=$(cat /sys/class/tty/tty0/active)
    case "$name" in
        tty[1-9]|tty1[0-2]) printf '%s\n' "$name" | sed 's/^tty//' ;;
        *) printf 'unexpected active VT: %s\n' "$name" >&2; return 1 ;;
    esac
}
deadline=$((SECONDS + 30))
while :; do
    active=$(active_vt 2>/dev/null || true)
    if test "$active" = 6 && test -r /dev/vcs6 && \
       python3 -c "from pathlib import Path; raise SystemExit(0 if b'AnduinOS' in Path('/dev/vcs6').read_bytes() else 1)"; then
        break
    fi
    if (( SECONDS >= deadline )); then
        break
    fi
    sleep 0.25
done
active=$(active_vt 2>/dev/null || true)
printf 'active-vt=%s\n' "$active"
printf 'vcs-device=/dev/vcs6\n'
python3 - <<'PY'
import hashlib
import json
from pathlib import Path

raw = Path('/dev/vcs6').read_bytes()
text = raw.decode('ascii', errors='replace').replace('\x00', ' ')
print(f'vcs-bytes={len(raw)}')
print(f'vcs-sha256={hashlib.sha256(raw).hexdigest()}')
print('vcs-text-json=' + json.dumps(text, ensure_ascii=True))
if 'AnduinOS' not in text:
    raise SystemExit(71)
if 'ubuntu' in text.casefold():
    raise SystemExit(72)
PY
test "$active" = 6
"""


def _cpu_z_download_command() -> str:
    """Render the pinned public CPU-Z download and file-contract probe."""

    archive = shlex.quote(_CPU_Z_ARCHIVE)
    member = shlex.quote(_CPU_Z_MEMBER)
    url = shlex.quote(_CPU_Z_URL)
    archive_sha = shlex.quote(_CPU_Z_ARCHIVE_SHA256)
    member_sha = shlex.quote(_CPU_Z_MEMBER_SHA256)
    handler = shlex.quote(_CPU_Z_HANDLER)
    return f"""set -euo pipefail
command -v curl
command -v unzip
command -v exe-thumbnailer
command -v xdg-mime
printf 'cpu-z-stage=preflight\n'
if flatpak info com.usebottles.bottles >/dev/null 2>&1; then
    printf 'bottles=installed\n'
    exit 81
fi
downloads=$HOME/Downloads
install -d -m 0755 "$downloads"
archive="$downloads"/{archive}
member="$downloads"/{member}
printf 'cpu-z-archive-preexisting=%s\n' "$(test -e "$archive" && echo yes || echo no)"
printf 'cpu-z-member-preexisting=%s\n' "$(test -e "$member" && echo yes || echo no)"
test ! -e "$archive" || exit 82
test ! -e "$member" || exit 83
printf 'cpu-z-stage=download\n'
curl --fail --location --silent --show-error --retry 3 \
    --proto '=https' --tlsv1.2 --output "$archive" \
    --write-out 'cpu-z-http-code=%{{http_code}}\n' {url}
archive_digest=$(sha256sum "$archive" | awk '{{print $1}}')
printf 'cpu-z-archive-sha256=%s\n' "$archive_digest"
test "$archive_digest" = {archive_sha} || exit 84
printf 'cpu-z-stage=extract\n'
unzip -p "$archive" {member} > "$member"
chmod 0644 "$archive" "$member"
member_digest=$(sha256sum "$member" | awk '{{print $1}}')
member_size=$(stat -c %s "$member")
printf 'cpu-z-member-sha256=%s\n' "$member_digest"
printf 'cpu-z-member-size=%s\n' "$member_size"
test "$member_digest" = {member_sha} || exit 85
test "$member_size" -eq {_CPU_Z_MEMBER_SIZE} || exit 86
test "$(dd if="$member" bs=1 count=2 status=none)" = MZ || exit 87
printf 'cpu-z-stage=mime-dispatch\n'
mime_type=$(xdg-mime query filetype "$member")
handler_name=$(xdg-mime query default "$mime_type")
printf 'cpu-z-mime=%s\n' "$mime_type"
printf 'cpu-z-handler=%s\n' "$handler_name"
case "$mime_type" in
    application/vnd.microsoft.portable-executable|application/x-msdownload) ;;
    *) exit 88 ;;
esac
test "$handler_name" = {handler} || exit 89
printf 'cpu-z-version=%s\n' {_CPU_Z_VERSION!r}
printf 'cpu-z-url=%s\n' {url}
printf 'cpu-z-archive=%s\n' {archive}
printf 'cpu-z-member=%s\n' {member}
printf 'bottles=absent\n'
printf 'public-cpu-z=downloaded-and-verified\n'
"""


def _spotify_public_catalog_command() -> str:
    """Render the public Flathub refresh and exact Spotify catalog probe."""

    remote = shlex.quote(_SPOTIFY_REMOTE)
    remote_url = shlex.quote(_SPOTIFY_REMOTE_URL)
    app_id = shlex.quote(_SPOTIFY_APP_ID)
    arch = shlex.quote(_SPOTIFY_ARCH)
    expected_ref = shlex.quote(_SPOTIFY_REF)
    return f"""set -uo pipefail
export LC_ALL=C
fail_spotify_public() {{
    printf 'spotify-public-failure-reason=%s\n' "$2"
    printf 'spotify-public-failure-class=%s\n' "$1"
    exit "$3"
}}
printf 'spotify-public-stage=preflight\n'
command -v flatpak >/dev/null 2>&1 || \
    fail_spotify_public product-regression flatpak-missing 81
printf 'flatpak-version=%s\n' "$(flatpak --version)"
remotes=$(flatpak remotes --system --show-disabled --columns=name,url,options 2>&1) || {{
    printf 'spotify-public-remotes-error=%s\n' "$remotes"
    fail_spotify_public product-regression remote-list-failed 82
}}
printf 'spotify-public-remotes=%s\n' "$remotes"
remote_count=$(printf '%s\n' "$remotes" | awk -F '\t' '$1 == "flathub" {{ count++ }} END {{ print count + 0 }}')
observed_url=$(printf '%s\n' "$remotes" | awk -F '\t' '$1 == "flathub" {{ print $2 }}')
printf 'spotify-public-remote-count=%s\n' "$remote_count"
printf 'spotify-public-remote-url=%s\n' "$observed_url"
test "$remote_count" -eq 1 || \
    fail_spotify_public product-regression flathub-remote-count 83
test "$observed_url" = {remote_url} || \
    fail_spotify_public product-regression flathub-remote-url 84
printf 'spotify-public-stage=appstream-refresh\n'
if ! timeout --signal=TERM 600 flatpak update --appstream --system \
    --noninteractive {remote}; then
    fail_spotify_public external-catalog appstream-refresh-failed 85
fi
printf 'spotify-public-appstream-refresh=passed\n'
printf 'spotify-public-stage=remote-resolution\n'
if ! spotify_ref=$(timeout --signal=TERM 180 flatpak remote-info --system \
    --arch={arch} --show-ref {remote} {app_id} 2>&1); then
    printf 'spotify-public-remote-info-error=%s\n' "$spotify_ref"
    fail_spotify_public external-catalog spotify-ref-unavailable 86
fi
if ! spotify_commit=$(timeout --signal=TERM 180 flatpak remote-info --system \
    --arch={arch} --show-commit {remote} {app_id} 2>&1); then
    printf 'spotify-public-remote-info-error=%s\n' "$spotify_commit"
    fail_spotify_public external-catalog spotify-commit-unavailable 87
fi
printf 'spotify-public-ref=%s\n' "$spotify_ref"
printf 'spotify-public-commit=%s\n' "$spotify_commit"
test "$spotify_ref" = {expected_ref} || \
    fail_spotify_public external-catalog spotify-ref-mismatch 88
printf 'spotify-public-stage=cached-appstream-contract\n'
cached_entry=$(flatpak remote-ls --system --cached --app --arch={arch} \
    --columns=application,ref,arch,branch,origin {remote} 2>&1 | \
    awk -F '\t' '$1 == "com.spotify.Client" {{ print; count++ }} END {{ if (count != 1) exit 1 }}') || {{
    printf 'spotify-public-cached-error=%s\n' "$cached_entry"
    fail_spotify_public external-catalog spotify-cached-entry-missing 89
}}
printf 'spotify-public-cached-entry=%s\n' "$cached_entry"
printf 'spotify-public-app-id=%s\n' {app_id}
printf 'spotify-public-remote=%s\n' {remote}
printf 'spotify-public-arch=%s\n' {arch}
printf 'spotify-public-failure-class=none\n'
printf 'spotify-public-catalog=current-and-resolved\n'
"""


def _wechat_install_command() -> str:
    """Render the current native WeChat Flatpak installation contract."""

    remote = shlex.quote(_SPOTIFY_REMOTE)
    remote_url = shlex.quote(_SPOTIFY_REMOTE_URL)
    app_id = shlex.quote(_WECHAT_APP_ID)
    arch = shlex.quote(_WECHAT_ARCH)
    expected_ref = shlex.quote(_WECHAT_REF)
    return f"""set -uo pipefail
export LC_ALL=C
fail_wechat() {{
    printf 'wechat-failure-reason=%s\n' "$2"
    printf 'wechat-failure-class=%s\n' "$1"
    exit "$3"
}}
printf 'wechat-stage=preflight\n'
command -v flatpak >/dev/null 2>&1 || \
    fail_wechat product-regression flatpak-missing 81
if flatpak info --system {app_id} >/dev/null 2>&1; then
    printf 'wechat-preinstalled=yes\n'
    fail_wechat product-regression unexpected-preinstalled-app 82
fi
printf 'wechat-preinstalled=no\n'
remotes=$(flatpak remotes --system --show-disabled --columns=name,url 2>&1) || {{
    printf 'wechat-remotes-error=%s\n' "$remotes"
    fail_wechat product-regression remote-list-failed 83
}}
remote_count=$(printf '%s\n' "$remotes" | awk -F '\t' '$1 == "flathub" {{ count++ }} END {{ print count + 0 }}')
observed_url=$(printf '%s\n' "$remotes" | awk -F '\t' '$1 == "flathub" {{ print $2 }}')
printf 'wechat-remote-count=%s\n' "$remote_count"
printf 'wechat-remote-url=%s\n' "$observed_url"
test "$remote_count" -eq 1 || \
    fail_wechat product-regression flathub-remote-count 84
test "$observed_url" = {remote_url} || \
    fail_wechat product-regression flathub-remote-url 85
printf 'wechat-stage=catalog-refresh\n'
if ! timeout --signal=TERM 600 flatpak update --appstream --system \
    --noninteractive {remote}; then
    fail_wechat external-catalog appstream-refresh-failed 86
fi
if ! remote_ref=$(timeout --signal=TERM 180 flatpak remote-info --system \
    --arch={arch} --show-ref {remote} {app_id} 2>&1); then
    printf 'wechat-remote-info-error=%s\n' "$remote_ref"
    fail_wechat external-catalog wechat-ref-unavailable 87
fi
if ! remote_commit=$(timeout --signal=TERM 180 flatpak remote-info --system \
    --arch={arch} --show-commit {remote} {app_id} 2>&1); then
    printf 'wechat-remote-info-error=%s\n' "$remote_commit"
    fail_wechat external-catalog wechat-commit-unavailable 88
fi
printf 'wechat-remote-ref=%s\n' "$remote_ref"
printf 'wechat-remote-commit=%s\n' "$remote_commit"
test "$remote_ref" = {expected_ref} || \
    fail_wechat external-catalog wechat-ref-mismatch 89
printf 'wechat-stage=install\n'
if ! timeout --signal=TERM 1200 flatpak install --system --noninteractive \
    --assumeyes --arch={arch} {remote} {app_id}; then
    fail_wechat external-artifact flatpak-install-failed 90
fi
# Third-party bwrap/extra-data helpers may write diagnostics without a trailing
# newline. Start a fresh protocol record instead of weakening the key parser.
printf '\nwechat-install-command=passed\n'
installed_ref=$(flatpak info --system --arch={arch} --show-ref {app_id} 2>&1) || \
    fail_wechat product-regression installed-ref-missing 91
installed_commit=$(flatpak info --system --arch={arch} --show-commit {app_id} 2>&1) || \
    fail_wechat product-regression installed-commit-missing 92
installed_origin=$(flatpak info --system --arch={arch} --show-origin {app_id} 2>&1) || \
    fail_wechat product-regression installed-origin-missing 93
installed_location=$(flatpak info --system --arch={arch} --show-location {app_id} 2>&1) || \
    fail_wechat product-regression installed-location-missing 94
printf 'wechat-installed-ref=%s\n' "$installed_ref"
printf 'wechat-installed-commit=%s\n' "$installed_commit"
printf 'wechat-installed-origin=%s\n' "$installed_origin"
printf 'wechat-installed-location=%s\n' "$installed_location"
test "$installed_ref" = "$remote_ref" || \
    fail_wechat product-regression installed-ref-mismatch 95
test "$installed_commit" = "$remote_commit" || \
    fail_wechat product-regression installed-commit-mismatch 96
test "$installed_origin" = {remote} || \
    fail_wechat product-regression installed-origin-mismatch 97
desktop=/var/lib/flatpak/exports/share/applications/com.tencent.WeChat.desktop
desktop_resolved=$(readlink -f "$desktop" 2>/dev/null || true)
printf 'wechat-desktop=%s\n' "$desktop"
printf 'wechat-desktop-resolved=%s\n' "$desktop_resolved"
test -s "$desktop_resolved" || \
    fail_wechat product-regression desktop-export-missing 98
grep -Eq '^Exec=.*flatpak run .*com[.]tencent[.]WeChat' "$desktop_resolved" || \
    fail_wechat product-regression desktop-exec-invalid 99
printf 'wechat-app-id=%s\n' {app_id}
printf 'wechat-arch=%s\n' {arch}
printf 'wechat-failure-class=none\n'
printf 'wechat-install=current-and-verified\n'
"""


def _nextcloud_ppa_source_probe_command() -> str:
    """Verify the source file created by software-properties."""

    return r"""set -euo pipefail
codename=$(. /etc/os-release; printf '%s' "$VERSION_CODENAME")
test -n "$codename"
EXPECTED_CODENAME="$codename" python3 - <<'PY'
import os
import re
from pathlib import Path

needle = 'ppa.launchpadcontent.net/nextcloud-devs/client/ubuntu'
root = Path('/etc/apt/sources.list.d')
matches = [
    path
    for path in sorted(root.iterdir())
    if path.is_file() and needle in path.read_text(encoding='utf-8', errors='replace')
]
print(f'os-release-codename={os.environ["EXPECTED_CODENAME"]}')
print(f'source-count={len(matches)}')
if len(matches) != 1:
    raise SystemExit(81)
path = matches[0]
text = path.read_text(encoding='utf-8', errors='replace')
codename = os.environ['EXPECTED_CODENAME']
uri = re.search(r'(?m)^URIs:\s*(\S+)', text)
suite = re.search(r'(?m)^Suites:\s*(\S+)', text)
if uri is None or suite is None:
    legacy = re.search(
        r'(?m)^deb(?:\s+\[[^]]+\])?\s+(\S+)\s+(\S+)\s+',
        text,
    )
    if legacy is not None:
        uri = uri or legacy
        suite = suite or legacy
        uri_value = legacy.group(1)
        suite_value = legacy.group(2)
    else:
        uri_value = ''
        suite_value = ''
else:
    uri_value = uri.group(1)
    suite_value = suite.group(1)
signed = bool(
    re.search(r'(?mi)^Signed-By:', text)
    or re.search(r'(?i)\bsigned-by=', text)
)
print(f'source-path={path}')
print(f'source-uri={uri_value}')
print(f'source-suite={suite_value}')
print(f'source-signed-by={"yes" if signed else "no"}')
if (
    needle not in uri_value
    or suite_value != codename
    or not signed
):
    raise SystemExit(82)
PY
"""


def _validate_graphical_vt_evidence(
    output: str,
    returncode: int,
    *,
    expected_vt: int | None = None,
) -> int:
    if returncode != 0:
        raise TestFailure(
            "The graphical VT/session probe failed:\n" + output[-8000:]
        )
    try:
        active = int(_last_value(output, "active-vt"))
        session_vt = int(_last_value(output, "graphical-session-vt"))
    except ValueError as error:
        raise TestFailure("The graphical VT probe returned a non-numeric VT") from error
    if not 1 <= active <= 12 or session_vt != active:
        raise TestFailure(
            f"The active VT {active} does not own the graphical session VT {session_vt}"
        )
    if expected_vt is not None and active != expected_vt:
        raise TestFailure(
            f"The harness returned to tty{active}, expected tty{expected_vt}"
        )
    expected = {
        "graphical-session-type": "wayland",
        "graphical-session-active": "yes",
        "graphical-target": "active",
        "gdm-service": "active",
    }
    for key, value in expected.items():
        if _last_value(output, key) != value:
            raise TestFailure(f"The restored graphical contract lost {key}={value}")
    return active


def _validate_tty6_evidence(output: str, returncode: int) -> dict[str, object]:
    if returncode != 0:
        raise TestFailure(
            "tty6 did not display the AnduinOS login banner:\n" + output[-8000:]
        )
    if _last_value(output, "active-vt") != "6":
        raise TestFailure("Ctrl+Alt+F6 did not make tty6 active")
    if _last_value(output, "vcs-device") != "/dev/vcs6":
        raise TestFailure("The tty6 probe did not read the kernel VT screen buffer")
    try:
        size = int(_last_value(output, "vcs-bytes"))
        text = json.loads(_last_value(output, "vcs-text-json"))
    except (ValueError, json.JSONDecodeError) as error:
        raise TestFailure("tty6 returned malformed screen-buffer evidence") from error
    digest = _last_value(output, "vcs-sha256")
    if size <= 0 or re.fullmatch(r"[0-9a-f]{64}", digest) is None:
        raise TestFailure("tty6 returned an empty or unhashed screen buffer")
    if not isinstance(text, str) or "AnduinOS" not in text:
        raise TestFailure("The visible tty6 character cells did not contain AnduinOS")
    if "ubuntu" in text.casefold():
        raise TestFailure("The visible tty6 character cells leaked Ubuntu branding")
    return {"active_vt": 6, "bytes": size, "sha256": digest, "text": text}


def _validate_nextcloud_ppa_evidence(
    output: str,
    returncode: int,
    username: str,
) -> dict[str, str]:
    if returncode != 0:
        raise TestFailure(
            "The public Nextcloud PPA command or source verification failed:\n"
            + output[-12000:]
        )
    expected = {
        "invoking-user": username,
        "command": "sudo add-apt-repository -y ppa:nextcloud-devs/client",
        "repository-command": "passed",
        "source-count": "1",
        "source-signed-by": "yes",
        "nextcloud-ppa-sudo-policy": "removed",
    }
    observed = {key: _last_value(output, key) for key in expected}
    for key, value in expected.items():
        if observed[key] != value:
            raise TestFailure(
                f"The Nextcloud PPA contract returned {key}={observed[key]!r}, "
                f"expected {value!r}"
            )
    codename = _last_value(output, "os-release-codename")
    suite = _last_value(output, "source-suite")
    if not re.fullmatch(r"[a-z][a-z0-9-]*", codename) or suite != codename:
        raise TestFailure(
            f"The PPA suite {suite!r} does not match VERSION_CODENAME={codename!r}"
        )
    source_path = _last_value(output, "source-path")
    if (
        not source_path.startswith("/etc/apt/sources.list.d/")
        or not source_path.endswith((".list", ".sources"))
    ):
        raise TestFailure("The PPA was not represented by a supported APT source file")
    source_uri = _last_value(output, "source-uri")
    needle = "ppa.launchpadcontent.net/nextcloud-devs/client/ubuntu"
    if needle not in source_uri:
        raise TestFailure("The installed APT source belongs to an unrelated PPA")
    return {
        **observed,
        "codename": codename,
        "source_path": source_path,
        "source_uri": source_uri,
    }


def _validate_spotify_public_catalog_evidence(
    output: str,
    returncode: int,
) -> dict[str, str]:
    """Accept only a freshly resolved exact Spotify ref from official Flathub."""

    if returncode != 0:
        try:
            classification = _last_value(
                output,
                "spotify-public-failure-class",
            )
            reason = _last_value(output, "spotify-public-failure-reason")
        except TestFailure as error:
            raise TestFailure(
                "The public Spotify catalog probe failed without a valid "
                f"classification (exit {returncode}):\n{output[-12000:]}"
            ) from error
        if classification not in {"external-catalog", "product-regression"}:
            raise TestFailure(
                "The public Spotify catalog probe returned an unknown failure "
                f"class {classification!r}"
            )
        raise TestFailure(
            f"public Spotify catalog failure ({classification}, {reason}, "
            f"exit {returncode}):\n{output[-12000:]}"
        )

    expected = {
        "spotify-public-remote-count": "1",
        "spotify-public-remote-url": _SPOTIFY_REMOTE_URL,
        "spotify-public-appstream-refresh": "passed",
        "spotify-public-ref": _SPOTIFY_REF,
        "spotify-public-app-id": _SPOTIFY_APP_ID,
        "spotify-public-remote": _SPOTIFY_REMOTE,
        "spotify-public-arch": _SPOTIFY_ARCH,
        "spotify-public-failure-class": "none",
        "spotify-public-catalog": "current-and-resolved",
    }
    observed = {key: _last_value(output, key) for key in expected}
    for key, value in expected.items():
        if observed[key] != value:
            raise TestFailure(
                f"The public Spotify contract returned {key}={observed[key]!r}, "
                f"expected {value!r}"
            )
    commit = _last_value(output, "spotify-public-commit")
    if re.fullmatch(r"[0-9a-f]{64}", commit) is None:
        raise TestFailure("The public Spotify ref did not expose a valid commit")
    cached_entry = _last_value(output, "spotify-public-cached-entry")
    expected_entry = "\t".join(
        (
            _SPOTIFY_APP_ID,
            _SPOTIFY_REF,
            _SPOTIFY_ARCH,
            "stable",
            _SPOTIFY_REMOTE,
        )
    )
    if cached_entry != expected_entry:
        raise TestFailure(
            "The refreshed local AppStream cache does not contain exactly the "
            "public Spotify stable ref"
        )
    version = _last_value(output, "flatpak-version")
    if not version.startswith("Flatpak "):
        raise TestFailure("The Spotify catalog probe did not identify Flatpak")
    return {
        **observed,
        "commit": commit,
        "cached_entry": cached_entry,
        "flatpak_version": version,
    }


def _validate_wechat_install_evidence(
    output: str,
    returncode: int,
) -> dict[str, str]:
    """Require the resolved current WeChat ref and its exported launcher."""

    if returncode != 0:
        classification = _safe_failure_class(
            output,
            "wechat-failure-class",
            {"external-catalog", "external-artifact", "product-regression"},
        )
        try:
            reason = _last_value(output, "wechat-failure-reason")
        except TestFailure:
            reason = "malformed-failure-evidence"
        raise TestFailure(
            f"WeChat installation failure ({classification}, {reason}, "
            f"exit {returncode}):\n{output[-16000:]}"
        )

    expected = {
        "wechat-preinstalled": "no",
        "wechat-remote-count": "1",
        "wechat-remote-url": _SPOTIFY_REMOTE_URL,
        "wechat-remote-ref": _WECHAT_REF,
        "wechat-install-command": "passed",
        "wechat-installed-ref": _WECHAT_REF,
        "wechat-installed-origin": _SPOTIFY_REMOTE,
        "wechat-desktop": (
            "/var/lib/flatpak/exports/share/applications/"
            "com.tencent.WeChat.desktop"
        ),
        "wechat-app-id": _WECHAT_APP_ID,
        "wechat-arch": _WECHAT_ARCH,
        "wechat-failure-class": "none",
        "wechat-install": "current-and-verified",
    }
    observed = {key: _last_value(output, key) for key in expected}
    for key, value in expected.items():
        if observed[key] != value:
            raise TestFailure(
                f"The WeChat install contract returned {key}={observed[key]!r}, "
                f"expected {value!r}"
            )
    remote_commit = _last_value(output, "wechat-remote-commit")
    installed_commit = _last_value(output, "wechat-installed-commit")
    if (
        re.fullmatch(r"[0-9a-f]{64}", remote_commit) is None
        or installed_commit != remote_commit
    ):
        raise TestFailure(
            "The installed WeChat deployment does not match the resolved public commit"
        )
    location = _last_value(output, "wechat-installed-location")
    resolved_desktop = _last_value(output, "wechat-desktop-resolved")
    if (
        not location.startswith("/var/lib/flatpak/app/com.tencent.WeChat/")
        or not resolved_desktop.startswith(location.rstrip("/") + "/")
        or not resolved_desktop.endswith("/export/share/applications/com.tencent.WeChat.desktop")
    ):
        raise TestFailure("WeChat's desktop export is outside its verified deployment")
    return {
        **observed,
        "commit": remote_commit,
        "location": location,
        "resolved_desktop": resolved_desktop,
    }


def _validate_cpu_z_download_evidence(
    output: str,
    returncode: int,
) -> dict[str, object]:
    if returncode != 0:
        raise TestFailure(
            "The pinned public CPU-Z download or file contract failed "
            f"with exit {returncode}:\n"
            + output[-12000:]
        )
    expected = {
        "cpu-z-http-code": "200",
        "cpu-z-archive-preexisting": "no",
        "cpu-z-member-preexisting": "no",
        "cpu-z-version": _CPU_Z_VERSION,
        "cpu-z-url": _CPU_Z_URL,
        "cpu-z-archive": _CPU_Z_ARCHIVE,
        "cpu-z-archive-sha256": _CPU_Z_ARCHIVE_SHA256,
        "cpu-z-member": _CPU_Z_MEMBER,
        "cpu-z-member-sha256": _CPU_Z_MEMBER_SHA256,
        "cpu-z-member-size": str(_CPU_Z_MEMBER_SIZE),
        "cpu-z-handler": _CPU_Z_HANDLER,
        "bottles": "absent",
        "public-cpu-z": "downloaded-and-verified",
    }
    observed = {key: _last_value(output, key) for key in expected}
    for key, value in expected.items():
        if observed[key] != value:
            raise TestFailure(
                f"The public CPU-Z contract returned {key}={observed[key]!r}, "
                f"expected {value!r}"
            )
    mime_type = _last_value(output, "cpu-z-mime")
    if mime_type not in _CPU_Z_MIMES:
        raise TestFailure(
            f"The official CPU-Z PE received unsupported MIME type {mime_type!r}"
        )
    return {
        **observed,
        "mime_type": mime_type,
        "member_size": int(observed["cpu-z-member-size"]),
    }


def _validate_distinct_boot_ids(before: str, after: str) -> None:
    if not before or not after or before == after:
        raise TestFailure("Ordinary reboot did not produce a distinct boot ID")


def _json_object(output: str) -> dict[str, object]:
    """Parse a CLI JSON object while rejecting ambiguous mixed output."""

    try:
        value = json.loads(output.strip())
    except json.JSONDecodeError as error:
        raise TestFailure(f"Snapshot CLI returned malformed JSON: {error}") from error
    if not isinstance(value, dict):
        raise TestFailure("Snapshot CLI did not return one JSON object")
    return value


def _validate_rime_evidence(path: Path, expected: str) -> None:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise TestFailure(f"Rime evidence is unavailable or malformed: {error}") from error
    if not isinstance(value, dict) or set(value) != {"expected", "observed", "exact"}:
        raise TestFailure("Rime evidence has an invalid shape")
    if (
        value["expected"] != expected
        or value["observed"] != expected
        or value["exact"] is not True
    ):
        raise TestFailure(
            f"Rime evidence does not prove exact committed text {expected!r}: {value!r}"
        )


def _validate_rollback_health(output: str) -> None:
    required = {
        "docker=absent",
        "root-sentinel=absent",
        "home-sentinel=present",
        "dpkg=ok",
        "apt=ok",
        "boot-artifacts=ok",
        "btrfs-default-subvolume=unchanged",
        "btrfs-staging-roots=absent",
        "recovery-grubenv=empty",
        "confirm-service=success",
        "recovery-pending=absent",
        "rollback-history=confirmed",
        "deployments-ready=target-and-fallback",
        "deployment-roots=verified",
        "active-root=selected-target",
        "snapshot-state=ok",
        "rollback-health=ok",
    }
    observed = {line.strip() for line in output.splitlines()}
    missing = sorted(required - observed)
    if missing:
        raise TestFailure(
            "Rollback evidence is missing required successful oracles: "
            + ", ".join(missing)
        )


__all__ = tuple(name for name in globals() if name.startswith("_"))
