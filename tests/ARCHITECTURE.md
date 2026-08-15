# AnduinOS system acceptance architecture

This document defines the target architecture and backlog for growing the ISO
acceptance harness from installation coverage into reproducible whole-desktop
coverage. It is not an implementation-status report. Every planned product
requirement below has a stable check identifier, intended isolation boundary,
driver, oracle, evidence contract, and profile. A check is implemented only
after runtime code reachable from `make test` executes it against a guest and
retains authoritative evidence.

The machine-readable planning inventory is `coverage-plan.json`; unit tests
require its 60 identifiers to match this document exactly. Those shape tests
validate the roadmap, not the guest behavior. `README.md`, `matrix.json`, and
the runtime modules under `iso_test/` describe the currently executable gate.

The existing ten installation scenarios remain the authority for firmware,
storage, Secure Boot, online/offline behavior, SSH, and post-install boot. The
desktop suites do not duplicate those installations. They consume only target
disks that have already passed every installation assertion.

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
       installation matrix (currently 10)
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

Until feature suites are implemented, plain `make test` keeps its current
installation-matrix meaning. The default may become `release-gate` only after
that profile is deterministic and its runtime is documented.

## Installation variants added by feature coverage

Most feature suites consume the existing UEFI/no-Secure-Boot, online, Btrfs,
Simplified-Chinese target. Two requirements genuinely change installation
inputs and therefore cannot be fabricated after installation:

1. **Automatic login.** Add `automatic_login` to the installation scenario
   model. Set it to true in one existing advanced-options scenario (prefer the
   SSH-enabled UEFI/no-Secure-Boot case) and false everywhere else. This covers
   both secure default and explicit opt-in without another installation.
2. **Wi-Fi credential migration.** Add one amd64 UEFI/no-Secure-Boot Btrfs
   installation using a virtual WPA2 interface instead of Ethernet. It enters
   the PSK once in Live, installs, recreates the same AP after reboot, and
   proves NetworkManager reconnects without another secret input. This is the
   eleventh full installation until reliable cross-architecture virtual Wi-Fi
   support is available.

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
| `regional.installed-zh-cn` | release-gate, installed zh_CN base | `/etc/default/locale`, timezone, user session environment, input sources, and high-value GNOME surfaces consistently report Simplified Chinese/Asia Shanghai. |
| `localization.zh-cn-contract` | release-gate, installed zh_CN base | Curated Shell, Settings, Nautilus, taskbar, appearance-menu, and GDM strings are Chinese; no gettext key or designated high-impact English fallback is shown. |
| `shell.initial-overview-hidden` | release-gate, first login | After the desktop reaches idle without input, AT-SPI/frame evidence shows the desktop rather than Overview; `start-in-overview=false` is supporting evidence. |
| `theme.cursor-user-session` | release-gate | SPICE cursor shape and size match Fluent dark cursors over a controlled background; user GSettings agree. |
| `branding.start-button-logo` | release-gate | The rendered ArcMenu button region matches the shipped AnduinOS SVG and activating it opens the menu. |
| `branding.settings-about-logo` | release-gate | Settings About displays the AnduinOS name and rendered AnduinOS logo. |
| `branding.gdm` | release-gate after logout | Passive GDM frame contains AnduinOS branding and no Ubuntu branding. |
| `theme.cursor-gdm` | release-gate after logout | GDM cursor-shape capture matches the distribution cursor; GDM dconf is supporting evidence. |
| `tty.tty6-branding` | release-gate | QMP sends Ctrl+Alt+F6, `fgconsole` reports 6, OCR/template evidence contains `AnduinOS`, and the harness returns to the graphical VT. |

### GNOME Shell, desktop, panel, and shortcuts

