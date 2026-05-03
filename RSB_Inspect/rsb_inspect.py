#!/usr/bin/env python3
from __future__ import annotations

import argparse
from pathlib import Path

from rsb_format import expected_mipmap_sizes, hexdump, load_rsb
from rsb_footer import (
    SUBSAMPLING_NAMES,
    describe_footer_linear,
    scan_length_prefixed_strings,
    scan_plain_rsb_strings,
)


def inspect_file(path: Path, footer_dump: int, raw_scans: bool) -> None:
    rsb = load_rsb(path)
    h = rsb.header
    data = rsb.data
    payload_end = rsb.payload_end
    footer = rsb.footer

    print(f"\n=== {path} ===")
    print("Header:")
    print(f"  file size:        {len(data)} bytes")
    print(f"  version:          {h.version}")
    print(f"  dimensions:       {h.width}x{h.height}")
    print(f"  contains_palette: {h.contains_palette}")
    print(f"  bits RGBA:        {h.bits_red},{h.bits_green},{h.bits_blue},{h.bits_alpha}")
    print(f"  bit depth:        {h.bit_depth} byte(s)/pixel")
    print(f"  dxt_type:         {h.dxt_type}")
    print(f"  format guess:     {h.format_name}")
    print(f"  payload start:    0x{h.payload_start:X}")

    if h.version > 7:
        print(f"  v{h.version} skipped 7-byte block @ 0x0C: {data[0x0C:0x13].hex(' ')}")

    if h.version >= 9:
        dxt_skip_start = h.payload_start - 8
        print(f"  v9+ unknown 4 bytes before dxt_type @ 0x{dxt_skip_start:X}: {data[dxt_skip_start:dxt_skip_start+4].hex(' ')}")

    print("\nBase image payload:")
    if rsb.payload_size is None:
        print("  payload size:     unknown/unsupported, likely paletted or unusual")
        print("  footer:           not calculated")
        return

    print(f"  payload size:     {rsb.payload_size} bytes")
    print(f"  payload end:      0x{payload_end:X}")
    if payload_end is not None and payload_end > len(data):
        print(f"  WARNING: expected payload exceeds file size by {payload_end - len(data)} byte(s)")
        return

    print("\nResolved footer metadata:")
    print(f"  footer start:      0x{payload_end:X}")
    print(f"  footer size:       {len(footer)} bytes")
    print(f"  mipmap count:      {rsb.mipmap_count}")
    if rsb.mipmap_count_source:
        print(f"  mipmap source:     {rsb.mipmap_count_source}")
    if rsb.subsampling is not None:
        print(f"  subsampling:       {rsb.subsampling} ({SUBSAMPLING_NAMES.get(rsb.subsampling, 'unknown')})")
    if rsb.animation_frame_count is not None:
        print(f"  animation frames:  {rsb.animation_frame_count}")

    print("\nFooter walk, resolved top-to-bottom:")
    if footer:
        for line in describe_footer_linear(footer, h.version):
            print(f"  {line}")
    else:
        print("  no footer bytes found")

    print("\nMipmap payloads after footer:")
    print(f"  mipmap data size: {len(rsb.mipmap_data)} bytes")
    if rsb.mipmap_count:
        sizes = expected_mipmap_sizes(h, rsb.mipmap_count)
        mip_start = (payload_end or 0) + len(footer)
        if sizes is None:
            print(f"  count={rsb.mipmap_count}; size details unavailable")
        else:
            cursor = mip_start
            for idx, (mw, mh, nbytes) in enumerate(sizes, 1):
                print(f"  mip {idx}: {mw}x{mh}, {nbytes} bytes, abs 0x{cursor:X}-0x{cursor+nbytes:X}")
                cursor += nbytes
    else:
        print("  none")

    if raw_scans and footer:
        lp = scan_length_prefixed_strings(footer)
        if lp:
            print("\nRaw scan: all length-prefixed .rsb strings in footer:")
            for off, n, s in lp:
                print(f"  footer+0x{off:X}: len={n} {s}")

        plain = scan_plain_rsb_strings(footer, base=(payload_end or 0))
        if plain:
            print("\nRaw scan: plain .rsb strings in footer:")
            for off, s in plain:
                print(f"  abs 0x{off:X}: {s}")

    if footer:
        print(f"\nFooter hexdump, first {footer_dump} bytes:")
        print(hexdump(footer, base=(payload_end or 0), max_bytes=footer_dump))


def main() -> int:
    ap = argparse.ArgumentParser(description="Inspect Red Storm .rsb headers, payload boundaries, resolved footer metadata, and mipmaps.")
    ap.add_argument("files", nargs="+", help=".rsb files to inspect")
    ap.add_argument("--footer-dump", type=int, default=256, help="bytes of footer to hexdump")
    ap.add_argument("--raw-scans", action="store_true", help="also print exploratory .rsb string scans after the resolved footer walk")
    args = ap.parse_args()

    for name in args.files:
        try:
            inspect_file(Path(name), args.footer_dump, args.raw_scans)
        except Exception as e:
            print(f"\nERR {name}: {e}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
