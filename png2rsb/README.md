# PNG to RSB Writer

A work-in-progress Python writer for creating Red Storm Entertainment `.rsb` texture files from PNG images.

This tool is primarily aimed at modding and research work around:

- Tom Clancy's Ghost Recon
- Ghost Recon: Desert Siege / Island Thunder
- The Sum of All Fears

The script can currently write simple **V8** and **V9** RSB files using raw, uncompressed pixel data, with experimental support for several pieces of RSBEditor-style engine metadata.

## Status

This writer is experimental.

It is intended for controlled testing, texture conversion, and reverse-engineering work rather than being a fully complete RSB authoring tool. The generated files are based on observed RSBEditor output and custom test samples.

Some metadata fields are understood well enough to write reliably. Others are still tentative and should be verified in-game and with RSBEditor.

## Requirements

- Python 3
- Pillow

Install Pillow with:

    python -m pip install Pillow

## Basic Usage

    python png_to_rsb_v89_mipmap_anim_damage_surface_fixed.py input.png output.rsb

By default, this writes a:

- Version 8 RSB
- ARGB8888-style texture
- BGRA byte order
- Raw/uncompressed payload
- No mipmaps
- No surface material
- No damage texture
- No animation frames
- No alpha-test or alpha-blend metadata

## Supported RSB Versions

The writer can currently emit:

- `--version 8`
- `--version 9`

Example:

    python png_to_rsb_v89_mipmap_anim_damage_surface_fixed.py input.png output_v8.rsb --version 8
    python png_to_rsb_v89_mipmap_anim_damage_surface_fixed.py input.png output_v9.rsb --version 9

Version 9 files include the extra V9 header fields:

- unknown/reserved int32, default `-1`
- `dxt_type`, default `-1`

Only raw/uncompressed V9 output is currently supported.

    --dxt-type -1

Compressed/DXT output is not currently written.

## Supported Pixel Formats

The writer can currently encode the following raw pixel formats:

| Format | Option |
|---|---|
| ARGB8888 | `--format argb8888` |
| RGB888 | `--format rgb888` |
| RGB565 | `--format rgb565` |
| ARGB1555 | `--format argb1555` |
| ARGB4444 | `--format argb4444` |

Example:

    python png_to_rsb_v89_mipmap_anim_damage_surface_fixed.py input.png output.rsb --format argb8888

For most modern conversion work, `argb8888` is the safest and highest-fidelity option.

## Byte Order Options

For 32-bit and 24-bit payloads, the writer supports multiple byte layouts:

    --byte-order bgra
    --byte-order rgba
    --byte-order argb
    --byte-order abgr

Default:

    --byte-order bgra

`bgra` is intended to match little-endian A8R8G8B8-style storage and is generally the most useful default for ARGB8888 RSB output.

Example:

    python png_to_rsb_v89_mipmap_anim_damage_surface_fixed.py input.png output.rsb --format argb8888 --byte-order bgra

## Vertical Flip

The input PNG can be flipped vertically before writing:

    --flip-y

Example:

    python png_to_rsb_v89_mipmap_anim_damage_surface_fixed.py input.png output.rsb --flip-y

This is useful when dealing with textures extracted from tools or formats where the image orientation differs from what the game expects.

## Alpha Metadata

The writer can set alpha-test and alpha-blend metadata in the RSB footer.

### Alpha Test

    --alpha-test
    --alpha-compare 0
    --alpha-ref 128

Example:

    python png_to_rsb_v89_mipmap_anim_damage_surface_fixed.py leaves.png leaves.rsb --alpha-test --alpha-ref 128

`--alpha-ref` must be between `0` and `255`.

### Alpha Blend

    --alpha-blend
    --src-blend 2
    --dst-blend 7

Example:

    python png_to_rsb_v89_mipmap_anim_damage_surface_fixed.py water.png water.rsb --alpha-blend --src-blend 2 --dst-blend 7

The exact blend values are based on observed RSBEditor-style metadata and should be tested in-game.

## Game / Editor Flags

The writer can set several known RSB game flags:

    --game-flag gunshot
    --game-flag grenade
    --game-flag los
    --game-flag foliage
    --game-flag water

