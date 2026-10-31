import grp
import os
import pwd
import re
import unicodedata

from gi.repository import Gtk

from .. import util
from ..i18n import _
from ..widgets import Page, Section



def _admin_group():
    for name in ("sudo", "wheel"):
        try:
            grp.getgrnam(name)
            return name
        except KeyError:
            pass
    return "sudo"


ADMIN_GROUP = _admin_group()


def list_users():
    users = []
    for pw in pwd.getpwall():
        if 1000 <= pw.pw_uid < 60000 and not pw.pw_shell.endswith(("nologin", "false")):
            users.append(pw)
    return sorted(users, key=lambda p: p.pw_uid)


def is_admin(pw):
    try:
        g = grp.getgrnam(ADMIN_GROUP)
    except KeyError:
        return False
    return pw.pw_name in g.gr_mem or pw.pw_gid == g.gr_gid


def real_name(pw):
    return pw.pw_gecos.split(",")[0].strip() or pw.pw_name


def avatar_image(size):
    img = Gtk.Image.new_from_icon_name(util.icon_name("avatar-default", "user-info", "system-users"),
                                       Gtk.IconSize.DIALOG)
    img.set_pixel_size(size)
    return img


def suggest_username(full):
    s = unicodedata.normalize("NFKD", full).encode("ascii", "ignore").decode().lower()
    parts = re.findall(r"[a-z0-9]+", s)
    name = parts[0] if parts else ""
    if name and name[0].isdigit():
        name = "u" + name
    return name[:32]


def password_entries(grid, row):
    """Add 'password' and 'confirm' entries to a grid; return them."""
    p1 = Gtk.Entry(visibility=False, input_purpose=Gtk.InputPurpose.PASSWORD, hexpand=True)
    p2 = Gtk.Entry(visibility=False, input_purpose=Gtk.InputPurpose.PASSWORD, activates_default=True)
    grid.attach(Gtk.Label(label=_("Password"), xalign=1), 0, row, 1, 1)
    grid.attach(p1, 1, row, 1, 1)
    grid.attach(Gtk.Label(label=_("Confirm password"), xalign=1), 0, row + 1, 1, 1)
    grid.attach(p2, 1, row + 1, 1, 1)
    return p1, p2


def dialog_grid(dlg):
    area = dlg.get_content_area()
    area.set_border_width(12)
    grid = Gtk.Grid(row_spacing=8, column_spacing=12)
    area.add(grid)
    return grid


