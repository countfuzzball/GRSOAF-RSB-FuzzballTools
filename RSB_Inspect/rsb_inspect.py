#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from rsb_format import expected_mipmap_sizes, hexdump, load_rsb
from rsb_footer import (
    SUBSAMPLING_NAMES,
    describe_footer_linear,
    footer_metadata_to_dict,
    scan_length_prefixed_strings,
    scan_plain_rsb_strings,
)


def _hex(value: int | None) -> str | None:
    return None if value is None else f"0x{value:X}"


def build_inspection_dict(
    path: Path,
    *,
    include_walk: bool = False,
    include_raw_scans: bool = False,
) -> dict[str, Any]:
    """Return a JSON-serialisable inspection result for one RSB file."""
    rsb = load_rsb(path)
    h = rsb.header
    data = rsb.data
    payload_end = rsb.payload_end
    footer = rsb.footer

    result: dict[str, Any] = {
        "file": str(path),
        "file_name": path.name,
        "file_size": len(data),
        "header": {
            "version": h.version,
            "width": h.width,
            "height": h.height,
            "contains_palette": h.contains_palette,
            "bits": {
                "red": h.bits_red,
                "green": h.bits_green,
                "blue": h.bits_blue,
                "alpha": h.bits_alpha,
            },
            "bit_depth_bytes_per_pixel": h.bit_depth,
            "dxt_type": h.dxt_type,
            "format_name": h.format_name,
            "payload_start": h.payload_start,
            "payload_start_hex": _hex(h.payload_start),
        },
        "payload": {
            "base_image_size": rsb.payload_size,
            "base_image_end": payload_end,
            "base_image_end_hex": _hex(payload_end),
            "supported": rsb.payload_size is not None,
        },
        "footer": None,
        "mipmaps": {
            "count": rsb.mipmap_count,
            "count_source": rsb.mipmap_count_source,
            "tiled": rsb.tiled,
            "subsampling": rsb.subsampling,
            "subsampling_name": None if rsb.subsampling is None else SUBSAMPLING_NAMES.get(rsb.subsampling, "unknown"),
            "data_size": len(rsb.mipmap_data),
            "levels": [],
        },
        "warnings": [],
    }

    if h.version > 7:
        result["header"]["v8plus_skipped_7_byte_block"] = {
            "offset": 0x0C,
            "offset_hex": "0xC",
            "raw_hex": data[0x0C:0x13].hex(" "),
        }

    if h.version >= 9:
        dxt_skip_start = h.payload_start - 8
        result["header"]["v9plus_unknown_4_bytes_before_dxt_type"] = {
            "offset": dxt_skip_start,
            "offset_hex": _hex(dxt_skip_start),
            "raw_hex": data[dxt_skip_start:dxt_skip_start + 4].hex(" "),
        }

    if rsb.payload_size is None:
        result["warnings"].append("payload size unknown/unsupported; footer was not calculated")
        return result

    if payload_end is not None and payload_end > len(data):
        result["warnings"].append(f"expected payload exceeds file size by {payload_end - len(data)} byte(s)")
        return result

    result["footer"] = footer_metadata_to_dict(
        footer,
        h.version,
        absolute_footer_start=payload_end,
        include_walk=include_walk,
        include_raw_scans=include_raw_scans,
    )

    if rsb.animation_frame_count is not None:
        result["footer"]["resolved_animation_frame_count"] = rsb.animation_frame_count

    if rsb.mipmap_count:
        sizes = expected_mipmap_sizes(h, rsb.mipmap_count)
        mip_start = (payload_end or 0) + len(footer)
        if sizes is None:
            result["warnings"].append("mipmap count present but size details unavailable")
        else:
            cursor = mip_start
            levels: list[dict[str, Any]] = []
            for idx, (mw, mh, nbytes) in enumerate(sizes, 1):
                levels.append({
                    "index": idx,
                    "width": mw,
                    "height": mh,
                    "size": nbytes,
                    "start": cursor,
                    "start_hex": _hex(cursor),
                    "end": cursor + nbytes,
                    "end_hex": _hex(cursor + nbytes),
                })
                cursor += nbytes
            result["mipmaps"]["levels"] = levels

    return result


def write_json_file(path: Path, obj: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, indent=2, sort_keys=False) + "\n", encoding="utf-8")


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
    ap.add_argument("--json", action="store_true", help="emit JSON to stdout instead of the human-readable report")
    ap.add_argument("--json-out", type=Path, help="write one JSON document to this file; with multiple inputs, the document is a list")
    ap.add_argument("--json-dir", type=Path, help="write one <filename>.json file per input into this directory")
    ap.add_argument("--write-json", action="store_true", help="write one adjacent <filename>.json file per input")
    ap.add_argument("--json-include-walk", action="store_true", help="include the human footer walk lines inside JSON under footer.walk")
    args = ap.parse_args()

    want_json_objects = args.json or args.json_out is not None or args.json_dir is not None or args.write_json
    json_results: list[dict[str, Any]] = []
    had_error = False

    for name in args.files:
        path = Path(name)
        try:
            if want_json_objects:
                obj = build_inspection_dict(
                    path,
                    include_walk=args.json_include_walk,
                    include_raw_scans=args.raw_scans,
                )
                json_results.append(obj)

                if args.json_dir is not None:
                    write_json_file(args.json_dir / f"{path.name}.json", obj)
                elif args.write_json:
                    write_json_file(path.with_name(f"{path.name}.json"), obj)

            if not args.json and args.json_out is None:
                inspect_file(path, args.footer_dump, args.raw_scans)
        except Exception as e:
            had_error = True
            if args.json:
                json_results.append({"file": str(path), "error": str(e)})
            else:
                print(f"\nERR {name}: {e}", file=sys.stderr)

    if args.json_out is not None:
        obj: Any = json_results[0] if len(json_results) == 1 else json_results
        write_json_file(args.json_out, obj)

    if args.json:
        obj = json_results[0] if len(json_results) == 1 else json_results
        print(json.dumps(obj, indent=2, sort_keys=False))

    return 1 if had_error else 0


if __name__ == "__main__":
    raise SystemExit(main())
