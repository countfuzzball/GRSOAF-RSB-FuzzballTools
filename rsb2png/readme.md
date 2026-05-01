# RSB to PNG Smart Detect Converter

A Python-based converter for extracting Red Storm Bitmap `.rsb` textures to `.png`.

This tool is intended for working with texture files from Red Storm Entertainment games such as:

- Tom Clancy's Ghost Recon
- Ghost Recon: Desert Siege
- Ghost Recon: Island Thunder
- The Sum of All Fears

It can inspect supported `.rsb` files, detect their version and pixel format, and export them as standard PNG images.

This project is part of a wider effort to understand, preserve, inspect, unpack, and eventually repack classic Red Storm `.rsb` texture files.

## What it does

The script reads `.rsb` files and converts supported raw bitmap formats into PNG.

Currently supported output formats include:

- RGB565
- RGB888
- ARGB1555
- ARGB4444
- ARGB8888

It also detects, but does not currently decode:

- Paletted RSBs
- DXT-compressed RSBs

Unsupported formats will be reported cleanly rather than silently producing broken output.

## Requirements

Python 3 is required.

The script also requires Pillow:

    pip install pillow

## Basic usage

Convert a single `.rsb` file:

    python3 rsb_to_pngsmartdetect_versioned_grouped.py texture.rsb

This will create a PNG beside the original file.

Example:

    texture.rsb.png

## Convert to a specific output file

    python3 rsb_to_pngsmartdetect_versioned_grouped.py texture.rsb -o texture.png

The `-o` / `--output` option can only be used when converting a single input file.

## Convert a directory

    python3 rsb_to_pngsmartdetect_versioned_grouped.py ./textures

By default, this only scans the given directory itself.

## Convert a directory recursively

    python3 rsb_to_pngsmartdetect_versioned_grouped.py ./textures --recursive

This will search through all subdirectories for `.rsb` files.

## Continue after errors

When batch-converting many files, some files may be unsupported, damaged, paletted, compressed, or otherwise unusual.

Use `--keep-going` to continue converting the rest:

    python3 rsb_to_pngsmartdetect_versioned_grouped.py ./textures --recursive --keep-going

## Group output by RSB version and format

For larger texture dumps, it can be useful to sort exported PNGs by RSB version and detected pixel format:

    python3 rsb_to_pngsmartdetect_versioned_grouped.py ./textures --recursive --group-by-format

This creates output like:

    output/
      v8/
        ARGB8888/
          texture.png
      v9/
        RGB565/
          another_texture.png

You can also specify the output folder:

    python3 rsb_to_pngsmartdetect_versioned_grouped.py ./textures --recursive --group-by-format --group-output-dir ./converted

## ARGB8888 notes

ARGB8888 RSB files are the trickiest format currently handled by the script.

Internally, the 32-bit texture payloads are stored in BGRA by default, but we need to read it out as ARGB. This is the default way now.

The byte order can be changed with --argb8888-order <bgra/rgba, etc>

e.g:
python3 rsb_to_pngsmartdetect_versioned_grouped.py texture.rsb --argb8888-order argb --payload-shift 0


Additionally, offsets can be specified with --payload-shift 0-3, which will shift where the script starts reading the image data by 0 to 3 bytes.


## Brute-force ARGB8888 variants

Some 32-bit RSB files are inconsistent or ambiguous. To help with that, the script can export all ARGB8888 interpretation variants:

    python3 rsb_to_pngsmartdetect_versioned_grouped.py texture.rsb --write-all-8888-variants

This writes all combinations of:

- 4 byte orders:
  - bgra
  - rgba
  - argb
  - abgr

- 4 payload shifts:
  - off0
  - off1
  - off2
  - off3

Example output:

    texture.rsb.off0.bgra.png
    texture.rsb.off0.rgba.png
    texture.rsb.off0.argb.png
    texture.rsb.off0.abgr.png
    texture.rsb.off1.bgra.png
    ...

This is useful when manually comparing outputs to determine which one is visually correct.

For most files, start by checking:

    off0.argb.png

## Payload shift

Some ARGB8888 files may appear to have their image payload start one, two, or three bytes later than expected.

You can manually specify this with:

    --payload-shift 0
    --payload-shift 1
    --payload-shift 2
    --payload-shift 3

Example:

    python3 rsb_to_pngsmartdetect_versioned_grouped.py texture.rsb --argb8888-order argb --payload-shift 0

Again, `argb` with `payload-shift 0` is the recommended first choice.

## Command examples

Convert one file normally:

    python3 rsb_to_pngsmartdetect_versioned_grouped.py c02_ground.rsb

Convert one ARGB8888 file using the usually-correct option:

    python3 rsb_to_pngsmartdetect_versioned_grouped.py c02_ground.rsb --argb8888-order argb --payload-shift 0

Export all ARGB8888 test variants:

    python3 rsb_to_pngsmartdetect_versioned_grouped.py c02_ground.rsb --write-all-8888-variants

Convert a folder recursively and continue after errors:

    python3 rsb_to_pngsmartdetect_versioned_grouped.py ./map_textures --recursive --keep-going

Convert a folder recursively and group by version/format:

    python3 rsb_to_pngsmartdetect_versioned_grouped.py ./map_textures --recursive --group-by-format --keep-going

Convert a folder recursively into a specific grouped output folder:

    python3 rsb_to_pngsmartdetect_versioned_grouped.py ./map_textures --recursive --group-by-format --group-output-dir ./png_output --keep-going

## Output messages

Successful conversions print information such as:

    OK texture.rsb -> texture.rsb.png | v8 256x256 ARGB8888 header_end=0x23, order=argb, shift=0

This tells you:

- source file
- output file
- RSB version
- image dimensions
- detected format
- header end offset
- ARGB8888 byte order, if relevant
- payload shift, if relevant
- number of trailing bytes ignored, if present

Trailing bytes are not necessarily an error. In many RSB files, data after the image payload may contain engine metadata.

## Current limitations

The script does not currently support decoding:

- Paletted RSB files
- DXT-compressed RSB files

The script focuses on raw bitmap-style RSB textures.

It also does not currently attempt to fully interpret all engine metadata stored after the image payload, such as material flags, surface types, animation references, mipmap metadata, damage texture data, or transparency flags.

Those areas are still under active research.

## Why this exists

The RSB format is poorly documented, and the old official and community tools are limited, Windows-centric, or tied to very old workflows.

This script is intended to make RSB inspection and conversion easier from a modern Python environment, especially when working with large texture sets from classic Red Storm games.

It is also useful for modding and preservation work, particularly when moving assets between Ghost Recon and The Sum of All Fears.

## Notes for modders

If you are converting ARGB8888 textures and the output looks wrong, do not assume the file is broken.

Try this first:

    --argb8888-order argb --payload-shift 0

If that still looks wrong, use:

    --write-all-8888-variants

Then compare the generated PNGs manually.

In most real-world cases tested so far, `off0.argb.png` is the one you will want.

## License

GPL 3.0

## Credits

This tool was developed through experimentation with publicly available RSB files, modding tools, and custom-made test files.

Research and implementation were assisted by LLM-generated Python scripting.

Further work on the broader Red Storm file format ecosystem has been informed by public reverse-engineering resources, including Alex Kimov's RSE file format research:

https://github.com/AlexKimov/RSE-file-formats
