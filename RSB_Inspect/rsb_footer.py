#!/usr/bin/env python3
from __future__ import annotations

import re
import struct
from dataclasses import dataclass
from typing import Any

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
    7: "High Grass",
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
    # 27 / 0x1B: last known RSBEditor surface entry.
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

BLEND_FUNCTION_NAMES_DST = BLEND_FUNCTION_NAMES_SRC

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
    0: "disabled",
    1: "enabled",
}


SCROLL_TYPE_NAMES = {
    0: "horizontal/vertical",
    1: "rotate",
}


SUBSAMPLING_NAMES = {
    0: "One",
    1: "Two",
    2: "Three",
    3: "Never",
}


@dataclass(frozen=True)
class AnimationTail:
    start_off: int
    frame_count: int
    frames: list[tuple[int, int, str]]
    mipmap_count_off: int
    mipmap_count: int
    subsampling_off: int
    subsampling: int
    damage_tail_off: int


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


def i32_at(footer: bytes, off: int) -> int | None:
    if 0 <= off and off + 4 <= len(footer):
        return struct.unpack_from("<i", footer, off)[0]
    return None


def f32_at(footer: bytes, off: int) -> float | None:
    if 0 <= off and off + 4 <= len(footer):
        return struct.unpack_from("<f", footer, off)[0]
    return None


def fmt_byte(v: int | None) -> str:
    return "unavailable" if v is None else f"0x{v:02X}"


def fmt_off(off: int) -> str:
    return f"footer+0x{off:X}"


def _decode_rsb_name(raw: bytes) -> str | None:
    if not raw.endswith(b"\x00"):
        return None
    try:
        s = raw[:-1].decode("ascii")
    except UnicodeDecodeError:
        return None
    if not s.lower().endswith(".rsb"):
        return None
    if not all(32 <= ord(c) <= 126 for c in s):
        return None
    return s


def scan_length_prefixed_strings(footer: bytes) -> list[tuple[int, int, str]]:
    found: list[tuple[int, int, str]] = []
    for off in range(0, max(0, len(footer) - 4)):
        n = u32(footer, off)
        if 1 <= n <= 260 and off + 4 + n <= len(footer):
            s = _decode_rsb_name(footer[off + 4:off + 4 + n])
            if s is not None:
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
    return sid == -1 or 0 <= sid <= 0x1B


def _parse_explicit_damage_surface_tail(footer: bytes, off: int, *, require_end: bool = False) -> tuple[int, str | None] | None:
    """
    Parse writer/RSBEditor-compatible damage/surface tails.

    Returns (end_offset, filename_or_None). Filename is None for disabled damage.
    """
    enabled = byte_at(footer, off)
    if enabled is None:
        return None

    if enabled == 0:
        end = off + 5
        if end > len(footer) or (require_end and end != len(footer)):
            return None
        raw_surface = footer[off + 1:off + 5]
        if not _looks_like_surface_id(raw_surface):
            return None
        return end, None

    if enabled == 1:
        n = u32_at(footer, off + 1)
        if n is None or n < 5 or n > 260:
            return None
        string_start = off + 5
        string_end = string_start + n
        end = string_end + 4
        if end > len(footer) or (require_end and end != len(footer)):
            return None
        name = _decode_rsb_name(footer[string_start:string_end])
        if name is None:
            return None
        raw_surface = footer[string_end:string_end + 4]
        if not _looks_like_surface_id(raw_surface):
            return None
        return end, name

    return None


def parse_animation_tail(footer: bytes, version: int | None = None) -> AnimationTail | None:
    """
    Parse canonical animation records from the newer writer/RSBEditor layout.

    Shape:
      footer+0x31: uint32 frame_count
      repeated:    uint32 name_len, ASCII .rsb filename including NUL
      then:        uint32 mipmap_count, uint32 subsampling
      then:        explicit damage/surface tail

    Zero-frame animation tails are ambiguous with the fixed non-animation layout,
    so this parser only returns a match when one or more frame records validate.
    """
    start = shifted(0x31, version)
    frame_count = u32_at(footer, start)
    if frame_count is None or frame_count <= 0 or frame_count > 128:
        return None

    frames: list[tuple[int, int, str]] = []
    off = start + 4
    for _ in range(frame_count):
        n = u32_at(footer, off)
        if n is None or n < 5 or n > 260:
            return None
        string_start = off + 4
        string_end = string_start + n
        if string_end > len(footer):
            return None
        name = _decode_rsb_name(footer[string_start:string_end])
        if name is None:
            return None
        frames.append((off, n, name))
        off = string_end

    mipmap_count_off = off
    subsampling_off = off + 4
    mipmap_count = u32_at(footer, mipmap_count_off)
    subsampling = u32_at(footer, subsampling_off)
    if mipmap_count is None or subsampling is None:
        return None
    if mipmap_count > 255 or subsampling > 255:
        return None

    damage_tail_off = off + 8
    # When load_rsb has already peeled off mipmap payloads, this tail should
    # reach exactly to the end of the footer. Do not require that here; old or
    # hand-edited files may contain extra bytes and the inspector can still be
    # useful.
    if _parse_explicit_damage_surface_tail(footer, damage_tail_off, require_end=False) is None:
        return None

    return AnimationTail(
        start_off=start,
        frame_count=frame_count,
        frames=frames,
        mipmap_count_off=mipmap_count_off,
        mipmap_count=mipmap_count,
        subsampling_off=subsampling_off,
        subsampling=subsampling,
        damage_tail_off=damage_tail_off,
    )


