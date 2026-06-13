#!/bin/bash

#==========================
# Set up the environment
#==========================
set -e                  # exit on error
set -o pipefail         # exit on pipeline error
set -u                  # treat unset variable as error
export SCRIPT_DIR="$(dirname "$(readlink -f "$0")")"

source $SCRIPT_DIR/shared.sh
source $SCRIPT_DIR/args.sh

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

    print_ok "Calling debootstrap to download base debian system..."
    sudo debootstrap  --arch=amd64 --variant=minbase --include=ca-certificates,wget,dbus $TARGET_UBUNTU_VERSION new_building_os $APT_SOURCE
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
    sudo cp -r $SCRIPT_DIR/mods new_building_os/root/mods
    sudo cp $SCRIPT_DIR/args.sh   new_building_os/root/mods/args.sh
    sudo cp $SCRIPT_DIR/shared.sh new_building_os/root/mods/shared.sh
}

function setup_apt() {
    print_ok "Setting up Ubuntu apt sources in chroot..."
    sudo tee new_building_os/etc/apt/sources.list > /dev/null <<EOF
deb $APT_SOURCE $TARGET_UBUNTU_VERSION main restricted universe multiverse
deb $APT_SOURCE $TARGET_UBUNTU_VERSION-updates main restricted universe multiverse
deb $APT_SOURCE $TARGET_UBUNTU_VERSION-backports main restricted universe multiverse
deb $APT_SOURCE $TARGET_UBUNTU_VERSION-security main restricted universe multiverse
EOF
    judge "Set up Ubuntu apt sources"

    print_ok "Setting up AnduinOS APKG apt source in chroot..."

    local keyring_path="new_building_os/usr/share/keyrings/anduinos-archive-keyring.gpg"
    local cert_url="$APKG_SERVER/artifacts/certs/$APKG_CERT_NAME"

    print_ok "Downloading GPG keyring from $cert_url ..."
    sudo mkdir -p new_building_os/usr/share/keyrings
    curl -sL "$cert_url" | sed '1s/^\xEF\xBB\xBF//' | gpg --dearmor | sudo tee "$keyring_path" > /dev/null
    judge "Download and dearmor keyring"

    print_ok "Generating anduinos.sources for $APKG_SERVER (suite: $TARGET_UBUNTU_VERSION-addon)..."
    sudo mkdir -p new_building_os/etc/apt/sources.list.d
    sudo tee new_building_os/etc/apt/sources.list.d/anduinos.sources > /dev/null <<EOF
Types: deb
URIs: $APKG_SERVER/artifacts/anduinos/
Suites: $TARGET_UBUNTU_VERSION-addon
Components: main
Architectures: amd64
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

function build_iso() {
    print_ok "Building ISO image..."

    print_ok "Creating image directory..."
    sudo rm -rf image
    mkdir -p image/{casper,isolinux,.disk}
    judge "Create image directory"

    # copy kernel files
    print_ok "Copying kernel files as /casper/vmlinuz, /casper/initrd and /casper/initrd.gz..."
    # Resolve the distro-maintained symlinks — they always point to the
    # current kernel, so we never pick a stale one left behind by apt.
    REAL_VMLINUZ=$(readlink -f new_building_os/vmlinuz 2>/dev/null)
    [ -f "$REAL_VMLINUZ" ] || REAL_VMLINUZ=$(readlink -f new_building_os/boot/vmlinuz 2>/dev/null)
    REAL_INITRD=$(readlink -f new_building_os/initrd.img 2>/dev/null)
    [ -f "$REAL_INITRD" ] || REAL_INITRD=$(readlink -f new_building_os/boot/initrd.img 2>/dev/null)
    if [ -z "$REAL_VMLINUZ" ] || [ ! -f "$REAL_VMLINUZ" ]; then
        print_error "No kernel found via vmlinuz symlink in new_building_os/"
        exit 1
    fi
    sudo cp "$REAL_VMLINUZ" image/casper/vmlinuz
    # Keep both names for remix compatibility:
    # - Legacy BIOS core.img may embed "/casper/initrd"
    # - Some remix tools (e.g. Cubic) may rewrite text grub.cfg to "/casper/initrd.gz"
    # Having both avoids boot mismatch between BIOS and UEFI paths.
    sudo cp "$REAL_INITRD" image/casper/initrd
    sudo cp "$REAL_INITRD" image/casper/initrd.gz
    judge "Copy kernel files"

    print_ok "Generating grub.cfg..."
    touch image/$TARGET_NAME
    cp $SCRIPT_DIR/args.sh image/$TARGET_NAME
    judge "Copy build args to disk"

    # Configurations are setup in new_building_os/usr/share/initramfs-tools/scripts/casper-bottom/25configure_init
    TRY_TEXT="Try or Install $TARGET_BUSINESS_NAME"
    TOGO_TEXT="$TARGET_BUSINESS_NAME To Go (Persistent on USB)"

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
        set gfxpayload=keep
        linux   /casper/vmlinuz boot=casper locale=${_code}.UTF-8 timezone=${_tz} systemd.timezone=${_tz} nopersistent quiet splash ---
        initrd  /casper/initrd
    }"
    done <<< "$SUPPORTED_LOCALES"

    # Copy system unicode.pf2 so GRUB can render CJK/Arabic/Thai labels.
    # Without loadfont, GRUB defaults to an ASCII-only built-in font.
    # Placed in both paths: isolinux (BIOS) and boot/grub/fonts (UEFI standard).
    print_ok "Preparing GRUB unicode font (for CJK)..."
    mkdir -p image/isolinux image/boot/grub/fonts
    cp /usr/share/grub/unicode.pf2 image/isolinux/unicode.pf2
    cp /usr/share/grub/unicode.pf2 image/boot/grub/fonts/unicode.pf2
    judge "Prepare GRUB unicode font"

    cat << EOF > image/isolinux/grub.cfg

search --set=root --file /$TARGET_NAME

insmod all_video
insmod gfxterm
insmod font
if loadfont /boot/grub/fonts/unicode.pf2 ; then
    terminal_output gfxterm
elif loadfont /isolinux/unicode.pf2 ; then
    terminal_output gfxterm
fi

set default="0"
set timeout=10

submenu "$TRY_TEXT" {
$_TRY_LOCALE_ENTRIES
}

submenu "Advanced Options..." {
    menuentry "$TRY_TEXT (Safe Graphics)" {
        set gfxpayload=keep
        linux   /casper/vmlinuz boot=casper nopersistent nomodeset ---
        initrd  /casper/initrd
    }
    menuentry "$TOGO_TEXT" {
       set gfxpayload=keep
       linux   /casper/vmlinuz boot=casper persistent quiet splash ---
       initrd  /casper/initrd
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
    print_ok "Generating manifes for filesystem..."
    sudo chroot new_building_os dpkg-query -W --showformat='${Package} ${Version}\n' | sudo tee image/casper/filesystem.manifest >/dev/null 2>&1
    judge "Generate manifest for filesystem"

    print_ok "Generating manifest for filesystem-desktop..."
    sudo cp -v image/casper/filesystem.manifest image/casper/filesystem.manifest-desktop
    for pkg in $TARGET_PACKAGE_REMOVE; do
        sudo sed -i "/^$pkg /d" image/casper/filesystem.manifest-desktop
    done
    judge "Generate manifest for filesystem-desktop"

    print_ok "Compressing rootfs as squashfs on /casper/filesystem.squashfs..."
    sudo mksquashfs new_building_os image/casper/filesystem.squashfs \
        -noappend -no-duplicates -no-recovery \
        -wildcards -b 1M \
        -comp zstd -Xcompression-level 19 \
        -e "var/cache/apt/archives/*" \
        -e "tmp/*" \
        -e "tmp/.*" \
        -e "swapfile"
    judge "Compress rootfs"

    print_ok "Verifying the integrity of filesystem.squashfs..."
    if sudo unsquashfs -s image/casper/filesystem.squashfs; then
        print_ok "Verification successful. The file appears to be valid."
    else
        print_error "Verification FAILED! The squashfs file is likely corrupt."
        exit 1
    fi
    
    print_ok "Generating filesystem.size on /casper/filesystem.size..."
    printf $(sudo du -sx --block-size=1 new_building_os | cut -f1) > image/casper/filesystem.size
    judge "Generate filesystem.size"

    print_ok "Generating README.diskdefines..."
    cat << EOF > image/README.diskdefines
#define DISKNAME  Try $TARGET_BUSINESS_NAME
#define TYPE  binary
#define TYPEbinary  1
#define ARCH  amd64
#define ARCHamd64  1
#define DISKNUM  1
#define DISKNUM1  1
#define TOTALNUM  0
#define TOTALNUM0  1
EOF
    judge "Generate README.diskdefines"

    DATE=`TZ="UTC" date +"%y%m%d%H%M"`
    cat << EOF > image/README.md
# $TARGET_BUSINESS_NAME $TARGET_BUILD_VERSION

$TARGET_BUSINESS_NAME is a custom Ubuntu-based Linux distribution that offers a familiar and easy-to-use experience for anyone moving to Linux.

This image is built with the following configurations:

- **Version**: $TARGET_BUILD_VERSION
- **Date**: $DATE

$TARGET_BUSINESS_NAME is distributed with GPLv3 license. You can find the license on [GPL-v3](https://github.com/aiursoftweb/anduinos-2/blob/master/LICENSE).

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

For detailed instructions, please visit [$TARGET_BUSINESS_NAME Document](https://docs.anduinos.com/Install/System-Requirements.html).
EOF

    pushd image
    print_ok "Creating EFI boot image on /isolinux/efiboot.img..."
    (
        cd isolinux && \
        dd if=/dev/zero of=efiboot.img bs=1M count=10 && \
        sudo mkfs.vfat efiboot.img && \
        mkdir efi && \
        sudo mount efiboot.img efi

        if ! sudo grub-install --target=x86_64-efi --efi-directory=efi --boot-directory=boot --uefi-secure-boot --removable --no-nvram; then
            sudo umount efi
            print_error "grub-install failed!"
            exit 1
        fi

        sudo umount efi && \
        rm -rf efi
    )
    judge "Create EFI boot image"

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

    print_ok "Creating .disk/info..."
    echo "$TARGET_BUSINESS_NAME $TARGET_BUILD_VERSION $TARGET_UBUNTU_VERSION - Release amd64 ($(date +%Y%m%d))" | sudo tee .disk/info
    judge "Create .disk/info"

    print_ok "Creating md5sum.txt..."
    sudo /bin/bash -c "(find . -type f -print0 | xargs -0 md5sum | grep -v -e 'md5sum.txt' -e 'bios.img' -e 'efiboot.img' > md5sum.txt)"
    judge "Create md5sum.txt"

    print_ok "Creating iso image on $SCRIPT_DIR/$TARGET_NAME.iso..."
    sudo xorriso \
        -as mkisofs \
        -r -J \
        -iso-level 3 \
        -full-iso9660-filenames \
        -volid "$TARGET_NAME" \
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

    judge "Create iso image"

    print_ok "Moving iso image to $SCRIPT_DIR/dist/$TARGET_BUSINESS_NAME-$TARGET_BUILD_VERSION-$DATE.iso..."
    mkdir -p "$SCRIPT_DIR/dist"
    mv "$SCRIPT_DIR/$TARGET_NAME.iso" "$SCRIPT_DIR/dist/$TARGET_BUSINESS_NAME-$TARGET_BUILD_VERSION-$DATE.iso"
    judge "Move iso image"

    print_ok "Generating sha256 checksum..."
    HASH=$(sha256sum "$SCRIPT_DIR/dist/$TARGET_BUSINESS_NAME-$TARGET_BUILD_VERSION-$DATE.iso" | cut -d ' ' -f 1)
    echo "SHA256: $HASH" > "$SCRIPT_DIR/dist/$TARGET_BUSINESS_NAME-$TARGET_BUILD_VERSION-$DATE.sha256"
    judge "Generate sha256 checksum"

    popd
}

function umount_on_exit() {
    sleep 2
    print_ok "Umount before exit..."
    sudo umount $SCRIPT_DIR/new_building_os/sys || sudo umount -lf $SCRIPT_DIR/new_building_os/sys || true
    sudo umount $SCRIPT_DIR/new_building_os/proc || sudo umount -lf $SCRIPT_DIR/new_building_os/proc || true
    sudo umount $SCRIPT_DIR/new_building_os/dev || sudo umount -lf $SCRIPT_DIR/new_building_os/dev || true
    sudo umount $SCRIPT_DIR/new_building_os/run || sudo umount -lf $SCRIPT_DIR/new_building_os/run || true
    judge "Umount before exit"
}

# =============   main  ================
cd $SCRIPT_DIR
bind_signal
clean
download_base_system
mount_folders
setup_apt
run_chroot
umount_folders
build_iso
echo "$0 - Initial build is done!"
