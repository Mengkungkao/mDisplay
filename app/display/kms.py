"""Direct HDMI output through the kernel's DRM/KMS, for boards without a desktop.

mFruit OS boards (Raspberry Pi OS Lite, Orange Pi server images) have no X11
or Wayland session: the HDMI port shows the text console. This module drives
the port itself, as an unprivileged member of the ``video`` group:

  1. open ``/dev/dri/cardN``; with no desktop running, the first program to
     open it may set modes (it becomes the DRM master);
  2. pick a *connected* external connector (HDMI, DisplayPort, DVI, VGA) and
     a mode (the screen's preferred one, or a smaller one of the same shape
     when frames are drawn in software);
  3. create two "dumb" frame buffers in kernel memory, map them, and show
     one while the next frame is written into the other; a page flip swaps
     them at the next vertical blank, so there is no tearing;
  4. on close, put back what the console showed (the kernel's own console
     also returns when the device is closed).

Frames are drawn by SDL's software renderer (dummy video driver, no window)
and copied straight into the mapped buffer. The Whisplay LCD is not a DRM
device (whisplay-daemon drives it over SPI), and only external connector
types are ever used, so this never touches it. Nothing here needs root.

All structures and ioctl numbers follow the kernel's uapi drm.h/drm_mode.h;
tests check their sizes against the well-known request numbers.
"""

from __future__ import annotations

import ctypes
import errno
import fcntl
import glob
import mmap
import os
import select
import struct
from ctypes import c_char, c_uint16, c_uint32, c_uint64
from dataclasses import dataclass, field
from typing import Optional

DRM_DIR = "/dev/dri"


def _iowr(nr: int, size: int) -> int:
    return (3 << 30) | (size << 16) | (ord("d") << 8) | nr


def _io(nr: int) -> int:
    return (ord("d") << 8) | nr


class ModeInfo(ctypes.Structure):
    _fields_ = [("clock", c_uint32), ("hdisplay", c_uint16), ("hsync_start", c_uint16),
                ("hsync_end", c_uint16), ("htotal", c_uint16), ("hskew", c_uint16),
                ("vdisplay", c_uint16), ("vsync_start", c_uint16), ("vsync_end", c_uint16),
                ("vtotal", c_uint16), ("vscan", c_uint16), ("vrefresh", c_uint32),
                ("flags", c_uint32), ("type", c_uint32), ("name", c_char * 32)]


class CardRes(ctypes.Structure):
    _fields_ = [("fb_id_ptr", c_uint64), ("crtc_id_ptr", c_uint64), ("connector_id_ptr", c_uint64),
                ("encoder_id_ptr", c_uint64), ("count_fbs", c_uint32), ("count_crtcs", c_uint32),
                ("count_connectors", c_uint32), ("count_encoders", c_uint32),
                ("min_width", c_uint32), ("max_width", c_uint32), ("min_height", c_uint32),
                ("max_height", c_uint32)]


class Crtc(ctypes.Structure):
    _fields_ = [("set_connectors_ptr", c_uint64), ("count_connectors", c_uint32),
                ("crtc_id", c_uint32), ("fb_id", c_uint32), ("x", c_uint32), ("y", c_uint32),
                ("gamma_size", c_uint32), ("mode_valid", c_uint32), ("mode", ModeInfo)]


class GetEncoder(ctypes.Structure):
    _fields_ = [("encoder_id", c_uint32), ("encoder_type", c_uint32), ("crtc_id", c_uint32),
                ("possible_crtcs", c_uint32), ("possible_clones", c_uint32)]


class GetConnector(ctypes.Structure):
    _fields_ = [("encoders_ptr", c_uint64), ("modes_ptr", c_uint64), ("props_ptr", c_uint64),
                ("prop_values_ptr", c_uint64), ("count_modes", c_uint32), ("count_props", c_uint32),
                ("count_encoders", c_uint32), ("encoder_id", c_uint32), ("connector_id", c_uint32),
                ("connector_type", c_uint32), ("connector_type_id", c_uint32),
                ("connection", c_uint32), ("mm_width", c_uint32), ("mm_height", c_uint32),
                ("subpixel", c_uint32), ("pad", c_uint32)]


class FbCmd(ctypes.Structure):
    _fields_ = [("fb_id", c_uint32), ("width", c_uint32), ("height", c_uint32),
                ("pitch", c_uint32), ("bpp", c_uint32), ("depth", c_uint32), ("handle", c_uint32)]


class PageFlip(ctypes.Structure):
    _fields_ = [("crtc_id", c_uint32), ("fb_id", c_uint32), ("flags", c_uint32),
                ("reserved", c_uint32), ("user_data", c_uint64)]