def find_damage_texture_record(footer: bytes, version: int | None = None) -> tuple[int, str] | None:
    """
    Look for likely damage texture record.

    Prefer the structured damage/surface tail positions first:
      - after the animation variable block, if animation records exist
      - fixed footer+0x3D for non-animation/current writer output

    Fallback scanning is retained for older samples and exploratory files.
    """
    anim = parse_animation_tail(footer, version)
    if anim is not None:
        parsed = _parse_explicit_damage_surface_tail(footer, anim.damage_tail_off, require_end=False)
        if parsed and parsed[1] is not None:
            return anim.damage_tail_off, parsed[1]

    fixed_tail_off = shifted(0x3D, version)
    parsed = _parse_explicit_damage_surface_tail(footer, fixed_tail_off, require_end=False)
    if parsed and parsed[1] is not None:
        return fixed_tail_off, parsed[1]

    for off in range(0, max(0, len(footer) - 9)):
        enabled = footer[off]
        if enabled != 1:
            continue

        n = u32_at(footer, off + 1)
        if n is None or n < 5 or n > 260:
            continue

        string_start = off + 5
        string_end = string_start + n
        following_start = string_end
        following_end = following_start + 4
        if following_end > len(footer):
            continue

        name = _decode_rsb_name(footer[string_start:string_end])
        if name is None:
            continue

        following = footer[following_start:following_end]
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


def find_animation_frame_records(
    footer: bytes,
    damage_record: tuple[int, str] | None = None,
    version: int | None = None,
) -> list[tuple[int, int, str]]:
    """Find likely length-prefixed animation frame .rsb references."""
    anim = parse_animation_tail(footer, version)
    if anim is not None:
        return anim.frames

    records = scan_length_prefixed_strings(footer)
    if not damage_record:
        return records
    damage_off, damage_name = damage_record
    damage_length_off = damage_off + 1
    return [r for r in records if not (r[0] == damage_length_off and r[2] == damage_name)]



def _byte_state(v: int | None) -> str:
    if v is None:
        return "unavailable"
    return "enabled" if v else "disabled"


def _fmt_u32(v: int | None, names: dict[int, str] | None = None) -> str:
    if v is None:
        return "unavailable"
    if names is not None:
        return f"{v} ({names.get(v, 'unknown')})"
    return str(v)


def _fmt_f32(v: float | None) -> str:
    return "unavailable" if v is None else repr(v)


def parse_damage_surface_tail(
    footer: bytes,
    off: int,
    *,
    require_end: bool = False,
) -> dict[str, object] | None:
    """
    Parse the explicit damage/surface tail used by current writer output.

    Disabled:
      uint8  damage_enabled = 0
      int32  surface_id

    Enabled:
      uint8  damage_enabled = 1
      uint32 filename_length
      char   filename[filename_length]  # includes NUL
      int32  surface_id
    """
    parsed = _parse_explicit_damage_surface_tail(footer, off, require_end=require_end)
    if parsed is None:
        return None

    end, filename = parsed
    enabled = byte_at(footer, off)
    surface_off = end - 4
    sid = i32_at(footer, surface_off)
    raw_surface = footer[surface_off:end]

    return {
        "start_off": off,
        "end_off": end,
        "enabled": bool(enabled),
        "filename": filename,
        "surface_off": surface_off,
        "surface_id": sid,
        "surface_name": SURFACE_NAMES.get(sid, "unknown surface index"),
        "surface_raw": raw_surface,
    }


def find_resolved_damage_surface_tail(footer: bytes, version: int | None = None) -> dict[str, object] | None:
    """Return the best-known damage/surface tail based on resolved layout."""
    anim = parse_animation_tail(footer, version)
    if anim is not None:
        parsed = parse_damage_surface_tail(footer, anim.damage_tail_off, require_end=False)
        if parsed is not None:
            return parsed

    fixed_tail_off = shifted(0x3D, version)
    parsed = parse_damage_surface_tail(footer, fixed_tail_off, require_end=False)
    if parsed is not None:
        return parsed

    return None


def _append_byte_line(lines: list[str], footer: bytes, off: int, label: str, *, names: dict[int, str] | None = None, as_enabled: bool = False) -> None:
    value = byte_at(footer, off)
    if value is None:
        lines.append(f"{fmt_off(off)} {label}: unavailable")
        return
    if as_enabled:
        lines.append(f"{fmt_off(off)} {label}: 0x{value:02X} ({_byte_state(value)})")
    elif names is not None:
        lines.append(f"{fmt_off(off)} {label}: 0x{value:02X} ({names.get(value, 'unknown')})")
    else:
        lines.append(f"{fmt_off(off)} {label}: 0x{value:02X}")


