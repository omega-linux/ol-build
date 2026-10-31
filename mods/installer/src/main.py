#!/usr/bin/env python3
import configparser
import os
import pwd
import re
import shutil
import subprocess
import sys
import threading
import traceback

sys.path.insert(0, os.path.dirname(os.path.realpath(__file__)))

import gi
gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
gi.require_version("GdkPixbuf", "2.0")
gi.require_version("Pango", "1.0")
from gi.repository import Gdk, GdkPixbuf, GLib, Gtk, Pango

import backend
import i18n
import partitioning
from i18n import _
from partitioning import MIB, Free, Part
from util import InstallError, firmware, human_size, log

CONFIG_DIR = os.environ.get("SYSTEM_INSTALLER_CONFIG", "/etc/system-installer")

DEFAULTS = {
    "branding": {
        "name": "Ubuntu",
        "version": "",
        "logo": "",
        "icon": "system-software-install",
        "accent": "",
        "window_title": "Install {name}",
        "welcome_title": "Welcome",
        "welcome_text": "This will install {name} {version} on your computer.\\n\\n"
                        "Make sure you have backed up anything important before you continue.",
        "wait_text": "Please wait while we get everything ready…",
        "done_title": "Installation complete",
        "done_text": "{name} has finished installing.",
        "language": "",
    },
    "system": {
        "hostname": "",
        "timezone": "",
        "locale": "",
        "keyboard": "",
        "groups": "sudo adm cdrom dip plugdev audio video render netdev lpadmin users",
        "kernel_cmdline": "quiet splash",
        "grub_distributor": "{name}",
        "grub_timeout": "5",
        "bootloader_id": "ubuntu",
        "esp_size_mib": "512",
    },
}
TEXT_KEYS = ("window_title", "welcome_title", "welcome_text", "wait_text", "done_title", "done_text")

if False:
    _("Install {name}")
    _("Welcome")
    _("This will install {name} {version} on your computer.\n\n"
      "Make sure you have backed up anything important before you continue.")
    _("Please wait while we get everything ready…")
    _("Installation complete")
    _("{name} has finished installing.")


class SafeDict(dict):
    def __missing__(self, key):
        return "{" + key + "}"


class Config(dict):
    def text(self, key):
        lang = i18n.current.lower()
        raw = self.raw.get("%s[%s]" % (key, lang)) or self.raw.get("%s[%s]" % (key, lang.split("_")[0]))
        if not raw:
            raw = _(self.raw[key])
        return raw.format_map(SafeDict(name=self["name"], version=self["version"])).strip()


def load_config():
    cp = configparser.ConfigParser(interpolation=None)
    cp.read_dict(DEFAULTS)
    cp.read(os.path.join(CONFIG_DIR, "branding.conf"))
    cfg = Config()
    cfg.raw = {}
    for section in cp.sections():
        for key, value in cp.items(section):
            value = value.strip().replace("\\n", "\n")
            cfg.raw[key] = value
    names = SafeDict(name=cfg.raw["name"], version=cfg.raw["version"])
    for section in DEFAULTS:
        for key in DEFAULTS[section]:
            cfg[key] = cfg.raw[key].format_map(names).strip()
    for key in ("logo", "icon"):
        path = os.path.join(CONFIG_DIR, cfg[key])
        if cfg[key] and not os.path.isabs(cfg[key]) and os.path.isfile(path):
            cfg[key] = path
    return cfg


def timezones():
    zones = []
    try:
        with open("/usr/share/zoneinfo/tzdata.zi") as f:
            for line in f:
                parts = line.split()
                if len(parts) >= 2 and parts[0] in ("Z", "L"):
                    zones.append(parts[1] if parts[0] == "Z" else parts[2])
    except OSError:
        pass
    if not zones:
        root = "/usr/share/zoneinfo"
        for region in ("Africa", "America", "Antarctica", "Asia", "Atlantic", "Australia",
                       "Europe", "Indian", "Pacific", "Etc"):
            for dirpath, _d, files in os.walk(os.path.join(root, region)):
                for f in files:
                    zones.append(os.path.relpath(os.path.join(dirpath, f), root))
    return sorted({z for z in zones if "/" in z and not z.startswith(("posix/", "right/"))} | {"UTC"})


def current_timezone():
    try:
        with open("/etc/timezone") as f:
            return f.read().strip()
    except OSError:
        pass
    link = os.path.realpath("/etc/localtime")
    return link.split("/zoneinfo/", 1)[1] if "/zoneinfo/" in link else "UTC"


def firmware_label(fw):
    return {"bios": _("Legacy BIOS"), "efi32": _("32-bit UEFI"), "efi64": _("64-bit UEFI")}[fw]


def label(text, css=None, wrap=True, xalign=0.0):
    w = Gtk.Label(label=text)
    w.set_line_wrap(wrap)
    w.set_xalign(xalign)
    if css:
        w.get_style_context().add_class(css)
    return w


def markup(text, xalign=0.0):
    w = Gtk.Label()
    w.set_markup(text)
    w.set_line_wrap(True)
    w.set_xalign(xalign)
    return w


def page_box():
    box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
    box.set_border_width(24)
    return box


def scrolled(child, height=-1):
    sw = Gtk.ScrolledWindow()
    sw.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
    sw.set_shadow_type(Gtk.ShadowType.IN)
    if height > 0:
        sw.set_min_content_height(height)
    sw.add(child)
    return sw


def list_view(columns):
    store = Gtk.ListStore(*([str] * (len(columns) + 1)))
    view = Gtk.TreeView(model=store)
    for i, title in enumerate(columns):
        col = Gtk.TreeViewColumn(title, Gtk.CellRendererText(), text=i + 1)
        col.set_expand(True)
        view.append_column(col)
    view.set_headers_visible(any(columns))
    view.set_search_column(1)
    return view, store


def matches(query, *texts):
    words = query.lower().split()
    haystack = " ".join(texts).lower()
    return all(w in haystack for w in words)


def shrinkable(combo):
    for cell in combo.get_cells():
        if isinstance(cell, Gtk.CellRendererText):
            cell.set_property("ellipsize", Pango.EllipsizeMode.END)
    combo.set_hexpand(True)
    return combo


