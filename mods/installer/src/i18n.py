import ast
import gettext
import os
import xml.etree.ElementTree as ET

PO_DIR = os.path.join(os.path.dirname(os.path.realpath(__file__)), "po")

LANGUAGES = [
    ("en", "English", "en_US.UTF-8", "us"),
    ("es", "Español", "es_ES.UTF-8", "es"),
    ("pt_BR", "Português (Brasil)", "pt_BR.UTF-8", "br"),
    ("pt", "Português", "pt_PT.UTF-8", "pt"),
    ("fr", "Français", "fr_FR.UTF-8", "fr"),
    ("de", "Deutsch", "de_DE.UTF-8", "de"),
    ("it", "Italiano", "it_IT.UTF-8", "it"),
    ("nl", "Nederlands", "nl_NL.UTF-8", "us"),
    ("ca", "Català", "ca_ES.UTF-8", "es"),
    ("pl", "Polski", "pl_PL.UTF-8", "pl"),
    ("cs", "Čeština", "cs_CZ.UTF-8", "cz"),
    ("ro", "Română", "ro_RO.UTF-8", "ro"),
    ("hu", "Magyar", "hu_HU.UTF-8", "hu"),
    ("sv", "Svenska", "sv_SE.UTF-8", "se"),
    ("tr", "Türkçe", "tr_TR.UTF-8", "tr"),
    ("id", "Bahasa Indonesia", "id_ID.UTF-8", "us"),
    ("el", "Ελληνικά", "el_GR.UTF-8", "us"),
    ("ru", "Русский", "ru_RU.UTF-8", "us"),
    ("uk", "Українська", "uk_UA.UTF-8", "us"),
    ("zh_CN", "简体中文", "zh_CN.UTF-8", "cn"),
    ("ja", "日本語", "ja_JP.UTF-8", "jp"),
    ("ko", "한국어", "ko_KR.UTF-8", "kr"),
]

_catalog = {}
_xkb = gettext.NullTranslations()
current = "en"


def _(text):
    return _catalog.get(text) or text


def parse_po(path):
    catalog = {}
    msgid = msgstr = None
    field = None

    def flush():
        if msgid and msgstr:
            catalog[msgid] = msgstr

    with open(path, encoding="utf-8") as f:
        for raw in f:
            line = raw.strip()
            if line.startswith("msgid "):
                flush()
                msgid, msgstr, field = ast.literal_eval(line[6:]), None, "id"
            elif line.startswith("msgstr "):
                msgstr, field = ast.literal_eval(line[7:]), "str"
            elif line.startswith('"') and field:
                if field == "id":
                    msgid += ast.literal_eval(line)
                else:
                    msgstr += ast.literal_eval(line)
            elif not line:
                field = None
    flush()
    return catalog


def available():
    return [lang for lang in LANGUAGES
            if lang[0] == "en" or os.path.isfile(os.path.join(PO_DIR, lang[0] + ".po"))]


def set_language(code):
    global _catalog, _xkb, current
    current = code
    path = os.path.join(PO_DIR, code + ".po")
    _catalog = parse_po(path) if os.path.isfile(path) else {}
    _xkb = gettext.translation("xkeyboard-config", languages=[code, code.split("_")[0]], fallback=True)


def language(code):
    return next((lang for lang in LANGUAGES if lang[0] == code), LANGUAGES[0])


_locales = None


def system_locales():
    global _locales
    if _locales is not None:
        return _locales
    result = []
    try:
        with open("/usr/share/i18n/SUPPORTED") as f:
            entries = [line.split() for line in f if line.strip() and not line.startswith("#")]
    except OSError:
        entries = []
    for entry in entries:
        if len(entry) < 2 or entry[1] != "UTF-8":
            continue
        name = entry[0]
        base = name.replace(".UTF-8", "").replace(".utf8", "")
        lang = territory = ""
        try:
            with open(os.path.join("/usr/share/i18n/locales", base), encoding="utf-8", errors="replace") as f:
                for line in f:
                    parts = line.split(None, 1)
                    if len(parts) == 2 and parts[0] in ("language", "territory"):
                        value = parts[1].strip().strip('"')
                        if parts[0] == "language" and not lang:
                            lang = value
                        elif parts[0] == "territory" and not territory:
                            territory = value
                    if lang and territory:
                        break
        except OSError:
            pass
        label = "%s (%s)" % (lang or base, territory) if territory else (lang or base)
        if "@" in base:
            label += " – " + base.split("@", 1)[1]
        result.append((name, "%s  —  %s" % (label, name)))
    if not any(n == "C.UTF-8" for n, _l in result):
        result.append(("C.UTF-8", "C.UTF-8"))
    _locales = sorted(result, key=lambda e: e[1].lower())
    return _locales


def best_locale(code):
    wanted = language(code)[2]
    names = [n for n, _l in system_locales()]
    if wanted in names or not names:
        return wanted
    prefix = code.split("_")[0] + "_"
    return next((n for n in names if n.startswith(prefix)), "en_US.UTF-8")


_layouts = None


def keyboard_layouts():
    global _layouts
    if _layouts is None:
        _layouts = []
        try:
            root = ET.parse("/usr/share/X11/xkb/rules/evdev.xml").getroot()
        except (OSError, ET.ParseError):
            root = None
        if root is not None:
            for layout in root.iter("layout"):
                ci = layout.find("configItem")
                variants = []
                for v in layout.findall("variantList/variant"):
                    vci = v.find("configItem")
                    variants.append((vci.findtext("name"), vci.findtext("description") or vci.findtext("name")))
                _layouts.append((ci.findtext("name"), ci.findtext("description") or ci.findtext("name"), variants))
    return [(name, _xkb.gettext(desc), [(v, _xkb.gettext(d)) for v, d in variants])
            for name, desc, variants in _layouts]
