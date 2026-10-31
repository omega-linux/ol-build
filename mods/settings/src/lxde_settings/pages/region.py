import gettext
import json
import re

from gi.repository import GLib, Gtk

from .. import util
from ..i18n import _
from ..widgets import Page, Section

ISO_DIR = "/usr/share/iso-codes/json"
XKB_RULES = "/usr/share/X11/xkb/rules/evdev.lst"
SUPPORTED = "/usr/share/i18n/SUPPORTED"
FORMAT_KEYS = ("LC_NUMERIC", "LC_TIME", "LC_MONETARY", "LC_PAPER", "LC_NAME", "LC_ADDRESS",
               "LC_TELEPHONE", "LC_MEASUREMENT", "LC_IDENTIFICATION")


def _iso_table(fname, key, domain):
    try:
        with open("%s/%s" % (ISO_DIR, fname)) as f:
            data = json.load(f)
    except (OSError, ValueError):
        return {}
    entries = next(iter(data.values()))
    return {e[key]: gettext.dgettext(domain, e["name"]) for e in entries if key in e}


_languages = None
_countries = None


def locale_label(loc):
    """'es_MX.UTF-8' -> 'Español (México) — es_MX.UTF-8' using iso-codes."""
    global _languages, _countries
    if _languages is None:
        _languages = _iso_table("iso_639-3.json", "alpha_3", "iso_639-3")
        _languages.update(_iso_table("iso_639-3.json", "alpha_2", "iso_639-3"))
        _countries = _iso_table("iso_3166-1.json", "alpha_2", "iso_3166-1")
    m = re.match(r"([a-z]{2,3})(?:_([A-Z]{2}))?", loc)
    if not m:
        return loc
    lang = _languages.get(m.group(1))
    if not lang:
        return loc
    lang = lang[0].upper() + lang[1:]
    if m.group(2) and m.group(2) in _countries:
        return "%s (%s) — %s" % (lang, _countries[m.group(2)], loc)
    return "%s — %s" % (lang, loc)


def _norm(loc):
    """'de_DE.UTF-8' and 'de_DE.utf8' -> 'de_DE'; keeps @modifiers."""
    return re.sub(r"\.utf-?8", "", loc, flags=re.I)


def parse_xkb_rules():
    """Return (layouts {id: desc}, variants {layout: [(id, desc)]}, options [(id, desc)])."""
    layouts, variants, options = {}, {}, []
    section = None
    try:
        with open(XKB_RULES) as f:
            for line in f:
                line = line.rstrip("\n")
                if line.startswith("! "):
                    section = line[2:].strip()
                    continue
                m = re.match(r"\s+(\S+)\s+(.*)", line)
                if not m:
                    continue
                name, desc = m.group(1), m.group(2).strip()
                if section == "layout":
                    layouts[name] = gettext.dgettext("xkeyboard-config", desc)
                elif section == "variant":
                    lay, _sep, d = desc.partition(": ")
                    variants.setdefault(lay, []).append((name, gettext.dgettext("xkeyboard-config", d)))
                elif section == "option" and name.startswith("grp:") and name.endswith("toggle"):
                    options.append((name, gettext.dgettext("xkeyboard-config", desc)))
    except OSError:
        pass
    return layouts, variants, options