def _append_u32_line(lines: list[str], footer: bytes, off: int, label: str, *, names: dict[int, str] | None = None) -> None:
    value = u32_at(footer, off)
    if value is None:
        lines.append(f"{fmt_off(off)} {label}: unavailable")
        return
    if names is not None:
        lines.append(f"{fmt_off(off)} {label}: {value} ({names.get(value, 'unknown')})")
    else:
        lines.append(f"{fmt_off(off)} {label}: {value}")


def _append_f32_line(lines: list[str], footer: bytes, off: int, label: str) -> None:
    lines.append(f"{fmt_off(off)} {label}: {_fmt_f32(f32_at(footer, off))}")



# ---------------------------------------------------------------------------
# Opaque trailer / authoring-resource detection
# ---------------------------------------------------------------------------


def find_8bim_marker(footer: bytes, *, search_limit: int = 64) -> int | None:
    """
    Return the offset of an early Adobe/Photoshop-style '8BIM' marker.

    Some official RGB565/object RSBs contain post-payload authoring cruft rather
    than an RSBEditor-style footer. If the inspector blindly treats those bytes
    as footer fields, ASCII '8BIM' becomes hilarious nonsense like tiled=0x42.
    """
    if not footer:
        return None
    off = footer[:max(0, min(len(footer), search_limit))].find(b"8BIM")
    return None if off < 0 else off


def has_early_8bim_marker(footer: bytes) -> bool:
    return find_8bim_marker(footer) is not None


def describe_8bim_opaque_trailer(footer: bytes, version: int | None = None) -> list[str]:
    """Return a safe/default footer report for an opaque 8BIM trailer."""
    marker_off = find_8bim_marker(footer)
    marker = "footer+0x?" if marker_off is None else fmt_off(marker_off)
    lines = [
        f"opaque trailer note: '8BIM' marker detected at {marker} — probable legacy Photoshop/Adobe resource data.",
        "known RSBEditor-style fields below are shown as disabled/defaults instead of interpreting the raw trailer bytes.",
        "raw trailer is preserved for inspection, but ignored as RSB metadata.",
    ]

    def bline(base: int, label: str, suffix: str = "disabled") -> None:
        lines.append(f"{fmt_off(shifted(base, version))} {label}: 0x00 ({suffix}) [suppressed from 8BIM trailer]")

    def uline(base: int, label: str, name: str | None = None) -> None:
        extra = f" ({name})" if name else ""
        lines.append(f"{fmt_off(shifted(base, version))} {label}: 0{extra} [suppressed from 8BIM trailer]")

    bline(0x04, "alpha blend enabled")
    bline(0x05, "alpha test enabled")
    bline(0x06, "mipmaps enabled")
    bline(0x07, "animation enabled")
    bline(0x08, "scrolling enabled")
    bline(0x09, "tiled enabled")
    bline(0x0A, "compress on load")
    bline(0x0B, "distortion map")
    lines.append(f"{fmt_off(shifted(0x0C, version))} game flags: 0x00 (none known) [suppressed from 8BIM trailer]")
    uline(0x10, "source blend function", "Zero")
    uline(0x14, "destination blend function", "Zero")
    uline(0x18, "alpha test compare function", "Never")
    lines.append(f"{fmt_off(shifted(0x1C, version))} alpha test reference: 0 [suppressed from 8BIM trailer]")
    uline(0x1D, "scrolling type", "horizontal/vertical")
    lines.append(f"{fmt_off(shifted(0x21, version))} horizontal/primary scroll rate f32: 0.0 [suppressed from 8BIM trailer]")
    lines.append(f"{fmt_off(shifted(0x25, version))} vertical/secondary scroll rate f32: 0.0 [suppressed from 8BIM trailer]")
    bline(0x29, "animation type", "disabled")
    lines.append(f"{fmt_off(shifted(0x2D, version))} animation delay f32: 0.0 [suppressed from 8BIM trailer]")
    lines.append(f"{fmt_off(shifted(0x35, version))} mipmap count byte: 0 [suppressed from 8BIM trailer]")
    lines.append(f"{fmt_off(shifted(0x39, version))} subsampling byte: 0 (One) [suppressed from 8BIM trailer]")
    lines.append(f"{fmt_off(shifted(0x3D, version))} damage texture enabled byte: 0x00 (disabled) [suppressed from 8BIM trailer]")

    surface = parse_surface_id(footer)
    if surface is not None:
        sid, surface_name = surface
        raw = footer[-4:].hex(" ")
        lines.append(f"{fmt_off(len(footer) - 4)} final surface-like int32: {sid} ({surface_name}); raw {raw} [reported cautiously]")
    else:
        lines.append("surface int32: unavailable")
    return lines


