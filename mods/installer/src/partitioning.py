import json
import os
import re
import shutil
import subprocess
import time

from i18n import _
from util import MIB, InstallError, human_size, log, output, partition_path, run

ESP_GUID = "c12a7328-f81f-11d2-ba4b-00a0c93ec93b"
BIOS_GUID = "21686148-6449-6e6f-744e-656564454649"
EXTENDED_TYPES = ("5", "f", "85")
MEDIA_DIRS = ("/cdrom", "/run/live/medium", "/isodevice")

MKFS = {
    "ext4": ["mkfs.ext4", "-F", "-q"],
    "ext3": ["mkfs.ext3", "-F", "-q"],
    "ext2": ["mkfs.ext2", "-F", "-q"],
    "btrfs": ["mkfs.btrfs", "-f", "-q"],
    "xfs": ["mkfs.xfs", "-f", "-q"],
    "vfat": ["mkfs.fat", "-F", "32"],
    "efi": ["mkfs.fat", "-F", "32", "-n", "EFI"],
    "swap": ["mkswap", "-f"],
}
PARTED_FS = {"ext4": "ext4", "ext3": "ext3", "ext2": "ext2", "btrfs": "btrfs", "xfs": "xfs",
             "vfat": "fat32", "efi": "fat32", "swap": "linux-swap"}
MOUNTABLE = ("ext4", "ext3", "ext2", "btrfs", "xfs", "vfat")
ROOT_FS = ("ext4", "ext3", "ext2", "btrfs", "xfs")
MOUNT_POINTS = ["/", "/boot", "/home", "/opt", "/srv", "/tmp", "/usr", "/usr/local", "/var"]


def use_label(use):
    return {
        "ext4": _("Ext4 journaling file system"),
        "ext3": _("Ext3 journaling file system"),
        "ext2": _("Ext2 file system"),
        "btrfs": _("Btrfs file system"),
        "xfs": _("XFS file system"),
        "vfat": _("FAT32 file system"),
        "swap": _("Swap area"),
        "efi": _("EFI system partition"),
        "biosgrub": _("Reserved BIOS boot area"),
        None: _("Do not use the partition"),
    }[use]


def available_uses():
    return [u for u in ("ext4", "ext3", "ext2", "btrfs", "xfs", "vfat", "swap", "efi")
            if shutil.which(MKFS[u][0])] + ["biosgrub"]


