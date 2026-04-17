#!/usr/bin/env python3

from __future__ import annotations

import argparse
import base64
import html
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

from PIL import Image, ImageColor, ImageDraw, ImageFilter, ImageFont, ImageOps
from pyembroidery import EmbPattern, write_png


ROOT = Path(__file__).resolve().parent
DEFAULT_FILES = [
    ROOT / "LBATH1C.PES",
    ROOT / "LBATH3C.PES",
]

HOOP_5X7_MM = (127.0, 178.0)
HOOP_6X10_MM = (160.0, 260.0)


@dataclass
class PesStats:
    path: Path
    stitches: int
    colors: int
    width_mm: float
    height_mm: float
    width_in: float
    height_in: float
    fits_5x7: bool
    fits_6x10: bool


def fits_hoop(width_mm: float, height_mm: float, hoop: tuple[float, float]) -> bool:
    short_side, long_side = sorted(hoop)
    design_short, design_long = sorted((width_mm, height_mm))
    return design_short <= short_side and design_long <= long_side


def read_stats(path: Path) -> tuple[EmbPattern, PesStats]:
    pattern = EmbPattern(str(path))
    x0, y0, x1, y1 = pattern.bounds()
    width_mm = (x1 - x0) / 10.0
    height_mm = (y1 - y0) / 10.0
    stats = PesStats(
        path=path,
        stitches=pattern.count_stitches(),
        colors=pattern.count_color_changes() + 1,
        width_mm=width_mm,
        height_mm=height_mm,
        width_in=width_mm / 25.4,
        height_in=height_mm / 25.4,
        fits_5x7=fits_hoop(width_mm, height_mm, HOOP_5X7_MM),
        fits_6x10=fits_hoop(width_mm, height_mm, HOOP_6X10_MM),
    )
    return pattern, stats


def render_preview(pattern: EmbPattern) -> Path:
    handle = tempfile.NamedTemporaryFile(prefix="pes-viewer-", suffix=".png", delete=False)
    handle.close()
    preview_path = Path(handle.name)
    write_png(pattern, str(preview_path))
    return preview_path


def preview_as_data_uri(preview_path: Path) -> str:
    encoded = base64.b64encode(preview_path.read_bytes()).decode("ascii")
    return f"data:image/png;base64,{encoded}"


def row_html(stats: PesStats, image_src: str) -> str:
    fit_5x7 = "Yes" if stats.fits_5x7 else "No"
    fit_6x10 = "Yes" if stats.fits_6x10 else "No"
    return f"""
    <section class="card">
      <div class="preview-wrap">
        <img class="preview" src="{image_src}" alt="Preview for {html.escape(stats.path.name)}" />
      </div>
      <div class="meta">
        <h2>{html.escape(stats.path.name)}</h2>
        <p class="path">{html.escape(str(stats.path))}</p>
        <dl>
          <dt>Stitches</dt><dd>{stats.stitches:,}</dd>
          <dt>Colors</dt><dd>{stats.colors}</dd>
          <dt>Size (mm)</dt><dd>{stats.width_mm:.1f} x {stats.height_mm:.1f}</dd>
          <dt>Size (in)</dt><dd>{stats.width_in:.2f}" x {stats.height_in:.2f}"</dd>
          <dt>Fits 5x7</dt><dd>{fit_5x7}</dd>
          <dt>Fits 6x10</dt><dd>{fit_6x10}</dd>
        </dl>
      </div>
    </section>
    """


def load_font(size: int, *, bold: bool = False, mono: bool = False) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    if mono:
        candidates = [
            "/System/Library/Fonts/SFNSMono.ttf",
            "/System/Library/Fonts/Menlo.ttc",
        ]
    elif bold:
        candidates = [
            "/System/Library/Fonts/SFNSRounded.ttf",
            "/System/Library/Fonts/ArialHB.ttc",
            "/System/Library/Fonts/HelveticaNeue.ttc",
        ]
    else:
        candidates = [
            "/System/Library/Fonts/SFNS.ttf",
            "/System/Library/Fonts/Helvetica.ttc",
            "/System/Library/Fonts/Avenir.ttc",
        ]

    for candidate in candidates:
        try:
            return ImageFont.truetype(candidate, size=size)
        except OSError:
            continue
    return ImageFont.load_default()


