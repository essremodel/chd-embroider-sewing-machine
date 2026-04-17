# Luxury Bath Embroidery Files

This repository contains the source artwork, generated embroidery files, and lightweight review tooling for the Luxury Bath logo embroidery project.

## Included deliverables

- `LBATH1C.PES` and `LBATH3C.PES`
- `luxbath_leftchest_1c.svg` and `luxbath_leftchest_3c.svg`
- stitch previews in `previews/`
- email-ready copies in `export/`
- the generator script `make_luxbath_embroidery.py`
- the local viewer script `pes_viewer.py` and launcher `Open PES Viewer.command`

## Source assets

- `LuxuryBath-bybc-black-horizontal.eps`
- `LuxuryBath-bybc-black-vertical.eps`
- `LuxuryBath-bybc-pantone-coated-horizontal.eps`
- `LuxuryBath-final-pantone-coated-vertical.eps`
- `luxury-bath-standards-final-v3 25.pdf`

## Current sizing

The generated `PES` files are currently scaled to about `7.02 in x 0.95 in` (`178.4 mm x 24.2 mm`), which fits a Brother `6x10` hoop and is larger than a standard left-chest placement.

## Regenerating files

The generator assumes a macOS environment with Ink/Stitch and Inkscape available. Re-run:

```bash
source .venv/bin/activate
python make_luxbath_embroidery.py
```

## Notes

`export/` is a convenience folder for emailing the key outputs without digging through the working directory.