def describe_footer_linear(footer: bytes, version: int | None = None) -> list[str]:
    """
    Present the resolved footer layout in byte-order.

    This deliberately avoids printing the obsolete fixed mipmap/subsampling
    offsets when animation records have displaced them. For animation files,
    the actual mipmap_count/subsampling values are shown where they really live
    in the variable animation tail.
    """
    lines: list[str] = []
    if len(footer) <= 0x1C:
        return ["Footer too small for known metadata guesses."]

    if has_early_8bim_marker(footer):
        return describe_8bim_opaque_trailer(footer, version)

    if footer_layout_shift(version):
        lines.append("layout note: using v6/older footer offset adjustment (-1 byte vs v8/v9 canonical offsets)")

    # Fixed prefix, in ascending offset order.
    _append_byte_line(lines, footer, shifted(0x04, version), "alpha blend enabled", as_enabled=True)
    _append_byte_line(lines, footer, shifted(0x05, version), "alpha test enabled", as_enabled=True)
    _append_byte_line(lines, footer, shifted(0x06, version), "mipmaps enabled", as_enabled=True)
    _append_byte_line(lines, footer, shifted(0x07, version), "animation enabled", as_enabled=True)
    _append_byte_line(lines, footer, shifted(0x08, version), "scrolling enabled", names=SCROLL_MODE_NAMES)
    _append_byte_line(lines, footer, shifted(0x09, version), "tiled enabled", as_enabled=True)
    _append_byte_line(lines, footer, shifted(0x0A, version), "compress on load", as_enabled=True)
    _append_byte_line(lines, footer, shifted(0x0B, version), "distortion map", as_enabled=True)

    game_off = shifted(0x0C, version)
    game = byte_at(footer, game_off)
    if game is None:
        lines.append(f"{fmt_off(game_off)} game flags: unavailable")
    else:
        enabled = [name for bit, name in GAME_FLAGS if game & bit]
        suffix = f" ({', '.join(enabled)})" if enabled else " (none known)"
        lines.append(f"{fmt_off(game_off)} game flags: 0x{game:02X}{suffix}")

    _append_u32_line(lines, footer, shifted(0x10, version), "source blend function", names=BLEND_FUNCTION_NAMES_SRC)
    _append_u32_line(lines, footer, shifted(0x14, version), "destination blend function", names=BLEND_FUNCTION_NAMES_DST)
    _append_u32_line(lines, footer, shifted(0x18, version), "alpha test compare function", names=ALPHA_TEST_FUNCTION_NAMES)

    ref_off = shifted(0x1C, version)
    ref = byte_at(footer, ref_off)
    lines.append(f"{fmt_off(ref_off)} alpha test reference: {'unavailable' if ref is None else ref}")

    _append_byte_line(lines, footer, shifted(0x1D, version), "scrolling type", names=SCROLL_TYPE_NAMES)
    scroll_type = byte_at(footer, shifted(0x1D, version))
    scroll_type_name = SCROLL_TYPE_NAMES.get(scroll_type, "unknown") if scroll_type is not None else "unknown"
    if scroll_type_name == "rotate":
        _append_f32_line(lines, footer, shifted(0x21, version), "rotation rate f32")
        _append_f32_line(lines, footer, shifted(0x25, version), "secondary/unused f32")
    else:
        _append_f32_line(lines, footer, shifted(0x21, version), "horizontal/primary scroll rate f32")
        _append_f32_line(lines, footer, shifted(0x25, version), "vertical/secondary scroll rate f32")

    _append_byte_line(lines, footer, shifted(0x29, version), "animation type", names={0: "none", 1: "oscillate", 2: "constant"})
    _append_f32_line(lines, footer, shifted(0x2D, version), "animation delay f32")

    # Variable/final part, also in actual file order.
    anim = parse_animation_tail(footer, version)
    if anim is not None:
        lines.append(f"{fmt_off(anim.start_off)} animation frame count uint32: {anim.frame_count}")
        for idx, (len_off, n, name) in enumerate(anim.frames, 1):
            string_off = len_off + 4
            end_off = string_off + n
            lines.append(f"{fmt_off(len_off)} animation frame {idx} length uint32: {n}")
            lines.append(f"{fmt_off(string_off)} animation frame {idx} string: {name!r} (ends before {fmt_off(end_off)})")
        lines.append(f"{fmt_off(anim.mipmap_count_off)} mipmap count uint32: {anim.mipmap_count}")
        lines.append(
            f"{fmt_off(anim.subsampling_off)} subsampling uint32: {anim.subsampling} "
            f"({SUBSAMPLING_NAMES.get(anim.subsampling, 'unknown subsampling value')})"
        )
        damage = parse_damage_surface_tail(footer, anim.damage_tail_off, require_end=False)
    else:
        fixed_count_off = shifted(0x35, version)
        fixed_subsampling_off = shifted(0x39, version)
        _append_byte_line(lines, footer, fixed_count_off, "mipmap count byte")
        subsampling = byte_at(footer, fixed_subsampling_off)
        if subsampling is None:
            lines.append(f"{fmt_off(fixed_subsampling_off)} subsampling byte: unavailable")
        else:
            lines.append(
                f"{fmt_off(fixed_subsampling_off)} subsampling byte: {subsampling} "
                f"({SUBSAMPLING_NAMES.get(subsampling, 'unknown subsampling value')})"
            )
        damage = parse_damage_surface_tail(footer, shifted(0x3D, version), require_end=False)

    if damage is None:
        tail_off = shifted(0x3D, version) if anim is None else anim.damage_tail_off
        lines.append(f"{fmt_off(tail_off)} damage/surface tail: not parsed")
    else:
        start_off = int(damage["start_off"])
        surface_off = int(damage["surface_off"])
        end_off = int(damage["end_off"])
        enabled = bool(damage["enabled"])
        filename = damage["filename"]
        lines.append(f"{fmt_off(start_off)} damage texture enabled byte: 0x{1 if enabled else 0:02X} ({'enabled' if enabled else 'disabled'})")
        if enabled:
            name_len_off = start_off + 1
            name_len = u32_at(footer, name_len_off)
            name_off = start_off + 5
            lines.append(f"{fmt_off(name_len_off)} damage texture length uint32: {name_len}")
            lines.append(f"{fmt_off(name_off)} damage texture string: {filename!r} (ends before {fmt_off(surface_off)})")
        sid = damage["surface_id"]
        surface_name = damage["surface_name"]
        raw = bytes(damage["surface_raw"]).hex(" ")
        lines.append(f"{fmt_off(surface_off)} surface int32: {sid} ({surface_name}); raw {raw}")
        if end_off != len(footer):
            lines.append(f"{fmt_off(end_off)} footer bytes continue after parsed damage/surface tail ({len(footer) - end_off} byte(s))")

    return lines


