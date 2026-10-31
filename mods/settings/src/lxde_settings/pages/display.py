import math
import os
import re
import shlex

from gi.repository import GLib, Gtk

from .. import util
from ..i18n import _
from ..widgets import Page, Section

AUTOSTART = os.path.join(GLib.get_user_config_dir(), "autostart", "lxrandr-autostart.desktop")
REVERT_SECONDS = 15

ROTATIONS = (
    ("normal", _("Landscape")),
    ("left", _("Portrait (left)")),
    ("right", _("Portrait (right)")),
    ("inverted", _("Landscape (flipped)")),
)


class Output:
    def __init__(self, name, connected, primary):
        self.name = name
        self.connected = connected
        self.primary = primary
        self.geometry = None  # (w, h, x, y) when enabled
        self.rotation = "normal"
        self.mm = (0, 0)
        self.modes = []  # [(res, [rates])]
        self.mode = None
        self.rate = None
        self.preferred = None

    @property
    def enabled(self):
        return self.geometry is not None

    def inches(self):
        w, h = self.mm
        return math.hypot(w, h) / 25.4 if w and h else 0


def parse_xrandr(text):
    outputs = []
    cur = None
    head = re.compile(r"^(\S+) (connected|disconnected)( primary)?"
                      r"(?: (\d+)x(\d+)\+(\d+)\+(\d+))?(?: (normal|left|inverted|right))?")
    for line in text.splitlines():
        m = head.match(line)
        if m:
            cur = Output(m.group(1), m.group(2) == "connected", bool(m.group(3)))
            if m.group(4):
                cur.geometry = tuple(int(m.group(i)) for i in range(4, 8))
                cur.rotation = m.group(8) or "normal"
            mm = re.search(r"(\d+)mm x (\d+)mm", line)
            if mm:
                cur.mm = (int(mm.group(1)), int(mm.group(2)))
            outputs.append(cur)
            continue
        m = re.match(r"^\s+(\d+x\d+i?)\s+(.*)$", line)
        if cur is not None and m:
            res, rates = m.group(1), []
            for tok in m.group(2).split():
                num = re.match(r"([\d.]+)", tok)
                if num:
                    rates.append(num.group(1))
                if not rates:
                    continue
                if "*" in tok:
                    cur.mode, cur.rate = res, rates[-1]
                if "+" in tok and cur.preferred is None:
                    cur.preferred = res
            cur.modes.append((res, rates))
    return outputs


def relation(o, ref):
    """Describe o's position relative to ref as an xrandr option."""
    if not (o.geometry and ref.geometry):
        return "right-of"
    ow, oh, ox, oy = o.geometry
    rw, rh, rx, ry = ref.geometry
    if (ox, oy) == (rx, ry):
        return "same-as"
    if ox >= rx + rw:
        return "right-of"
    if ox + ow <= rx:
        return "left-of"
    if oy + oh <= ry:
        return "above"
    return "below"


def state_argv(outputs):
    """xrandr command that reproduces the given state exactly."""
    argv = ["xrandr"]
    for o in outputs:
        if not o.connected and not o.enabled:
            continue
        argv += ["--output", o.name]
        if o.enabled and o.mode:
            w, h, x, y = o.geometry
            argv += ["--mode", o.mode, "--rate", o.rate or "", "--rotate", o.rotation, "--pos", "%dx%d" % (x, y)]
            if o.primary:
                argv.append("--primary")
        else:
            argv.append("--off")
    return [a for a in argv if a != ""]


class OutputSection(Section):
    def __init__(self, page, out, others, ref):
        size = out.inches()
        title = "%s — %.1f″" % (out.name, size) if size else out.name
        super().__init__(title)
        self.page = page
        self.out = out
        multi = bool(others)
        self._ready = False

        self.enable = Gtk.Switch(active=out.enabled)
        self.enable.connect("notify::active", self._changed)
        if multi:
            self.add_row(_("Use this display"), self.enable)

        self.primary = Gtk.CheckButton(active=out.primary)
        self.primary.connect("toggled", self._on_primary)
        if multi:
            self.add_row(_("Make this my main display"), self.primary)

        self.res = Gtk.ComboBoxText()
        for res, _rates in out.modes:
            label = res.replace("x", " × ")
            if res == out.preferred:
                label = _("%s (recommended)") % label
            self.res.append(res, label)
        self.res.set_active_id(out.mode or out.preferred or (out.modes[0][0] if out.modes else ""))
        self.res.connect("changed", self._on_res)
        self.add_row(_("Resolution"), self.res)

        self.rate = Gtk.ComboBoxText()
        self.rate.connect("changed", self._changed)
        self.add_row(_("Refresh rate"), self.rate)
        self._fill_rates(out.rate)

        self.rot = Gtk.ComboBoxText()
        for rid, label in ROTATIONS:
            self.rot.append(rid, label)
        self.rot.set_active_id(out.rotation)
        self.rot.connect("changed", self._changed)
        self.add_row(_("Orientation"), self.rot)

        self.pos = None
        self.ref = ref
        if ref is not None:
            self.pos = Gtk.ComboBoxText()
            for rid, label in (("right-of", _("Right of %s")), ("left-of", _("Left of %s")),
                               ("above", _("Above %s")), ("below", _("Below %s")),
                               ("same-as", _("Mirror %s"))):
                self.pos.append(rid, label % ref.name)
            self.pos.set_active_id(relation(out, ref))
            self.pos.connect("changed", self._changed)
            self.pos_row = self.add_row(_("Position"), self.pos)

        for combo in (self.res, self.rate, self.rot) + ((self.pos,) if self.pos else ()):
            combo.set_size_request(240, -1)
        self._sync_sensitive()
        self._ready = True

    def _fill_rates(self, active=None):
        self.rate.remove_all()
        rates = dict(self.out.modes).get(self.res.get_active_id(), [])
        for r in sorted(set(rates), key=float, reverse=True):
            self.rate.append(r, "%.2f Hz" % float(r))
        if active in rates:
            self.rate.set_active_id(active)
        else:
            self.rate.set_active(0)

    def _on_res(self, _c):
        self._fill_rates()
        self._changed()

    def _on_primary(self, btn):
        if btn.get_active():
            self.page.set_primary(self)
        self._changed()

    def _sync_sensitive(self):
        on = self.enable.get_active()
        for w in (self.res, self.rate, self.rot, self.primary) + ((self.pos,) if self.pos else ()):
            w.set_sensitive(on)

    def _changed(self, *_a):
        if not self._ready:
            return
        self._sync_sensitive()
        self.page.mark_dirty()

    def argv(self):
        a = ["--output", self.out.name]
        if not self.enable.get_active():
            return a + ["--off"]
        a += ["--mode", self.res.get_active_id(), "--rotate", self.rot.get_active_id()]
        if self.rate.get_active_id():
            a += ["--rate", self.rate.get_active_id()]
        if self.primary.get_active():
            a.append("--primary")
        if self.pos is not None:
            a += ["--%s" % self.pos.get_active_id(), self.ref.name]
        return a


