#!/usr/bin/env python3

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageColor, ImageDraw, ImageFilter, ImageOps

from pes_viewer import (
    ROOT,
    DEFAULT_FILES,
    add_glow,
    draw_pill,
    export_readme_assets,
    load_font,
    preview_panel,
    read_stats,
    render_preview,
    vertical_gradient,
)


README_ASSETS = ROOT / "README.assets"


def card_background(size: tuple[int, int]) -> Image.Image:
    image = vertical_gradient(size, "#06111b", "#13344d")
    add_glow(image, (30, -140, 850, 420), "#0c6fa7", 140)
    add_glow(image, (1040, 120, 1820, 900), "#53c1ea", 150)
    return image


def rounded_panel(image: Image.Image, box: tuple[int, int, int, int], *, fill: tuple[int, int, int, int], outline: tuple[int, int, int, int]) -> None:
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle(box, radius=34, fill=fill, outline=outline, width=2)


def fit_summary(stats) -> str:
    if stats.fits_5x7:
        return "Fits 5x7 and 6x10"
    if stats.fits_6x10:
        return "Fits 6x10 only"
    return "Requires a larger hoop"


def build_hero_asset(preview_paths: list[Path], stats_list: list) -> None:
    hero = card_background((1800, 860))
    draw = ImageDraw.Draw(hero)

    heading_font = load_font(72, bold=True)
    eyebrow_font = load_font(20, bold=True)
    subhead_font = load_font(30)
    body_font = load_font(24)
    pill_font = load_font(20, bold=True)
    stat_font = load_font(22, bold=True)
    small_font = load_font(18)

    draw.text((88, 84), "BROTHER NQ1700E  •  PES DELIVERABLES", font=eyebrow_font, fill="#73c3ff")
    draw.text((88, 152), "Luxury Bath", font=heading_font, fill="#f4f8ff")
    draw.text((88, 236), "Embroidery Files", font=heading_font, fill="#f4f8ff")
    draw.multiline_text(
        (92, 346),
        "Source art, generated PES files, preview images,\nand local review tooling for the current\nLuxury Bath embroidery package.",
        font=subhead_font,
        fill="#9eb5cc",
        spacing=12,
    )

    pill_x = 88
    pill_y = 502
    for text, fill, outline, text_fill in [
        ("Brother NQ1700E", "#12304A", "#2A5E89", "#b9d6f7"),
        ("PES format", "#102C24", "#2F7A64", "#b5ead5"),
        ("2 exported variants", "#2A1E11", "#956A2D", "#f8ddb1"),
        ("6x10 hoop fit", "#19192e", "#6760c7", "#d4ceff"),
    ]:
        width, _ = draw_pill(draw, (pill_x, pill_y), text, fill=fill, outline=outline, text_fill=text_fill, font=pill_font)
        pill_x += width + 14

    draw.text((92, 608), "Current exports", font=small_font, fill="#73c3ff")
    draw.text(
        (92, 638),
        f"LBATH1C.PES  •  {stats_list[0].stitches:,} stitches  •  LBATH3C.PES  •  {stats_list[1].stitches:,} stitches",
        font=stat_font,
        fill="#e0eefb",
    )
    draw.text(
        (92, 682),
        "Current export size: 178.4 × 24.2 mm  •  fits 6x10  •  does not fit 5x7",
        font=body_font,
        fill="#afc3d9",
    )

    large_panel = preview_panel(preview_paths[1], (900, 300))
    small_panel = preview_panel(preview_paths[0], (480, 190))

    large_shadow = Image.new("RGBA", hero.size, (0, 0, 0, 0))
    shadow_draw = ImageDraw.Draw(large_shadow)
    shadow_draw.rounded_rectangle((878, 110, 878 + 900, 110 + 300), radius=38, fill=(0, 0, 0, 120))
    hero.alpha_composite(large_shadow.filter(ImageFilter.GaussianBlur(26)))
    hero.alpha_composite(large_panel, (866, 100))

    small_shadow = Image.new("RGBA", hero.size, (0, 0, 0, 0))
    shadow_draw = ImageDraw.Draw(small_shadow)
    shadow_draw.rounded_rectangle((1142, 420, 1142 + 480, 420 + 190), radius=32, fill=(0, 0, 0, 120))
    hero.alpha_composite(small_shadow.filter(ImageFilter.GaussianBlur(22)))
    hero.alpha_composite(small_panel, (1126, 404))

    rounded_panel(hero, (1376, 590, 1738, 782), fill=(7, 18, 30, 208), outline=(56, 87, 120, 255))
    draw.text((1404, 622), "At a glance", font=load_font(24, bold=True), fill="#f4f8ff")
    draw.text((1404, 664), f"{stats_list[1].width_in:.2f}\" wide", font=load_font(40, bold=True), fill="#7dd0ff")
    draw.text((1404, 712), fit_summary(stats_list[1]), font=body_font, fill="#d8e6f4")
    draw.text((1404, 748), "Generated from committed PES files", font=small_font, fill="#97afc8")

    README_ASSETS.mkdir(parents=True, exist_ok=True)
    hero.save(README_ASSETS / "hero-banner.png")


