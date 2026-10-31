# base packages for x11 desktops
apt install xserver-xorg-core xorg xinput dbus-x11 blueman desktop-file-utils xdg-user-dirs gvfs-fuse gvfs-backends polkitd pkexec language-pack-en x11-utils -y
apt install pipewire pipewire-audio-client-libraries libspa-0.2-bluetooth libspa-0.2-jack pipewire-pulse wireplumber --no-install-recommends -y
# apt install cryptsetup cryptsetup-initramfs -y

# graphics
apt install -y --no-install-recommends libgl1-mesa-dri libglx-mesa0 libegl-mesa0 libgbm1 mesa-vulkan-drivers mesa-utils
apt install xserver-xorg-video-amdgpu intel-media-va-driver i965-va-driver vainfo vulkan-tools -y --no-install-recommends
