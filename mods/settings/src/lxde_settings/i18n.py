import gettext
import locale

DOMAIN = "lxde-settings"


def setup(localedir):
    try:
        locale.setlocale(locale.LC_ALL, "")
    except locale.Error:
        pass
    gettext.bindtextdomain(DOMAIN, localedir)
    gettext.textdomain(DOMAIN)


def _(msg):
    return gettext.dgettext(DOMAIN, msg)


def N_(msg):
    """Mark a string for translation without translating it yet."""
    return msg


def ngettext(singular, plural, n):
    return gettext.dngettext(DOMAIN, singular, plural, n)
