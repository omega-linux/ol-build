import os
import struct

from gi.repository import GLib, Gtk

from .. import lxsession, openbox, util
from ..i18n import _
from ..widgets import Page, Section


def _theme_dirs(sub):
    home = GLib.get_home_dir()
    dirs = [os.path.join(home, "." + sub), os.path.join(GLib.get_user_data_dir(), sub)]
    dirs += [os.path.join(d, sub) for d in GLib.get_system_data_dirs()]
    return [d for d in dirs if os.path.isdir(d)]


def gtk_themes():
    found = set()
    for d in _theme_dirs("themes"):
        for name in os.listdir(d):
            if os.path.isdir(os.path.join(d, name, "gtk-3.0")):
                found.add(name)
    for builtin in ("Adwaita", "HighContrast"):
        found.add(builtin)
    return sorted(found, key=str.lower)


def icon_themes():
    icons, cursors = set(), set()
    for d in _theme_dirs("icons"):
        for name in os.listdir(d):
            path = os.path.join(d, name)
            if os.path.isdir(os.path.join(path, "cursors")):
                cursors.add(name)
            index = os.path.join(path, "index.theme")
            if name != "default" and os.path.exists(index):
                kf = GLib.KeyFile()
                try:
                    kf.load_from_file(index, GLib.KeyFileFlags.NONE)
                    if kf.get_string("Icon Theme", "Directories").strip():
                        icons.add(name)
                except GLib.Error:  # no Directories key: cursor-only theme
                    pass
    return sorted(icons, key=str.lower), sorted(cursors, key=str.lower)


def cursor_sizes(theme):
    """Nominal sizes stored in the theme's arrow cursor.  Xcursor snaps any
    other size to the nearest of these, so only these are worth offering."""
    for d in _theme_dirs("icons"):
        path = os.path.join(d, theme, "cursors", "left_ptr")
        try:
            with open(path, "rb") as f:
                data = f.read()
        except OSError:
            continue
        if data[:4] != b"Xcur":
            continue
        sizes = set()
        ntoc = struct.unpack_from("<I", data, 12)[0]
        for i in range(min(ntoc, 1024)):
            typ, sub, _pos = struct.unpack_from("<III", data, 16 + i * 12)
            if typ == 0xFFFD0002:  # image chunk; subtype = nominal size
                sizes.add(sub)
        if sizes:
            return sorted(sizes)
    return [24, 32, 48, 64]


