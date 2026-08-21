# AnduinOS system acceptance architecture

This document defines the target architecture and backlog for growing the ISO
acceptance harness from installation coverage into reproducible whole-desktop
coverage. It is not an implementation-status report. Every planned product
requirement below has a stable check identifier, intended isolation boundary,
driver, oracle, evidence contract, and profile. A check is implemented only
after runtime code reachable from `make test` executes it against a guest and
retains authoritative evidence.

The machine-readable planning inventory is `coverage-plan.json`; unit tests
require its 65 identifiers to match this document exactly. Those shape tests
validate the roadmap, not the guest behavior. `README.md`, `matrix.json`, and
the runtime modules under `iso_test/` describe the currently executable gate.

The executable matrix currently contains eleven amd64 installation scenarios
and seven arm64 scenarios. They remain the authority for firmware, storage,
Secure Boot, network policy, SSH, and post-install boot. The desktop suites do
not duplicate those installations. They consume only target disks that have
already passed every installation assertion.

## Executable status

`feature-suites.json` is the runtime authority, separate from the 65-check
roadmap in `coverage-plan.json`. The implemented execution engine now promotes
a passed source installation atomically, opens it read-only, creates a fresh
qcow2 overlay and UEFI VARS copy per suite, supports multiple boots inside one
suite, reports `scenario -> suite -> check` in the TUI and JSON summary, and
removes overlays, temporary bases, and writable UEFI VARS on success, failure,
SIGTERM, or Ctrl+C. Lossless PNG frames and variable-store hashes preserve the
diagnostic evidence without retaining large raw framebuffer or firmware-state
copies.
The CLI runs inside a minimal crash supervisor: Linux parent-death signals
contain QEMU and display helpers, and the parent can reclaim the exact
supervisor-token workspace even when a native module terminates the worker
with SIGSEGV. The recovery path is exercised by a real signal fault-injection
test and preserves durable evidence while deleting only disposable boot state. A
fatal Python thread dump is written atomically to `worker-fault.log` inside the
run artifacts; successful workers leave no empty crash file behind.

Installation-level desktop dispatch uses independent `files.appimage-open`,
`files.exe-thumbnail-fixture`, and `files.exe-open-fixture` boundaries. Their
fixture preparation, MIME oracle, AT-SPI driver, Nautilus log, and evidence
directory are separate, so a broken native AppImage execution path cannot hide
a working or broken Windows PE preview or dispatch path. The local PE contains
a deterministic embedded icon: Nautilus must create a retrievable thumbnail
which passes the purple-background/white-chip pixel oracle before the separate
open check is allowed to prove EXE Runner dispatch.
AT-SPI identifies the selected Nautilus row but does not perform the final
activation. The host supplies a recorded SPICE double-click when semantic
bounds are usable, or recorded QMP keyboard input after observable Nautilus
focus. An accessibility action's boolean return is never a passing oracle.

The deterministic `release-gate` currently executes Rime input, exact UTF-8
editing and saving in GNOME Text Editor, the real green Swap Control dashboard,
content-validated image and video thumbnails, Loupe and Celluloid activation,
local-DEB dispatch to GNOME Software, an ordinary reboot, account/GDM lifecycle,
the live GTK/Qt/Firefox theme transition, the untouched post-login Overview
state, desktop shortcuts, shell shortcuts, localized default desktop icons,
desktop-background terminal launch, Start branding, and taskbar Pin/Remove
behavior. The `nightly-online` profile reruns those checks and additionally
executes `storage.btrfs-docker-rollback` and the public Spotify store lane.
Installing `docker.io` must not become a release gate until the configured APT
source is a fixed signed snapshot. The positive rollback lane is sourced from
the UEFI/Secure-Boot-disabled Btrfs scenario so the product's real one-shot EFI
recovery path is exercised; BIOS Secure Boot classification remains an
independent fail-closed compatibility contract rather than being silently
treated as a successful recovery run.
Its privileged oracle never treats the user-facing, metadata-redacted snapshot
status as recovery evidence: it validates the exact target/fallback records,
their real Btrfs UUIDs, the archived transaction, the active root's parent UUID,
and cleared pending/EFI one-shot state from the protected recovery store.
Every registered runtime check has a failure-injection unit oracle; a roadmap
entry is not treated as executable merely because it appears in this document.
The architecture tests additionally require all 57 deterministic release-gate
IDs, and all 62 non-platform roadmap IDs, to be reachable under the exact same
identifier from either an installation scenario or `feature-suites.json`.
Aliases and prose-only claims cannot satisfy that closure check.

