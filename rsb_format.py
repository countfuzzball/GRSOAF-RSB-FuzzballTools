#!/usr/bin/env python3
from __future__ import annotations

import struct
from dataclasses import dataclass
from pathlib import Path


class RSBError(Exception):
    pass


@dataclass(frozen=True)
class RSBHeader:
    version: int
    width: int
    height: int
    contains_palette: int
    bits_red: int
    bits_green: int
    bits_blue: int
    bits_alpha: int
    bit_depth: int
    dxt_type: int | None
    payload_start: int
    format_name: str


@dataclass(frozen=True)
class RSBFile:
    path: Path
    data: bytes
    header: RSBHeader
    payload_size: int | None
    payload_end: int | None
    footer: bytes
    mipmap_data: bytes = b""
    mipmap_count: int = 0
    tiled: bool | None = None


def u32(data: bytes, off: int) -> int:
    return struct.unpack_from("<I", data, off)[0]


def i32(data: bytes, off: int) -> int:
    return struct.unpack_from("<i", data, off)[0]


def hexdump(data: bytes, base: int = 0, width: int = 16, max_bytes: int = 256) -> str:
    data = data[:max_bytes]
    lines: list[str] = []
    for i in range(0, len(data), width):
        chunk = data[i:i + width]
        hx = " ".join(f"{b:02X}" for b in chunk)
        asc = "".join(chr(b) if 32 <= b <= 126 else "." for b in chunk)
        lines.append(f"{base+i:08X}  {hx:<{width*3}}  {asc}")
    return "\n".join(lines)


def guess_format(bits_red: int, bits_green: int, bits_blue: int, bits_alpha: int, dxt_type: int | None) -> str:
    if dxt_type is not None and dxt_type >= 0:
        return {
            0: "DXT1",
            1: "DXT2?",
            2: "DXT3?",
            3: "DXT4?",
            4: "DXT5",
            5: "DXT5?",
        }.get(dxt_type, f"DXT({dxt_type})")

    t = (bits_red, bits_green, bits_blue, bits_alpha)
    return {
        (5, 6, 5, 0): "RGB565",
        (5, 5, 5, 1): "ARGB1555",
        (4, 4, 4, 4): "ARGB4444",
        (8, 8, 8, 8): "ARGB8888",
        (8, 8, 8, 0): "RGB888",
    }.get(t, f"raw{t}")


def parse_header(data: bytes) -> RSBHeader:
    if len(data) < 12:
        raise RSBError("file too small for RSB header")

    off = 0
    version = u32(data, off); off += 4
    width = u32(data, off); off += 4
    height = u32(data, off); off += 4

    contains_palette = 0
    bits_red = bits_green = bits_blue = bits_alpha = 0
    dxt_type = None

    if version == 0:
        contains_palette = u32(data, off); off += 4
        if contains_palette == 0:
            bits_red = u32(data, off); off += 4
            bits_green = u32(data, off); off += 4
            bits_blue = u32(data, off); off += 4
            bits_alpha = u32(data, off); off += 4
    else:
        if version > 7:
            off += 7
        bits_red = u32(data, off); off += 4
        bits_green = u32(data, off); off += 4
        bits_blue = u32(data, off); off += 4
        bits_alpha = u32(data, off); off += 4

        if version >= 9:
            off += 4
            dxt_type = i32(data, off); off += 4

    total_bits = bits_red + bits_green + bits_blue + bits_alpha
    bit_depth = total_bits // 8 if total_bits and total_bits % 8 == 0 else 0
    fmt = guess_format(bits_red, bits_green, bits_blue, bits_alpha, dxt_type)

    return RSBHeader(
        version=version,
        width=width,
        height=height,
        contains_palette=contains_palette,
        bits_red=bits_red,
        bits_green=bits_green,
        bits_blue=bits_blue,
        bits_alpha=bits_alpha,
        bit_depth=bit_depth,
        dxt_type=dxt_type,
        payload_start=off,
        format_name=fmt,
    )


