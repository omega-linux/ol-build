apt update
apt install lxde-core lightdm slick-greeter celluloid xinit lxsession -y
apt install lxde --no-install-recommends -y
apt remove lxpanel lxpanel-data -y
apt install ./pkg/lxpanel_0.11.1-olinux_amd64.deb -y
apt install libwnck-3-0 libwnck-3-common -y
apt install lxde --no-install-recommends -y
apt install lxpolkit network-manager-gnome notification-daemon -y
dpkg-reconfigure lightdm

# this is necessary for lightdm to work
systemctl set-default graphical.target

# install some other things
apt install gnome-disk-utility xscreensaver -y

# nuke ts because we dont even need it like wtf
apt autoremove xterm -y
