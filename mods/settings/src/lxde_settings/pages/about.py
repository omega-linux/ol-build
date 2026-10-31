import os
import platform
import re
import shlex

from gi.repository import Gdk, GdkPixbuf, GLib, Gtk

from .. import config, util
from ..i18n import _
from ..widgets import Page, Section, info_label


def read_os_release():
    data = {}
    for path in ("/etc/os-release", "/usr/lib/os-release"):
        try:
            with open(path) as f:
                for line in f:
                    if "=" in line and not line.startswith("#"):
                        k, v = line.rstrip("\n").split("=", 1)
                        try:
                            data[k] = shlex.split(v)[0] if v else ""
                        except (ValueError, IndexError):
                            data[k] = v
            break
        except OSError:
            continue
    return data


def cpu_name():
    model, threads = "", 0
    try:
        with open("/proc/cpuinfo") as f:
            for line in f:
                if line.startswith("model name") and not model:
                    model = line.split(":", 1)[1].strip()
                elif line.startswith("processor"):
                    threads += 1
    except OSError:
        pass
    model = re.sub(r"\s+", " ", model or platform.processor() or _("Unknown"))
    return "%s × %d" % (model, threads) if threads > 1 else model


def memory_total():
    try:
        with open("/proc/meminfo") as f:
            for line in f:
                if line.startswith("MemTotal:"):
                    return int(line.split()[1]) * 1024
    except (OSError, ValueError):
        pass
    return 0


def gpu_names():
    names = []
    for line in util.run_sync(["lspci", "-mm"]).splitlines():
        try:
            fields = shlex.split(line)
        except ValueError:
            continue
        if len(fields) >= 4 and re.search(r"VGA|3D|Display", fields[1]):
            vendor, device = fields[2], fields[3]
            m = re.search(r"\[(.+)\]", device)
            vendor = vendor.replace("Corporation", "").replace("Advanced Micro Devices, Inc.", "AMD")
            vendor = re.sub(r"\s*\[.*\]", "", vendor).strip()
            names.append("%s %s" % (vendor, m.group(1) if m else device))
    return names


def disk_usage(path="/"):
    try:
        st = os.statvfs(path)
    except OSError:
        return 0, 0
    total = st.f_blocks * st.f_frsize
    return total, total - st.f_bavail * st.f_frsize


