#!/usr/bin/env python3
from __future__ import annotations

import struct
from dataclasses import dataclass
from pathlib import Path
from typing import Any


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
    # Extra reader-side metadata. These are intentionally optional so older
    # callers that only use the original fields keep working.
    mipmap_count_source: str | None = None
    subsampling: int | None = None
    animation_frame_count: int | None = None


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


def _u32_at(data: bytes, off: int) -> int | None:
    if 0 <= off and off + 4 <= len(data):
        return struct.unpack_from("<I", data, off)[0]
    return None


def _i32_at(data: bytes, off: int) -> int | None:
    if 0 <= off and off + 4 <= len(data):
        return struct.unpack_from("<i", data, off)[0]
    return None


def _valid_rsb_name(raw: bytes) -> bool:
    if not raw.endswith(b"\x00"):
        return False
    try:
        name = raw[:-1].decode("ascii")
    except UnicodeDecodeError:
        return False
    return name.lower().endswith(".rsb") and all(32 <= ord(c) <= 126 for c in name)


def _looks_like_surface_id(value: int | None) -> bool:
    # RSBEditor's known surface list is -1 or 0..27. The writer accepts any
    # signed int32, but this stricter check is useful only when validating an
    # inferred footer/mipmap split.
    return value == -1 or (value is not None and 0 <= value <= 0x1B)


def _parse_damage_surface_tail(data: bytes, off: int, *, require_end: bool = False) -> dict[str, Any] | None:
    """
    Parse the explicit damage/surface tail used by current writer output:
      disabled: 00 <int32 surface>
      enabled:  01 <uint32 name_len> <name NUL> <int32 surface>

    The parser is intentionally local to rsb_format.py so mipmap splitting does
    not need to import rsb_footer.py and create a circular dependency.
    """
    enabled = _byte_at(data, off)
    if enabled is None:
        return None

    if enabled == 0:
        end = off + 5
        if end > len(data) or (require_end and end != len(data)):
            return None
        surface = _i32_at(data, off + 1)
        if not _looks_like_surface_id(surface):
            return None
        return {"enabled": False, "surface": surface, "end": end}

    if enabled == 1:
        n = _u32_at(data, off + 1)
        if n is None or n < 5 or n > 260:
            return None
        string_start = off + 5
        string_end = string_start + n
        end = string_end + 4
        if end > len(data) or (require_end and end != len(data)):
            return None
        if not _valid_rsb_name(data[string_start:string_end]):
            return None
        surface = _i32_at(data, string_end)
        if not _looks_like_surface_id(surface):
            return None
        return {"enabled": True, "surface": surface, "end": end}

    return None


def _parse_animation_tail_metadata(data: bytes, version: int | None) -> dict[str, Any] | None:
    """
    Parse the canonical animation variable tail shape used by the writer:
      footer+0x31: <uint32 frame_count>
      repeated:    <uint32 name_len> <name NUL>
      then:        <uint32 mipmap_count> <uint32 subsampling>
      then:        damage/surface tail

    A zero-frame tail is ambiguous with the non-animation fixed layout, so this
    helper only returns a match when at least one validated .rsb frame exists.
    """
    shift = _footer_layout_shift(version)
    start = 0x31 + shift
    frame_count = _u32_at(data, start)
    if frame_count is None or frame_count <= 0 or frame_count > 128:
        return None

    frames: list[tuple[int, int, str]] = []
    off = start + 4
    for _ in range(frame_count):
        n = _u32_at(data, off)
        if n is None or n < 5 or n > 260:
            return None
        string_start = off + 4
        string_end = string_start + n
        if string_end > len(data):
            return None
        raw = data[string_start:string_end]
        if not _valid_rsb_name(raw):
            return None
        frames.append((off, n, raw[:-1].decode("ascii")))
        off = string_end

    mipmap_count_off = off
    subsampling_off = off + 4
    mipmap_count = _u32_at(data, mipmap_count_off)
    subsampling = _u32_at(data, subsampling_off)
    if mipmap_count is None or subsampling is None:
        return None
    if mipmap_count > 255 or subsampling > 255:
        return None

    damage_tail_off = off + 8
    # This check works even before mipmaps are peeled off because the damage
    # tail begins immediately after the two uint32s; any mipmap payload follows
    # after that tail.
    if _byte_at(data, damage_tail_off) not in (0, 1):
        return None

    return {
        "start": start,
        "frame_count": frame_count,
        "frames": frames,
        "mipmap_count_off": mipmap_count_off,
        "mipmap_count": mipmap_count,
        "subsampling_off": subsampling_off,
        "subsampling": subsampling,
        "damage_tail_off": damage_tail_off,
    }