class SearchCombo(Gtk.MenuButton):
    def __init__(self, items, changed=None):
        super().__init__()
        self.changed = changed
        self.active = None
        self.labels = dict(items)
        self.text = Gtk.Label(xalign=0)
        self.text.set_ellipsize(Pango.EllipsizeMode.END)
        inner = Gtk.Box(spacing=6)
        inner.pack_start(self.text, True, True, 0)
        inner.pack_end(Gtk.Image.new_from_icon_name("pan-down-symbolic", Gtk.IconSize.BUTTON), False, False, 0)
        self.add(inner)

        self.search = Gtk.SearchEntry()
        self.store = Gtk.ListStore(str, str)
        for key, text in items:
            self.store.append([key, text])
        self.filter = self.store.filter_new()
        self.filter.set_visible_func(lambda model, it, _d: matches(self.search.get_text(), model[it][0], model[it][1]))
        self.view = Gtk.TreeView(model=self.filter)
        self.view.set_headers_visible(False)
        self.view.set_enable_search(False)
        cell = Gtk.CellRendererText(ellipsize=Pango.EllipsizeMode.END)
        self.view.append_column(Gtk.TreeViewColumn("", cell, text=1))
        self.view.connect("row-activated", lambda v, path, _c: self.choose(self.filter[path][0]))
        self.search.set_placeholder_text(_("Search…"))
        self.search.connect("search-changed", self.on_search)
        self.search.connect("activate", self.on_enter)
        self.search.connect("key-press-event", self.on_key)

        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        box.set_border_width(6)
        box.pack_start(self.search, False, False, 0)
        sw = scrolled(self.view)
        self.scroller = sw
        box.pack_start(sw, True, True, 0)
        box.show_all()
        pop = Gtk.Popover()
        pop.add(box)
        pop.connect("show", self.on_show)
        self.set_popover(pop)

    def fit(self):
        top = self.get_toplevel()
        if not top.get_realized():
            return
        win_w, win_h = top.get_allocated_width(), top.get_allocated_height()
        coords = self.translate_coordinates(top, 0, 0)
        y = coords[1] if coords else 0
        below = win_h - y - self.get_allocated_height()
        pop = self.get_popover()
        pop.set_position(Gtk.PositionType.BOTTOM if below >= y else Gtk.PositionType.TOP)
        room = max(below, y) - self.search.get_preferred_height()[1] - 40
        height = max(80, min(320, room))
        width = max(200, min(440, win_w - 40))
        self.scroller.set_size_request(width, height)

    def on_show(self, _pop):
        self.fit()
        GLib.idle_add(lambda: self.fit() and False)
        self.search.set_text("")
        self.filter.refilter()
        for row in self.filter:
            if row[0] == self.active:
                self.view.set_cursor(row.path, None, False)
                self.view.scroll_to_cell(row.path, None, True, 0.4, 0)
        self.search.grab_focus()

    def on_search(self, _entry):
        self.filter.refilter()
        if len(self.filter):
            self.view.set_cursor(Gtk.TreePath(0), None, False)
            self.view.scroll_to_point(0, 0)

    def on_enter(self, _entry):
        _model, it = self.view.get_selection().get_selected()
        if it:
            self.choose(self.filter[it][0])

    def on_key(self, _entry, event):
        if event.keyval in (Gdk.KEY_Down, Gdk.KEY_Up):
            _model, it = self.view.get_selection().get_selected()
            if it is None:
                return False
            path = self.filter.get_path(it)
            index = path.get_indices()[0] + (1 if event.keyval == Gdk.KEY_Down else -1)
            if 0 <= index < len(self.filter):
                self.view.set_cursor(Gtk.TreePath(index), None, False)
            return True
        return False

    def choose(self, key):
        self.set_active_id(key)
        self.get_popover().popdown()
        if self.changed:
            self.changed(key)

    def add_item(self, key, text):
        if key not in self.labels:
            self.labels[key] = text
            self.store.append([key, text])

    def set_active_id(self, key):
        if key not in self.labels:
            return False
        self.active = key
        self.text.set_text(self.labels[key])
        return True

    def get_active_id(self):
        return self.active


def select_row(view, key):
    store = view.get_model()
    for row in store:
        if row[0] == key:
            view.set_cursor(row.path, None, False)
            view.scroll_to_cell(row.path, None, True, 0.3, 0)
            return True
    return False


