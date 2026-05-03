# RSB Inspector

A small Python toolkit for inspecting Red Storm Entertainment `.rsb` texture files, with a focus on the footer metadata used by **Ghost Recon**, **Island Thunder**, and **The Sum of All Fears** era tools.

The current refactor changes the inspector from a loose collection of offset guesses into a **resolved, top-to-bottom footer walk**. This is especially useful for RSBEditor-style files where animation records move later fields, such as mipmap count, subsampling, damage texture, and surface/material ID, away from their simple fixed offsets.

## What it does

`rsb_inspect.py` reports:

- RSB header information
- guessed image format
- base image payload boundaries
- resolved footer metadata
- animation frame records
- mipmap count and mipmap payload ranges
- alpha blend and alpha test metadata
- game/editor flags such as gunshot, grenade, LOS, foliage, and water
- scrolling metadata
- tiled, compress-on-load, distortion map, and subsampling fields
- damage texture record
- final surface/material ID
- optional raw scans for `.rsb` strings
- footer hexdump

The important part of this refactor is that the inspector now presents the file in the order the metadata actually appears, rather than showing fixed offsets and then warning that later fields were consumed by animation records.

## Why this refactor exists

RSBEditor-style non-animation files appear to store some values at fixed footer positions:

```text
footer+0x35  mipmap count
footer+0x39  subsampling
footer+0x3D  damage/surface tail
```

Animation-enabled files are different. Animation frame records begin earlier, at `footer+0x31`, so the fixed `footer+0x35` and `footer+0x39` positions become part of the variable animation data.

The resolved animation tail layout is currently understood as:

```text
footer+0x31  uint32 frame_count
             repeated frame records:
               uint32 name_length
               char[name_length] frame_name, including NUL
             uint32 mipmap_count
             uint32 subsampling
             damage/surface tail
```

So an animation file is no longer displayed as:

```text
footer+0x35  mipmap count field consumed by animation tail
footer+0x39  subsampling field consumed by animation tail
```

Instead, it is displayed using the actual resolved offsets inside the animation tail.

## Files

```text
rsb_inspect.py   command-line inspector
rsb_format.py    RSB header parsing, payload sizing, footer/mipmap splitting
rsb_footer.py    footer metadata parsing and human-readable formatting
```

## Requirements

Python 3.10 or newer is recommended.

The inspector itself uses only the Python standard library.

## Basic usage

Inspect one file:

```bash
python rsb_inspect.py texture.rsb
```

Inspect several files:

```bash
python rsb_inspect.py *.rsb
```

Show more or less of the footer hexdump:

```bash
python rsb_inspect.py texture.rsb --footer-dump 512
```

Enable extra exploratory string scans:

```bash
python rsb_inspect.py texture.rsb --raw-scans
```

`--raw-scans` is useful when investigating unknown or hand-edited files. The normal output prefers the resolved parser so the report stays readable.

## Example output shape

The exact values will depend on the file, but the current inspector output is organised like this:

```text
=== example.rsb ===
Header:
  file size:        ...
  version:          ...
  dimensions:       ...
  format guess:     ...
  payload start:    ...

Base image payload:
  payload size:     ...
  payload end:      ...

Resolved footer metadata:
  footer start:      ...
  footer size:       ...
  mipmap count:      ...
  mipmap source:     ...
  subsampling:       ...
  animation frames:  ...

Footer walk, resolved top-to-bottom:
  footer+0x04 alpha blend enabled byte: ...
  footer+0x05 alpha test enabled byte: ...
  ...
  footer+0x31 animation frame count uint32: ...
  ...
  footer+0x67 mipmap count uint32: ...
  footer+0x6B subsampling uint32: ...
  footer+0x6F damage texture enabled byte: ...
  footer+0x70 surface int32: ...

Mipmap payloads after footer:
  mip 1: ...
  mip 2: ...

Footer hexdump, first 256 bytes:
  ...
```

## Current footer model

The inspector uses v8/v9 footer offsets as the canonical layout.

For some older examples, v6-style footer fields appear to be shifted one byte earlier. The code keeps that compatibility path, but the current refactor is primarily aimed at v8/v9 RSBEditor-style files.

