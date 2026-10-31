"""Install-time paths.  ``make install`` substitutes the @...@ values; when
running from the source tree they fall back to paths inside the checkout."""

import os

_src = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

LOCALEDIR = "@LOCALEDIR@"
HELPER = "@HELPER@"
DATADIR = "@PKGDATADIR@"

if LOCALEDIR.startswith("@"):
    LOCALEDIR = os.path.join(_src, "build", "locale")
if HELPER.startswith("@"):
    HELPER = os.path.join(_src, "helper", "lxde-settings-helper")
if DATADIR.startswith("@"):
    DATADIR = os.path.join(_src, "data")
