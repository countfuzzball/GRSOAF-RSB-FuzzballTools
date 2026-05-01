# RSB Inspect

`rsb_inspect.py` is a small Python inspection tool for Red Storm Entertainment `.rsb` texture files, used by games such as *Tom Clancy’s Ghost Recon* and *The Sum of All Fears*.

It prints header information, payload boundaries, guessed image format, footer metadata guesses, mipmap information, damage texture references, animation frame references, surface/material IDs, and a footer hexdump.

This tool is part of a work-in-progress reverse-engineering effort around the RSB texture format. It is intended for research, modding, debugging, and comparing RSB files produced by different tools.

## What it does

`rsb_inspect.py` can currently report:

- RSB version
- image dimensions
- palette flag
- RGBA bit layout
- guessed image format
- payload start/end offsets
- calculated payload size
- footer size
- mipmap count and mipmap payload sizes
- v8/v9 footer metadata guesses
- game transparency flags
- alpha blend fields
- alpha test fields
- mipmap/tiled settings
- scrolling/rotation metadata
- compress-on-load flag
- distortion-map flag
- subsampling enum
- possible damage texture reference
- possible animation frame `.rsb` references
- final surface/material ID
- raw footer hexdump

The script is especially useful when comparing a known-good RSBEditor-generated file against a generated or modified RSB.

## Important note about format support

`rsb_inspect.py` is an inspector, not the authoritative parser for every possible RSB layout.

There may be some drift between what the `rsb2png` / image conversion side of the toolchain can handle and what `rsb_inspect.py` can currently identify.

In practice, `rsb2png` is currently more robust to the RSB spec than `rsb_inspect.py`.

That means an RSB file may successfully unpack or convert with the image tools while `rsb_inspect.py` still reports incomplete, tentative, or unknown footer information. This is expected for now. The inspector is deliberately conservative and focused on showing what is currently understood, rather than pretending the entire RSB format is fully mapped.

## Requirements

- Python 3.10 or newer recommended
- No third-party Python modules required

The following files should be kept together:

- `rsb_inspect.py`
- `rsb_format.py`
- `rsb_footer.py`

## Usage

Basic usage:

    python3 rsb_inspect.py texture.rsb

Inspect multiple files:

    python3 rsb_inspect.py texture1.rsb texture2.rsb texture3.rsb

Increase or reduce the amount of footer hex shown:

    python3 rsb_inspect.py texture.rsb --footer-dump 512

Default footer dump size is 256 bytes.

## Example output

The output looks broadly like this:

    === texture.rsb ===
    file size:        10895 bytes
    version:          8
    dimensions:       64x32
    contains_palette: 0
    bits RGBA:        8,8,8,8
    bit depth:        4 byte(s)/pixel
    dxt_type:         None
    format guess:     ARGB8888
    payload start:    0x23
    payload size:     8192 bytes
    payload end:      0x2023
    footer size:      123 bytes
    mipmap count:     2
    mipmap data size: 2560 bytes

The exact fields shown will depend on the RSB version, whether the payload size can be calculated, and whether recognizable footer metadata is present.

## Supported and partially supported formats

The inspector currently recognises common raw RSB pixel layouts including:

- RGB565
- ARGB1555
- ARGB4444
- ARGB8888
- RGB888

It also has tentative support for identifying DXT-style formats where the header exposes a DXT type.

Paletted or unusual files may not have a calculable payload size yet. In those cases the tool may report the payload as unknown and skip footer parsing.

## Footer metadata status

Many footer fields are based on controlled comparisons against files saved by RSBEditor.

The following areas are partially mapped:

- game transparency flags
- gunshot transparency
- grenade transparency
- line-of-sight transparency
- foliage flag
- water flag
- alpha blending
- alpha testing
- mipmaps
- tiled flag
- scrolling / rotation
- animation settings
- damage texture references
- subsampling
- compress on load
- distortion map
- surface/material ID

These fields should still be treated as research findings rather than final specification.

When the script says `tentative`, `guess`, `ish`, or `unknown`, take that seriously.

## Surface/material IDs

The final 4 bytes of the footer are currently treated as a signed int32 surface/material ID.

Known examples:

- `FF FF FF FF` = none / -1
- `05 00 00 00` = sand
- `1B 00 00 00` = last known RSBEditor surface entry

Surface IDs appear to start at `0`, with `-1` used for no surface.

## Mipmaps

For files with a recognized base image payload, the inspector attempts to split the file into:

    [header][base image payload][footer metadata][mipmap payloads]

The mipmap count is read from the currently mapped footer field. If the mipmap metadata looks sane, the inspector peels the mipmap data from the end of the file and reports each expected mip level.

If the fields do not look sane, the trailer is left as footer data.

## Version notes

The inspector is primarily built around v8/v9-style RSB files, especially those relevant to *The Sum of All Fears* and later *Ghost Recon* material.

Some older layouts appear shifted by one byte compared with the v8/v9 footer layout. The helper code applies a known adjustment for v6-or-older examples where appropriate.

Known version-specific behaviour:

- v8/v9 files use the current canonical footer offsets
- v6-or-older files may use a one-byte earlier footer layout
- v9+ files include additional header bytes before the DXT type field

## Limitations

Current known limitations:

- footer parsing is incomplete
- DXT sizing is approximate and may need block-accurate handling
- paletted files are not fully handled
- unusual RSB layouts may not split payload/footer/mipmaps correctly
- blend function names are not fully mapped
- alpha compare function names are not fully mapped
- some animation fields are still tentative
- this is not yet a formal RSB specification

For image extraction/conversion, use the dedicated RSB-to-image tooling. This inspector is best used as a diagnostic companion.

## Typical workflow

A useful workflow is:

1. Create or modify an RSB.
2. Run it through `rsb_inspect.py`.
3. Compare the output against a known-good RSBEditor-generated sample.
4. Check whether key fields such as mipmaps, animation references, damage texture references, and surface IDs landed where expected.
5. Test the file in-game.

Example:

    python3 rsb_inspect.py known_good.rsb generated_test.rsb

This makes it easier to spot whether a generated file has accidentally shifted footer records or clobbered metadata.

## Project status

This tool is experimental but useful.

It exists because the RSB format is only partially documented publicly, and a lot of behaviour has to be inferred from real game files, RSBEditor output, and controlled binary comparisons.

Expect the output format and field mappings to change as more of the format is understood.

## Credits

This work is heavily informed by public Red Storm / RSB modding research, controlled sample files, and reverse-engineering experiments.

It is intended for preservation, interoperability, and modding research around older Red Storm Entertainment games.
