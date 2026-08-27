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

# Map Debian arch name to GRUB target name (amd64 -> x86_64, arm64 -> arm64)
case "$TARGET_ARCH" in
    amd64) GRUB_EFI_TARGET="x86_64-efi" ;;
    arm64) GRUB_EFI_TARGET="arm64-efi" ;;
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
    sudo rm -rf new_building_os image || true
    judge "Clean up build artifacts"
}

function download_base_system() {
    print_ok "Creating new_building_os directory..."
    sudo mkdir -p new_building_os
    judge "Create build directory"

    print_ok "Calling debootstrap to download base system (arch: $TARGET_ARCH)..."
    sudo debootstrap --arch="$TARGET_ARCH" --variant=minbase \
        --include=ca-certificates,wget,dbus \
        "$TARGET_UBUNTU_VERSION" new_building_os "$APT_SOURCE"
    judge "Download base system"
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
}

function setup_apt() {
    print_ok "Setting up Ubuntu apt sources in chroot..."
    sudo mkdir -p new_building_os/etc/apt/sources.list.d
    sudo tee new_building_os/etc/apt/sources.list.d/ubuntu.sources > /dev/null <<EOF
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
    sudo rm -f new_building_os/etc/apt/sources.list

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

function run_chroot() {
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

function prepare_iso_directory() {
    print_ok "Creating image directory..."
    sudo rm -rf image
    mkdir -p image/{LiveOS,isolinux,.disk}
    judge "Create image directory"
}

function prepare_live_grub_font() {
    print_ok "Generating 28px Unicode font for the Live ISO..."
    mkdir -p \
        image/isolinux \
        image/boot/grub/fonts
    grub-mkfont \
        --size="28" \
        --output="image/isolinux/anduinos-unicode-28.pf2" \
        "/usr/share/fonts/opentype/unifont/unifont.otf"
    cp "image/isolinux/anduinos-unicode-28.pf2" \
        "image/boot/grub/fonts/anduinos-unicode-28.pf2"
    judge "Prepare readable Live GRUB font"
}

function build_iso() {
    print_ok "Building ISO image..."

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

    print_ok "Generating grub.cfg..."
    touch "image/$TARGET_NAME"
    cp "$SCRIPT_DIR/args.sh" "image/$TARGET_NAME"
    judge "Copy build args to disk"

    TRY_TEXT="Try or Install $TARGET_BUSINESS_NAME"
    TOGO_TEXT="$TARGET_BUSINESS_NAME To Go (Persistent on USB)"
    LIVE_BOOT_ARGS="root=live:CDLABEL=$TARGET_NAME rd.live.dir=LiveOS rd.live.squashimg=rootfs.squashfs rd.overlay rd.anduinos.live=1"

    # Build locale submenu entries for Try mode.
    # Each entry also derives a best-guess timezone so the live session
    # clock matches the user's region, not hardcoded Los Angeles.
    _TRY_LOCALE_ENTRIES=""
    while IFS="|" read -r _code _label; do
        [ -z "$_code" ] && continue
        [ -z "$_label" ] && continue

        # locale -> timezone best-guess mapping
        case "${_code}" in
            en_US) _tz="America/New_York" ;;
            en_GB) _tz="Europe/London" ;;
            zh_CN) _tz="Asia/Shanghai" ;;
            zh_TW) _tz="Asia/Taipei" ;;
            zh_HK) _tz="Asia/Hong_Kong" ;;
            ja_JP) _tz="Asia/Tokyo" ;;
            ko_KR) _tz="Asia/Seoul" ;;
            vi_VN) _tz="Asia/Ho_Chi_Minh" ;;
            th_TH) _tz="Asia/Bangkok" ;;
            de_DE) _tz="Europe/Berlin" ;;
            fr_FR) _tz="Europe/Paris" ;;
            es_ES) _tz="Europe/Madrid" ;;
            ru_RU) _tz="Europe/Moscow" ;;
            it_IT) _tz="Europe/Rome" ;;
            pt_PT) _tz="Europe/Lisbon" ;;
            pt_BR) _tz="America/Sao_Paulo" ;;
            ar_SA) _tz="Asia/Riyadh" ;;
            nl_NL) _tz="Europe/Amsterdam" ;;
            sv_SE) _tz="Europe/Stockholm" ;;
            pl_PL) _tz="Europe/Warsaw" ;;
            tr_TR) _tz="Europe/Istanbul" ;;
            ro_RO) _tz="Europe/Bucharest" ;;
            da_DK) _tz="Europe/Copenhagen" ;;
            uk_UA) _tz="Europe/Kiev" ;;
            id_ID) _tz="Asia/Jakarta" ;;
            fi_FI) _tz="Europe/Helsinki" ;;
            hi_IN) _tz="Asia/Kolkata" ;;
            el_GR) _tz="Europe/Athens" ;;
            *)      _tz="America/Los_Angeles" ;;
        esac

        _TRY_LOCALE_ENTRIES="$_TRY_LOCALE_ENTRIES
    menuentry \"$_label\" {
        set gfxpayload=auto
        linux   /LiveOS/vmlinuz $LIVE_BOOT_ARGS locale=${_code}.UTF-8 timezone=${_tz} systemd.timezone=${_tz} quiet splash ---
        initrd  /LiveOS/initrd
    }"
    done <<< "$SUPPORTED_LOCALES"

    cat << EOF > image/isolinux/grub.cfg

