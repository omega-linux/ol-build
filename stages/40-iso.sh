#!/usr/bin/env bash
set -Eeuo pipefail
source "${ROOT_DIR}/config.sh"
source "${ROOT_DIR}/lib/common.sh"
source "${ROOT_DIR}/grub.conf"

[[ -e ${CHROOT_DIR}/etc/casper.conf ]] || die "chroot is not configured; run './do.sh configure' first"

umount_chroot

log "preparing ${IMAGE_DIR}"
rm -rf "${IMAGE_DIR}"
mkdir -p "${IMAGE_DIR}"/{casper,boot/grub,.disk}

if [[ -z ${KERNEL_VERSION} && -s ${CHROOT_DIR}/boot/live-kernel ]]; then
    KERNEL_VERSION=$(<"${CHROOT_DIR}/boot/live-kernel")
    log "kernel ${KERNEL_VERSION} selected by a mod"
fi
if [[ -n ${KERNEL_VERSION} ]]; then
    kernel="${CHROOT_DIR}/boot/vmlinuz-${KERNEL_VERSION}"
    [[ -e ${kernel} ]] || die "KERNEL_VERSION=${KERNEL_VERSION} but ${kernel} does not exist"
else
    kernel=$(find "${CHROOT_DIR}/boot" -maxdepth 1 -name 'vmlinuz-*' | sort -V | tail -n1)
    [[ -n ${kernel} ]] || die "no kernel found in ${CHROOT_DIR}/boot"
fi
kver=${kernel##*/vmlinuz-}
[[ -e ${CHROOT_DIR}/boot/initrd.img-${kver} ]] || die "no initrd for kernel ${kver}"
log "using kernel ${kver}"
cp "${kernel}" "${IMAGE_DIR}/casper/vmlinuz"
cp "${CHROOT_DIR}/boot/initrd.img-${kver}" "${IMAGE_DIR}/casper/initrd"

chroot "${CHROOT_DIR}" dpkg-query -W --showformat='${Package} ${Version}\n' \
    > "${IMAGE_DIR}/casper/filesystem.manifest"

squashfs_options
log "creating filesystem.squashfs (${SQUASHFS_ARGS[*]})"
mksquashfs "${CHROOT_DIR}" "${IMAGE_DIR}/casper/filesystem.squashfs" \
    -noappend -wildcards "${SQUASHFS_ARGS[@]}" \
    -e 'proc/*' 'sys/*' 'dev/*' 'run/*' 'tmp/*' 'boot/*' "${CHROOT_BUILD_DIR#/}"

du -sx --block-size=1 "${CHROOT_DIR}" | cut -f1 > "${IMAGE_DIR}/casper/filesystem.size"

echo "Ubuntu ${VERSION} Live \"${SUITE}\" - ${ARCH} ($(date -u +%Y%m%d))" \
    > "${IMAGE_DIR}/.disk/info"
touch "${IMAGE_DIR}/ubuntu"   # marker file GRUB uses to find the medium

cat > "${IMAGE_DIR}/boot/grub/grub.cfg" <<EOF
search --no-floppy --set=root --file /ubuntu

insmod all_video
insmod gfxterm
terminal_output gfxterm

set default=${GRUB_DEFAULT}
set timeout=${GRUB_TIMEOUT}

menuentry "${GRUB_ENTRY_LIVE}" {
    linux  /casper/vmlinuz boot=casper ${BOOT_OPTIONS} ---
    initrd /casper/initrd
}
menuentry "${GRUB_ENTRY_SAFE}" {
    linux  /casper/vmlinuz boot=casper nomodeset ---
    initrd /casper/initrd
}
menuentry "${GRUB_ENTRY_TORAM}" {
    linux  /casper/vmlinuz boot=casper toram ${BOOT_OPTIONS} ---
    initrd /casper/initrd
}
if [ "\${grub_platform}" = "efi" ]; then
    menuentry "${GRUB_ENTRY_FIRMWARE}" { fwsetup }
fi
menuentry "${GRUB_ENTRY_REBOOT}" { reboot }
menuentry "${GRUB_ENTRY_SHUTDOWN}" { halt }
EOF

for platform in i386-pc x86_64-efi i386-efi; do
    [[ -d /usr/lib/grub/${platform} ]] || die "GRUB platform ${platform} is not installed on the host; run './do.sh deps'"
done

iso="${OUT_DIR}/${ISO_NAME}"
log "writing ${iso}"
mkdir -p "${OUT_DIR}"
rm -f "${iso}"
grub-mkrescue \
    --output="${iso}" \
    "${IMAGE_DIR}" \
    -- -volid "${ISO_LABEL}"

efi_files=$(xorriso -indev "${iso}" -find /efi/boot -type f 2>/dev/null | tr '[:upper:]' '[:lower:]')
for loader in bootx64.efi bootia32.efi; do
    [[ ${efi_files} == *"/efi/boot/${loader}"* ]] || die "${loader} is missing from ${iso}"
done
log "boot loaders: BIOS, UEFI x86_64 (bootx64.efi), UEFI ia32 (bootia32.efi)"

(cd "${OUT_DIR}" && sha256sum "${ISO_NAME}" > "${ISO_NAME}.sha256")
log "ISO ready: ${iso} ($(du -h "${iso}" | cut -f1))"