def vertical_gradient(size: tuple[int, int], top: str, bottom: str) -> Image.Image:
    width, height = size
    top_rgb = ImageColor.getrgb(top)
    bottom_rgb = ImageColor.getrgb(bottom)
    base = Image.new("RGBA", size)
    draw = ImageDraw.Draw(base)
    for y in range(height):
        mix = y / max(height - 1, 1)
        color = tuple(int(top_rgb[i] * (1.0 - mix) + bottom_rgb[i] * mix) for i in range(3))
        draw.line((0, y, width, y), fill=color + (255,))
    return base


def add_glow(image: Image.Image, box: tuple[int, int, int, int], color: str, blur_radius: int) -> None:
    glow = Image.new("RGBA", image.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(glow)
    draw.ellipse(box, fill=ImageColor.getrgb(color) + (70,))
    image.alpha_composite(glow.filter(ImageFilter.GaussianBlur(blur_radius)))


def fit_label(value: bool) -> tuple[str, str]:
    return ("Fits", "#5fd3a0") if value else ("No fit", "#ff7e7e")


def palette_for(stats: PesStats) -> list[str]:
    if stats.colors >= 3:
        return ["#004F6E", "#0076BC", "#54C1EA"]
    return ["#231F20"]


def preview_panel(preview_path: Path, size: tuple[int, int]) -> Image.Image:
    panel = Image.new("RGBA", size, (12, 16, 24, 255))
    draw = ImageDraw.Draw(panel)
    width, height = size
    for x in range(0, width, 36):
        draw.line((x, 0, x, height), fill=(41, 52, 68, 120), width=1)
    for y in range(0, height, 36):
        draw.line((0, y, width, y), fill=(41, 52, 68, 120), width=1)
    draw.rounded_rectangle((0, 0, width - 1, height - 1), radius=28, outline=(72, 88, 112, 255), width=2)

    preview = Image.open(preview_path).convert("RGBA")
    preview = ImageOps.contain(preview, (width - 96, height - 96), Image.Resampling.LANCZOS)
    shadow = Image.new("RGBA", size, (0, 0, 0, 0))
    shadow_draw = ImageDraw.Draw(shadow)
    px = (width - preview.width) // 2
    py = (height - preview.height) // 2
    shadow_draw.rounded_rectangle(
        (px - 18, py - 18, px + preview.width + 18, py + preview.height + 18),
        radius=24,
        fill=(0, 0, 0, 90),
    )
    panel.alpha_composite(shadow.filter(ImageFilter.GaussianBlur(16)))
    panel.alpha_composite(preview, (px, py))
    return panel


def draw_pill(draw: ImageDraw.ImageDraw, xy: tuple[int, int], text: str, *, fill: str, outline: str, text_fill: str, font: ImageFont.ImageFont) -> tuple[int, int]:
    left, top = xy
    bbox = draw.textbbox((0, 0), text, font=font)
    width = bbox[2] - bbox[0] + 34
    height = bbox[3] - bbox[1] + 18
    draw.rounded_rectangle((left, top, left + width, top + height), radius=height // 2, fill=fill, outline=outline, width=2)
    draw.text((left + 17, top + 8 - bbox[1]), text, font=font, fill=text_fill)
    return width, height


def draw_metric_block(
    image: Image.Image,
    box: tuple[int, int, int, int],
    *,
    label: str,
    value: str,
    accent: str,
    value_font: ImageFont.ImageFont,
    label_font: ImageFont.ImageFont,
) -> None:
    draw = ImageDraw.Draw(image)
    left, top, right, bottom = box
    draw.rounded_rectangle(box, radius=26, fill=(17, 22, 32, 230), outline=(58, 70, 90, 255), width=2)
    draw.rounded_rectangle((left + 18, top + 18, left + 28, bottom - 18), radius=5, fill=ImageColor.getrgb(accent) + (255,))
    draw.text((left + 48, top + 22), label.upper(), font=label_font, fill="#7e91aa")
    draw.text((left + 48, top + 62), value, font=value_font, fill="#f4f8ff")


def export_stat_card(path: Path, stats: PesStats, preview_path: Path, output_path: Path) -> None:
    card = vertical_gradient((1600, 980), "#08111b", "#10253a")
    add_glow(card, (80, 40, 700, 580), "#2A7DBF", 120)
    add_glow(card, (980, 180, 1520, 860), "#54C1EA", 100)
    add_glow(card, (1120, -120, 1660, 360), "#0B5D7D", 120)

    draw = ImageDraw.Draw(card)
    heading_font = load_font(58, bold=True)
    subhead_font = load_font(25)
    section_font = load_font(18, bold=True)
    body_font = load_font(28)
    metric_font = load_font(42, bold=True)
    tiny_font = load_font(18)
    mono_font = load_font(22, mono=True)

    draw.text((84, 70), "Luxury Bath PES Viewer", font=heading_font, fill="#f5f9ff")
    draw.text((86, 144), "Local inspection snapshot generated from the embroidery file itself.", font=subhead_font, fill="#92a7c0")

    chip_y = 204
    next_x = 86
    for chip_text, fill, outline, text_fill in [
        ("Brother NQ1700E", "#12304A", "#2A5E89", "#b9d6f7"),
        ("PES format", "#102C24", "#2F7A64", "#b5ead5"),
        (f"{stats.colors}-color design", "#2A1E11", "#956A2D", "#f8ddb1"),
    ]:
        width, _ = draw_pill(draw, (next_x, chip_y), chip_text, fill=fill, outline=outline, text_fill=text_fill, font=section_font)
        next_x += width + 16

    panel = preview_panel(preview_path, (900, 560))
    card.alpha_composite(panel, (82, 292))

    draw.text((110, 878), "Viewer preview", font=section_font, fill="#74c2ff")
    draw.text((110, 910), "Rendered locally from the `.pes` stitches using the repo's `pes_viewer.py` tool.", font=tiny_font, fill="#97a8bc")

    info_left = 1028
    info_right = 1516

    title = path.stem.replace("_", " ")
    draw.text((info_left, 300), title, font=load_font(42, bold=True), fill="#f4f8ff")
    draw.text((info_left, 352), path.name, font=mono_font, fill="#8ea4bf")

    metric_boxes = [
        ("Stitches", f"{stats.stitches:,}", "#7dc4ff"),
        ("Size", f"{stats.width_mm:.1f} × {stats.height_mm:.1f} mm", "#5fd3a0"),
        ("Inches", f'{stats.width_in:.2f}" × {stats.height_in:.2f}"', "#ffcb6b"),
        ("Colors", str(stats.colors), "#ff8c82"),
    ]
    y = 420
    for label, value, accent in metric_boxes:
        draw_metric_block(card, (info_left, y, info_right, y + 132), label=label, value=value, accent=accent, value_font=metric_font, label_font=section_font)
        y += 148

    fit5_text, fit5_color = fit_label(stats.fits_5x7)
    fit610_text, fit610_color = fit_label(stats.fits_6x10)
    draw.text((info_left, 738), "Hoop fit", font=section_font, fill="#7e91aa")
    draw_pill(draw, (info_left, 772), f"5x7: {fit5_text}", fill="#0f1722", outline=fit5_color, text_fill=fit5_color, font=body_font)
    draw_pill(draw, (info_left, 834), f"6x10: {fit610_text}", fill="#0f1722", outline=fit610_color, text_fill=fit610_color, font=body_font)

    draw.text((info_left, 908), "Thread palette", font=section_font, fill="#7e91aa")
    swatch_x = info_left
    for color in palette_for(stats):
        draw.rounded_rectangle((swatch_x, 938, swatch_x + 62, 968), radius=15, fill=color, outline="#d5e5f7", width=2)
        swatch_x += 82

    output_path.parent.mkdir(parents=True, exist_ok=True)
    card.save(output_path)


def export_overview(cards: list[tuple[Path, PesStats, Path]], output_path: Path) -> None:
    canvas = vertical_gradient((1800, 1160), "#071018", "#15314a")
    add_glow(canvas, (40, -120, 860, 480), "#0d6fa7", 140)
    add_glow(canvas, (1080, 200, 1780, 980), "#5fc6eb", 140)

    draw = ImageDraw.Draw(canvas)
    heading_font = load_font(72, bold=True)
    subhead_font = load_font(28)
    pill_font = load_font(20, bold=True)
    card_title_font = load_font(30, bold=True)
    meta_font = load_font(22)
    small_font = load_font(18)

    draw.text((86, 70), "Luxury Bath Embroidery Snapshot", font=heading_font, fill="#f6faff")
    draw.text((88, 158), "Viewer-generated screenshots for the current Brother NQ1700E PES exports.", font=subhead_font, fill="#9cb2cb")
    draw_pill(draw, (88, 218), "Public README asset", fill="#13293f", outline="#3671a6", text_fill="#b8d9ff", font=pill_font)
    draw_pill(draw, (312, 218), "USB-ready PES files", fill="#102b23", outline="#2f7a64", text_fill="#b5ead5", font=pill_font)

    positions = [(82, 308), (920, 308)]
    for (path, stats, card_path), (x, y) in zip(cards, positions):
        card = Image.open(card_path).convert("RGBA")
        card = ImageOps.contain(card, (798, 720), Image.Resampling.LANCZOS)
        shadow = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
        shadow_draw = ImageDraw.Draw(shadow)
        shadow_draw.rounded_rectangle((x + 10, y + 18, x + card.width + 10, y + card.height + 18), radius=36, fill=(0, 0, 0, 105))
        canvas.alpha_composite(shadow.filter(ImageFilter.GaussianBlur(26)))
        canvas.alpha_composite(card, (x, y))
        draw.rounded_rectangle((x + 22, y + 24, x + 220, y + 76), radius=26, fill=(7, 17, 28, 220), outline=(72, 134, 196, 255), width=2)
        draw.text((x + 46, y + 38), path.stem, font=card_title_font, fill="#e7f0fb")
        draw.text((x + 26, y + card.height + 26), f"{stats.stitches:,} stitches  •  {stats.colors} colors  •  {stats.width_in:.2f}\" wide", font=meta_font, fill="#dce9f7")

    draw.text((90, 1088), "Generated with `./.venv/bin/python pes_viewer.py --export-readme-assets assets/readme`", font=small_font, fill="#8ea7c2")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(output_path)


def export_readme_assets(paths: list[Path], output_dir: Path) -> list[Path]:
    exported: list[Path] = []
    cards: list[tuple[Path, PesStats, Path]] = []
    for path in paths:
        pattern, stats = read_stats(path)
        preview_path = render_preview(pattern)
        card_path = output_dir / f"{path.stem.lower()}_viewer.png"
        export_stat_card(path, stats, preview_path, card_path)
        cards.append((path, stats, card_path))
        exported.append(card_path)
    overview_path = output_dir / "viewer_overview.png"
    export_overview(cards, overview_path)
    exported.insert(0, overview_path)
    return exported


def build_report(paths: list[Path]) -> Path:
    temp_dir = Path(tempfile.mkdtemp(prefix="pes-viewer-report-"))
    rows: list[str] = []

    for path in paths:
        pattern, stats = read_stats(path)
        preview_path = render_preview(pattern)
        rows.append(row_html(stats, preview_as_data_uri(preview_path)))

    html_doc = f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <title>PES Viewer</title>
  <style>
    :root {{
      color-scheme: dark light;
      --bg: #111318;
      --panel: #1c212b;
      --text: #eef2f7;
      --muted: #a9b4c5;
      --line: #2f3746;
      --accent: #7dc4ff;
    }}
    body {{
      margin: 0;
      font: 16px/1.45 -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      background: linear-gradient(180deg, #0d1015, #161c25);
      color: var(--text);
    }}
    header {{
      padding: 24px 28px 8px;
    }}
    header h1 {{
      margin: 0 0 6px;
      font-size: 28px;
    }}
    header p {{
      margin: 0;
      color: var(--muted);
    }}
    main {{
      padding: 20px 28px 32px;
      display: grid;
      gap: 20px;
    }}
    .card {{
      display: grid;
      grid-template-columns: minmax(340px, 2fr) minmax(260px, 1fr);
      gap: 20px;
      background: rgba(28, 33, 43, 0.92);
      border: 1px solid rgba(255,255,255,0.08);
      border-radius: 18px;
      padding: 18px;
      box-shadow: 0 18px 40px rgba(0,0,0,0.28);
    }}
    .preview-wrap {{
      overflow: auto;
      background: #0d1015;
      border-radius: 12px;
      border: 1px solid var(--line);
      padding: 12px;
      min-height: 180px;
    }}
    .preview {{
      image-rendering: pixelated;
      max-width: none;
    }}
    .meta h2 {{
      margin: 0 0 6px;
      font-size: 22px;
    }}
    .path {{
      margin: 0 0 16px;
      color: var(--muted);
      word-break: break-all;
      font-size: 13px;
    }}
    dl {{
      display: grid;
      grid-template-columns: max-content 1fr;
      gap: 8px 16px;
      margin: 0;
    }}
    dt {{
      color: var(--muted);
    }}
    dd {{
      margin: 0;
      font-weight: 600;
    }}
    .footer {{
      padding: 0 28px 24px;
      color: var(--muted);
      font-size: 13px;
    }}
    @media (max-width: 900px) {{
      .card {{
        grid-template-columns: 1fr;
      }}
    }}
  </style>
</head>
<body>
  <header>
    <h1>PES Viewer</h1>
    <p>Local embroidery preview report generated from your `.pes` files.</p>
  </header>
  <main>
    {''.join(rows)}
  </main>
  <div class="footer">
    Generated by local viewer script in {html.escape(str(ROOT))}
  </div>
</body>
</html>
"""

    report_path = temp_dir / "index.html"
    report_path.write_text(html_doc, encoding="utf-8")
    return report_path


def choose_files_via_osascript() -> list[Path]:
    script = (
        'set chosen to choose file with prompt "Choose PES files to review" '
        'of type {"pes"} with multiple selections allowed\n'
        'set output to ""\n'
        'repeat with f in chosen\n'
        '  set output to output & POSIX path of f & linefeed\n'
        'end repeat\n'
        'return output'
    )
    result = subprocess.run(
        ["osascript", "-e", script],
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        return []
    return [Path(line) for line in result.stdout.splitlines() if line.strip()]


def open_report(paths: list[Path]) -> Path:
    report_path = build_report(paths)
    subprocess.run(["open", str(report_path)], check=True)
    return report_path


def print_info(path: Path) -> None:
    _pattern, stats = read_stats(path)
    print(f"file={stats.path}")
    print(f"stitches={stats.stitches}")
    print(f"colors={stats.colors}")
    print(f"width_mm={stats.width_mm:.1f}")
    print(f"height_mm={stats.height_mm:.1f}")
    print(f"width_in={stats.width_in:.2f}")
    print(f"height_in={stats.height_in:.2f}")
    print(f"fits_5x7={stats.fits_5x7}")
    print(f"fits_6x10={stats.fits_6x10}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Simple local PES viewer")
    parser.add_argument("pes", nargs="*", help="Optional PES files to open")
    parser.add_argument("--info", action="store_true", help="Print PES metadata and exit")
    parser.add_argument("--no-open", action="store_true", help="Build report but do not open it")
    parser.add_argument("--export-readme-assets", metavar="DIR", help="Export polished PNG screenshots for README use")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    paths = [Path(p).expanduser().resolve() for p in args.pes]

    if args.info:
        if not paths:
            raise SystemExit("Pass at least one .pes file with --info")
        for idx, path in enumerate(paths):
            if idx:
                print()
            print_info(path)
        return

    if not paths:
        chosen = choose_files_via_osascript()
        paths = chosen or [path for path in DEFAULT_FILES if path.exists()]

    if not paths:
        raise SystemExit("No PES files selected and no default PES files were found.")

    if args.export_readme_assets:
        output_dir = Path(args.export_readme_assets).expanduser().resolve()
        for exported in export_readme_assets(paths, output_dir):
            print(exported)
        return

    report_path = build_report(paths)
    if not args.no_open:
        subprocess.run(["open", str(report_path)], check=True)
    else:
        print(report_path)


if __name__ == "__main__":
    main()