class DisplayPage(Page):
    page_id = "display"
    title = _("Display")
    icons = ("preferences-desktop-display", "video-display", "display")

    def __init__(self, window):
        super().__init__(window)
        self.box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=24)
        self.content.pack_start(self.box, False, False, 0)

        detect = Gtk.Button(label=_("Detect displays"))
        detect.connect("clicked", lambda *_a: self.load())
        self.apply_btn = Gtk.Button(label=_("Apply"))
        self.apply_btn.get_style_context().add_class("suggested-action")
        self.apply_btn.connect("clicked", self._apply)
        bar = Gtk.Box(spacing=6)
        bar.pack_start(detect, False, False, 0)
        bar.pack_end(self.apply_btn, False, False, 0)
        self.content.pack_start(bar, False, False, 0)

        if not util.which("xrandr"):
            self.box.add(Gtk.Label(label=_("xrandr is not installed."), xalign=0))
            bar.set_sensitive(False)
            return
        self.load()

    def load(self):
        for c in self.box.get_children():
            c.destroy()
        self.outputs = parse_xrandr(util.run_sync(["xrandr", "--query"]))
        connected = [o for o in self.outputs if o.connected or o.enabled]
        self.sections = []
        if not connected:
            self.box.add(Gtk.Label(label=_("No displays were detected."), xalign=0))
        # Show enabled outputs first so positions are relative to an active one.
        connected.sort(key=lambda o: (not o.primary, not o.enabled))
        for i, o in enumerate(connected):
            others = [x for x in connected if x is not o]
            # Every other display is positioned relative to the first one.
            sec = OutputSection(self, o, others, connected[0] if i > 0 else None)
            self.sections.append(sec)
            self.box.pack_start(sec, False, False, 0)
        self.box.show_all()
        self.apply_btn.set_sensitive(False)

    def set_primary(self, section):
        for s in self.sections:
            if s is not section and s.primary.get_active():
                s.primary.set_active(False)

    def mark_dirty(self):
        self.apply_btn.set_sensitive(True)

    def _apply(self, _btn):
        argv = ["xrandr"]
        for s in self.sections:
            argv += s.argv()
        if all(not s.enable.get_active() for s in self.sections):
            util.error_dialog(self.window, _("At least one display must stay on."))
            return
        revert = state_argv(self.outputs)

        def applied(status, _out, err):
            if status != 0:
                util.error_dialog(self.window, _("The display settings could not be applied"), err.strip())
                util.run_async(revert, lambda *_a: self.load())
                return
            if self._confirm():
                self._save(argv)
                self.load()
            else:
                util.run_async(revert, lambda *_a: self.load())

        util.run_async(argv, applied)

    def _confirm(self):
        dlg = Gtk.MessageDialog(transient_for=self.window, modal=True, message_type=Gtk.MessageType.QUESTION,
                                buttons=Gtk.ButtonsType.NONE, text=_("Keep these display settings?"))
        dlg.add_button(_("_Revert"), Gtk.ResponseType.CANCEL)
        dlg.add_button(_("_Keep changes"), Gtk.ResponseType.OK)
        dlg.set_default_response(Gtk.ResponseType.CANCEL)
        left = [REVERT_SECONDS]

        def tick():
            dlg.format_secondary_text(_("Reverting to the previous settings in %d seconds.") % left[0])
            left[0] -= 1
            if left[0] < 0:
                dlg.response(Gtk.ResponseType.CANCEL)
                return False
            return True

        tick()
        tid = GLib.timeout_add_seconds(1, tick)
        resp = dlg.run()
        if left[0] >= 0:
            GLib.source_remove(tid)
        dlg.destroy()
        return resp == Gtk.ResponseType.OK

    def _save(self, argv):
        """Persist like lxrandr: an autostart entry that re-runs xrandr at login."""
        os.makedirs(os.path.dirname(AUTOSTART), exist_ok=True)
        cmd = " ".join(shlex.quote(a) for a in argv)
        with open(AUTOSTART, "w") as f:
            f.write("[Desktop Entry]\nType=Application\nName=LXRandR autostart\n"
                    "Comment=Start xrandr with settings done in LXDE Settings\n"
                    "Exec=sh -c %s\nOnlyShowIn=LXDE\n" % shlex.quote(cmd).replace("%", "%%"))

