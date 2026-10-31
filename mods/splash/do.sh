# we inztall le plymouth themez
apt install plymouth plymouth-label --no-install-recommends -y
cp -rf theme/DEEPIN-15-LOGINSPINNER-TUX-LOGO-BLACK-BGRD_V1.0_PLYMOUTH-THEME /usr/share/plymouth/themes/
update-alternatives --install /usr/share/plymouth/themes/default.plymouth default.plymouth "/usr/share/plymouth/themes/DEEPIN-15-LOGINSPINNER-TUX-LOGO-BLACK-BGRD_V1.0_PLYMOUTH-THEME/DEEPIN-15-LOGINSPINNER-TUX-LOGO-BLACK-BGRD_V1.0_PLYMOUTH-THEME.plymouth" 200
update-alternatives --set default.plymouth "/usr/share/plymouth/themes/DEEPIN-15-LOGINSPINNER-TUX-LOGO-BLACK-BGRD_V1.0_PLYMOUTH-THEME/DEEPIN-15-LOGINSPINNER-TUX-LOGO-BLACK-BGRD_V1.0_PLYMOUTH-THEME.plymouth"
