#!/bin/bash

#==========================
# Set up the environment
#==========================
set -e                  # exit on error
set -o pipefail         # exit on pipeline error
set -u                  # treat unset variable as error
SCRIPT_DIR="$(dirname "$(readlink -f "$0")")"
export SCRIPT_DIR

source "$SCRIPT_DIR/shared.sh"
source "$SCRIPT_DIR/args.sh"

# Persistent host-side cache for downloaded .deb packages.
# When KEEP_DOWNLOADED_DEBS=true, the chroot's /var/cache/apt/archives is
# bind-mounted to this directory so that retries after a network failure
# reuse packages that were already downloaded. It is excluded from the
# SquashFS, so the final ISO size is unaffected.
APT_CACHE_DIR="$SCRIPT_DIR/.cache/apt-archives"
export APT_CACHE_DIR

# Do NOT derive this label from TARGET_NAME. Rufus ISO mode replaces the old
# volume-label substring across matching boot command lines, not just CDLABEL
# values. With label "anduinos", FAT label uppercasing also turns
# rd.anduinos.live=1 into rd.ANDUINOS.live=1. Our case-sensitive Live hooks then
# skip BOTH media verification and Live-user setup, leaving a GDM login prompt.
# "ANDUINOS" alone is not sufficient: a custom USB label would also rewrite
# ANDUINOS-PERSIST. Keep the media label distinct from parameter names and the
# persistence label; changing the USB label must only change media references.
# Regression coverage: make test TEST_ARGS="--live-usb-only --no-tui".
LIVE_MEDIA_LABEL="AOS_LIVE"

# Reject unsupported targets before starting either build workshop.
case "$TARGET_ARCH" in
    amd64|arm64) ;;
    *)
        print_error "Unsupported target architecture: $TARGET_ARCH"
        exit 1
        ;;
esac

function bind_signal() {
    print_ok "Bind signal..."
    trap umount_on_exit EXIT
    judge "Bind signal"
}

function clean() {
    print_ok "Cleaning up previous build..."
    sudo umount new_building_os/sys || sudo umount -lf new_building_os/sys || true
    sudo umount new_building_os/proc || sudo umount -lf new_building_os/proc || true
    sudo umount new_building_os/dev || sudo umount -lf new_building_os/dev || true
    sudo umount new_building_os/run || sudo umount -lf new_building_os/run || true
    # The persistent deb cache lives in .cache/ and is intentionally kept.
    sudo umount new_building_os/var/cache/apt/archives || sudo umount -lf new_building_os/var/cache/apt/archives || true
    sudo rm -rf new_building_os official_ubuntu_os image || true
    judge "Clean up build artifacts"
}

# Prepare the persistent host-side apt cache. Kept outside new_building_os so
# that clean() does not delete downloaded .deb packages between builds.
function prepare_apt_cache() {
    if [[ "${KEEP_DOWNLOADED_DEBS:-false}" != "true" ]]; then
        print_ok "Deb cache disabled (KEEP_DOWNLOADED_DEBS != true); apt cache will be discarded at cleanup."
        return 0
    fi
    print_ok "Preparing persistent deb cache at $APT_CACHE_DIR ..."
    mkdir -p "$APT_CACHE_DIR/partial"
    judge "Prepare persistent deb cache"
}

# Bind-mount the persistent cache into the chroot so apt writes downloaded
# packages to the host directory instead of the disposable rootfs.
function mount_apt_cache() {
    [[ "${KEEP_DOWNLOADED_DEBS:-false}" == "true" ]] || return 0
    print_ok "Mounting persistent deb cache into chroot..."
    mkdir -p "$APT_CACHE_DIR/partial"
    sudo mount --bind "$APT_CACHE_DIR" "$SCRIPT_DIR/new_building_os/var/cache/apt/archives"
    judge "Mount persistent deb cache"
}

function umount_apt_cache() {
    [[ "${KEEP_DOWNLOADED_DEBS:-false}" == "true" ]] || return 0
    sudo umount "$SCRIPT_DIR/new_building_os/var/cache/apt/archives" || \
        sudo umount -lf "$SCRIPT_DIR/new_building_os/var/cache/apt/archives" || true
}

# ---------------------------------------------------------------------------
# Staged build / resume support
# ---------------------------------------------------------------------------
STATE_DIR="$SCRIPT_DIR/.cache/build-state"
RESUME=false

function stage_done() {
    mkdir -p "$STATE_DIR"
    touch "$STATE_DIR/$1.ok"
}

function stage_is_done() {
    [[ -f "$STATE_DIR/$1.ok" ]]
}

function run_stage() {
    local name="$1"
    shift
    if [[ "$RESUME" == "true" ]] && stage_is_done "$name"; then
        print_ok "Skipping completed stage: $name"
        return 0
    fi
    print_ok "Running stage: $name"
    "$@"
    stage_done "$name"
}