class CreateDumb(ctypes.Structure):
    _fields_ = [("height", c_uint32), ("width", c_uint32), ("bpp", c_uint32), ("flags", c_uint32),
                ("handle", c_uint32), ("pitch", c_uint32), ("size", c_uint64)]


class MapDumb(ctypes.Structure):
    _fields_ = [("handle", c_uint32), ("pad", c_uint32), ("offset", c_uint64)]


class DestroyDumb(ctypes.Structure):
    _fields_ = [("handle", c_uint32)]


SET_MASTER = _io(0x1E)
DROP_MASTER = _io(0x1F)
GETRESOURCES = _iowr(0xA0, ctypes.sizeof(CardRes))
GETCRTC = _iowr(0xA1, ctypes.sizeof(Crtc))
SETCRTC = _iowr(0xA2, ctypes.sizeof(Crtc))
GETENCODER = _iowr(0xA6, ctypes.sizeof(GetEncoder))
GETCONNECTOR = _iowr(0xA7, ctypes.sizeof(GetConnector))
ADDFB = _iowr(0xAE, ctypes.sizeof(FbCmd))
RMFB = _iowr(0xAF, 4)
PAGE_FLIP = _iowr(0xB0, ctypes.sizeof(PageFlip))
CREATE_DUMB = _iowr(0xB2, ctypes.sizeof(CreateDumb))
MAP_DUMB = _iowr(0xB3, ctypes.sizeof(MapDumb))
DESTROY_DUMB = _iowr(0xB4, ctypes.sizeof(DestroyDumb))

PAGE_FLIP_EVENT = 0x01
EVENT_FLIP_COMPLETE = 0x02
MODE_TYPE_PREFERRED = 1 << 3
CONNECTED = 1

CONNECTOR_TYPES = {0: "Unknown", 1: "VGA", 2: "DVI-I", 3: "DVI-D", 4: "DVI-A", 5: "Composite",
                   6: "SVIDEO", 7: "LVDS", 8: "Component", 9: "DIN", 10: "DP", 11: "HDMI-A",
                   12: "HDMI-B", 13: "TV", 14: "eDP", 15: "Virtual", 16: "DSI", 17: "DPI",
                   18: "Writeback", 19: "SPI", 20: "USB"}
# Screens a person plugs in. Built-in panels (eDP, DSI, DPI, LVDS), SPI panels
# and virtual or write-back connectors are never chosen automatically.
EXTERNAL = {11: 0, 12: 0, 10: 1, 3: 2, 2: 2, 4: 3, 1: 4}


class KmsError(Exception):
    """The HDMI port cannot be used; ``remedy`` says what to do."""

    def __init__(self, problem: str, remedy: str = ""):
        super().__init__(problem)
        self.problem = problem
        self.remedy = remedy


@dataclass
class Mode:
    width: int
    height: int
    refresh: int
    preferred: bool
    info: ModeInfo = field(repr=False, default=None)

    def describe(self) -> str:
        return f"{self.width}×{self.height} @ {self.refresh} Hz"


@dataclass
class Connector:
    card: str
    id: int
    type: int
    type_id: int
    connected: bool
    modes: list
    encoder_id: int
    encoders: list
    mm: tuple = (0, 0)

    @property
    def name(self) -> str:
        return f"{CONNECTOR_TYPES.get(self.type, 'Unknown')}-{self.type_id}"

    @property
    def external(self) -> bool:
        return self.type in EXTERNAL


def _ioctl(fd: int, request: int, arg) -> None:
    fcntl.ioctl(fd, request, arg, True)


def _array(ctype, count: int):
    return (ctype * max(1, count))()


def resources(fd: int) -> tuple:
    """(crtc ids, connector ids, encoder ids) of an open card."""
    res = CardRes()
    _ioctl(fd, GETRESOURCES, res)
    for _ in range(3):       # the counts can change between the two calls (hot-plug)
        fbs, crtcs = _array(c_uint32, res.count_fbs), _array(c_uint32, res.count_crtcs)
        conns, encs = _array(c_uint32, res.count_connectors), _array(c_uint32, res.count_encoders)
        counts = (res.count_fbs, res.count_crtcs, res.count_connectors, res.count_encoders)
        res.fb_id_ptr, res.crtc_id_ptr = ctypes.addressof(fbs), ctypes.addressof(crtcs)
        res.connector_id_ptr, res.encoder_id_ptr = ctypes.addressof(conns), ctypes.addressof(encs)
        _ioctl(fd, GETRESOURCES, res)
        if counts == (res.count_fbs, res.count_crtcs, res.count_connectors, res.count_encoders):
            return (list(crtcs[:res.count_crtcs]), list(conns[:res.count_connectors]),
                    list(encs[:res.count_encoders]))
    raise KmsError("The display hardware kept changing while it was being read.", "Try again.")


