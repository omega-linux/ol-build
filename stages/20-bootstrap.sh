#!/usr/bin/env bash
set -Eeuo pipefail
source "${ROOT_DIR}/config.sh"
source "${ROOT_DIR}/lib/common.sh"

if [[ -e ${CHROOT_DIR}/etc/os-release ]]; then
    die "${CHROOT_DIR} already contains a system; run './do.sh clean' first"
fi

mkdir -p "${CHROOT_DIR}"
log "debootstrapping ${SUITE}/${ARCH} from ${MIRROR}"
debootstrap \
    --arch="${ARCH}" \
    --variant=minbase \
    --components="${COMPONENTS// /,}" \
    "${SUITE}" "${CHROOT_DIR}" "${MIRROR}"