search --set=root --file /$TARGET_NAME

set gfxmode=1440x900,1280x800,1280x720,1024x768,auto
insmod all_video
insmod gfxterm
insmod font
if loadfont /boot/grub/fonts/anduinos-unicode-28.pf2 ; then
    terminal_output gfxterm
elif loadfont /isolinux/anduinos-unicode-28.pf2 ; then
    terminal_output gfxterm
fi

set default="0"
set timeout=10

submenu "$TRY_TEXT" {
$_TRY_LOCALE_ENTRIES
}

submenu "Advanced Options..." {
    menuentry "$TRY_TEXT (Safe Graphics)" {
        set gfxpayload=auto
        linux   /LiveOS/vmlinuz $LIVE_BOOT_ARGS nomodeset ---
        initrd  /LiveOS/initrd
    }
    menuentry "$TOGO_TEXT" {
        set gfxpayload=auto
        linux   /LiveOS/vmlinuz root=live:CDLABEL=$TARGET_NAME rd.live.dir=LiveOS rd.live.squashimg=rootfs.squashfs rd.overlay=LABEL=ANDUINOS-PERSIST rd.live.overlay.cowfs=ext4 rd.anduinos.live=1 quiet splash ---
        initrd  /LiveOS/initrd
    }
    menuentry "Check installation media for defects (Integrity Check)" {
        set gfxpayload=auto
        linux   /LiveOS/vmlinuz $LIVE_BOOT_ARGS rd.live.check=1 quiet splash ---
        initrd  /LiveOS/initrd
    }
}

if [ "\$grub_platform" == "efi" ]; then
    menuentry "Boot from next volume" {
        exit 1
    }
    menuentry "UEFI Firmware Settings" {
        fwsetup
    }
fi
EOF
    judge "Generate grub.cfg"


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