def connector(fd: int, card: str, connector_id: int) -> Connector:
    info = GetConnector(connector_id=connector_id)
    _ioctl(fd, GETCONNECTOR, info)
    for _ in range(3):
        modes = _array(ModeInfo, info.count_modes)
        encoders = _array(c_uint32, info.count_encoders)
        props, values = _array(c_uint32, info.count_props), _array(c_uint64, info.count_props)
        counts = (info.count_modes, info.count_encoders, info.count_props)
        info.modes_ptr, info.encoders_ptr = ctypes.addressof(modes), ctypes.addressof(encoders)
        info.props_ptr, info.prop_values_ptr = ctypes.addressof(props), ctypes.addressof(values)
        _ioctl(fd, GETCONNECTOR, info)
        if counts == (info.count_modes, info.count_encoders, info.count_props):
            break
    found = [Mode(m.hdisplay, m.vdisplay, m.vrefresh, bool(m.type & MODE_TYPE_PREFERRED),
                  _copy_mode(m)) for m in modes[:info.count_modes]]
    return Connector(card, connector_id, info.connector_type, info.connector_type_id,
                     info.connection == CONNECTED, found, info.encoder_id,
                     list(encoders[:info.count_encoders]), (info.mm_width, info.mm_height))


def _copy_mode(mode: ModeInfo) -> ModeInfo:
    copy = ModeInfo()
    ctypes.memmove(ctypes.addressof(copy), ctypes.addressof(mode), ctypes.sizeof(ModeInfo))
    return copy


def cards() -> list:
    return sorted(glob.glob(os.path.join(DRM_DIR, "card[0-9]*")))


def survey() -> list:
    """Every connector of every card (for --diagnose); never sets a mode."""
    found = []
    for card in cards():
        try:
            fd = os.open(card, os.O_RDWR | os.O_CLOEXEC)
        except OSError as exc:
            found.append({"card": card, "error": exc.strerror or str(exc)})
            continue
        try:
            _crtcs, connector_ids, _encs = resources(fd)
            for cid in connector_ids:
                c = connector(fd, card, cid)
                found.append({"card": card, "connector": c.name, "connected": c.connected,
                              "external": c.external,
                              "modes": sorted({m.describe() for m in c.modes})})
        except (OSError, KmsError) as exc:
            found.append({"card": card, "error": str(exc)})
        finally:
            os.close(fd)
    return found


def choose_mode(modes: list, prefer_small: bool, max_pixels: int = 1920 * 1080) -> Optional[Mode]:
    """The screen's preferred mode; with ``prefer_small`` (software drawing) the smallest
    mode of the same shape that is at least 1280 wide, so frames stay cheap."""
    if not modes:
        return None
    preferred = next((m for m in modes if m.preferred), None) or max(
        modes, key=lambda m: (m.width * m.height, m.refresh))
    shape = preferred.width / max(1, preferred.height)
    usable = [m for m in modes if m.width * m.height <= max_pixels] or modes
    if preferred.width * preferred.height > max_pixels:
        preferred = max(usable, key=lambda m: (m.width * m.height, -abs(m.refresh - 60)))
    if not prefer_small:
        return preferred
    same = [m for m in usable if abs(m.width / max(1, m.height) - shape) < 0.02 and m.width >= 1280
            and 50 <= m.refresh <= 61]
    if not same:
        return preferred
    return min(same, key=lambda m: (m.width * m.height, -m.refresh))


def choose_connector(connectors: list, wanted: str = "") -> Optional[Connector]:
    """The connected external screen (``wanted`` = a name such as HDMI-A-1)."""
    live = [c for c in connectors if c.connected and c.modes]
    if wanted and wanted != "auto":
        return next((c for c in live if c.name == wanted), None)
    external = [c for c in live if c.external]
    return min(external, key=lambda c: (EXTERNAL[c.type], c.card, c.type_id), default=None)


