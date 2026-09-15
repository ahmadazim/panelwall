"""Byte-level checks of the Colorlight packet builders against the documented layout."""

import struct

import numpy as np

from panelwall.sinks.colorlight import (
    DST_MAC, SRC_MAC, build_display_packet, build_row_packet, build_brightness_packet,
    frame_to_packets, ColorlightSink,
)


def test_row_packet_layout():
    px = bytes([1, 2, 3, 4, 5, 6])  # two pixels, already BGR
    p = build_row_packet(row=5, x_offset=0x0102, pixels_bgr=px)
    assert p[0:6] == DST_MAC and p[6:12] == SRC_MAC
    assert p[12:14] == b"\x55\x00"
    payload = p[14:]
    assert payload[0] == 5
    assert payload[1:3] == b"\x01\x02"          # x offset, big-endian
    assert payload[3:5] == b"\x00\x02"          # pixel count
    assert payload[5] == 0x08 and payload[6] == 0x88
    assert payload[7:] == px


def test_row_above_255_uses_5501():
    p = build_row_packet(row=300, x_offset=0, pixels_bgr=b"\x00\x00\x00")
    assert p[12:14] == b"\x55\x01"
    assert p[14] == 300 & 0xFF


def test_display_packet_layout():
    p = build_display_packet(brightness=0xBF, rgb=(0x10, 0x20, 0x30))
    assert p[12:14] == b"\x01\x07"
    payload = p[14:]
    assert len(payload) == 98
    assert payload[21] == 0xBF
    assert payload[22] == 0x05
    assert payload[24:27] == b"\x10\x20\x30"
    assert sum(payload) == 0xBF + 0x05 + 0x10 + 0x20 + 0x30  # everything else zero


def test_brightness_packet():
    p = build_brightness_packet(0x92)
    assert p[12:14] == b"\x0a\x92"
    assert p[14:17] == b"\x92\x92\xff" and len(p) == 14 + 63


def test_frame_to_packets_order_and_bgr():
    f = np.zeros((64, 256, 3), dtype=np.uint8)
    f[3, 7] = (255, 0, 0)     # pure red at (x=7, y=3)
    pkts = frame_to_packets(f, brightness=0x80)
    assert len(pkts) == 64 + 1                   # one per row + display
    assert pkts[-1][12:14] == b"\x01\x07"
    row3 = pkts[3]
    assert row3[14] == 3
    n = struct.unpack("!H", row3[17:19])[0]
    assert n == 256
    pix = row3[21:]
    assert pix[7 * 3:7 * 3 + 3] == b"\x00\x00\xff"   # BGR: red lands in the last byte
    assert len(row3) == 14 + 7 + 256 * 3


class FakeSock:
    def __init__(self):
        self.sent = []

    def send(self, b):
        self.sent.append(b)

    def close(self):
        pass


def test_sink_sends_all_packets():
    s = FakeSock()
    sink = ColorlightSink(iface="eth0", brightness=0x40, sock=s)
    sink.show(np.zeros((64, 256, 3), dtype=np.uint8))
    assert len(s.sent) == 65
    assert s.sent[-1][14 + 21] == 0x40