# Generate the package lists consumed by mods/05 from packages.json.
function prepare_build_config() {
    print_ok "Generating package lists from packages.json..."
    python3 "$SCRIPT_DIR/gui/packages_config.py" --generate --root "$SCRIPT_DIR"
    judge "Generate package lists"
}

# Custom script running inside the chroot after all mods, before unmount.
function run_custom_chroot_hook() {
    local hook="$SCRIPT_DIR/custom_hooks.sh"
    if [[ -s "$hook" ]]; then
        print_ok "Running custom chroot hook..."
        sudo cp "$hook" new_building_os/root/custom_hooks.sh
        sudo chroot new_building_os /bin/bash /root/custom_hooks.sh
        judge "Run custom chroot hook"
    else
        print_ok "No custom chroot hook; skipping."
    fi
}

# Custom script running on the host after image/ is ready, before xorriso.
function run_pre_iso_hook() {
    local hook="$SCRIPT_DIR/custom_pre_iso.sh"
    if [[ -s "$hook" ]]; then
        print_ok "Running custom pre-ISO hook..."
        ( cd "$SCRIPT_DIR" && bash "$hook" )
        judge "Run custom pre-ISO hook"
    else
        print_ok "No custom pre-ISO hook; skipping."
    fi
}

function stage_prepare() {
    prepare_iso_directory
    download_base_system
}

function stage_mount_apt() {
    mount_folders
    setup_apt
}

function stage_export() {
    umount_folders
    prepare_live_grub_font
    prepare_live_grub_theme
    export_anduinos_payload
}

function prepare_iso_directory() {
    print_ok "Creating image directory..."
    sudo rm -rf image
    mkdir -p image/{LiveOS,isolinux,.disk}
    judge "Create image directory"
}

# Contract: prepare_iso_directory has created the shared image/ output tree.
# On success, this workshop has unmounted new_building_os and exported:
#   image/LiveOS/{rootfs.squashfs,vmlinuz,initrd,filesystem.manifest,filesystem.size}
#   image/boot/grub/fonts/anduinos-unicode-16.pf2
#   image/boot/grub/themes/anduinos-hyperfluent/
# We require the completed system to provide its kernel symlink, the dedicated
# /boot/anduinos-live-initrd.img and the packaged GRUB theme. Only this workshop
# knows those rootfs paths; build_iso consumes the exported files.
function run_chroot_anduinos() {
    download_base_system
    mount_folders
    setup_apt
    apply_anduinos_mods
    umount_folders
    prepare_live_grub_font
    prepare_live_grub_theme
    export_anduinos_payload
}

function download_base_system() {
    # Early mods need dbus-uuidgen; anduinos-core-system selects the suite's bus daemon.
    bootstrap_ubuntu_root "$SCRIPT_DIR/new_building_os" ca-certificates,wget,dbus-bin
}

# Shared bootstrap only; package sources and workshop actions remain explicit.
function bootstrap_ubuntu_root() {
    local target_root=$1
    local packages=$2
    print_ok "Bootstrapping Ubuntu $TARGET_UBUNTU_VERSION ($TARGET_ARCH) in $target_root..."
    sudo mkdir -p "$target_root"
    sudo debootstrap --arch="$TARGET_ARCH" --variant=minbase \
        --include="$packages" \
        "$TARGET_UBUNTU_VERSION" "$target_root" "$APT_SOURCE"
    judge "Bootstrap Ubuntu build environment"
}

function configure_ubuntu_sources() {
    local target_root=$1
    print_ok "Setting up Ubuntu apt sources in chroot..."
    sudo mkdir -p "$target_root/etc/apt/sources.list.d"
    sudo tee "$target_root/etc/apt/sources.list.d/ubuntu.sources" > /dev/null <<EOF
Types: deb
URIs: $APT_SOURCE
Suites: $TARGET_UBUNTU_VERSION
Components: main restricted universe multiverse
Signed-By: /usr/share/keyrings/ubuntu-archive-keyring.gpg

Types: deb
URIs: $APT_SOURCE
Suites: $TARGET_UBUNTU_VERSION-updates
Components: main restricted universe multiverse
Signed-By: /usr/share/keyrings/ubuntu-archive-keyring.gpg

Types: deb
URIs: $APT_SOURCE
Suites: $TARGET_UBUNTU_VERSION-backports
Components: main restricted universe multiverse
Signed-By: /usr/share/keyrings/ubuntu-archive-keyring.gpg

Types: deb
URIs: $APT_SOURCE
Suites: $TARGET_UBUNTU_VERSION-security
Components: main restricted universe multiverse
Signed-By: /usr/share/keyrings/ubuntu-archive-keyring.gpg
EOF
    judge "Set up Ubuntu apt sources"

    # Remove stale legacy-format sources.list (debootstrap artifact).
    # Ubuntu 24.04+ uses deb822 .sources files in sources.list.d/ instead.
    sudo rm -f "$target_root/etc/apt/sources.list"
}

