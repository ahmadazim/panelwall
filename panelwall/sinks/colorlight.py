"""ColorlightSink: pushes frames to a Colorlight 5A-75B over raw Ethernet.

Protocol (reverse-engineered; two independent implementations agree -
Harald Kubota's write-up and the colorlight.rs crate):

  All frames are raw layer-2 Ethernet, no IP.  dst 11:22:33:44:55:66,
  src 22:22:33:44:55:66 (the card doesn't care about the src).

  Per displayed image, in this order:
    1. One ROW frame per display row, ethertype 0x5500 (rows 0-255) or
       0x5501 (rows 256-511).  Payload:
         [0]    row number, low byte
         [1:3]  pixel offset (big-endian) - x position of first pixel
         [3:5]  pixel count  (big-endian)
         [5]    0x08
         [6]    0x88
         [7:]   pixels, 3 bytes each, B G R order
    2. One DISPLAY frame, ethertype 0x0107, 98-byte payload, which tells
       the card "show what you've just received":
         [21]   brightness 0..255
         [22]   0x05
         [24:27] per-channel brightness R,G,B (0xFF = full)

  Optional: a BRIGHTNESS frame, ethertype 0x0A00 | level, 63-byte payload
  starting [level, level, 0xFF, 0...]. We use the byte inside 0x0107 instead.

Needs CAP_NET_RAW: run with sudo, or
  sudo setcap cap_net_raw+ep $(readlink -f $(which python3))
"""

from __future__ import annotations

import socket
import struct

import numpy as np

from .base import Sink

DST_MAC = bytes.fromhex("112233445566")
SRC_MAC = bytes.fromhex("222233445566")

ET_DISPLAY = 0x0107
ET_BRIGHTNESS_BASE = 0x0A00
ET_ROW_BASE = 0x5500

MAX_PIXELS_PER_PACKET = 497  # (1500 - 7) // 3 : keep under the standard MTU


def _eth_header(ethertype: int) -> bytes:
    return DST_MAC + SRC_MAC + struct.pack("!H", ethertype)


def build_row_packet(row: int, x_offset: int, pixels_bgr: bytes) -> bytes:
    """One 0x55xx packet carrying `len(pixels_bgr)//3` pixels of one row."""
    n = len(pixels_bgr) // 3
    if not (0 <= row < 512):
        raise ValueError("row out of range")
    if n > MAX_PIXELS_PER_PACKET:
        raise ValueError("too many pixels for one packet")
    ethertype = ET_ROW_BASE | (row >> 8)
    payload = struct.pack("!BHHBB", row & 0xFF, x_offset, n, 0x08, 0x88) + pixels_bgr
    return _eth_header(ethertype) + payload


def build_display_packet(brightness: int = 0xFF, rgb: tuple[int, int, int] = (0xFF, 0xFF, 0xFF)) -> bytes:
    payload = bytearray(98)
    payload[21] = brightness & 0xFF
    payload[22] = 0x05
    payload[24], payload[25], payload[26] = (v & 0xFF for v in rgb)
    return _eth_header(ET_DISPLAY) + bytes(payload)


def build_brightness_packet(level: int) -> bytes:
    level &= 0xFF
    payload = bytearray(63)
    payload[0] = level
    payload[1] = level
    payload[2] = 0xFF
    return _eth_header(ET_BRIGHTNESS_BASE | level) + bytes(payload)


def frame_to_packets(frame: np.ndarray, brightness: int) -> list[bytes]:
    """Pure function: RGB (H, W, 3) -> list of raw Ethernet frames, in send order."""
    h, w, c = frame.shape
    assert c == 3
    bgr = np.ascontiguousarray(frame[:, :, ::-1])  # RGB -> BGR
    pkts = []
    for y in range(h):
        row = bgr[y].tobytes()
        for x0 in range(0, w, MAX_PIXELS_PER_PACKET):
            chunk = row[x0 * 3:(x0 + MAX_PIXELS_PER_PACKET) * 3]
            pkts.append(build_row_packet(y, x0, chunk))
    pkts.append(build_display_packet(brightness))
    return pkts


class ColorlightSink(Sink):
    def __init__(self, iface: str = "eth0", brightness: int = 0xBF, sock=None):
        self.iface = iface
        self.brightness = brightness
        if sock is None:
            # ETH_P_ALL so we can also read (detection replies) if we ever want to
            sock = socket.socket(socket.AF_PACKET, socket.SOCK_RAW, socket.htons(0x0003))
            sock.bind((iface, 0))
        self.sock = sock

    def set_brightness(self, level: int) -> None:
        self.brightness = max(0, min(255, int(level)))

    def show(self, frame: np.ndarray) -> None:
        for p in frame_to_packets(frame, self.brightness):
            self.sock.send(p)

    def close(self) -> None:
        try:
            self.sock.close()
        except OSError:
            pass
