"""Minimal libpulse binding (ctypes) driven by the GLib main loop.

Works with PulseAudio and with PipeWire through pipewire-pulse.  Only the
pieces the Sound page needs are bound: server info, sink/source lists,
default device, volume and mute, plus change subscriptions.
"""

import ctypes as C

from gi.repository import GLib, GObject

_pa = C.CDLL("libpulse.so.0")
_pg = C.CDLL("libpulse-mainloop-glib.so.0")

VOLUME_NORM = 0x10000
INVALID_INDEX = 0xFFFFFFFF
CHANNELS_MAX = 32

CONTEXT_READY = 4
CONTEXT_FAILED = 5
CONTEXT_TERMINATED = 6
CONTEXT_NOFAIL = 2

SUBSCRIPTION_MASK_SINK = 0x0001
SUBSCRIPTION_MASK_SOURCE = 0x0002
SUBSCRIPTION_MASK_SERVER = 0x0080


class SampleSpec(C.Structure):
    _fields_ = [("format", C.c_int), ("rate", C.c_uint32), ("channels", C.c_uint8)]


class ChannelMap(C.Structure):
    _fields_ = [("channels", C.c_uint8), ("map", C.c_int * CHANNELS_MAX)]


class CVolume(C.Structure):
    _fields_ = [("channels", C.c_uint8), ("values", C.c_uint32 * CHANNELS_MAX)]


class PortInfo(C.Structure):
    _fields_ = [
        ("name", C.c_char_p),
        ("description", C.c_char_p),
        ("priority", C.c_uint32),
        ("available", C.c_int),
    ]


# Only the leading fields we read are declared; the C structs are longer,
# which is fine because we never allocate them ourselves.
class SinkInfo(C.Structure):
    _fields_ = [
        ("name", C.c_char_p),
        ("index", C.c_uint32),
        ("description", C.c_char_p),
        ("sample_spec", SampleSpec),
        ("channel_map", ChannelMap),
        ("owner_module", C.c_uint32),
        ("volume", CVolume),
        ("mute", C.c_int),
        ("monitor_source", C.c_uint32),
        ("monitor_source_name", C.c_char_p),
        ("latency", C.c_uint64),
        ("driver", C.c_char_p),
        ("flags", C.c_int),
        ("proplist", C.c_void_p),
        ("configured_latency", C.c_uint64),
        ("base_volume", C.c_uint32),
        ("state", C.c_int),
        ("n_volume_steps", C.c_uint32),
        ("card", C.c_uint32),
        ("n_ports", C.c_uint32),
        ("ports", C.POINTER(C.POINTER(PortInfo))),
        ("active_port", C.POINTER(PortInfo)),
    ]


class SourceInfo(C.Structure):
    _fields_ = [
        ("name", C.c_char_p),
        ("index", C.c_uint32),
        ("description", C.c_char_p),
        ("sample_spec", SampleSpec),
        ("channel_map", ChannelMap),
        ("owner_module", C.c_uint32),
        ("volume", CVolume),
        ("mute", C.c_int),
        ("monitor_of_sink", C.c_uint32),
        ("monitor_of_sink_name", C.c_char_p),
        ("latency", C.c_uint64),
        ("driver", C.c_char_p),
        ("flags", C.c_int),
        ("proplist", C.c_void_p),
        ("configured_latency", C.c_uint64),
        ("base_volume", C.c_uint32),
        ("state", C.c_int),
        ("n_volume_steps", C.c_uint32),
        ("card", C.c_uint32),
        ("n_ports", C.c_uint32),
        ("ports", C.POINTER(C.POINTER(PortInfo))),
        ("active_port", C.POINTER(PortInfo)),
    ]


class ServerInfo(C.Structure):
    _fields_ = [
        ("user_name", C.c_char_p),
        ("host_name", C.c_char_p),
        ("server_version", C.c_char_p),
        ("server_name", C.c_char_p),
        ("sample_spec", SampleSpec),
        ("default_sink_name", C.c_char_p),
        ("default_source_name", C.c_char_p),
    ]


CONTEXT_NOTIFY_CB = C.CFUNCTYPE(None, C.c_void_p, C.c_void_p)
SUCCESS_CB = C.CFUNCTYPE(None, C.c_void_p, C.c_int, C.c_void_p)
SINK_INFO_CB = C.CFUNCTYPE(None, C.c_void_p, C.POINTER(SinkInfo), C.c_int, C.c_void_p)
SOURCE_INFO_CB = C.CFUNCTYPE(None, C.c_void_p, C.POINTER(SourceInfo), C.c_int, C.c_void_p)
SERVER_INFO_CB = C.CFUNCTYPE(None, C.c_void_p, C.POINTER(ServerInfo), C.c_void_p)
SUBSCRIBE_CB = C.CFUNCTYPE(None, C.c_void_p, C.c_int, C.c_uint32, C.c_void_p)