function mount_folders() {
    print_ok "Reloading systemd daemon..."
    sudo systemctl daemon-reload
    judge "Reload systemd daemon"

    print_ok "Mounting /dev /run from host to build dir..."
    sudo mount --bind /dev new_building_os/dev
    sudo mount --bind /run new_building_os/run
    judge "Mount /dev /run"

    print_ok "Mounting /proc /sys /dev/pts within chroot..."
    sudo chroot new_building_os mount none -t proc /proc
    sudo chroot new_building_os mount none -t sysfs /sys
    sudo chroot new_building_os mount none -t devpts /dev/pts
    judge "Mount /proc /sys /dev/pts"

    print_ok "Copying mods to chroot /root/mods..."
    sudo cp -r "$SCRIPT_DIR/mods" new_building_os/root/mods
    sudo cp "$SCRIPT_DIR/args.sh" new_building_os/root/mods/args.sh
    sudo cp "$SCRIPT_DIR/shared.sh" new_building_os/root/mods/shared.sh
    # Package selection from packages.json (generated on the host by
    # gui/packages_config.py); chroot itself does not need python3.
    sudo cp "$SCRIPT_DIR/.cache/build/core_packages.txt" new_building_os/root/mods/core_packages.txt
    sudo cp "$SCRIPT_DIR/.cache/build/desktop_packages.txt" new_building_os/root/mods/desktop_packages.txt

    mount_apt_cache
}

function setup_apt() {
    configure_ubuntu_sources "$SCRIPT_DIR/new_building_os"

    print_ok "Setting up AnduinOS APKG apt source in chroot..."

    local keyring_path="new_building_os/usr/share/keyrings/anduinos-archive-keyring.gpg"
    local cert_url="$APKG_SERVER/artifacts/certs/$APKG_CERT_NAME"

    print_ok "Downloading GPG keyring from $cert_url ..."
    sudo mkdir -p new_building_os/usr/share/keyrings
    curl --fail --show-error --location "$cert_url" | \
        sed '1s/^\xEF\xBB\xBF//' | \
        gpg --dearmor | \
        sudo tee "$keyring_path" > /dev/null
    judge "Download and dearmor keyring"

    print_ok "Generating anduinos.sources for $APKG_SERVER (suite: $TARGET_UBUNTU_VERSION-addon)..."
    sudo mkdir -p new_building_os/etc/apt/sources.list.d
    sudo tee new_building_os/etc/apt/sources.list.d/anduinos.sources > /dev/null <<EOF
Types: deb
URIs: $APKG_SERVER/artifacts/anduinos/
Suites: $TARGET_UBUNTU_VERSION-addon
Components: main
Architectures: $TARGET_ARCH
Signed-By: /usr/share/keyrings/anduinos-archive-keyring.gpg
EOF
    judge "Generate sources"

    print_ok "Enabling apt recommends in chroot..."
    echo 'APT::Install-Recommends "true";' | sudo tee new_building_os/etc/apt/apt.conf.d/99-enable-recommends > /dev/null
    judge "Enable apt recommends"

    print_ok "Running apt update in chroot..."
    sudo chroot new_building_os apt update
    judge "Apt update in chroot"

    # Upgrade base system BEFORE mods run.  Swap packages (mod 01)
    # must not be visible to this upgrade — apt would try to
    # "normalize" them back to Ubuntu's lower version and fail.
    print_ok "Upgrading base system packages..."
    sudo chroot new_building_os apt -y upgrade
    judge "Upgrade base system"
}

function apply_anduinos_mods() {
    print_ok "Running install_all_mods.sh in new_building_os..."
    print_warn "============================================"
    print_warn "   The following will run in chroot ENV!"
    print_warn "============================================"
    sudo chroot new_building_os /usr/bin/env DEBIAN_FRONTEND=${DEBIAN_FRONTEND:-readline} /root/mods/install_all_mods.sh -
    print_warn "============================================"
    print_warn "   chroot ENV execution completed!"
    print_warn "============================================"
    judge "Run install_all_mods.sh in new_building_os"

    print_ok "Sleeping for 5 seconds to allow chroot to exit cleanly..."
    sleep 5
}

function umount_folders() {
    umount_apt_cache

    print_ok "Cleaning mods from chroot /root/mods..."
    sudo rm -rf new_building_os/root/mods
    judge "Clean up chroot /root/mods"

    print_ok "Unmounting /proc /sys /dev/pts within chroot..."
    sudo chroot new_building_os umount /dev/pts || sudo chroot new_building_os umount -lf /dev/pts
    sudo chroot new_building_os umount /sys || sudo chroot new_building_os umount -lf /sys
    sudo chroot new_building_os umount /proc || sudo chroot new_building_os umount -lf /proc
    judge "Unmount /proc /sys /dev/pts"

    print_ok "Unmounting /dev /run outside of chroot..."
    sudo umount new_building_os/dev || sudo umount -lf new_building_os/dev
    sudo umount new_building_os/run || sudo umount -lf new_building_os/run
    judge "Unmount /dev /run"
}

