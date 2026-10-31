"""Openbox window-border theme, replacing obconf (no longer in the Arch repos)."""

import os
import re

from gi.repository import GLib

from . import util


def rc_path():
    """The rc.xml the running Openbox uses (LXDE passes --config-file)."""
    pid = util.run_sync(["pgrep", "-x", "-u", str(os.getuid()), "openbox"]).split()
    if pid:
        try:
            with open("/proc/%s/cmdline" % pid[0], "rb") as f:
                args = f.read().decode(errors="replace").split("\0")
            if "--config-file" in args:
                return args[args.index("--config-file") + 1]
        except (OSError, IndexError):
            pass
    conf = os.path.join(GLib.get_user_config_dir(), "openbox")
    session = os.environ.get("DESKTOP_SESSION", "LXDE").lower()
    for name in ("%s-rc.xml" % session, "lxde-rc.xml", "rc.xml"):
        if os.path.exists(os.path.join(conf, name)):
            return os.path.join(conf, name)
    return None


def themes():
    home = GLib.get_home_dir()
    dirs = [os.path.join(home, ".themes"), os.path.join(GLib.get_user_data_dir(), "themes")]
    dirs += [os.path.join(d, "themes") for d in GLib.get_system_data_dirs()]
    found = set()
    for d in dirs:
        if os.path.isdir(d):
            found.update(n for n in os.listdir(d) if os.path.isdir(os.path.join(d, n, "openbox-3")))
    return sorted(found, key=str.lower)


# Edit the text in place with a regex: rewriting the file through an XML
# library would drop comments and mangle the namespace.
_THEME_NAME = re.compile(r"(<theme>.*?<name>)(.*?)(</name>)", re.S)


def get_theme(path):
    try:
        with open(path, encoding="utf-8") as f:
            m = _THEME_NAME.search(f.read())
    except OSError:
        return None
    return m.group(2).strip() if m else None


def set_theme(path, name):
    with open(path, encoding="utf-8") as f:
        text = f.read()
    escaped = GLib.markup_escape_text(name)
    new, n = _THEME_NAME.subn(lambda m: m.group(1) + escaped + m.group(3), text, count=1)
    if not n:
        raise ValueError("no <theme><name> element in %s" % path)
    tmp = path + ".lxde-settings"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(new)
    os.replace(tmp, path)
    util.run_async(["openbox", "--reconfigure"])
