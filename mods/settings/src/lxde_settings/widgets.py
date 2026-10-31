"""Building blocks for pages.  Only stock GTK widgets and theme style
classes are used so everything follows the user's GTK theme."""

from gi.repository import GLib, Gtk


class Page(Gtk.ScrolledWindow):
    """Base class: a scrollable column of sections."""

    page_id = ""
    title = ""
    icons = ("preferences-system",)

    def __init__(self, window):
        super().__init__(hscrollbar_policy=Gtk.PolicyType.NEVER)
        self.window = window
        self.content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=24,
                               margin_start=32, margin_end=32, margin_top=24, margin_bottom=24)
        heading = Gtk.Label(xalign=0)
        heading.set_markup("<span size='x-large' weight='bold'>%s</span>" % GLib.markup_escape_text(self.title))
        self.content.pack_start(heading, False, False, 0)
        self.add(self.content)

    def add_section(self, section):
        self.content.pack_start(section, False, False, 0)
        return section


def _separator_header(row, before):
    if before is not None and row.get_header() is None:
        row.set_header(Gtk.Separator())


class Section(Gtk.Box):
    """A titled, framed list of setting rows (GNOME Settings style)."""

    def __init__(self, title=None, description=None):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        if title:
            lbl = Gtk.Label(xalign=0)
            lbl.set_markup("<b>%s</b>" % GLib.markup_escape_text(title))
            self.pack_start(lbl, False, False, 0)
        if description:
            d = Gtk.Label(label=description, xalign=0, wrap=True)
            d.get_style_context().add_class("dim-label")
            self.pack_start(d, False, False, 0)
        frame = Gtk.Frame()
        self.list = Gtk.ListBox(selection_mode=Gtk.SelectionMode.NONE)
        self.list.set_header_func(_separator_header)
        frame.add(self.list)
        self.pack_start(frame, False, False, 0)

    def add_row(self, title, widget=None, subtitle=None):
        row = Gtk.ListBoxRow(activatable=False)
        box = Gtk.Box(spacing=12, margin_start=12, margin_end=12, margin_top=8, margin_bottom=8)
        labels = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2, valign=Gtk.Align.CENTER)
        t = Gtk.Label(label=title, xalign=0, wrap=True)
        labels.pack_start(t, False, False, 0)
        row.title_label = t
        row.subtitle_label = None
        if subtitle is not None:
            s = Gtk.Label(label=subtitle, xalign=0, wrap=True, selectable=False)
            s.get_style_context().add_class("dim-label")
            labels.pack_start(s, False, False, 0)
            row.subtitle_label = s
        box.pack_start(labels, True, True, 0)
        if widget is not None:
            widget.set_valign(Gtk.Align.CENTER)
            box.pack_end(widget, False, False, 0)
        row.add(box)
        self.list.add(row)
        return row

    def add_widget(self, widget, margin=12):
        row = Gtk.ListBoxRow(activatable=False)
        widget.set_margin_start(margin)
        widget.set_margin_end(margin)
        widget.set_margin_top(8)
        widget.set_margin_bottom(8)
        row.add(widget)
        self.list.add(row)
        return row

    def clear(self):
        for c in self.list.get_children():
            c.destroy()


def info_label(text=""):
    lbl = Gtk.Label(label=text, xalign=1, selectable=True, wrap=True, max_width_chars=48)
    lbl.set_justify(Gtk.Justification.RIGHT)
    return lbl


def combo(items, active=None):
    """ComboBoxText from (id, label) pairs."""
    c = Gtk.ComboBoxText()
    for i, label in items:
        c.append(i, label)
    if active is not None:
        c.set_active_id(active)
    return c


def button_box(*buttons):
    box = Gtk.Box(spacing=6, halign=Gtk.Align.END)
    for b in buttons:
        box.pack_start(b, False, False, 0)
    return box


def message_bar(text):
    bar = Gtk.InfoBar(message_type=Gtk.MessageType.INFO)
    bar.get_content_area().add(Gtk.Label(label=text, wrap=True, xalign=0))
    return bar
