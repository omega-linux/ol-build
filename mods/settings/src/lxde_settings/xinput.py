"""Pointer settings for the Xorg libinput driver through XInput2 (ctypes on
libXi), so no ``xinput`` binary is needed.  The libinput driver ignores the
core-protocol acceleration that ``xset m`` sets; it only honours its own
"libinput Accel Speed" / "Accel Profile Enabled" device properties."""

import ctypes as C
import struct

XI_ALL_DEVICES = 0
XI_SLAVE_POINTER = 3
PROP_MODE_REPLACE = 0
ANY_PROPERTY_TYPE = 0

try:
    _x = C.CDLL("libX11.so.6")
    _xi = C.CDLL("libXi.so.6")
except OSError:
    _x = _xi = None


class _DeviceInfo(C.Structure):
    _fields_ = [("deviceid", C.c_int), ("name", C.c_char_p), ("use", C.c_int), ("attachment", C.c_int),
                ("enabled", C.c_int), ("num_classes", C.c_int), ("classes", C.c_void_p)]


if _xi is not None:
    _x.XOpenDisplay.restype = C.c_void_p
    _x.XOpenDisplay.argtypes = [C.c_char_p]
    _x.XCloseDisplay.argtypes = [C.c_void_p]
    _x.XFlush.argtypes = [C.c_void_p]
    _x.XFree.argtypes = [C.c_void_p]
    _x.XInternAtom.restype = C.c_ulong
    _x.XInternAtom.argtypes = [C.c_void_p, C.c_char_p, C.c_int]
    _xi.XIQueryDevice.restype = C.POINTER(_DeviceInfo)
    _xi.XIQueryDevice.argtypes = [C.c_void_p, C.c_int, C.POINTER(C.c_int)]
    _xi.XIFreeDeviceInfo.argtypes = [C.POINTER(_DeviceInfo)]
    _xi.XIListProperties.restype = C.POINTER(C.c_ulong)
    _xi.XIListProperties.argtypes = [C.c_void_p, C.c_int, C.POINTER(C.c_int)]
    _xi.XIGetProperty.restype = C.c_int
    _xi.XIGetProperty.argtypes = [C.c_void_p, C.c_int, C.c_ulong, C.c_long, C.c_long, C.c_int, C.c_ulong,
                                  C.POINTER(C.c_ulong), C.POINTER(C.c_int), C.POINTER(C.c_ulong),
                                  C.POINTER(C.c_ulong), C.POINTER(C.POINTER(C.c_ubyte))]
    _xi.XIChangeProperty.argtypes = [C.c_void_p, C.c_int, C.c_ulong, C.c_ulong, C.c_int, C.c_int,
                                     C.c_char_p, C.c_int]


class _Display:
    def __enter__(self):
        self.dpy = _x.XOpenDisplay(None) if _xi is not None else None
        return self if self.dpy else None

    def __exit__(self, *_a):
        if self.dpy:
            _x.XFlush(self.dpy)
            _x.XCloseDisplay(self.dpy)

    def atom(self, name):
        return _x.XInternAtom(self.dpy, name.encode(), 1)  # only_if_exists

    def pointers(self, prop):
        """Ids of physical pointers that have the given property."""
        atom = self.atom(prop)
        if not atom:
            return []
        n = C.c_int()
        info = _xi.XIQueryDevice(self.dpy, XI_ALL_DEVICES, C.byref(n))
        ids = []
        for i in range(n.value):
            if info[i].use != XI_SLAVE_POINTER:
                continue
            k = C.c_int()
            props = _xi.XIListProperties(self.dpy, info[i].deviceid, C.byref(k))
            if props:
                if atom in props[:k.value]:
                    ids.append(info[i].deviceid)
                _x.XFree(props)
        _xi.XIFreeDeviceInfo(info)
        return ids

    def get(self, dev, prop):
        """Return (format, raw bytes) of a device property."""
        atype, fmt, nitems, after = C.c_ulong(), C.c_int(), C.c_ulong(), C.c_ulong()
        data = C.POINTER(C.c_ubyte)()
        if _xi.XIGetProperty(self.dpy, dev, self.atom(prop), 0, 64, 0, ANY_PROPERTY_TYPE, C.byref(atype),
                             C.byref(fmt), C.byref(nitems), C.byref(after), C.byref(data)) != 0 or not data:
            return 0, b""
        raw = C.string_at(data, nitems.value * fmt.value // 8)
        _x.XFree(data)
        return fmt.value, raw

    def set(self, dev, prop, type_name, fmt, raw):
        # XI2 packs format-32 data as 32-bit items (unlike core XChangeProperty).
        _xi.XIChangeProperty(self.dpy, dev, self.atom(prop), _x.XInternAtom(self.dpy, type_name.encode(), 0),
                             fmt, PROP_MODE_REPLACE, raw, len(raw) * 8 // fmt)


def available():
    with _Display() as d:
        return bool(d and d.pointers("libinput Accel Speed"))
    return False


def get_state():
    """(speed -1..1, acceleration on, left handed) from the first libinput mouse, or None."""
    with _Display() as d:
        if not d:
            return None
        devs = d.pointers("libinput Accel Speed")
        if not devs:
            return None
        _f, raw = d.get(devs[0], "libinput Accel Speed")
        speed = struct.unpack("=f", raw[:4])[0] if len(raw) >= 4 else 0.0
        _f, prof = d.get(devs[0], "libinput Accel Profile Enabled")
        accel = not (len(prof) >= 2 and prof[1] == 1)  # [adaptive, flat, ...]
        _f, lh = d.get(devs[0], "libinput Left Handed Enabled")
        return speed, accel, bool(lh and lh[0])
    return None


def apply(speed, accel, left_handed):
    """Apply to every libinput pointer; returns False when there are none."""
    with _Display() as d:
        if not d:
            return False
        devs = d.pointers("libinput Accel Speed")
        for dev in devs:
            d.set(dev, "libinput Accel Speed", "FLOAT", 32, struct.pack("=f", max(-1.0, min(1.0, speed))))
            _f, avail = d.get(dev, "libinput Accel Profiles Available")
            _f, cur = d.get(dev, "libinput Accel Profile Enabled")
            if len(avail) >= 2 and avail[1] and cur:
                prof = bytearray(len(cur))
                prof[0 if accel else 1] = 1
                d.set(dev, "libinput Accel Profile Enabled", "INTEGER", 8, bytes(prof))
        for dev in d.pointers("libinput Left Handed Enabled"):
            d.set(dev, "libinput Left Handed Enabled", "INTEGER", 8, bytes([1 if left_handed else 0]))
        return bool(devs)
    return False
