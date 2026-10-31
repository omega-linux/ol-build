#!/bin/bash
set -Eeuo pipefail
export LC_ALL=C

log()  { printf '    custom-kernel: %s\n' "$*"; }
warn() { printf '\e[1;33mWARN:\e[0m custom-kernel: %s\n' "$*" >&2; }
die()  { printf '\e[1;31mERROR:\e[0m custom-kernel: %s\n' "$*" >&2; exit 1; }

kernel_re='^linux-(image|modules|modules-extra|main-modules|headers|tools|cloud-tools|buildinfo|generic)(-|$)'

installed_pkgs() {
    dpkg-query -W -f='${db:Status-Status} ${Package}\n' | awk '$1 == "installed" {print $2}' | sort -u
}
autoremovable() {
    apt-get -s autoremove | awk '$1 == "Remv" {sub(/:.*/, "", $2); print $2}' | sort -u
}

tmp=$(mktemp -d)
trap 'rm -rf "${tmp}"' EXIT

shopt -s nullglob
debs=(pkg/*.deb)
[[ ${#debs[@]} -gt 0 ]] || die "no .deb files in ${MOD_DIR}/pkg"

own_pkgs=()
kver=""
for deb in "${debs[@]}"; do
    own_pkgs+=("$(dpkg-deb -f "${deb}" Package)")
    v=$(dpkg-deb -c "${deb}" | awk '{print $6}' | sed -n 's|^\./boot/vmlinuz-||p')
    if [[ -n ${v} ]]; then
        [[ -z ${kver} ]] || die "more than one kernel image in pkg/ (${kver} and ${v})"
        kver=${v}
    fi
done
[[ -n ${kver} ]] || die "none of the packages in pkg/ contains /boot/vmlinuz-*"
printf '%s\n' "${own_pkgs[@]}" | sort -u > "${tmp}/own"
log "kernel version ${kver}"

installed_pkgs > "${tmp}/before"
apt-mark showauto | sort -u > "${tmp}/auto"
autoremovable > "${tmp}/orphans-before"

log "installing ${#debs[@]} package(s): ${own_pkgs[*]}"
apt-get install -y --no-install-recommends "${debs[@]/#/./}"
[[ -e /boot/vmlinuz-${kver} ]] || die "/boot/vmlinuz-${kver} missing after install"

config=/boot/config-${kver}
if [[ -f ${config} ]]; then
    needed=(SQUASHFS OVERLAY_FS ISO9660_FS BLK_DEV_LOOP)
    case ${SQUASHFS_COMP} in
        xz)   needed+=(SQUASHFS_XZ) ;;
        zstd) needed+=(SQUASHFS_ZSTD) ;;
        gzip) needed+=(SQUASHFS_ZLIB) ;;
        lz4)  needed+=(SQUASHFS_LZ4) ;;
        lzo)  needed+=(SQUASHFS_LZO) ;;
    esac
    missing=()
    for opt in "${needed[@]}"; do
        grep -Eq "^CONFIG_${opt}=(y|m)$" "${config}" || missing+=("CONFIG_${opt}")
    done
    [[ ${#missing[@]} -eq 0 ]] || die "kernel ${kver} lacks options the live system needs to boot: ${missing[*]}"
    if ! grep -q '^CONFIG_EFI_MIXED=y$' "${config}"; then
        warn "kernel ${kver} has no CONFIG_EFI_MIXED=y, it will not work properly on 32-bit UEFI machines"
    fi
else
    warn "no ${config}, cannot check that the kernel supports squashfs/overlayfs/iso9660/loop"
fi

{ grep -E "${kernel_re}" "${tmp}/before" || true; } | comm -23 - "${tmp}/own" > "${tmp}/remove"

if [[ -s ${tmp}/remove ]]; then
    mapfile -t remove < "${tmp}/remove"
    log "removing other kernel packages: ${remove[*]}"
    apt-get -y purge "${remove[@]}"

    installed_pkgs > "${tmp}/after"
    comm -23 "${tmp}/before" "${tmp}/after" | comm -23 - "${tmp}/remove" > "${tmp}/lost"
    if [[ -s ${tmp}/lost ]]; then
        mapfile -t lost < "${tmp}/lost"
        log "reinstalling packages apt removed together with the kernel: ${lost[*]}"
        apt-get install -y --no-install-recommends "${lost[@]}"
        comm -12 "${tmp}/lost" "${tmp}/auto" | xargs -r apt-mark auto >/dev/null
    fi

    installed_pkgs | comm -12 - "${tmp}/remove" > "${tmp}/back"
    if [[ -s ${tmp}/back ]]; then
        die "reinstalling $(tr '\n' ' ' < "${tmp}/lost")brought back kernel packages: $(tr '\n' ' ' < "${tmp}/back")"
    fi

    { autoremovable | comm -23 - "${tmp}/orphans-before" | grep -vE "${kernel_re}" || true; } > "${tmp}/keep"
    if [[ -s ${tmp}/keep ]]; then
        mapfile -t keep < "${tmp}/keep"
        log "keeping packages that only the removed kernels depended on: ${keep[*]}"
        apt-mark manual "${keep[@]}" >/dev/null
    fi
else
    log "no other kernel packages installed"
fi

others=()
for f in /boot/vmlinuz-*; do
    [[ ${f} == "/boot/vmlinuz-${kver}" ]] || others+=("${f}")
done
[[ ${#others[@]} -eq 0 ]] || warn "other kernels still in /boot (not owned by a removed package?): ${others[*]}"

if [[ ! -e /boot/initrd.img-${kver} ]]; then
    log "creating initramfs for ${kver}"
    update-initramfs -c -k "${kver}"
fi

echo "${kver}" > /boot/live-kernel
log "the ISO will boot kernel ${kver}"
