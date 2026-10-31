#!/usr/bin/env bash
# remove workdirs
set -Eeuo pipefail
source "${ROOT_DIR}/config.sh"
source "${ROOT_DIR}/lib/common.sh"

umount_chroot
assert_nothing_mounted "${WORK_DIR}"
log "removing ${WORK_DIR}"
rm -rf --one-file-system "${WORK_DIR}"
