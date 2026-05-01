#!/usr/bin/env python3
"""Convert selected Red Storm Bitmap (.rsb) files to PNG.

Adds brute-force ARGB8888 testing helpers:
- all 4 byte orders: bgra, rgba, argb, abgr
- optional payload start offsets: 0..3 bytes

Useful for troublesome 32-bit RSBs where channel order or payload alignment
is inconsistent between files.
"""

from __future__ import annotations

import argparse
import os
import struct
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from PIL import Image


class RSBError(Exception):
    pass


@dataclass
class RSBHeader:
    version: int
    width: int
    height: int
    contains_palette: int
    bits_red: int
    bits_green: int
    bits_blue: int
    bits_alpha: int
    bit_depth_bytes: int | None
    dxt_type: int | None
    header_end: int
    format_name: str


class ByteReader:
    def __init__(self, data: bytes):
        self.data = data
        self.pos = 0

    def tell(self) -> int:
        return self.pos

    def seek(self, offset: int, whence: int = os.SEEK_SET) -> None:
        if whence == os.SEEK_SET:
            new_pos = offset
        elif whence == os.SEEK_CUR:
            new_pos = self.pos + offset
        elif whence == os.SEEK_END:
            new_pos = len(self.data) + offset
        else:
            raise ValueError(f"bad whence: {whence}")
        if new_pos < 0 or new_pos > len(self.data):
            raise RSBError(f"seek out of range: {new_pos}")
        self.pos = new_pos

    def read_u32(self) -> int:
        if self.pos + 4 > len(self.data):
            raise RSBError("unexpected EOF while reading u32")
        value = struct.unpack_from("<I", self.data, self.pos)[0]
        self.pos += 4
        return value

    def read_i32(self) -> int:
        if self.pos + 4 > len(self.data):
            raise RSBError("unexpected EOF while reading i32")
        value = struct.unpack_from("<i", self.data, self.pos)[0]
        self.pos += 4
        return value


def guess_format(bits_red: int, bits_green: int, bits_blue: int, bits_alpha: int,
                 contains_palette: int, dxt_type: int | None) -> str:
    if dxt_type is not None and dxt_type >= 0:
        return {
            0: "DXT1",
            1: "DXT2?",
            2: "DXT3?",
            3: "DXT4?",
            4: "DXT5",
            5: "DXT5?",
        }.get(dxt_type, f"DXT({dxt_type})")

    if contains_palette == 1:
        return "paletted"

    t = (bits_red, bits_green, bits_blue, bits_alpha)
    if t == (5, 6, 5, 0):
        return "RGB565"
    if t == (5, 5, 5, 1):
        return "ARGB1555"
    if t == (4, 4, 4, 4):
        return "ARGB4444"
    if t == (8, 8, 8, 8):
        return "ARGB8888"
    if t == (8, 8, 8, 0):
        return "RGB888"
    return f"raw({bits_red},{bits_green},{bits_blue},{bits_alpha})"


def parse_header(data: bytes) -> RSBHeader:
    r = ByteReader(data)

    version = r.read_u32()
    width = r.read_u32()
    height = r.read_u32()

    contains_palette = 0
    bits_red = bits_green = bits_blue = bits_alpha = 0
    bit_depth_bytes: int | None = None
    dxt_type: int | None = None

    if version == 0:
        contains_palette = r.read_u32()
        if contains_palette == 0:
            bits_red = r.read_u32()
            bits_green = r.read_u32()
            bits_blue = r.read_u32()
            bits_alpha = r.read_u32()
    else:
        contains_palette = 0
        if version > 7:
            r.seek(7, os.SEEK_CUR)
        bits_red = r.read_u32()
        bits_green = r.read_u32()
        bits_blue = r.read_u32()
        bits_alpha = r.read_u32()
        if version >= 9:
            r.seek(4, os.SEEK_CUR)
            dxt_type = r.read_i32()

    total_bits = bits_red + bits_green + bits_blue + bits_alpha
    if total_bits and total_bits % 8 == 0:
        bit_depth_bytes = total_bits // 8

    format_name = guess_format(bits_red, bits_green, bits_blue, bits_alpha, contains_palette, dxt_type)

    return RSBHeader(
        version=version,
        width=width,
        height=height,
        contains_palette=contains_palette,
        bits_red=bits_red,
        bits_green=bits_green,
        bits_blue=bits_blue,
        bits_alpha=bits_alpha,
        bit_depth_bytes=bit_depth_bytes,
        dxt_type=dxt_type,
        header_end=r.tell(),
        format_name=format_name,
    )


def unpack_rgb565(payload: bytes, width: int, height: int) -> bytes:
    out = bytearray(width * height * 4)
    j = 0
    for i in range(0, width * height * 2, 2):
        v = payload[i] | (payload[i + 1] << 8)
        r = ((v >> 11) & 0x1F) * 255 // 31
        g = ((v >> 5) & 0x3F) * 255 // 63
        b = (v & 0x1F) * 255 // 31
        out[j:j+4] = bytes((r, g, b, 255))
        j += 4
    return bytes(out)


