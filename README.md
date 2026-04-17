# Luxury Bath Embroidery Files

This repository contains the source artwork, generated embroidery files, and review tooling for the Luxury Bath logo embroidery project.

## Purpose

The main goal of this repo is to keep the current Luxury Bath embroidery deliverables in one place so they can be:

- reviewed before stitch-out
- copied to USB for the embroidery machine
- emailed to vendors or collaborators
- regenerated from the source artwork when sizing or stitch settings change

## Target Machine

These embroidery files are intended for a Brother `NQ1700E` embroidery machine, which reads `PES` design files.

Current machine-target assumptions:

- file format: `PES`
- machine: Brother `NQ1700E`
- current design size: about `178.4 mm x 24.2 mm`
- current design size in inches: about `7.02 in x 0.95 in`
- hoop fit: fits the Brother `6x10` hoop
- hoop fit: does not fit the Brother `5x7` hoop

## Primary Deliverables

Use these files on the machine:

- `LBATH1C.PES`
  - 1-color version
  - about `3208` stitches
- `LBATH3C.PES`
  - 3-color version
  - about `3218` stitches

Supporting working files:

- `luxbath_leftchest_1c.svg`
- `luxbath_leftchest_3c.svg`
- `previews/LBATH1C_preview.png`
- `previews/LBATH3C_preview.png`

Email-ready copies are also bundled in `export/`.

## Design Notes

The current exported `PES` files are long horizontal logo versions sized larger than a typical left-chest logo. At the current width they are more appropriate for a larger front placement or other wide application than for a small polo chest position.

The current stitch files use:

- the Luxury Bath icon
- the `LUXURY BATH` wordmark

The current stitch files do not include:

- `BY BATH CONCEPTS`

That byline was omitted because it becomes too small to sew cleanly in the horizontal logo at smaller embroidery sizes.

## Repository Contents

Source artwork:

- `LuxuryBath-bybc-black-horizontal.eps`
- `LuxuryBath-bybc-black-vertical.eps`
- `LuxuryBath-bybc-pantone-coated-horizontal.eps`
- `LuxuryBath-final-pantone-coated-vertical.eps`
- `luxury-bath-standards-final-v3 25.pdf`

Generated embroidery outputs:

- `LBATH1C.PES`
- `LBATH3C.PES`
- `luxbath_leftchest_1c.svg`
- `luxbath_leftchest_3c.svg`
- `previews/LBATH1C_preview.png`
- `previews/LBATH3C_preview.png`

Tooling:

- `make_luxbath_embroidery.py`
- `pes_viewer.py`
- `Open PES Viewer.command`

Sharing bundle:

- `export/`

## Viewing And Checking Files

To inspect a `PES` file locally:

```bash
./.venv/bin/python pes_viewer.py --info LBATH3C.PES
```

Or use the launcher on macOS:

```bash
./Open\ PES\ Viewer.command
```

The viewer reports:

- stitch count
- color count
- design width and height
- inch conversion
- hoop fit for `5x7` and `6x10`

## USB Transfer For The Brother Machine

Recommended USB workflow:

1. Format a real USB flash drive as `FAT32`.
2. Copy `LBATH1C.PES` and/or `LBATH3C.PES` to the USB root or a single top-level folder.
3. Keep file names simple.
4. Avoid deeply nested folders.
5. Keep the USB relatively clean so the machine can browse it easily.

On the Brother `NQ1700E`, insert the USB drive and load the design through the machine's USB menu.

## Regenerating The Files

The generator script is intended for a macOS environment with:

- Inkscape installed
- Ink/Stitch available
- the local Python virtual environment in `.venv`

To regenerate the working SVG and `PES` outputs:

```bash
source .venv/bin/activate
python make_luxbath_embroidery.py
```

## Notes

- `export/` is included as a quick-send folder for emailing the important outputs.
- This repo is meant to track the current embroidery working set, not to replace the original brand source of truth.
