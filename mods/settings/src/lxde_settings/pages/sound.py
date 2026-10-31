from gi.repository import Gtk

from .. import util
from ..i18n import _
from ..widgets import Page, Section


def _volume_icon(volume, mute, kind):
    if kind == "source":
        return "microphone-sensitivity-muted" if mute else "audio-input-microphone"
    if mute or volume <= 0:
        return "audio-volume-muted"
    if volume < 0.34:
        return "audio-volume-low"
    if volume < 0.67:
        return "audio-volume-medium"
    return "audio-volume-high"


class DeviceSection(Section):
    """Device chooser + port chooser + volume slider for sinks or sources."""

    def __init__(self, client, kind, title, chooser_label, volume_label):
        super().__init__(title)
        self.client = client
        self.kind = kind
        self._updating = False

        self.device_combo = Gtk.ComboBoxText()
        self.device_combo.set_size_request(320, -1)
        self.device_combo.connect("changed", self._on_device)
        self.add_row(chooser_label, self.device_combo)

        self.port_combo = Gtk.ComboBoxText()
        self.port_combo.set_size_request(320, -1)
        self.port_combo.connect("changed", self._on_port)
        self.port_row = self.add_row(_("Connector"), self.port_combo)

        box = Gtk.Box(spacing=6)
        self.mute_btn = Gtk.ToggleButton(relief=Gtk.ReliefStyle.NONE)
        self.mute_btn.set_tooltip_text(_("Mute"))
        self.mute_img = Gtk.Image()
        self.mute_btn.add(self.mute_img)
        self.mute_btn.connect("toggled", self._on_mute)
        self.scale = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 0, 100, 1)
        self.scale.set_draw_value(False)
        self.scale.set_size_request(260, -1)
        self.scale.connect("value-changed", self._on_volume)
        self.value_lbl = Gtk.Label(width_chars=4, xalign=1)
        box.pack_start(self.mute_btn, False, False, 0)
        box.pack_start(self.scale, True, True, 0)
        box.pack_start(self.value_lbl, False, False, 0)
        self.add_row(volume_label, box)

    def devices(self):
        return self.client.sinks if self.kind == "sink" else self.client.sources

    def current(self):
        default = self.client.default_sink if self.kind == "sink" else self.client.default_source
        for d in self.devices():
            if d.name == default:
                return d
        return None

    def update(self):
        self._updating = True
        devs = self.devices()
        self.device_combo.remove_all()
        for d in devs:
            self.device_combo.append(d.name, d.description)
        cur = self.current()
        self.set_sensitive(cur is not None)
        if cur is None:
            self.device_combo.append("", _("No devices found"))
            self.device_combo.set_active_id("")
            self.port_row.hide()
            self._updating = False
            return
        self.device_combo.set_active_id(cur.name)

        self.port_combo.remove_all()
        for name, desc, available in cur.ports:
            self.port_combo.append(name, desc if available else _("%s (unplugged)") % desc)
        self.port_combo.set_active_id(cur.active_port)
        self.port_row.set_visible(len(cur.ports) > 1)

        pct = round(cur.volume * 100)
        if not self.scale.has_grab():
            self.scale.set_value(min(pct, 100))
        self.value_lbl.set_text("%d" % pct)
        self.mute_btn.set_active(cur.mute)
        self.mute_img.set_from_icon_name(
            util.icon_name(_volume_icon(cur.volume, cur.mute, self.kind), "audio-volume-high"),
            Gtk.IconSize.BUTTON)
        self._updating = False

    def _on_device(self, combo):
        name = combo.get_active_id()
        if not self._updating and name:
            self.client.set_default(self.kind, name)

    def _on_port(self, combo):
        port, cur = combo.get_active_id(), self.current()
        if not self._updating and port and cur and port != cur.active_port:
            self.client.set_port(self.kind, cur, port)

    def _on_mute(self, btn):
        cur = self.current()
        if not self._updating and cur:
            self.client.set_mute(self.kind, cur, btn.get_active())

    def _on_volume(self, scale):
        cur = self.current()
        if self._updating or not cur:
            return
        v = scale.get_value()
        self.value_lbl.set_text("%d" % v)
        self.client.set_volume(self.kind, cur, v / 100.0)
        if cur.mute and v > 0:
            self.client.set_mute(self.kind, cur, False)


class SoundPage(Page):
    page_id = "sound"
    title = _("Sound")
    icons = ("preferences-desktop-sound", "audio-volume-high", "multimedia-volume-control")

    def __init__(self, window):
        super().__init__(window)
        from ..pulse import PulseClient

        self.client = PulseClient()
        self.status = Gtk.Label(label=_("Connecting to the sound server…"), xalign=0)
        self.status.get_style_context().add_class("dim-label")
        self.content.pack_start(self.status, False, False, 0)

        self.output = self.add_section(DeviceSection(
            self.client, "sink", _("Output"), _("Choose your output device"), _("Master volume")))
        self.input = self.add_section(DeviceSection(
            self.client, "source", _("Input"), _("Choose your input device"), _("Input volume")))

        adv = self.add_section(Section(_("Advanced")))
        if util.which("pavucontrol"):
            b = Gtk.Button(label=_("Open volume mixer"))
            b.connect("clicked", lambda *_a: util.spawn(["pavucontrol"]))
            adv.add_row(_("App volume and device preferences"), b,
                        _("Set the volume and device of each application"))
        else:
            adv.add_row(_("App volume and device preferences"), None,
                        _("Install pavucontrol to adjust each application separately"))

        self.client.connect("changed", self._on_changed)
        self.client.connect("state-changed", self._on_state)
        self.output.set_sensitive(False)
        self.input.set_sensitive(False)

    def _on_state(self, client):
        if client.connected:
            self.status.set_text("")
            self.status.hide()
        else:
            self.status.set_text(_("Not connected to the sound server. Retrying…"))
            self.status.show()
            self.output.set_sensitive(False)
            self.input.set_sensitive(False)

    def _on_changed(self, client):
        self.status.set_text(_("Sound server: %s") % client.server_name)
        self.status.show()
        self.output.update()
        self.input.update()
