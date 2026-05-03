#!/usr/bin/env python3
from __future__ import annotations

import re
import struct

from rsb_format import u32


GAME_FLAGS = [
    (0x01, "gunshot transparency"),
    (0x02, "grenade transparency"),
    (0x04, "LOS transparent"),
    (0x08, "foliage"),
    (0x10, "water"),
]


SURFACE_NAMES = {
    -1: "none",
    0: "Carpet",
    1: "Concrete",
    2: "Wood",
    3: "Metal",
    4: "Asphalt",
    5: "Sand",
    6: "Low Grass",
    7: "High Garass",
    8: "Puddle",
    9: "Water",
    10: "Drywall",
    11: "Thin Metal",
    12: "Thick Metal",
    13: "Metal Gas Tank",
    14: "Steam Pipe",
    15: "Electrical Panel",
    16: "Snow",
    17: "Safety Glass",
    18: "Bullet Resistant Glass",
    19: "Ice",
    20: "Mud",
    21: "Glass",
    22: "Foliage",
    23: "Gravel",
    24: "Glass Shards",
    25: "Creaky Wood",
    26: "Deep Sand",
    27: "Baked Clay",
    
    # 27 - 0x1B: "last known RSBEditor surface entry",
}


BLEND_FUNCTION_NAMES_SRC = {
    0: "Zero",
    1: "One",
    2: "Source Alpha",
    3: "Inverse Source Alpha",
    4: "Source Colour",
    5: "Inverse Source Colour",
    6: "Destination Colour",
    7: "Inverse Destination Colour",
    8: "Both Source Alpha",
    9: "Both Inverse Source Alpha",
}

BLEND_FUNCTION_NAMES_DST = {
    0: "Zero",
    1: "One",
    2: "Source Alpha",
    3: "Inverse Source Alpha",
    4: "Source Colour",
    5: "Inverse Source Colour",
    6: "Destination Colour",
    7: "Inverse Destination Colour",
    8: "Both Source Alpha",
    9: "Both Inverse Source Alpha",
}

ALPHA_TEST_FUNCTION_NAMES = {
    0: "Never",
    1: "Less",
    2: "Equal",
    3: "Less/Equal",
    4: "Greater",
    5: "Not Equal",
    6: "Greater/Equal",
    7: "Always",
}


SCROLL_MODE_NAMES = {
    # footer+0x08 appears to be the master scrolling enabled byte.
    0: "disabled",
    1: "enabled",
}


SCROLL_TYPE_NAMES = {
    # footer+0x1D is currently mapped from controlled RSBEditor edits.
    # 0 was seen with horizontal/vertical scrolling.
    # 1 was seen with rotate scrolling.
    0: "horizontal/vertical",
    1: "rotate",
}


SUBSAMPLING_NAMES = {
    # RSBEditor appears to store this as a zero-based enum.
    0: "One",
    1: "Two",
    2: "Three",
    3: "Never"
}


def footer_layout_shift(version: int | None) -> int:
    """
    Known footer field offsets appear one byte earlier in v6 examples than in
    v8/v9 examples. Keep the old v8/v9 offsets as canonical and apply this
    signed adjustment for older layouts.
    """
    if version is not None and version <= 6:
        return -1
    return 0


def shifted(base_off: int, version: int | None) -> int:
    return base_off + footer_layout_shift(version)


def byte_at(footer: bytes, off: int) -> int | None:
    if 0 <= off < len(footer):
        return footer[off]
    return None


def u32_at(footer: bytes, off: int) -> int | None:
    if 0 <= off and off + 4 <= len(footer):
        return struct.unpack_from("<I", footer, off)[0]
    return None


def f32_at(footer: bytes, off: int) -> float | None:
    if 0 <= off and off + 4 <= len(footer):
        return struct.unpack_from("<f", footer, off)[0]
    return None


def fmt_byte(v: int | None) -> str:
    return "unavailable" if v is None else f"0x{v:02X}"


def fmt_off(off: int) -> str:
    return f"footer+0x{off:X}"


def scan_length_prefixed_strings(footer: bytes) -> list[tuple[int, int, str]]:
    found: list[tuple[int, int, str]] = []
    for off in range(0, max(0, len(footer) - 4)):
        n = u32(footer, off)
        if 1 <= n <= 260 and off + 4 + n <= len(footer):
            raw = footer[off + 4:off + 4 + n]
            if raw.endswith(b"\x00"):
                try:
                    s = raw[:-1].decode("ascii")
                except UnicodeDecodeError:
                    continue
                if s.lower().endswith(".rsb") and all(32 <= ord(c) <= 126 for c in s):
                    found.append((off, n, s))
    return found


