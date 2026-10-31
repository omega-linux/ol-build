#!/bin/bash
set -Eeuo pipefail
trap 'rc=$?; printf "\e[1;31mERROR:\e[0m command failed (exit %s) at %s:%s: %s\n" "${rc}" "${BASH_SOURCE[0]:-$0}" "${LINENO}" "${BASH_COMMAND}" >&2; exit "${rc}"' ERR
source "${ROOT_DIR}/config.sh"

export DEBIAN_FRONTEND=noninteractive
export LC_ALL=C

log()  { printf '\e[1;32m  ->\e[0m %s\n' "$*"; }
warn() { printf '\e[1;33mWARN:\e[0m %s\n' "$*" >&2; }

apt_install() { apt-get install -y --no-install-recommends "$@"; }

log "writing apt sources"
rm -f /etc/apt/sources.list
cat > /etc/apt/sources.list.d/ubuntu.sources <<EOF
Types: deb
URIs: ${MIRROR}
Suites: ${SUITE} ${SUITE}-updates ${SUITE}-backports
Components: ${COMPONENTS}
Signed-By: /usr/share/keyrings/ubuntu-archive-keyring.gpg

Types: deb
URIs: ${SECURITY_MIRROR}
Suites: ${SUITE}-security
Components: ${COMPONENTS}
Signed-By: /usr/share/keyrings/ubuntu-archive-keyring.gpg
EOF

apt-get update
apt-get -y dist-upgrade

echo "${LIVE_HOSTNAME}" > /etc/hostname
cat > /etc/hosts <<EOF
127.0.0.1   localhost
127.0.1.1   ${LIVE_HOSTNAME}
::1         localhost ip6-localhost ip6-loopback
ff02::1     ip6-allnodes
ff02::2     ip6-allrouters
EOF

debconf-set-selections <<EOF
keyboard-configuration keyboard-configuration/layoutcode string ${LIVE_KEYMAP}
keyboard-configuration keyboard-configuration/xkb-keymap select ${LIVE_KEYMAP}
tzdata tzdata/Areas select ${LIVE_TIMEZONE%%/*}
tzdata tzdata/Zones/${LIVE_TIMEZONE%%/*} select ${LIVE_TIMEZONE#*/}
EOF

log "installing initramfs-tools and casper"
apt_install initramfs-tools casper

log "installing required packages"
apt_install "${REQUIRED_PACKAGES[@]}"

optional=()
for p in "${OPTIONAL_PACKAGES[@]}"; do
    if apt-cache show "${p}" >/dev/null 2>&1; then
        optional+=("${p}")
    else
        warn "optional package not available, skipping: ${p}"
    fi
done
if [[ ${#optional[@]} -gt 0 ]]; then
    log "installing optional packages"
    apt_install "${optional[@]}"
fi

mapfile -t unwanted < <(dpkg-query -W -f='${Package} ${db:Status-Status}\n' \
    'ubiquity*' 'subiquity*' 'plymouth*' ubuntu-desktop-bootstrap 2>/dev/null \
    | awk '$2 == "installed" {print $1}')
if [[ ${#unwanted[@]} -gt 0 ]]; then
    log "purging: ${unwanted[*]}"
    apt-get -y purge "${unwanted[@]}"
fi

log "configuring locale ${LIVE_LOCALE}"
sed -i "s/^# *\(${LIVE_LOCALE//./\\.}\)/\1/" /etc/locale.gen
grep -q "^${LIVE_LOCALE}" /etc/locale.gen || echo "${LIVE_LOCALE} ${LIVE_LOCALE#*.}" >> /etc/locale.gen
locale-gen
update-locale LANG="${LIVE_LOCALE}"

ln -sf "/usr/share/zoneinfo/${LIVE_TIMEZONE}" /etc/localtime
echo "${LIVE_TIMEZONE}" > /etc/timezone

cat > /etc/default/keyboard <<EOF
XKBMODEL="pc105"
XKBLAYOUT="${LIVE_KEYMAP}"
XKBVARIANT=""
XKBOPTIONS=""
BACKSPACE="guess"
EOF

cat > /etc/casper.conf <<EOF
export USERNAME="${LIVE_USER}"
export USERFULLNAME="Live session user"
export HOST="${LIVE_HOSTNAME}"
export BUILD_SYSTEM="Ubuntu"
EOF

log "configuring console autologin on tty1"
mkdir -p /etc/systemd/system/getty@tty1.service.d
cat > /etc/systemd/system/getty@tty1.service.d/autologin.conf <<EOF
[Service]
ExecStart=
ExecStart=-/sbin/agetty --autologin ${LIVE_USER} --noclear %I \$TERM
EOF

mkdir -p /etc/NetworkManager/conf.d
cat > /etc/NetworkManager/conf.d/10-globally-managed-devices.conf <<'EOF'
[keyfile]
unmanaged-devices=none
EOF

systemctl set-default multi-user.target
