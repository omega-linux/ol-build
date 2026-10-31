#!/usr/bin/env bash
set -Eeuo pipefail
source "${ROOT_DIR}/config.sh"
source "${ROOT_DIR}/lib/common.sh"

order="${MODS_DIR}/order"
if [[ ! -s ${order} ]] || ! grep -qvE '^[[:space:]]*(#|$)' "${order}"; then
    log "no mods listed in ${order}, skipping"
    exit 0
fi

trap chroot_leave EXIT
chroot_enter

cp -a "${MODS_DIR}" "${CHROOT_DIR}${CHROOT_BUILD_DIR}/mods"

log "running mods inside the chroot"
chroot_exec run-mods.sh
chroot_exec finalize.sh
