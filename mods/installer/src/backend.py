import os
import re
import shutil
import subprocess

from i18n import _
from partitioning import MEDIA_DIRS
from util import LOG_PATH, InstallError, firmware, log, output, run

APP_DIR = "/usr/lib/system-installer"
TARGET = "/target"
SOURCE_DIRS = ("/rofs", "/run/rofs")
CLEANUP_UNIT = "system-installer-cleanup.service"


def required_size():
    for media in MEDIA_DIRS:
        try:
            with open(os.path.join(media, "casper/filesystem.size")) as f:
                return int(f.read().strip())
        except (OSError, ValueError):
            pass
    return 0


def source_root():
    for p in SOURCE_DIRS:
        if os.path.isdir(os.path.join(p, "etc")) and os.path.isdir(os.path.join(p, "usr")):
            return p
    return None


def language_packs(locale):
    lang = re.split(r"[_.@]", locale)[0]
    if lang in ("C", "POSIX", "en"):
        return []
    if lang == "zh":
        lang = "zh-hant" if re.search(r"_(TW|HK|MO)", locale) else "zh-hans"
    return ["language-pack-" + lang, "language-pack-gnome-" + lang]


class Installer:
    def __init__(self, plan, branding, progress, status):
        self.plan = plan
        self.layout = plan["layout"]
        self.branding = branding
        self.progress = progress
        self.status = status
        self.kver = os.uname().release
        self.fw = firmware()

    def step(self, frac, text):
        log("== " + text)
        self.status(text)
        self.progress(frac)

    def install(self):
        try:
            open(LOG_PATH, "w").close()
        except OSError:
            pass
        log("firmware: %s, kernel: %s" % (self.fw, self.kver))
        log("plan: %s" % {k: v for k, v in self.plan.items() if k not in ("password", "layout")})
        for line in self.layout.describe():
            log("layout: " + line)
        self.src = source_root()
        if not self.src:
            raise InstallError(_("Could not find the live system image."))
        try:
            self.unmount_target()
            self.step(0.02, _("Preparing the disks"))
            self.layout.apply(self.status, self.plan.get("bios_disk"))
            self.mount_target()
            self.copy_system(0.12, 0.68)
            self.bind_mounts()
            self.configure()
            self.bootloader()
            self.step(0.98, _("Finishing"))
            try:
                shutil.copy(LOG_PATH, os.path.join(TARGET, "var/log/system-installer.log"))
            except OSError:
                pass
            run(["sync"])
        finally:
            self.unmount_target()
        self.step(1.0, _("Done"))

    def mounts(self):
        parts = [p for p in self.layout.used() if p.mount]
        return sorted(parts, key=lambda p: (p.mount != "/", p.mount.count("/"), p.mount))

    def mount_target(self):
        os.makedirs(TARGET, exist_ok=True)
        for p in self.mounts():
            path = os.path.join(TARGET, p.mount.lstrip("/"))
            os.makedirs(path, exist_ok=True)
            run(["mount", p.path, path])

    def unmount_target(self):
        if not os.path.isdir(TARGET):
            return
        mounted = output(["findmnt", "-rn", "-o", "TARGET"], check=False).splitlines()
        if not any(m == TARGET or m.startswith(TARGET + "/") for m in mounted):
            return
        if run(["umount", "-R", TARGET], check=False).returncode != 0:
            run(["umount", "-lR", TARGET], check=False)

    def copy_system(self, start, end):
        self.step(start, _("Copying files"))
        cmd = ["rsync", "-aHAX", "--numeric-ids", "--no-inc-recursive", "--info=progress2",
               self.src + "/", TARGET + "/"]
        log("$ " + " ".join(cmd))
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        buf = b""
        tail = []
        last = -1
        while True:
            chunk = proc.stdout.read1(4096)
            if not chunk:
                break
            buf += chunk
            pieces = re.split(rb"[\r\n]", buf)
            buf = pieces.pop()
            for piece in pieces:
                line = piece.decode(errors="replace").strip()
                if not line:
                    continue
                m = re.search(r"(\d+)%", line)
                if m:
                    pct = int(m.group(1))
                    if pct != last:
                        last = pct
                        self.progress(start + (end - start) * pct / 100.0)
                        self.status(_("Copying files (%d%%)") % pct)
                else:
                    tail = (tail + [line])[-20:]
                    log(line)
        rc = proc.wait()
        if rc != 0:
            raise InstallError(_("Copying the system failed (rsync exit %d)") % rc + "\n\n" + "\n".join(tail))

    def bind_mounts(self):
        for d in ("dev", "proc", "sys", "run"):
            path = os.path.join(TARGET, d)
            os.makedirs(path, exist_ok=True)
            run(["mount", "--rbind", "/" + d, path])
            run(["mount", "--make-rslave", path])

    def chroot(self, *cmd, input=None, check=True):
        env = {"PATH": "/usr/sbin:/usr/bin:/sbin:/bin", "HOME": "/root", "LANG": "C.UTF-8",
               "DEBIAN_FRONTEND": "noninteractive"}
        return run(["chroot", TARGET] + list(cmd), input=input, check=check, env=env)

    def target(self, rel):
        return os.path.join(TARGET, rel.lstrip("/"))

    def write(self, rel, text, mode=0o644):
        path = self.target(rel)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as f:
            f.write(text)
        os.chmod(path, mode)

    def remove(self, rel):
        path = self.target(rel)
        if os.path.isdir(path) and not os.path.islink(path):
            shutil.rmtree(path, ignore_errors=True)
        elif os.path.lexists(path):
            os.remove(path)

    def uuid(self, dev):
        return output(["blkid", "-s", "UUID", "-o", "value", dev]).strip()

    def installed(self, pkg):
        p = self.chroot("dpkg-query", "-W", "-f=${db:Status-Status}", pkg, check=False)
        return p.returncode == 0 and p.stdout.strip() == "installed"

    def fstab(self):
        lines = ["# <file system> <mount point> <type> <options> <dump> <pass>"]
        for p in self.mounts():
            fs = "vfat" if p.use in ("vfat", "efi") else p.use
            if p.use == "efi":
                opts = "umask=0077"
            elif p.mount == "/" and p.use.startswith("ext"):
                opts = "errors=remount-ro"
            else:
                opts = "defaults"
            passno = 0 if p.use in ("btrfs", "xfs") else (1 if p.mount in ("/", "/boot/efi") else 2)
            lines.append("UUID=%s  %s  %s  %s  0  %d" % (self.uuid(p.path), p.mount, fs, opts, passno))
        for p in self.layout.used():
            if p.use == "swap":
                lines.append("UUID=%s  none  swap  sw  0  0" % self.uuid(p.path))
        self.write("etc/fstab", "\n".join(lines) + "\n")

    def configure_locale(self):
        loc = self.plan.get("locale")
        if not loc:
            return
        self.step(0.76, _("Configuring the language"))
        gen = self.target("etc/locale.gen")
        charset = "UTF-8"
        if os.path.exists(gen):
            with open(gen) as f:
                lines = f.read().splitlines()
            pattern = re.compile(r"^#\s*(%s)\s" % re.escape(loc))
            found = False
            for i, line in enumerate(lines):
                if pattern.match(line + " "):
                    lines[i] = line.lstrip("#").lstrip()
                    found = True
                elif line.split()[:1] == [loc]:
                    found = True
            if not found:
                lines.append("%s %s" % (loc, charset))
            with open(gen, "w") as f:
                f.write("\n".join(lines) + "\n")
        self.chroot("locale-gen", loc)
        self.chroot("update-locale", "LANG=" + loc)
        if self.plan.get("language_packs"):
            self.install_language_packs(loc)

    def install_language_packs(self, loc):
        pkgs = language_packs(loc)
        if not pkgs:
            return
        self.step(0.78, _("Downloading language support"))
        resolv = self.target("etc/resolv.conf")
        link = os.readlink(resolv) if os.path.islink(resolv) else None
        saved = None
        if link is None and os.path.exists(resolv):
            with open(resolv) as f:
                saved = f.read()
        try:
            with open("/etc/resolv.conf") as f:
                live = f.read()
            if os.path.lexists(resolv):
                os.remove(resolv)
            with open(resolv, "w") as f:
                f.write(live)
            if self.chroot("apt-get", "update", check=False).returncode != 0:
                log("apt-get update failed, skipping language packs")
                return
            wanted = [p for p in pkgs if self.chroot("apt-cache", "show", p, check=False).returncode == 0]
            if wanted and self.chroot("apt-get", "install", "-y", *wanted, check=False).returncode != 0:
                log("installing language packs failed, continuing without them")
            self.chroot("apt-get", "clean", check=False)
        except OSError as e:
            log("language packs skipped: %s" % e)
        finally:
            if os.path.lexists(resolv):
                os.remove(resolv)
            if link is not None:
                os.symlink(link, resolv)
            elif saved is not None:
                with open(resolv, "w") as f:
                    f.write(saved)

    def configure_keyboard(self):
        layout = self.plan.get("keyboard_layout")
        if not layout:
            return
        self.write("etc/default/keyboard",
                   'XKBMODEL="pc105"\nXKBLAYOUT="%s"\nXKBVARIANT="%s"\nXKBOPTIONS=""\n\nBACKSPACE="guess"\n'
                   % (layout, self.plan.get("keyboard_variant") or ""))

    def configure(self):
        p = self.plan
        self.step(0.70, _("Installing the kernel"))
        vmlinuz = "boot/vmlinuz-%s" % self.kver
        if not os.path.exists(self.target(vmlinuz)):
            for c in [os.path.join(m, "casper/vmlinuz") for m in MEDIA_DIRS] + ["/" + vmlinuz]:
                if os.path.isfile(c):
                    shutil.copy2(c, self.target(vmlinuz))
                    break
            else:
                raise InstallError(_("Could not find the running kernel (%s) on the live media.") % self.kver)
        if not os.path.isdir(self.target("lib/modules/" + self.kver)) and \
                not os.path.isdir(self.target("usr/lib/modules/" + self.kver)):
            raise InstallError(_("The live image has no modules for kernel %s.") % self.kver)

        self.step(0.72, _("Configuring the system"))
        self.write("usr/sbin/policy-rc.d", "#!/bin/sh\nexit 101\n", 0o755)
        for rel in ("etc/casper.conf", "etc/systemd/system/getty@tty1.service.d/autologin.conf"):
            self.remove(rel)

        host = p["hostname"]
        self.write("etc/hostname", host + "\n")
        self.write("etc/hosts", "127.0.0.1   localhost\n127.0.1.1   %s\n"
                   "::1         localhost ip6-localhost ip6-loopback\n"
                   "ff02::1     ip6-allnodes\nff02::2     ip6-allrouters\n" % host)

        tz = p.get("timezone")
        if tz and os.path.exists(self.target("usr/share/zoneinfo/" + tz)):
            self.remove("etc/localtime")
            os.symlink("/usr/share/zoneinfo/" + tz, self.target("etc/localtime"))
            self.write("etc/timezone", tz + "\n")

        self.fstab()
        self.configure_keyboard()
        self.configure_locale()

        self.step(0.82, _("Creating user %s") % p["username"])
        with open(self.target("etc/group")) as f:
            existing = {line.split(":")[0] for line in f if line.strip()}
        groups = [g for g in self.branding["groups"].split() if g in existing]
        cmd = ["useradd", "-m", "-s", "/bin/bash", "-c", p.get("fullname", "")]
        if groups:
            cmd += ["-G", ",".join(groups)]
        self.chroot(*(cmd + [p["username"]]))
        self.chroot("chpasswd", input="%s:%s\n" % (p["username"], p["password"]))
        sudoers = "etc/sudoers.d/10-%s" % p["username"]
        self.write(sudoers, "%s ALL=(ALL:ALL) ALL\n" % p["username"], 0o440)
        self.chroot("visudo", "-cf", "/" + sudoers)

        self.step(0.84, _("Removing live session packages"))
        initrd = "boot/initrd.img-%s" % self.kver
        self.chroot("update-initramfs", "-u" if os.path.exists(self.target(initrd)) else "-c", "-k", self.kver)
        if self.installed("casper"):
            self.chroot("apt-get", "-y", "purge", "casper")

        self.step(0.86, _("Generating the initramfs"))
        self.chroot("update-initramfs", "-u", "-k", self.kver)

        unit = "etc/systemd/system/" + CLEANUP_UNIT
        self.write(unit, "[Unit]\nDescription=Remove the system installer\n"
                         "ConditionPathExists=%s\n\n"
                         "[Service]\nType=oneshot\nExecStart=/bin/sh %s/cleanup.sh\n\n"
                         "[Install]\nWantedBy=multi-user.target\n" % (APP_DIR, APP_DIR))
        wants = self.target("etc/systemd/system/multi-user.target.wants")
        os.makedirs(wants, exist_ok=True)
        link = os.path.join(wants, CLEANUP_UNIT)
        if not os.path.lexists(link):
            os.symlink("/" + unit, link)
        self.remove("usr/sbin/policy-rc.d")

    def grub_install(self, *args, check=True):
        return self.chroot("grub-install", *args, check=check)

    def bootloader(self):
        p = self.plan
        b = self.branding
        self.step(0.88, _("Installing the boot loader"))
        if not os.path.exists(self.target("etc/default/grub")):
            self.write("etc/default/grub",
                       'GRUB_DEFAULT=0\nGRUB_TIMEOUT_STYLE=menu\nGRUB_TIMEOUT=%s\n'
                       'GRUB_DISTRIBUTOR="%s"\nGRUB_CMDLINE_LINUX_DEFAULT="%s"\nGRUB_CMDLINE_LINUX=""\n'
                       % (b["grub_timeout"], b["grub_distributor"], b["kernel_cmdline"]))

        installed = []
        if p.get("bios_disk"):
            self.grub_install("--target=i386-pc", "--recheck", p["bios_disk"])
            installed.append("i386-pc")

        if any(q.use == "efi" for q in self.layout.used()):
            bid = b["bootloader_id"]
            signed = os.path.isdir(self.target("usr/lib/grub/x86_64-efi-signed")) and \
                os.path.isdir(self.target("usr/lib/shim"))
            for tgt, native_fw, extra in (
                    ("x86_64-efi", "efi64", ["--uefi-secure-boot" if signed else "--no-uefi-secure-boot"]),
                    ("i386-efi", "efi32", [])):
                if not os.path.isdir(self.target("usr/lib/grub/" + tgt)):
                    if self.fw == native_fw:
                        raise InstallError(_("GRUB for %s is not installed in the live image.") % tgt)
                    continue
                base = ["--target=" + tgt, "--efi-directory=/boot/efi"] + extra
                if self.fw == native_fw:
                    r = self.grub_install(*(base + ["--bootloader-id=" + bid]), check=False)
                    if r.returncode != 0:
                        log("registering the boot entry failed, retrying without NVRAM")
                        self.grub_install(*(base + ["--bootloader-id=" + bid, "--no-nvram"]))
                self.grub_install(*(base + ["--removable", "--no-nvram"]))
                installed.append(tgt)

        if not installed:
            raise InstallError(_("No boot loader was installed."))
        self.step(0.94, _("Writing the boot menu"))
        self.chroot("grub-mkconfig", "-o", "/boot/grub/grub.cfg")