class DumbBuffer:
    def __init__(self, fd: int, width: int, height: int):
        self.fd = fd
        self.handle = 0
        self.fb_id = 0
        self.map = None
        create = CreateDumb(height=height, width=width, bpp=32)
        _ioctl(fd, CREATE_DUMB, create)
        self.handle, self.pitch, self.size = create.handle, create.pitch, create.size
        try:
            fb = FbCmd(width=width, height=height, pitch=self.pitch, bpp=32, depth=24,
                       handle=self.handle)
            _ioctl(fd, ADDFB, fb)
            self.fb_id = fb.fb_id
            mapping = MapDumb(handle=self.handle)
            _ioctl(fd, MAP_DUMB, mapping)
            self.map = mmap.mmap(fd, self.size, mmap.MAP_SHARED, mmap.PROT_READ | mmap.PROT_WRITE,
                                 offset=mapping.offset)
            self.view = (ctypes.c_char * self.size).from_buffer(self.map)
            self.address = ctypes.addressof(self.view)
            ctypes.memset(self.address, 0, self.size)
        except Exception:
            self.release()
            raise

    def release(self) -> None:
        if self.map is not None:
            self.view = None
            try:
                self.map.close()
            except BufferError:
                pass
            self.map = None
        if self.fb_id:
            try:
                _ioctl(self.fd, RMFB, ctypes.c_uint32(self.fb_id))
            except OSError:
                pass
            self.fb_id = 0
        if self.handle:
            try:
                _ioctl(self.fd, DESTROY_DUMB, DestroyDumb(handle=self.handle))
            except OSError:
                pass
            self.handle = 0