def unpack_argb1555(payload: bytes, width: int, height: int) -> bytes:
    out = bytearray(width * height * 4)
    j = 0
    for i in range(0, width * height * 2, 2):
        v = payload[i] | (payload[i + 1] << 8)
        a = 255 if (v >> 15) & 0x1 else 0
        r = ((v >> 10) & 0x1F) * 255 // 31
        g = ((v >> 5) & 0x1F) * 255 // 31
        b = (v & 0x1F) * 255 // 31
        out[j:j+4] = bytes((r, g, b, a))
        j += 4
    return bytes(out)


def unpack_argb4444(payload: bytes, width: int, height: int) -> bytes:
    out = bytearray(width * height * 4)
    j = 0
    for i in range(0, width * height * 2, 2):
        v = payload[i] | (payload[i + 1] << 8)
        a = ((v >> 12) & 0xF) * 17
        r = ((v >> 8) & 0xF) * 17
        g = ((v >> 4) & 0xF) * 17
        b = (v & 0xF) * 17
        out[j:j+4] = bytes((r, g, b, a))
        j += 4
    return bytes(out)


def unpack_argb8888(payload: bytes, width: int, height: int, byte_order: str = "bgra") -> bytes:
    out = bytearray(width * height * 4)

    for i in range(0, width * height * 4, 4):
        p0 = payload[i]
        p1 = payload[i + 1]
        p2 = payload[i + 2]
        p3 = payload[i + 3]

        if byte_order == "bgra":
            b, g, r, a = p0, p1, p2, p3
        elif byte_order == "rgba":
            r, g, b, a = p0, p1, p2, p3
        elif byte_order == "argb":
            a, r, g, b = p0, p1, p2, p3
        elif byte_order == "abgr":
            a, b, g, r = p0, p1, p2, p3
        else:
            raise RSBError(f"unsupported ARGB8888 byte order: {byte_order}")

        out[i:i+4] = bytes((r, g, b, a))

    return bytes(out)


def unpack_rgb888(payload: bytes, width: int, height: int) -> bytes:
    out = bytearray(width * height * 4)
    j = 0
    for i in range(0, width * height * 3, 3):
        r = payload[i]
        g = payload[i + 1]
        b = payload[i + 2]
        out[j:j+4] = bytes((r, g, b, 255))
        j += 4
    return bytes(out)


def decode_rsb(
    data: bytes,
    argb8888_order: str = "bgra",
    payload_shift: int = 0,
) -> tuple[RSBHeader, Image.Image, int]:
    header = parse_header(data)

    if header.contains_palette == 1:
        raise RSBError("paletted RSBs are not supported yet")
    if header.dxt_type is not None and header.dxt_type >= 0:
        raise RSBError(f"DXT-compressed RSBs are not supported yet ({header.format_name})")

    bpp_map = {
        "RGB565": 2,
        "ARGB1555": 2,
        "ARGB4444": 2,
        "ARGB8888": 4,
        "RGB888": 3,
    }
    if header.format_name not in bpp_map:
        raise RSBError(
            f"unsupported/unrecognised format {header.format_name} "
            f"(bits {header.bits_red},{header.bits_green},{header.bits_blue},{header.bits_alpha})"
        )

    bytes_per_pixel = bpp_map[header.format_name]
    expected_payload = header.width * header.height * bytes_per_pixel
    start = header.header_end + payload_shift
    end = start + expected_payload

    if start < 0:
        raise RSBError(f"payload start before file beginning: {start}")
    if end > len(data):
        raise RSBError(
            f"file too small for {header.width}x{header.height} {header.format_name} image at "
            f"offset 0x{start:X}. Need at least {end} bytes, have {len(data)}."
        )

    payload = data[start:end]
    trailing = len(data) - end

    if header.format_name == "RGB565":
        rgba = unpack_rgb565(payload, header.width, header.height)
    elif header.format_name == "ARGB1555":
        rgba = unpack_argb1555(payload, header.width, header.height)
    elif header.format_name == "ARGB4444":
        rgba = unpack_argb4444(payload, header.width, header.height)
    elif header.format_name == "ARGB8888":
        rgba = unpack_argb8888(payload, header.width, header.height, byte_order=argb8888_order)
    elif header.format_name == "RGB888":
        rgba = unpack_rgb888(payload, header.width, header.height)
    else:
        raise AssertionError("unreachable")

    image = Image.frombytes("RGBA", (header.width, header.height), rgba)
    return header, image, trailing


def safe_folder_name(name: str) -> str:
    return "".join(c if c.isalnum() or c in ("-", "_") else "_" for c in name)


def default_output_path(src: Path, suffix: str = ".png") -> Path:
    if src.suffix:
        return src.with_suffix(src.suffix + suffix)
    return src.with_name(src.name + suffix)


def build_grouped_output_path(
    src: Path,
    base_dir: Path,
    version: int,
    format_name: str,
    suffix: str = ".png",
) -> Path:
    version_dir = base_dir / f"v{version}"
    format_dir = version_dir / safe_folder_name(format_name)
    format_dir.mkdir(parents=True, exist_ok=True)
    stem = src.stem if src.suffix else src.name
    return format_dir / f"{stem}{suffix}"


