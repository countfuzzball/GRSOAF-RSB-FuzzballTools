#!/usr/bin/env python3
from __future__ import annotations

import argparse
import struct
from pathlib import Path
from typing import Iterable

try:
    from PIL import Image
except ImportError as exc:
    raise SystemExit(
        "Pillow is required. Install it with: python -m pip install Pillow"
    ) from exc


class RSBWriteError(Exception):
    pass


FORMAT_BITS = {
    "argb8888": (8, 8, 8, 8),
    "rgb888": (8, 8, 8, 0),
    "rgb565": (5, 6, 5, 0),
    "argb1555": (5, 5, 5, 1),
    "argb4444": (4, 4, 4, 4),
}

GAME_FLAG_BITS = {
    "gunshot": 0x01,
    "grenade": 0x02,
    "los": 0x04,
    "foliage": 0x08,
    "water": 0x10,
}

BYTE_ORDERS = ("bgra", "rgba", "argb", "abgr")
SCROLL_TYPES = {"hv": 0, "rotate": 1}
ANIMATION_TYPES = {"none": 0, "oscillate": 1, "constant": 2}


def u32(value: int) -> bytes:
    return struct.pack("<I", value)


def i32(value: int) -> bytes:
    return struct.pack("<i", value)


def f32(value: float) -> bytes:
    return struct.pack("<f", value)


def build_header(width: int, height: int, fmt: str, version: int, v9_unknown: int, dxt_type: int) -> bytes:
    """
    V8/V9 layout matching the current rsb_format.py reader:
      uint32 version
      uint32 width
      uint32 height
      7 reserved bytes                      # version > 7
      uint32 bits_red
      uint32 bits_green
      uint32 bits_blue
      uint32 bits_alpha

    V8 payload follows immediately at 0x23.

    V9 adds:
      int32 unknown/reserved                # usually -1 in current samples
      int32 dxt_type                        # -1 for raw/uncompressed pixels

    V9 raw pixel payload therefore starts at 0x2B.
    """
    if fmt not in FORMAT_BITS:
        raise RSBWriteError(f"unsupported format {fmt!r}")
    if version not in (8, 9):
        raise RSBWriteError("--version must be 8 or 9")

    br, bg, bb, ba = FORMAT_BITS[fmt]
    parts = [
        u32(version),
        u32(width),
        u32(height),
        b"\x00" * 7,
        u32(br),
        u32(bg),
        u32(bb),
        u32(ba),
    ]
    if version == 9:
        parts.extend([i32(v9_unknown), i32(dxt_type)])
    return b"".join(parts)


def image_to_rgba(path: Path, flip_y: bool) -> Image.Image:
    im = Image.open(path).convert("RGBA")
    if flip_y:
        im = im.transpose(Image.Transpose.FLIP_TOP_BOTTOM)
    return im


def encode_argb8888(im: Image.Image, byte_order: str) -> bytes:
    if byte_order not in BYTE_ORDERS:
        raise RSBWriteError(f"unsupported byte order {byte_order!r}")

    raw = im.tobytes("raw", "RGBA")
    out = bytearray(len(raw))
    for i in range(0, len(raw), 4):
        r, g, b, a = raw[i], raw[i + 1], raw[i + 2], raw[i + 3]
        if byte_order == "bgra":
            out[i:i + 4] = bytes((b, g, r, a))
        elif byte_order == "rgba":
            out[i:i + 4] = bytes((r, g, b, a))
        elif byte_order == "argb":
            out[i:i + 4] = bytes((a, r, g, b))
        elif byte_order == "abgr":
            out[i:i + 4] = bytes((a, b, g, r))
    return bytes(out)


