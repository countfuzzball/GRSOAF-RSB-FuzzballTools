# RSB Inspector

A small Python tool for inspecting Red Storm Entertainment `.rsb` texture files, with a focus on header decoding, payload boundary detection, footer metadata, mipmaps, animation records, surface IDs, damage texture records, and JSON-friendly output for tooling.

This tool is aimed at Ghost Recon / Island Thunder / Sum of All Fears modding and reverse-engineering work. It does **not** convert image data by itself; it tells you what is inside an `.rsb`, where the important byte ranges are, and how the footer appears to be structured.

## Features

- Reads `.rsb` headers and reports:
  - RSB version
  - dimensions
  - palette flag
  - RGBA bit layout
  - byte depth
  - DXT type, where present
  - guessed format name
  - base image payload start/end
- Supports common observed formats:
  - `RGB565`
  - `RGB888`
  - `ARGB1555`
  - `ARGB4444`
  - `ARGB8888`
  - DXT-ish headers, with conservative sizing notes
- Resolves footer metadata in human-readable form:
  - alpha blend
  - alpha test
  - mipmaps
  - animation
  - scrolling
  - tiled
  - compress-on-load
  - distortion map
  - gunshot/grenade/LOS transparency flags
  - foliage/water flags
  - blend functions
  - alpha compare function/reference
  - scroll/rotation rates
  - animation type and delay
  - damage texture tail
  - surface/material ID
- Handles the newer variable animation tail layout:
  - frame count
  - length-prefixed `.rsb` animation frame names
  - mipmap count after animation frame records
  - subsampling after animation frame records
  - damage/surface tail after the animation block
- Handles the fixed non-animation footer layout:
  - mipmap count at the known fixed byte
  - subsampling at the known fixed byte
  - damage/surface tail at the known fixed offset
- Splits footer metadata from appended mipmap payloads when possible.
- Emits either readable terminal output or JSON.
- Can write one JSON report per `.rsb` file.
- Detects early `8BIM` / Photoshop resource trailers and treats them as opaque data instead of misreading them as RSBEditor footer metadata.

## Why the 8BIM handling matters

Some official texture files appear to contain leftover Adobe / Photoshop resource data after the base image payload. These trailers can contain the ASCII marker `8BIM` near the start of the post-image data.

Without special handling, those bytes can be accidentally interpreted as normal RSB footer fields. That leads to nonsense values such as bogus mipmap counts, strange flag bytes, or garbage blend/animation settings.

This tool preserves the raw trailer bytes for inspection, but when an early `8BIM` marker is detected it reports safe default metadata instead of pretending the trailer is a real RSBEditor-style footer.

In plain English: if the file just has Photoshop cruft after the image, the inspector says so and does **not** hallucinate a real footer from it.

## Repository layout

```text
.
├── rsb_inspect.py   # Command-line interface and JSON report builder
├── rsb_format.py    # Header parsing, payload sizing, mipmap splitting
└── rsb_footer.py    # Footer decoding, animation/damage/surface parsing, JSON metadata
```

## Requirements

- Python 3.10 or newer
- No third-party Python packages required

The code uses modern type hint syntax such as `int | None`, so Python 3.9 and older are not recommended.

## Installation

Clone or copy the three Python files into the same directory:

```bash
git clone <your-repo-url>
cd <your-repo-name>
```

Or, if you are just copying files manually, keep these together:

```text
rsb_inspect.py
rsb_format.py
rsb_footer.py
```

Then run:

```bash
python3 rsb_inspect.py path/to/texture.rsb
```

On Windows:

```powershell
python .\rsb_inspect.py .\texture.rsb
```

## Basic usage

Inspect one file:

```bash
python3 rsb_inspect.py texture.rsb
```

Inspect several files:

```bash
python3 rsb_inspect.py texture1.rsb texture2.rsb texture3.rsb
```

Inspect every `.rsb` in a directory:

```bash
python3 rsb_inspect.py *.rsb
```