# ---------------------------------------------------------------------------
# Structured metadata output for tools/GUI callers.
# ---------------------------------------------------------------------------

def _offset_obj(off: int, absolute_footer_start: int | None = None) -> dict[str, Any]:
    obj: dict[str, Any] = {
        "footer_offset": off,
        "footer_offset_hex": f"footer+0x{off:X}",
    }
    if absolute_footer_start is not None:
        obj["absolute_offset"] = absolute_footer_start + off
        obj["absolute_offset_hex"] = f"0x{absolute_footer_start + off:X}"
    return obj


def _byte_field(footer: bytes, off: int, *, names: dict[int, str] | None = None, enabled: bool = False, absolute_footer_start: int | None = None) -> dict[str, Any]:
    value = byte_at(footer, off)
    obj = _offset_obj(off, absolute_footer_start)
    obj["available"] = value is not None
    obj["value"] = value
    obj["value_hex"] = None if value is None else f"0x{value:02X}"
    if enabled:
        obj["enabled"] = None if value is None else bool(value)
    if names is not None:
        obj["name"] = None if value is None else names.get(value, "unknown")
    return obj


def _u32_field(footer: bytes, off: int, *, names: dict[int, str] | None = None, absolute_footer_start: int | None = None) -> dict[str, Any]:
    value = u32_at(footer, off)
    obj = _offset_obj(off, absolute_footer_start)
    obj["available"] = value is not None
    obj["value"] = value
    if names is not None:
        obj["name"] = None if value is None else names.get(value, "unknown")
    return obj


def _i32_field(footer: bytes, off: int, *, names: dict[int, str] | None = None, absolute_footer_start: int | None = None) -> dict[str, Any]:
    value = i32_at(footer, off)
    obj = _offset_obj(off, absolute_footer_start)
    obj["available"] = value is not None
    obj["value"] = value
    if names is not None:
        obj["name"] = None if value is None else names.get(value, "unknown")
    return obj


def _f32_field(footer: bytes, off: int, *, absolute_footer_start: int | None = None) -> dict[str, Any]:
    value = f32_at(footer, off)
    obj = _offset_obj(off, absolute_footer_start)
    obj["available"] = value is not None
    obj["value"] = value
    return obj


def _game_flags_obj(footer: bytes, off: int, absolute_footer_start: int | None = None) -> dict[str, Any]:
    value = byte_at(footer, off)
    obj = _offset_obj(off, absolute_footer_start)
    obj["available"] = value is not None
    obj["value"] = value
    obj["value_hex"] = None if value is None else f"0x{value:02X}"
    obj["enabled_names"] = [] if value is None else [name for bit, name in GAME_FLAGS if value & bit]
    obj["bits"] = {
        name: (None if value is None else bool(value & bit))
        for bit, name in GAME_FLAGS
    }
    return obj


def _frame_obj(idx: int, len_off: int, n: int, name: str, absolute_footer_start: int | None = None) -> dict[str, Any]:
    string_off = len_off + 4
    end_off = string_off + n
    return {
        "index": idx,
        "filename": name,
        "length": n,
        "length_offset": _offset_obj(len_off, absolute_footer_start),
        "string_offset": _offset_obj(string_off, absolute_footer_start),
        "end_offset": _offset_obj(end_off, absolute_footer_start),
    }


def _damage_surface_tail_obj(
    footer: bytes,
    damage: dict[str, object] | None,
    *,
    absolute_footer_start: int | None = None,
) -> dict[str, Any]:
    if damage is None:
        return {"parsed": False}

    start_off = int(damage["start_off"])
    end_off = int(damage["end_off"])
    surface_off = int(damage["surface_off"])
    enabled = bool(damage["enabled"])
    filename = damage["filename"]
    raw_surface = bytes(damage["surface_raw"])
    name_len_off = start_off + 1 if enabled else None
    name_len = u32_at(footer, name_len_off) if name_len_off is not None else None
    name_off = start_off + 5 if enabled else None

    return {
        "parsed": True,
        "start_offset": _offset_obj(start_off, absolute_footer_start),
        "end_offset": _offset_obj(end_off, absolute_footer_start),
        "damage_texture": {
            "enabled": enabled,
            "enabled_byte": _byte_field(footer, start_off, enabled=True, absolute_footer_start=absolute_footer_start),
            "filename": filename,
            "length": name_len,
            "length_offset": None if name_len_off is None else _offset_obj(name_len_off, absolute_footer_start),
            "string_offset": None if name_off is None else _offset_obj(name_off, absolute_footer_start),
        },
        "surface": {
            "value": damage["surface_id"],
            "name": damage["surface_name"],
            "raw_hex": raw_surface.hex(" "),
            "offset": _offset_obj(surface_off, absolute_footer_start),
        },
    }



