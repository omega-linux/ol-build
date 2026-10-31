#!/usr/bin/env bash
set -Eeuo pipefail
source "${ROOT_DIR}/config.sh"
source "${ROOT_DIR}/lib/common.sh"

command -v apt-get >/dev/null || die "only apt-based hosts are supported"

host_pkgs=(
    debootstrap ubuntu-keyring
    squashfs-tools xorriso mtools dosfstools
    grub-common grub-pc-bin grub-efi-amd64-bin grub-efi-ia32-bin
)

missing=()
for p in "${host_pkgs[@]}"; do
    dpkg-query -W -f='${Status}' "${p}" 2>/dev/null | grep -q 'install ok installed' || missing+=("${p}")
done

if [[ ${#missing[@]} -gt 0 ]]; then
    log "installing host packages: ${missing[*]}"
    apt-get update
    DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends "${missing[@]}"
else
    log "host packages already installed"
fi

script_dir=/usr/share/debootstrap/scripts
if [[ ! -e ${script_dir}/${SUITE} ]]; then
    log "debootstrap has no script for '${SUITE}', linking it to gutsy"
    ln -s gutsy "${script_dir}/${SUITE}"
fi