class InstallerWindow(Gtk.Window):
    def __init__(self, cfg):
        super().__init__()
        self.cfg = cfg
        self.fw = firmware()
        self.required = backend.required_size()
        self.busy = False
        self.plan = {}
        self.history = []
        self.manual_layout = None
        self.locale_edited = bool(cfg["locale"])
        self.keyboard_edited = bool(cfg["keyboard"])
        langs = [code for code, *_r in i18n.available()]
        wanted = cfg["language"] if cfg["language"] in langs else self.guess_language(langs)
        i18n.set_language(wanted)
        self.locale = cfg["locale"] or i18n.best_locale(wanted)
        self.language_packs = True
        kb = (cfg["keyboard"] or i18n.language(wanted)[3]).split(":")
        self.keyboard = (kb[0], kb[1] if len(kb) > 1 else "")
        width, height = 820, 580
        display = Gdk.Display.get_default()
        monitor = display.get_primary_monitor() or display.get_monitor(0) if display else None
        if monitor:
            area = monitor.get_workarea()
            width, height = min(width, area.width - 20), min(height, area.height - 40)
        self.set_default_size(width, height)
        self.set_position(Gtk.WindowPosition.CENTER)
        if cfg["icon"]:
            if os.path.isfile(cfg["icon"]):
                self.set_icon_from_file(cfg["icon"])
            else:
                self.set_icon_name(cfg["icon"])
        self.connect("delete-event", lambda *_a: self.busy)
        self.apply_css()
        self.build()
        self.apply_keyboard()

    def guess_language(self, langs):
        env = os.environ.get("LANG", "en").split(".")[0]
        for code in (env, env.split("_")[0]):
            if code in langs:
                return code
        return "en"

    def apply_css(self):
        css = "label.error { color: #c01c28; }\n.big-wait { font-size: 16pt; }\n"
        accent = self.cfg["accent"]
        if re.fullmatch(r"#[0-9a-fA-F]{3,8}", accent):
            css += ("button.suggested-action { background-image: none; background-color: %s; "
                    "border-color: %s; color: #ffffff; }\n"
                    "progressbar progress { background-image: none; background-color: %s; border-color: %s; }\n"
                    % (accent, accent, accent, accent))
        provider = Gtk.CssProvider()
        provider.load_from_data(css.encode())
        Gtk.StyleContext.add_provider_for_screen(Gdk.Screen.get_default(), provider,
                                                 Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)

    def logo(self, size):
        path = self.cfg["logo"]
        try:
            if path and os.path.isfile(path):
                pb = GdkPixbuf.Pixbuf.new_from_file_at_scale(path, size, size, True)
                return Gtk.Image.new_from_pixbuf(pb)
            if self.cfg["icon"] and os.path.isfile(self.cfg["icon"]):
                pb = GdkPixbuf.Pixbuf.new_from_file_at_scale(self.cfg["icon"], size, size, True)
                return Gtk.Image.new_from_pixbuf(pb)
            if self.cfg["icon"]:
                img = Gtk.Image.new_from_icon_name(self.cfg["icon"], Gtk.IconSize.DIALOG)
                img.set_pixel_size(size)
                return img
        except GLib.Error:
            pass
        return None

    def build(self, page="welcome"):
        child = self.get_child()
        if child:
            self.remove(child)
            child.destroy()
        self.set_title(self.cfg.text("window_title"))
        outer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.add(outer)

        header = Gtk.Box(spacing=12)
        header.set_border_width(16)
        logo = self.logo(48)
        if logo:
            header.pack_start(logo, False, False, 0)
        self.title = markup("")
        header.pack_start(self.title, True, True, 0)
        outer.pack_start(header, False, False, 0)
        outer.pack_start(Gtk.Separator(), False, False, 0)

        self.stack = Gtk.Stack()
        self.stack.set_transition_type(Gtk.StackTransitionType.SLIDE_LEFT_RIGHT)
        outer.pack_start(self.stack, True, True, 0)

        outer.pack_start(Gtk.Separator(), False, False, 0)
        buttons = Gtk.Box(spacing=8)
        buttons.set_border_width(12)
        self.error_label = label("")
        self.error_label.get_style_context().add_class("error")
        buttons.pack_start(self.error_label, True, True, 0)
        self.back_btn = Gtk.Button(label=_("Back"))
        self.back_btn.connect("clicked", self.on_back)
        self.next_btn = Gtk.Button(label=_("Continue"))
        self.next_btn.get_style_context().add_class("suggested-action")
        self.next_btn.connect("clicked", self.on_next)
        buttons.pack_end(self.next_btn, False, False, 0)
        buttons.pack_end(self.back_btn, False, False, 0)
        self.button_bar = buttons
        outer.pack_start(buttons, False, False, 0)

        self.titles = {}
        for name in ("welcome", "keyboard", "disk", "partition", "user", "summary", "progress", "done"):
            getattr(self, "build_" + name)()
        outer.show_all()
        self.show_page(page, push=False)

    def add_page(self, name, title, widget):
        self.titles[name] = title
        sw = Gtk.ScrolledWindow()
        sw.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
        sw.add(widget)
        self.stack.add_named(sw, name)

    def show_page(self, name, push=True):
        current = self.stack.get_visible_child_name()
        if push and current and current != name:
            self.history.append(current)
        self.stack.set_visible_child_name(name)
        self.title.set_markup("<span size='x-large' weight='bold'>%s</span>"
                              % GLib.markup_escape_text(self.titles[name]))
        self.error_label.set_text("")
        self.back_btn.set_visible(bool(self.history) and name not in ("progress", "done"))
        self.next_btn.set_label({"summary": _("Install now"), "done": _("Restart now")}.get(name, _("Continue")))
        self.button_bar.set_visible(name != "progress")
        refresh = getattr(self, "enter_" + name, None)
        if refresh:
            refresh()

    def error(self, text):
        self.error_label.set_text(text)

    def on_back(self, _b):
        if self.history:
            self.show_page(self.history.pop(), push=False)

    def on_next(self, _b):
        getattr(self, "next_" + self.stack.get_visible_child_name())()

    def build_welcome(self):
        box = Gtk.Box(spacing=18)
        box.set_border_width(24)
        self.lang_list = Gtk.ListBox()
        self.lang_list.set_selection_mode(Gtk.SelectionMode.BROWSE)
        for code, native, *_r in i18n.available():
            row = Gtk.ListBoxRow()
            row.code = code
            lab = label(native, wrap=False)
            lab.set_margin_start(8)
            lab.set_margin_top(4)
            lab.set_margin_bottom(4)
            row.add(lab)
            self.lang_list.add(row)
            if code == i18n.current:
                self.lang_list.select_row(row)
        self.lang_list.connect("row-selected", self.on_language)
        sw = scrolled(self.lang_list)
        sw.set_size_request(230, -1)
        box.pack_start(sw, False, False, 0)

        right = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        right.set_valign(Gtk.Align.CENTER)
        logo = self.logo(112)
        if logo:
            right.pack_start(logo, False, False, 0)
        right.pack_start(markup("<span size='xx-large' weight='bold'>%s</span>" % GLib.markup_escape_text(
            ("%s %s" % (self.cfg["name"], self.cfg["version"])).strip()), xalign=0.5), False, False, 0)
        text = label(self.cfg.text("welcome_text"), xalign=0.5)
        text.set_justify(Gtk.Justification.CENTER)
        right.pack_start(text, False, False, 0)

        grid = Gtk.Grid(column_spacing=12, row_spacing=8)
        grid.set_margin_top(12)
        self.locale_combo = SearchCombo(i18n.system_locales(), self.on_locale)
        self.locale_combo.set_hexpand(True)
        self.locale_combo.add_item(self.locale, self.locale)
        self.locale_combo.set_active_id(self.locale)
        grid.attach(label(_("Language of the installed system")), 0, 0, 1, 1)
        grid.attach(self.locale_combo, 0, 1, 1, 1)
        self.langpack_check = Gtk.CheckButton(label=_("Download language support (needs an internet connection)"))
        self.langpack_check.get_child().set_line_wrap(True)
        self.langpack_check.set_active(self.language_packs)
        self.langpack_check.connect("toggled", lambda c: setattr(self, "language_packs", c.get_active()))
        grid.attach(self.langpack_check, 0, 2, 1, 1)
        right.pack_start(grid, False, False, 0)
        right.pack_start(label(_("Firmware detected: %s") % firmware_label(self.fw), "dim-label", xalign=0.5),
                         False, False, 0)
        box.pack_start(right, True, True, 0)
        self.add_page("welcome", self.cfg.text("welcome_title"), box)

    def on_language(self, _list, row):
        if not row or row.code == i18n.current:
            return
        i18n.set_language(row.code)
        if not self.locale_edited:
            self.locale = i18n.best_locale(row.code)
        if not self.keyboard_edited:
            kb = i18n.language(row.code)[3].split(":")
            self.keyboard = (kb[0], kb[1] if len(kb) > 1 else "")
            self.apply_keyboard()
        GLib.idle_add(self.build, "welcome")

    def on_locale(self, key):
        self.locale = key
        self.locale_edited = True

    def next_welcome(self):
        self.show_page("keyboard")

    def build_keyboard(self):
        box = page_box()
        box.pack_start(label(_("Choose your keyboard layout:")), False, False, 0)
        panes = Gtk.Box(spacing=12, homogeneous=True)
        self.layout_view, self.layout_store = list_view([""])
        self.variant_view, self.variant_store = list_view([""])
        self.layouts = {name: (desc, variants) for name, desc, variants in i18n.keyboard_layouts()}
        self.layouts.pop("custom", None)
        for name, (desc, _v) in sorted(self.layouts.items(), key=lambda e: e[1][0].lower()):
            self.layout_store.append([name, desc])
        self.layout_search = Gtk.SearchEntry()
        self.layout_search.set_placeholder_text(_("Search…"))
        self.layout_filter = self.layout_store.filter_new()
        self.layout_filter.set_visible_func(
            lambda model, it, _d: matches(self.layout_search.get_text(), model[it][0], model[it][1]))
        self.layout_view.set_model(self.layout_filter)
        self.layout_view.set_enable_search(False)
        self.layout_search.connect("search-changed", lambda _e: self.on_layout_search())
        left = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        left.pack_start(self.layout_search, False, False, 0)
        left.pack_start(scrolled(self.layout_view, 230), True, True, 0)
        right = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        spacer = Gtk.Box()
        sizes = Gtk.SizeGroup(mode=Gtk.SizeGroupMode.VERTICAL)
        sizes.add_widget(self.layout_search)
        sizes.add_widget(spacer)
        right.pack_start(spacer, False, False, 0)
        right.pack_start(scrolled(self.variant_view, 230), True, True, 0)
        panes.pack_start(left, True, True, 0)
        panes.pack_start(right, True, True, 0)
        box.pack_start(panes, True, True, 0)
        self.kb_test = Gtk.Entry()
        self.kb_test.set_placeholder_text(_("Type here to test your keyboard"))
        box.pack_start(self.kb_test, False, False, 0)
        self.layout_view.get_selection().connect("changed", self.on_layout)
        self.variant_view.get_selection().connect("changed", self.on_variant)
        self.add_page("keyboard", _("Keyboard layout"), box)

    def enter_keyboard(self):
        layout, variant = self.keyboard
        if layout not in self.layouts:
            layout, variant = "us", ""
        self.loading_kb = True
        select_row(self.layout_view, layout)
        self.fill_variants(layout)
        select_row(self.variant_view, variant)
        self.loading_kb = False

    def on_layout_search(self):
        self.loading_kb = True
        self.layout_filter.refilter()
        select_row(self.layout_view, self.keyboard[0])
        self.loading_kb = False

    def fill_variants(self, layout):
        self.variant_store.clear()
        desc, variants = self.layouts.get(layout, ("", []))
        self.variant_store.append(["", desc])
        for v, d in sorted(variants, key=lambda e: e[1].lower()):
            self.variant_store.append([v, d])

    def on_layout(self, sel):
        model, it = sel.get_selected()
        if not it or getattr(self, "loading_kb", False):
            return
        self.loading_kb = True
        self.fill_variants(model[it][0])
        select_row(self.variant_view, "")
        self.loading_kb = False
        self.set_keyboard(model[it][0], "")

    def on_variant(self, sel):
        model, it = sel.get_selected()
        if not it or getattr(self, "loading_kb", False):
            return
        lmodel, lit = self.layout_view.get_selection().get_selected()
        if lit:
            self.set_keyboard(lmodel[lit][0], model[it][0])

    def set_keyboard(self, layout, variant):
        self.keyboard = (layout, variant)
        self.keyboard_edited = True
        self.apply_keyboard()

    def session_user(self):
        user = os.environ.get("SUDO_USER")
        if not user and os.environ.get("PKEXEC_UID"):
            try:
                user = pwd.getpwuid(int(os.environ["PKEXEC_UID"])).pw_name
            except (KeyError, ValueError):
                user = None
        return user if user and user != "root" else None

    def apply_keyboard(self):
        layout, variant = self.keyboard
        quiet = {"stdout": subprocess.DEVNULL, "stderr": subprocess.DEVNULL}
        if shutil.which("setxkbmap") and os.environ.get("DISPLAY"):
            cmd = ["setxkbmap", "-model", "pc105", "-layout", layout, "-variant", variant]
            if subprocess.run(cmd, **quiet).returncode != 0:
                user = self.session_user()
                if user and shutil.which("runuser"):
                    env = ["env", "DISPLAY=" + os.environ["DISPLAY"]]
                    if os.environ.get("XAUTHORITY"):
                        env.append("XAUTHORITY=" + os.environ["XAUTHORITY"])
                    if subprocess.run(["runuser", "-u", user, "--"] + env + cmd, **quiet).returncode != 0:
                        log("setxkbmap failed for %s:%s" % (layout, variant))
        if os.geteuid() == 0 and os.path.isdir("/etc/default"):
            try:
                with open("/etc/default/keyboard", "w") as f:
                    f.write('XKBMODEL="pc105"\nXKBLAYOUT="%s"\nXKBVARIANT="%s"\nXKBOPTIONS=""\n\nBACKSPACE="guess"\n'
                            % (layout, variant))
            except OSError:
                pass
            if shutil.which("setupcon"):
                subprocess.Popen(["setupcon", "-k", "--force"], **quiet)

    def next_keyboard(self):
        self.show_page("disk")

    def build_disk(self):
        box = page_box()
        self.erase_radio = Gtk.RadioButton.new_with_label(None, _("Erase disk and install %s") % self.cfg["name"])
        box.pack_start(self.erase_radio, False, False, 0)
        erase_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        erase_box.set_margin_start(28)
        self.disk_combo = shrinkable(Gtk.ComboBoxText())
        erase_box.pack_start(self.disk_combo, False, False, 0)
        erase_box.pack_start(label(_("Everything on the selected disk will be deleted."), "dim-label"),
                             False, False, 0)
        box.pack_start(erase_box, False, False, 0)
        self.manual_radio = Gtk.RadioButton.new_with_label_from_widget(self.erase_radio, _("Something else"))
        box.pack_start(self.manual_radio, False, False, 0)
        hint = label(_("Create, delete or choose partitions yourself, or choose multiple partitions."),
                     "dim-label")
        hint.set_margin_start(28)
        box.pack_start(hint, False, False, 0)
        if self.plan.get("mode") == "manual":
            self.manual_radio.set_active(True)
        self.erase_radio.connect("toggled", lambda r: self.disk_combo.set_sensitive(r.get_active()))
        if self.required:
            box.pack_start(label(_("%(name)s needs at least %(size)s of disk space.") % {
                "name": self.cfg["name"], "size": human_size(self.min_size())}, "dim-label"), False, False, 12)
        self.add_page("disk", _("Installation type"), box)

    def min_size(self):
        return int(self.required * 1.2) + (int(self.cfg["esp_size_mib"]) + 2) * MIB + 2 * 1000 ** 3

    def enter_disk(self):
        self.erase_disks = partitioning.scan(self.fw).disks
        active = self.disk_combo.get_active_id() or self.plan.get("disk")
        self.disk_combo.remove_all()
        for d in self.erase_disks:
            self.disk_combo.append(d.path, d.describe())
        if not (active and self.disk_combo.set_active_id(active)) and self.erase_disks:
            self.disk_combo.set_active(0)
        self.disk_combo.set_sensitive(self.erase_radio.get_active())

    def next_disk(self):
        if self.erase_radio.get_active():
            path = self.disk_combo.get_active_id()
            if not path:
                return self.error(_("No disk available to install to."))
            layout = partitioning.scan(self.fw)
            disk = layout.disk(path)
            if self.required and disk.size < self.min_size():
                return self.error(_("%(disk)s is too small (%(size)s needed).")
                                  % {"disk": path, "size": human_size(self.min_size())})
            layout.erase(disk, int(self.cfg["esp_size_mib"]))
            self.plan.update(mode="erase", disk=path, layout=layout, bios_disk=path)
            self.show_page("user")
        else:
            self.plan["mode"] = "manual"
            self.show_page("partition")

    def build_partition(self):
        box = page_box()
        box.set_spacing(8)
        self.part_store = Gtk.TreeStore(str, str, str, str, bool, bool, str, int)
        self.part_view = Gtk.TreeView(model=self.part_store)
        cols = [(_("Device"), 1), (_("Type"), 2), (_("Mount point"), 3)]
        for title, idx in cols:
            cell = Gtk.CellRendererText()
            col = Gtk.TreeViewColumn(title, cell, text=idx, weight=7)
            col.set_resizable(True)
            col.set_expand(idx == 2)
            self.part_view.append_column(col)
        toggle = Gtk.CellRendererToggle()
        self.part_view.append_column(Gtk.TreeViewColumn(_("Format?"), toggle, active=4, visible=5))
        self.part_view.append_column(Gtk.TreeViewColumn(_("Size"), Gtk.CellRendererText(), text=6, weight=7))
        self.part_view.get_selection().connect("changed", lambda _s: self.update_part_buttons())
        self.part_view.connect("row-activated", lambda *_a: self.on_part_activate())
        box.pack_start(scrolled(self.part_view, 240), True, True, 0)

        tools = Gtk.Box(spacing=6)
        self.btn_add = Gtk.Button.new_from_icon_name("list-add-symbolic", Gtk.IconSize.BUTTON)
        self.btn_add.set_tooltip_text(_("Add a partition"))
        self.btn_del = Gtk.Button.new_from_icon_name("list-remove-symbolic", Gtk.IconSize.BUTTON)
        self.btn_del.set_tooltip_text(_("Delete the partition"))
        self.btn_change = Gtk.Button(label=_("Change…"))
        self.btn_table = Gtk.Button(label=_("New Partition Table…"))
        self.btn_revert = Gtk.Button(label=_("Revert"))
        self.btn_add.connect("clicked", lambda _b: self.on_add())
        self.btn_del.connect("clicked", lambda _b: self.on_delete())
        self.btn_change.connect("clicked", lambda _b: self.on_change())
        self.btn_table.connect("clicked", lambda _b: self.on_new_table())
        self.btn_revert.connect("clicked", lambda _b: self.rescan())
        for b in (self.btn_add, self.btn_del, self.btn_change):
            tools.pack_start(b, False, False, 0)
        tools.pack_end(self.btn_revert, False, False, 0)
        tools.pack_end(self.btn_table, False, False, 0)
        if shutil.which("gparted"):
            editor = Gtk.Button(label=_("Open GParted"))
            editor.set_tooltip_text(_("Resize or move partitions (pending changes here are discarded)"))
            editor.connect("clicked", self.on_gparted)
            tools.pack_end(editor, False, False, 0)
        box.pack_start(tools, False, False, 0)

        grid = Gtk.Grid(column_spacing=12, row_spacing=6)
        self.bios_combo = shrinkable(Gtk.ComboBoxText())
        self.bios_combo.set_hexpand(True)
        grid.attach(label(_("Device for boot loader installation (Legacy BIOS)"), wrap=False), 0, 0, 1, 1)
        grid.attach(self.bios_combo, 1, 0, 1, 1)
        box.pack_start(grid, False, False, 0)
        need = {"bios": _("This computer started in Legacy BIOS mode."),
                "efi32": _("This computer started in 32-bit UEFI mode, so an EFI system partition is needed."),
                "efi64": _("This computer started in 64-bit UEFI mode, so an EFI system partition is needed.")}
        box.pack_start(label(need[self.fw], "dim-label"), False, False, 0)
        self.add_page("partition", _("Installation type"), box)

    def enter_partition(self):
        if self.manual_layout is None:
            self.manual_layout = partitioning.scan(self.fw)
        self.populate()

    def rescan(self):
        self.manual_layout = partitioning.scan(self.fw)
        self.populate()

    def on_gparted(self, button):
        button.set_sensitive(False)
        proc = subprocess.Popen(["gparted"])

        def done(_pid, _status):
            button.set_sensitive(True)
            self.rescan()
        GLib.child_watch_add(GLib.PRIORITY_DEFAULT, proc.pid, done)

    def populate(self):
        layout = self.manual_layout
        keep = self.selected_key()
        self.error("")
        self.rows = {}
        self.part_store.clear()
        for disk in layout.disks:
            key = "d:" + disk.path
            self.rows[key] = disk
            table = disk.label.upper() if disk.label else _("no partition table")
            parent = self.part_store.append(None, [key, disk.path, "%s  (%s)" % (disk.model, table), "",
                                                   False, False, human_size(disk.size), 700])
            for i, seg in enumerate(disk.segments()):
                key = "s:%s:%d" % (disk.path, i)
                self.rows[key] = seg
                if isinstance(seg, Free):
                    self.part_store.append(parent, [key, "  " + _("free space"), "", "", False, False,
                                                    human_size(seg.size), 400])
                else:
                    if seg.use:
                        kind = partitioning.use_label(seg.use)
                    elif seg.extended:
                        kind = _("Extended partition")
                    else:
                        kind = seg.fs or _("unknown")
                    name = seg.name() + ("  “%s”" % seg.label if seg.label else "")
                    self.part_store.append(parent, [key, "  " + name, kind, seg.mount,
                                                    seg.will_format(), bool(seg.use and seg.use != "biosgrub"),
                                                    human_size(seg.size), 400])
        self.part_view.expand_all()
        if keep:
            for row in self.iter_rows(self.part_store):
                if row[0] == keep:
                    self.part_view.get_selection().select_iter(row.iter)
        current = self.bios_combo.get_active_id()
        if current is None:
            current = self.plan.get("bios_disk") or ""
            if not current and self.fw == "bios" and layout.disks:
                current = layout.disks[0].path
        self.bios_combo.remove_all()
        self.bios_combo.append("", _("Don't install a Legacy BIOS boot loader"))
        for disk in layout.disks:
            self.bios_combo.append(disk.path, disk.describe())
        self.bios_combo.set_active_id(current if current in [""] + [d.path for d in layout.disks] else "")
        self.update_part_buttons()

    def iter_rows(self, store):
        for row in store:
            yield row
            for child in row.iterchildren():
                yield child

    def selected_key(self):
        model, it = self.part_view.get_selection().get_selected()
        return model[it][0] if it else None

    def selected(self):
        key = self.selected_key()
        return self.rows.get(key) if key else None

    def update_part_buttons(self):
        obj = self.selected()
        self.btn_add.set_sensitive(isinstance(obj, Free))
        self.btn_del.set_sensitive(isinstance(obj, Part))
        self.btn_change.set_sensitive(isinstance(obj, Part) and not obj.extended)
        self.btn_table.set_sensitive(isinstance(obj, partitioning.Disk))

    def on_part_activate(self):
        obj = self.selected()
        if isinstance(obj, Free):
            self.on_add()
        elif isinstance(obj, Part) and not obj.extended:
            self.on_change()

    def dialog(self, title):
        d = Gtk.Dialog(title=title, transient_for=self, modal=True)
        d.add_button(_("Cancel"), Gtk.ResponseType.CANCEL)
        ok = d.add_button(_("OK"), Gtk.ResponseType.OK)
        ok.get_style_context().add_class("suggested-action")
        d.set_default_response(Gtk.ResponseType.OK)
        grid = Gtk.Grid(column_spacing=12, row_spacing=10)
        grid.set_border_width(18)
        d.get_content_area().add(grid)
        return d, grid

    def use_widgets(self, grid, row, use, mount, allow_none):
        use_combo = shrinkable(Gtk.ComboBoxText())
        if allow_none:
            use_combo.append("none", partitioning.use_label(None))
        for u in partitioning.available_uses():
            use_combo.append(u, partitioning.use_label(u))
        use_combo.set_active_id(use or "none")
        if use_combo.get_active_id() is None:
            use_combo.set_active(0)
        mount_combo = Gtk.ComboBoxText.new_with_entry()
        for m in partitioning.MOUNT_POINTS:
            mount_combo.append_text(m)
        mount_combo.get_child().set_text(mount)

        def sync(*_a):
            u = use_combo.get_active_id()
            mount_combo.set_sensitive(u in partitioning.MOUNTABLE)
            if u == "efi":
                mount_combo.get_child().set_text("/boot/efi")
            elif u not in partitioning.MOUNTABLE:
                mount_combo.get_child().set_text("")
        use_combo.connect("changed", sync)
        sync()
        grid.attach(label(_("Use as:"), wrap=False), 0, row, 1, 1)
        grid.attach(use_combo, 1, row, 1, 1)
        grid.attach(label(_("Mount point:"), wrap=False), 0, row + 1, 1, 1)
        grid.attach(mount_combo, 1, row + 1, 1, 1)
        return use_combo, mount_combo

    def on_add(self):
        free = self.selected()
        if not isinstance(free, Free):
            return
        d, grid = self.dialog(_("Create partition"))
        max_mb = max(1, free.size // 1000 ** 2)
        size = Gtk.SpinButton.new_with_range(1, max_mb, 1)
        size.set_value(max_mb)
        grid.attach(label(_("Size (MB):"), wrap=False), 0, 0, 1, 1)
        grid.attach(size, 1, 0, 1, 1)
        begin = Gtk.RadioButton.new_with_label(None, _("Beginning of this space"))
        end = Gtk.RadioButton.new_with_label_from_widget(begin, _("End of this space"))
        loc = Gtk.Box(spacing=12)
        loc.pack_start(begin, False, False, 0)
        loc.pack_start(end, False, False, 0)
        grid.attach(label(_("Location:"), wrap=False), 0, 1, 1, 1)
        grid.attach(loc, 1, 1, 1, 1)
        has_root = any(p.mount == "/" for p in self.manual_layout.used())
        use_combo, mount_combo = self.use_widgets(grid, 2, "ext4", "" if has_root else "/", False)
        d.show_all()
        while d.run() == Gtk.ResponseType.OK:
            use = use_combo.get_active_id()
            nbytes = size.get_value_as_int() * 1000 ** 2
            if size.get_value_as_int() >= max_mb:
                nbytes = free.size
            try:
                self.manual_layout.add(free, nbytes, end.get_active(), use, mount_combo.get_child().get_text())
            except ValueError as e:
                self.message(str(e))
                continue
            break
        d.destroy()
        self.populate()

    def on_change(self):
        part = self.selected()
        if not isinstance(part, Part):
            return
        d, grid = self.dialog(_("Edit partition"))
        grid.attach(label(_("Partition:"), wrap=False), 0, 0, 1, 1)
        grid.attach(label("%s  (%s%s)" % (part.name(), human_size(part.size),
                                          ", " + part.fs if part.fs else ""), wrap=False), 1, 0, 1, 1)
        use_combo, mount_combo = self.use_widgets(grid, 1, part.use or (None if part.is_new else None),
                                                  part.mount, not part.is_new)
        if not part.use and not part.is_new:
            use_combo.set_active_id("none")
        fmt = Gtk.CheckButton(label=_("Format the partition"))
        fmt.set_active(part.will_format())
        grid.attach(fmt, 1, 3, 1, 1)

        def sync_format(*_a):
            u = use_combo.get_active_id()
            probe = Part(part.disk, part.start, part.end, part.number, part.fs, ptype=part.ptype)
            probe.is_new = part.is_new
            probe.use = None if u == "none" else u
            forced = probe.needs_format()
            fmt.set_sensitive(not forced and probe.use not in (None, "biosgrub"))
            if forced:
                fmt.set_active(True)
            elif probe.use in (None, "biosgrub"):
                fmt.set_active(False)
        use_combo.connect("changed", sync_format)
        sync_format()
        d.show_all()
        if d.run() == Gtk.ResponseType.OK:
            u = use_combo.get_active_id()
            self.manual_layout.set_use(part, None if u == "none" else u,
                                       mount_combo.get_child().get_text(), fmt.get_active())
        d.destroy()
        self.populate()

    def on_delete(self):
        part = self.selected()
        if isinstance(part, Part):
            self.manual_layout.delete(part)
            self.populate()

    def on_new_table(self):
        disk = self.selected()
        if not isinstance(disk, partitioning.Disk):
            return
        d, grid = self.dialog(_("New partition table"))
        grid.attach(label(_("Create a new empty partition table on %s?\n"
                            "All partitions on this disk will be deleted.") % disk.path), 0, 0, 2, 1)
        kind = shrinkable(Gtk.ComboBoxText())
        kind.append("gpt", _("GPT (recommended)"))
        kind.append("msdos", _("MBR / msdos (for very old computers)"))
        kind.set_active_id("gpt")
        grid.attach(label(_("Type:"), wrap=False), 0, 1, 1, 1)
        grid.attach(kind, 1, 1, 1, 1)
        d.show_all()
        if d.run() == Gtk.ResponseType.OK:
            self.manual_layout.new_table(disk, kind.get_active_id())
        d.destroy()
        self.populate()

    def message(self, text):
        m = Gtk.MessageDialog(transient_for=self, modal=True, message_type=Gtk.MessageType.WARNING,
                              buttons=Gtk.ButtonsType.CLOSE, text=text)
        m.run()
        m.destroy()

    def next_partition(self):
        bios = self.bios_combo.get_active_id() or None
        err = self.manual_layout.check(self.fw, bios, self.required)
        if err:
            return self.error(err)
        self.plan.update(mode="manual", layout=self.manual_layout, bios_disk=bios)
        self.show_page("user")

    def build_user(self):
        box = page_box()
        grid = Gtk.Grid(column_spacing=12, row_spacing=10)
        self.fullname = Gtk.Entry()
        self.fullname.set_hexpand(True)
        self.username = Gtk.Entry()
        self.hostname = Gtk.Entry()
        self.password = Gtk.Entry(visibility=False)
        self.password2 = Gtk.Entry(visibility=False)
        self.zones = timezones()
        self.tz_combo = SearchCombo([(z, z.replace("_", " ")) for z in self.zones])
        p = self.plan
        self.fullname.set_text(p.get("fullname", ""))
        self.username.set_text(p.get("username", ""))
        self.hostname.set_text(p.get("hostname", self.cfg["hostname"]))
        self.password.set_text(p.get("password", ""))
        self.password2.set_text(p.get("password", ""))
        if not self.tz_combo.set_active_id(p.get("timezone") or self.cfg["timezone"] or current_timezone()):
            self.tz_combo.set_active_id("UTC")
        self.username_edited = bool(p.get("username"))
        self.hostname_edited = bool(p.get("hostname") or self.cfg["hostname"])
        self.fullname.connect("changed", self.on_fullname)
        self.username.connect("changed", self.on_username)
        self.username.connect("key-press-event", lambda *_a: setattr(self, "username_edited", True))
        self.hostname.connect("key-press-event", lambda *_a: setattr(self, "hostname_edited", True))
        rows = [(_("Your name"), self.fullname), (_("Username"), self.username),
                (_("Computer name"), self.hostname), (_("Password"), self.password),
                (_("Confirm password"), self.password2), (_("Time zone"), self.tz_combo)]
        for i, (text, widget) in enumerate(rows):
            grid.attach(label(text, wrap=False), 0, i, 1, 1)
            grid.attach(widget, 1, i, 1, 1)
        box.pack_start(grid, False, False, 0)
        box.pack_start(label(_("This user will be an administrator (sudo)."), "dim-label"), False, False, 0)
        self.add_page("user", _("Who are you?"), box)

    def on_fullname(self, entry):
        if not self.username_edited:
            text = entry.get_text().strip()
            first = text.split(" ")[0].lower() if text else ""
            self.username.set_text(re.sub(r"[^a-z0-9_-]", "", first))

    def on_username(self, entry):
        if not self.hostname_edited:
            user = entry.get_text()
            self.hostname.set_text(("%s-pc" % user) if user else "")

    def next_user(self):
        user = self.username.get_text()
        host = self.hostname.get_text()
        pw = self.password.get_text()
        tz = self.tz_combo.get_active_id() or ""
        if not re.fullmatch(r"[a-z_][a-z0-9_-]{0,31}", user):
            return self.error(_("The username must start with a lowercase letter and use only a-z, 0-9, - and _."))
        if user in ("root", "daemon", "bin", "sys", "nobody", "admin", "sudo"):
            return self.error(_("That username is reserved."))
        if not re.fullmatch(r"[A-Za-z0-9]([A-Za-z0-9-]{0,61}[A-Za-z0-9])?", host):
            return self.error(_("The computer name may only use letters, digits and -."))
        if not pw:
            return self.error(_("Choose a password."))
        if pw != self.password2.get_text():
            return self.error(_("The passwords do not match."))
        if ":" in self.fullname.get_text():
            return self.error(_("Your name cannot contain \":\"."))
        if "\n" in pw:
            return self.error(_("The password cannot contain line breaks."))
        if tz not in self.zones:
            return self.error(_("Choose a valid time zone."))
        self.plan.update(fullname=self.fullname.get_text().strip(), username=user, hostname=host,
                         password=pw, timezone=tz)
        self.show_page("summary")

    def build_summary(self):
        box = page_box()
        self.summary = markup("")
        self.summary.set_selectable(True)
        self.summary.set_valign(Gtk.Align.START)
        sw = Gtk.ScrolledWindow()
        sw.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        sw.add(self.summary)
        box.pack_start(sw, True, True, 0)
        self.add_page("summary", _("Ready to install"), box)

    def enter_summary(self):
        p = self.plan
        esc = GLib.markup_escape_text
        lines = ["<b>%s</b>" % esc(_("These changes will be written to the disks:"))]
        lines += ["  • " + esc(line) for line in p["layout"].describe()]
        if p.get("bios_disk"):
            lines.append("  • " + esc(_("The Legacy BIOS boot loader will be written to %s.") % p["bios_disk"]))
        if any(q.use == "efi" for q in p["layout"].used()):
            lines.append("  • " + esc(_("The UEFI boot loader (64-bit and 32-bit) will be installed.")))
        kb = self.layouts.get(self.keyboard[0], (self.keyboard[0], []))
        kb_name = kb[0]
        if self.keyboard[1]:
            kb_name = dict(kb[1]).get(self.keyboard[1], kb_name)
        lines += ["", "<b>%s</b>" % esc(_("Settings:")),
                  "  • " + esc(_("User: %(name)s (%(user)s), administrator")
                               % {"name": p["fullname"] or p["username"], "user": p["username"]}),
                  "  • " + esc(_("Computer name: %s") % p["hostname"]),
                  "  • " + esc(_("Language: %s") % self.locale),
                  "  • " + esc(_("Keyboard: %s") % kb_name),
                  "  • " + esc(_("Time zone: %s") % p["timezone"]),
                  "", "<b>%s</b>" % esc(_("These changes cannot be undone."))]
        self.summary.set_markup("\n".join(lines))

    def next_summary(self):
        self.plan.update(locale=self.locale, language_packs=self.language_packs and not self.locale.startswith("en"),
                         keyboard_layout=self.keyboard[0], keyboard_variant=self.keyboard[1])
        self.show_page("progress")
        self.busy = True
        threading.Thread(target=self.worker, daemon=True).start()

    def build_progress(self):
        box = page_box()
        box.set_valign(Gtk.Align.CENTER)
        logo = self.logo(96)
        if logo:
            box.pack_start(logo, False, False, 0)
        wait = label(self.cfg.text("wait_text"), "big-wait", xalign=0.5)
        wait.set_justify(Gtk.Justification.CENTER)
        box.pack_start(wait, False, False, 12)
        self.bar = Gtk.ProgressBar()
        self.bar.set_margin_start(40)
        self.bar.set_margin_end(40)
        box.pack_start(self.bar, False, False, 0)
        self.status = label("", "dim-label", xalign=0.5)
        box.pack_start(self.status, False, False, 0)
        self.add_page("progress", _("Installing %s") % self.cfg["name"], box)

    def worker(self):
        def progress(frac):
            GLib.idle_add(self.bar.set_fraction, max(0.0, min(1.0, frac)))

        def status(text):
            GLib.idle_add(self.status.set_text, text)
        try:
            backend.Installer(self.plan, self.cfg, progress, status).install()
            GLib.idle_add(self.finished, None)
        except InstallError as e:
            GLib.idle_add(self.finished, str(e))
        except Exception:
            log(traceback.format_exc())
            GLib.idle_add(self.finished, traceback.format_exc(limit=3))

    def finished(self, err):
        self.busy = False
        if err is None:
            self.history = []
            self.show_page("done")
            return
        dialog = Gtk.MessageDialog(transient_for=self, modal=True, message_type=Gtk.MessageType.ERROR,
                                   buttons=Gtk.ButtonsType.CLOSE, text=_("The installation failed"))
        dialog.format_secondary_text("%s\n\n%s" % (err, _("The full log is in %s.") % backend.LOG_PATH))
        dialog.run()
        dialog.destroy()
        Gtk.main_quit()

    def build_done(self):
        box = page_box()
        box.set_valign(Gtk.Align.CENTER)
        logo = self.logo(128)
        if logo:
            box.pack_start(logo, False, False, 0)
        text = label(self.cfg.text("done_text"), xalign=0.5)
        text.set_justify(Gtk.Justification.CENTER)
        box.pack_start(text, False, False, 0)
        actions = Gtk.Box(spacing=8)
        actions.set_halign(Gtk.Align.CENTER)
        off_btn = Gtk.Button(label=_("Shut down"))
        off_btn.connect("clicked", lambda _b: self.power("poweroff"))
        quit_btn = Gtk.Button(label=_("Keep using the live session"))
        quit_btn.connect("clicked", lambda _b: Gtk.main_quit())
        actions.pack_start(off_btn, False, False, 0)
        actions.pack_start(quit_btn, False, False, 0)
        box.pack_start(actions, False, False, 12)
        self.add_page("done", self.cfg.text("done_title"), box)

    def next_done(self):
        self.power("reboot")

    def power(self, action):
        subprocess.Popen(["systemctl", action])
        Gtk.main_quit()


def main():
    if os.geteuid() != 0:
        print("system-installer must run as root", file=sys.stderr)
        sys.exit(1)
    win = InstallerWindow(load_config())
    win.connect("destroy", Gtk.main_quit)
    win.show()
    Gtk.main()


if __name__ == "__main__":
    main()