class UsersPage(Page):
    page_id = "users"
    title = _("Users")
    icons = ("system-users", "preferences-desktop-user", "avatar-default")

    def __init__(self, window):
        super().__init__(window)
        self.me = pwd.getpwuid(os.getuid()).pw_name
        self.selected = self.me

        self.list_section = self.add_section(Section(_("Accounts")))
        self.list_section.list.set_selection_mode(Gtk.SelectionMode.SINGLE)
        self.list_section.list.connect("row-selected", self._on_select)
        add = Gtk.Button(label=_("Add a user…"), halign=Gtk.Align.START)
        add.connect("clicked", self._on_add)
        self.content.pack_start(add, False, False, 0)

        self.detail_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=24)
        self.content.pack_start(self.detail_box, False, False, 0)
        self.content.pack_start(Gtk.Label(
            label=_("Changes to accounts require administrator authentication."),
            xalign=0, wrap=True), False, False, 0)
        self.reload()

    # --- list -----------------------------------------------------------

    def reload(self):
        sec = self.list_section
        sec.clear()
        self.users = {pw.pw_name: pw for pw in list_users()}
        if self.selected not in self.users:
            self.selected = self.me
        for pw in self.users.values():
            box = Gtk.Box(spacing=12)
            box.pack_start(avatar_image(40), False, False, 0)
            labels = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, valign=Gtk.Align.CENTER)
            name = real_name(pw)
            if pw.pw_name == self.me:
                name = _("%s (you)") % name
            labels.pack_start(Gtk.Label(label=name, xalign=0), False, False, 0)
            sub = Gtk.Label(label="%s · %s" % (pw.pw_name, _("Administrator") if is_admin(pw) else _("Standard")),
                            xalign=0)
            sub.get_style_context().add_class("dim-label")
            labels.pack_start(sub, False, False, 0)
            box.pack_start(labels, True, True, 0)
            row = sec.add_widget(box)
            row.set_activatable(True)
            row.user = pw.pw_name
        for row in sec.list.get_children():
            if row.user == self.selected:
                sec.list.select_row(row)
        sec.show_all()
        self._show_details()

    def _on_select(self, _lb, row):
        if row is not None and row.user != self.selected:
            self.selected = row.user
            self._show_details()

    # --- details --------------------------------------------------------

    def _show_details(self):
        for c in self.detail_box.get_children():
            c.destroy()
        pw = self.users.get(self.selected)
        if pw is None:
            return
        mine = pw.pw_name == self.me
        sec = Section(_("Account settings — %s") % pw.pw_name)
        self.detail_box.pack_start(sec, False, False, 0)

        name_entry = Gtk.Entry(text=real_name(pw) if pw.pw_gecos else "", width_chars=24)
        name_btn = Gtk.Button(label=_("Change"), sensitive=False)
        name_entry.connect("changed", lambda e: name_btn.set_sensitive(e.get_text().strip() != real_name(pw)))
        name_btn.connect("clicked", lambda *_a: self._helper(
            ["set-realname", pw.pw_name, name_entry.get_text().strip()]))
        name_entry.connect("activate", lambda *_a: name_btn.clicked() if name_btn.get_sensitive() else None)
        nb = Gtk.Box(spacing=6)
        nb.pack_start(name_entry, False, False, 0)
        nb.pack_start(name_btn, False, False, 0)
        sec.add_row(_("Full name"), nb)

        acct = Gtk.ComboBoxText()
        acct.append("standard", _("Standard"))
        acct.append("admin", _("Administrator"))
        acct.set_active_id("admin" if is_admin(pw) else "standard")
        acct.set_sensitive(not mine)
        acct.connect("changed", lambda c: self._helper(
            ["set-admin", pw.pw_name, "yes" if c.get_active_id() == "admin" else "no"]))
        sec.add_row(_("Account type"), acct,
                    _("Administrators can install software and change system settings")
                    if not mine else _("You cannot change the type of your own account"))

        pwbtn = Gtk.Button(label=_("Change…"))
        pwbtn.connect("clicked", self._on_password, pw)
        sec.add_row(_("Password"), pwbtn)

        if not mine:
            rm = Gtk.Button(label=_("Remove user…"))
            rm.get_style_context().add_class("destructive-action")
            rm.connect("clicked", self._on_remove, pw)
            sec.add_row(_("Remove this account"), rm)
        self.detail_box.show_all()

    def _helper(self, args, stdin=None):
        util.run_helper(self.window, args, lambda ok: self.reload(), stdin)

    # --- actions --------------------------------------------------------

    def _on_password(self, _btn, pw):
        dlg = Gtk.Dialog(title=_("Change password for %s") % pw.pw_name, transient_for=self.window, modal=True)
        dlg.add_buttons(_("_Cancel"), Gtk.ResponseType.CANCEL, _("_Change"), Gtk.ResponseType.OK)
        dlg.set_default_response(Gtk.ResponseType.OK)
        grid = dialog_grid(dlg)
        p1, p2 = password_entries(grid, 0)
        hint = Gtk.Label(xalign=0)
        hint.get_style_context().add_class("dim-label")
        grid.attach(hint, 1, 2, 1, 1)
        ok_btn = dlg.get_widget_for_response(Gtk.ResponseType.OK)
        ok_btn.set_sensitive(False)

        def check(*_a):
            a, b = p1.get_text(), p2.get_text()
            ok = bool(a) and a == b
            hint.set_text("" if ok or not b else _("The passwords do not match"))
            ok_btn.set_sensitive(ok)

        p1.connect("changed", check)
        p2.connect("changed", check)
        dlg.show_all()
        if dlg.run() == Gtk.ResponseType.OK:
            self._helper(["set-password", pw.pw_name], p1.get_text() + "\n")
        dlg.destroy()

    def _on_add(self, _btn):
        dlg = Gtk.Dialog(title=_("Add a user"), transient_for=self.window, modal=True)
        dlg.add_buttons(_("_Cancel"), Gtk.ResponseType.CANCEL, _("_Add"), Gtk.ResponseType.OK)
        dlg.set_default_response(Gtk.ResponseType.OK)
        grid = dialog_grid(dlg)
        full = Gtk.Entry(hexpand=True)
        user = Gtk.Entry()
        kind = Gtk.ComboBoxText()
        kind.append("standard", _("Standard"))
        kind.append("admin", _("Administrator"))
        kind.set_active_id("standard")
        for i, (label, w) in enumerate(((_("Full name"), full), (_("User name"), user),
                                        (_("Account type"), kind))):
            grid.attach(Gtk.Label(label=label, xalign=1), 0, i, 1, 1)
            grid.attach(w, 1, i, 1, 1)
        p1, p2 = password_entries(grid, 3)
        note = Gtk.Label(label=_("Leave the password empty to set it later."), xalign=0)
        note.get_style_context().add_class("dim-label")
        grid.attach(note, 1, 5, 1, 1)
        ok_btn = dlg.get_widget_for_response(Gtk.ResponseType.OK)
        edited = [False]

        def on_full(_e):
            if not edited[0]:
                user.handler_block_by_func(on_user)
                user.set_text(suggest_username(full.get_text()))
                user.handler_unblock_by_func(on_user)
            validate()

        def on_user(_e):
            edited[0] = True
            validate()

        def validate(*_a):
            name = user.get_text()
            valid = bool(re.match(r"^[a-z_][a-z0-9_-]{0,31}$", name)) and name not in self.users
            try:
                pwd.getpwnam(name)
                valid = False
            except KeyError:
                pass
            ok_btn.set_sensitive(valid and p1.get_text() == p2.get_text() and
                                 not re.search(r"[:,=\n]", full.get_text()))

        full.connect("changed", on_full)
        user.connect("changed", on_user)
        p1.connect("changed", validate)
        p2.connect("changed", validate)
        validate()
        dlg.show_all()
        if dlg.run() == Gtk.ResponseType.OK:
            name = user.get_text()
            self.selected = name
            self._helper(["add-user", name, full.get_text().strip(), kind.get_active_id()],
                         p1.get_text() + "\n")
        dlg.destroy()

    def _on_remove(self, _btn, pw):
        dlg = Gtk.MessageDialog(transient_for=self.window, modal=True, message_type=Gtk.MessageType.WARNING,
                                buttons=Gtk.ButtonsType.NONE,
                                text=_("Remove the account of %s?") % real_name(pw))
        dlg.format_secondary_text(_("You can keep the user's home folder (%s) or delete it with all "
                                    "of its files.") % pw.pw_dir)
        dlg.add_button(_("_Cancel"), Gtk.ResponseType.CANCEL)
        dlg.add_button(_("_Keep files"), 1)
        b = dlg.add_button(_("_Delete files"), 2)
        b.get_style_context().add_class("destructive-action")
        resp = dlg.run()
        dlg.destroy()
        if resp in (1, 2):
            self._helper(["del-user", pw.pw_name, "remove-files" if resp == 2 else "keep-files"])