These may also be comma-separated:

    --game-flag gunshot,grenade,los

Known flags:

| Flag | Meaning |
|---|---|
| `gunshot` | Gunshot transparency |
| `grenade` | Grenade transparency |
| `los` | Line-of-sight transparency |
| `foliage` | Foliage flag |
| `water` | Water flag |

Example:

    python png_to_rsb_v89_mipmap_anim_damage_surface_fixed.py bush.png bush.rsb --game-flag gunshot,grenade,los,foliage

## Surface / Material ID

The writer can set a surface/material ID:

    --surface 5

Example:

    python png_to_rsb_v89_mipmap_anim_damage_surface_fixed.py sand.png sand.rsb --surface 5

A value of `-1` means no surface/material:

    --surface -1

Surface IDs are stored as signed 32-bit integers. In observed RSBEditor output, `-1` is represented as:

    FF FF FF FF

## Damage Texture Record

The writer can emit a tentative damage texture record:

    --damage-texture damaged_texture.rsb

Example:

    python png_to_rsb_v89_mipmap_anim_damage_surface_fixed.py grass.png grass.rsb --damage-texture grass_damaged.rsb

The damage texture name must end in `.rsb`.

Damage texture support is still experimental and should be tested in RSBEditor and in-game.

## Mipmaps

The writer can generate and append mipmap levels:

    --mipmap-count 2

Example:

    python png_to_rsb_v89_mipmap_anim_damage_surface_fixed.py input.png output.rsb --mipmap-count 2

Mipmaps are generated by resizing the source PNG using Pillow's Lanczos resampling.

For example, a 64x64 texture with `--mipmap-count 2` will append:

- 32x32 mip level
- 16x16 mip level

The mipmap metadata flag and count are written into the footer.

## Tiled Flag

The writer can set the tiled checkbox-style metadata flag:

    --tiled

Example:

    python png_to_rsb_v89_mipmap_anim_damage_surface_fixed.py tile.png tile.rsb --mipmap-count 2 --tiled

## Subsampling

The writer can set the subsampling metadata value:

    --subsampling 0
    --subsampling 1
    --subsampling 2

Current mapping:

| Value | Meaning |
|---|---|
| `0` | One |
| `1` | Two |
| `2` | Three |

Example:

    python png_to_rsb_v89_mipmap_anim_damage_surface_fixed.py input.png output.rsb --subsampling 2

## Compress On Load

The writer can set the compress-on-load metadata flag:

    --compress-on-load

Example:

    python png_to_rsb_v89_mipmap_anim_damage_surface_fixed.py input.png output.rsb --compress-on-load

This only writes the metadata flag. The tool does not currently compress the pixel payload.

## Distortion Map

The writer can set the distortion-map metadata flag:

    --distortion-map

Example:

    python png_to_rsb_v89_mipmap_anim_damage_surface_fixed.py distortion.png distortion.rsb --distortion-map

## Scrolling Metadata

The writer can emit scrolling metadata.

Enable scrolling:

    --scroll-enabled

Supported scroll types:

    --scroll-type hv
    --scroll-type rotate

Horizontal/vertical style:

    python png_to_rsb_v89_mipmap_anim_damage_surface_fixed.py water.png water.rsb \
      --scroll-enabled \
      --scroll-type hv \
      --scroll-primary 0.5 \
      --scroll-secondary 0.0

Rotation style:

    python png_to_rsb_v89_mipmap_anim_damage_surface_fixed.py swirl.png swirl.rsb \
      --scroll-enabled \
      --scroll-type rotate \
      --scroll-primary 45.0

The exact interpretation of these values should be verified against RSBEditor and in-game behaviour.

## Animation Metadata

The writer can emit experimental animation-style metadata and frame references.

Enable animation:

    --animation-enabled

Supported animation types:

    --animation-type none
    --animation-type oscillate
    --animation-type constant

Add frame references with repeated `--animation-frame` options:

    python png_to_rsb_v89_mipmap_anim_damage_surface_fixed.py base.png animated.rsb \
      --animation-enabled \
      --animation-type constant \
      --animation-delay 0.25 \
      --animation-frame reticle_texture1.rsb \
      --animation-frame reticle_texture2.rsb

