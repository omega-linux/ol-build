#!/bin/bash
apt-get install -y --no-install-recommends python3 python3-gi gir1.2-gtk-3.0 parted fdisk dosfstools e2fsprogs btrfs-progs xfsprogs rsync efibootmgr locales xkb-data x11-xkb-utils grub2-common grub-pc-bin grub-efi-amd64-bin grub-efi-ia32-bin grub-efi-amd64-signed shim-signed
./src/install.sh /
mkdir -p /etc/system-installer
cp -a branding/. /etc/system-installer/
conf=/etc/system-installer/branding.conf
desktop=/usr/share/applications/system-installer.desktop
name=$(sed -n 's/^name *= *//p' "${conf}" | head -n1)
icon=$(sed -n 's/^icon *= *//p' "${conf}" | head -n1)
[[ -z ${name} ]] || sed -i "s|^Name=.*|Name=Install ${name}|" "${desktop}"
if [[ -n ${icon} ]]; then
    [[ ${icon} == /* || ! -f /etc/system-installer/${icon} ]] || icon=/etc/system-installer/${icon}
    sed -i "s|^Icon=.*|Icon=${icon}|" "${desktop}"
fi
install -Dm755 "${desktop}" /etc/skel/Desktop/system-installer.desktop
