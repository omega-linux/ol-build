#!/bin/sh
systemctl disable system-installer-cleanup.service
rm -f /etc/systemd/system/system-installer-cleanup.service \
    /usr/bin/system-installer \
    /usr/share/applications/system-installer.desktop \
    /usr/share/polkit-1/actions/org.systeminstaller.policy \
    /etc/skel/Desktop/system-installer.desktop
find /home /root -maxdepth 3 -name system-installer.desktop -delete
rm -rf /etc/system-installer /usr/lib/system-installer