$TARGET_BUSINESS_NAME is distributed under the GPLv3 license. You can find the license at [GPL-v3](https://github.com/aiursoftweb/anduinos-2/blob/master/LICENSE).

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

        if [ "$TARGET_ARCH" = arm64 ]; then
            target_root="$SCRIPT_DIR/new_building_os"
            arm64_shim="$target_root/usr/lib/shim/shimaa64.efi.signed.latest"
            arm64_grub="$target_root/usr/lib/grub/arm64-efi-signed/gcdaa64.efi.signed"
            arm64_mok="$target_root/usr/lib/shim/mmaa64.efi"

            # The signed Canonical config-delivery GRUB image already embeds
            # FAT, ISO9660, GPT, search and configfile support. Build the
            # removable-media ESP directly from the completed ARM64 target;
            # this avoids installing a foreign shim package that conflicts
            # with an amd64 build host's own bootloader.
            cat > arm64-grub.cfg <<EOF
search --no-floppy --label --set=anduinos_iso $TARGET_NAME
set prefix=(\$anduinos_iso)/boot/grub
configfile \$prefix/grub.cfg
EOF
            printf 'shimaa64.efi,%s,,This is the boot entry for %s\n' \
                "$TARGET_BUSINESS_NAME" "$TARGET_BUSINESS_NAME" \
                | iconv -f UTF-8 -t UTF-16LE > BOOTAA64.CSV

            mmd -i efiboot.img ::/EFI ::/EFI/BOOT
            mcopy -i efiboot.img "$arm64_shim" ::/EFI/BOOT/BOOTAA64.EFI
            mcopy -i efiboot.img "$arm64_grub" ::/EFI/BOOT/grubaa64.efi
            mcopy -i efiboot.img "$arm64_mok" ::/EFI/BOOT/mmaa64.efi
            mcopy -i efiboot.img BOOTAA64.CSV ::/EFI/BOOT/BOOTAA64.CSV
            mcopy -i efiboot.img arm64-grub.cfg ::/EFI/BOOT/grub.cfg
            rm -f BOOTAA64.CSV arm64-grub.cfg
        else
            mkdir efi boot
            sudo mount efiboot.img efi
            if ! sudo grub-install \
                --target="$GRUB_EFI_TARGET" \
                --efi-directory=efi \
                --boot-directory=boot \
                --uefi-secure-boot \
                --removable \
                --no-nvram; then
                sudo umount efi
                print_error "grub-install failed!"
                exit 1
            fi
            sudo umount efi
            rm -rf efi
        fi
    )
    judge "Create EFI boot image"

    # BIOS boot image — amd64-only.  ARM64 machines are pure UEFI.
    if [ "$TARGET_ARCH" = "amd64" ]; then
        print_ok "Creating BIOS boot image on /isolinux/bios.img..."
        grub-mkstandalone \
            --format=i386-pc \
            --output=isolinux/core.img \
            --install-modules="linux16 linux normal iso9660 biosdisk memdisk search tar ls font gfxterm all_video" \
            --modules="linux16 linux normal iso9660 biosdisk search font gfxterm all_video" \
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
    if [ "$TARGET_ARCH" = "amd64" ]; then
        sudo /bin/bash -c "(find . -type f -print0 | xargs -0 md5sum | grep -v -e 'md5sum.txt' -e 'bios.img' -e 'efiboot.img' > md5sum.txt)"
    else
        sudo /bin/bash -c "(find . -type f -print0 | xargs -0 md5sum | grep -v -e 'md5sum.txt' -e 'efiboot.img' > md5sum.txt)"
    fi
    judge "Create md5sum.txt"

    print_ok "Creating iso image on $SCRIPT_DIR/$TARGET_NAME.iso (arch: $TARGET_ARCH)..."
    if [ "$TARGET_ARCH" = "amd64" ]; then
        # amd64: hybrid ISO with BIOS (El Torito) + UEFI
        sudo xorriso \
            -as mkisofs \
            -r -J \
            -iso-level 3 \
            -full-iso9660-filenames \
            -volid "$TARGET_NAME" \
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
            -volid "$TARGET_NAME" \
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
    sudo umount "$SCRIPT_DIR/new_building_os/sys" || sudo umount -lf "$SCRIPT_DIR/new_building_os/sys" || true
    sudo umount "$SCRIPT_DIR/new_building_os/proc" || sudo umount -lf "$SCRIPT_DIR/new_building_os/proc" || true
    sudo umount "$SCRIPT_DIR/new_building_os/dev" || sudo umount -lf "$SCRIPT_DIR/new_building_os/dev" || true
    sudo umount "$SCRIPT_DIR/new_building_os/run" || sudo umount -lf "$SCRIPT_DIR/new_building_os/run" || true
    judge "Unmount filesystems before exit"
}

# =============   main  ================
cd "$SCRIPT_DIR"
bind_signal
clean
download_base_system
mount_folders
setup_apt
run_chroot
umount_folders
prepare_iso_directory
prepare_live_grub_font
build_iso
echo "$0 - Build completed."