| Check ID | Profile/source | Driver and direct oracle |
|---|---|---|
| `desktop.context-menu-terminal` | release-gate | Right-click the real desktop, activate the terminal action, and observe a new Ptyxis window in the user session. |
| `desktop.icons-visible` | release-gate | Home and Trash icons are visible through DING and their accessible/component bounds lie on the desktop; the extension process remains healthy. |
| `desktop.create-shortcut` | release-gate overlay | Create/pin a fixture application on the desktop, observe its icon, double-click it, and observe the fixture window. |
| `panel.pin-application` | release-gate overlay | Pin a fixture app from ArcMenu, then observe its launcher on Dash to Panel across a Shell restart. |
| `panel.remove-menu-localized` | release-gate zh_CN/en_US | Right-click the pinned taskbar icon; the menu contains the locale-correct `Remove from taskbar` action, which removes the launcher when activated. |
| `shell.extension-policy` | release-gate | The exact installed extension inventory is loaded; every extension is active except `simple-weather@romanlefler.com` and `network-stats@gnome.noroadsleft.xyz`, which are installed but initially inactive. |
| `shell.extension-errors` | release-gate | Login and exercise each enabled extension; no new GNOME Shell JS error or extension exception appears in the scoped journal. |
| `journal.boot-and-idle` | release-gate | No unexpected fatal/error-policy event appears from kernel start through a settled desktop. |
| `journal.action-scoped` | every feature suite | Every interactive check passes its component-specific journal guard. |
| `shortcut.super-tab` | release-gate | Super+Tab changes Overview visibility and a second press restores the desktop. |
| `shortcut.alt-tab` | release-gate | With two distinguishable fixture windows open, Alt+Tab changes focus to the expected other window. |
| `shortcut.super-i` | release-gate | Super+I opens GNOME Settings and the resulting window is focused. |
| `shortcut.super-u` | release-gate | Network Stats begins inactive; Super+U displays/toggles the network information UI, and a second invocation restores the default inactive state. |
| `shortcut.super-shift-s` | release-gate | Super+Shift+S opens the Shell screenshot UI; completing a capture creates a valid non-empty image. |
| `search.spotify-store` | release-gate plus nightly-online | Searching Spotify in the real start menu yields a Software result and opens the Spotify details page. Release uses pinned AppStream metadata; nightly repeats against the public catalog. |
| `command.why-placeholder` | release-gate | Running `why` in Ptyxis shows the expected placeholder and exits without a shell error. |

### Input, emoji, and appearance

| Check ID | Profile/source | Driver and direct oracle |
|---|---|---|
| `system.inotify-max-user-instances` | release-gate | `sysctl -n fs.inotify.max_user_instances` returns exactly `524288` in the installed kernel. |
| `render.twemoji-water-pistol` | release-gate | Render `🤓 🍔 🔫 👽 ✨` in a controlled GTK text surface; font resolution selects Twemoji and the pistol crop satisfies the green-pixel/color-shape oracle. |
| `input.utf8-chinese-text` | release-gate | The editor's AT-SPI text after inserting `变角次亮采之门` is byte-for-byte the expected normalized Unicode text and the screenshot has no tofu glyphs. |
| `input.super-space-rime` | release-gate, installed zh_CN base | Super+Space changes to Rime; QMP types a fixed ASCII composition and selection sequence; AT-SPI reads the exact expected Chinese result. |
| `appearance.swapcontrol-green` | release-gate | Launch Swap Control; the home page becomes idle without an error and its designated primary region passes the green visual oracle. |
| `appearance.theme-menu-localized` | release-gate zh_CN/en_US | The bottom theme selector exposes localized Light/Dark labels appropriate to the session locale. |
| `appearance.theme-gtk` | release-gate overlay | Toggle light then dark; a fixture GTK application reports and visibly renders the matching scheme both times. |
| `appearance.theme-qt` | release-gate overlay | The same toggle changes a fixture Qt application's palette both times without restarting the session. |
| `appearance.theme-firefox` | release-gate overlay | A local page using `prefers-color-scheme` reports and renders the selected light/dark state in Firefox. |

### File previews, associations, and launchers

Release fixtures are generated by the project, redistributable, content-hash
pinned, and mounted read-only. Actual CPU-Z is a separate cached nightly
artifact because its public download and license are outside the ISO contract.

| Check ID | Profile/source | Driver and direct oracle |
|---|---|---|
| `files.image-thumbnail` | release-gate | Nautilus generates thumbnail metadata for pinned PNG/JPEG fixtures and renders a non-generic preview. |
| `files.video-thumbnail` | release-gate | Nautilus generates and renders a video-frame preview for a short pinned MP4. |
| `files.image-open` | release-gate | Double-clicking the image opens Loupe with the fixture content. |
| `files.video-open` | release-gate | Double-clicking the video opens Celluloid and playback advances beyond time zero. |
| `files.deb-software` | release-gate | Double-clicking a benign fixture DEB opens its local-package page in GNOME Software; installation is not required. |
| `files.exe-thumbnail-fixture` | release-gate amd64 | A project-owned PE fixture receives the expected EXE thumbnail rather than a generic file icon. |
| `files.exe-open-fixture` | release-gate amd64 overlay | Double-clicking the PE fixture launches it through the configured Windows compatibility path and shows its fixture window. |
| `files.cpuz-thumbnail-and-open` | nightly-online amd64 | Fetch the declared CPU-Z version, verify SHA-256, observe its preview, double-click it, and observe the CPU-Z window. |
| `files.appimage-open` | release-gate per supported architecture | Double-clicking a signed project fixture AppImage launches its fixture window without a terminal workaround. |