def _fn(lib, name, restype, *argtypes):
    f = getattr(lib, name)
    f.restype = restype
    f.argtypes = list(argtypes)
    return f


_vp = C.c_void_p
_s = C.c_char_p
pa_glib_mainloop_new = _fn(_pg, "pa_glib_mainloop_new", _vp, _vp)
pa_glib_mainloop_get_api = _fn(_pg, "pa_glib_mainloop_get_api", _vp, _vp)
pa_context_new = _fn(_pa, "pa_context_new", _vp, _vp, _s)
pa_context_set_state_callback = _fn(_pa, "pa_context_set_state_callback", None, _vp, CONTEXT_NOTIFY_CB, _vp)
pa_context_connect = _fn(_pa, "pa_context_connect", C.c_int, _vp, _s, C.c_int, _vp)
pa_context_disconnect = _fn(_pa, "pa_context_disconnect", None, _vp)
pa_context_unref = _fn(_pa, "pa_context_unref", None, _vp)
pa_context_get_state = _fn(_pa, "pa_context_get_state", C.c_int, _vp)
pa_context_set_subscribe_callback = _fn(_pa, "pa_context_set_subscribe_callback", None, _vp, SUBSCRIBE_CB, _vp)
pa_context_subscribe = _fn(_pa, "pa_context_subscribe", _vp, _vp, C.c_uint32, SUCCESS_CB, _vp)
pa_context_get_server_info = _fn(_pa, "pa_context_get_server_info", _vp, _vp, SERVER_INFO_CB, _vp)
pa_context_get_sink_info_list = _fn(_pa, "pa_context_get_sink_info_list", _vp, _vp, SINK_INFO_CB, _vp)
pa_context_get_source_info_list = _fn(_pa, "pa_context_get_source_info_list", _vp, _vp, SOURCE_INFO_CB, _vp)
pa_context_set_default_sink = _fn(_pa, "pa_context_set_default_sink", _vp, _vp, _s, SUCCESS_CB, _vp)
pa_context_set_default_source = _fn(_pa, "pa_context_set_default_source", _vp, _vp, _s, SUCCESS_CB, _vp)
pa_context_set_sink_volume_by_name = _fn(
    _pa, "pa_context_set_sink_volume_by_name", _vp, _vp, _s, C.POINTER(CVolume), SUCCESS_CB, _vp)
pa_context_set_source_volume_by_name = _fn(
    _pa, "pa_context_set_source_volume_by_name", _vp, _vp, _s, C.POINTER(CVolume), SUCCESS_CB, _vp)
pa_context_set_sink_mute_by_name = _fn(_pa, "pa_context_set_sink_mute_by_name", _vp, _vp, _s, C.c_int, SUCCESS_CB, _vp)
pa_context_set_source_mute_by_name = _fn(
    _pa, "pa_context_set_source_mute_by_name", _vp, _vp, _s, C.c_int, SUCCESS_CB, _vp)
pa_context_set_sink_port_by_name = _fn(_pa, "pa_context_set_sink_port_by_name", _vp, _vp, _s, _s, SUCCESS_CB, _vp)
pa_context_set_source_port_by_name = _fn(
    _pa, "pa_context_set_source_port_by_name", _vp, _vp, _s, _s, SUCCESS_CB, _vp)
pa_operation_unref = _fn(_pa, "pa_operation_unref", None, _vp)
pa_cvolume_max = _fn(_pa, "pa_cvolume_max", C.c_uint32, C.POINTER(CVolume))
pa_cvolume_scale = _fn(_pa, "pa_cvolume_scale", C.POINTER(CVolume), C.POINTER(CVolume), C.c_uint32)


_NOCB = SUCCESS_CB()  # NULL callback


def _str(b):
    return b.decode("utf-8", "replace") if b else ""


class Device:
    """Snapshot of a sink or source."""

    def __init__(self, info):
        self.name = _str(info.name)
        self.index = info.index
        self.description = _str(info.description) or self.name
        self.cvolume = CVolume()
        C.pointer(self.cvolume)[0] = info.volume
        self.mute = bool(info.mute)
        self.volume = pa_cvolume_max(C.byref(self.cvolume)) / VOLUME_NORM
        self.ports = []
        for i in range(info.n_ports):
            p = info.ports[i].contents
            # available: 0 unknown, 1 no, 2 yes
            self.ports.append((_str(p.name), _str(p.description), p.available != 1))
        self.active_port = _str(info.active_port.contents.name) if info.active_port else ""


def _op(op):
    if op:
        pa_operation_unref(op)