function prepare_live_grub_font() {
    print_ok "Generating BIOS Unicode font for the Live ISO..."
    mkdir -p \
        image/isolinux \
        image/boot/grub/fonts
    grub-mkfont \
        --size="16" \
        --output="image/isolinux/anduinos-unicode-16.pf2" \
        "/usr/share/fonts/opentype/unifont/unifont.otf"
    cp "image/isolinux/anduinos-unicode-16.pf2" \
        "image/boot/grub/fonts/anduinos-unicode-16.pf2"
    judge "Prepare readable Live GRUB font"
}

function prepare_live_grub_theme() {
    local source_dir="new_building_os/usr/share/grub/themes/anduinos-hyperfluent"
    if [ ! -s "$source_dir/theme.txt" ] || [ ! -s "$source_dir/background.png" ] || [ ! -s "$source_dir/live-grub.cfg" ]; then
        print_error "Installed GRUB theme package is incomplete: $source_dir"
        exit 1
    fi
    mkdir -p image/boot/grub/themes
    cp -r "$source_dir" image/boot/grub/themes/
    judge "Copy packaged GRUB theme to Live ISO"
}

function export_anduinos_payload() {
    local REAL_VMLINUZ REAL_INITRD filesystem_size
    # Copy the kernel and the separately-built non-host-only Live initrd.
    print_ok "Copying the Dracut Live boot artifacts to /LiveOS..."
    # Resolve the distro-maintained symlinks — they always point to the
    # current kernel, so we never pick a stale one left behind by apt.
    REAL_VMLINUZ=$(readlink -f new_building_os/vmlinuz 2>/dev/null)
    [ -f "$REAL_VMLINUZ" ] || REAL_VMLINUZ=$(readlink -f new_building_os/boot/vmlinuz 2>/dev/null)
    REAL_INITRD="new_building_os/boot/anduinos-live-initrd.img"
    sudo cp "$REAL_VMLINUZ" image/LiveOS/vmlinuz
    sudo cp "$REAL_INITRD" image/LiveOS/initrd
    judge "Copy kernel files"

    # generate manifest
    print_ok "Generating manifest for filesystem..."
    sudo chroot new_building_os dpkg-query -W --showformat='${Package} ${Version}\n' | sudo tee image/LiveOS/filesystem.manifest >/dev/null 2>&1
    judge "Generate manifest for filesystem"
    judge "Generate manifest for filesystem-desktop"

    print_ok "Compressing the single root filesystem as /LiveOS/rootfs.squashfs..."
    sudo mksquashfs new_building_os image/LiveOS/rootfs.squashfs \
        -noappend -no-duplicates -no-recovery \
        -wildcards -b 1M \
        -comp zstd -Xcompression-level 19 \
        -e "var/cache/apt/archives/*" \
        -e "tmp/*" \
        -e "tmp/.*" \
        -e "boot/anduinos-live-initrd.img" \
        -e "swapfile"
    judge "Compress rootfs"

    print_ok "Generating filesystem.size on /LiveOS/filesystem.size..."
    filesystem_size=$(sudo du -sx --block-size=1 new_building_os | cut -f1)
    printf '%s\n' "$filesystem_size" > image/LiveOS/filesystem.size
    judge "Generate filesystem.size"
}

# Contract: the configured Ubuntu suite/architecture must provide signed shim,
# CD GRUB and MokManager. On success, image/isolinux/live-efi/ contains:
#   amd64: BOOTX64.EFI, grubx64.efi, mmx64.efi
#   arm64: BOOTAA64.EFI, grubaa64.efi, mmaa64.efi
# build_iso copies these files into efiboot.img and removes the staging folder.
# official_ubuntu_os uses only Ubuntu sources; boot packages are downloaded and
# extracted, not installed. Neither this root nor its APT cache enters the ISO
# or the AnduinOS squashfs. No AnduinOS rootfs contents are required here.
function run_chroot_ubuntu() {
    local target_root="$SCRIPT_DIR/official_ubuntu_os"
    bootstrap_ubuntu_root "$target_root" ca-certificates
    configure_ubuntu_sources "$target_root"
    sudo chroot "$target_root" apt-get update
    download_live_efi \
        "$target_root" "$SCRIPT_DIR/image/isolinux/live-efi" \
        "$TARGET_ARCH"
    judge "Export official Ubuntu Live bootloaders"
}