class KmsOutput:
    """Owns one connector of one card while mDisplay shows on it."""

    def __init__(self, wanted: str = "auto", prefer_small: bool = True):
        self.wanted = wanted
        self.prefer_small = prefer_small
        self.fd = -1
        self.connector: Optional[Connector] = None
        self.mode: Optional[Mode] = None
        self.crtc_id = 0
        self.saved: Optional[Crtc] = None
        self.buffers: list = []
        self.front = 0
        self.flip_pending = False
        self.flips = True
        self.connectors: list = []

    @property
    def size(self) -> tuple:
        return (self.mode.width, self.mode.height) if self.mode else (0, 0)

    def describe(self) -> str:
        if not self.connector:
            return ""
        return f"{self.connector.name} · {self.mode.width}×{self.mode.height} · {self.mode.refresh} Hz"

    def open(self) -> "KmsOutput":
        found = cards()
        if not found:
            raise KmsError("This board has no display hardware the kernel can drive (no /dev/dri).",
                           "Check that the board's display driver is loaded.")
        problems = []
        for card in found:
            try:
                fd = os.open(card, os.O_RDWR | os.O_CLOEXEC)
            except PermissionError:
                problems.append(f"{card}: permission denied")
                continue
            except OSError as exc:
                problems.append(f"{card}: {exc.strerror or exc}")
                continue
            try:
                crtcs, connector_ids, _ = resources(fd)
                connectors = [connector(fd, card, cid) for cid in connector_ids]
                self.connectors += connectors
                chosen = choose_connector(connectors, self.wanted)
                if chosen is None:
                    os.close(fd)
                    continue
                self.fd = fd
                self.connector = chosen
                self.crtc_id = self._crtc_for(chosen, crtcs)
                self.mode = choose_mode(chosen.modes, self.prefer_small)
                self._start()
                return self
            except KmsError:
                self.close()
                raise
            except OSError as exc:
                problems.append(f"{card}: {exc.strerror or exc}")
                self.close()
        if any("permission" in p for p in problems):
            raise KmsError("mDisplay may not use the HDMI port (permission denied).",
                           "Add this user to the 'video' group: sudo usermod -aG video $USER, "
                           "then restart the board.")
        if self.wanted not in ("", "auto"):
            raise KmsError(f"Screen {self.wanted} is not connected.",
                           "Connect it, or choose another screen in the settings.")
        raise KmsError("No screen is connected to the HDMI port.",
                       "Connect a TV or monitor to HDMI and switch it on, then Retry.")

    def _crtc_for(self, chosen: Connector, crtcs: list) -> int:
        candidates = ([chosen.encoder_id] if chosen.encoder_id else []) + chosen.encoders
        for encoder_id in candidates:
            enc = GetEncoder(encoder_id=encoder_id)
            try:
                _ioctl(self.fd, GETENCODER, enc)
            except OSError:
                continue
            if enc.crtc_id:
                return enc.crtc_id
            for index, crtc_id in enumerate(crtcs):
                if enc.possible_crtcs & (1 << index):
                    return crtc_id
        raise KmsError(f"{chosen.name} has no display controller free.", "Restart the board.")

    def _start(self) -> None:
        saved = Crtc(crtc_id=self.crtc_id)
        try:
            _ioctl(self.fd, GETCRTC, saved)
            self.saved = saved
        except OSError:
            self.saved = None
        w, h = self.mode.width, self.mode.height
        self.buffers = [DumbBuffer(self.fd, w, h), DumbBuffer(self.fd, w, h)]
        self._set_crtc(self.buffers[0].fb_id, self.mode.info)
        self.front = 0

    def _set_crtc(self, fb_id: int, mode: ModeInfo, x: int = 0, y: int = 0) -> None:
        ids = (c_uint32 * 1)(self.connector.id)
        crtc = Crtc(set_connectors_ptr=ctypes.addressof(ids), count_connectors=1,
                    crtc_id=self.crtc_id, fb_id=fb_id, x=x, y=y, mode_valid=1)
        crtc.mode = mode
        try:
            _ioctl(self.fd, SETCRTC, crtc)
        except PermissionError:
            try:
                _ioctl(self.fd, SET_MASTER, 0)
                _ioctl(self.fd, SETCRTC, crtc)
            except OSError as exc:
                raise KmsError("Another program is using the HDMI screen (a desktop or "
                               "another app).", "Close it, or run mDisplay inside that "
                               f"desktop instead ({exc.strerror or exc}).") from exc

    # -------------------------------------------------------------- frames
    @property
    def back(self) -> DumbBuffer:
        return self.buffers[1 - self.front]

    def wait_flip(self, timeout: float = 0.1) -> bool:
        """Wait for the last page flip to complete (vertical blank)."""
        if not self.flip_pending:
            return True
        ready, _, _ = select.select([self.fd], [], [], timeout)
        if not ready:
            return False
        data = os.read(self.fd, 4096)
        offset = 0
        while offset + 8 <= len(data):
            kind, length = struct.unpack_from("<II", data, offset)
            if kind == EVENT_FLIP_COMPLETE:
                self.flip_pending = False
            offset += max(8, length)
        return not self.flip_pending

    def show(self, write) -> None:
        """``write(address, pitch)`` fills the back buffer; then it is shown at the next blank."""
        if self.flip_pending and not self.wait_flip(0.1):
            self.flip_pending = False      # a lost event must not stop the display
        back = self.back
        write(back.address, back.pitch)
        if self.flips:
            flip = PageFlip(crtc_id=self.crtc_id, fb_id=back.fb_id, flags=PAGE_FLIP_EVENT)
            try:
                _ioctl(self.fd, PAGE_FLIP, flip)
                self.flip_pending = True
            except OSError as exc:
                if exc.errno in (errno.EINVAL, errno.ENOSYS, errno.EOPNOTSUPP):
                    self.flips = False     # this driver cannot flip: set the buffer directly
                    self._set_crtc(back.fb_id, self.mode.info)
                elif exc.errno == errno.EBUSY:
                    self.wait_flip(0.1)
                    return
                else:
                    raise
        else:
            self._set_crtc(back.fb_id, self.mode.info)
        self.front = 1 - self.front

    def close(self) -> None:
        if self.fd < 0:
            return
        if self.flip_pending:
            self.wait_flip(0.2)
        if self.saved is not None and self.saved.mode_valid and self.saved.fb_id:
            try:
                self._set_crtc(self.saved.fb_id, self.saved.mode, self.saved.x, self.saved.y)
            except (OSError, KmsError):
                pass               # closing the device below brings the console back anyway
        for buffer in self.buffers:
            buffer.release()
        self.buffers = []
        try:
            os.close(self.fd)
        except OSError:
            pass
        self.fd = -1


def main(argv=None) -> int:
    """``python3 -m app.display.kms`` lists the screens; ``--pattern SECONDS`` shows a test
    picture on the connected one for that long, then gives the screen back."""
    import argparse
    import json
    import time
    parser = argparse.ArgumentParser(description="DRM/KMS screens (no desktop needed)")
    parser.add_argument("--pattern", type=float, default=0.0)
    args = parser.parse_args(argv)
    print(json.dumps(survey(), indent=2))
    if args.pattern <= 0:
        return 0
    out = KmsOutput(prefer_small=True).open()
    print("showing on", out.describe(), flush=True)
    w, h = out.size
    started, frames = time.monotonic(), 0
    try:
        while time.monotonic() - started < args.pattern:
            shade = int(127 + 120 * ((frames % 120) / 120.0))

            def write(address, pitch, shade=shade):
                row = bytes([shade // 3, shade // 2, shade, 255]) * w
                for y in range(0, h, 1):
                    ctypes.memmove(address + y * pitch, row, len(row))
            out.show(write)
            frames += 1
    finally:
        out.close()
    print(f"{frames} frames in {args.pattern:.1f} s", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