Show a larger footer hexdump:

```bash
python3 rsb_inspect.py texture.rsb --footer-dump 512
```

Enable exploratory raw scans for `.rsb` strings in the footer:

```bash
python3 rsb_inspect.py texture.rsb --raw-scans
```

## JSON usage

Print JSON to standard output:

```bash
python3 rsb_inspect.py texture.rsb --json
```

Write one JSON file:

```bash
python3 rsb_inspect.py texture.rsb --json-out texture_report.json
```

Write one combined JSON report for multiple files:

```bash
python3 rsb_inspect.py a.rsb b.rsb c.rsb --json-out report.json
```

When multiple input files are used with `--json-out`, the output JSON document is a list.

Write one JSON file per input into a directory:

```bash
python3 rsb_inspect.py *.rsb --json-dir json_reports
```

This writes files like:

```text
json_reports/texture1.rsb.json
json_reports/texture2.rsb.json
json_reports/texture3.rsb.json
```

Write adjacent JSON files beside each input:

```bash
python3 rsb_inspect.py *.rsb --write-json
```

This writes files like:

```text
texture1.rsb.json
texture2.rsb.json
texture3.rsb.json
```

Include the human-readable footer walk inside the JSON output:

```bash
python3 rsb_inspect.py texture.rsb --json --json-include-walk
```

Combine JSON output with raw scans:

```bash
python3 rsb_inspect.py texture.rsb --json --raw-scans
```

## Command-line options

```text
usage: rsb_inspect.py [-h] [--footer-dump FOOTER_DUMP] [--raw-scans]
                      [--json] [--json-out JSON_OUT] [--json-dir JSON_DIR]
                      [--write-json] [--json-include-walk]
                      files [files ...]
```

### Positional arguments

| Argument | Description |
|---|---|
| `files` | One or more `.rsb` files to inspect. |

### Optional arguments

| Option | Description |
|---|---|
| `--footer-dump N` | Number of footer bytes to show in the terminal hexdump. Default: `256`. |
| `--raw-scans` | Print or include exploratory scans for `.rsb` strings found in the footer. |
| `--json` | Emit JSON to standard output instead of the normal human-readable report. |
| `--json-out PATH` | Write one JSON document to `PATH`. With multiple inputs, the document is a list. |
| `--json-dir DIR` | Write one `<filename>.json` report per input into `DIR`. |
| `--write-json` | Write one adjacent `<filename>.json` report beside each input file. |
| `--json-include-walk` | Include the normal footer walk lines inside JSON under `footer.walk`. |

## Human-readable output overview

A normal inspection prints sections like this:

```text
=== texture.rsb ===
Header:
  file size:        8293 bytes
  version:          8
  dimensions:       64x64
  contains_palette: 0
  bits RGBA:        5,6,5,0
  bit depth:        2 byte(s)/pixel
  dxt_type:         None
  format guess:     RGB565
  payload start:    0x23

Base image payload:
  payload size:     8192 bytes
  payload end:      0x2023

Resolved footer metadata:
  footer start:      0x2023
  footer size:       66 bytes
  mipmap count:      0
  mipmap source:     fixed byte @ footer+0x35
  subsampling:       0 (One)
```

The exact output depends on the file version, format, footer size, and whether animation/mipmap records are present.

## JSON output overview

The top-level JSON object contains:

```json
{
  "file": "texture.rsb",
  "file_name": "texture.rsb",
  "file_size": 8293,
  "header": {},
  "payload": {},
  "footer": {},
  "mipmaps": {},
  "warnings": []
}
```

### `header`

The `header` object reports basic RSB header fields:

```json
{
  "version": 8,
  "width": 64,
  "height": 64,
  "contains_palette": 0,
  "bits": {
    "red": 5,
    "green": 6,
    "blue": 5,
    "alpha": 0
  },
  "bit_depth_bytes_per_pixel": 2,
  "dxt_type": null,
  "format_name": "RGB565",
  "payload_start": 35,
  "payload_start_hex": "0x23"
}
```