def uptime():
    try:
        with open("/proc/uptime") as f:
            secs = int(float(f.read().split()[0]))
    except (OSError, ValueError):
        return ""
    d, rem = divmod(secs, 86400)
    h, m = divmod(rem // 60, 60)
    if d:
        return _("%d d %d h %d min") % (d, h, m)
    return _("%d h %d min") % (h, m)


def desktop_name():
    desk = os.environ.get("XDG_CURRENT_DESKTOP") or os.environ.get("DESKTOP_SESSION") or _("Unknown")
    out = util.run_sync(["lxpanel", "--version"]).strip()
    m = re.search(r"([\d.]+)", out)
    if m and "LXDE" in desk.upper():
        desk += " (lxpanel %s)" % m.group(1)
    return desk


class AboutPage(Page):
    page_id = "about"
    title = _("About")
    icons = ("help-about", "computer")

    def __init__(self, window):
        super().__init__(window)
        osr = read_os_release()
        self.os_name = osr.get("PRETTY_NAME") or osr.get("NAME") or "Linux"

        top = Gtk.Box(spacing=18)
        logo = self._logo(osr, 96)
        top.pack_start(logo, False, False, 0)
        lbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4, valign=Gtk.Align.CENTER)
        name = Gtk.Label(xalign=0, selectable=True)
        name.set_markup("<span size='xx-large' weight='bold'>%s</span>" % GLib.markup_escape_text(self.os_name))
        lbox.pack_start(name, False, False, 0)
        url = osr.get("HOME_URL")
        if url:
            lbox.pack_start(Gtk.LinkButton(uri=url, label=url, halign=Gtk.Align.START), False, False, 0)
        top.pack_start(lbox, True, True, 0)
        self.content.pack_start(top, False, False, 0)

        # Device name ------------------------------------------------------
        self.hostnamed = util.system_proxy("org.freedesktop.hostname1", "/org/freedesktop/hostname1",
                                           "org.freedesktop.hostname1")
        dev = self.add_section(Section(_("Device")))
        self.host_lbl = info_label()
        rename = Gtk.Button(label=_("Rename…"))
        rename.connect("clicked", self._on_rename)
        hb = Gtk.Box(spacing=12)
        hb.pack_start(self.host_lbl, False, False, 0)
        hb.pack_start(rename, False, False, 0)
        dev.add_row(_("Device name"), hb)
        self._update_hostname()
        if self.hostnamed:
            self.hostnamed.connect("g-properties-changed", lambda *_a: self._update_hostname())
        chassis = util.prop(self.hostnamed, "Chassis", "")
        if chassis:
            names = {"desktop": _("Desktop computer"), "laptop": _("Laptop"), "convertible": _("Convertible"),
                     "server": _("Server"), "tablet": _("Tablet"), "handset": _("Phone"),
                     "vm": _("Virtual machine"), "container": _("Container"), "embedded": _("Embedded device")}
            dev.add_row(_("Chassis"), info_label(names.get(chassis, chassis.capitalize())))
        vendor = util.prop(self.hostnamed, "HardwareVendor", "")
        model = util.prop(self.hostnamed, "HardwareModel", "")
        if vendor or model:
            dev.add_row(_("Hardware model"), info_label(("%s %s" % (vendor, model)).strip()))

        # Specifications ---------------------------------------------------
        spec = self.add_section(Section(_("Device specifications")))
        self.facts = []

        def fact(label, value, section=spec):
            self.facts.append((label, value))
            section.add_row(label, info_label(value))

        fact(_("Processor"), cpu_name())
        fact(_("Memory"), util.human_size(memory_total()))
        gpus = gpu_names()
        fact(_("Graphics") if len(gpus) < 2 else _("Graphics cards"), "\n".join(gpus) or _("Unknown"))
        total, used = disk_usage("/")
        disk_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        disk_txt = _("%(used)s used of %(total)s") % {"used": util.human_size(used), "total": util.human_size(total)}
        disk_box.pack_start(info_label(disk_txt), False, False, 0)
        bar = Gtk.LevelBar(min_value=0, max_value=1)
        bar.set_value(used / total if total else 0)
        bar.set_size_request(240, -1)
        disk_box.pack_start(bar, False, False, 0)
        spec.add_row(_("Disk (system)"), disk_box)
        self.facts.append((_("Disk (system)"), disk_txt))
        fact(_("System type"), _("%s-bit operating system, %s") % (
            "64" if platform.architecture()[0] == "64bit" else "32", platform.machine()))

        # Software ---------------------------------------------------------
        sw = self.add_section(Section(_("Software")))
        fact(_("Operating system"), self.os_name, sw)
        u = os.uname()
        fact(_("Kernel"), "%s %s" % (u.sysname, u.release), sw)
        fact(_("Desktop"), desktop_name(), sw)
        session = os.environ.get("XDG_SESSION_TYPE") or ("x11" if os.environ.get("DISPLAY") else "")
        fact(_("Windowing system"), {"x11": "X11", "wayland": "Wayland"}.get(session, session or _("Unknown")), sw)
        fact(_("GTK version"), "%d.%d.%d" % (Gtk.get_major_version(), Gtk.get_minor_version(),
                                              Gtk.get_micro_version()), sw)
        fact(_("Uptime"), uptime(), sw)

        copy = Gtk.Button(label=_("Copy"), halign=Gtk.Align.END)
        copy.set_tooltip_text(_("Copy the system information to the clipboard"))
        copy.connect("clicked", self._on_copy)
        self.content.pack_start(copy, False, False, 0)

    def _logo(self, osr, size):
        """The bundled OS logo, else the distribution's themed logo icon."""
        path = os.path.join(config.DATADIR, "oslogo.png")
        scale = self.get_scale_factor()
        try:
            pix = GdkPixbuf.Pixbuf.new_from_file_at_scale(path, size * scale, size * scale, True)
            img = Gtk.Image.new_from_surface(Gdk.cairo_surface_create_from_pixbuf(pix, scale, None))
            return img
        except GLib.Error:
            img = Gtk.Image.new_from_icon_name(
                util.icon_name(osr.get("LOGO", "distributor-logo"), "distributor-logo", "computer"),
                Gtk.IconSize.DIALOG)
            img.set_pixel_size(size)
            return img

    def _update_hostname(self):
        pretty = util.prop(self.hostnamed, "PrettyHostname", "")
        static = util.prop(self.hostnamed, "StaticHostname", "") or util.prop(self.hostnamed, "Hostname", "")
        self.host_lbl.set_text(pretty or static or os.uname().nodename)

    def _on_copy(self, _btn):
        text = "%s: %s\n" % (_("Device name"), self.host_lbl.get_text())
        text += "\n".join("%s: %s" % (k, v.replace("\n", ", ")) for k, v in self.facts)
        Gtk.Clipboard.get(Gdk.SELECTION_CLIPBOARD).set_text(text, -1)

    def _on_rename(self, _btn):
        if not self.hostnamed:
            util.error_dialog(self.window, _("The hostname service is not available"))
            return
        dlg = Gtk.Dialog(title=_("Rename device"), transient_for=self.window, modal=True)
        dlg.add_buttons(_("_Cancel"), Gtk.ResponseType.CANCEL, _("_Rename"), Gtk.ResponseType.OK)
        dlg.set_default_response(Gtk.ResponseType.OK)
        area = dlg.get_content_area()
        area.set_spacing(6)
        area.set_border_width(12)
        area.add(Gtk.Label(label=_("The name may contain letters, numbers and hyphens."), xalign=0))
        entry = Gtk.Entry(text=self.host_lbl.get_text(), activates_default=True)
        area.add(entry)
        dlg.show_all()
        while dlg.run() == Gtk.ResponseType.OK:
            name = entry.get_text().strip()
            static = re.sub(r"[^A-Za-z0-9-]+", "-", name).strip("-")[:63]
            if not static:
                continue
            pretty = name if name != static else ""

            def set_pretty(ok):
                if ok:
                    util.dbus_call(self.window, self.hostnamed, "SetPrettyHostname",
                                   GLib.Variant("(sb)", (pretty, True)))

            util.dbus_call(self.window, self.hostnamed, "SetStaticHostname",
                           GLib.Variant("(sb)", (static, True)), set_pretty)
            break
        dlg.destroy()