def scan_plain_rsb_strings(data: bytes, base: int = 0) -> list[tuple[int, str]]:
    found: list[tuple[int, str]] = []
    pattern = re.compile(rb"[A-Za-z0-9_ ./\\-]+\.rsb\x00", re.IGNORECASE)
    for m in pattern.finditer(data):
        try:
            s = m.group(0)[:-1].decode("ascii")
        except UnicodeDecodeError:
            continue
        found.append((base + m.start(), s))
    return found


def _looks_like_surface_id(raw: bytes) -> bool:
    """Return True if raw looks like the final signed int32 surface/material id."""
    if len(raw) != 4:
        return False

    sid = struct.unpack("<i", raw)[0]

    # Known controlled samples:
    #   -1 / FF FF FF FF = none
    #    5              = sand
    #    0x1B           = last known RSBEditor surface entry
    #
    # Treat 0..0x1B as the currently mapped RSBEditor surface range. This
    # prevents a valid surface id after a damage texture filename being
    # mistaken for a missing FF FF FF FF terminator.
    return sid == -1 or 0 <= sid <= 0x1B


def find_damage_texture_record(footer: bytes) -> tuple[int, str] | None:
    """
    Look for likely damage texture record:

        uint8  enabled = 1
        uint32 string_length
        char   filename[string_length]  # includes NUL
        int32  following value

    In simple/no-surface cases the following value is often FF FF FF FF
    (-1 / surface none). If a surface/material is selected, those same four
    bytes can instead be a valid final surface id such as 05 00 00 00.

    Returns:
        (footer_offset, filename)
    """
    for off in range(0, max(0, len(footer) - 9)):
        enabled = footer[off]
        if enabled != 1:
            continue

        try:
            n = struct.unpack_from("<I", footer, off + 1)[0]
        except struct.error:
            continue

        string_start = off + 5
        string_end = string_start + n
        following_start = string_end
        following_end = following_start + 4

        if n < 5 or n > 260:
            continue
        if following_end > len(footer):
            continue

        raw = footer[string_start:string_end]
        following = footer[following_start:following_end]

        if not raw.endswith(b"\x00"):
            continue

        try:
            name = raw[:-1].decode("ascii")
        except UnicodeDecodeError:
            continue

        if not name.lower().endswith(".rsb"):
            continue

        # Old logic required FF FF FF FF here. That fails when the selected
        # surface id is stored immediately after the damage texture string.
        # Only accept non-FF values when they are exactly the footer tail,
        # where parse_surface_id() expects the surface/material id to live.
        if following == b"\xFF\xFF\xFF\xFF":
            return off, name
        if following_end == len(footer) and _looks_like_surface_id(following):
            return off, name

    return None

def parse_surface_id(footer: bytes) -> tuple[int, str] | None:
    """Parse the final signed int32 surface/material id."""
    if len(footer) < 4:
        return None
    sid = struct.unpack_from("<i", footer, len(footer) - 4)[0]
    return sid, SURFACE_NAMES.get(sid, "unknown surface index")


def find_animation_frame_records(footer: bytes, damage_record: tuple[int, str] | None = None) -> list[tuple[int, int, str]]:
    """Find likely length-prefixed animation frame .rsb references, excluding damage texture if found."""
    records = scan_length_prefixed_strings(footer)
    if not damage_record:
        return records
    damage_off, damage_name = damage_record
    damage_length_off = damage_off + 1
    return [r for r in records if not (r[0] == damage_length_off and r[2] == damage_name)]


def describe_alpha_blend(footer: bytes, version: int | None = None) -> list[str]:
    """
    Tentative alpha blend mapping, based on controlled RSBEditor edits:

        canonical v8/v9 footer+0x04 = alpha blend enabled
        canonical v8/v9 footer+0x10 = source blend function/index
        canonical v8/v9 footer+0x14 = destination blend function/index

    v6 examples appear shifted one byte earlier.
    """
    lines: list[str] = []
    enabled_off = shifted(0x04, version)
    src_off = shifted(0x10, version)
    dst_off = shifted(0x14, version)

    enabled = byte_at(footer, enabled_off)
    src = u32_at(footer, src_off)
    dst = u32_at(footer, dst_off)

    state = "unknown" if enabled is None else ("enabled" if enabled else "disabled")
    lines.append(f"{fmt_off(enabled_off)} alpha blend enabled byte:  {fmt_byte(enabled)} ({state})")

    if src is None:
        lines.append(f"{fmt_off(src_off)} source blend function:    unavailable")
    else:
        lines.append(f"{fmt_off(src_off)} source blend function:    {src} ({BLEND_FUNCTION_NAMES_SRC.get(src, 'unknown blend function')})")

    if dst is None:
        lines.append(f"{fmt_off(dst_off)} destination blend function: unavailable")
    else:
        lines.append(f"{fmt_off(dst_off)} destination blend function: {dst} ({BLEND_FUNCTION_NAMES_DST.get(dst, 'unknown blend function')})")

    return lines