def align_up(n):
    return -(-n // MIB) * MIB


def align_down(n):
    return n // MIB * MIB


class Free:
    def __init__(self, disk, start, end):
        self.disk = disk
        self.start = start
        self.end = end

    @property
    def size(self):
        return self.end - self.start


class Part:
    def __init__(self, disk, start, end, number=None, fs="", label="", ptype="", mounted=""):
        self.disk = disk
        self.start = start
        self.end = end
        self.number = number
        self.is_new = number is None
        self.fs = fs
        self.label = label
        self.ptype = (ptype or "").lower()
        self.mounted = mounted
        self.use = None
        self.format = False
        self.mount = ""

    @property
    def size(self):
        return self.end - self.start

    @property
    def path(self):
        return partition_path(self.disk.path, self.number) if self.number else ""

    @property
    def esp(self):
        return self.ptype in (ESP_GUID, "ef")

    @property
    def biosgrub(self):
        return self.ptype == BIOS_GUID

    @property
    def extended(self):
        return self.disk.label == "msdos" and self.ptype in EXTENDED_TYPES

    @property
    def logical(self):
        return self.disk.label == "msdos" and bool(self.number) and self.number >= 5

    def name(self):
        return self.path if not self.is_new else _("New partition")

    def detected_use(self):
        if self.fs == "vfat" and self.esp:
            return "efi"
        if self.biosgrub:
            return "biosgrub"
        if self.fs in ("ext4", "ext3", "ext2", "btrfs", "xfs", "vfat", "swap"):
            return self.fs
        return None

    def needs_format(self):
        if self.is_new:
            return True
        if self.use in (None, "biosgrub"):
            return False
        current = self.detected_use()
        if self.use == "efi":
            return self.fs != "vfat"
        if self.use == "vfat":
            return self.fs != "vfat"
        return current != self.use

    def will_format(self):
        return self.use in MKFS and (self.is_new or self.format or self.needs_format())


class Disk:
    def __init__(self, path, size, model, sector):
        self.path = path
        self.size = size
        self.model = model
        self.sector = sector
        self.table = ""
        self.new_table = None
        self.parts = []
        self.deleted = []

    @property
    def label(self):
        return self.new_table or self.table

    def usable(self):
        end = align_down(self.size)
        if self.label != "msdos":
            end -= MIB
        return MIB, end

    def segments(self):
        lo, hi = self.usable()
        items = []
        cur = lo
        for p in sorted(self.parts, key=lambda p: p.start):
            if p.logical:
                items.append(p)
                continue
            gs, ge = align_up(cur), align_down(p.start)
            if ge - gs >= MIB:
                items.append(Free(self, gs, ge))
            items.append(p)
            cur = max(cur, p.end)
        gs = align_up(cur)
        if hi - gs >= MIB:
            items.append(Free(self, gs, hi))
        return items

    def describe(self):
        return "%s  %s  %s" % (self.path, human_size(self.size), self.model)

    def changed(self):
        return bool(self.new_table or self.deleted or any(p.is_new for p in self.parts))


def _flag(v):
    return str(v).lower() in ("1", "true")


def live_disks():
    disks = set()
    for mnt in MEDIA_DIRS:
        src = output(["findmnt", "-n", "-o", "SOURCE", mnt], check=False).strip()
        if not src.startswith("/dev/"):
            continue
        parent = output(["lsblk", "-ndo", "PKNAME", src], check=False).strip()
        disks.add("/dev/" + parent if parent else src)
    return disks


def sector_size(name):
    try:
        with open("/sys/block/%s/queue/logical_block_size" % name) as f:
            return int(f.read().strip())
    except (OSError, ValueError):
        return 512


def read_table(disk):
    p = subprocess.run(["sfdisk", "-J", disk.path], text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if p.returncode != 0 or not p.stdout.strip():
        return None
    return json.loads(p.stdout)["partitiontable"]


def scan(fw):
    data = json.loads(output(["lsblk", "-J", "-b", "-o",
                              "NAME,PATH,SIZE,TYPE,MODEL,RO,FSTYPE,LABEL,MOUNTPOINT"]))
    skip = live_disks()
    disks = []
    for d in data.get("blockdevices", []):
        if d.get("type") != "disk" or _flag(d.get("ro")):
            continue
        if d["name"].startswith(("zram", "loop", "ram")) or d["path"] in skip:
            continue
        size = int(d.get("size") or 0)
        if size < 4 * MIB:
            continue
        disk = Disk(d["path"], size, (d.get("model") or "").strip(), sector_size(d["name"]))
        info = {c["path"]: c for c in d.get("children") or []}
        table = read_table(disk)
        if table:
            disk.table = "msdos" if table.get("label") == "dos" else table.get("label", "")
            sec = int(table.get("sectorsize") or disk.sector)
            for e in table.get("partitions", []):
                num = int(re.search(r"(\d+)$", e["node"]).group(1))
                start = int(e["start"]) * sec
                c = info.get(e["node"], {})
                disk.parts.append(Part(disk, start, start + int(e["size"]) * sec, num,
                                       c.get("fstype") or "", c.get("label") or "",
                                       e.get("type", ""), c.get("mountpoint") or ""))
        disks.append(disk)
    layout = Layout(disks)
    layout.set_defaults(fw)
    return layout


class Layout:
    def __init__(self, disks):
        self.disks = disks

    def disk(self, path):
        return next((d for d in self.disks if d.path == path), None)

    def parts(self):
        return [p for d in self.disks for p in d.parts]

    def used(self):
        return [p for p in self.parts() if p.use]

    def set_defaults(self, fw):
        efi = False
        for p in self.parts():
            u = p.detected_use()
            if u == "efi" and fw != "bios" and not efi:
                p.use, p.mount, efi = "efi", "/boot/efi", True
            elif u == "swap":
                p.use = "swap"
            elif u == "biosgrub":
                p.use = "biosgrub"

    def new_table(self, disk, label):
        disk.new_table = label
        disk.parts = []
        disk.deleted = []

    def add(self, free, size, at_end, use, mount):
        disk = free.disk
        if not disk.label:
            disk.new_table = "gpt"
        if disk.label == "msdos" and len([p for p in disk.parts if not p.logical]) >= 4:
            raise ValueError(_("An MBR (msdos) disk can only have 4 primary partitions."))
        size = min(free.size, align_down(size))
        if size < MIB:
            raise ValueError(_("The partition is too small."))
        start = free.end - size if at_end else free.start
        p = Part(disk, start, start + size)
        self.set_use(p, use, mount, True)
        disk.parts.append(p)
        return p

    def set_use(self, p, use, mount, fmt):
        p.use = use
        p.format = fmt
        if use == "efi":
            p.mount = "/boot/efi"
        elif use in MOUNTABLE:
            p.mount = mount.strip()
        else:
            p.mount = ""

    def delete(self, part):
        disk = part.disk
        victims = [part]
        if part.extended:
            victims += [q for q in disk.parts if q.logical and part.start <= q.start < part.end]
        for q in victims:
            disk.parts.remove(q)
            if not q.is_new and not disk.new_table:
                disk.deleted.append(q.number)

    def erase(self, disk, esp_mib):
        self.new_table(disk, "gpt")
        for p in self.parts():
            if p.use in ("efi", "biosgrub", "swap") or p.mount:
                p.use, p.mount, p.format = None, "", False
        self.add(disk.segments()[0], MIB, False, "biosgrub", "")
        self.add(disk.segments()[-1], esp_mib * MIB, False, "efi", "")
        self.add(disk.segments()[-1], disk.size, False, "ext4", "/")

    def check(self, fw, bios_disk, required):
        mounts = {}
        for p in self.used():
            if p.mount:
                if not re.fullmatch(r"/[^\s]*", p.mount) or (p.mount != "/" and p.mount.endswith("/")):
                    return _("Invalid mount point: %s") % p.mount
                if p.mount in mounts:
                    return _("The mount point %s is used more than once.") % p.mount
                mounts[p.mount] = p
        root = mounts.get("/")
        if not root:
            return _("No root file system (/) is defined.")
        if root.use not in ROOT_FS:
            return _("The root file system (/) cannot use %s.") % use_label(root.use)
        if not root.will_format():
            return _("The root partition (/) must be formatted.")
        if required and root.size < required * 1.2:
            return _("The root partition is too small, it needs at least %s.") % human_size(required * 1.2)
        for p in self.used():
            if p.use in MOUNTABLE and p.use != "vfat" and not p.mount:
                return _("Choose a mount point for %s.") % p.name()
        efis = [p for p in self.used() if p.use == "efi"]
        if len(efis) > 1:
            return _("Only one EFI system partition can be used.")
        if fw != "bios" and not efis:
            return _("An EFI system partition is required to boot this computer.")
        if fw == "bios" and not bios_disk:
            return _("Choose a device for the boot loader.")
        if bios_disk:
            d = self.disk(bios_disk)
            if not d or not d.label:
                return _("%s has no partition table.") % bios_disk
            if d.label == "gpt" and not any(p.use == "biosgrub" for p in d.parts):
                return _("%s uses GPT, so it needs a reserved BIOS boot area (1 MB) for the boot loader.") % d.path
        return None

    def describe(self):
        lines = []
        for d in self.disks:
            if d.new_table:
                lines.append(_("The partition table of %(disk)s will be replaced (%(type)s).")
                             % {"disk": d.path, "type": d.new_table.upper()})
            for n in d.deleted:
                lines.append(_("Partition %s will be deleted.") % partition_path(d.path, n))
            for p in sorted(d.parts, key=lambda p: p.start):
                if p.is_new:
                    lines.append(_("New partition of %(size)s on %(disk)s: %(use)s")
                                 % {"size": human_size(p.size), "disk": d.path, "use": use_label(p.use)})
                elif p.will_format():
                    lines.append(_("%(part)s will be formatted as %(use)s.")
                                 % {"part": p.path, "use": use_label(p.use)})
                if p.mount:
                    lines.append(_("%(part)s will be mounted on %(mount)s.")
                                 % {"part": p.name() if not p.is_new else _("The new partition"), "mount": p.mount})
                elif p.use == "swap":
                    lines.append(_("%s will be used as swap.") % (p.name() if not p.is_new else _("The new partition")))
        return lines

    def release(self, devices):
        for dev in devices:
            for line in output(["lsblk", "-nrpo", "PATH,FSTYPE,MOUNTPOINT", dev], check=False).splitlines():
                fields = line.split(" ")
                path = fields[0]
                if len(fields) > 1 and fields[1] == "swap":
                    run(["swapoff", path], check=False)
                if len(fields) > 2 and fields[2]:
                    run(["umount", "-l", path], check=False)

    def wait_for(self, paths):
        run(["udevadm", "settle"], check=False)
        for _i in range(50):
            if all(os.path.exists(p) for p in paths):
                return
            time.sleep(0.2)
        raise InstallError(_("The new partitions did not show up: %s") % ", ".join(paths))

    def apply(self, status, bios_disk):
        for d in self.disks:
            touched = [p for p in d.parts if p.use]
            if not d.changed() and not any(p.will_format() for p in touched):
                continue
            status(_("Partitioning %s") % d.path)
            if d.changed():
                self.release([d.path])
            else:
                self.release([p.path for p in touched if p.will_format()])
            parted = ["parted", "-s", d.path]
            if d.new_table:
                for line in output(["lsblk", "-nrpo", "PATH,TYPE", d.path], check=False).splitlines():
                    path, kind = (line.split(" ") + [""])[:2]
                    if kind == "part":
                        run(["wipefs", "-a", "-f", path], check=False)
                run(["wipefs", "-a", "-f", d.path])
                run(parted + ["mklabel", d.new_table])
            else:
                for n in sorted(d.deleted, reverse=True):
                    run(parted + ["rm", str(n)])
            new = sorted([p for p in d.parts if p.is_new], key=lambda p: p.start)
            for p in new:
                cmd = parted + ["unit", "MiB", "mkpart"]
                if d.label == "msdos":
                    cmd.append("primary")
                else:
                    cmd.append({"efi": "EFI", "biosgrub": "bios", "swap": "swap"}.get(p.use, "linux"))
                if p.use in PARTED_FS:
                    cmd.append(PARTED_FS[p.use])
                cmd += [str(p.start // MIB), str(p.end // MIB)]
                run(cmd)
            if d.changed():
                run(["partprobe", d.path], check=False)
                run(["udevadm", "settle"], check=False)
            if new:
                table = read_table(d) or {}
                sec = int(table.get("sectorsize") or d.sector)
                found = [(int(e["start"]) * sec, int(re.search(r"(\d+)$", e["node"]).group(1)))
                         for e in table.get("partitions", [])]
                for p in new:
                    match = [n for s, n in found if abs(s - p.start) < MIB]
                    if not match:
                        raise InstallError(_("Could not find the new partition at %s on %s.")
                                           % (human_size(p.start), d.path))
                    p.number = match[0]
            for p in d.parts:
                if p.use == "efi" and not p.esp:
                    run(parted + ["set", str(p.number), "esp", "on"])
                if p.use == "biosgrub" and not p.biosgrub and d.label == "gpt":
                    run(parted + ["set", str(p.number), "bios_grub", "on"])
            if bios_disk == d.path and d.label == "msdos":
                root = next((p for p in d.parts if p.mount == "/"), None)
                if root:
                    run(parted + ["set", str(root.number), "boot", "on"], check=False)
            self.wait_for([p.path for p in d.parts if p.use])

        for p in self.used():
            if p.will_format():
                status(_("Formatting %s") % p.path)
                run(["wipefs", "-a", "-f", p.path], check=False)
                run(MKFS[p.use] + [p.path])