def expected_payload_size(h: RSBHeader) -> int | None:
    return expected_image_size(h, h.width, h.height)


def expected_image_size(h: RSBHeader, width: int, height: int) -> int | None:
    pixels = width * height

    if h.dxt_type is not None and h.dxt_type >= 0:
        # Keep the original simple sizing model for now. RSB DXT variants may
        # need block-accurate sizing once more compressed mipmap samples exist.
        if h.dxt_type == 0:
            return pixels // 2  # DXT1 approximation from public Noesis reader style.
        return pixels           # DXT3/DXT5-ish approximation.

    if h.contains_palette == 1:
        return None

    if h.bit_depth:
        return pixels * h.bit_depth

    return None


def expected_mipmap_sizes(h: RSBHeader, count: int) -> list[tuple[int, int, int]] | None:
    """Return [(width, height, byte_size), ...] for generated mip levels."""
    if count <= 0:
        return []

    sizes: list[tuple[int, int, int]] = []
    w, ht = h.width, h.height
    for _ in range(count):
        w = max(1, w // 2)
        ht = max(1, ht // 2)
        n = expected_image_size(h, w, ht)
        if n is None:
            return None
        sizes.append((w, ht, n))
    return sizes


def _footer_layout_shift(version: int | None) -> int:
    return -1 if version is not None and version <= 6 else 0


def _byte_at(data: bytes, off: int) -> int | None:
    if 0 <= off < len(data):
        return data[off]
    return None


def split_footer_and_mipmaps(h: RSBHeader, trailer: bytes) -> tuple[bytes, bytes, int, bool | None]:
    """
    Split post-base-image bytes into footer metadata and optional mipmap payloads.

    Controlled RSBEditor samples show:
      canonical footer+0x06 = mipmaps enabled byte
      canonical footer+0x09 = tiled enabled byte
      canonical footer+0x35 = mipmap count

    When mipmaps are present, the layout is:
      [header][base image][footer metadata][mipmap payloads]

    This function uses the mipmap count and expected generated mip sizes to
    peel mipmap bytes off the end of the trailer, leaving footer metadata in
    RSBFile.footer. If the fields do not look sane, the whole trailer remains
    the footer.
    """
    shift = _footer_layout_shift(h.version)
    mip_enabled = _byte_at(trailer, 0x06 + shift)
    tiled_byte = _byte_at(trailer, 0x09 + shift)
    mip_count = _byte_at(trailer, 0x35 + shift)
    tiled = None if tiled_byte is None else bool(tiled_byte)

    if mip_enabled != 1 or mip_count is None or mip_count <= 0:
        return trailer, b"", 0, tiled

    sizes = expected_mipmap_sizes(h, mip_count)
    if sizes is None:
        return trailer, b"", 0, tiled

    mip_total = sum(n for _, _, n in sizes)
    if mip_total <= 0 or mip_total > len(trailer):
        return trailer, b"", 0, tiled

    footer_len = len(trailer) - mip_total

    # Avoid accepting impossible/accidental mip counts. The count field must
    # remain inside the metadata part after the split.
    if footer_len <= 0x35 + shift:
        return trailer, b"", 0, tiled

    return trailer[:footer_len], trailer[footer_len:], mip_count, tiled


def load_rsb(path: str | Path) -> RSBFile:
    path = Path(path)
    data = path.read_bytes()
    header = parse_header(data)
    payload_size = expected_payload_size(header)

    if payload_size is None:
        payload_end = None
        footer = b""
        mipmap_data = b""
        mipmap_count = 0
        tiled = None
    else:
        payload_end = header.payload_start + payload_size
        trailer = data[payload_end:] if payload_end <= len(data) else b""
        footer, mipmap_data, mipmap_count, tiled = split_footer_and_mipmaps(header, trailer)

    return RSBFile(
        path=path,
        data=data,
        header=header,
        payload_size=payload_size,
        payload_end=payload_end,
        footer=footer,
        mipmap_data=mipmap_data,
        mipmap_count=mipmap_count,
        tiled=tiled,
    )
