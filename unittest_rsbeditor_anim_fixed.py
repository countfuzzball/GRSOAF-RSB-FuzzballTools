#!/usr/bin/env python3
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from PIL import Image


HEADER_V8_SIZE = 0x23
WIDTH = 64
HEIGHT = 32
BYTES_PER_PIXEL = 4
MAIN_PAYLOAD_SIZE = WIDTH * HEIGHT * BYTES_PER_PIXEL
FIXED_FOOTER_PREFIX_LEN = 0x3D

DAMAGE_NAME = b"reticle_ar.rsb\x00"
DAMAGE_NAME_RECORD = b"\x01" + len(DAMAGE_NAME).to_bytes(4, "little") + DAMAGE_NAME

FRAME1 = b"reticle_texture1.rsb\x00"
FRAME2 = b"reticle_texture2.rsb\x00"


def anim_records(mip_count: int = 0, subsampling: int = 0) -> bytes:
    """
    Animation records begin at footer +0x31.

    The old apparent 8-byte spacer after the frame records is now understood as:
      uint32 mipmap_count
      uint32 subsampling

    For animation-only/default files this still appears as 8 zero bytes.
    """
    return (
        (2).to_bytes(4, "little")
        + len(FRAME1).to_bytes(4, "little")
        + FRAME1
        + len(FRAME2).to_bytes(4, "little")
        + FRAME2
        + mip_count.to_bytes(4, "little")
        + subsampling.to_bytes(4, "little")
    )


def make_input_png(path: Path) -> None:
    im = Image.new("RGBA", (WIDTH, HEIGHT))
    px = im.load()

    for y in range(HEIGHT):
        for x in range(WIDTH):
            px[x, y] = (
                (x * 3) & 0xFF,
                (y * 7) & 0xFF,
                (x + y) & 0xFF,
                255,
            )

    im.save(path)


