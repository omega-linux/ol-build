#!/usr/bin/env bash
# usage: sudo ./do.sh [stage...]
#   (no args)   full build from scratch: clean, deps, bootstrap, configure, mods, iso
#   deps        install host build tools
#   bootstrap   debootstrap a fresh base system into work/chroot
#   configure   install kernel, casper and configure the base live system
#   mods        run the mods listed in mods/order inside the chroot
#   iso         build the squashfs + bootable hybrid (BIOS/UEFI) ISO in out/
#   clean       remove work/ (out/ is kept)
#
# settings are in config.sh and can be overridden from the environment.
set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
export ROOT_DIR
# shellcheck source=config.sh
source "${ROOT_DIR}/config.sh"
# shellcheck source=lib/common.sh
source "${ROOT_DIR}/lib/common.sh"

STAGES_DIR="${ROOT_DIR}/stages"

usage() { sed -n '2,13s/^# \{0,1\}//p' "$0"; }

run_stage() {
    local name=$1 script
    case ${name} in
        clean)     script=00-clean.sh ;;
        deps)      script=10-host-deps.sh ;;
        bootstrap) script=20-bootstrap.sh ;;
        configure) script=30-configure.sh ;;
        mods)      script=35-mods.sh ;;
        iso)       script=40-iso.sh ;;
        *) usage; die "unknown stage: ${name}" ;;
    esac
    log "stage: ${name}"
    bash "${STAGES_DIR}/${script}" || die "stage '${name}' failed (exit $?), stopping the build"
}

main() {
    case ${1:-} in -h|--help|help) usage; exit 0 ;; esac
    require_root
    squashfs_options
    local stages=("$@")
    [[ ${#stages[@]} -gt 0 ]] || stages=(clean deps bootstrap configure mods iso)

    mkdir -p "${WORK_DIR}" "${OUT_DIR}"
    local start=${SECONDS} s
    for s in "${stages[@]}"; do
        run_stage "${s}"
    done
    log "done in $(( (SECONDS - start) / 60 ))m $(( (SECONDS - start) % 60 ))s"
}

main "$@" 2>&1 | tee "${ROOT_DIR}/build.log"
exit "${PIPESTATUS[0]}"