class RegionPage(Page):
    page_id = "region"
    title = _("Region & Language")
    icons = ("preferences-desktop-locale", "config-language", "preferences-desktop-keyboard")

    def __init__(self, window):
        super().__init__(window)
        self.localed = util.system_proxy("org.freedesktop.locale1", "/org/freedesktop/locale1",
                                         "org.freedesktop.locale1")
        if self.localed is None:
            self.content.pack_start(Gtk.Label(
                label=_("The locale service (systemd-localed) is not available."), xalign=0), False, False, 0)
            return
        self._build_language()
        self._build_keyboard()
        self.localed.connect("g-properties-changed", lambda *_a: self._load_keyboard())

    # --- language ----------------------------------------------------------

    def _current_locale(self):
        env = {}
        for item in util.prop(self.localed, "Locale", []):
            k, _sep, v = item.partition("=")
            env[k] = v
        return env

    def _build_language(self):
        sec = self.add_section(Section(
            _("Language"),
            _("Changes take effect the next time you log in. Use “Add languages” to install "
              "a language that is not in the list yet.")))
        self.lang_combo = Gtk.ComboBoxText()
        self.fmt_combo = Gtk.ComboBoxText()
        for c in (self.lang_combo, self.fmt_combo):
            c.set_size_request(320, -1)
        self._fill_locales()
        sec.add_row(_("Display language"), self.lang_combo, _("Menus, windows and messages"))
        sec.add_row(_("Formats"), self.fmt_combo, _("Dates, times, numbers and currency"))

        self.lang_apply = Gtk.Button(label=_("Apply"), sensitive=False)
        self.lang_apply.get_style_context().add_class("suggested-action")
        self.lang_apply.connect("clicked", self._apply_language)
        for c in (self.lang_combo, self.fmt_combo):
            c.connect("changed", lambda *_a: self._filling or self.lang_apply.set_sensitive(True))
        add = Gtk.Button(label=_("Add languages…"))
        add.connect("clicked", self._on_add_languages)
        bb = Gtk.Box(spacing=6)
        bb.pack_start(add, False, False, 0)
        bb.pack_end(self.lang_apply, False, False, 0)
        sec.add_widget(bb)

    def _generated_locales(self):
        return [l for l in util.run_sync(["localectl", "list-locales"]).split() if l]

    def _fill_locales(self, keep=None):
        """(Re)fill both combos; ``keep`` = (lang, fmt) selections to restore."""
        self._filling = True
        locales = self._generated_locales()
        env = self._current_locale()
        for v in env.values():
            if v and v not in locales:
                locales.append(v)
        items = sorted(((l, locale_label(l)) for l in locales), key=lambda x: x[1].lower())
        self.lang_combo.remove_all()
        self.fmt_combo.remove_all()
        self.fmt_combo.append("", _("Same as the display language"))
        for loc, label in items:
            self.lang_combo.append(loc, label)
            self.fmt_combo.append(loc, label)
        if keep:
            lang, fmt = keep
        else:
            lang = env.get("LANG", "")
            fmt = env.get("LC_TIME") or env.get("LC_NUMERIC") or ""
            fmt = fmt if fmt != lang else ""
        self.lang_combo.set_active_id(lang)
        self.fmt_combo.set_active_id(fmt)
        self._filling = False

    def _on_add_languages(self, _btn):
        installed = {_norm(l) for l in self._generated_locales()}
        try:
            with open(SUPPORTED) as f:
                available = [p[0] for p in (l.split() for l in f)
                             if len(p) == 2 and p[1] == "UTF-8" and _norm(p[0]) not in installed]
        except OSError:
            util.error_dialog(self.window, _("The list of available languages could not be read"), SUPPORTED)
            return

        dlg = Gtk.Dialog(title=_("Add languages"), transient_for=self.window, modal=True)
        dlg.set_default_size(520, 560)
        dlg.add_buttons(_("_Cancel"), Gtk.ResponseType.CANCEL, _("_Install"), Gtk.ResponseType.OK)
        area = dlg.get_content_area()
        area.set_spacing(6)
        area.set_border_width(12)
        area.pack_start(Gtk.Label(label=_("Select the languages to install. Generating them can take a minute."),
                                  xalign=0, wrap=True), False, False, 0)
        search = Gtk.SearchEntry(placeholder_text=_("Search languages"))
        area.pack_start(search, False, False, 0)

        store = Gtk.ListStore(bool, str, str)  # checked, label, locale
        for loc in sorted(available, key=lambda l: locale_label(l).lower()):
            store.append([False, locale_label(loc), loc])
        filt = store.filter_new()
        filt.set_visible_func(lambda m, it, _d: search.get_text().strip().lower() in m[it][1].lower())
        search.connect("search-changed", lambda *_a: filt.refilter())

        view = Gtk.TreeView(model=filt, headers_visible=False, enable_search=False)
        toggle = Gtk.CellRendererToggle()
        ok_btn = dlg.get_widget_for_response(Gtk.ResponseType.OK)
        ok_btn.set_sensitive(False)

        def on_toggle(_cell, path):
            row = store[filt.convert_path_to_child_path(Gtk.TreePath(path))]
            row[0] = not row[0]
            ok_btn.set_sensitive(any(r[0] for r in store))

        toggle.connect("toggled", on_toggle)
        view.append_column(Gtk.TreeViewColumn("", toggle, active=0))
        view.append_column(Gtk.TreeViewColumn("", Gtk.CellRendererText(), text=1))
        view.connect("row-activated", lambda v, path, _c: on_toggle(None, path.to_string()))
        sw = Gtk.ScrolledWindow(shadow_type=Gtk.ShadowType.IN)
        sw.add(view)
        area.pack_start(sw, True, True, 0)

        busy = Gtk.Box(spacing=6)
        busy.pack_start(Gtk.Spinner(active=True), False, False, 0)
        busy.pack_start(Gtk.Label(label=_("Generating languages…")), False, False, 0)
        area.pack_start(busy, False, False, 0)
        dlg.show_all()
        busy.hide()

        def on_response(d, resp):
            if resp != Gtk.ResponseType.OK:
                d.destroy()
                return
            chosen = [r[2] for r in store if r[0]]
            keep = (self.lang_combo.get_active_id(), self.fmt_combo.get_active_id())
            busy.show()
            for w in (sw, search, ok_btn, d.get_widget_for_response(Gtk.ResponseType.CANCEL)):
                w.set_sensitive(False)

            def done(ok):
                d.destroy()
                if ok:
                    self._fill_locales(keep)

            util.run_helper(self.window, ["add-locales"] + chosen, done)

        dlg.connect("response", on_response)

    @staticmethod
    def _end(widget):
        box = Gtk.Box(halign=Gtk.Align.END)
        box.pack_start(widget, False, False, 0)
        return box

    def _apply_language(self, _btn):
        env = self._current_locale()
        lang = self.lang_combo.get_active_id() or env.get("LANG", "C.UTF-8")
        fmt = self.fmt_combo.get_active_id()
        new = {k: v for k, v in env.items() if k not in FORMAT_KEYS}
        new["LANG"] = lang
        if fmt and fmt != lang:
            for k in FORMAT_KEYS:
                new[k] = fmt
        arr = ["%s=%s" % (k, v) for k, v in new.items()]

        def done(ok):
            if ok:
                self.lang_apply.set_sensitive(False)
                dlg = Gtk.MessageDialog(transient_for=self.window, modal=True, message_type=Gtk.MessageType.INFO,
                                        buttons=Gtk.ButtonsType.OK, text=_("Language settings saved"))
                dlg.format_secondary_text(_("Log out and back in to use the new settings."))
                dlg.run()
                dlg.destroy()

        util.dbus_call(self.window, self.localed, "SetLocale", GLib.Variant("(asb)", (arr, True)), done)

    # --- keyboard ----------------------------------------------------------

    def _build_keyboard(self):
        self.xkb_layouts, self.xkb_variants, grp_options = parse_xkb_rules()
        sec = self.add_section(Section(
            _("Keyboard"),
            _("The first layout is the default. The layouts are applied to this session "
              "and saved as the system-wide default.")))
        self.kb_section = sec
        self.layout_list = Gtk.ListBox(selection_mode=Gtk.SelectionMode.NONE)
        sec.add_widget(self.layout_list, margin=0)

        add = Gtk.Button(label=_("Add a layout…"))
        add.connect("clicked", self._on_add_layout)
        self.switch_combo = Gtk.ComboBoxText()
        self.switch_combo.append("", _("Not set"))
        for oid, desc in grp_options:
            self.switch_combo.append(oid, desc)
        self.switch_combo.set_size_request(320, -1)
        self.switch_combo.connect("changed", lambda *_a: self._dirty())
        sec.add_row(_("Switch layouts with"), self.switch_combo)

        self.kb_apply = Gtk.Button(label=_("Apply"), sensitive=False)
        self.kb_apply.get_style_context().add_class("suggested-action")
        self.kb_apply.connect("clicked", self._apply_keyboard)
        bb = Gtk.Box(spacing=6)
        bb.pack_start(add, False, False, 0)
        bb.pack_end(self.kb_apply, False, False, 0)
        sec.add_widget(bb)

        test = self.add_section(Section(_("Test the keyboard")))
        test.add_widget(Gtk.Entry(placeholder_text=_("Type here to test the layout")))
        self._load_keyboard()

    def _load_keyboard(self):
        layouts = [l for l in util.prop(self.localed, "X11Layout", "").split(",") if l]
        variants = util.prop(self.localed, "X11Variant", "").split(",")
        self.model = util.prop(self.localed, "X11Model", "")
        self.options = [o for o in util.prop(self.localed, "X11Options", "").split(",") if o]
        if not layouts:  # fall back to what the session is using
            out = util.run_sync(["setxkbmap", "-query"])
            m = re.search(r"layout:\s*(\S+)", out)
            layouts = m.group(1).split(",") if m else ["us"]
            m = re.search(r"variant:\s*(\S+)", out)
            variants = m.group(1).split(",") if m else []
        self.layouts = [(l, variants[i] if i < len(variants) else "") for i, l in enumerate(layouts)]
        grp = next((o for o in self.options if o.startswith("grp:")), "")
        self._loading = True
        self.switch_combo.set_active_id(grp)
        if self.switch_combo.get_active_id() is None:
            self.switch_combo.set_active_id("")
        self._loading = False
        self._fill_layouts()
        self.kb_apply.set_sensitive(False)

    def _layout_desc(self, layout, variant):
        if variant:
            for vid, desc in self.xkb_variants.get(layout, []):
                if vid == variant:
                    return desc
        return self.xkb_layouts.get(layout, layout)

    def _fill_layouts(self):
        for c in self.layout_list.get_children():
            c.destroy()
        for i, (lay, var) in enumerate(self.layouts):
            row = Gtk.ListBoxRow(activatable=False)
            box = Gtk.Box(spacing=6, margin_start=12, margin_end=12, margin_top=6, margin_bottom=6)
            box.pack_start(Gtk.Label(label=self._layout_desc(lay, var), xalign=0), True, True, 0)
            code = Gtk.Label(label=lay + ("(%s)" % var if var else ""))
            code.get_style_context().add_class("dim-label")
            box.pack_start(code, False, False, 0)
            for icon, tip, cb, sens in (
                    ("go-up-symbolic", _("Move up"), self._move, i > 0),
                    ("go-down-symbolic", _("Move down"), self._move, i < len(self.layouts) - 1),
                    ("list-remove-symbolic", _("Remove"), self._remove, len(self.layouts) > 1)):
                b = Gtk.Button.new_from_icon_name(icon, Gtk.IconSize.BUTTON)
                b.set_relief(Gtk.ReliefStyle.NONE)
                b.set_tooltip_text(tip)
                b.set_sensitive(sens)
                b.connect("clicked", cb, i, icon)
                box.pack_start(b, False, False, 0)
            row.add(box)
            self.layout_list.add(row)
        self.layout_list.set_header_func(
            lambda row, before: row.set_header(Gtk.Separator()) if before and not row.get_header() else None)
        self.layout_list.show_all()

    def _dirty(self):
        if not getattr(self, "_loading", False):
            self.kb_apply.set_sensitive(True)

    def _move(self, _btn, i, icon):
        j = i - 1 if icon.startswith("go-up") else i + 1
        self.layouts[i], self.layouts[j] = self.layouts[j], self.layouts[i]
        self._fill_layouts()
        self._dirty()

    def _remove(self, _btn, i, _icon):
        del self.layouts[i]
        self._fill_layouts()
        self._dirty()

    def _on_add_layout(self, _btn):
        dlg = Gtk.Dialog(title=_("Add a keyboard layout"), transient_for=self.window, modal=True)
        dlg.set_default_size(460, 520)
        dlg.add_buttons(_("_Cancel"), Gtk.ResponseType.CANCEL, _("_Add"), Gtk.ResponseType.OK)
        area = dlg.get_content_area()
        area.set_spacing(6)
        area.set_border_width(12)
        search = Gtk.SearchEntry(placeholder_text=_("Search layouts"))
        area.pack_start(search, False, False, 0)

        store = Gtk.TreeStore(str, str, str)  # label, layout, variant
        for lay, desc in sorted(self.xkb_layouts.items(), key=lambda x: x[1].lower()):
            it = store.append(None, [desc, lay, ""])
            for vid, vdesc in sorted(self.xkb_variants.get(lay, []), key=lambda x: x[1].lower()):
                store.append(it, [vdesc, lay, vid])
        filt = store.filter_new()

        def visible(model, it, _d):
            q = search.get_text().strip().lower()
            if not q:
                return True
            if q in model[it][0].lower() or q == model[it][1]:
                return True
            child = model.iter_children(it)
            while child:
                if q in model[child][0].lower():
                    return True
                child = model.iter_next(child)
            parent = model.iter_parent(it)
            return bool(parent and q in model[parent][0].lower())

        filt.set_visible_func(visible)
        view = Gtk.TreeView(model=filt, headers_visible=False, enable_search=False)
        view.append_column(Gtk.TreeViewColumn("", Gtk.CellRendererText(), text=0))
        search.connect("search-changed", lambda *_a: (filt.refilter(),
                                                      view.expand_all() if search.get_text() else None))
        view.connect("row-activated", lambda *_a: dlg.response(Gtk.ResponseType.OK))
        sw = Gtk.ScrolledWindow(shadow_type=Gtk.ShadowType.IN)
        sw.add(view)
        area.pack_start(sw, True, True, 0)
        dlg.show_all()
        if dlg.run() == Gtk.ResponseType.OK:
            model, it = view.get_selection().get_selected()
            if it:
                entry = (model[it][1], model[it][2])
                if entry not in self.layouts:
                    self.layouts.append(entry)
                    self._fill_layouts()
                    self._dirty()
        dlg.destroy()

    def _apply_keyboard(self, _btn):
        layout = ",".join(l for l, _v in self.layouts)
        variant = ",".join(v for _l, v in self.layouts)
        if not variant.strip(","):
            variant = ""
        grp = self.switch_combo.get_active_id() or ""
        options = [o for o in self.options if not o.startswith("grp:")]
        if grp and len(self.layouts) > 1:
            options.append(grp)
        # Apply to the running X session right away.
        argv = ["setxkbmap", "-layout", layout, "-variant", variant, "-option", ""]
        for o in options:
            argv += ["-option", o]
        if self.model:
            argv += ["-model", self.model]
        util.run_async(argv)
        util.dbus_call(self.window, self.localed, "SetX11Keyboard",
                       GLib.Variant("(ssssbb)", (layout, self.model, variant, ",".join(options), True, True)),
                       lambda ok: self.kb_apply.set_sensitive(not ok))
