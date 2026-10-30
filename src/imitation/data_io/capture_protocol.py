"""Decode bounded OKFT v1 BGRA frames without opening a capture device.

All header integers are little endian. PTS is an uncalibrated CoreMedia clock;
only the Python reception timestamp is suitable for local action alignment.
"""
from __future__ import annotations

import struct
import time
from typing import BinaryIO

import numpy as np


FRAME_MAGIC = b"OKFT"
FRAME_VERSION = 1
# magic, version, flags, width, height, stride, bytes, PTS ns, PTS epoch,
# native Dispatch uptime ns, sequence. Flag bit 0 marks a numeric PTS.
FRAME_HEADER = struct.Struct("<4sHHIIIIqqQQ")
MAX_FRAME_BYTES = 128 * 1024 * 1024
MAX_DIMENSION = 16_384


def read_exact(stream: BinaryIO, count: int) -> bytearray | None:
    """Read exactly ``count`` bytes; clean EOF returns None, truncation raises.

    The caller validates the count before allocation. A partial frame must not
    be mistaken for a normal end of stream or resynchronized inside its pixels.
    """
    if not 0 < count <= MAX_FRAME_BYTES:
        raise ValueError("invalid bounded read length")
    data = bytearray(count)
    offset = 0
    while offset < count:
        received = stream.readinto(memoryview(data)[offset:])
        if not received:
            if not offset:
                return None
            raise EOFError(f"truncated frame: {offset} of {count} bytes")
        offset += received
    return data


def unpack_header(header: bytes | bytearray) -> dict:
    """Validate a 56-byte OKFT header before trusting payload allocation sizes."""
    if len(header) != FRAME_HEADER.size:
        raise ValueError("invalid timed frame header length")
    magic, version, flags, width, height, stride, size, pts, epoch, callback, seq = FRAME_HEADER.unpack(header)
    if magic != FRAME_MAGIC or version != FRAME_VERSION or flags & ~1:
        raise ValueError("unsupported timed frame magic, version, or flags")
    if (not 0 < width <= MAX_DIMENSION or not 0 < height <= MAX_DIMENSION
            or stride < width * 4 or stride % 4 or size != stride * height
            or size > MAX_FRAME_BYTES or not seq):
        raise ValueError("invalid timed frame dimensions, stride, bytes, or sequence")
    return {"width": width, "height": height, "stride": stride, "payload_size": size,
            "source_t_ns": pts if flags & 1 else None, "source_epoch": epoch,
            "native_callback_ns": callback, "sequence": seq}


def decode_pixels(payload: bytes | bytearray, metadata: dict) -> tuple[np.ndarray, dict]:
    """Return owned BGR uint8 HWC pixels and lossless crop geometry.

    Alpha >= 254 defines opaque content. Crop only an almost full-size opaque
    bounding rectangle (at least 90% of each dimension), matching the existing
    native capture policy. Small/fading regions remain full size. No resize or
    black-pixel trimming is performed; crop coordinates are source-pixel xywh.
    """
    width, height = metadata["width"], metadata["height"]
    if len(payload) != metadata["payload_size"]:
        raise ValueError("frame payload length does not match header")
    bgra = np.frombuffer(payload, dtype=np.uint8).reshape(height, metadata["stride"] // 4, 4)[:, :width]
    opaque = bgra[:, :, 3] >= 254
    rows, columns = np.flatnonzero(opaque.any(axis=1)), np.flatnonzero(opaque.any(axis=0))
    x0, y0, x1, y1 = 0, 0, width, height
    if len(rows) and len(columns):
        bounds = int(columns[0]), int(rows[0]), int(columns[-1]) + 1, int(rows[-1]) + 1
        if bounds[2] - bounds[0] >= .9 * width and bounds[3] - bounds[1] >= .9 * height:
            x0, y0, x1, y1 = bounds
    image = bgra[y0:y1, x0:x1, :3].copy()
    geometry = {"source_size_wh": [width, height], "crop_xywh": [x0, y0, x1 - x0, y1 - y0],
                "resize": None, "pixel_format": "BGR", "alpha_threshold": 254}
    return image, geometry


def read_timed_frame(stream: BinaryIO) -> dict | None:
    """Read one frame and stamp when its complete payload becomes available.

    Returned ``t_ns == received_ns`` uses ``time.monotonic_ns`` in nanoseconds;
    it is a reception time, not exposure time. ``source_t_ns`` is optional PTS
    with its own epoch and explicitly uncalibrated clock. EOF before a header
    returns None; malformed headers and incomplete payloads raise immediately.
    """
    header = read_exact(stream, FRAME_HEADER.size)
    if header is None:
        return None
    metadata = unpack_header(header)
    payload = read_exact(stream, metadata["payload_size"])
    if payload is None:
        raise EOFError("timed frame payload missing")
    received_ns = time.monotonic_ns()
    image, geometry = decode_pixels(payload, metadata)
    return {"image": image, "t_ns": received_ns, "received_ns": received_ns,
            "source_t_ns": metadata["source_t_ns"], "source_epoch": metadata["source_epoch"],
            "sequence": metadata["sequence"], "clock": "python.time.monotonic_ns",
            "source_clock": "CMSampleBuffer.presentationTimeStamp (uncalibrated)",
            "native_callback_ns": metadata["native_callback_ns"],
            "native_callback_clock": "DispatchTime.uptimeNanoseconds (uncalibrated)",
            "protocol": "OKFT/1", "geometry": geometry}
