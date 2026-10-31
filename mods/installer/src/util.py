import os
import subprocess

LOG_PATH = "/var/log/system-installer.log"
MIB = 1024 * 1024


class InstallError(Exception):
    pass


def log(text):
    try:
        with open(LOG_PATH, "a") as f:
            f.write(text.rstrip("\n") + "\n")
    except OSError:
        pass


def run(cmd, input=None, check=True, env=None):
    log("$ " + " ".join(cmd))
    p = subprocess.run(cmd, input=input, text=True, env=env,
                       stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    if p.stdout:
        log(p.stdout)
    if check and p.returncode != 0:
        raise InstallError("%s failed (exit %d)\n\n%s" % (" ".join(cmd), p.returncode, p.stdout[-1500:]))
    return p


def output(cmd, check=True):
    p = subprocess.run(cmd, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if check and p.returncode != 0:
        raise InstallError("%s failed (exit %d)\n\n%s" % (" ".join(cmd), p.returncode, p.stderr))
    return p.stdout


def firmware():
    if not os.path.isdir("/sys/firmware/efi"):
        return "bios"
    try:
        with open("/sys/firmware/efi/fw_platform_size") as f:
            size = f.read().strip()
    except OSError:
        size = "64"
    return "efi32" if size == "32" else "efi64"


def human_size(n):
    n = float(n)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1000 or unit == "TB":
            return ("%.1f %s" % (n, unit)) if unit != "B" else ("%d B" % n)
        n /= 1000.0


def partition_path(disk, n):
    return "%s%s%d" % (disk, "p" if disk[-1].isdigit() else "", n)