def build_stitch_gallery(preview_paths: list[Path], stats_list: list) -> None:
    canvas = card_background((1800, 1040))
    draw = ImageDraw.Draw(canvas)
    heading_font = load_font(66, bold=True)
    subhead_font = load_font(28)
    card_title_font = load_font(34, bold=True)
    body_font = load_font(22)
    pill_font = load_font(18, bold=True)
    small_font = load_font(18)

    draw.text((88, 70), "Embroidery variants", font=heading_font, fill="#f4f8ff")
    draw.text((90, 150), "Both previews below are rendered from the actual PES outputs committed in this repository.", font=subhead_font, fill="#9eb5cc")

    positions = [(78, 238), (916, 238)]
    labels = ["Single-color export", "Three-color export"]
    for idx, ((x, y), preview_path, stats, label) in enumerate(zip(positions, preview_paths, stats_list, labels)):
        box = (x, y, x + 800, y + 710)
        rounded_panel(canvas, box, fill=(8, 18, 30, 208), outline=(58, 87, 120, 255))

        panel = preview_panel(preview_path, (744, 292))
        canvas.alpha_composite(panel, (x + 28, y + 28))

        draw.text((x + 30, y + 354), DEFAULT_FILES[idx].name, font=card_title_font, fill="#f4f8ff")
        pill_x = x + 30
        pill_y = y + 404
        for text, fill, outline, text_fill in [
            (label, "#12304A", "#2A5E89", "#b9d6f7"),
            (f"{stats.colors} color{'s' if stats.colors != 1 else ''}", "#102C24", "#2F7A64", "#b5ead5"),
            (fit_summary(stats), "#2A1E11", "#956A2D", "#f8ddb1"),
        ]:
            width, _ = draw_pill(draw, (pill_x, pill_y), text, fill=fill, outline=outline, text_fill=text_fill, font=pill_font)
            pill_x += width + 12

        details = [
            ("Stitches", f"{stats.stitches:,}"),
            ("Colors", str(stats.colors)),
            ("Size", f"{stats.width_mm:.1f} × {stats.height_mm:.1f} mm"),
            ("Width", f'{stats.width_in:.2f}"'),
            ("Hoop", "6x10 only" if stats.fits_6x10 and not stats.fits_5x7 else fit_summary(stats)),
        ]
        first_col_x = x + 34
        second_col_x = x + 404
        first_col_y = y + 484
        second_col_y = y + 484
        for idx_detail, (name, value) in enumerate(details):
            col_x = first_col_x if idx_detail < 3 else second_col_x
            row_y = first_col_y + idx_detail * 76 if idx_detail < 3 else second_col_y + (idx_detail - 3) * 76
            draw.text((col_x, row_y), name.upper(), font=small_font, fill="#6f89a7")
            draw.text((col_x, row_y + 28), value, font=body_font, fill="#e3eef9")

    canvas.save(README_ASSETS / "stitch-gallery.png")
def main() -> None:
    README_ASSETS.mkdir(parents=True, exist_ok=True)

    pes_files = [path for path in DEFAULT_FILES if path.exists()]
    exported = export_readme_assets(pes_files, README_ASSETS)
    viewer_overview_path = README_ASSETS / "viewer_overview.png"
    if viewer_overview_path not in exported:
        raise SystemExit("Viewer overview was not generated.")

    stats_list = []
    preview_paths = []
    for path in pes_files:
        pattern, stats = read_stats(path)
        stats_list.append(stats)
        preview_paths.append(render_preview(pattern))

    build_hero_asset(preview_paths, stats_list)
    build_stitch_gallery(preview_paths, stats_list)
    for asset in sorted(README_ASSETS.iterdir()):
        if asset.is_file():
            print(asset)


if __name__ == "__main__":
    main()