### Fixed prefix fields

The known v8/v9-style prefix includes:

```text
footer+0x04  alpha blend enabled
footer+0x05  alpha test enabled
footer+0x06  mipmaps enabled
footer+0x07  animation enabled
footer+0x08  scrolling enabled
footer+0x09  tiled enabled
footer+0x0A  compress on load
footer+0x0B  distortion map
footer+0x0C  game/editor flags
footer+0x10  source blend function
footer+0x14  destination blend function
footer+0x18  alpha test compare function
footer+0x1C  alpha reference value
footer+0x1D  scrolling type
footer+0x21  primary scroll/rotation rate
footer+0x25  secondary scroll rate
footer+0x29  animation type
footer+0x2D  animation delay
```

### Non-animation tail

For files without animation frame records:

```text
footer+0x35  mipmap count byte
footer+0x39  subsampling byte
footer+0x3D  damage/surface tail
```

### Animation tail

For files with animation frame records:

```text
footer+0x31  animation frame count
             animation frame records
             uint32 mipmap count
             uint32 subsampling
             damage/surface tail
```

This is the main behavioural change in the refactored inspector.

## Damage/surface tail

The currently modelled damage/surface tail is:

Damage disabled:

```text
uint8  damage_enabled = 0
int32  surface_id
```

Damage enabled:

```text
uint8  damage_enabled = 1
uint32 damage_texture_name_length
char[] damage_texture_name, including NUL terminator
int32  surface_id
```

Known surface IDs are mapped to the entries exposed by RSBEditor, including values such as concrete, wood, metal, sand, water, foliage, gravel, glass, and others. `-1` means no surface.

## Mipmap splitting

The loader treats the RSB file as:

```text
header
base image payload
footer metadata
optional generated mipmap payloads
```

When mipmaps are enabled, `rsb_format.py` uses the resolved mipmap count and expected image sizes to peel mipmap payloads off the end of the file, leaving `RSBFile.footer` as metadata only.

For animation files, the mipmap count is read from the animation tail rather than from the old fixed `footer+0x35` position.

## Supported formats

The parser currently recognises these uncompressed/raw layouts from the header bit fields:

- `RGB565`
- `ARGB1555`
- `ARGB4444`
- `ARGB8888`
- `RGB888`

DXT values are recognised at a basic level, but DXT sizing is still approximate and should be treated as investigative rather than final.

Paletted or unusual payloads may be reported as unsupported for payload/footer splitting.

## Development notes

This project is reverse-engineering work. Field names are based on controlled edits, RSBEditor behaviour, game/editor observations, and comparison between generated and real files.

That means:

- some labels are best-known names, not official documentation
- some fields may be ignored by the game or editor in certain combinations
- RSBEditor may rewrite or normalise fields when saving
- engine behaviour is ultimately more important than byte-level appearance

The current reader/writer alignment is strongest for v8/v9 RSBEditor-style files using the modelled footer layouts.

## Suggested validation workflow

When changing the parser or writer, test at least these combinations:

```text
clean default
surface only
damage texture only
damage texture + surface
mipmaps only
mipmaps + subsampling
mipmaps + damage texture + surface
animation frames only
animation + damage texture
animation + damage texture + surface
animation + mipmaps
animation + mipmaps + subsampling
animation + mipmaps + damage texture + surface
```

A good sanity check is:

1. create or save a sample in RSBEditor
2. inspect it with `rsb_inspect.py`
3. generate a comparable file with the writer
4. inspect both files
5. confirm that all resolved fields agree
6. open the generated file in RSBEditor and in-game

## Limitations

Known limitations include:

- no image extraction in this inspector layer
- no full DXT block-accurate parser yet
- no official RSB specification
- unknown fields may still exist
- v8/v9 footer logic is the best-supported path
- v6 and older files may need additional samples

## Status

The refactored inspector is intended to be the readable, user-facing view of the current RSB footer model. The older exploratory scans are still available behind `--raw-scans`, but the default output now favours a clean, resolved, linear explanation of the file.
