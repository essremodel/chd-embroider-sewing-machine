#!/usr/bin/env python3

from __future__ import annotations

import argparse
import base64
import html
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

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

    report_path = build_report(paths)
    if not args.no_open:
        subprocess.run(["open", str(report_path)], check=True)
    else:
        print(report_path)


if __name__ == "__main__":
    main()