## Design principles

1. Test observed behavior, not only package or configuration presence. A
   configuration assertion can be supporting evidence, but cannot replace the
   user-visible action it is meant to produce.
2. Keep installation dimensions separate from feature dimensions. Firmware,
   filesystem, network policy, and Secure Boot belong to `matrix.json`;
   desktop checks belong to feature suites.
3. Never mutate a verified installation base. Every stateful suite runs on a
   fresh qcow2 overlay and a fresh copy of UEFI VARS.
4. Navigate localized interfaces semantically through AT-SPI roles, states,
   actions, and relationships. Localized strings are assertions, not fragile
   selectors, unless the string itself is the requirement.
5. Do not use fixed sleeps as proof. Poll an observable state until a bounded
   deadline and retain the last observation on failure.
6. A product failure is not retried into a pass. Infrastructure startup may be
   retried before a check begins, but assertions and state-changing actions run
   exactly once per disposable overlay.
7. Release-gate tests do not depend on mutable public Internet services.
   Public stores, PPAs, and third-party downloads run in a separate nightly
   profile.
8. Test instrumentation is uploaded to `/run/anduinos-test` or mounted from a
   read-only fixture image. It must not be copied into the installed system.
9. Passwords, Wi-Fi PSKs, MOK secrets, and temporary account credentials must
   never appear in command lines, transcripts, screenshots, or manifests.
10. Missing a required release-gate capability is a preflight failure, not a
    skip. Optional platform-lab checks may report a capability-based skip.

## Execution graph

```text
ISO + architecture + framework revision
                  |
                  v
 installation matrix (11 amd64 / 7 arm64)
                  |
        all installation assertions pass
                  |
                  v
       immutable installed qcow2 base
          |          |          |
          v          v          v
       overlay    overlay    overlay       ...
       branding   shell      files
          |          |          |
          +----------+----------+
                     |
            structured evidence + JUnit + TUI
```

An installation base is promoted only after the installer completion page,
target reboot, package audit, filesystem assertions, Live cleanup, firmware
workflow, and scenario-specific assertions have all passed. A base identity is
the hash of:

- ISO SHA-256;
- architecture and installation scenario;
- firmware CODE and original VARS SHA-256;
- resolved test defaults that affect the installation;
- framework Git revision and guest-driver SHA-256.

The harness writes that identity beside the base and refuses stale or partial
bases. Promotion is atomic. Promoted bases are opened read-only and guarded by
a file lock while overlays exist.

Each feature suite creates an overlay equivalent to:

```bash
qemu-img create -f qcow2 -F qcow2 -b /absolute/base.qcow2 suite.qcow2
```

The backing path recorded in an artifact must be absolute. The base cannot be
deleted while dependent suites are running. A stateful suite such as account
creation, theme switching, Wine launch, or package installation gets its own
overlay; independent suites may run in parallel within host RAM and CPU limits.

Within one healthy overlay, a product assertion failure is recorded and later
declared checks continue by default. This prevents one defect from hiding
independent coverage. `--fail-fast` restores immediate termination. Protocol or
configuration failures and a stopped QEMU always terminate the suite because
subsequent observations would not be trustworthy.

## Three observation modes

The serial debug shell is excellent for controlled assertions, but changing a
kernel command line can perturb the exact boot sequence being observed. The
runner therefore needs three explicit modes:

- `passive`: boot without GRUB edits or guest uploads. Capture firmware,
  Plymouth, GDM, automatic login, and crash evidence from QMP/SPICE only.
- `controlled`: use the existing one-shot serial root shell, then upload the
  AT-SPI/session driver to `/run`. This is the normal desktop-test mode.
- `platform`: launch through the real host integration under test, such as
  GNOME Boxes/libvirt or a physical Wi-Fi runner, while retaining host-side
  video and guest-side assertions.

Checks that care about first boot may run a passive observation first, power
off, then boot the disposable overlay in controlled mode for supporting system
assertions. The passive observation is the behavioral oracle; the later
configuration read is supporting evidence only.

Controlled serial input has an additional ownership boundary. Firmware, GRUB,
Linux, and the debug shell share the same UART, so the harness must not send a
shell probe merely because the serial socket exists. It first waits passively
for a Linux kernel diagnostic, then separately for Bash's exact
`servicename=debug-shell.service` prompt marker. Only then may marker-framed
shell commands be written. A fault-injection test must prove that firmware,
GRUB, and the kernel-before-Bash transcript all receive zero bytes from the
harness. Installed-system instrumentation edits only the generated real
menuentries, is checked by `grub-script-check`, and carries a byte-for-byte
backup that each disposable overlay restores before any ordinary reboot.

