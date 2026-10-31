#!/usr/bin/env bash
set -Eeuo pipefail
source "${ROOT_DIR}/config.sh"
source "${ROOT_DIR}/lib/common.sh"

trap chroot_leave EXIT
chroot_enter

log "configuring the base system inside the chroot"
chroot_exec configure.sh
chroot_exec finalize.sh