def save_variant(
    src: Path,
    dst: Path | None,
    argb8888_order: str,
    payload_shift: int = 0,
    verbose: bool = True,
    group_by_format: bool = False,
    grouped_output_root: Path | None = None,
) -> int:
    data = src.read_bytes()
    header, image, trailing = decode_rsb(
        data,
        argb8888_order=argb8888_order,
        payload_shift=payload_shift,
    )

    if header.format_name == "ARGB8888" and dst is None:
        suffix = f".off{payload_shift}.{argb8888_order}.png"
    else:
        suffix = ".png"

    if dst is not None:
        out_path = dst
    elif group_by_format:
        base_dir = grouped_output_root or src.parent / "output"
        out_path = build_grouped_output_path(src, base_dir, header.version, header.format_name, suffix)
    else:
        out_path = default_output_path(src, suffix)

    image.save(out_path)

    if verbose:
        trail_msg = f", trailing {trailing} byte(s) ignored" if trailing else ""
        extra = ""
        if header.format_name == "ARGB8888":
            extra = f", order={argb8888_order}, shift={payload_shift}"
        print(
            f"OK  {src} -> {out_path} | v{header.version} {header.width}x{header.height} "
            f"{header.format_name} header_end=0x{header.header_end:X}{extra}{trail_msg}"
        )
    return 0


def convert_file(
    src: Path,
    dst: Path | None,
    verbose: bool = True,
    argb8888_order: str = "bgra",
    payload_shift: int = 0,
    write_all_8888_variants: bool = False,
    group_by_format: bool = False,
    grouped_output_root: Path | None = None,
) -> int:
    if write_all_8888_variants:
        data = src.read_bytes()
        header = parse_header(data)
        if header.format_name == "ARGB8888":
            for shift in range(4):
                for order in ("bgra", "rgba", "argb", "abgr"):
                    save_variant(
                        src,
                        None,
                        order,
                        payload_shift=shift,
                        verbose=verbose,
                        group_by_format=group_by_format,
                        grouped_output_root=grouped_output_root,
                    )
            return 0

    return save_variant(
        src,
        dst,
        argb8888_order,
        payload_shift=payload_shift,
        verbose=verbose,
        group_by_format=group_by_format,
        grouped_output_root=grouped_output_root,
    )


def iter_inputs(paths: Iterable[Path], recursive: bool) -> Iterable[Path]:
    for path in paths:
        if path.is_file():
            yield path
        elif path.is_dir():
            walker = path.rglob("*.rsb") if recursive else path.glob("*.rsb")
            for sub in walker:
                if sub.is_file():
                    yield sub


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Convert supported .rsb files to PNG")
    parser.add_argument("inputs", nargs="+", help="Input .rsb file(s) or directory/directories")
    parser.add_argument("-o", "--output", help="Output PNG path (single input file only)")
    parser.add_argument("-r", "--recursive", action="store_true", help="Recurse into directories")
    parser.add_argument("--keep-going", action="store_true", help="Continue after errors in batch mode")
    parser.add_argument(
        "--argb8888-order",
        choices=("bgra", "rgba", "argb", "abgr"),
        default="bgra",
        help="Byte order to assume for ARGB8888 payloads (default: bgra)",
    )
    parser.add_argument(
        "--payload-shift",
        type=int,
        default=0,
        choices=(0, 1, 2, 3),
        help="Additional byte shift to apply to the ARGB8888 payload start (default: 0)",
    )
    parser.add_argument(
        "--write-all-8888-variants",
        action="store_true",
        help="For ARGB8888 files, write all 16 combinations: off0..off3 x bgra/rgba/argb/abgr",
    )
    parser.add_argument(
        "--group-by-format",
        action="store_true",
        help="Write PNGs into per-version/per-format subfolders (for example output/v9/ARGB8888/file.png)",
    )
    parser.add_argument(
        "--group-output-dir",
        help="Base directory for --group-by-format output (default: ./output beside each source file)",
    )
    args = parser.parse_args(argv)

    input_paths = [Path(p) for p in args.inputs]
    if args.output and len(input_paths) != 1:
        parser.error("--output can only be used with a single input file")
    if args.output and args.write_all_8888_variants:
        parser.error("--output cannot be used together with --write-all-8888-variants")
    if args.output and args.group_by_format:
        parser.error("--output cannot be used together with --group-by-format")
    if args.group_output_dir and not args.group_by_format:
        parser.error("--group-output-dir requires --group-by-format")

    failures = 0
    for src in iter_inputs(input_paths, args.recursive):
        try:
            dst = Path(args.output) if args.output and src.is_file() and len(input_paths) == 1 else None
            convert_file(
                src,
                dst,
                argb8888_order=args.argb8888_order,
                payload_shift=args.payload_shift,
                write_all_8888_variants=args.write_all_8888_variants,
                group_by_format=args.group_by_format,
                grouped_output_root=Path(args.group_output_dir) if args.group_output_dir else None,
            )
        except Exception as exc:
            failures += 1
            print(f"ERR {src}: {exc}", file=sys.stderr)
            if not args.keep_going:
                return 1
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