function download_live_efi() (
    set -euo pipefail
    target_root=$(realpath "$1")
    output=$(realpath -m "$2")
    target_arch=$3
    case "$target_arch" in
        amd64) efi_suffix=x64; grub_platform=x86_64 ;;
        arm64) efi_suffix=aa64; grub_platform=arm64 ;;
        *) echo "Unsupported Live EFI architecture: $target_arch" >&2; exit 1 ;;
    esac
    scratch=$(mktemp -d "$target_root/tmp/anduinos-live-efi.XXXXXX")
    trap 'rm -rf -- "$scratch"' EXIT

    # Use only target Ubuntu sources, as the build user rather than root.
    sudo --preserve-env=HOME chroot --userspec="$(id -u):$(id -g)" "$target_root" /bin/sh -ec '
        cd "$1"
        apt-get -o Dir::Etc::sourcelist=/etc/apt/sources.list.d/ubuntu.sources \
            -o Dir::Etc::sourceparts=- download \
            "grub-efi-$2-signed:$2" "shim-signed:$2"
    ' sh "/${scratch#"${target_root%/}/"}" "$target_arch"

    for deb in "$scratch"/*.deb; do
        dpkg-deb --extract "$deb" "$scratch/payload"
    done
    mkdir -p "$output"
    install -m 0644 "$scratch/payload/usr/lib/grub/$grub_platform-efi-signed/gcd$efi_suffix.efi.signed" "$output/grub$efi_suffix.efi"
    install -m 0644 "$scratch/payload/usr/lib/shim/shim$efi_suffix.efi.signed.latest" "$output/BOOT${efi_suffix^^}.EFI"
    install -m 0644 "$scratch/payload/usr/lib/shim/mm$efi_suffix.efi" "$output/mm$efi_suffix.efi"
)

function generate_live_grub_config() {
    local try_text="Try or Install $TARGET_BUSINESS_NAME"
    local togo_text="$TARGET_BUSINESS_NAME To Go (Persistent on USB)"
    # Our Live checker owns media verification; do not enable rd.live.check.
    local live_boot_args="root=live:CDLABEL=$LIVE_MEDIA_LABEL rd.live.dir=LiveOS rd.live.squashimg=rootfs.squashfs rd.overlay rd.anduinos.live=1"
    local verified_boot_args="$live_boot_args rd.anduinos.media-check=1"
    local regional_entries=""
    local region_count=0
    local code label timezone keyboard extra

    # The Live region is only a boot-time default; it does not constrain the installer.
    while IFS='|' read -r code label timezone keyboard extra; do
        [[ -n $code ]] || continue
        if [[ -z $label || -z $timezone || -z $keyboard || -n $extra ]]; then
            printf 'Invalid Live regional policy entry: %s\n' "$code" >&2
            return 1
        fi
        case "$code:$timezone:$keyboard" in
            *[!A-Za-z0-9_+./:@-]*)
                printf 'Unsafe Live regional policy entry: %s\n' "$code" >&2
                return 1
                ;;
        esac
        case "$label" in
            *\"*|*\\*|*\$*)
                printf 'Unsafe Live GRUB label: %s\n' "$label" >&2
                return 1
                ;;
        esac
        region_count=$((region_count + 1))
        regional_entries="$regional_entries
    menuentry \"$label\" --class lang {
        set gfxpayload=auto
        linux   /LiveOS/vmlinuz $verified_boot_args locale=$code.UTF-8 timezone=$timezone systemd.timezone=$timezone rd.anduinos.keyboard=$keyboard quiet splash ---
        initrd  /LiveOS/initrd
    }"
    done <<< "$SUPPORTED_LIVE_REGIONS"
    if ((region_count != 29)); then
        printf 'Live regional policy must contain exactly 29 entries\n' >&2
        return 1
    fi

    cat <<EOF
search --set=root --file /$TARGET_NAME

# BIOS firmware can pick 640x480 for "auto" even when larger VBE modes work.
# Prefer a readable menu there, but retain auto for older BIOS implementations.
# UEFI keeps the same automatic policy as an installed AnduinOS system.
if [ "\$grub_platform" = "pc" ]; then
    set gfxmode=1024x768,800x600,auto
else
    set gfxmode=auto
fi
if [ "\$grub_platform" = "efi" ]; then
    insmod efi_gop
else
    insmod all_video
fi
insmod gfxterm
insmod font
set theme_font_ready=0
if loadfont unicode ; then
    set theme_font_ready=1
    terminal_output gfxterm
elif loadfont /boot/grub/fonts/anduinos-unicode-16.pf2 ; then
    set theme_font_ready=1
    terminal_output gfxterm
elif loadfont /isolinux/anduinos-unicode-16.pf2 ; then
    set theme_font_ready=1
    terminal_output gfxterm
fi
if [ -f /boot/grub/themes/anduinos-hyperfluent/live-grub.cfg ]; then
    source /boot/grub/themes/anduinos-hyperfluent/live-grub.cfg
fi

set default="0"
set timeout=10

submenu "$try_text" --class anduinos {
$regional_entries
}

submenu "Advanced Options..." --class recovery {
    menuentry "$try_text (Safe Graphics)" --class driver {
        set gfxpayload=auto
        linux   /LiveOS/vmlinuz $verified_boot_args nomodeset ---
        initrd  /LiveOS/initrd
    }
    menuentry "$try_text (Console Compatibility)" --class recovery {
        set gfxpayload=auto
        linux   /LiveOS/vmlinuz $verified_boot_args quiet splash console=tty0 ---
        initrd  /LiveOS/initrd
    }
    menuentry "$try_text (Skip Media Check)" --class recovery {
        set gfxpayload=auto
        linux   /LiveOS/vmlinuz $live_boot_args quiet splash ---
        initrd  /LiveOS/initrd
    }
    menuentry "$togo_text" --class anduinos {
        # Optical media cannot hold a writable persistence partition.
        insmod regexp
        if regexp '^cd[0-9]+$' "\$root"; then
            clear
            echo 'AnduinOS To Go requires a USB drive written in DD mode with unallocated space after the image.'
            echo 'This boot medium is not supported. Powering off in 15 seconds.'
            sleep 15
            insmod halt
            halt
        fi
        set gfxpayload=auto
        linux   /LiveOS/vmlinuz root=live:CDLABEL=$LIVE_MEDIA_LABEL rd.live.dir=LiveOS rd.live.squashimg=rootfs.squashfs rd.overlay=LABEL=ANDUINOS-PERSIST rd.live.overlay.cowfs=ext4 rd.anduinos.live=1 rd.anduinos.media-check=1 quiet splash ---
        initrd  /LiveOS/initrd
    }
}

if [ "\$grub_platform" == "efi" ]; then
    menuentry "Boot from next volume" --class find.efi {
        exit 1
    }
    menuentry "UEFI Firmware Settings" --class efi {
        fwsetup
    }
fi
EOF
}

# Assemble the removable-media entry without requiring a local MOK or network.
function prepare_live_efi() (
    set -euo pipefail
    image=$(realpath "$1")
    loaders=$(realpath "$2")
    media_label=$3
    scratch=$(mktemp -d)
    trap 'rm -rf -- "$scratch"' EXIT
    printf 'search --no-floppy --label --set=anduinos_iso %s\nset prefix=($anduinos_iso)/boot/grub\nconfigfile $prefix/grub.cfg\n' \
        "$media_label" > "$scratch/grub.cfg"
    mmd -i "$image" ::/EFI ::/EFI/BOOT
    mcopy -i "$image" "$loaders"/* ::/EFI/BOOT/
    mcopy -i "$image" "$scratch/grub.cfg" ::/EFI/BOOT/grub.cfg
)

function build_iso() {
    print_ok "Building ISO image..."

    # Custom host-side hook: image/ is ready but ISO is not yet assembled.
    run_pre_iso_hook

    print_ok "Generating grub.cfg..."
    touch "image/$TARGET_NAME"
    cp "$SCRIPT_DIR/args.sh" "image/$TARGET_NAME"
    judge "Copy build args to disk"

    generate_live_grub_config > image/isolinux/grub.cfg
    judge "Generate grub.cfg"


    print_ok "Generating README.diskdefines..."
    cat << EOF > image/README.diskdefines
#define DISKNAME  Try $TARGET_BUSINESS_NAME
#define TYPE  binary
#define TYPEbinary  1
#define ARCH  $TARGET_ARCH
#define ARCH${TARGET_ARCH}  1
#define DISKNUM  1
#define DISKNUM1  1
#define TOTALNUM  0
#define TOTALNUM0  1
EOF
    judge "Generate README.diskdefines"

    DATE=$(TZ="UTC" date +"%y%m%d%H%M")
    cat << EOF > image/README.md
# $TARGET_BUSINESS_NAME $TARGET_BUILD_VERSION

$TARGET_BUSINESS_NAME is a custom Ubuntu-based Linux distribution that offers a familiar and easy-to-use experience for anyone moving to Linux.

This image is built with the following configurations:

- **Version**: $TARGET_BUILD_VERSION
- **Date**: $DATE

## Licensing and source code

$TARGET_BUSINESS_NAME includes components under different licenses. Our [ISO build scripts](https://github.com/AiursoftWeb/AnduinOS-2) are licensed under [GPLv3](https://github.com/AiursoftWeb/AnduinOS-2/blob/master/LICENSE), except where otherwise stated. Other components retain their respective licenses; including them in this image does not place the entire operating system under GPLv3.

The [package manifest](LiveOS/filesystem.manifest) is generated automatically from this image and lists its installed package names and versions.

After booting the live system or installing it, consult \`/usr/share/doc/<package>/copyright\` for each package's copyright and license notices, and \`/usr/share/common-licenses/\` for common license texts.

Our [package sources and build recipes](https://github.com/AiursoftWeb/AnduinOS-Packages) are public. See the existing [source and license references](https://github.com/AiursoftWeb/AnduinOS-2/blob/master/OSS.md#obtaining-source-code-for-a-release) for guidance on obtaining corresponding source for a release.

## Privacy

See our [privacy statement](https://www.anduinos.com/privacy.html) for the distinction between operating-system telemetry, website logs, and third-party network services.

## Please verify the checksum!!!

To verify the integrity of the image, you can calculate the md5sum of the image and compare it with the value in the file \`md5sum.txt\`.

To do this, run the following command in the terminal:

\`\`\`bash
md5sum -c md5sum.txt | grep -v 'OK'
\`\`\`

No output indicates that the image is correct.

## How to use

Press F12 to enter the boot menu when you start your computer. Select the USB drive to boot from.

## More information

For detailed instructions, please visit the [$TARGET_BUSINESS_NAME documentation](https://docs.anduinos.com/Install/System-Requirements.html).
EOF

    pushd image
    print_ok "Creating EFI boot image on /isolinux/efiboot.img..."
    (
        cd isolinux
        dd if=/dev/zero of=efiboot.img bs=1M count=10
        mkfs.vfat efiboot.img

        prepare_live_efi efiboot.img live-efi "$LIVE_MEDIA_LABEL"
        # These are build inputs, not extra files in the finished ISO.
        find live-efi -maxdepth 1 -type f -delete
        rmdir live-efi
    )
    judge "Create EFI boot image"

    # BIOS boot image — amd64-only.  ARM64 machines are pure UEFI.
    if [ "$TARGET_ARCH" = "amd64" ]; then
        print_ok "Creating BIOS boot image on /isolinux/bios.img..."
        grub-mkstandalone \
            --format=i386-pc \
            --output=isolinux/core.img \
            --install-modules="linux16 linux normal iso9660 biosdisk memdisk search tar ls font gfxterm gfxmenu png all_video configfile test regexp halt" \
            --modules="linux16 linux normal iso9660 biosdisk search font gfxterm gfxmenu png all_video configfile test regexp halt" \
            --locales="" \
            --fonts="" \
            "boot/grub/grub.cfg=isolinux/grub.cfg"
        judge "Create BIOS boot image"

        print_ok "Creating hybrid boot image on /isolinux/bios.img..."
        cat /usr/lib/grub/i386-pc/cdboot.img isolinux/core.img > isolinux/bios.img
        judge "Create hybrid boot image"
    fi

    print_ok "Creating .disk/info..."
    echo "$TARGET_BUSINESS_NAME $TARGET_BUILD_VERSION $TARGET_UBUNTU_VERSION - Release $TARGET_ARCH ($(date +%Y%m%d))" | sudo tee .disk/info
    judge "Create .disk/info"

    print_ok "Creating md5sum.txt..."
    # ISO-mode writers legitimately rewrite this config's volume references.
    # Hashing it here would falsely report corruption after a custom-label
    # rewrite, even with the namespace collision above fixed. Exclude only this
    # mutable config, not all .cfg files or any system payload. Kernel, initrd,
    # SquashFS and package manifest remain checked; whole-ISO/DD checks still
    # cover this config as well. This exception does not fix mangled boot keys:
    # media verification cannot run if rd.anduinos.live itself was rewritten.
    sudo /bin/bash -c 'find . -type f ! -name md5sum.txt ! -name bios.img ! -name efiboot.img ! -path ./isolinux/grub.cfg -print0 | xargs -0 md5sum > md5sum.txt'
    judge "Create md5sum.txt"

    print_ok "Creating iso image on $SCRIPT_DIR/$TARGET_NAME.iso (arch: $TARGET_ARCH)..."
    if [ "$TARGET_ARCH" = "amd64" ]; then
        # amd64: hybrid ISO with BIOS (El Torito) + UEFI
        sudo xorriso \
            -as mkisofs \
            -r -J \
            -iso-level 3 \
            -full-iso9660-filenames \
            -volid "$LIVE_MEDIA_LABEL" \
            -partition_offset 16 \
            -eltorito-boot boot/grub/bios.img \
                -no-emul-boot \
                -boot-load-size 4 \
                -boot-info-table \
                --eltorito-catalog boot/grub/boot.cat \
                --grub2-boot-info \
                --grub2-mbr /usr/lib/grub/i386-pc/boot_hybrid.img \
            -eltorito-alt-boot \
                -e EFI/efiboot.img \
                -no-emul-boot \
                -append_partition 2 0xef isolinux/efiboot.img \
            -output "$SCRIPT_DIR/$TARGET_NAME.iso" \
            -m "isolinux/efiboot.img" \
            -m "isolinux/bios.img" \
            -graft-points \
                "/EFI/efiboot.img=isolinux/efiboot.img" \
                "/boot/grub/grub.cfg=isolinux/grub.cfg" \
                "/boot/grub/bios.img=isolinux/bios.img" \
                "."
    else
        # arm64: UEFI-only ISO — no BIOS, no El Torito, no hybrid MBR
        sudo xorriso \
            -as mkisofs \
            -r -J \
            -iso-level 3 \
            -full-iso9660-filenames \
            -volid "$LIVE_MEDIA_LABEL" \
            -partition_offset 16 \
            -e EFI/efiboot.img \
            -no-emul-boot \
            -append_partition 2 0xef isolinux/efiboot.img \
            -appended_part_as_gpt \
            -output "$SCRIPT_DIR/$TARGET_NAME.iso" \
            -m "isolinux/efiboot.img" \
            -graft-points \
                "/EFI/efiboot.img=isolinux/efiboot.img" \
                "/boot/grub/grub.cfg=isolinux/grub.cfg" \
                "."
    fi

    judge "Create iso image"

    print_ok "Embedding the Dracut rd.live.check media checksum..."
    sudo implantisomd5 --force "$SCRIPT_DIR/$TARGET_NAME.iso"
    judge "Embed ISO media checksum"

    print_ok "Moving iso image to $SCRIPT_DIR/dist/$TARGET_BUSINESS_NAME-$TARGET_BUILD_VERSION-$DATE.iso..."
    mkdir -p "$SCRIPT_DIR/dist"
    mv "$SCRIPT_DIR/$TARGET_NAME.iso" "$SCRIPT_DIR/dist/$TARGET_BUSINESS_NAME-$TARGET_BUILD_VERSION-$DATE-$TARGET_ARCH.iso"
    judge "Move iso image"

    print_ok "Generating sha256 checksum..."
    HASH=$(sha256sum "$SCRIPT_DIR/dist/$TARGET_BUSINESS_NAME-$TARGET_BUILD_VERSION-$DATE-$TARGET_ARCH.iso" | cut -d ' ' -f 1)
    echo "SHA256: $HASH" > "$SCRIPT_DIR/dist/$TARGET_BUSINESS_NAME-$TARGET_BUILD_VERSION-$DATE-$TARGET_ARCH.sha256"
    judge "Generate sha256 checksum"

    popd
}

function umount_on_exit() {
    sleep 2
    print_ok "Unmounting filesystems before exit..."
    umount_apt_cache
    sudo umount "$SCRIPT_DIR/new_building_os/sys" || sudo umount -lf "$SCRIPT_DIR/new_building_os/sys" || true
    sudo umount "$SCRIPT_DIR/new_building_os/proc" || sudo umount -lf "$SCRIPT_DIR/new_building_os/proc" || true
    sudo umount "$SCRIPT_DIR/new_building_os/dev" || sudo umount -lf "$SCRIPT_DIR/new_building_os/dev" || true
    sudo umount "$SCRIPT_DIR/new_building_os/run" || sudo umount -lf "$SCRIPT_DIR/new_building_os/run" || true
    judge "Unmount filesystems before exit"
}

# Business call tree (staged). Each stage writes a .ok marker under
# .cache/build-state/ so `build.sh --resume` can skip completed stages:
# main
# ├── bind_signal -> umount_on_exit [EXIT callback]
# ├── clean / prepare_apt_cache / prepare_build_config
# ├── stage prepare      -> prepare_iso_directory + download_base_system
# ├── stage mount_apt    -> mount_folders (+ mount_apt_cache) + setup_apt
# ├── stage mods         -> apply_anduinos_mods [chroot, packages.json filtered]
# ├── stage custom_chroot -> custom_hooks.sh [chroot]
# ├── stage export       -> umount_folders + GRUB font/theme + export payload
# ├── stage efi          -> run_chroot_ubuntu (official signed bootloaders)
# └── stage iso          -> run_pre_iso_hook + build_iso -> dist/*.iso
# =============   main  ================
if [[ "${BASH_SOURCE[0]}" == "$0" ]]; then
    cd "$SCRIPT_DIR"

    if [[ "${1:-}" == "--resume" ]]; then
        RESUME=true
        print_ok "Resume mode: completed stages will be skipped."
        if [[ ! -d "$SCRIPT_DIR/new_building_os" ]]; then
            print_warn "new_building_os is missing; starting from scratch."
            RESUME=false
            rm -rf "$STATE_DIR"
        elif stage_is_done mount_apt && ! mountpoint -q new_building_os/proc 2>/dev/null; then
            # 进程重启后 chroot 挂载已丢失：重新挂载并重跑其后的阶段。
            print_warn "chroot mounts are gone; re-running mount and later stages."
            rm -f "$STATE_DIR/mount_apt.ok" "$STATE_DIR/mods.ok" \
                  "$STATE_DIR/custom_chroot.ok" "$STATE_DIR/export.ok"
        fi
    fi

    bind_signal
    if [[ "$RESUME" != "true" ]]; then
        clean
        rm -rf "$STATE_DIR"
    fi
    prepare_apt_cache
    prepare_build_config

    run_stage prepare stage_prepare
    run_stage mount_apt stage_mount_apt
    run_stage mods apply_anduinos_mods
    run_stage custom_chroot run_custom_chroot_hook
    run_stage export stage_export
    run_stage efi run_chroot_ubuntu
    run_stage iso build_iso

    echo "$0 - Build completed."
fi