## Suite and check model

The installation `Scenario` model must not grow dozens of feature booleans.
Add a separate suite registry whose declarative records reference small Python
check plugins:

```json
{
  "id": "installed-zh-shell",
  "source": "uefi-nosb-online-btrfs-ssh-toggle",
  "profile": "release-gate",
  "isolation": "overlay",
  "architectures": ["amd64", "arm64"],
  "capabilities": ["graphical", "atspi", "qmp-input"],
  "checks": [
    "shell.initial-overview-hidden",
    "shell.extension-policy",
    "shortcut.super-tab",
    "shortcut.alt-tab",
    "shortcut.super-i",
    "shortcut.super-u",
    "shortcut.super-shift-s"
  ]
}
```

JSON selects and parameterizes plugins; it does not become a programming
language. Complex behavior remains readable Python. The common interface is:

```python
class FeatureCheck:
    def prepare(self, context): ...
    def run(self, context): ...
    def collect(self, context): ...
    def cleanup(self, context): ...
```

Every check returns a structured result with its identifier, status, duration,
observations, and attachments. A check declares:

- required base or Live source;
- supported architectures;
- required capabilities and network policy;
- `passive`, `controlled`, or `platform` observation mode;
- whether it mutates the guest or requires a reboot;
- timeout and direct oracle;
- required evidence files;
- profiles in which failure is gating.

## Drivers and oracles

### Command and state driver

The serial channel runs root assertions. User-session commands are launched in
the actual logged-in user's systemd and D-Bus environment. Preferred state
interfaces are `gsettings`, `busctl`/GIO D-Bus, `loginctl`, `localectl`,
`timedatectl`, `systemctl`, `nmcli`, `gio`, `fc-match`, and package queries.

Serial command output and asynchronous kernel/systemd diagnostics occupy the
same byte stream. Binary evidence transfer is therefore framed rather than
treated as one unverified base64 line: every bounded frame contains its guest
offset and SHA-256, corrupt frames are retried independently, and the complete
file identity is checked before and after download. Only transport corruption
is retryable. Fatal kernel health, including death of the virtual input
controller used by QMP, immediately invalidates the suite instead of being
retried into a pass.

### AT-SPI driver

AT-SPI discovers applications, roles, accessible names, text, states, actions,
focus, and component bounds. It performs semantic actions when exposed. If a
GNOME Shell widget exposes no invokable action, the driver emits a semantic QMP
request tied to the focused accessible object, following the existing installer
checkbox handshake. Absolute screen coordinates are not acceptable selectors.

### QMP input and frame capture

QMP sends the real keyboard combinations and pointer events a user would send.
An assertion checks the resulting focus, window, dialog, file, session, or
screen state. QMP/SPICE frame capture covers firmware, Plymouth, GDM, Shell
chrome, cursor shape, and UI that does not expose a sufficient accessibility
tree.

### Visual oracle

Whole-screen pixel equality is too fragile across GPU backends and font
rasterizers. Visual checks use the smallest stable region and one of:

- alpha-aware template matching for an AnduinOS logo or icon;
- OCR only where AT-SPI cannot expose text, such as a Linux VT;
- dominant-color or color-ratio assertions for the Twemoji water pistol and
  Swap Control landing page;
- perceptual similarity with masks for clocks, network state, animation, and
  wallpaper areas;
- SPICE cursor-shape capture plus configured cursor-theme evidence.

Reference assets carry their source package version, expected scale, theme,
and resolution. A visual failure always retains the actual image, expected
image, mask, and highlighted difference.

### Journal guard

`journalctl -f has no errors` is represented as an action-scoped journal
contract, not a grep of the entire boot history:

1. Record the journal cursor immediately before a check.
2. Perform the user action.
3. Collect entries after that cursor from the system and user journals.
4. Fail on a new crash, core dump, segfault, failed unit, GNOME Shell
   `JS ERROR`, extension exception, unknown assertion failure, or unexpected
   priority 0-3 message owned by the exercised component.
5. Classify a known diagnostic as non-blocking only when its exact component,
   message, scenario, package-version glob, and bounded occurrence count all
   match, and an independent functional oracle for that component passes.
6. Keep known diagnostics visible in the result rather than deleting them from
   the evidence. A version change, count increase, or near-match expires the
   exception and restores the release failure automatically.

GNOME Shell 50's hidden-Dash null-icon diagnostic is one such narrowly scoped
exception: only its complete stack during `settings-about-branding`, once, is
known. The About-page identity and rendered-logo oracles still have to pass,
and any other Shell JavaScript error remains a release blocker.

