# RSB Viewer

`RSB Viewer` is a small Tkinter-based GUI for inspecting Red Storm Entertainment `.rsb` texture files, used by games such as *Tom Clancy’s Ghost Recon* and *The Sum of All Fears*.

It provides a friendlier visual interface over the same RSB inspection logic used by the command-line tools. Instead of reading a long terminal dump, you can browse folders, select `.rsb` files, and view their header, payload, footer, mipmap, animation, damage texture, and surface metadata in a structured table.

It can also launch the PNG conversion script from inside the GUI.

## What it does

`RSB Viewer` can:

- open a single `.rsb` file
- open a folder and recursively list `.rsb` files
- display RSB header information
- show guessed pixel format
- show payload start/end offsets
- show footer size
- show mipmap count and mipmap payload locations
- display v8/v9 footer metadata guesses
- show transparency/game flags
- show alpha blend and alpha test fields
- show scrolling/rotation metadata
- show mipmap, tiled, subsampling, compression, and distortion-map fields
- detect possible damage texture records
- detect possible animation frame `.rsb` references
- show surface/material IDs
- launch a PNG conversion dialog
- convert a selected file or folder using the companion converter script

## Requirements

- Python 3.10 or newer recommended
- Tkinter

Tkinter is included with many Python installs, but on some Linux distributions it may need to be installed separately.

For example, on Debian/Ubuntu-based systems:

    sudo apt install python3-tk

The following files should be kept in the same directory:

    rsb_viewer.py
    rsb_format.py
    rsb_footer.py

For PNG conversion from inside the GUI, this file should also be present beside `rsb_viewer.py`:

    rsb_to_pngsmartdetect_versioned_grouped.py

If the converter script is missing, the viewer can still inspect files, but the `Convert to PNG` function will not run.

## Usage

Run the viewer with:

    python3 rsb_viewer.py

On Windows:

    py rsb_viewer.py

or:

    python rsb_viewer.py

## Opening files

Use `Open file` to inspect a single `.rsb`.

The viewer will load the file and display information such as:

- file size
- RSB version
- dimensions
- palette flag
- bit layout
- guessed image format
- payload start
- payload size
- payload end
- footer size
- mipmap count
- tiled flag, if available

## Opening folders

Use `Open folder` to browse a directory tree.

The viewer recursively scans for `.rsb` files and displays them in the left-hand file tree. Directories that do not contain any `.rsb` files are automatically pruned from the tree.

Clicking an `.rsb` file loads its metadata into the right-hand table.

## Field sections

The viewer groups output into sections.

Typical sections include:

    File / Header
    Version-specific bytes
    Mipmap payloads
    Footer field map
    Damage texture record
    Surface setting
    Animation frame .rsb refs
    All length-prefixed .rsb strings
    Plain .rsb strings in footer

Not every file will show every section. The visible sections depend on the file version, whether the payload size can be calculated, whether footer data exists, and whether recognizable metadata is found.

## Converting to PNG

The `Convert to PNG` button opens a conversion dialog for the currently selected file or folder.

The dialog builds and runs a command for:

    rsb_to_pngsmartdetect_versioned_grouped.py

The conversion dialog supports:

- single-file conversion
- folder conversion
- recursive folder conversion
- ARGB8888 byte order selection
- payload shift selection
- writing all ARGB8888 variants
- grouping output by detected format
- keeping going after errors
- optional output directory selection
- live command preview
- live conversion log
- stop button for cancelling a running conversion

## ARGB8888 byte order options

The conversion dialog exposes the following ARGB8888 byte orders:

    bgra
    rgba
    argb
    abgr

This is useful because RSB files can be awkward when interpreted as 32-bit pixel data. Depending on the source file and game/toolchain, the visually correct output may require trying more than one interpretation.

For most normal conversions, use the default first. If the image looks blue-shifted, channel-swapped, or otherwise wrong, try another byte order or use the all-variants option.

## Payload shift options

The converter dialog allows payload shifts of:

    0
    1
    2
    3

This is intended for troublesome files where the apparent image payload starts a byte or two away from the expected offset.

For normal files, leave this at `0`.

## Write all 8888 variants

The `Write all 8888 variants` option tells the converter to output multiple ARGB8888 interpretations.

This is useful when manually investigating files and trying to identify which channel order and payload offset gives the correct visual result.

Use this when:

- the image appears heavily blue-tinted
- alpha looks wrong
- the output looks nearly correct but slightly shifted
- you are unsure whether the file is BGRA, RGBA, ARGB, or ABGR on disk

## Group by format

The `Group by format` option is useful when converting a large folder of mixed RSB files.

It lets the converter place output files into grouped folders based on the detected format, making it easier to sort large texture dumps.

## Keep going on errors

The `Keep going on errors` option is enabled by default.

This is helpful when converting large mod or game directories. If one file fails, the converter will continue trying the rest instead of stopping immediately.

## Folder conversion

When a folder is selected in the file tree, `Convert to PNG` opens the conversion dialog for that folder.

If `Recursive` is enabled, subfolders will also be processed.

This is useful for converting entire map texture folders or mod directories.

## Important notes

This viewer is a research and modding utility. It is not a final, authoritative RSB specification.

Some fields are currently best-effort guesses based on controlled samples, RSBEditor output, and real game files.

Fields marked as unknown, tentative, or “ish” should be treated carefully.

The viewer can show what the current parser understands, but that does not mean every possible RSB variant is fully mapped.

## Relationship to rsb_inspect.py

`rsb_viewer.py` is essentially a GUI companion to the command-line inspection workflow.

Use `rsb_inspect.py` when you want terminal output, hexdumps, copy-pasteable offsets, or scripting-friendly diagnostics.

Use `rsb_viewer.py` when you want to browse many files visually and quickly compare their metadata.

## Limitations

Current limitations include:

- footer field mapping is incomplete
- DXT handling may still be approximate
- paletted files may not fully inspect
- unusual RSB files may show incomplete metadata
- the viewer depends on companion parser files
- the PNG conversion button depends on the external converter script being present
- the GUI does not currently preview the image itself
- blend and alpha compare function names are not fully mapped
- some animation fields are still tentative

## Typical workflow

A practical workflow is:

1. Launch the viewer.
2. Open a folder containing `.rsb` files.
3. Select files in the left-hand tree.
4. Check their format, payload, footer, mipmap, animation, and surface fields.
5. Use `Convert to PNG` on a file or folder.
6. If ARGB8888 output looks wrong, try another byte order or write all variants.
7. Compare the resulting PNGs against known-good game textures or RSBEditor output.

## Project status

Experimental, but useful.

This tool exists to make RSB research less painful by putting the inspection data into a simple GUI.

Expect field names, guesses, offsets, and output behaviour to change as more of the RSB format is understood.