For v8+ files, the JSON also includes the skipped 7-byte block from the header:

```json
"v8plus_skipped_7_byte_block": {
  "offset": 12,
  "offset_hex": "0xC",
  "raw_hex": "00 00 00 00 00 00 00"
}
```

For v9+ files, it also includes the unknown 4 bytes before the DXT type field:

```json
"v9plus_unknown_4_bytes_before_dxt_type": {
  "offset": 35,
  "offset_hex": "0x23",
  "raw_hex": "ff ff ff ff"
}
```

### `payload`

The `payload` object reports the calculated base image payload:

```json
{
  "base_image_size": 8192,
  "base_image_end": 8227,
  "base_image_end_hex": "0x2023",
  "supported": true
}
```

If the payload size cannot be calculated, `supported` is `false` and the footer is not decoded.

### `footer`

The `footer` object contains decoded footer metadata, including:

- total footer size
- layout shift information
- fixed byte fields
- game flags
- blend functions
- alpha test settings
- scroll/rotation settings
- animation settings
- animation frame records, if detected
- damage texture tail, if detected
- surface/material ID, if detected

Most field objects include both relative footer offsets and absolute file offsets where possible.

Example field object:

```json
"alpha_test_enabled": {
  "offset": 5,
  "offset_hex": "0x5",
  "absolute_offset": 8232,
  "absolute_offset_hex": "0x2028",
  "available": true,
  "value": 1,
  "value_hex": "0x01",
  "enabled": true
}
```

### `mipmaps`

The `mipmaps` object reports the resolved mipmap count and any appended mipmap payload levels:

```json
{
  "count": 2,
  "count_source": "fixed byte @ footer+0x35",
  "tiled": false,
  "subsampling": 0,
  "subsampling_name": "One",
  "data_size": 2560,
  "levels": [
    {
      "index": 1,
      "width": 32,
      "height": 32,
      "size": 2048,
      "start": 8293,
      "start_hex": "0x2065",
      "end": 10341,
      "end_hex": "0x2865"
    },
    {
      "index": 2,
      "width": 16,
      "height": 16,
      "size": 512,
      "start": 10341,
      "start_hex": "0x2865",
      "end": 10853,
      "end_hex": "0x2A65"
    }
  ]
}
```

## Footer layout notes

The inspector uses observed RSBEditor-compatible offsets as its canonical layout.

For v8/v9-style files, known footer fields are treated as starting at the usual offsets:

| Field | Offset |
|---|---:|
| alpha blend enabled | `footer+0x04` |
| alpha test enabled | `footer+0x05` |
| mipmaps enabled | `footer+0x06` |
| animation enabled | `footer+0x07` |
| scrolling enabled | `footer+0x08` |
| tiled enabled | `footer+0x09` |
| compress on load | `footer+0x0A` |
| distortion map | `footer+0x0B` |
| game flags | `footer+0x0C` |
| source blend function | `footer+0x10` |
| destination blend function | `footer+0x14` |
| alpha test compare function | `footer+0x18` |
| alpha test reference | `footer+0x1C` |
| scrolling type | `footer+0x1D` |
| horizontal scroll / rotation rate | `footer+0x21` |
| vertical scroll / secondary rate | `footer+0x25` |
| animation type | `footer+0x29` |
| animation delay | `footer+0x2D` |
| animation frame count | `footer+0x31`, when animation tail is present |
| fixed mipmap count | `footer+0x35`, for non-animation layout |
| fixed subsampling | `footer+0x39`, for non-animation layout |
| fixed damage/surface tail | `footer+0x3D`, for non-animation layout |

For v6 and older observed layouts, the inspector applies a `-1` byte footer offset shift.

## Animation tail layout

Animation-enabled files can use a variable-length tail. In that layout, the mipmap count and subsampling fields are **not** at the fixed non-animation offsets.

The expected shape is:

```text
footer+0x31: uint32 frame_count
repeated frame records:
    uint32 name_length
    char   filename[name_length]    # includes NUL terminator
then:
    uint32 mipmap_count
    uint32 subsampling
then:
    damage/surface tail
```

The inspector validates the animation tail by checking that the frame records contain plausible NUL-terminated `.rsb` filenames.

## Damage/surface tail layout

The tool understands the explicit damage/surface tail used by current writer output and RSBEditor-like files.

Disabled damage texture:

```text
uint8  damage_enabled = 0
int32  surface_id
```

Enabled damage texture:

```text
uint8  damage_enabled = 1
uint32 filename_length
char   filename[filename_length]    # includes NUL terminator
int32  surface_id
```

The final `surface_id` is decoded using the currently known RSBEditor surface list.

## Known surface IDs

| ID | Surface |
|---:|---|
| `-1` | none |
| `0` | Carpet |
| `1` | Concrete |
| `2` | Wood |
| `3` | Metal |
| `4` | Asphalt |
| `5` | Sand |
| `6` | Low Grass |
| `7` | High Grass |
| `8` | Puddle |
| `9` | Water |
| `10` | Drywall |
| `11` | Thin Metal |
| `12` | Thick Metal |
| `13` | Metal Gas Tank |
| `14` | Steam Pipe |
| `15` | Electrical Panel |
| `16` | Snow |
| `17` | Safety Glass |
| `18` | Bullet Resistant Glass |
| `19` | Ice |
| `20` | Mud |
| `21` | Glass |
| `22` | Foliage |
| `23` | Gravel |
| `24` | Glass Shards |
| `25` | Creaky Wood |
| `26` | Deep Sand |
| `27` | Baked Clay |

## Game flag bits

The known game flag byte is decoded as:

| Bit | Meaning |
|---:|---|
| `0x01` | gunshot transparency |
| `0x02` | grenade transparency |
| `0x04` | LOS transparent |
| `0x08` | foliage |
| `0x10` | water |

Unknown bits are not named by the inspector.

## Blend function names

Known blend function values are displayed as:

| Value | Name |
|---:|---|
| `0` | Zero |
| `1` | One |
| `2` | Source Alpha |
| `3` | Inverse Source Alpha |
| `4` | Source Colour |
| `5` | Inverse Source Colour |
| `6` | Destination Colour |
| `7` | Inverse Destination Colour |
| `8` | Both Source Alpha |
| `9` | Both Inverse Source Alpha |

## Alpha test function names

| Value | Name |
|---:|---|
| `0` | Never |
| `1` | Less |
| `2` | Equal |
| `3` | Less/Equal |
| `4` | Greater |
| `5` | Not Equal |
| `6` | Greater/Equal |
| `7` | Always |

## Subsampling names

| Value | Name |
|---:|---|
| `0` | One |
| `1` | Two |
| `2` | Three |
| `3` | Never |

## 8BIM / Photoshop trailer behaviour

When an early `8BIM` marker is found in the post-image trailer:

- the trailer remains available as `footer` data
- mipmap count is forced to `0`
- mipmap data is not split from the trailer
- tiled is reported as `false`
- subsampling is reported as `0` / `One`
- known RSBEditor-style fields are reported as disabled/default values
- JSON fields include `suppressed_from_8bim_trailer: true`
- JSON includes an `opaque_trailer` object explaining the detection

Example JSON fragment:

```json
"opaque_trailer": {
  "detected": true,
  "kind": "8BIM/Photoshop resource data",
  "marker_offset": {
    "offset": 0,
    "offset_hex": "0x0",
    "absolute_offset": 8227,
    "absolute_offset_hex": "0x2023"
  },
  "note": "Raw trailer bytes are preserved, but known RSBEditor-style fields are suppressed to disabled/default values."
}
```

This is intentional. The goal is to avoid false positives from non-RSB metadata.

## Exit status

- `0` means all requested files were inspected successfully.
- `1` means one or more files failed to inspect.

