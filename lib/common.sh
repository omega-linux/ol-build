CHROOT_BUILD_DIR=/root/live-build

log()  { printf '\e[1;34m==>\e[0m %s\n' "$*"; }
warn() { printf '\e[1;33mWARN:\e[0m %s\n' "$*" >&2; }
die()  { printf '\e[1;31mERROR:\e[0m %s\n' "$*" >&2; exit 1; }

trap 'rc=$?; printf "\e[1;31mERROR:\e[0m command failed (exit %s) at %s:%s: %s\n" "${rc}" "${BASH_SOURCE[0]:-$0}" "${LINENO}" "${BASH_COMMAND}" >&2; exit "${rc}"' ERR

require_root() {
    [[ ${EUID} -eq 0 ]] || die "this must run as root (try: sudo $0)"
}

mount_chroot() {
    local d
    for d in dev dev/pts proc sys run; do
        mkdir -p "${CHROOT_DIR}/${d}"
    done
    mountpoint -q "${CHROOT_DIR}/dev"     || mount --bind /dev "${CHROOT_DIR}/dev"
    mountpoint -q "${CHROOT_DIR}/dev/pts" || mount -t devpts devpts "${CHROOT_DIR}/dev/pts" -o gid=5,mode=620
    mountpoint -q "${CHROOT_DIR}/proc"    || mount -t proc proc "${CHROOT_DIR}/proc"
    mountpoint -q "${CHROOT_DIR}/sys"     || mount -t sysfs sysfs "${CHROOT_DIR}/sys"
    mountpoint -q "${CHROOT_DIR}/run"     || mount -t tmpfs tmpfs "${CHROOT_DIR}/run"
}

umount_chroot() {
    local d
    [[ -d ${CHROOT_DIR} ]] || return 0
    for d in run sys proc dev/pts dev; do
        if mountpoint -q "${CHROOT_DIR}/${d}"; then
            umount "${CHROOT_DIR}/${d}" 2>/dev/null || umount -l "${CHROOT_DIR}/${d}"
        fi
    done
}

chroot_enter() {
    [[ -e ${CHROOT_DIR}/etc/os-release ]] || die "no base system in ${CHROOT_DIR}; run './do.sh bootstrap' first"
    mount_chroot

    rm -f "${CHROOT_DIR}/etc/resolv.conf"
    cp -L /etc/resolv.conf "${CHROOT_DIR}/etc/resolv.conf"

    printf '#!/bin/sh\nexit 101\n' > "${CHROOT_DIR}/usr/sbin/policy-rc.d"
    chmod +x "${CHROOT_DIR}/usr/sbin/policy-rc.d"

    rm -rf "${CHROOT_DIR}${CHROOT_BUILD_DIR}"
    mkdir -p "${CHROOT_DIR}${CHROOT_BUILD_DIR}"
    cp "${ROOT_DIR}/config.sh" "${ROOT_DIR}"/chroot/*.sh "${CHROOT_DIR}${CHROOT_BUILD_DIR}/"
}

chroot_leave() {
    [[ -d ${CHROOT_DIR}/etc ]] || return 0
    rm -rf "${CHROOT_DIR}${CHROOT_BUILD_DIR}"
    rm -f "${CHROOT_DIR}/usr/sbin/policy-rc.d"
    ln -sfn ../run/systemd/resolve/stub-resolv.conf "${CHROOT_DIR}/etc/resolv.conf"
    umount_chroot
}

chroot_exec() {
    chroot "${CHROOT_DIR}" /usr/bin/env -i \
        HOME=/root TERM="${TERM:-xterm}" PATH=/usr/sbin:/usr/bin:/sbin:/bin \
        ROOT_DIR="${CHROOT_BUILD_DIR}" \
        /bin/bash "${CHROOT_BUILD_DIR}/$1"
}

squashfs_options() {
    local defaults
    case ${SQUASHFS_COMP} in
        xz)   defaults="-b 1M -Xdict-size 100% -Xbcj x86" ;;
        zstd) defaults="-b 1M -Xcompression-level 19" ;;
        gzip) defaults="-b 1M -Xcompression-level 9" ;;
        lz4)  defaults="-b 1M -Xhc" ;;
        lzo)  defaults="-b 1M" ;;
        *) die "SQUASHFS_COMP='${SQUASHFS_COMP}' is not supported; use xz, zstd, gzip, lz4 or lzo" ;;
    esac
    local extra
    read -ra extra <<< "${SQUASHFS_OPTS:-${defaults}}"
    SQUASHFS_ARGS=(-comp "${SQUASHFS_COMP}" "${extra[@]}")
}

assert_nothing_mounted() {
    local dir=$1
    [[ -d ${dir} ]] || return 0
    if findmnt -rn -o TARGET | grep -q "^$(realpath "${dir}")/"; then
        die "something is still mounted under ${dir}; unmount it first"
    fi
}
