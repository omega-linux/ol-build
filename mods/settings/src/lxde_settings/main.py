import sys
import traceback

import gi

gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
gi.require_version("GdkPixbuf", "2.0")

from gi.repository import Gio, GLib, Gtk  # noqa: E402

from . import config, i18n  # noqa: E402

i18n.setup(config.LOCALEDIR)

from .i18n import _  # noqa: E402
from .pages import PAGES  # noqa: E402
from . import util  # noqa: E402

APP_ID = "org.lxde.Settings"


class SettingsWindow(Gtk.ApplicationWindow):
    def __init__(self, app):
        super().__init__(application=app, title=_("Settings"))
        self.set_default_size(960, 680)
        self.set_icon_name(util.icon_name("preferences-system", "preferences-desktop"))
        self._pages = {}

        hbox = Gtk.Box()
        self.add(hbox)

        side_scroll = Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.NEVER)
        side_scroll.set_size_request(220, -1)
        self.sidebar = Gtk.ListBox()
        self.sidebar.get_style_context().add_class("sidebar")
        self.sidebar.connect("row-selected", self._on_row_selected)
        side_scroll.add(self.sidebar)
        hbox.pack_start(side_scroll, False, False, 0)
        hbox.pack_start(Gtk.Separator(orientation=Gtk.Orientation.VERTICAL), False, False, 0)

        self.stack = Gtk.Stack(transition_type=Gtk.StackTransitionType.CROSSFADE)
        hbox.pack_start(self.stack, True, True, 0)

        for cls in PAGES:
            row = Gtk.ListBoxRow()
            row.page_cls = cls
            box = Gtk.Box(spacing=12, margin_start=12, margin_end=12, margin_top=8, margin_bottom=8)
            box.pack_start(Gtk.Image.new_from_icon_name(util.icon_name(*cls.icons), Gtk.IconSize.LARGE_TOOLBAR),
                           False, False, 0)
            box.pack_start(Gtk.Label(label=cls.title, xalign=0), True, True, 0)
            row.add(box)
            self.sidebar.add(row)
        self.show_all()

    def show_page(self, page_id):
        for row in self.sidebar.get_children():
            if row.page_cls.page_id == page_id:
                self.sidebar.select_row(row)
                return True
        return False

    def _on_row_selected(self, _lb, row):
        if row is None:
            return
        cls = row.page_cls
        if cls.page_id not in self._pages:
            try:
                page = cls(self)
            except Exception:  # keep the rest of the app usable if one page breaks
                traceback.print_exc()
                page = Gtk.Label(label=_("This page could not be loaded."))
            page.show_all()
            self.stack.add_named(page, cls.page_id)
            self._pages[cls.page_id] = page
        self.stack.set_visible_child_name(cls.page_id)


class SettingsApp(Gtk.Application):
    def __init__(self):
        super().__init__(application_id=APP_ID, flags=Gio.ApplicationFlags.HANDLES_COMMAND_LINE)
        self.window = None
        self.add_main_option("list-pages", 0, GLib.OptionFlags.NONE, GLib.OptionArg.NONE,
                             _("List the available pages and exit"), None)
        self.add_main_option("apply-input", 0, GLib.OptionFlags.NONE, GLib.OptionArg.NONE,
                             _("Apply the saved mouse settings and exit (used at login)"), None)

    def do_handle_local_options(self, options):
        if options.contains("list-pages"):
            for cls in PAGES:
                print("%-12s %s" % (cls.page_id, cls.title))
            return 0
        if options.contains("apply-input"):
            from .pages.input import apply_saved
            apply_saved()
            return 0
        return -1

    def do_command_line(self, cmdline):
        args = cmdline.get_arguments()[1:]
        if self.window is None:
            self.window = SettingsWindow(self)
        page = args[0] if args else None
        if not (page and self.window.show_page(page)) and self.window.sidebar.get_selected_row() is None:
            self.window.show_page(PAGES[0].page_id)
        self.window.present()
        return 0


def run():
    GLib.set_prgname("lxde-settings")
    GLib.set_application_name(_("Settings"))
    return SettingsApp().run(sys.argv)
