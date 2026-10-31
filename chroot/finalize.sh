#!/bin/bash
set -Eeuo pipefail
trap 'rc=$?; printf "\e[1;31mERROR:\e[0m command failed (exit %s) at %s:%s: %s\n" "${rc}" "${BASH_SOURCE[0]:-$0}" "${LINENO}" "${BASH_COMMAND}" >&2; exit "${rc}"' ERR

export DEBIAN_FRONTEND=noninteractive
export LC_ALL=C

log() { printf '\e[1;32m  ->\e[0m %s\n' "$*"; }

if compgen -G '/boot/vmlinuz-*' >/dev/null; then
    log "regenerating initramfs"
    update-initramfs -u -k all
fi

log "cleaning up"
apt-get -y autoremove --purge
apt-get clean
rm -rf /var/lib/apt/lists/* /tmp/* /var/tmp/*
rm -f /var/log/*.log /var/log/apt/* /root/.bash_history
rm -f /var/lib/dbus/machine-id
truncate -s 0 /etc/machine-id