class PulseClient(GObject.Object):
    """Keeps a live view of the sound server.  Emits ``changed`` whenever
    devices, defaults or volumes change and ``state-changed`` on connect /
    disconnect."""

    __gsignals__ = {
        "changed": (GObject.SignalFlags.RUN_FIRST, None, ()),
        "state-changed": (GObject.SignalFlags.RUN_FIRST, None, ()),
    }

    def __init__(self):
        super().__init__()
        self.connected = False
        self.sinks = []
        self.sources = []
        self.default_sink = ""
        self.default_source = ""
        self.server_name = ""
        self._pending = 0
        self._new_sinks = []
        self._new_sources = []
        self._refresh_id = 0
        self._ctx = None
        # Keep ctypes callback objects alive for the lifetime of the client.
        self._state_cb = CONTEXT_NOTIFY_CB(self._on_state)
        self._sub_cb = SUBSCRIBE_CB(self._on_event)
        self._sink_cb = SINK_INFO_CB(self._on_sink)
        self._source_cb = SOURCE_INFO_CB(self._on_source)
        self._server_cb = SERVER_INFO_CB(self._on_server)
        self._ml = pa_glib_mainloop_new(None)
        self._api = pa_glib_mainloop_get_api(self._ml)
        self._connect()

    def _connect(self):
        self._ctx = pa_context_new(self._api, b"lxde-settings")
        pa_context_set_state_callback(self._ctx, self._state_cb, None)
        pa_context_connect(self._ctx, None, CONTEXT_NOFAIL, None)
        return False

    def _on_state(self, ctx, _ud):
        state = pa_context_get_state(ctx)
        if state == CONTEXT_READY:
            self.connected = True
            pa_context_set_subscribe_callback(ctx, self._sub_cb, None)
            _op(pa_context_subscribe(
                ctx, SUBSCRIPTION_MASK_SINK | SUBSCRIPTION_MASK_SOURCE | SUBSCRIPTION_MASK_SERVER, _NOCB, None))
            self.emit("state-changed")
            self.refresh()
        elif state in (CONTEXT_FAILED, CONTEXT_TERMINATED):
            was = self.connected
            self.connected = False
            if was:
                self.emit("state-changed")
            pa_context_unref(ctx)
            self._ctx = None
            GLib.timeout_add_seconds(2, self._connect)

    def _on_event(self, _ctx, _type, _idx, _ud):
        if not self._refresh_id:
            self._refresh_id = GLib.timeout_add(40, self._do_refresh)

    def _do_refresh(self):
        self._refresh_id = 0
        self.refresh()
        return False

    def refresh(self):
        if not self.connected or self._pending:
            if self.connected and not self._refresh_id:
                self._refresh_id = GLib.timeout_add(100, self._do_refresh)
            return
        self._pending = 3
        self._new_sinks = []
        self._new_sources = []
        _op(pa_context_get_server_info(self._ctx, self._server_cb, None))
        _op(pa_context_get_sink_info_list(self._ctx, self._sink_cb, None))
        _op(pa_context_get_source_info_list(self._ctx, self._source_cb, None))

    def _finish_one(self):
        self._pending -= 1
        if self._pending == 0:
            self.sinks = self._new_sinks
            self.sources = self._new_sources
            self.emit("changed")

    def _on_server(self, _ctx, info, _ud):
        if info:
            i = info.contents
            self.default_sink = _str(i.default_sink_name)
            self.default_source = _str(i.default_source_name)
            self.server_name = "%s %s" % (_str(i.server_name), _str(i.server_version))
        self._finish_one()

    def _on_sink(self, _ctx, info, eol, _ud):
        if eol:
            self._finish_one()
        elif info:
            self._new_sinks.append(Device(info.contents))

    def _on_source(self, _ctx, info, eol, _ud):
        if eol:
            self._finish_one()
        elif info:
            i = info.contents
            if i.monitor_of_sink == INVALID_INDEX:  # skip "Monitor of ..." sources
                self._new_sources.append(Device(i))

    # --- actions -------------------------------------------------------

    def set_default(self, kind, name):
        fn = pa_context_set_default_sink if kind == "sink" else pa_context_set_default_source
        _op(fn(self._ctx, name.encode(), _NOCB, None))

    def set_volume(self, kind, dev, value):
        cv = CVolume()
        C.pointer(cv)[0] = dev.cvolume
        pa_cvolume_scale(C.byref(cv), int(max(0.0, value) * VOLUME_NORM))
        dev.cvolume = cv
        fn = pa_context_set_sink_volume_by_name if kind == "sink" else pa_context_set_source_volume_by_name
        _op(fn(self._ctx, dev.name.encode(), C.byref(cv), _NOCB, None))

    def set_mute(self, kind, dev, mute):
        fn = pa_context_set_sink_mute_by_name if kind == "sink" else pa_context_set_source_mute_by_name
        _op(fn(self._ctx, dev.name.encode(), int(mute), _NOCB, None))

    def set_port(self, kind, dev, port):
        fn = pa_context_set_sink_port_by_name if kind == "sink" else pa_context_set_source_port_by_name
        _op(fn(self._ctx, dev.name.encode(), port.encode(), _NOCB, None))