When using `--json`, errors are included as JSON objects:

```json
{
  "file": "bad_file.rsb",
  "error": "file too small for RSB header"
}
```

Without `--json`, errors are printed to standard error.

## Using the modules from Python

You can also import the parser from another Python script.

```python
from pathlib import Path
from rsb_format import load_rsb
from rsb_footer import footer_metadata_to_dict

path = Path("texture.rsb")
rsb = load_rsb(path)

metadata = footer_metadata_to_dict(
    rsb.footer,
    rsb.header.version,
    absolute_footer_start=rsb.payload_end,
    include_walk=True,
    include_raw_scans=True,
)

print(rsb.header.format_name)
print(metadata["fields"]["alpha_test_enabled"])
```

Or build the same JSON structure used by the CLI:

```python
from pathlib import Path
from rsb_inspect import build_inspection_dict

report = build_inspection_dict(
    Path("texture.rsb"),
    include_walk=True,
    include_raw_scans=True,
)

print(report["header"]["format_name"])
print(report["mipmaps"]["count"])
```

## Practical workflows

### Check whether a texture has suspicious Photoshop trailer data

```bash
python3 rsb_inspect.py texture.rsb --json | grep -i 8bim
```

Or inspect normally and look for the `opaque 8BIM/Photoshop trailer` mipmap source line.

### Generate JSON reports for an entire folder

```bash
mkdir -p reports
python3 rsb_inspect.py *.rsb --json-dir reports
```

### Compare footer metadata between files

```bash
python3 rsb_inspect.py original.rsb converted.rsb --json-out compare.json
```

Then diff or inspect `compare.json` with your preferred JSON viewer.

### Find animation frame references

```bash
python3 rsb_inspect.py animated_texture.rsb --raw-scans
```

This prints resolved animation records first, then exploratory `.rsb` string scans if requested.

## Limitations

This is a reverse-engineering inspection tool, not an official RSB specification.

Known limitations:

- The tool does not decode or export image pixels.
- The tool does not write or modify `.rsb` files.
- Paletted or unusual payloads may report unknown payload size.
- DXT payload sizing is conservative and may need refinement with more compressed samples.
- Unknown footer bits are preserved/displayed but not fully interpreted.
- `8BIM` trailers are treated as opaque; the tool does not attempt to parse Photoshop resource blocks.
- Surface IDs are decoded according to the currently known RSBEditor list.
- Footer offsets are based on observed files and may need adjustment for rare variants.

## Troubleshooting

### `payload size unknown/unsupported`

The inspector could not calculate the base image size. This usually means the file is paletted or uses a format that the current sizing logic does not understand.

### `expected payload exceeds file size`

The calculated payload size is larger than the file itself. Possible causes:

- corrupt file
- unsupported format
- incorrect interpretation of the header
- unusual compressed texture layout

### Mipmap count looks wrong

If the file contains an early `8BIM` marker, the tool intentionally suppresses mipmap interpretation and reports count `0`.

If the file is animation-enabled, remember that the mipmap count may live after the animation frame records rather than at the fixed non-animation offset.

### A filename appears in raw scans but not as an animation frame

`--raw-scans` is exploratory. It may find any plausible `.rsb` string in the footer. The resolved animation parser is stricter and only accepts records that fit the expected animation tail layout.

## Development notes

The code is split deliberately:

- `rsb_format.py` avoids importing `rsb_footer.py`, so low-level payload/mipmap splitting does not create a circular dependency.
- `rsb_footer.py` owns the richer interpretation layer and JSON metadata construction.
- `rsb_inspect.py` is intentionally thin: it handles command-line arguments, readable output, and JSON report writing.

This makes it easier to reuse the parser in a GUI or batch conversion tool later.

## Project status

Current focus:

- Reliable RSB inspection
- JSON output suitable for GUI/tools/tests
- Correct handling of fixed and animation-shifted footer fields
- Safe handling of opaque `8BIM` / Photoshop trailer data

## License

GPL 3.0