The unfiltered slice and the filtered verdict are both evidence. A global boot
journal guard also covers the interval from kernel start through desktop idle.
The executable global policy lives in `journal-policy.json`; broad regex
allowlists and unversioned exceptions are invalid by design.

### Host integration drivers

- A SPICE display client resizes a VirtIO-GPU/QXL display and queries Mutter's
  DisplayConfig state in the guest.
- A GNOME Boxes platform runner creates and launches the VM through Boxes and
  libvirt, resizes the real Boxes window, and observes the same guest state.
- A virtual Wi-Fi provider uses `mac80211_hwsim` radios and `hostapd` to offer a
  WPA2 network with an ephemeral PSK. A physical-Wi-Fi runner repeats the
  workflow in the platform lab.
- A deterministic HTTP service exposes pinned APT/AppStream content and the
  local Firefox theme fixture. Public endpoints are used only by nightly
  checks.

## Test profiles

| Profile | Purpose | Network and determinism |
|---|---|---|
| `unit` | Framework parsing, drivers, oracles, and failure injection | No VM and no network |
| `install` | Existing firmware/storage/Secure Boot/SSH matrix | Pinned APT snapshot for online cases |
| `release-gate` | Stable installed-desktop behavior on disposable overlays | No mutable public services |
| `nightly-online` | Spotify store, public PPA, CPU-Z source, WeChat repository | Public network; failures alert but are classified separately |
| `platform-lab` | Actual GNOME Boxes, physical Wi-Fi, selected real hardware | Dedicated runners with declared capabilities |

The intended command surface is:

```bash
make test PROFILE=install
make test PROFILE=release-gate
make test PROFILE=nightly-online
make test PROFILE=platform-lab
make test SUITES='installed-zh-shell file-integration'
```

`platform-lab` is a reserved, fail-closed profile until a dedicated runner
registers executable GNOME Boxes, authenticated WeChat tray, and physical
Wi-Fi checks. Merely declaring those checks in `coverage-plan.json` must never
silently fall back to the ordinary installation matrix or report platform
coverage. Invoking the profile without such a runner is therefore a
configuration error.

Plain `make test` now selects `release-gate`. Use `PROFILE=install` for the
architecture's installation scenarios only. A selected case automatically runs only suites
whose declared base is that case; an explicitly selected suite without its
required case fails during preflight.

## Installation variants added by feature coverage

Most feature suites consume the existing UEFI/no-Secure-Boot, online, Btrfs,
Simplified-Chinese target. Two requirements genuinely change installation
inputs and therefore cannot be fabricated after installation:

1. **Automatic login.** Add `automatic_login` to the installation scenario
   model. Set it to true in one existing advanced-options scenario (prefer the
   SSH-enabled UEFI/no-Secure-Boot case) and false everywhere else. This covers
   both secure default and explicit opt-in without another installation.
2. **Passwordless sudo.** Add `passwordless_sudo` to the same advanced-options
   scenario and leave it false everywhere else. The UI driver must prove the
   default and selected summary, while the installed target must validate the
   exact root-owned sudoers policy with `visudo`, clear all sudo timestamps,
   and exercise `sudo -n` as the created non-root user. This covers both sides
   without adding an installation.
3. **Wi-Fi credential migration.** The amd64 matrix includes one
   UEFI/no-Secure-Boot Btrfs installation using a virtual WPA2 interface
   instead of Ethernet. It enters an ephemeral PSK once through the Live GNOME
   dialog, installs, recreates the same local-only AP after reboot without
   supplying credentials to the installed NetworkManager process, and proves
   automatic reconnection with the exact migrated UUID. This is the eleventh
   amd64 installation; it remains excluded from arm64 until reliable
   cross-architecture virtual Wi-Fi support is available.

GRUB regional propagation does not require 28 full installations. The ISO
contract statically validates all 28 generated locale/timezone pairs, then
boot-only tests exercise representative Latin (`en_GB`), CJK (`zh_CN`), RTL
(`ar_SA`), and non-Latin IME (`ja_JP`) entries. The installed Simplified
Chinese base proves that the selected locale and timezone survive installation.

## Feature suites and complete requirement mapping

The `Oracle` column describes the direct pass condition. Command/configuration
checks listed alongside a visual or interactive condition are supporting
evidence and cannot independently pass the check.

### Boot, regional settings, and branding

