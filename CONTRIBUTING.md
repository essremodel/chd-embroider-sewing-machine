# Contributing

This repository is maintained as a clean public handoff package for the current Luxury Bath embroidery files.

## Keep Changes Grounded

- Only document behavior and file characteristics that are supported by the committed files.
- Keep README visuals generated from real repo assets.
- Avoid adding unrelated machine exports, scratch files, or local experiments.

## If You Change Outputs

If you change source artwork, the generator, or the committed `PES` files, regenerate the repo artifacts before opening a PR:

```bash
source .venv/bin/activate
python make_luxbath_embroidery.py
python make_readme_assets.py
python pes_viewer.py --info LBATH1C.PES LBATH3C.PES
```

## Repo Scope

Good contributions usually involve:

- improving the committed embroidery outputs
- improving preview and verification tooling
- tightening documentation and file organization
- keeping the shareable `export/` bundle accurate

This repo is not meant to become a general embroidery dump. Keep it focused on the Luxury Bath deliverables.
