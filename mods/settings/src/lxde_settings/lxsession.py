"""Read/write the lxsession desktop.conf (the LXDE XSettings source) and
mirror GTK keys to the plain GTK config files, like lxappearance does."""

import os

from gi.repository import GLib

from . import util

SESSION = os.environ.get("DESKTOP_SESSION") or "LXDE"
if "/" in SESSION or not SESSION:
    SESSION = "LXDE"
USER_CONF = os.path.join(GLib.get_user_config_dir(), "lxsession", SESSION, "desktop.conf")


def _system_conf():
    for d in GLib.get_system_config_dirs():
        p = os.path.join(d, "lxsession", SESSION, "desktop.conf")
        if os.path.exists(p):
            return p
    return None


def load():
    kf = GLib.KeyFile()
    for path in (USER_CONF, _system_conf()):
        if path and os.path.exists(path):
            try:
                kf.load_from_file(path, GLib.KeyFileFlags.KEEP_COMMENTS)
                break
            except GLib.Error:
                continue
    return kf


def get(kf, group, key, default=""):
    try:
        return kf.get_string(group, key)
    except GLib.Error:
        return default


def get_int(kf, group, key, default=0):
    try:
        return int(kf.get_string(group, key))
    except (GLib.Error, ValueError):
        return default


def update(values):
    """Set {(group, key): value} in a fresh copy of desktop.conf and save it,
    so pages never overwrite each other's keys with stale data."""
    kf = load()
    for (group, key), val in values.items():
        kf.set_string(group, key, str(val))
    os.makedirs(os.path.dirname(USER_CONF), exist_ok=True)
    kf.save_to_file(USER_CONF)


def reload_settings_daemon():
    """Ask lxsession to re-read desktop.conf and broadcast the XSettings."""
    proxy = util.session_proxy("org.lxde.SessionManager", "/org/lxde/SessionManager", "org.lxde.SessionManager")
    if proxy is not None:
        try:
            proxy.call_sync("ReloadSettingsDaemon", None, 0, 3000, None)
            return True
        except GLib.Error:
            pass
    if util.which("lxsession"):
        util.run_async(["lxsession", "-r", "-s", SESSION])
        return True
    return False


def is_running():
    proxy = util.session_proxy("org.lxde.SessionManager", "/org/lxde/SessionManager", "org.lxde.SessionManager")
    return proxy is not None and proxy.get_name_owner() is not None


def write_gtk_files(theme, icons, font, cursor, cursor_size):
    """Keep GTK2/GTK3 config files in sync for apps started outside lxsession."""
    gtk3 = os.path.join(GLib.get_user_config_dir(), "gtk-3.0", "settings.ini")
    kf = GLib.KeyFile()
    try:
        kf.load_from_file(gtk3, GLib.KeyFileFlags.KEEP_COMMENTS)
    except GLib.Error:
        pass
    for key, val in (("gtk-theme-name", theme), ("gtk-icon-theme-name", icons), ("gtk-font-name", font),
                     ("gtk-cursor-theme-name", cursor)):
        if val:
            kf.set_string("Settings", key, val)
    if cursor_size:
        kf.set_integer("Settings", "gtk-cursor-theme-size", cursor_size)
    os.makedirs(os.path.dirname(gtk3), exist_ok=True)
    kf.save_to_file(gtk3)

    gtk2 = os.path.expanduser("~/.gtkrc-2.0")
    managed = {"gtk-theme-name": theme, "gtk-icon-theme-name": icons, "gtk-font-name": font,
               "gtk-cursor-theme-name": cursor}
    lines = []
    try:
        with open(gtk2) as f:
            lines = [l for l in f if l.split("=", 1)[0].strip() not in managed]
    except OSError:
        pass
    lines += ['%s="%s"\n' % (k, v) for k, v in managed.items() if v]
    with open(gtk2, "w") as f:
        f.writelines(lines)

    if cursor:  # default cursor for X clients that read ~/.icons/default
        d = os.path.expanduser("~/.icons/default")
        os.makedirs(d, exist_ok=True)
        with open(os.path.join(d, "index.theme"), "w") as f:
            f.write("[Icon Theme]\nInherits=%s\n" % cursor)