| Check ID | Profile/source | Driver and direct oracle |
|---|---|---|
| `boot.plymouth-anduinos-logo` | release-gate, passive installed boot | Sample frames from kernel start to GDM; an AnduinOS animation/logo must be visible and Ubuntu branding must not be visible. |
| `regional.grub-contract` | unit/install, ISO | All 28 GRUB entries contain the exact declared `locale`, `timezone`, and `systemd.timezone` values. |
| `regional.grub-live-propagation` | release-gate, four boot-only Live variants | `locale`, `localectl`, `timedatectl`, GNOME session environment, clock timezone, and representative localized accessible text match the chosen GRUB entry. |
| `regional.installed-zh-cn` | release-gate, installed zh_CN base | `/etc/default/locale`, timezone, generated locale, a real user GNOME session, and the already-running DING desktop's semantic Home/Trash labels consistently report Simplified Chinese/Asia Shanghai. Process environment is retained only as diagnostics because GNOME may clear it after `setlocale`. |
| `localization.zh-cn-contract` | release-gate, installed zh_CN base | Curated Shell, Settings, Nautilus, taskbar, appearance-menu, and GDM strings are Chinese; no gettext key or designated high-impact English fallback is shown. |
| `shell.initial-overview-hidden` | release-gate, first login | After the desktop reaches idle without input, AT-SPI/frame evidence shows the desktop rather than Overview; `start-in-overview=false` is supporting evidence. |
| `theme.cursor-user-session` | release-gate | SPICE cursor shape and size match Fluent dark cursors over a controlled background; user GSettings agree. |
| `branding.start-button-logo` | release-gate | The rendered ArcMenu button region matches the shipped AnduinOS SVG and activating it opens the menu. |
| `branding.settings-about-logo` | release-gate | Settings About displays the AnduinOS name and rendered AnduinOS logo. |
| `branding.gdm` | release-gate after logout | Passive GDM frame contains AnduinOS branding and no Ubuntu branding. |
| `theme.cursor-gdm` | release-gate after logout | GDM cursor-shape capture matches the distribution cursor; GDM dconf is supporting evidence. |
| `tty.tty6-branding` | release-gate | QMP sends Ctrl+Alt+F6, the kernel's `/sys/class/tty/tty0/active` reports tty6, the active `/dev/vcs6` character cells contain `AnduinOS` and no Ubuntu branding, and the harness returns to the original graphical VT with the Wayland session intact. |

### GNOME Shell, desktop, panel, and shortcuts