def _suppressed_byte_field(
    off: int,
    *,
    value: int = 0,
    names: dict[int, str] | None = None,
    enabled: bool = False,
    absolute_footer_start: int | None = None,
) -> dict[str, Any]:
    obj = _offset_obj(off, absolute_footer_start)
    obj.update({
        "available": True,
        "value": value,
        "value_hex": f"0x{value:02X}",
        "suppressed_from_8bim_trailer": True,
    })
    if enabled:
        obj["enabled"] = bool(value)
    if names is not None:
        obj["name"] = names.get(value, "unknown")
    return obj


def _suppressed_u32_field(
    off: int,
    *,
    value: int = 0,
    names: dict[int, str] | None = None,
    absolute_footer_start: int | None = None,
) -> dict[str, Any]:
    obj = _offset_obj(off, absolute_footer_start)
    obj.update({
        "available": True,
        "value": value,
        "suppressed_from_8bim_trailer": True,
    })
    if names is not None:
        obj["name"] = names.get(value, "unknown")
    return obj


def _suppressed_f32_field(off: int, *, value: float = 0.0, absolute_footer_start: int | None = None) -> dict[str, Any]:
    obj = _offset_obj(off, absolute_footer_start)
    obj.update({
        "available": True,
        "value": value,
        "suppressed_from_8bim_trailer": True,
    })
    return obj


def _suppressed_game_flags_obj(off: int, absolute_footer_start: int | None = None) -> dict[str, Any]:
    obj = _offset_obj(off, absolute_footer_start)
    obj.update({
        "available": True,
        "value": 0,
        "value_hex": "0x00",
        "enabled_names": [],
        "bits": {name: False for _, name in GAME_FLAGS},
        "suppressed_from_8bim_trailer": True,
    })
    return obj


def _suppressed_8bim_metadata_to_dict(
    footer: bytes,
    version: int | None = None,
    *,
    absolute_footer_start: int | None = None,
    include_walk: bool = False,
    include_raw_scans: bool = False,
) -> dict[str, Any]:
    """Return JSON metadata for an opaque 8BIM trailer without interpreting it as RSBEditor fields."""
    shift = footer_layout_shift(version)
    marker_off = find_8bim_marker(footer)
    result: dict[str, Any] = {
        "size": len(footer),
        "layout": {
            "version": version,
            "shift": shift,
            "note": "v6/older footer offset adjustment (-1 byte vs v8/v9 canonical offsets)" if shift else None,
        },
        "opaque_trailer": {
            "detected": True,
            "kind": "8BIM/Photoshop resource data",
            "marker_offset": None if marker_off is None else _offset_obj(marker_off, absolute_footer_start),
            "note": "Raw trailer bytes are preserved, but known RSBEditor-style fields are suppressed to disabled/default values.",
        },
        "fields": {},
        "animation_tail": {"detected": False, "suppressed_from_8bim_trailer": True},
        "damage_surface_tail": {
            "parsed": False,
            "suppressed_from_8bim_trailer": True,
            "damage_texture": {"enabled": False, "filename": None},
        },
        "surface": None,
    }

    if absolute_footer_start is not None:
        result["start_offset"] = absolute_footer_start
        result["start_offset_hex"] = f"0x{absolute_footer_start:X}"

    fields: dict[str, Any] = result["fields"]
    fields["alpha_blend_enabled"] = _suppressed_byte_field(shifted(0x04, version), enabled=True, absolute_footer_start=absolute_footer_start)
    fields["alpha_test_enabled"] = _suppressed_byte_field(shifted(0x05, version), enabled=True, absolute_footer_start=absolute_footer_start)
    fields["mipmaps_enabled"] = _suppressed_byte_field(shifted(0x06, version), enabled=True, absolute_footer_start=absolute_footer_start)
    fields["animation_enabled"] = _suppressed_byte_field(shifted(0x07, version), enabled=True, absolute_footer_start=absolute_footer_start)
    fields["scrolling_enabled"] = _suppressed_byte_field(shifted(0x08, version), names=SCROLL_MODE_NAMES, absolute_footer_start=absolute_footer_start)
    fields["tiled_enabled"] = _suppressed_byte_field(shifted(0x09, version), enabled=True, absolute_footer_start=absolute_footer_start)
    fields["compress_on_load"] = _suppressed_byte_field(shifted(0x0A, version), enabled=True, absolute_footer_start=absolute_footer_start)
    fields["distortion_map"] = _suppressed_byte_field(shifted(0x0B, version), enabled=True, absolute_footer_start=absolute_footer_start)
    fields["game_flags"] = _suppressed_game_flags_obj(shifted(0x0C, version), absolute_footer_start=absolute_footer_start)
    fields["source_blend_function"] = _suppressed_u32_field(shifted(0x10, version), names=BLEND_FUNCTION_NAMES_SRC, absolute_footer_start=absolute_footer_start)
    fields["destination_blend_function"] = _suppressed_u32_field(shifted(0x14, version), names=BLEND_FUNCTION_NAMES_DST, absolute_footer_start=absolute_footer_start)
    fields["alpha_test_compare_function"] = _suppressed_u32_field(shifted(0x18, version), names=ALPHA_TEST_FUNCTION_NAMES, absolute_footer_start=absolute_footer_start)
    fields["alpha_test_reference"] = _suppressed_byte_field(shifted(0x1C, version), absolute_footer_start=absolute_footer_start)
    fields["scrolling_type"] = _suppressed_byte_field(shifted(0x1D, version), names=SCROLL_TYPE_NAMES, absolute_footer_start=absolute_footer_start)
    fields["horizontal_scroll_rate"] = _suppressed_f32_field(shifted(0x21, version), absolute_footer_start=absolute_footer_start)
    fields["vertical_scroll_rate"] = _suppressed_f32_field(shifted(0x25, version), absolute_footer_start=absolute_footer_start)
    fields["animation_type"] = _suppressed_byte_field(shifted(0x29, version), names={0: "disabled", 1: "oscillate", 2: "constant"}, absolute_footer_start=absolute_footer_start)
    fields["animation_delay"] = _suppressed_f32_field(shifted(0x2D, version), absolute_footer_start=absolute_footer_start)
    fields["mipmap_count"] = _suppressed_byte_field(shifted(0x35, version), absolute_footer_start=absolute_footer_start)
    fields["subsampling"] = _suppressed_byte_field(shifted(0x39, version), names=SUBSAMPLING_NAMES, absolute_footer_start=absolute_footer_start)

    parsed_surface = parse_surface_id(footer)
    if parsed_surface is not None:
        sid, surface_name = parsed_surface
        surface_off = len(footer) - 4
        result["surface"] = {
            "value": sid,
            "name": surface_name,
            "raw_hex": footer[surface_off:].hex(" "),
            "offset": _offset_obj(surface_off, absolute_footer_start),
            "reported_cautiously": True,
            "suppressed_from_8bim_trailer": True,
        }

    if include_walk:
        result["walk"] = describe_footer_linear(footer, version)

    if include_raw_scans:
        result["raw_scans"] = {
            "length_prefixed_rsb_strings": [
                {"offset": _offset_obj(off, absolute_footer_start), "length": n, "filename": name}
                for off, n, name in scan_length_prefixed_strings(footer)
            ],
            "plain_rsb_strings": [
                {"offset": off, "offset_hex": f"0x{off:X}", "filename": name}
                for off, name in scan_plain_rsb_strings(footer, base=(absolute_footer_start or 0))
            ],
        }

    return result

