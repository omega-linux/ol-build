"""Shared helpers: subprocesses, pkexec helper, system D-Bus and dialogs."""

import os
import shutil
import subprocess

from gi.repository import Gio, GLib, Gtk

from . import config
from .i18n import _


def which(name):
    return shutil.which(name)


def run_sync(argv, timeout=10):
    """Run a short, read-only command and return its stdout ('' on error)."""
    try:
        env = dict(os.environ, LC_ALL="C")
        return subprocess.run(argv, capture_output=True, text=True, timeout=timeout, env=env).stdout
    except (OSError, subprocess.SubprocessError):
        return ""


def run_async(argv, callback=None, stdin=None):
    """Run a command without blocking the UI.

    ``callback(status, stdout, stderr)`` is called from the main loop."""
    flags = Gio.SubprocessFlags.STDOUT_PIPE | Gio.SubprocessFlags.STDERR_PIPE
    if stdin is not None:
        flags |= Gio.SubprocessFlags.STDIN_PIPE
    try:
        proc = Gio.Subprocess.new(argv, flags)
    except GLib.Error as e:
        if callback:
            GLib.idle_add(lambda: callback(-1, "", e.message) and False)
        return

    def done(p, res):
        try:
            _ok, out, err = p.communicate_utf8_finish(res)
        except GLib.Error as e:
            out, err = "", e.message
        status = p.get_exit_status() if p.get_if_exited() else -1
        if callback:
            callback(status, out or "", err or "")

    proc.communicate_utf8_async(stdin, None, done)


def spawn(argv):
    """Start a detached program (e.g. pavucontrol)."""
    try:
        Gio.Subprocess.new(argv, Gio.SubprocessFlags.NONE)
    except GLib.Error as e:
        error_dialog(None, _("Could not start %s") % argv[0], e.message)


def run_helper(parent, args, callback=None, stdin=None):
    """Run the privileged helper through pkexec.

    polkit asks for authentication; ``callback(ok)`` receives the result."""

    def done(status, out, err):
        if status == 126:  # authentication dialog dismissed
            pass
        elif status == 127 and not err.strip():
            error_dialog(parent, _("Not authorized"), _("Authentication failed or was refused."))
        elif status != 0:
            error_dialog(parent, _("The operation failed"), (err or out).strip())
        if callback:
            callback(status == 0)

    run_async(["pkexec", config.HELPER] + list(args), done, stdin)


def system_proxy(name, path, iface):
    """Return a Gio.DBusProxy on the system bus or None."""
    try:
        return Gio.DBusProxy.new_for_bus_sync(
            Gio.BusType.SYSTEM, Gio.DBusProxyFlags.NONE, None, name, path, iface, None)
    except GLib.Error:
        return None


def session_proxy(name, path, iface):
    try:
        return Gio.DBusProxy.new_for_bus_sync(
            Gio.BusType.SESSION, Gio.DBusProxyFlags.DO_NOT_AUTO_START, None, name, path, iface, None)
    except GLib.Error:
        return None


def prop(proxy, name, default=None):
    if proxy is None:
        return default
    v = proxy.get_cached_property(name)
    return default if v is None else v.unpack()


def dbus_call(parent, proxy, method, params, callback=None):
    """Call a privileged method; the service asks polkit for authorization."""

    def done(p, res):
        ok = True
        try:
            p.call_finish(res)
        except GLib.Error as e:
            ok = False
            remote = Gio.DBusError.get_remote_error(e) or ""
            if not remote.endswith(("Cancelled", "AuthenticationCancelled")):
                Gio.DBusError.strip_remote_error(e)
                error_dialog(parent, _("Could not apply the change"), e.message)
        if callback:
            callback(ok)

    proxy.call(method, params, Gio.DBusCallFlags.ALLOW_INTERACTIVE_AUTHORIZATION,
               5 * 60 * 1000, None, done)


def error_dialog(parent, title, detail=""):
    dlg = Gtk.MessageDialog(transient_for=parent, modal=True, message_type=Gtk.MessageType.ERROR,
                            buttons=Gtk.ButtonsType.CLOSE, text=title)
    if detail:
        dlg.format_secondary_text(detail)
    dlg.run()
    dlg.destroy()


def confirm_dialog(parent, title, detail, ok_label, destructive=False):
    dlg = Gtk.MessageDialog(transient_for=parent, modal=True, message_type=Gtk.MessageType.QUESTION,
                            buttons=Gtk.ButtonsType.NONE, text=title)
    dlg.format_secondary_text(detail)
    dlg.add_button(_("_Cancel"), Gtk.ResponseType.CANCEL)
    btn = dlg.add_button(ok_label, Gtk.ResponseType.OK)
    if destructive:
        btn.get_style_context().add_class("destructive-action")
    resp = dlg.run()
    dlg.destroy()
    return resp == Gtk.ResponseType.OK


def icon_name(*names):
    """First icon name that exists in the current icon theme."""
    theme = Gtk.IconTheme.get_default()
    for n in names:
        if theme.has_icon(n):
            return n
    return names[-1]


def human_size(n):
    for unit in ("B", "KiB", "MiB", "GiB", "TiB"):
        if n < 1024 or unit == "TiB":
            return "%.1f %s" % (n, unit) if unit != "B" else "%d B" % n
        n /= 1024.0