| Check ID | Profile/source | Driver and direct oracle |
|---|---|---|
| `terminal.ptyxis-initial-size` | release-gate, installed contract | Before the first desktop interaction can persist a window size, query the fresh installed user's effective `org.gnome.Ptyxis window-size`; its schema type must be `(uu)` and its value must be exactly the typed, nonzero `(uint32 80, uint32 24)` tuple. |
| `desktop.context-menu-terminal` | release-gate | Right-click the real desktop, activate the terminal action, and observe a new Ptyxis window in the user session. |
| `desktop.icons-visible` | release-gate | Home and Trash icons are visible through DING and their accessible/component bounds lie on the desktop; the extension process remains healthy. |
| `desktop.create-shortcut` | release-gate overlay | Create/pin a fixture application on the desktop, observe its icon, double-click it, and observe the fixture window. |
| `panel.pin-application` | release-gate overlay | Pin a fixture app from ArcMenu, then observe its launcher on Dash to Panel across a Shell restart. |
| `panel.remove-menu-localized` | release-gate zh_CN/en_US | Right-click the pinned taskbar icon; the menu contains the locale-correct `Remove from taskbar` action, which removes the launcher when activated. |
| `shell.appindicator-roundtrip` | release-gate overlay | Launch a GTK4 fixture which implements the production StatusNotifierItem and DBusMenu protocols without test-only packages. Send Alt+F4, require its window to disappear while the same kernel PID/start time survives, locate its semantic GNOME Shell icon in the lower-right tray, double-click it through host input (the extension's activation gesture), and require the same process/window to return. |
| `shell.extension-policy` | release-gate | The exact installed extension inventory is loaded; every extension is active except `simple-weather@romanlefler.com` and `network-stats@gnome.noroadsleft.xyz`, which are installed but initially inactive. |
| `shell.extension-errors` | release-gate | Login and exercise each enabled extension; no new GNOME Shell JS error or extension exception appears in the scoped journal. |
| `journal.boot-and-idle` | release-gate | No unexpected fatal/error-policy event appears from kernel start through a settled desktop. |
| `journal.action-scoped` | every feature suite | Every interactive check passes its component-specific journal guard. |
| `shortcut.super-tab` | release-gate | Super+Tab changes Overview visibility and a second press restores the desktop. |
| `shortcut.alt-tab` | release-gate | With two distinguishable fixture windows open, Alt+Tab changes focus to the expected other window. |
| `shortcut.super-i` | release-gate | Super+I opens GNOME Settings and the resulting window is focused. |
| `shortcut.super-u` | release-gate | Network Stats begins inactive; Super+U displays/toggles the network information UI, and a second invocation restores the default inactive state. |
| `shortcut.super-shift-s` | release-gate | Super+Shift+S opens the Shell screenshot UI; completing a capture creates a valid non-empty image. |
| `search.spotify-store` | release-gate plus nightly-online | With the VM link physically down, searching Spotify in the real start menu yields a Software result from ISO-shipped metadata and opens the Spotify details page. |
| `command.why-placeholder` | release-gate | Running `why` in Ptyxis shows the expected placeholder and exits without a shell error. |

### Input, emoji, and appearance

| Check ID | Profile/source | Driver and direct oracle |
|---|---|---|
| `system.inotify-max-user-instances` | release-gate | `sysctl -n fs.inotify.max_user_instances` returns exactly `524288` in the installed kernel. |
| `render.twemoji-water-pistol` | release-gate | Render `🤓 🍔 🔫 👽 ✨` in a controlled GTK text surface; font resolution selects Twemoji and the pistol crop satisfies the green-pixel/color-shape oracle. |
| `input.utf8-chinese-text` | release-gate | The editor's AT-SPI text after inserting `变角次亮采之门` is byte-for-byte the expected normalized Unicode text; the saved UTF-8 file contains exactly that text plus Text Editor's intentional implicit trailing newline. |
| `input.super-space-rime` | release-gate, installed zh_CN base | Super+Space changes to Rime; QMP types a fixed ASCII composition and selection sequence; AT-SPI reads the exact expected Chinese result. |
| `appearance.swapcontrol-green` | release-gate | Launch Swap Control, authenticate its polkit prompt through an opaque QMP secret request, require the semantic home-page markers, and verify its designated primary region with the green visual oracle and scoped journal gate. |
| `appearance.theme-menu-localized` | release-gate zh_CN/en_US | The bottom theme selector exposes localized Light/Dark labels appropriate to the session locale. |
| `appearance.theme-gtk` | release-gate overlay | Toggle light then dark; a fixture GTK application reports and visibly renders the matching scheme both times. |
| `appearance.theme-qt` | release-gate overlay | The same toggle changes a fixture Qt application's palette both times without restarting the session. |
| `appearance.theme-firefox` | release-gate overlay | A local page using `prefers-color-scheme` reports and renders the selected light/dark state in Firefox. |

### File previews, associations, and launchers

Release fixtures are generated by the project, redistributable, content-hash
pinned, and mounted read-only. Actual CPU-Z is a separate nightly artifact
fetched from CPUID over HTTPS and accepted only when its pinned archive and
member digests match. Its public availability and license remain outside the
deterministic ISO contract.

| Check ID | Profile/source | Driver and direct oracle |
|---|---|---|
| `files.image-thumbnail` | release-gate | Nautilus generates thumbnail metadata for pinned PNG/JPEG fixtures and renders a non-generic preview. |
| `files.video-thumbnail` | release-gate | Nautilus generates and renders a video-frame preview for a short pinned MP4. |
| `files.image-open` | release-gate | Double-clicking the image opens Loupe with the fixture content. |
| `files.video-open` | release-gate | Double-clicking the video opens Celluloid and playback advances beyond time zero. |
| `files.deb-software` | release-gate | Double-clicking a benign fixture DEB opens its local-package page in GNOME Software; installation is not required. |
| `files.exe-thumbnail-fixture` | release-gate amd64 | A project-owned PE fixture receives the expected EXE thumbnail rather than a generic file icon. |
| `files.exe-open-fixture` | release-gate amd64 overlay | Double-clicking the PE fixture launches it through the configured Windows compatibility path and shows its fixture window. |
| `files.cpuz-thumbnail-and-open` | nightly-online amd64 | Fetch the declared CPU-Z 2.20.2 archive from CPUID, verify both archive and x64 member SHA-256, require Nautilus to cache and visibly expose the embedded white-chip-on-purple preview, then double-click the real PE. Its detected MIME must be one of the two PE types explicitly owned by AnduinOS EXE Runner (`application/vnd.microsoft.portable-executable` or `application/x-msdownload`). EXE Runner must recognize CPU-Z and show its CPU-X native-alternative recommendation with usable Get, Force Run, and Cancel actions. The check does not activate an external store or install Bottles. |
| `files.appimage-open` | release-gate per supported architecture | The same signed project fixture is tested twice through real Nautilus input: mode `0755` must launch its window natively with no MIME handler, while mode `0644` must create neither a process nor a window. |

### Accounts, login policy, display, and networking

| Check ID | Profile/source | Driver and direct oracle |
|---|---|---|
| `account.add-user` | release-gate overlay | Add a standard user through GNOME Settings/Polkit and verify the account appears in Settings and AccountsService. |
| `account.new-user-login` | release-gate overlay | Log out, select the new user in GDM, authenticate, and reach that user's fresh GNOME desktop. |
| `account.change-password` | release-gate overlay | Change the new user's password through Settings, log out, reject the old password, and accept the new password. |
| `account.logout-gdm` | release-gate | Invoke the real logout action and reach branded GDM with the correct cursor before any automatic input. |
| `login.autologin-disabled` | install/release-gate | Default advanced options require GDM authentication on first target boot; no user session starts before QMP enters the password. |
| `login.autologin-enabled` | install/release-gate, passive first boot | With explicit installer opt-in, the target reaches the created user's desktop without any password/key input; the account still has a password and can authenticate after logout. |
| `sudo.password-required` | install/release-gate | With the default advanced option, the passwordless policy is absent, the managed state is empty, the account remains in `sudo`, and `sudo -n` is denied after `sudo -K` clears every cached credential. |
| `sudo.passwordless-enabled` | install/release-gate | With explicit opt-in, the root-owned `0440` policy contains only the created account's exact `NOPASSWD` rule, the root-owned state is exact, `visudo` accepts the complete configuration, and that non-root account runs `sudo -n id -u` as UID 0 after `sudo -K`. |
| `display.spice-resize` | release-gate | Resize the SPICE client through at least two non-native sizes; Mutter reports matching logical monitor geometry and the desktop remains usable. |
| `display.gnome-boxes-resize` | platform-lab | Launch through actual GNOME Boxes/KVM, resize the Boxes window, and observe matching guest resolution changes. |
| `network.wifi-migration-hwsim` | install/release-gate amd64 | Enter a WPA2 PSK once in Live, install, recreate the AP, and observe automatic target connection without another secret injection. The migrated Netplan is root-owned mode 0600. |
| `network.wifi-migration-physical` | platform-lab | Repeat the exact workflow with a controlled physical AP and Wi-Fi adapter. |

### Storage rollback

| Check ID | Profile/source | Driver and direct oracle |
|---|---|---|
| `storage.btrfs-docker-rollback` | nightly-online, UEFI/no-Secure-Boot Btrfs overlay | Install the real `docker.io` package, require a complete snapshot transaction and exact protected recovery metadata, arm rollback through Disk Snapshots Manager, traverse the product-owned one-shot EFI recovery boot, then prove `docker.io` and its sentinel disappeared while the restored root UUID/parent UUID, fallback deployment, history record, package database, kernel, initramfs, GRUB, and GNOME boot are all healthy. |

### Public ecosystem integrations

| Check ID | Profile/source | Driver and direct oracle |
|---|---|---|
| `apt.nextcloud-client-ppa` | nightly-online | Run the exact `sudo add-apt-repository -y ppa:nextcloud-devs/client`, require exit zero, a valid signed source, and a successful metadata refresh. |
| `app.wechat-install` | nightly-online amd64 overlay | Resolve current Flathub `app/com.tencent.WeChat/x86_64/stable`, install it including Tencent's declared extra-data payload, require the installed commit/origin and exported desktop file to match that resolution, then launch the real ArcMenu result. Since the proprietary X11/Qt client has no AT-SPI application, require one mapped EWMH WeChat window plus a screenshot crop containing its QR-code transitions and green login marker. |
| `app.wechat-tray` | platform-lab authenticated amd64 session | Start from an explicitly supplied, disposable authenticated WeChat test profile. Send Alt+F4 to the visible WeChat window, require that same EWMH client PID and kernel process start time to remain while the window disappears, observe a semantic GNOME Shell AppIndicator whose geometry is in the lower-right tray, double-click it through host input, and require the same process/window to return. Anonymous CI must not pretend the QR login page has tray semantics. |
| `store.spotify-public` | nightly-online amd64 | Refresh official Flathub AppStream over HTTPS, resolve the exact current `app/com.spotify.Client/x86_64/stable` ref and commit, prove that entry reached the local cache, reload GNOME Software, and repeat real ArcMenu-to-details navigation with networking up. Refresh/resolution failures are `external-catalog`; UI failure after successful resolution is `product-regression`. |

## Fixture and dependency policy

The release fixture set contains:

- PNG, JPEG, SVG, and a short MP4 with known dimensions and content;
- a benign DEB with metadata but no privileged maintainer scripts;
- tiny GTK and Qt applications that report their effective theme;
- a local HTML page that reports `prefers-color-scheme`;
- per-architecture AppImages signed by the test project;
- a benign PE application for thumbnail and Wine-launch integration;
- AppStream metadata containing a deterministic Spotify entry;
- logo, cursor, and color reference assets derived from the exact packages in
  the ISO under test.

Fixtures are identified by SHA-256 in the run manifest. Small redistributable
fixtures may live in Git LFS or a generated fixture ISO. Large or restricted
third-party artifacts are fetched only by `nightly-online`, verified against
versioned digests before use, and may be backed by a CI download cache that
preserves the same byte identity.

The host test environment is versioned separately from the guest and declares
QEMU, OVMF/AAVMF, libvirt/Boxes for platform runs, SPICE client bindings,
Pillow/image comparison support, and OCR language data. A host dependency
change is recorded in the run manifest so visual drift is diagnosable.

## Scheduling and reporting

Base production is serialized per target image. Once a base is promoted,
independent overlays may run in parallel. A resource allocator owns QMP
sockets, serial sockets, host-forward ports, temporary VARS, memory, vCPUs,
and KVM slots. ARM64-on-amd64 TCG visual suites default to nightly because of
runtime; architecture-neutral command assertions still run against ARM64
installation bases. An agent-independent SPICE channel delivers strictly
mapped scan codes to graphical GRUB, and stable non-menu framebuffer repaints
gate every following command. The resulting kernel/debug-shell arguments must
then prove themselves on PL011; a default or malformed boot cannot pass merely
because the VM stayed alive. The virtio GPU remains present for the complete
firmware-to-graphical lifecycle.

The current installation matrix dashboard is hierarchical: its eleven amd64
or seven arm64 disposable installation scenarios remain the top-level progress
units, while the active
scenario exposes each implemented assertion boundary and its real lifecycle:

```text
● installed-zh-shell                         RUNNING
  ✓ shell.initial-overview-hidden            PASSED
  ✓ shell.extension-policy                   PASSED
  ● shortcut.super-u                         Checking Network Stats UI
  ○ shortcut.super-shift-s                   NOT STARTED
```

Plain/CI output preserves the same transitions as durable lines. Final output
derives both `summary.json` and JUnit XML from the dashboard state, including
pending work after fail-fast. JSON Lines are retained for individual action
traces; the future base/overlay provenance graph and HTML evidence index remain
part of the design below. A failed visual or UI check retains its frame,
accessibility tree, journal slice, and command transcript.

## Delivery order

1. Add suite/check models, profile selection, base promotion, overlay creation,
   resource allocation, nested reporting, JUnit output, and journal cursors
   without weakening existing installation verdicts.
2. Implement deterministic state and Shell checks: inotify, locale/timezone,
   overview, cursor configuration, extension policy/errors, shortcut effects,
   branding configuration, and scoped journal policy.
3. Add passive frame capture and visual oracles for Plymouth, Shell/GDM logos,
   cursor shape, Twemoji, Swap Control, and VT branding.
4. Add the fixture image/server and file, MIME, theme, Firefox, AppImage, PE,
   Rime, desktop, panel, and account suites.
5. Keep the automatic-login, virtual-Wi-Fi, and deterministic SPICE variants
   under regression while expanding their cross-architecture coverage.
6. Add nightly public ecosystem checks and platform-lab GNOME Boxes/physical
   Wi-Fi checks.

No stage is considered complete merely because a plugin exists. Each listed
check must have a failure-injection unit test proving that its oracle rejects a
known-bad observation, followed by at least one retained QEMU evidence run.

## Architecture completion criteria

The feature-test architecture is complete when:

- every check ID in this document is registered and selectable;
- every release-gate check has deterministic fixtures and a direct behavioral
  oracle;
- the automatic-login and virtual-Wi-Fi installation variants pass and fail
  correctly under injected negative conditions;
- public and hardware dependencies cannot accidentally enter the release gate;
- all suites use disposable overlays and fresh UEFI VARS;
- journal, visual, AT-SPI, QMP, and command evidence are indexed per check;
- the TUI, JSON, JUnit, and exit status agree on every check result;
- a requirement-to-check audit reports no missing, duplicate, or unimplemented
  requirement.
