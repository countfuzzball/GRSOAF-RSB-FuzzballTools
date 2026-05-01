# RSB Tools (Ghost Recon / Sum of All Fears)

LLM-assisted Python scripts for inspecting, unpacking, and repacking `.rsb` texture files used by **Tom Clancy's Ghost Recon (2001)** and **The Sum of All Fears (2002)**, with experimental support for engine-specific RSB metadata.

This project is intended for practical reverse-engineering and modding workflows rather than as a complete or authoritative specification of the RSB format.

---

## Important Note About This Project

These scripts are **LLM-generated / LLM-assisted**.

They were created through an iterative process of:

- comparing known-good RSB files
- testing against real Ghost Recon / Sum of All Fears assets
- checking output in RSBEditor and in-game
- refining assumptions based on byte-level differences
- using existing community research as a foundation

Because of this, the code should be treated as **experimental reverse-engineering tooling**, not polished production software.

Expect mistakes, false assumptions, edge cases, and weird files that break things.

---

## Acknowledgements

This work is heavily based on and cross-referenced against AlexKimov's excellent **RSE file formats** research:

https://github.com/AlexKimov/RSE-file-formats

In particular, the RSB-related documentation and Noesis plugin work in that repository provided a major foundation for understanding the structure of Red Storm Entertainment texture files.

This project would not exist in its current form without that prior research.

Additional inspiration and comparison points came from older community tools and modding utilities, including:

- RSBEditor
- RSBTool
- Ghost Recon / Sum of All Fears community modding knowledge
- direct testing against publicly available game/mod assets and custom-made RSB files

---

## Overview

This repository contains Python utilities for working with Red Storm Entertainment’s proprietary **RSB texture format**, including:

- inspecting RSB headers and metadata
- extracting textures to standard formats such as PNG
- rebuilding images back into RSB files
- experimenting with engine-specific fields such as mipmaps, surfaces, damage textures, and animation records

The main goal is to support modding workflows, especially:

- porting textures and maps between Ghost Recon and The Sum of All Fears
- fixing incompatible or broken textures
- documenting unknown RSB fields through practical testing
- creating scriptable alternatives to old closed-source tools

---

## Current Status

This is a **work-in-progress reverse-engineering project**.

Some features work well for tested files. Others are partial, fragile, or based on current best guesses.

The project currently focuses mainly on practical compatibility with:

- Ghost Recon
- Ghost Recon: Desert Siege
- Ghost Recon: Island Thunder
- The Sum of All Fears

---

## Features

### Implemented / Partially Working

- RSB header inspection
- RSB version detection
- texture dimension parsing
- format detection for common payload types
- PNG extraction
- PNG to RSB rebuilding
- RSB v8 writing
- partial RSB v9 writing / compatibility
- ARGB8888 handling
- ARGB1555 handling
- ARGB4444 handling
- RGB565 handling
- basic mipmap field support
- surface type parsing/writing
- damage texture reference parsing/writing
- basic animation record support
- optional generation of multiple extraction candidates where byte order is ambiguous

### Experimental / Incomplete

- full RSB v9 support
- complete animation block support
- scrolling animation fields
- tiled / subsampling options
- compression-related flags
- distortion-map metadata
- robust automatic channel-order detection
- robust automatic payload-offset detection
- formal validation against every known RSB variant

---

## Known Limitations

RSB files are quirky.

Known pain points include:

- channel ordering can vary or be ambiguous
- some files appear to require shifted payload offsets
- RSBEditor-generated files may differ slightly from shipped game assets
- animation records can interact awkwardly with mipmap fields
- some metadata fields are still guessed rather than fully understood
- case-sensitive filenames can cause trouble when preparing assets on Linux for Windows games

Always test rebuilt RSB files in the actual target game.

---

## Why This Exists

The original tools for working with RSB files are useful but limited:

- some are closed-source
- some only support specific RSB versions
- some only export to BMP
- some are tied to very old software or workflows
- some behaviours are undocumented

This project exists to make RSB experimentation more transparent, scriptable, and reproducible.

It is especially aimed at people doing weird modding work where old tools are not quite enough.

---

## Contributing

Contributions, notes, corrections, and sample comparisons are welcome.

Especially useful contributions include:

- known-good RSB files with clear provenance
- before/after files produced by RSBEditor
- byte-level notes on unknown fields
- examples of RSBs that fail to extract or repack correctly
- confirmation of in-game behaviour across Ghost Recon and The Sum of All Fears

Please keep copyright in mind when sharing samples. Prefer small custom-made test files where possible.

---

## Disclaimer

This project is unofficial and is not affiliated with Red Storm Entertainment or Ubisoft.

It is a fan reverse-engineering / modding project intended for interoperability, preservation, and experimentation.

No original game assets are included unless explicitly stated otherwise.
