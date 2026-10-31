# move the themes to those dirs
cp -rf themes/* /usr/share/themes/
cp -rf icons/* /usr/share/icons/
mkdir -p /etc/skel/.config/lxsession/LXDE
cp -rf cfgs/desktop.conf /etc/skel/.config/lxsession/LXDE

# replace adwaita cursor with bibata cuz lxde sometimes chooses to use adwaita instead of the custom one
rm -rf /usr/share/icons/Adwaita/cursors/*
cp -rf /usr/share/icons/Bibata-Modern-Ice/cursors/* /usr/share/icons/Adwaita/cursors/

# wallpapers and logout banner
cp -rf art/* /usr/fancy-stuff/
mkdir -p /etc/skel/.config/pcmanfm/LXDE
cp -rf cfgs/desktop-items-0.conf /etc/skel/.config/pcmanfm/LXDE/

# panels
mkdir -p /etc/skel/.config/lxpanel/LXDE
cp -rf cfgs/lxpanel/* /etc/skel/.config/lxpanel/LXDE/
mkdir /usr/fancy-stuff/PanelIcons
cp -rf panel-ics/* /usr/fancy-stuff/PanelIcons/

# lightdm greeter cfg
cp -rf greet/slick-greeter.conf /etc/lightdm/

# openbox theme config
mkdir /etc/skel/.config/openbox
cp -rf cfgs/lxde-rc.xml /etc/skel/.config/openbox/
