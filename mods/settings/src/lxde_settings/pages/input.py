import os
import shlex
import shutil

from gi.repository import GLib, Gtk

from .. import lxsession, util, xinput
from ..i18n import _
from ..widgets import Page, Section

# libinput pointer settings are not part of lxsession's desktop.conf, so they
# live in our own file and an autostart entry re-applies them at login.
MOUSE_CONF = os.path.join(GLib.get_user_config_dir(), "lxde-settings", "mouse.conf")
AUTOSTART = os.path.join(GLib.get_user_config_dir(), "autostart", "lxde-settings-mouse.desktop")


def load_mouse():
    """(speed -1..1, acceleration, left handed) from the saved file, else the live device."""
    kf = GLib.KeyFile()
    try:
        kf.load_from_file(MOUSE_CONF, GLib.KeyFileFlags.NONE)
        return (kf.get_double("Mouse", "Speed"), kf.get_boolean("Mouse", "Acceleration"),
                kf.get_boolean("Mouse", "LeftHanded"))
    except GLib.Error:
        return xinput.get_state()


def save_mouse(speed, accel, left):
    kf = GLib.KeyFile()
    kf.set_double("Mouse", "Speed", round(speed, 2))
    kf.set_boolean("Mouse", "Acceleration", accel)
    kf.set_boolean("Mouse", "LeftHanded", left)
    os.makedirs(os.path.dirname(MOUSE_CONF), exist_ok=True)
    kf.save_to_file(MOUSE_CONF)
    exe = shutil.which("lxde-settings")
    if exe:  # only when installed; running from the source tree has no stable command
        os.makedirs(os.path.dirname(AUTOSTART), exist_ok=True)
        with open(AUTOSTART, "w") as f:
            f.write("[Desktop Entry]\nType=Application\nName=LXDE Settings mouse\n"
                    "Comment=Apply the mouse settings made in LXDE Settings\n"
                    "Exec=%s --apply-input\nNoDisplay=true\n" % shlex.quote(exe))


def apply_saved():
    """Entry point for ``lxde-settings --apply-input`` at login."""
    state = load_mouse()
    if state is not None:
        xinput.apply(*state)


class InputPage(Page):
    """Mouse and keyboard basics."""

    page_id = "input"
    title = _("Mouse & Keyboard")
    icons = ("preferences-desktop-peripherals", "input-mouse", "input-keyboard")

    def __init__(self, window):
        super().__init__(window)
        self.kf = lxsession.load()
        gi = lambda g, k, d: lxsession.get_int(self.kf, g, k, d)  # noqa: E731
        self._save_id = 0
        self.libinput = xinput.available()

        mouse = self.add_section(Section(_("Mouse and touchpad")))
        if self.libinput:
            speed, accel, left = load_mouse() or (0.0, True, False)
            self.speed = self._scale(-100, 100, round(speed * 100), _("Slow"), _("Fast"))
            mouse.add_row(_("Pointer speed"), self.speed)
            self.accel = Gtk.Switch(active=accel)
            self.accel.connect("notify::active", self._changed)
            mouse.add_row(_("Mouse acceleration"), self.accel,
                          _("The pointer moves farther when you move the mouse faster"))
        else:
            # Non-libinput drivers (evdev) use core pointer acceleration.
            left = gi("Mouse", "LeftHanded", 0) != 0
            self.speed = self._scale(0, 100, gi("Mouse", "AccFactor", 20), _("Slow"), _("Fast"))
            mouse.add_row(_("Pointer speed"), self.speed)
            self.thresh = self._scale(1, 100, gi("Mouse", "AccThreshold", 10), _("Low"), _("High"))
            mouse.add_row(_("Acceleration threshold"), self.thresh,
                          _("How far the pointer moves before it accelerates"))
        self.left = Gtk.Switch(active=left)
        self.left.connect("notify::active", self._changed)
        mouse.add_row(_("Left-handed mouse"), self.left, _("Swap the left and right buttons"))

        kb = self.add_section(Section(_("Keyboard")))
        self.delay = self._scale(100, 2000, gi("Keyboard", "Delay", 500), _("Short"), _("Long"))
        kb.add_row(_("Repeat delay"), self.delay)
        # Store the interval (ms) but present it as speed: faster = shorter interval.
        self.rate = self._scale(10, 200, 210 - gi("Keyboard", "Interval", 30), _("Slow"), _("Fast"))
        kb.add_row(_("Repeat speed"), self.rate)
        self.beep = Gtk.Switch(active=gi("Keyboard", "Beep", 1) != 0)
        self.beep.connect("notify::active", self._changed)
        kb.add_row(_("Keyboard beep"), self.beep)
        kb.add_widget(Gtk.Entry(placeholder_text=_("Type here to test the repeat settings")))

        layouts = Gtk.Button(label=_("Keyboard layouts…"), halign=Gtk.Align.START)
        layouts.connect("clicked", lambda *_a: window.show_page("region"))
        self.content.pack_start(layouts, False, False, 0)

    def _scale(self, lo, hi, value, low_label, high_label):
        s = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, lo, hi, 1)
        s.set_draw_value(False)
        s.set_size_request(260, -1)
        s.add_mark(lo, Gtk.PositionType.BOTTOM, low_label)
        s.add_mark(hi, Gtk.PositionType.BOTTOM, high_label)
        s.set_value(value)
        s.connect("value-changed", self._changed)
        return s

    def _changed(self, *_a):
        self._apply_now()
        if self._save_id:
            GLib.source_remove(self._save_id)
        self._save_id = GLib.timeout_add(500, self._save)

    def _apply_now(self):
        left = self.left.get_active()
        if self.libinput:
            xinput.apply(self.speed.get_value() / 100.0, self.accel.get_active(), left)
        else:
            util.run_async(["xset", "m", "%d/10" % self.speed.get_value(), str(int(self.thresh.get_value()))])
            util.run_async(["xmodmap", "-e", "pointer = 3 2 1" if left else "pointer = default"])
        util.run_async(["xset", "r", "rate", str(int(self.delay.get_value())),
                        str(max(1, round(1000 / (210 - self.rate.get_value()))))])
        util.run_async(["xset", "b", "on" if self.beep.get_active() else "off"])

    def _save(self):
        self._save_id = 0
        left = self.left.get_active()
        values = {("Keyboard", "Delay"): int(self.delay.get_value()),
                  ("Keyboard", "Interval"): 210 - int(self.rate.get_value()),
                  ("Keyboard", "Beep"): int(self.beep.get_active())}
        if self.libinput:
            # lxsession must not swap the buttons too, or left-handed would cancel out.
            values[("Mouse", "LeftHanded")] = 0
        else:
            values.update({("Mouse", "AccFactor"): int(self.speed.get_value()),
                           ("Mouse", "AccThreshold"): int(self.thresh.get_value()),
                           ("Mouse", "LeftHanded"): int(left)})
        try:
            lxsession.update(values)
            if self.libinput:
                save_mouse(self.speed.get_value() / 100.0, self.accel.get_active(), left)
        except (OSError, GLib.Error) as e:
            util.error_dialog(self.window, _("Could not save the settings"), str(e))
        return False
