import time
from datetime import datetime

from gi.repository import GLib, Gtk

from .. import util
from ..i18n import _
from ..widgets import Page, Section


def timezone_store(zones):
    """TreeStore grouping zones by region so the combo shows submenus."""
    store = Gtk.TreeStore(str, str)  # id, label
    groups = {}
    for z in sorted(zones):
        if "/" in z:
            region, city = z.split("/", 1)
        else:
            region, city = _("Other"), z
        if region not in groups:
            groups[region] = store.append(None, [None, region])
        store.append(groups[region], [z, city.replace("_", " ").replace("/", " / ")])
    return store


class DateTimePage(Page):
    page_id = "datetime"
    title = _("Date & Time")
    icons = ("preferences-system-time", "x-office-calendar", "appointment-soon")

    def __init__(self, window):
        super().__init__(window)
        self.proxy = util.system_proxy("org.freedesktop.timedate1", "/org/freedesktop/timedate1",
                                       "org.freedesktop.timedate1")
        self._updating = False

        self.clock = Gtk.Label(xalign=0, selectable=True)
        self.content.pack_start(self.clock, False, False, 0)

        sec = self.add_section(Section(_("Date and time")))
        self.ntp_switch = Gtk.Switch()
        self.ntp_switch.connect("notify::active", self._on_ntp)
        self.ntp_row = sec.add_row(_("Set the time automatically"), self.ntp_switch, "")
        self.change_btn = Gtk.Button(label=_("Change…"))
        self.change_btn.connect("clicked", self._on_change_time)
        sec.add_row(_("Set the date and time manually"), self.change_btn)

        tz = self.add_section(Section(_("Time zone")))
        self.tz_combo = Gtk.ComboBox()
        cell = Gtk.CellRendererText()
        self.tz_combo.pack_start(cell, True)
        self.tz_combo.add_attribute(cell, "text", 1)
        self.tz_combo.set_id_column(0)
        self.tz_combo.set_size_request(260, -1)
        self.tz_combo.connect("changed", self._on_tz)
        tz.add_row(_("Time zone"), self.tz_combo)

        self.rtc_switch = Gtk.Switch()
        self.rtc_switch.connect("notify::active", self._on_rtc)
        tz.add_row(_("Hardware clock uses local time"), self.rtc_switch,
                   _("Only enable this when Windows is installed on the same computer "
                     "and keeps its clock in local time"))

        if self.proxy is None:
            self.content.set_sensitive(False)
            self.clock.set_text(_("The time and date service (systemd-timedated) is not available."))
            return
        self._load_zones()
        self.proxy.connect("g-properties-changed", lambda *_a: self._sync())
        self._sync()
        self._tick()
        self._timer = GLib.timeout_add_seconds(1, self._tick)
        self.connect("destroy", lambda *_a: GLib.source_remove(self._timer))

    def _load_zones(self):
        zones = []
        try:
            res = self.proxy.call_sync("ListTimezones", None, 0, 5000, None)
            zones = res.unpack()[0]
        except GLib.Error:
            zones = util.run_sync(["timedatectl", "list-timezones"]).split()
        self.tz_combo.set_model(timezone_store(zones))

    def _refresh_props(self):
        # timedated does not emit PropertiesChanged for every property, so read
        # them explicitly instead of relying on the cache.
        for name in ("Timezone", "NTP", "CanNTP", "NTPSynchronized", "LocalRTC"):
            try:
                v = self.proxy.call_sync("org.freedesktop.DBus.Properties.Get",
                                         GLib.Variant("(ss)", ("org.freedesktop.timedate1", name)),
                                         0, 2000, None).unpack()[0]
                self.proxy.set_cached_property(name, GLib.Variant(
                    "s" if name == "Timezone" else "b", v))
            except GLib.Error:
                pass

    def _sync(self):
        self._refresh_props()
        self._updating = True
        ntp = util.prop(self.proxy, "NTP", False)
        self.ntp_switch.set_active(ntp)
        self.ntp_switch.set_sensitive(util.prop(self.proxy, "CanNTP", False))
        if not util.prop(self.proxy, "CanNTP", False):
            sub = _("No network time service is installed")
        elif ntp:
            sub = _("Synchronized with a time server") if util.prop(self.proxy, "NTPSynchronized", False) \
                else _("Waiting for a time server…")
        else:
            sub = _("Off")
        self.ntp_row.subtitle_label.set_text(sub)
        self.change_btn.set_sensitive(not ntp)
        self._select_tz(util.prop(self.proxy, "Timezone", ""))
        self.rtc_switch.set_active(util.prop(self.proxy, "LocalRTC", False))
        self._updating = False

    def _select_tz(self, tz):
        found = []

        def match(model, path, it, _d):
            if model[it][0] == tz:
                found.append(it)
                return True
            return False

        model = self.tz_combo.get_model()
        model.foreach(match, None)
        if found:
            self.tz_combo.set_active_iter(found[0])

    def _tick(self):
        now = datetime.now().astimezone()
        self.clock.set_markup("<span size='xx-large'>%s</span>\n%s" % (
            GLib.markup_escape_text(now.strftime("%X")),
            GLib.markup_escape_text("%s  (%s, UTC%s)" % (
                now.strftime("%A, %x"), util.prop(self.proxy, "Timezone", time.tzname[0]),
                now.strftime("%z")[:3] + ":" + now.strftime("%z")[3:]))))
        return True

    def _call(self, method, sig, args):
        util.dbus_call(self.window, self.proxy, method, GLib.Variant(sig, args),
                       lambda ok: GLib.timeout_add(300, lambda: self._sync() and False))

    def _on_ntp(self, sw, _p):
        if not self._updating:
            self._call("SetNTP", "(bb)", (sw.get_active(), True))

    def _on_rtc(self, sw, _p):
        if not self._updating:
            self._call("SetLocalRTC", "(bbb)", (sw.get_active(), False, True))

    def _on_tz(self, combo):
        tz = combo.get_active_id()
        if not self._updating and tz and tz != util.prop(self.proxy, "Timezone", ""):
            self._call("SetTimezone", "(sb)", (tz, True))

    def _on_change_time(self, _btn):
        dlg = Gtk.Dialog(title=_("Set date and time"), transient_for=self.window, modal=True)
        dlg.add_buttons(_("_Cancel"), Gtk.ResponseType.CANCEL, _("_Set"), Gtk.ResponseType.OK)
        area = dlg.get_content_area()
        area.set_spacing(12)
        area.set_border_width(12)
        now = datetime.now()
        cal = Gtk.Calendar()
        cal.select_month(now.month - 1, now.year)
        cal.select_day(now.day)
        area.add(cal)
        tbox = Gtk.Box(spacing=6, halign=Gtk.Align.CENTER)
        spins = []
        for val, hi in ((now.hour, 23), (now.minute, 59), (now.second, 59)):
            s = Gtk.SpinButton.new_with_range(0, hi, 1)
            s.set_value(val)
            s.set_wrap(True)
            s.set_orientation(Gtk.Orientation.VERTICAL)
            s.connect("output", self._two_digits)
            spins.append(s)
            if len(spins) > 1:
                tbox.pack_start(Gtk.Label(label=":"), False, False, 0)
            tbox.pack_start(s, False, False, 0)
        area.add(tbox)
        dlg.show_all()
        if dlg.run() == Gtk.ResponseType.OK:
            y, m, d = cal.get_date()
            local = datetime(y, m + 1, d, *(int(s.get_value()) for s in spins))
            usec = int(local.timestamp() * 1_000_000)
            self._call("SetTime", "(xbb)", (usec, False, True))
        dlg.destroy()

    @staticmethod
    def _two_digits(spin):
        spin.set_text("%02d" % spin.get_value_as_int())
        return True