def _read_footer_metadata_from_trailer(h: RSBHeader, trailer: bytes) -> dict[str, Any]:
    """Return the best-known mipmap/subsampling metadata source."""
    shift = _footer_layout_shift(h.version)
    tiled_byte = _byte_at(trailer, 0x09 + shift)
    tiled = None if tiled_byte is None else bool(tiled_byte)

    anim = _parse_animation_tail_metadata(trailer, h.version)
    if anim is not None:
        return {
            "mipmap_count": int(anim["mipmap_count"]),
            "mipmap_count_source": f"animation tail uint32 @ footer+0x{anim['mipmap_count_off']:X}",
            "subsampling": int(anim["subsampling"]),
            "tiled": tiled,
            "animation_frame_count": int(anim["frame_count"]),
            "animation_meta": anim,
        }

    fixed_count_off = 0x35 + shift
    fixed_subsampling_off = 0x39 + shift
    fixed_count = _byte_at(trailer, fixed_count_off)
    fixed_subsampling = _byte_at(trailer, fixed_subsampling_off)
    return {
        "mipmap_count": int(fixed_count or 0),
        "mipmap_count_source": f"fixed byte @ footer+0x{fixed_count_off:X}" if fixed_count is not None else None,
        "subsampling": fixed_subsampling,
        "tiled": tiled,
        "animation_frame_count": None,
        "animation_meta": None,
    }


def _find_early_8bim_marker(data: bytes, *, search_limit: int = 64) -> int | None:
    """Return offset of an early Adobe/Photoshop '8BIM' marker in trailer data."""
    if not data:
        return None
    off = data[:max(0, min(len(data), search_limit))].find(b"8BIM")
    return None if off < 0 else off


def split_footer_and_mipmaps(h: RSBHeader, trailer: bytes) -> tuple[bytes, bytes, int, bool | None, str | None, int | None, int | None]:
    """
    Split post-base-image bytes into footer metadata and optional mipmap payloads.

    Current writer/RSBEditor-compatible layouts:
      non-animation:
        footer+0x35 = mipmap count byte
        footer+0x39 = subsampling byte
      animation with frame records:
        footer+0x31 = uint32 frame_count
        frame records follow
        uint32 mipmap_count and uint32 subsampling follow the frame records

    Mipmap payloads are appended after the complete footer metadata/tail. This
    function first discovers the correct count source, then peels the generated
    mipmap payload bytes off the end of the trailer.
    """
    shift = _footer_layout_shift(h.version)

    # Some official textures, especially plain RGB565 object textures, can have
    # opaque Photoshop/Adobe resource data after the base image payload. Do not
    # read ASCII "8BIM" bytes as RSB flags/mipmap metadata. Keep the bytes in
    # footer/trailer for preservation/inspection, but expose safe defaults.
    marker_off = _find_early_8bim_marker(trailer)
    if marker_off is not None:
        return (
            trailer,
            b"",
            0,
            False,
            f"opaque 8BIM/Photoshop trailer @ footer+0x{marker_off:X}; suppressed",
            0,
            None,
        )

    mip_enabled = _byte_at(trailer, 0x06 + shift)
    meta = _read_footer_metadata_from_trailer(h, trailer)
    mip_count = meta["mipmap_count"]
    tiled = meta["tiled"]
    source = meta["mipmap_count_source"]
    subsampling = meta["subsampling"]
    anim_frame_count = meta["animation_frame_count"]

    if mip_enabled != 1 or mip_count <= 0:
        return trailer, b"", 0, tiled, source, subsampling, anim_frame_count

    sizes = expected_mipmap_sizes(h, mip_count)
    if sizes is None:
        return trailer, b"", 0, tiled, source, subsampling, anim_frame_count

    mip_total = sum(n for _, _, n in sizes)
    if mip_total <= 0 or mip_total > len(trailer):
        return trailer, b"", 0, tiled, source, subsampling, anim_frame_count

    footer_len = len(trailer) - mip_total
    if footer_len <= 0:
        return trailer, b"", 0, tiled, source, subsampling, anim_frame_count

    footer_candidate = trailer[:footer_len]

    # Sanity-check that the count source still exists after the split. For an
    # animation tail, also verify the damage/surface tail reaches exactly to the
    # inferred footer boundary; this catches false positives from random pixels.
    anim_meta = meta["animation_meta"]
    if anim_meta is not None:
        anim2 = _parse_animation_tail_metadata(footer_candidate, h.version)
        if anim2 is None or int(anim2["mipmap_count"]) != mip_count:
            return trailer, b"", 0, tiled, source, subsampling, anim_frame_count
        if _parse_damage_surface_tail(footer_candidate, int(anim2["damage_tail_off"]), require_end=True) is None:
            return trailer, b"", 0, tiled, source, subsampling, anim_frame_count
    else:
        fixed_count_off = 0x35 + shift
        if footer_len <= fixed_count_off:
            return trailer, b"", 0, tiled, source, subsampling, anim_frame_count

    return footer_candidate, trailer[footer_len:], mip_count, tiled, source, subsampling, anim_frame_count


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
        mipmap_count_source = None
        subsampling = None
        animation_frame_count = None
    else:
        payload_end = header.payload_start + payload_size
        trailer = data[payload_end:] if payload_end <= len(data) else b""
        (
            footer,
            mipmap_data,
            mipmap_count,
            tiled,
            mipmap_count_source,
            subsampling,
            animation_frame_count,
        ) = split_footer_and_mipmaps(header, trailer)

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
        mipmap_count_source=mipmap_count_source,
        subsampling=subsampling,
        animation_frame_count=animation_frame_count,
    )
