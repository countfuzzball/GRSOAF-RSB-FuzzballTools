#!/usr/bin/env python3
from __future__ import annotations

import argparse
from pathlib import Path

from rsb_format import expected_mipmap_sizes, hexdump, load_rsb
from rsb_footer import (
    find_animation_frame_records,
    find_damage_texture_record,
    parse_surface_id,
    scan_length_prefixed_strings,
    scan_plain_rsb_strings,
    try_v8_footer_map,
)


def inspect_file(path: Path, footer_dump: int) -> None:
    rsb = load_rsb(path)
    h = rsb.header
    data = rsb.data
    payload_end = rsb.payload_end
    footer = rsb.footer

    print(f"\n=== {path} ===")
    print(f"file size:        {len(data)} bytes")
    print(f"version:          {h.version}")
    print(f"dimensions:       {h.width}x{h.height}")
    print(f"contains_palette: {h.contains_palette}")
    print(f"bits RGBA:        {h.bits_red},{h.bits_green},{h.bits_blue},{h.bits_alpha}")
    print(f"bit depth:        {h.bit_depth} byte(s)/pixel")
    print(f"dxt_type:         {h.dxt_type}")
    print(f"format guess:     {h.format_name}")
    print(f"payload start:    0x{h.payload_start:X}")

    if rsb.payload_size is None:
        print("payload size:     unknown/unsupported, likely paletted or unusual")
        print("footer:           not calculated")
    else:
        print(f"payload size:     {rsb.payload_size} bytes")
        print(f"payload end:      0x{payload_end:X}")
        if payload_end is not None and payload_end > len(data):
            print(f"WARNING: expected payload exceeds file size by {payload_end - len(data)} byte(s)")
            return
        print(f"footer size:      {len(footer)} bytes")
        print(f"mipmap count:     {rsb.mipmap_count}")
        print(f"mipmap data size: {len(rsb.mipmap_data)} bytes")

    if rsb.mipmap_count:
        print("\nMipmap payloads:")
        sizes = expected_mipmap_sizes(h, rsb.mipmap_count)
        mip_start = (payload_end or 0) + len(footer)
        if sizes is None:
            print(f"  count={rsb.mipmap_count}, total bytes={len(rsb.mipmap_data)}; size details unavailable")
        else:
            cursor = mip_start
            for idx, (mw, mh, nbytes) in enumerate(sizes, 1):
                print(f"  mip {idx}: {mw}x{mh}, {nbytes} bytes, abs 0x{cursor:X}-0x{cursor+nbytes:X}")
                cursor += nbytes

    if h.version > 7:
        print(f"v{h.version} skipped 7-byte block @ 0x0C: {data[0x0C:0x13].hex(' ')}")

    if h.version >= 9:
        dxt_skip_start = h.payload_start - 8
        print(f"v9+ unknown 4 bytes before dxt_type @ 0x{dxt_skip_start:X}: {data[dxt_skip_start:dxt_skip_start+4].hex(' ')}")

    if footer:
        print("\nKnown v8/v9-derived footer guesses:")
        for line in try_v8_footer_map(footer, h.version):
            print(f"  {line}")

        dmg = find_damage_texture_record(footer)
        print("\nLikely damage texture record:")
        if dmg:
            off, name = dmg
            print(f"  footer+0x{off:X}: enabled")
            print(f"  damage texture: {name}")
        else:
            print("  not found")

        surface = parse_surface_id(footer)
        print("\nSurface setting:")
        if surface:
            sid, surface_name = surface
            raw = footer[-4:].hex(" ")
            print(f"  final int32: {sid} ({surface_name})")
            print(f"  raw bytes:   {raw}")
        else:
            print("  not found")

        anim_refs = find_animation_frame_records(footer, dmg)
        print("\nLikely animation frame .rsb references:")
        if anim_refs:
            for idx, (off, n, s) in enumerate(anim_refs, 1):
                print(f"  {idx:02d}. footer+0x{off:X}: len={n} {s}")
        else:
            print("  not found")

        lp = scan_length_prefixed_strings(footer)
        if lp:
            print("\nAll length-prefixed .rsb strings in footer:")
            for off, n, s in lp:
                label = ""
                if dmg and off == dmg[0] + 1 and s == dmg[1]:
                    label = "  [damage texture]"
                print(f"  footer+0x{off:X}: len={n} {s}{label}")

        plain = scan_plain_rsb_strings(footer, base=(payload_end or 0))
        if plain:
            print("\nPlain .rsb strings in footer:")
            for off, s in plain:
                print(f"  abs 0x{off:X}: {s}")

        print(f"\nFooter hexdump, first {footer_dump} bytes:")
        print(hexdump(footer, base=(payload_end or 0), max_bytes=footer_dump))


def main() -> int:
    ap = argparse.ArgumentParser(description="Inspect Red Storm .rsb headers, payload boundaries, and possible footer metadata.")
    ap.add_argument("files", nargs="+", help=".rsb files to inspect")
    ap.add_argument("--footer-dump", type=int, default=256, help="bytes of footer to hexdump")
    args = ap.parse_args()

    for name in args.files:
        try:
            inspect_file(Path(name), args.footer_dump)
        except Exception as e:
            print(f"\nERR {name}: {e}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