class AppearancePage(Page):
    page_id = "appearance"
    title = _("Appearance")
    icons = ("preferences-desktop-theme", "preferences-desktop-wallpaper", "applications-graphics")

    def __init__(self, window):
        super().__init__(window)
        self.kf = lxsession.load()
        self._loading = True
        g = lambda key, d="": lxsession.get(self.kf, "GTK", key, d)  # noqa: E731
        settings = Gtk.Settings.get_default()

        sec = self.add_section(Section(_("Style"), _("Changes apply immediately to all GTK applications.")))
        self.theme = self._combo(gtk_themes(), g("sNet/ThemeName", settings.props.gtk_theme_name))
        sec.add_row(_("Applications theme"), self.theme)
        icons, cursors = icon_themes()
        self.icons = self._combo(icons, g("sNet/IconThemeName", settings.props.gtk_icon_theme_name))
        sec.add_row(_("Icons"), self.icons)
        self.cursor = self._combo(cursors, g("sGtk/CursorThemeName", settings.props.gtk_cursor_theme_name))
        sec.add_row(_("Cursor"), self.cursor)
        # Refill the sizes for the new theme before saving, not after.
        self.cursor.disconnect_by_func(self._changed)
        self.cursor.connect("changed", self._on_cursor_theme)
        self.cursor_size = Gtk.ComboBoxText()
        self.cursor_size.set_size_request(240, -1)
        self._fill_cursor_sizes(lxsession.get_int(self.kf, "GTK", "iGtk/CursorThemeSize", 24) or 24)
        self.cursor_size.connect("changed", self._changed)
        sec.add_row(_("Cursor size"), self.cursor_size,
                    _("Applications that were already open keep their cursor until restarted"))
        self.ob_rc = openbox.rc_path()
        current = openbox.get_theme(self.ob_rc) if self.ob_rc else None
        if current is not None:
            self.ob_theme = Gtk.ComboBoxText()
            names = openbox.themes()
            for n in names + ([current] if current not in names else []):
                self.ob_theme.append(n, n)
            self.ob_theme.set_active_id(current)
            self.ob_theme.set_size_request(240, -1)
            self.ob_theme.connect("changed", self._on_ob_theme)
            sec.add_row(_("Window borders"), self.ob_theme, _("Openbox title bars and frames"))
        self._restart_id = 0
        self._cursor_state = self._cursor_values()

        fonts = self.add_section(Section(_("Fonts")))
        self.font = Gtk.FontButton(font=g("sGtk/FontName", settings.props.gtk_font_name), use_font=True)
        self.font.connect("font-set", self._changed)
        fonts.add_row(_("Default font"), self.font)
        self.antialias = Gtk.Switch(active=lxsession.get_int(self.kf, "GTK", "iXft/Antialias", 1) != 0)
        self.antialias.connect("notify::active", self._changed)
        fonts.add_row(_("Antialiasing"), self.antialias)
        self.hinting = Gtk.ComboBoxText()
        for hid, label in (("hintnone", _("None")), ("hintslight", _("Slight")),
                           ("hintmedium", _("Medium")), ("hintfull", _("Full"))):
            self.hinting.append(hid, label)
        self.hinting.set_active_id(g("sXft/HintStyle", "hintslight"))
        self.hinting.connect("changed", self._changed)
        fonts.add_row(_("Hinting"), self.hinting)
        self.rgba = Gtk.ComboBoxText()
        for rid, label in (("none", _("Grayscale")), ("rgb", "RGB"), ("bgr", "BGR"),
                           ("vrgb", _("Vertical RGB")), ("vbgr", _("Vertical BGR"))):
            self.rgba.append(rid, label)
        self.rgba.set_active_id(g("sXft/RGBA", "rgb"))
        self.rgba.connect("changed", self._changed)
        fonts.add_row(_("Subpixel order"), self.rgba)

        more = self.add_section(Section(_("More")))
        self._launcher(more, _("Desktop background"), ["pcmanfm", "--desktop-pref"],
                       _("Wallpaper and desktop icons"))
        self._launcher(more, _("Panel"), ["lxpanelctl", "config"], _("Panel size, position and applets"))

        if not lxsession.is_running():
            self.content.pack_start(Gtk.Label(
                label=_("lxsession is not running: settings are saved but may need a restart of the "
                        "applications to take effect."), wrap=True, xalign=0), False, False, 0)
        self._loading = False

    def _fill_cursor_sizes(self, want):
        sizes = cursor_sizes(self.cursor.get_active_id() or "")
        nearest = min(sizes, key=lambda n: abs(n - want))
        self.cursor_size.remove_all()
        for n in sizes:
            self.cursor_size.append(str(n), "%d px" % n)
        self.cursor_size.set_active_id(str(nearest))

    def _on_cursor_theme(self, _combo):
        if self._loading:
            return
        self._loading = True  # refilling the sizes must not trigger a second save
        self._fill_cursor_sizes(int(self.cursor_size.get_active_id() or 24))
        self._loading = False
        self._changed()

    def _on_ob_theme(self, combo):
        try:
            openbox.set_theme(self.ob_rc, combo.get_active_id())
        except (OSError, ValueError) as e:
            util.error_dialog(self.window, _("Could not save the settings"), str(e))

    def _cursor_values(self):
        return self.cursor.get_active_id(), self.cursor_size.get_active_id()

    def _restart_wm(self):
        """Openbox loads its cursors (frames and root window, which most
        windows inherit) only at startup, so restart it in place.  Windows
        stay open."""
        self._restart_id = 0
        if util.run_sync(["pgrep", "-x", "-u", str(os.getuid()), "openbox"]).strip():
            util.run_async(["openbox", "--restart"])
        return False

    def _combo(self, names, active):
        c = Gtk.ComboBoxText()
        for n in names:
            c.append(n, n)
        if active and active not in names:
            c.append(active, active)
        c.set_active_id(active)
        c.set_size_request(240, -1)
        c.connect("changed", self._changed)
        return c

    def _launcher(self, section, title, argv, subtitle):
        btn = Gtk.Button(label=_("Open"))
        btn.connect("clicked", lambda *_a: util.spawn(argv))
        row = section.add_row(title, btn, subtitle)
        if not util.which(argv[0]):
            btn.set_sensitive(False)
            row.subtitle_label.set_text(_("Install %s to use this") % argv[0])

    def _changed(self, *_a):
        if self._loading:
            return
        theme = self.theme.get_active_id() or ""
        icons = self.icons.get_active_id() or ""
        cursor = self.cursor.get_active_id() or ""
        font = self.font.get_font() or ""
        size = int(self.cursor_size.get_active_id() or 24)
        values = {("GTK", "iGtk/CursorThemeSize"): size,
                  ("GTK", "iXft/Antialias"): 1 if self.antialias.get_active() else 0,
                  ("GTK", "iXft/Hinting"): 0 if self.hinting.get_active_id() == "hintnone" else 1,
                  ("GTK", "sXft/HintStyle"): self.hinting.get_active_id() or "hintslight",
                  ("GTK", "sXft/RGBA"): self.rgba.get_active_id() or "rgb"}
        for key, val in (("sNet/ThemeName", theme), ("sNet/IconThemeName", icons),
                         ("sGtk/CursorThemeName", cursor), ("sGtk/FontName", font)):
            if val:
                values[("GTK", key)] = val
        try:
            lxsession.update(values)
            lxsession.write_gtk_files(theme, icons, font, cursor, size)
        except (OSError, GLib.Error) as e:
            util.error_dialog(self.window, _("Could not save the settings"), str(e))
            return
        if not lxsession.reload_settings_daemon():
            # No XSettings daemon: at least update this window.
            s = Gtk.Settings.get_default()
            s.props.gtk_theme_name = theme
            s.props.gtk_icon_theme_name = icons
            s.props.gtk_font_name = font
        if self._cursor_values() != self._cursor_state:
            self._cursor_state = self._cursor_values()
            if self._restart_id:
                GLib.source_remove(self._restart_id)
            # Give lxsession a moment to publish Xcursor.* before Openbox re-reads it.
            self._restart_id = GLib.timeout_add(700, self._restart_wm)