def describe_alpha_test(footer: bytes, version: int | None = None) -> list[str]:
    """
    Tentative alpha test mapping. This is separate from alpha blending; an RSB
    can plausibly use alpha blend, alpha test, both, or neither.
    """
    lines: list[str] = []
    enabled_off = shifted(0x05, version)
    compare_off = shifted(0x18, version)
    reference_off = shifted(0x1C, version)

    enabled = byte_at(footer, enabled_off)
    compare = u32_at(footer, compare_off)
    reference = byte_at(footer, reference_off)

    state = "unknown" if enabled is None else ("enabled" if enabled else "disabled")
    lines.append(f"{fmt_off(enabled_off)} alpha test enabled byte:   {fmt_byte(enabled)} ({state})")

    if compare is None:
        lines.append(f"{fmt_off(compare_off)} alpha test compare func:  unavailable")
    else:
        lines.append(f"{fmt_off(compare_off)} alpha test compare func:  {compare} ({ALPHA_TEST_FUNCTION_NAMES.get(compare, 'unknown compare function')})")

    if reference is None:
        lines.append(f"{fmt_off(reference_off)} alpha test reference:     unavailable")
    else:
        lines.append(f"{fmt_off(reference_off)} alpha test reference:     {reference}")

    return lines


def describe_mipmap_fields(footer: bytes, version: int | None = None) -> list[str]:
    """
    Mipmap/tiled footer mapping, based on controlled RSBEditor edits:

        canonical v8/v9 footer+0x06 = mipmaps enabled byte
        canonical v8/v9 footer+0x09 = tiled enabled byte
        canonical v8/v9 footer+0x35 = mipmap count

    Generated mipmap payloads appear after the normal footer metadata.
    v6 examples, if applicable, are expected to use the same -1 byte shift
    as other footer fields until proven otherwise.
    """
    lines: list[str] = []
    enabled_off = shifted(0x06, version)
    tiled_off = shifted(0x09, version)
    count_off = shifted(0x35, version)

    enabled = byte_at(footer, enabled_off)
    tiled = byte_at(footer, tiled_off)
    count = byte_at(footer, count_off)

    enabled_state = "unknown" if enabled is None else ("enabled" if enabled else "disabled")
    tiled_state = "unknown" if tiled is None else ("enabled" if tiled else "disabled")

    lines.append(f"{fmt_off(enabled_off)} mipmaps enabled byte: {fmt_byte(enabled)} ({enabled_state})")
    lines.append(f"{fmt_off(tiled_off)} tiled enabled byte:   {fmt_byte(tiled)} ({tiled_state})")
    if count is None:
        lines.append(f"{fmt_off(count_off)} mipmap count byte:    unavailable")
    else:
        lines.append(f"{fmt_off(count_off)} mipmap count byte:    {count}")

    return lines


def describe_scrolling(footer: bytes, version: int | None = None) -> list[str]:
    """
    Tentative scrolling mapping, based on controlled RSBEditor edits:

        canonical v8/v9 footer+0x08 = scrolling enabled byte
        canonical v8/v9 footer+0x1D = scrolling type/function
        canonical v8/v9 footer+0x21 = horizontal/primary/rotation rate float32
        canonical v8/v9 footer+0x25 = vertical scroll rate float32

    Controlled samples so far:
      - no scrolling:          +0x08=0, +0x1D=0, rates 0/0
      - horizontal/vertical:   +0x08=1, +0x1D=0, rates 25/100
      - rotate, 62 deg/sec:    +0x08=1, +0x1D=1, primary rate 62

    For rotate, the +0x25 vertical-rate field may be ignored/stale by the
    editor/engine; in the current sample it retained 100.0 from a previous
    horizontal/vertical setting. v6 examples appear shifted one byte earlier.
    """
    lines: list[str] = []
    enabled_off = shifted(0x08, version)
    type_off = shifted(0x1D, version)
    primary_rate_off = shifted(0x21, version)
    secondary_rate_off = shifted(0x25, version)

    enabled = byte_at(footer, enabled_off)
    scroll_type = byte_at(footer, type_off)
    primary_rate = f32_at(footer, primary_rate_off)
    secondary_rate = f32_at(footer, secondary_rate_off)

    if enabled is None:
        lines.append(f"{fmt_off(enabled_off)} scrolling enabled byte: unavailable")
    else:
        lines.append(
            f"{fmt_off(enabled_off)} scrolling enabled byte: 0x{enabled:02X} "
            f"({SCROLL_MODE_NAMES.get(enabled, 'unknown enabled value')})"
        )

    if scroll_type is None:
        lines.append(f"{fmt_off(type_off)} scrolling type byte:    unavailable")
    else:
        lines.append(
            f"{fmt_off(type_off)} scrolling type byte:    0x{scroll_type:02X} "
            f"({SCROLL_TYPE_NAMES.get(scroll_type, 'unknown scroll type')})"
        )

    type_name = SCROLL_TYPE_NAMES.get(scroll_type, "unknown") if scroll_type is not None else "unknown"
    if type_name == "rotate":
        lines.append(f"{fmt_off(primary_rate_off)} rotation rate f32:      {primary_rate!r} degrees/sec?")
        lines.append(f"{fmt_off(secondary_rate_off)} secondary/unused f32:  {secondary_rate!r}")
    else:
        lines.append(f"{fmt_off(primary_rate_off)} horizontal/primary rate f32: {primary_rate!r}")
        lines.append(f"{fmt_off(secondary_rate_off)} vertical/secondary rate f32: {secondary_rate!r}")

    return lines