def mip_payload_size(width: int, height: int, count: int) -> int:
    total = 0
    w, h = width, height

    for _ in range(count):
        w = max(1, w // 2)
        h = max(1, h // 2)
        total += w * h * BYTES_PER_PIXEL

    return total


def run_writer(writer: Path, input_png: Path, out_path: Path, *args: str) -> None:
    cmd = [
        sys.executable,
        str(writer),
        str(input_png),
        str(out_path),
        *args,
    ]

    result = subprocess.run(
        cmd,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )

    if result.returncode != 0:
        raise AssertionError(
            "writer failed\n"
            f"cmd: {' '.join(cmd)}\n"
            f"stdout:\n{result.stdout}\n"
            f"stderr:\n{result.stderr}"
        )

    if not out_path.exists():
        raise AssertionError(f"writer did not create output file: {out_path}")


def get_footer(path: Path, mip_count: int = 0) -> bytes:
    data = path.read_bytes()

    footer_start = HEADER_V8_SIZE + MAIN_PAYLOAD_SIZE
    footer_end = len(data) - mip_payload_size(WIDTH, HEIGHT, mip_count)

    if footer_end < footer_start:
        raise AssertionError("calculated footer range is invalid")

    return data[footer_start:footer_end]


def assert_equal(actual: bytes, expected: bytes, label: str) -> None:
    if actual != expected:
        raise AssertionError(
            f"{label} mismatch\n"
            f"actual:   {actual.hex(' ')}\n"
            f"expected: {expected.hex(' ')}"
        )


def assert_prefix_flags(
    footer: bytes,
    *,
    mip_count: int = 0,
    animation_enabled: bool = False,
    tiled: bool = False,
    scroll_enabled: bool = False,
    scroll_type: int = 0,
    subsampling: int = 0,
) -> None:
    if len(footer) < FIXED_FOOTER_PREFIX_LEN and not animation_enabled:
        raise AssertionError(f"footer too short: {len(footer)} bytes")
    if len(footer) < 0x31:
        raise AssertionError(f"footer too short for fixed pre-animation fields: {len(footer)} bytes")

    checks = [
        ("mipmap enabled byte +0x06", footer[0x06], 1 if mip_count > 0 else 0),
        ("animation enabled byte +0x07", footer[0x07], 1 if animation_enabled else 0),
        ("scroll enabled byte +0x08", footer[0x08], 1 if scroll_enabled else 0),
        ("tiled byte +0x09", footer[0x09], 1 if tiled else 0),
        ("scroll type byte +0x1D", footer[0x1D], scroll_type),
    ]

    # Non-animation files store mipmap/subsampling at fixed offsets.
    # Animation files displace these into the variable animation tail.
    if not animation_enabled:
        checks.append(("mipmap count byte +0x35", footer[0x35], mip_count & 0xFF))
        checks.append(("subsampling byte +0x39", footer[0x39], subsampling & 0xFF))

    for name, actual, expected in checks:
        if actual != expected:
            raise AssertionError(f"{name}: got {actual:#x}, expected {expected:#x}")


def test_case(
    name: str,
    writer: Path,
    input_png: Path,
    tmpdir: Path,
    args: list[str],
    expected_tail: bytes,
    *,
    mip_count: int = 0,
    animation_enabled: bool = False,
    tiled: bool = False,
    scroll_enabled: bool = False,
    scroll_type: int = 0,
    subsampling: int = 0,
) -> None:
    out_path = tmpdir / f"{name}.rsb"

    run_writer(writer, input_png, out_path, *args)

    footer = get_footer(out_path, mip_count=mip_count)

    assert_prefix_flags(
        footer,
        mip_count=mip_count,
        animation_enabled=animation_enabled,
        tiled=tiled,
        scroll_enabled=scroll_enabled,
        scroll_type=scroll_type,
        subsampling=subsampling,
    )

    tail_offset = 0x31 if animation_enabled else 0x3D
    actual_tail = footer[tail_offset:]
    assert_equal(actual_tail, expected_tail, name)

    print(f"PASS {name}")


def main() -> int:
    if len(sys.argv) not in (2, 3):
        print(
            "Usage:\n"
            "  python unittest.py ./png_to_rsb_v89_rsbeditor_anim_fixed.py\n"
            "  python unittest.py ./png_to_rsb_v89_rsbeditor_anim_fixed.py ./rsb_test_outputs",
            file=sys.stderr,
        )
        return 2

    writer = Path(sys.argv[1]).resolve()
    if not writer.exists():
        print(f"Writer not found: {writer}", file=sys.stderr)
        return 2

    if len(sys.argv) == 3:
        outdir = Path(sys.argv[2]).resolve()
    else:
        outdir = Path("rsb_writer_test_outputs").resolve()

    outdir.mkdir(parents=True, exist_ok=True)

    input_png = outdir / "input.png"
    make_input_png(input_png)

    tests = [
        {
            "name": "clean_default",
            "args": [],
            "tail": b"\x00" + b"\xFF\xFF\xFF\xFF",
        },
        {
            "name": "surface_sand",
            "args": ["--surface", "5"],
            "tail": b"\x00" + (5).to_bytes(4, "little", signed=True),
        },
        {
            "name": "damage_only_no_surface_plain",
            "args": ["--damage-texture", "reticle_ar.rsb"],
            "tail": DAMAGE_NAME_RECORD + b"\xFF\xFF\xFF\xFF",
        },
        {
            "name": "damage_surface_sand_plain",
            "args": ["--damage-texture", "reticle_ar.rsb", "--surface", "5"],
            "tail": DAMAGE_NAME_RECORD + (5).to_bytes(4, "little", signed=True),
        },
        {
            "name": "mipmaps_only",
            "args": ["--mipmap-count", "2"],
            "tail": b"\x00" + b"\xFF\xFF\xFF\xFF",
            "mip_count": 2,
        },
        {
            "name": "mipmaps_subsampling_three",
            "args": ["--mipmap-count", "2", "--subsampling", "2"],
            "tail": b"\x00" + b"\xFF\xFF\xFF\xFF",
            "mip_count": 2,
            "subsampling": 2,
        },
        {
            "name": "mipmaps_damage_no_surface",
            "args": ["--mipmap-count", "2", "--damage-texture", "reticle_ar.rsb"],
            "tail": DAMAGE_NAME_RECORD + b"\xFF\xFF\xFF\xFF",
            "mip_count": 2,
        },
        {
            "name": "mipmaps_damage_surface_sand",
            "args": [
                "--mipmap-count", "2",
                "--damage-texture", "reticle_ar.rsb",
                "--surface", "5",
            ],
            "tail": DAMAGE_NAME_RECORD + (5).to_bytes(4, "little", signed=True),
            "mip_count": 2,
        },
        {
            "name": "animation_only",
            "args": [
                "--animation-enabled",
                "--animation-type", "constant",
                "--animation-delay", "0.25",
                "--animation-frame", "reticle_texture1.rsb",
                "--animation-frame", "reticle_texture2.rsb",
            ],
            "tail": anim_records() + b"\x00" + b"\xFF\xFF\xFF\xFF",
            "animation_enabled": True,
        },
        {
            "name": "animation_damage_no_surface",
            "args": [
                "--animation-enabled",
                "--animation-type", "constant",
                "--animation-delay", "0.25",
                "--animation-frame", "reticle_texture1.rsb",
                "--animation-frame", "reticle_texture2.rsb",
                "--damage-texture", "reticle_ar.rsb",
            ],
            "tail": anim_records() + DAMAGE_NAME_RECORD + b"\xFF\xFF\xFF\xFF",
            "animation_enabled": True,
        },
        {
            "name": "animation_damage_surface_sand",
            "args": [
                "--animation-enabled",
                "--animation-type", "constant",
                "--animation-delay", "0.25",
                "--animation-frame", "reticle_texture1.rsb",
                "--animation-frame", "reticle_texture2.rsb",
                "--damage-texture", "reticle_ar.rsb",
                "--surface", "5",
            ],
            "tail": anim_records() + DAMAGE_NAME_RECORD + (5).to_bytes(4, "little", signed=True),
            "animation_enabled": True,
        },
        {
            "name": "animation_mipmaps_only",
            "args": [
                "--animation-enabled",
                "--animation-type", "constant",
                "--animation-delay", "0.25",
                "--animation-frame", "reticle_texture1.rsb",
                "--animation-frame", "reticle_texture2.rsb",
                "--mipmap-count", "2",
            ],
            "tail": anim_records(mip_count=2) + b"\x00" + b"\xFF\xFF\xFF\xFF",
            "mip_count": 2,
            "animation_enabled": True,
        },
        {
            "name": "animation_mipmaps_subsampling_three",
            "args": [
                "--animation-enabled",
                "--animation-type", "constant",
                "--animation-delay", "0.25",
                "--animation-frame", "reticle_texture1.rsb",
                "--animation-frame", "reticle_texture2.rsb",
                "--mipmap-count", "2",
                "--subsampling", "2",
            ],
            "tail": anim_records(mip_count=2, subsampling=2) + b"\x00" + b"\xFF\xFF\xFF\xFF",
            "mip_count": 2,
            "animation_enabled": True,
            "subsampling": 2,
        },
        {
            "name": "animation_mipmaps_damage_no_surface",
            "args": [
                "--animation-enabled",
                "--animation-type", "constant",
                "--animation-delay", "0.25",
                "--animation-frame", "reticle_texture1.rsb",
                "--animation-frame", "reticle_texture2.rsb",
                "--mipmap-count", "2",
                "--damage-texture", "reticle_ar.rsb",
            ],
            "tail": anim_records(mip_count=2) + DAMAGE_NAME_RECORD + b"\xFF\xFF\xFF\xFF",
            "mip_count": 2,
            "animation_enabled": True,
        },
        {
            "name": "animation_mipmaps_damage_surface_sand",
            "args": [
                "--animation-enabled",
                "--animation-type", "constant",
                "--animation-delay", "0.25",
                "--animation-frame", "reticle_texture1.rsb",
                "--animation-frame", "reticle_texture2.rsb",
                "--mipmap-count", "2",
                "--damage-texture", "reticle_ar.rsb",
                "--surface", "5",
            ],
            "tail": anim_records(mip_count=2) + DAMAGE_NAME_RECORD + (5).to_bytes(4, "little", signed=True),
            "mip_count": 2,
            "animation_enabled": True,
        },
        {
            "name": "animation_tiled_scroll_fixed_fields",
            "args": [
                "--animation-enabled",
                "--animation-type", "constant",
                "--animation-delay", "0.25",
                "--animation-frame", "reticle_texture1.rsb",
                "--animation-frame", "reticle_texture2.rsb",
                "--tiled",
                "--scroll-enabled",
                "--scroll-type", "rotate",
                "--scroll-primary", "1.5",
            ],
            "tail": anim_records() + b"\x00" + b"\xFF\xFF\xFF\xFF",
            "animation_enabled": True,
            "tiled": True,
            "scroll_enabled": True,
            "scroll_type": 1,
        },
    ]

    print(f"Writing test files to: {outdir}")

    for t in tests:
        test_case(
            t["name"],
            writer,
            input_png,
            outdir,
            t["args"],
            t["tail"],
            mip_count=t.get("mip_count", 0),
            animation_enabled=t.get("animation_enabled", False),
            tiled=t.get("tiled", False),
            scroll_enabled=t.get("scroll_enabled", False),
            scroll_type=t.get("scroll_type", 0),
            subsampling=t.get("subsampling", 0),
        )

    print(f"\nAll RSB writer footer tests passed.")
    print(f"Created files are in: {outdir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