Animation frame names must end in `.rsb`.

The writer currently emits the observed frame-count and frame-name record structure from controlled RSBEditor samples, including the spacer bytes seen in those samples.

Animation metadata is still experimental.

## Example Commands

### Simple V8 ARGB8888 RSB

    python png_to_rsb_v89_mipmap_anim_damage_surface_fixed.py input.png output.rsb

### V9 ARGB8888 RSB

    python png_to_rsb_v89_mipmap_anim_damage_surface_fixed.py input.png output_v9.rsb --version 9

### Foliage Texture With Alpha Test and LOS/Gunshot/Grenade Transparency

    python png_to_rsb_v89_mipmap_anim_damage_surface_fixed.py foliage.png foliage.rsb \
      --alpha-test \
      --alpha-ref 128 \
      --game-flag gunshot,grenade,los,foliage

### Water Texture With Alpha Blend, Water Flag, and Scrolling

    python png_to_rsb_v89_mipmap_anim_damage_surface_fixed.py water.png water.rsb \
      --alpha-blend \
      --src-blend 2 \
      --dst-blend 7 \
      --game-flag water \
      --scroll-enabled \
      --scroll-type hv \
      --scroll-primary 0.25 \
      --scroll-secondary 0.0

### Texture With Surface ID and Mipmaps

    python png_to_rsb_v89_mipmap_anim_damage_surface_fixed.py sand.png sand.rsb \
      --surface 5 \
      --mipmap-count 2

### Animated Texture With Mipmaps

    python png_to_rsb_v89_mipmap_anim_damage_surface_fixed.py reticle.png reticle_anim.rsb \
      --animation-enabled \
      --animation-type constant \
      --animation-delay 0.25 \
      --animation-frame reticle_texture1.rsb \
      --animation-frame reticle_texture2.rsb \
      --mipmap-count 2

### Texture With Damage Texture and Surface

    python png_to_rsb_v89_mipmap_anim_damage_surface_fixed.py grass.png grass.rsb \
      --damage-texture grass_damaged.rsb \
      --surface 6

## What This Writer Does Not Currently Support

The writer does not currently support:

- DXT-compressed output
- Paletted RSB output
- Full validation against every Ghost Recon / SOAF engine edge case
- Writing `.map` files
- Editing existing RSBs in place
- Preserving unknown metadata from an original source RSB
- Full RSBEditor parity
- Guaranteed correct behaviour for every animation/damage/mipmap combination

This tool writes new RSBs from PNG input. It does not yet act as a complete round-trip editor.

## Notes on Experimental Metadata

Several footer fields were mapped by comparing controlled RSBEditor output files. The following areas are believed to be usable but should still be treated as research-grade:

- damage texture records
- animation frame references
- scrolling metadata
- alpha blend factors
- subsampling values
- compress-on-load flag
- distortion-map flag
- game transparency flags

The safest workflow is to generate test RSBs, inspect them with the companion inspector scripts, open them in RSBEditor where possible, and then test them in-game.

## Recommended Workflow

1. Start with a known-good PNG.
2. Write a simple ARGB8888 V8 RSB.
3. Confirm it loads in-game.
4. Add one metadata feature at a time.
5. Re-test after each feature.
6. Use inspector output to compare generated files against known-good RSBEditor samples.

Example:

    python png_to_rsb_v89_mipmap_anim_damage_surface_fixed.py input.png test_clean.rsb

    python png_to_rsb_v89_mipmap_anim_damage_surface_fixed.py input.png test_alpha.rsb \
      --alpha-test \
      --alpha-ref 128

    python png_to_rsb_v89_mipmap_anim_damage_surface_fixed.py input.png test_surface.rsb \
      --alpha-test \
      --alpha-ref 128 \
      --surface 5

## Credits

This script is part of an ongoing reverse-engineering and modding research effort around Red Storm `.rsb` textures.

Generated with LLM assistance and based on observed behaviour from public tools, custom-made test RSBs, and comparison against RSBEditor output.

Special thanks / reference:

- AlexKimov's RSE file formats work: https://github.com/AlexKimov/RSE-file-formats

Use at your own risk, and always keep backups of original game files.