def footer_metadata_to_dict(
    footer: bytes,
    version: int | None = None,
    *,
    absolute_footer_start: int | None = None,
    include_walk: bool = False,
    include_raw_scans: bool = False,
) -> dict[str, Any]:
    """
    Return decoded footer metadata as JSON-serialisable dictionaries.

    This is intended for RSBViewer/GUI/tests. It uses the same resolved layout
    logic as describe_footer_linear(), but returns stable field names instead
    of human-formatted strings.
    """
    shift = footer_layout_shift(version)
    result: dict[str, Any] = {
        "size": len(footer),
        "layout": {
            "version": version,
            "shift": shift,
            "note": "v6/older footer offset adjustment (-1 byte vs v8/v9 canonical offsets)" if shift else None,
        },
        "fields": {},
        "animation_tail": {"detected": False},
        "damage_surface_tail": {"parsed": False},
        "surface": None,
    }

    if absolute_footer_start is not None:
        result["start_offset"] = absolute_footer_start
        result["start_offset_hex"] = f"0x{absolute_footer_start:X}"

    if has_early_8bim_marker(footer):
        return _suppressed_8bim_metadata_to_dict(
            footer,
            version,
            absolute_footer_start=absolute_footer_start,
            include_walk=include_walk,
            include_raw_scans=include_raw_scans,
        )

    fields: dict[str, Any] = result["fields"]
    fields["alpha_blend_enabled"] = _byte_field(footer, shifted(0x04, version), enabled=True, absolute_footer_start=absolute_footer_start)
    fields["alpha_test_enabled"] = _byte_field(footer, shifted(0x05, version), enabled=True, absolute_footer_start=absolute_footer_start)
    fields["mipmaps_enabled"] = _byte_field(footer, shifted(0x06, version), enabled=True, absolute_footer_start=absolute_footer_start)
    fields["animation_enabled"] = _byte_field(footer, shifted(0x07, version), enabled=True, absolute_footer_start=absolute_footer_start)
    fields["scrolling_enabled"] = _byte_field(footer, shifted(0x08, version), names=SCROLL_MODE_NAMES, absolute_footer_start=absolute_footer_start)
    fields["tiled_enabled"] = _byte_field(footer, shifted(0x09, version), enabled=True, absolute_footer_start=absolute_footer_start)
    fields["compress_on_load"] = _byte_field(footer, shifted(0x0A, version), enabled=True, absolute_footer_start=absolute_footer_start)
    fields["distortion_map"] = _byte_field(footer, shifted(0x0B, version), enabled=True, absolute_footer_start=absolute_footer_start)
    fields["game_flags"] = _game_flags_obj(footer, shifted(0x0C, version), absolute_footer_start=absolute_footer_start)
    fields["source_blend_function"] = _u32_field(footer, shifted(0x10, version), names=BLEND_FUNCTION_NAMES_SRC, absolute_footer_start=absolute_footer_start)
    fields["destination_blend_function"] = _u32_field(footer, shifted(0x14, version), names=BLEND_FUNCTION_NAMES_DST, absolute_footer_start=absolute_footer_start)
    fields["alpha_test_compare_function"] = _u32_field(footer, shifted(0x18, version), names=ALPHA_TEST_FUNCTION_NAMES, absolute_footer_start=absolute_footer_start)
    fields["alpha_test_reference"] = _byte_field(footer, shifted(0x1C, version), absolute_footer_start=absolute_footer_start)
    fields["scrolling_type"] = _byte_field(footer, shifted(0x1D, version), names=SCROLL_TYPE_NAMES, absolute_footer_start=absolute_footer_start)

    scroll_type = byte_at(footer, shifted(0x1D, version))
    if SCROLL_TYPE_NAMES.get(scroll_type) == "rotate":
        fields["rotation_rate"] = _f32_field(footer, shifted(0x21, version), absolute_footer_start=absolute_footer_start)
        fields["secondary_unused_rate"] = _f32_field(footer, shifted(0x25, version), absolute_footer_start=absolute_footer_start)
    else:
        fields["horizontal_scroll_rate"] = _f32_field(footer, shifted(0x21, version), absolute_footer_start=absolute_footer_start)
        fields["vertical_scroll_rate"] = _f32_field(footer, shifted(0x25, version), absolute_footer_start=absolute_footer_start)

    # Corrected labels: animation type 0 is treated as disabled/none by the UI,
    # while 1/2 are the observed RSBEditor behaviours.
    fields["animation_type"] = _byte_field(footer, shifted(0x29, version), names={0: "disabled", 1: "oscillate", 2: "constant"}, absolute_footer_start=absolute_footer_start)
    fields["animation_delay"] = _f32_field(footer, shifted(0x2D, version), absolute_footer_start=absolute_footer_start)

    anim = parse_animation_tail(footer, version)
    if anim is not None:
        result["animation_tail"] = {
            "detected": True,
            "start_offset": _offset_obj(anim.start_off, absolute_footer_start),
            "frame_count": anim.frame_count,
            "frames": [
                _frame_obj(idx, len_off, n, name, absolute_footer_start)
                for idx, (len_off, n, name) in enumerate(anim.frames, 1)
            ],
            "mipmap_count": {
                **_u32_field(footer, anim.mipmap_count_off, absolute_footer_start=absolute_footer_start),
                "value": anim.mipmap_count,
            },
            "subsampling": {
                **_u32_field(footer, anim.subsampling_off, names=SUBSAMPLING_NAMES, absolute_footer_start=absolute_footer_start),
                "value": anim.subsampling,
                "name": SUBSAMPLING_NAMES.get(anim.subsampling, "unknown subsampling value"),
            },
            "damage_tail_offset": _offset_obj(anim.damage_tail_off, absolute_footer_start),
        }
        damage = parse_damage_surface_tail(footer, anim.damage_tail_off, require_end=False)
    else:
        fixed_count_off = shifted(0x35, version)
        fixed_subsampling_off = shifted(0x39, version)
        fields["mipmap_count"] = _byte_field(footer, fixed_count_off, absolute_footer_start=absolute_footer_start)
        fields["subsampling"] = _byte_field(footer, fixed_subsampling_off, names=SUBSAMPLING_NAMES, absolute_footer_start=absolute_footer_start)
        damage = parse_damage_surface_tail(footer, shifted(0x3D, version), require_end=False)

    result["damage_surface_tail"] = _damage_surface_tail_obj(footer, damage, absolute_footer_start=absolute_footer_start)

    if damage is not None:
        result["surface"] = result["damage_surface_tail"].get("surface")
    else:
        parsed_surface = parse_surface_id(footer)
        if parsed_surface is not None:
            sid, surface_name = parsed_surface
            surface_off = len(footer) - 4
            result["surface"] = {
                "value": sid,
                "name": surface_name,
                "raw_hex": footer[surface_off:].hex(" "),
                "offset": _offset_obj(surface_off, absolute_footer_start),
            }

    if include_walk:
        result["walk"] = describe_footer_linear(footer, version)

    if include_raw_scans:
        result["raw_scans"] = {
            "length_prefixed_rsb_strings": [
                {"offset": _offset_obj(off, absolute_footer_start), "length": n, "filename": s}
                for off, n, s in scan_length_prefixed_strings(footer)
            ],
            "plain_rsb_strings": [
                {"offset": off, "offset_hex": f"0x{off:X}", "filename": s}
                for off, s in scan_plain_rsb_strings(footer, base=(absolute_footer_start or 0))
            ],
        }

    return result


# Backward-compatible names used by older inspector scripts.
def try_v8_footer_map(footer: bytes, version: int | None = None) -> list[str]:
    return describe_footer_linear(footer, version)