def describe_misc_texture_flags(footer: bytes, version: int | None = None) -> list[str]:
    """
    Miscellaneous RSBEditor texture/export flags, based on controlled edits:

        canonical v8/v9 footer+0x0A = compress on load enabled
        canonical v8/v9 footer+0x0B = distortion map enabled
        canonical v8/v9 footer+0x39 = subsampling enum

    Subsampling appears zero-based in current samples:
        0 = One/default
        1 = Two
        2 = Three

    These fields are metadata only in the samples tested; they did not change
    the image payload size. v6/older files use the normal footer offset shift
    until proven otherwise.
    """
    lines: list[str] = []
    compress_off = shifted(0x0A, version)
    distortion_off = shifted(0x0B, version)
    subsampling_off = shifted(0x39, version)

    compress = byte_at(footer, compress_off)
    distortion = byte_at(footer, distortion_off)
    subsampling = byte_at(footer, subsampling_off)

    compress_state = "unknown" if compress is None else ("enabled" if compress else "disabled")
    distortion_state = "unknown" if distortion is None else ("enabled" if distortion else "disabled")

    lines.append(f"{fmt_off(compress_off)} compress on load byte: {fmt_byte(compress)} ({compress_state})")
    lines.append(f"{fmt_off(distortion_off)} distortion map byte:   {fmt_byte(distortion)} ({distortion_state})")
    if subsampling is None:
        lines.append(f"{fmt_off(subsampling_off)} subsampling enum:     unavailable")
    else:
        lines.append(
            f"{fmt_off(subsampling_off)} subsampling enum:     {subsampling} "
            f"({SUBSAMPLING_NAMES.get(subsampling, 'unknown subsampling value')})"
        )

    return lines


def try_v8_footer_map(footer: bytes, version: int | None = None) -> list[str]:
    lines: list[str] = []
    if len(footer) <= 0x1C:
        return ["Footer too small for known metadata guesses."]

    if footer_layout_shift(version):
        lines.append("layout note: using v6/older footer offset adjustment (-1 byte vs v8/v9 canonical offsets)")

    game_off = shifted(0x0C, version)
    game = byte_at(footer, game_off)
    if game is None:
        lines.append(f"{fmt_off(game_off)} game flags: unavailable")
    else:
        enabled = [name for bit, name in GAME_FLAGS if game & bit]
        lines.append(f"{fmt_off(game_off)} game flags: 0x{game:02X}" + (f" ({', '.join(enabled)})" if enabled else " (none known)"))

    lines.append("Alpha blend:")
    lines.extend(f"  {line}" for line in describe_alpha_blend(footer, version))

    lines.append("Alpha test:")
    lines.extend(f"  {line}" for line in describe_alpha_test(footer, version))

    lines.append("Mipmaps / tiling:")
    lines.extend(f"  {line}" for line in describe_mipmap_fields(footer, version))

    lines.append("Scrolling:")
    lines.extend(f"  {line}" for line in describe_scrolling(footer, version))

    lines.append("Misc texture/export flags:")
    lines.extend(f"  {line}" for line in describe_misc_texture_flags(footer, version))

    if len(footer) > 0x30:
        anim_enable_off = shifted(0x07, version)
        anim_type_off = shifted(0x29, version)
        delay_off = shifted(0x2D, version)
        anim_enable = byte_at(footer, anim_enable_off)
        anim_type = byte_at(footer, anim_type_off)
        delay = f32_at(footer, delay_off)
        type_name = "unavailable" if anim_type is None else {1: "oscillate?", 2: "constant?"}.get(anim_type, "unknown/none")
        lines.append(f"{fmt_off(anim_enable_off)} animation-ish enabled byte: {fmt_byte(anim_enable)}")
        lines.append(f"{fmt_off(anim_type_off)} animation type-ish byte:    {fmt_byte(anim_type)} ({type_name})")
        lines.append(f"{fmt_off(delay_off)} float32 delay-ish seconds:  {delay!r}")

    return lines