def encode_rgb888(im: Image.Image, byte_order: str) -> bytes:
    raw = im.tobytes("raw", "RGBA")
    out = bytearray((len(raw) // 4) * 3)
    j = 0
    for i in range(0, len(raw), 4):
        r, g, b = raw[i], raw[i + 1], raw[i + 2]
        if byte_order in ("bgra", "abgr"):
            out[j:j + 3] = bytes((b, g, r))
        else:
            out[j:j + 3] = bytes((r, g, b))
        j += 3
    return bytes(out)


def encode_rgb565(im: Image.Image) -> bytes:
    raw = im.tobytes("raw", "RGBA")
    out = bytearray((len(raw) // 4) * 2)
    j = 0
    for i in range(0, len(raw), 4):
        r, g, b = raw[i], raw[i + 1], raw[i + 2]
        value = ((r >> 3) << 11) | ((g >> 2) << 5) | (b >> 3)
        out[j:j + 2] = struct.pack("<H", value)
        j += 2
    return bytes(out)


def encode_argb1555(im: Image.Image, alpha_threshold: int) -> bytes:
    raw = im.tobytes("raw", "RGBA")
    out = bytearray((len(raw) // 4) * 2)
    j = 0
    for i in range(0, len(raw), 4):
        r, g, b, a = raw[i], raw[i + 1], raw[i + 2], raw[i + 3]
        abit = 1 if a >= alpha_threshold else 0
        value = (abit << 15) | ((r >> 3) << 10) | ((g >> 3) << 5) | (b >> 3)
        out[j:j + 2] = struct.pack("<H", value)
        j += 2
    return bytes(out)


def encode_argb4444(im: Image.Image) -> bytes:
    raw = im.tobytes("raw", "RGBA")
    out = bytearray((len(raw) // 4) * 2)
    j = 0
    for i in range(0, len(raw), 4):
        r, g, b, a = raw[i], raw[i + 1], raw[i + 2], raw[i + 3]
        value = ((a >> 4) << 12) | ((r >> 4) << 8) | ((g >> 4) << 4) | (b >> 4)
        out[j:j + 2] = struct.pack("<H", value)
        j += 2
    return bytes(out)


def encode_pixels(im: Image.Image, fmt: str, byte_order: str, alpha_threshold: int) -> bytes:
    if fmt == "argb8888":
        return encode_argb8888(im, byte_order)
    if fmt == "rgb888":
        return encode_rgb888(im, byte_order)
    if fmt == "rgb565":
        return encode_rgb565(im)
    if fmt == "argb1555":
        return encode_argb1555(im, alpha_threshold)
    if fmt == "argb4444":
        return encode_argb4444(im)
    raise RSBWriteError(f"unsupported format {fmt!r}")


def mip_dimensions(width: int, height: int, count: int) -> list[tuple[int, int]]:
    dims: list[tuple[int, int]] = []
    w, h = width, height
    for _ in range(count):
        w = max(1, w // 2)
        h = max(1, h // 2)
        dims.append((w, h))
    return dims


def build_mipmap_payloads(im: Image.Image, args: argparse.Namespace) -> bytes:
    if args.mipmap_count <= 0:
        return b""

    payloads: list[bytes] = []
    for w, h in mip_dimensions(im.width, im.height, args.mipmap_count):
        mip = im.resize((w, h), Image.Resampling.LANCZOS)
        payloads.append(encode_pixels(mip, args.format, args.byte_order, args.alpha_threshold))
    return b"".join(payloads)


def blank_footer_prefix() -> bytearray:
    """
    Minimal known V8/V9-style metadata footer prefix.

    Controlled RSBEditor samples show that the damage/surface tail begins at
    footer offset +0x3D. For writer output intended to reopen cleanly in
    RSBEditor, always emit an explicit damage-disabled byte for no-damage
    files rather than a bare FF FF FF FF tail:

      no damage + no surface:             00 FF FF FF FF
      no damage + surface:                00 <int32 surface>
      damage + no surface:                01 <len> <name NUL> FF FF FF FF
      damage + surface:                   01 <len> <name NUL> <int32 surface>

    This returns only the fixed 0x3D-byte prefix. build_damage_surface_tail()
    appends the final damage/surface bytes explicitly.
    """
    return bytearray(0x3D)

def parse_game_flags(values: Iterable[str]) -> int:
    flags = 0
    for value in values:
        for part in value.split(","):
            key = part.strip().lower()
            if not key:
                continue
            if key not in GAME_FLAG_BITS:
                valid = ", ".join(sorted(GAME_FLAG_BITS))
                raise RSBWriteError(f"unknown game flag {part!r}; valid: {valid}")
            flags |= GAME_FLAG_BITS[key]
    return flags


def encode_rsb_name(name: str, option_name: str) -> bytes:
    encoded = name.encode("ascii")
    if not encoded.lower().endswith(b".rsb"):
        raise RSBWriteError(f"{option_name} must end with .rsb")
    if b"\x00" in encoded:
        raise RSBWriteError(f"{option_name} cannot contain NUL bytes")
    return encoded + b"\x00"

def build_damage_surface_tail(args: argparse.Namespace) -> bytes:
    """Build explicit damage/surface tail for RSBEditor-compatible output."""
    if args.damage_texture:
        encoded = encode_rsb_name(args.damage_texture, "--damage-texture")
        tail = bytearray()
        tail += b"\x01"
        tail += u32(len(encoded))
        tail += encoded
        tail += i32(args.surface)
        return bytes(tail)

    # Important:
    # Always write an explicit damage-disabled byte.
    # RSBEditor may treat bare FF FF FF FF as damage enabled.
    return b"\x00" + i32(args.surface)


def animation_frame_record_bytes(frames: Iterable[str] | None) -> bytes:
    if not frames:
        return b""

    out = bytearray()
    for frame in frames:
        encoded = encode_rsb_name(frame, f"animation frame {frame!r}")
        out += u32(len(encoded))
        out += encoded

    return bytes(out)

def build_animation_tail(args: argparse.Namespace) -> bytes:
    """
    Build the animation variable section observed in canonical RSBEditor output.

    Animation records begin at footer offset +0x31, not +0x3D.

    For non-animation files, RSBEditor stores mipmap/subsampling metadata at
    fixed footer positions +0x35 and +0x39. Animation records start at +0x31,
    so those fixed positions are consumed by the variable animation block.

    The animation-tail shape is therefore:
      <uint32 frame_count>
      repeated: <uint32 name_len> <name NUL>
      <uint32 mipmap_count>
      <uint32 subsampling>
      damage/surface tail

    In zero-mipmap/default-subsampling samples, those two uint32 values appear
    as an 8-byte zero spacer. With mipmaps enabled, the first uint32 must carry
    the generated mipmap count or RSBEditor reopens the file with count 0.
    """
    frames = args.animation_frame or []
    tail = bytearray()
    tail += u32(len(frames))
    tail += animation_frame_record_bytes(frames)
    tail += u32(args.mipmap_count)
    tail += u32(args.subsampling)
    tail += build_damage_surface_tail(args)
    return bytes(tail)


def build_footer(args: argparse.Namespace) -> bytes:
    footer = blank_footer_prefix()

    footer[0x04] = 1 if args.alpha_blend else 0
    footer[0x05] = 1 if args.alpha_test else 0
    footer[0x06] = 1 if args.mipmap_count > 0 else 0
    footer[0x07] = 1 if args.animation_enabled else 0
    footer[0x08] = 1 if args.scroll_enabled else 0
    footer[0x09] = 1 if args.tiled else 0
    footer[0x0A] = 1 if args.compress_on_load else 0
    footer[0x0B] = 1 if args.distortion_map else 0
    footer[0x0C] = parse_game_flags(args.game_flag or [])

    struct.pack_into("<I", footer, 0x10, args.src_blend)
    struct.pack_into("<I", footer, 0x14, args.dst_blend)
    struct.pack_into("<I", footer, 0x18, args.alpha_compare)
    footer[0x1C] = args.alpha_ref & 0xFF

    footer[0x1D] = SCROLL_TYPES[args.scroll_type]
    struct.pack_into("<f", footer, 0x21, args.scroll_primary)
    struct.pack_into("<f", footer, 0x25, args.scroll_secondary)

    footer[0x29] = ANIMATION_TYPES[args.animation_type]
    struct.pack_into("<f", footer, 0x2D, args.animation_delay)

    if args.animation_frame:
        # Canonical RSBEditor animation records begin at +0x31.
        # This makes later metadata variable-position: build_animation_tail()
        # writes mipmap count/subsampling after the animation frame records.
        footer = footer[:0x31]
        footer += build_animation_tail(args)
    else:
        # Non-animation files keep these values at fixed footer offsets.
        footer[0x35] = args.mipmap_count & 0xFF
        footer[0x39] = args.subsampling
        footer += build_damage_surface_tail(args)

    return bytes(footer)

def write_rsb(input_png: Path, output_rsb: Path, args: argparse.Namespace) -> None:
    im = image_to_rgba(input_png, args.flip_y)
    width, height = im.size

    header = build_header(width, height, args.format, args.version, args.v9_unknown, args.dxt_type)
    pixels = encode_pixels(im, args.format, args.byte_order, args.alpha_threshold)
    footer = build_footer(args)
    mipmaps = build_mipmap_payloads(im, args)

    expected = width * height * (sum(FORMAT_BITS[args.format]) // 8)
    if len(pixels) != expected:
        raise RSBWriteError(f"internal size mismatch: got {len(pixels)} bytes, expected {expected}")

    output_rsb.parent.mkdir(parents=True, exist_ok=True)
    output_rsb.write_bytes(header + pixels + footer + mipmaps)


def validate_args(args: argparse.Namespace) -> None:
    if not (0 <= args.alpha_threshold <= 255):
        raise RSBWriteError("--alpha-threshold must be 0..255")
    if not (0 <= args.alpha_ref <= 255):
        raise RSBWriteError("--alpha-ref must be 0..255")
    if not (-2147483648 <= args.surface <= 2147483647):
        raise RSBWriteError("--surface must fit a signed int32")
    for name in ("src_blend", "dst_blend", "alpha_compare"):
        value = getattr(args, name)
        if not (0 <= value <= 0xFFFFFFFF):
            raise RSBWriteError(f"--{name.replace('_', '-')} must fit uint32")
    if not (0 <= args.mipmap_count <= 255):
        raise RSBWriteError("--mipmap-count must be 0..255")
    if args.mipmap_count:
        max_possible = 0
        # Calculated after opening would be more exact; this catches silly input only.
        if args.mipmap_count > 32:
            raise RSBWriteError("--mipmap-count is suspiciously high; use 0..32")
    if args.dxt_type != -1:
        raise RSBWriteError("this writer only emits raw/uncompressed pixels; keep --dxt-type -1")


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Convert a PNG into a simple V8/V9 Red Storm .rsb file. Raw, uncompressed only."
    )
    ap.add_argument("input_png", type=Path)
    ap.add_argument("output_rsb", type=Path)

    core = ap.add_argument_group("core RSB output")
    core.add_argument("--version", type=int, choices=(8, 9), default=8)
    core.add_argument("--format", choices=sorted(FORMAT_BITS), default="argb8888")
    core.add_argument(
        "--byte-order",
        choices=BYTE_ORDERS,
        default="bgra",
        help="byte layout for 32-bit/24-bit payloads; bgra matches little-endian A8R8G8B8-style storage",
    )
    core.add_argument("--flip-y", action="store_true", help="flip the image vertically before writing")
    core.add_argument("--alpha-threshold", type=int, default=128, help="threshold used by argb1555 alpha")
    core.add_argument("--v9-unknown", type=int, default=-1, help="V9-only unknown int32 before dxt_type")
    core.add_argument("--dxt-type", type=int, default=-1, help="V9-only dxt_type; only -1/raw is supported for writing")

    alpha = ap.add_argument_group("alpha blend / alpha test metadata")
    alpha.add_argument("--alpha-blend", action="store_true")
    alpha.add_argument("--src-blend", type=int, default=0)
    alpha.add_argument("--dst-blend", type=int, default=0)
    alpha.add_argument("--alpha-test", action="store_true")
    alpha.add_argument("--alpha-compare", type=int, default=0)
    alpha.add_argument("--alpha-ref", type=int, default=128)

    flags = ap.add_argument_group("game/editor flags")
    flags.add_argument("--game-flag", action="append", help="repeatable or comma-separated: gunshot, grenade, los, foliage, water")
    flags.add_argument("--tiled", action="store_true")
    flags.add_argument("--compress-on-load", action="store_true")
    flags.add_argument("--distortion-map", action="store_true")
    flags.add_argument("--subsampling", type=int, choices=(0, 1, 2), default=0, help="0=One, 1=Two, 2=Three")
    flags.add_argument("--surface", type=int, default=-1, help="surface/material id; -1 means none")
    flags.add_argument("--damage-texture", help="write a tentative enabled damage texture record, e.g. grass_damaged.rsb")

    mip = ap.add_argument_group("mipmaps")
    mip.add_argument("--mipmap-count", type=int, default=0, help="generate and append this many mipmap levels")

    scroll = ap.add_argument_group("scrolling metadata")
    scroll.add_argument("--scroll-enabled", action="store_true")
    scroll.add_argument("--scroll-type", choices=sorted(SCROLL_TYPES), default="hv", help="hv=horizontal/vertical, rotate=rotation")
    scroll.add_argument("--scroll-primary", type=float, default=0.0, help="horizontal/primary rate, or rotation rate for rotate")
    scroll.add_argument("--scroll-secondary", type=float, default=0.0, help="vertical/secondary rate")

    anim = ap.add_argument_group("animation-ish metadata")
    anim.add_argument("--animation-enabled", action="store_true")
    anim.add_argument("--animation-type", choices=sorted(ANIMATION_TYPES), default="none")
    anim.add_argument("--animation-delay", type=float, default=0.0)
    anim.add_argument("--animation-frame", action="append", help="repeatable .rsb frame reference record")

    args = ap.parse_args()
    validate_args(args)
    write_rsb(args.input_png, args.output_rsb, args)
    print(f"wrote {args.output_rsb}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
