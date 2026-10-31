SUITE="${SUITE:-resolute}"
VERSION="${VERSION:-26.04}"
ARCH="${ARCH:-amd64}"
MIRROR="${MIRROR:-http://archive.ubuntu.com/ubuntu}"
SECURITY_MIRROR="${SECURITY_MIRROR:-http://security.ubuntu.com/ubuntu}"
COMPONENTS="${COMPONENTS:-main restricted universe multiverse}"

LIVE_HOSTNAME="${LIVE_HOSTNAME:-olinux}"
LIVE_USER="${LIVE_USER:-live}"
LIVE_LOCALE="${LIVE_LOCALE:-en_US.UTF-8}"
LIVE_TIMEZONE="${LIVE_TIMEZONE:-Etc/UTC}"
LIVE_KEYMAP="${LIVE_KEYMAP:-us}"

BOOT_OPTIONS="${BOOT_OPTIONS:-quiet splash}"
KERNEL_VERSION="${KERNEL_VERSION:-}"

ISO_LABEL="${ISO_LABEL:-OmegaLinux}"
ISO_NAME="${ISO_NAME:-omegalinux-4.0-synapse-${ARCH}.iso}"
SQUASHFS_COMP="${SQUASHFS_COMP:-lz4}"
SQUASHFS_OPTS="${SQUASHFS_OPTS:-}"

WORK_DIR="${WORK_DIR:-${ROOT_DIR}/work}"
CHROOT_DIR="${CHROOT_DIR:-${WORK_DIR}/chroot}"
IMAGE_DIR="${IMAGE_DIR:-${WORK_DIR}/image}"
OUT_DIR="${OUT_DIR:-${ROOT_DIR}/out}"
MODS_DIR="${MODS_DIR:-${ROOT_DIR}/mods}"

REQUIRED_PACKAGES=(linux-image-generic initramfs-tools casper systemd-sysv udev kmod dbus sudo locales tzdata keyboard-configuration console-setup network-manager iproute2 iputils-ping ca-certificates curl network-manager systemd-resolved iw rfkill wpasupplicant wireless-regdb libnss-mdns avahi-daemon ubuntu-drivers-common libpam-systemd grub2-common grub-pc-bin grub-efi-amd64-bin grub-efi-ia32-bin grub-efi-amd64-signed shim-signed zram-config systemd-timesyncd)
OPTIONAL_PACKAGES=(less nano bash-completion)