### Accounts, login policy, display, and networking

| Check ID | Profile/source | Driver and direct oracle |
|---|---|---|
| `account.add-user` | release-gate overlay | Add a standard user through GNOME Settings/Polkit and verify the account appears in Settings and AccountsService. |
| `account.new-user-login` | release-gate overlay | Log out, select the new user in GDM, authenticate, and reach that user's fresh GNOME desktop. |
| `account.change-password` | release-gate overlay | Change the new user's password through Settings, log out, reject the old password, and accept the new password. |
| `account.logout-gdm` | release-gate | Invoke the real logout action and reach branded GDM with the correct cursor before any automatic input. |
| `login.autologin-disabled` | install/release-gate | Default advanced options require GDM authentication on first target boot; no user session starts before QMP enters the password. |
| `login.autologin-enabled` | install/release-gate, passive first boot | With explicit installer opt-in, the target reaches the created user's desktop without any password/key input; the account still has a password and can authenticate after logout. |
| `display.spice-resize` | release-gate | Resize the SPICE client through at least two non-native sizes; Mutter reports matching logical monitor geometry and the desktop remains usable. |
| `display.gnome-boxes-resize` | platform-lab | Launch through actual GNOME Boxes/KVM, resize the Boxes window, and observe matching guest resolution changes. |
| `network.wifi-migration-hwsim` | install/release-gate amd64 | Enter a WPA2 PSK once in Live, install, recreate the AP, and observe automatic target connection without another secret injection. The migrated Netplan is root-owned mode 0600. |
| `network.wifi-migration-physical` | platform-lab | Repeat the exact workflow with a controlled physical AP and Wi-Fi adapter. |

### Public ecosystem integrations

| Check ID | Profile/source | Driver and direct oracle |
|---|---|---|
| `apt.nextcloud-client-ppa` | nightly-online | Run the exact `sudo add-apt-repository -y ppa:nextcloud-devs/client`, require exit zero, a valid signed source, and a successful metadata refresh. |
| `app.wechat-install` | nightly-online amd64 overlay | Install the declared WeChat package from the tested repository snapshot and launch its main window without package or loader errors. |
| `app.wechat-tray` | nightly-online amd64 overlay | Minimize/close WeChat according to its supported action; an AppIndicator appears in the lower-right tray and restores the same process/window. |
| `store.spotify-public` | nightly-online | Repeat start-menu Spotify discovery against the current public store and classify external catalog outages separately from product regressions. |

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
third-party artifacts are downloaded into a CI cache, verified against a
versioned digest, and used only by `nightly-online`.

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
installation bases.

The current installation matrix dashboard is hierarchical: its ten disposable
installation scenarios remain the top-level progress units, while the active
scenario exposes each implemented assertion boundary and its real lifecycle:

```text
● installed-zh-shell                         RUNNING
  ✓ shell.initial-overview-hidden            PASSED
  ✓ shell.extension-policy                   PASSED
  ● shortcut.super-u                         Checking Network Stats UI
  ○ shortcut.super-shift-s                   NOT STARTED
```

Plain/CI output preserves the same transitions as durable lines, and final
output records the child verdicts in `summary.json`. JSON Lines, JUnit XML, the
future base/overlay provenance graph, and an HTML evidence index remain part of
the feature-suite design below. A failed visual or UI check will link directly
to its frame, accessibility tree, journal slice, and command transcript.

## Delivery order

1. Add suite/check models, profile selection, base promotion, overlay creation,
   resource allocation, nested reporting, JUnit output, and journal cursors
   without changing the ten existing scenario verdicts.
2. Implement deterministic state and Shell checks: inotify, locale/timezone,
   overview, cursor configuration, extension policy/errors, shortcut effects,
   branding configuration, and scoped journal policy.
3. Add passive frame capture and visual oracles for Plymouth, Shell/GDM logos,
   cursor shape, Twemoji, Swap Control, and VT branding.
4. Add the fixture image/server and file, MIME, theme, Firefox, AppImage, PE,
   Rime, desktop, panel, and account suites.
5. Extend the installer matrix for automatic login and virtual Wi-Fi, then add
   deterministic SPICE resizing.
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
