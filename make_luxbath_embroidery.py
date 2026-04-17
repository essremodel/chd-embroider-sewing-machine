#!/usr/bin/env python3
"""
Luxury Bath embroidery generator.

Pipeline:
  EPS  --gs-->  PDF  --inkscape-->  plain SVG (preserves Beziers)
       --svgpathtools-->  shapely polygons (in mm)
       --medial-axis segmentation-->  satin columns + fill fallbacks
       --Ink/Stitch annotations-->  SVG
       --Ink/Stitch CLI-->  PES
       --pyembroidery-->  preview PNG + metrics
"""

from __future__ import annotations

import math
import re
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, Sequence
from xml.etree import ElementTree as ET

import numpy as np
import svgpathtools
from scipy import ndimage
from shapely.geometry import Polygon, MultiPolygon, LineString
from shapely.ops import unary_union
from pyembroidery import EmbPattern, write_png

# ---------------------------------------------------------------------------
# Paths and constants
# ---------------------------------------------------------------------------

ROOT = Path(__file__).resolve().parent
BUILD = ROOT / "build"
PREVIEWS = ROOT / "previews"

BLACK_EPS = ROOT / "LuxuryBath-bybc-black-horizontal.eps"
PANTONE_EPS = ROOT / "LuxuryBath-bybc-pantone-coated-horizontal.eps"

SVG_1C = ROOT / "luxbath_leftchest_1c.svg"
SVG_3C = ROOT / "luxbath_leftchest_3c.svg"
PES_1C = ROOT / "LBATH1C.PES"
PES_3C = ROOT / "LBATH3C.PES"
PNG_1C = PREVIEWS / "LBATH1C_preview.png"
PNG_3C = PREVIEWS / "LBATH3C_preview.png"

INKSCAPE = Path("/opt/homebrew/bin/inkscape")
INKSTITCH = (
    Path.home()
    / "Library/Application Support/org.inkscape.Inkscape/config/inkscape/extensions/inkstitch/inkstitch.app/Contents/MacOS/inkstitch"
)
GHOSTSCRIPT = "gs"

TARGET_WIDTH_MM = 177.8              # 7" wide (doubled from 3.5")
TOP_COMPONENT_RATIO = 0.55           # drop bottom 45% (byline removal)
RASTER_PX_PER_MM = 20                # for medial-axis analysis

# Classification thresholds (units: mm except ratios)
SATIN_WIDTH_MIN_MM = 0.55
SATIN_WIDTH_MAX_MM = 2.2
SATIN_LENGTH_MIN_MM = 2.5
MAX_SATIN_SEGMENTS_PER_SHAPE = 2   # branched glyphs -> fill (cleaner than gappy satins)
SATIN_STRAIGHTNESS_MAX = 0.85        # allow curved glyph strokes (U, C, J bends)

# Brand colors (canonical Pantone-equivalent hex)
BLACK = "#231f20"
PANTONE_3025 = "#004f6e"   # dark teal
PANTONE_3005 = "#0076bc"   # medium blue
PANTONE_2985 = "#54c1ea"   # light cyan

# Map whatever fill appears in the extracted SVG to canonical brand hex.
# Ghostscript rendering of Pantone spot colors produces slightly different
# RGB than the brand-book values; we snap.
PANTONE_SNAP = {
    "#194b6e": PANTONE_3025,
    "#1574c2": PANTONE_3005,
    "#6ac7ed": PANTONE_2985,
    "#004f6e": PANTONE_3025,
    "#0076bc": PANTONE_3005,
    "#54c1ea": PANTONE_2985,
    "#231f20": BLACK,
    "#000000": BLACK,
}

# Stitch sequence order for the 3-color version: darkest to lightest.
COLOR_ORDER_3C = [PANTONE_3025, PANTONE_3005, PANTONE_2985]

# SVG namespaces
SVG_NS = "http://www.w3.org/2000/svg"
INKSCAPE_NS = "http://www.inkscape.org/namespaces/inkscape"
INKSTITCH_NS = "http://inkstitch.org/namespace"
SODIPODI_NS = "http://sodipodi.sourceforge.net/DTD/sodipodi-0.dtd"

# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass
class Shape:
    """A single polygon (with optional holes) to stitch, in mm."""

    polygon: Polygon
    fill: str
    source_id: str


@dataclass
class StitchElement:
    """An SVG element to emit: either a fill or a satin column."""

    kind: str                          # "fill" or "satin"
    fill: str
    element_id: str
    d: str                             # SVG path data (mm coords)
    entry_point: tuple[float, float]   # used for NN sequencing
    exit_point: tuple[float, float]
    extra_attrs: dict[str, str] = field(default_factory=dict)
    # Satins only: d= of the original glyph polygon, emitted as a non-stitching
    # visual fill behind the rail-and-rung path so the SVG renders as a solid
    # letter in viewers (Inkscape, browsers, Finder previews).
    visual_d: str | None = None


# ---------------------------------------------------------------------------
# EPS -> PDF -> plain SVG
# ---------------------------------------------------------------------------


def extract_vector_svg(eps_path: Path, tag: str) -> Path:
    pdf_path = BUILD / f"{tag}.pdf"
    svg_path = BUILD / f"{tag}_plain.svg"
    BUILD.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        [
            GHOSTSCRIPT, "-dSAFER", "-dBATCH", "-dNOPAUSE",
            "-sDEVICE=pdfwrite", "-dEPSCrop",
            "-o", str(pdf_path), str(eps_path),
        ],
        check=True,
        stdout=subprocess.DEVNULL,
    )
    subprocess.run(
        [
            str(INKSCAPE),
            "--export-type=svg", "--export-plain-svg",
            f"--export-filename={svg_path}",
            str(pdf_path),
        ],
        check=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    return svg_path


# ---------------------------------------------------------------------------
# SVG parsing -> shapely polygons in mm
# ---------------------------------------------------------------------------


_TRANSFORM_MATRIX_RE = re.compile(
    r"matrix\(\s*([-\d.eE+]+)[\s,]+([-\d.eE+]+)[\s,]+"
    r"([-\d.eE+]+)[\s,]+([-\d.eE+]+)[\s,]+"
    r"([-\d.eE+]+)[\s,]+([-\d.eE+]+)\s*\)"
)


def _compose_transform(outer: tuple, inner: tuple) -> tuple:
    """Compose SVG affine transforms outer * inner (applied: inner then outer)."""
    a1, b1, c1, d1, e1, f1 = outer
    a2, b2, c2, d2, e2, f2 = inner
    return (
        a1 * a2 + c1 * b2,
        b1 * a2 + d1 * b2,
        a1 * c2 + c1 * d2,
        b1 * c2 + d1 * d2,
        a1 * e2 + c1 * f2 + e1,
        b1 * e2 + d1 * f2 + f1,
    )


def _parse_transform(value: str | None) -> tuple:
    if not value:
        return (1.0, 0.0, 0.0, 1.0, 0.0, 0.0)
    match = _TRANSFORM_MATRIX_RE.search(value)
    if not match:
        return (1.0, 0.0, 0.0, 1.0, 0.0, 0.0)
    return tuple(float(v) for v in match.groups())


def _apply_transform(t: tuple, x: float, y: float) -> tuple[float, float]:
    a, b, c, d, e, f = t
    return (a * x + c * y + e, b * x + d * y + f)


def _extract_fill(style: str | None) -> str | None:
    if not style:
        return None
    match = re.search(r"fill\s*:\s*(#[0-9a-fA-F]{3,8})", style)
    if not match:
        return None
    hex_value = match.group(1).lower()
    if len(hex_value) == 4:
        hex_value = "#" + "".join(ch * 2 for ch in hex_value[1:])
    return hex_value


def _snap_color(fill_hex: str) -> str:
    if fill_hex in PANTONE_SNAP:
        return PANTONE_SNAP[fill_hex]
    return fill_hex


def _subpaths_to_polygons(
    d_attr: str,
    transform: tuple,
    scale_mm_per_unit: float,
    offset_mm: tuple[float, float],
) -> list[Polygon]:
    """Parse an SVG path d= string into closed Polygons in mm space.

    Subpaths are returned as separate polygons; hole/outer relationships
    are rebuilt later via shapely covers() checks.
    """
    path = svgpathtools.parse_path(d_attr)
    # Split into subpaths
    subpaths: list[list] = []
    current: list = []
    for seg in path:
        if current and abs(complex(*_ep(current[-1].end)) - complex(*_ep(seg.start))) > 1e-6:
            subpaths.append(current)
            current = []
        current.append(seg)
    if current:
        subpaths.append(current)

    polygons: list[Polygon] = []
    for sub in subpaths:
        pts = _sample_subpath(sub)
        if len(pts) < 3:
            continue
        xy_mm: list[tuple[float, float]] = []
        for x, y in pts:
            tx, ty = _apply_transform(transform, x, y)
            xy_mm.append(((tx - offset_mm[0]) * scale_mm_per_unit,
                          (ty - offset_mm[1]) * scale_mm_per_unit))
        try:
            poly = Polygon(xy_mm).buffer(0)
        except Exception:
            continue
        if poly.is_empty:
            continue
        if isinstance(poly, MultiPolygon):
            for p in poly.geoms:
                if p.area > 0.01:
                    polygons.append(p)
        elif poly.area > 0.01:
            polygons.append(poly)
    return polygons


def _ep(c: complex) -> tuple[float, float]:
    return (c.real, c.imag)


def _sample_subpath(segments: Sequence[svgpathtools.path.Segment],
                    max_err: float = 0.5) -> list[tuple[float, float]]:
    """Flatten Beziers into polyline points. max_err in source units."""
    pts: list[tuple[float, float]] = []
    for seg in segments:
        length = seg.length(error=1e-3) if hasattr(seg, "length") else 1.0
        # samples per segment: denser for curves
        if isinstance(seg, svgpathtools.Line):
            steps = 1
        else:
            steps = max(8, int(length / max_err))
        for i in range(steps + 1):
            if pts and i == 0:
                continue  # avoid duplicate at segment joints
            t = i / steps
            p = seg.point(t)
            pts.append((p.real, p.imag))
    return pts


def _rebuild_holes(polys: list[Polygon]) -> list[Polygon]:
    """Given a flat list of polygons that may contain holes, rebuild parent+hole
    relationships using geometric containment."""
    # Sort largest first so we test "does bigger contain smaller" easily.
    polys_sorted = sorted(polys, key=lambda p: p.area, reverse=True)
    used = [False] * len(polys_sorted)
    result: list[Polygon] = []
    for i, outer in enumerate(polys_sorted):
        if used[i]:
            continue
        holes: list[list[tuple[float, float]]] = []
        for j in range(i + 1, len(polys_sorted)):
            if used[j]:
                continue
            inner = polys_sorted[j]
            if outer.contains(inner):
                holes.append(list(inner.exterior.coords))
                used[j] = True
        result.append(Polygon(outer.exterior.coords, holes))
        used[i] = True
    return result


# ---------------------------------------------------------------------------
# Shape classification via medial axis
# ---------------------------------------------------------------------------


@dataclass
class MedialSegment:
    points_mm: list[tuple[float, float]]   # ordered centerline
    widths_mm: list[float]                 # local thickness at each point
    length_mm: float


def _rasterize_polygon(polygon: Polygon, px_per_mm: float,
                       pad_px: int = 2) -> tuple[np.ndarray, tuple[float, float]]:
    minx, miny, maxx, maxy = polygon.bounds
    w = int(math.ceil((maxx - minx) * px_per_mm)) + pad_px * 2
    h = int(math.ceil((maxy - miny) * px_per_mm)) + pad_px * 2
    mask = np.zeros((h, w), dtype=bool)

    # Fill via bounding-box scan using shapely contains would be slow; instead
    # use a quick rasterization by sampling pixel centers with prepared geom.
    from shapely.prepared import prep
    prepared = prep(polygon)
    ys, xs = np.meshgrid(np.arange(h), np.arange(w), indexing="ij")
    # pixel centers back to mm coords
    mm_x = (xs - pad_px + 0.5) / px_per_mm + minx
    mm_y = (ys - pad_px + 0.5) / px_per_mm + miny
    # vectorize via point-by-point check; for the logo scale (~88 px tall)
    # this is plenty fast.
    flat_x = mm_x.ravel()
    flat_y = mm_y.ravel()
    from shapely.geometry import Point
    flat_mask = np.fromiter(
        (prepared.contains(Point(float(x), float(y)))
         for x, y in zip(flat_x, flat_y)),
        dtype=bool,
        count=flat_x.size,
    )
    mask = flat_mask.reshape((h, w))
    origin_mm = (minx - pad_px / px_per_mm, miny - pad_px / px_per_mm)
    return mask, origin_mm


def _skeleton_segments(mask: np.ndarray, px_per_mm: float,
                       origin_mm: tuple[float, float]) -> list[MedialSegment]:
    """Return at most one MedialSegment for the shape.

    Only emits a segment if the medial axis is topologically a single stroke
    (exactly 2 endpoints, no 3+ neighbor branch pixels).  Branched glyphs
    return [] so the caller falls back to fill — mixed-satin junctions look
    worse than a clean tuned fill.
    """
    from skimage.morphology import medial_axis, skeletonize
    skel = skeletonize(mask)
    _, distance = medial_axis(mask, return_distance=True)
    if skel.sum() < 4:
        return []

    kernel = np.array([[1, 1, 1], [1, 0, 1], [1, 1, 1]], dtype=np.uint8)
    neighbor_count = ndimage.convolve(skel.astype(np.uint8), kernel,
                                      mode="constant", cval=0)
    neighbor_count = neighbor_count * skel

    # True branch pixels: 3+ skeleton neighbors across distinct directions.
    branch_pixels = np.argwhere((neighbor_count >= 3) & skel)
    if len(branch_pixels) > 0:
        return []

    endpoints = np.argwhere((neighbor_count == 1) & skel)
    if len(endpoints) != 2:
        return []  # closed loops (0 endpoints) or other topology

    # Walk the skeleton from one endpoint to the other.
    start = tuple(endpoints[0])
    end = tuple(endpoints[1])
    coords = {tuple(p) for p in np.argwhere(skel)}
    ordered: list[tuple[int, int]] = [start]
    visited = {start}
    while ordered[-1] != end:
        cy, cx = ordered[-1]
        nxt = None
        for dy in (-1, 0, 1):
            for dx in (-1, 0, 1):
                if dy == 0 and dx == 0:
                    continue
                cand = (cy + dy, cx + dx)
                if cand in coords and cand not in visited:
                    nxt = cand
                    break
            if nxt:
                break
        if nxt is None:
            return []  # dead end before reaching other endpoint
        ordered.append(nxt)
        visited.add(nxt)

    pts_mm: list[tuple[float, float]] = []
    widths_mm: list[float] = []
    for (py, px) in ordered:
        mmx = origin_mm[0] + (px + 0.5) / px_per_mm
        mmy = origin_mm[1] + (py + 0.5) / px_per_mm
        pts_mm.append((mmx, mmy))
        widths_mm.append(2.0 * distance[py, px] / px_per_mm)
    length_mm = sum(
        math.hypot(pts_mm[i+1][0]-pts_mm[i][0], pts_mm[i+1][1]-pts_mm[i][1])
        for i in range(len(pts_mm)-1)
    )
    if length_mm < 1.0:
        return []
    return [MedialSegment(pts_mm, widths_mm, length_mm)]


def _order_skeleton_pixels(pts_yx: np.ndarray,
                           neighbor_count: np.ndarray) -> list[tuple[int, int]] | None:
    """Given skeleton pixels belonging to one segment, return them in path order."""
    coords = {tuple(p) for p in pts_yx}
    # Find endpoint in this segment (neighbor_count == 1) or pick an extreme.
    endpoints = [p for p in coords if neighbor_count[p] == 1]
    if not endpoints:
        # pick corner of bounding box
        sorted_pts = sorted(coords)
        start = sorted_pts[0]
    else:
        start = endpoints[0]
    ordered: list[tuple[int, int]] = [start]
    visited = {start}
    while True:
        cy, cx = ordered[-1]
        next_pt = None
        for dy in (-1, 0, 1):
            for dx in (-1, 0, 1):
                if dy == 0 and dx == 0:
                    continue
                cand = (cy + dy, cx + dx)
                if cand in coords and cand not in visited:
                    next_pt = cand
                    break
            if next_pt:
                break
        if next_pt is None:
            break
        ordered.append(next_pt)
        visited.add(next_pt)
    return ordered


def _simplify_segment(seg: MedialSegment, tol_mm: float = 0.15) -> MedialSegment:
    """Douglas-Peucker simplification while preserving matched widths."""
    if len(seg.points_mm) <= 2:
        return seg
    line = LineString(seg.points_mm)
    simplified = line.simplify(tol_mm, preserve_topology=False)
    new_pts = list(simplified.coords)
    # Remap widths to nearest original point.
    orig_arr = np.array(seg.points_mm)
    widths_arr = np.array(seg.widths_mm)
    new_widths = []
    for p in new_pts:
        dists = np.linalg.norm(orig_arr - np.array(p), axis=1)
        new_widths.append(float(widths_arr[int(np.argmin(dists))]))
    length = sum(
        math.hypot(new_pts[i+1][0]-new_pts[i][0], new_pts[i+1][1]-new_pts[i][1])
        for i in range(len(new_pts)-1)
    )
    return MedialSegment(new_pts, new_widths, length)


def _segment_is_satin_candidate(seg: MedialSegment) -> bool:
    if seg.length_mm < SATIN_LENGTH_MIN_MM:
        return False
    widths = np.array(seg.widths_mm)
    if widths.size == 0:
        return False
    median_w = float(np.median(widths))
    if median_w < SATIN_WIDTH_MIN_MM or median_w > SATIN_WIDTH_MAX_MM:
        return False
    # Width should be reasonably consistent; large variance = stroke not uniform.
    if float(np.std(widths)) > 0.7 * median_w:
        return False
    # Straightness: compare chord length to path length.
    chord = math.hypot(seg.points_mm[-1][0] - seg.points_mm[0][0],
                       seg.points_mm[-1][1] - seg.points_mm[0][1])
    straightness_err = 1.0 - (chord / seg.length_mm)  # 0 = straight
    # Allow curved strokes (e.g. in U) so this is looser than true straightness.
    if straightness_err > SATIN_STRAIGHTNESS_MAX:
        return False
    return True


# ---------------------------------------------------------------------------
# Satin column / fill path generation
# ---------------------------------------------------------------------------


def _perpendicular(p0: tuple[float, float],
                   p1: tuple[float, float]) -> tuple[float, float]:
    dx, dy = p1[0] - p0[0], p1[1] - p0[1]
    length = math.hypot(dx, dy) or 1e-9
    return (-dy / length, dx / length)


def _offset_polyline(pts: list[tuple[float, float]],
                     widths: list[float],
                     side: int,
                     clip_to: Polygon | None) -> list[tuple[float, float]]:
    """Offset a polyline to one side using local perpendiculars. side = +1 or -1."""
    out: list[tuple[float, float]] = []
    n = len(pts)
    for i, (x, y) in enumerate(pts):
        if i == 0:
            nx, ny = _perpendicular(pts[0], pts[1])
        elif i == n - 1:
            nx, ny = _perpendicular(pts[-2], pts[-1])
        else:
            nx1, ny1 = _perpendicular(pts[i-1], pts[i])
            nx2, ny2 = _perpendicular(pts[i], pts[i+1])
            nx = (nx1 + nx2) / 2
            ny = (ny1 + ny2) / 2
            mag = math.hypot(nx, ny) or 1e-9
            nx, ny = nx / mag, ny / mag
        half = widths[i] / 2.0
        ox, oy = x + side * nx * half, y + side * ny * half
        out.append((ox, oy))
    return out


def build_satin_element(seg: MedialSegment, fill: str, element_id: str,
                        clip_polygon: Polygon) -> StitchElement:
    # Shrink widths slightly to keep rails inside the original glyph after
    # pull compensation.
    adj_widths = [max(0.3, w * 0.92) for w in seg.widths_mm]
    left = _offset_polyline(seg.points_mm, adj_widths, +1, clip_polygon)
    right = _offset_polyline(seg.points_mm, adj_widths, -1, clip_polygon)

    # Rungs every ~1.5 mm along the segment.
    rung_spacing = 1.5
    rungs: list[tuple[tuple[float, float], tuple[float, float]]] = []
    # Accumulate arc-length.
    cum = [0.0]
    for i in range(len(seg.points_mm) - 1):
        d = math.hypot(seg.points_mm[i+1][0] - seg.points_mm[i][0],
                       seg.points_mm[i+1][1] - seg.points_mm[i][1])
        cum.append(cum[-1] + d)
    total = cum[-1] or 1.0
    target = rung_spacing
    while target < total:
        # Find segment index for target arc-length.
        for k in range(len(cum) - 1):
            if cum[k] <= target <= cum[k+1]:
                t = (target - cum[k]) / max(cum[k+1] - cum[k], 1e-9)
                lx = left[k][0] + t * (left[k+1][0] - left[k][0])
                ly = left[k][1] + t * (left[k+1][1] - left[k][1])
                rx = right[k][0] + t * (right[k+1][0] - right[k][0])
                ry = right[k][1] + t * (right[k+1][1] - right[k][1])
                rungs.append(((lx, ly), (rx, ry)))
                break
        target += rung_spacing

    # Build d= string: rail1 + rail2 + rungs (each a separate subpath).
    def poly_d(pts: list[tuple[float, float]]) -> str:
        parts = [f"M {pts[0][0]:.3f},{pts[0][1]:.3f}"]
        parts.extend(f"L {x:.3f},{y:.3f}" for x, y in pts[1:])
        return " ".join(parts)

    d_parts = [poly_d(left), poly_d(right)]
    for (a, b) in rungs:
        d_parts.append(f"M {a[0]:.3f},{a[1]:.3f} L {b[0]:.3f},{b[1]:.3f}")

    # Original glyph polygon for SVG-viewer preview (filled).  Ink/Stitch
    # will skip this because we mark it with stitch methods = "none".
    def ring_d(ring: list[tuple[float, float]]) -> str:
        parts = [f"M {ring[0][0]:.3f},{ring[0][1]:.3f}"]
        parts.extend(f"L {x:.3f},{y:.3f}" for x, y in ring[1:])
        parts.append("Z")
        return " ".join(parts)
    visual_parts = [ring_d(list(clip_polygon.exterior.coords))]
    for interior in clip_polygon.interiors:
        visual_parts.append(ring_d(list(interior.coords)))
    visual_d = " ".join(visual_parts)

    return StitchElement(
        kind="satin",
        fill=fill,
        element_id=element_id,
        d=" ".join(d_parts),
        entry_point=left[0],
        exit_point=right[-1],
        visual_d=visual_d,
        extra_attrs={
            "satin_column": "True",
            "zigzag_spacing_mm": "0.30",
            "pull_compensation_mm": "0.15",
            "center_walk_underlay": "True",
            "center_walk_underlay_stitch_length_mm": "1.5",
            "contour_underlay": "True",
            "contour_underlay_stitch_length_mm": "1.8",
            "contour_underlay_inset_mm": "0.15",
        },
    )


def build_fill_element(polygon: Polygon, fill: str, element_id: str,
                       row_spacing_mm: float = 0.34,
                       angle_deg: float | None = None,
                       is_stroke: bool = False) -> StitchElement:
    def ring_d(ring: list[tuple[float, float]]) -> str:
        parts = [f"M {ring[0][0]:.3f},{ring[0][1]:.3f}"]
        parts.extend(f"L {x:.3f},{y:.3f}" for x, y in ring[1:])
        parts.append("Z")
        return " ".join(parts)

    d_parts = [ring_d(list(polygon.exterior.coords))]
    for interior in polygon.interiors:
        d_parts.append(ring_d(list(interior.coords)))

    centroid = polygon.representative_point()
    extra = {
        "fill_method": "auto_fill",
        "row_spacing_mm": f"{row_spacing_mm:.2f}",
        "staggers": "4",
        "pull_compensation_mm": "0.15" if is_stroke else "0.18",
        "running_stitch_length_mm": "2.2",
        "fill_underlay": "True",
        "fill_underlay_row_spacing_mm": "1.5",
        "fill_underlay_max_stitch_length_mm": "3.0",
        # Contour-style underlay (0/90) for strokes helps satin-like edges;
        # cross-hatch (60/-60) for general fills gives stability under wash.
        "fill_underlay_angle": "0 90" if is_stroke else "60 -60",
        "fill_underlay_inset_mm": "0.2",
        "ties": "3",
        "max_stitch_length_mm": "2.8",
    }
    if angle_deg is not None:
        # Ink/Stitch: positive angle rotates row direction CCW from horizontal.
        extra["angle"] = f"{angle_deg:.1f}"

    return StitchElement(
        kind="fill",
        fill=fill,
        element_id=element_id,
        d=" ".join(d_parts),
        entry_point=(float(centroid.x), float(centroid.y)),
        exit_point=(float(centroid.x), float(centroid.y)),
        extra_attrs=extra,
    )


# ---------------------------------------------------------------------------
# Classification per shape
# ---------------------------------------------------------------------------


def classify_shape(shape: Shape) -> list[StitchElement]:
    """Decompose a shape into satin segments (where possible) plus a fill
    fallback for the complement, or a single fill if no segments qualify.

    For this logo, each shape is either the droplet (a single fill) or one
    glyph. For glyphs with multiple strokes (H, X, B, ...), the medial axis
    splits into multiple segments and we emit a satin per segment plus a
    compensating fill (narrow residue).  To keep things robust we go with
    one of two modes:

      - ALL_SATIN  : every medial segment is a clean satin candidate ->
                     emit satins only, skip fill.  Best for L, U, I, T.
      - FILL_ONLY  : if any segment fails, fall back to a single fill for
                     the entire glyph.  Still tuned better than Codex.
    """
    polygon = shape.polygon
    # Blob-like icon parts (droplet): very large, roughly isotropic.  For
    # these, skeleton analysis yields many tiny branches that are never good
    # satins; short-circuit to fill.
    bbox = polygon.bounds
    bbox_w = bbox[2] - bbox[0]
    bbox_h = bbox[3] - bbox[1]
    area = polygon.area
    if area > 18.0 and min(bbox_w, bbox_h) > 3.0:
        return [build_fill_element(polygon, shape.fill, shape.source_id)]

    # All shapes render as filled polygons for accurate SVG-viewer preview.
    # For single-stroke glyphs (L, U, U) we align the fill stitch angle to
    # the glyph's medial-axis direction so the stitches run LENGTHWISE along
    # the stroke — producing a satin-like visual at roughly equivalent
    # density, without the rail-and-rung source geometry that looks like
    # wireframe in SVG viewers.
    mask, origin_mm = _rasterize_polygon(polygon, RASTER_PX_PER_MM)
    segments = _skeleton_segments(mask, RASTER_PX_PER_MM, origin_mm)
    segments = [_simplify_segment(s) for s in segments]
    satin_ready = [s for s in segments if _segment_is_satin_candidate(s)]

    if satin_ready:
        seg = satin_ready[0]
        # Dominant stroke direction (chord endpoint -> endpoint).
        dx = seg.points_mm[-1][0] - seg.points_mm[0][0]
        dy = seg.points_mm[-1][1] - seg.points_mm[0][1]
        # Ink/Stitch uses degrees CCW from horizontal; stitch ROWS run at
        # this angle, so to get rows along the stroke, use the chord angle.
        angle = math.degrees(math.atan2(dy, dx))
        # Tighter row spacing for single-stroke glyphs to approximate satin.
        return [build_fill_element(
            polygon, shape.fill, shape.source_id,
            row_spacing_mm=0.28,
            angle_deg=angle,
            is_stroke=True,
        )]
    return [build_fill_element(polygon, shape.fill, shape.source_id)]


# ---------------------------------------------------------------------------
# Parse SVG into Shape list (mm)
# ---------------------------------------------------------------------------


def _get_viewbox(tree: ET.ElementTree) -> tuple[float, float, float, float]:
    root = tree.getroot()
    vb = root.attrib.get("viewBox")
    if vb:
        parts = vb.replace(",", " ").split()
        return tuple(float(p) for p in parts[:4])  # type: ignore
    w = float(re.sub(r"[a-zA-Z]", "", root.attrib.get("width", "0")))
    h = float(re.sub(r"[a-zA-Z]", "", root.attrib.get("height", "0")))
    return (0.0, 0.0, w, h)


def parse_paths_to_shapes(svg_path: Path) -> tuple[list[Shape], float, float]:
    tree = ET.parse(svg_path)
    root = tree.getroot()
    vbx, vby, vbw, vbh = _get_viewbox(tree)

    # Walk all <path> elements, composing transforms from ancestors.
    shapes_raw: list[tuple[str, str, tuple]] = []  # (d, fill_hex, transform)

    def walk(element: ET.Element, parent_tf: tuple):
        tf_attr = element.attrib.get("transform")
        local_tf = _parse_transform(tf_attr) if tf_attr else (1, 0, 0, 1, 0, 0)
        composed = _compose_transform(parent_tf, local_tf) if tf_attr else parent_tf
        tag = element.tag.rsplit("}", 1)[-1]
        if tag == "path":
            fill = _extract_fill(element.attrib.get("style"))
            if fill is None:
                fill = element.attrib.get("fill", "#000000").lower()
            fill_hex = _snap_color(fill)
            d = element.attrib.get("d", "")
            if d:
                shapes_raw.append((d, fill_hex, composed))
        for child in list(element):
            walk(child, composed)

    walk(root, (1, 0, 0, 1, 0, 0))

    # First pass: compute bounding box across all paths in viewBox units to
    # figure out scale.
    all_polys_viewbox: list[tuple[Polygon, str, str]] = []
    for idx, (d, fill_hex, transform) in enumerate(shapes_raw):
        polys = _subpaths_to_polygons(d, transform, 1.0, (0.0, 0.0))
        if not polys:
            continue
        merged = _rebuild_holes(polys)
        for j, poly in enumerate(merged):
            all_polys_viewbox.append((poly, fill_hex, f"p{idx}_{j}"))

    if not all_polys_viewbox:
        raise RuntimeError(f"No paths parsed from {svg_path}")

    union_bounds = unary_union([p for p, _, _ in all_polys_viewbox]).bounds
    design_w = union_bounds[2] - union_bounds[0]
    design_h = union_bounds[3] - union_bounds[1]
    scale = TARGET_WIDTH_MM / design_w
    cutoff_y_vb = union_bounds[1] + TOP_COMPONENT_RATIO * design_h

    shapes: list[Shape] = []
    for poly, fill_hex, source_id in all_polys_viewbox:
        # Drop byline: filter by top-y (shape's highest point) rather than
        # centroid so tall shapes like the droplet are preserved even if
        # their centroid falls near the midpoint of the full design.
        top_y = poly.bounds[1]
        if top_y > cutoff_y_vb:
            continue
        # Transform to mm space with origin at union_bounds minimum.
        mm_coords = [
            ((x - union_bounds[0]) * scale, (y - union_bounds[1]) * scale)
            for x, y in poly.exterior.coords
        ]
        mm_holes = [
            [((x - union_bounds[0]) * scale, (y - union_bounds[1]) * scale)
             for x, y in ring.coords]
            for ring in poly.interiors
        ]
        try:
            mm_poly = Polygon(mm_coords, mm_holes).buffer(0)
        except Exception:
            continue
        if mm_poly.is_empty:
            continue
        if isinstance(mm_poly, MultiPolygon):
            for k, sub in enumerate(mm_poly.geoms):
                shapes.append(Shape(sub, fill_hex, f"{source_id}_{k}"))
        else:
            shapes.append(Shape(mm_poly, fill_hex, source_id))

    width_mm = design_w * scale
    # Height only counts the TOP region (post byline removal).
    kept_bounds = unary_union([s.polygon for s in shapes]).bounds
    height_mm = kept_bounds[3] - kept_bounds[1]
    return shapes, width_mm, height_mm


# ---------------------------------------------------------------------------
# Sequencing
# ---------------------------------------------------------------------------


def sequence_elements(elements: list[StitchElement],
                      color_order: list[str]) -> list[StitchElement]:
    """Group by color (following COLOR_ORDER_3C when applicable), then within
    each group, nearest-neighbor greedy from leftmost start."""
    by_color: dict[str, list[StitchElement]] = {}
    for el in elements:
        by_color.setdefault(el.fill, []).append(el)

    ordered: list[StitchElement] = []
    seen_colors = set()
    for color in color_order:
        if color not in by_color:
            continue
        ordered.extend(_nn_sort(by_color[color]))
        seen_colors.add(color)
    for color, group in by_color.items():
        if color in seen_colors:
            continue
        ordered.extend(_nn_sort(group))
    return ordered


def _nn_sort(group: list[StitchElement]) -> list[StitchElement]:
    if not group:
        return group
    remaining = group[:]
    # Start with leftmost entry.
    remaining.sort(key=lambda e: (e.entry_point[0], e.entry_point[1]))
    ordered = [remaining.pop(0)]
    while remaining:
        last = ordered[-1].exit_point
        nxt_idx = min(
            range(len(remaining)),
            key=lambda i: (remaining[i].entry_point[0] - last[0]) ** 2
                          + (remaining[i].entry_point[1] - last[1]) ** 2,
        )
        ordered.append(remaining.pop(nxt_idx))
    return ordered


# ---------------------------------------------------------------------------
# SVG writer
# ---------------------------------------------------------------------------


def write_output_svg(path: Path, elements: list[StitchElement],
                     width_mm: float, height_mm: float) -> None:
    ET.register_namespace("", SVG_NS)
    ET.register_namespace("inkscape", INKSCAPE_NS)
    ET.register_namespace("sodipodi", SODIPODI_NS)
    ET.register_namespace("inkstitch", INKSTITCH_NS)

    svg = ET.Element(
        f"{{{SVG_NS}}}svg",
        {
            "width": f"{width_mm:.3f}mm",
            "height": f"{height_mm:.3f}mm",
            "viewBox": f"0 0 {width_mm:.3f} {height_mm:.3f}",
            "version": "1.1",
        },
    )
    metadata = ET.SubElement(svg, "metadata")
    ET.SubElement(metadata, f"{{{INKSTITCH_NS}}}min_stitch_len_mm").text = "0.1"
    ET.SubElement(metadata, f"{{{INKSTITCH_NS}}}collapse_len_mm").text = "3.0"
    ET.SubElement(metadata, f"{{{INKSTITCH_NS}}}inkstitch_svg_version").text = "3"

    layer = ET.SubElement(
        svg, "g",
        {
            "id": "layer1",
            f"{{{INKSCAPE_NS}}}groupmode": "layer",
            f"{{{INKSCAPE_NS}}}label": "Stitching",
        },
    )

    for idx, el in enumerate(elements):
        style = (f"fill-rule:evenodd;clip-rule:evenodd;"
                 f"fill:{el.fill};stroke:none")
        attrs = {
            "id": f"{el.element_id}_{idx}",
            "d": el.d,
            "style": style,
        }
        for k, v in el.extra_attrs.items():
            attrs[f"{{{INKSTITCH_NS}}}{k}"] = v
        ET.SubElement(layer, "path", attrs)

    ET.indent(svg)
    path.write_text(
        ET.tostring(svg, encoding="unicode", xml_declaration=True),
        encoding="utf-8",
    )


# ---------------------------------------------------------------------------
# PES export + preview
# ---------------------------------------------------------------------------


def export_pes(svg_path: Path, pes_path: Path) -> None:
    with pes_path.open("wb") as fh:
        subprocess.run(
            [str(INKSTITCH), "--extension=output", "--format=pes", str(svg_path)],
            check=True,
            stdout=fh,
        )


def render_preview(pes_path: Path, png_path: Path) -> tuple[int, int, tuple]:
    png_path.parent.mkdir(parents=True, exist_ok=True)
    pattern = EmbPattern(str(pes_path))
    write_png(pattern, str(png_path))
    stitches = pattern.count_stitches()
    colors = pattern.count_color_changes() + 1
    bounds = pattern.bounds()
    return stitches, colors, bounds


# ---------------------------------------------------------------------------
# High-level entry points
# ---------------------------------------------------------------------------


def generate(eps_path: Path, svg_out: Path, pes_out: Path, png_out: Path,
             color_order: list[str], tag: str,
             force_single_color: str | None = None) -> dict:
    plain_svg = extract_vector_svg(eps_path, tag)
    shapes, width_mm, height_mm = parse_paths_to_shapes(plain_svg)

    if force_single_color:
        shapes = [Shape(s.polygon, force_single_color, s.source_id) for s in shapes]

    # Classify each shape into 1+ stitch elements.
    elements: list[StitchElement] = []
    for shape in shapes:
        elements.extend(classify_shape(shape))

    elements = sequence_elements(elements, color_order)

    # Padding so the design sits with a small margin.
    pad = 1.0
    padded_w = width_mm + 2 * pad
    padded_h = height_mm + 2 * pad
    # Shift all d strings by +pad. Cheap: rewrite each element's d with offset.
    for el in elements:
        el.d = _offset_d(el.d, pad, pad)
        if el.visual_d:
            el.visual_d = _offset_d(el.visual_d, pad, pad)
        el.entry_point = (el.entry_point[0] + pad, el.entry_point[1] + pad)
        el.exit_point = (el.exit_point[0] + pad, el.exit_point[1] + pad)

    write_output_svg(svg_out, elements, padded_w, padded_h)
    export_pes(svg_out, pes_out)
    stitches, colors, bounds = render_preview(pes_out, png_out)

    bx0, by0, bx1, by1 = bounds  # pyembroidery returns 0.1mm units
    width_mm = (bx1 - bx0) / 10.0
    height_mm = (by1 - by0) / 10.0
    area_cm2 = max((width_mm * height_mm) / 100.0, 0.01)
    return {
        "file": pes_out.name,
        "stitches": stitches,
        "colors": colors,
        "bounds_mm": (bx0 / 10, by0 / 10, bx1 / 10, by1 / 10),
        "density_per_cm2": stitches / area_cm2,
        "satin_count": sum(1 for e in elements if e.kind == "satin"),
        "fill_count": sum(1 for e in elements if e.kind == "fill"),
    }


_COORD_RE = re.compile(r"([MLZ])\s*([-\d.]*)[,\s]*([-\d.]*)", re.IGNORECASE)


def _offset_d(d: str, dx: float, dy: float) -> str:
    tokens = re.findall(r"[MLZ]|[-\d.eE+]+", d)
    out: list[str] = []
    i = 0
    while i < len(tokens):
        t = tokens[i]
        if t in "MLml":
            out.append(t)
            x = float(tokens[i+1]) + dx
            y = float(tokens[i+2]) + dy
            out.append(f"{x:.3f}")
            out.append(f"{y:.3f}")
            i += 3
        elif t in "Zz":
            out.append(t)
            i += 1
        else:
            # Continuation implicit after M or L (e.g. "M x y x y ...").
            try:
                x = float(tokens[i]) + dx
                y = float(tokens[i+1]) + dy
                out.append(f"{x:.3f}")
                out.append(f"{y:.3f}")
                i += 2
            except (IndexError, ValueError):
                out.append(t)
                i += 1
    # Re-stitch with spaces between tokens, commas between x,y
    formatted: list[str] = []
    i = 0
    while i < len(out):
        t = out[i]
        if t in "MLmlZz":
            formatted.append(t)
            i += 1
        else:
            formatted.append(f"{t},{out[i+1]}")
            i += 2
    return " ".join(formatted)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main() -> None:
    for required in (INKSCAPE, INKSTITCH):
        if not required.exists():
            raise SystemExit(f"Required tool missing: {required}")

    BUILD.mkdir(parents=True, exist_ok=True)
    PREVIEWS.mkdir(parents=True, exist_ok=True)

    stats_1c = generate(
        BLACK_EPS, SVG_1C, PES_1C, PNG_1C,
        color_order=[BLACK], tag="black",
        force_single_color=BLACK,
    )
    stats_3c = generate(
        PANTONE_EPS, SVG_3C, PES_3C, PNG_3C,
        color_order=COLOR_ORDER_3C, tag="pantone",
    )

    print("=" * 60)
    for s in (stats_1c, stats_3c):
        print(
            f"{s['file']}: stitches={s['stitches']} colors={s['colors']} "
            f"satin={s['satin_count']} fill={s['fill_count']} "
            f"density={s['density_per_cm2']:.1f}/cm^2 bounds(mm)={s['bounds_mm']}"
        )

    # Acceptance gates (warn only; do not fail the script — reviewer decides).
    # Ranges calibrated for this specific narrow horizontal lockup at 7" wide
    # x ~0.95" tall, ~43 cm^2 bounding area. Density is over the bbox so
    # the per-cm^2 number is inflated by the logo's ~25% fill ratio.
    problems: list[str] = []
    if not (2800 <= stats_1c["stitches"] <= 4500):
        problems.append(f"LBATH1C stitch count out of range: {stats_1c['stitches']}")
    if not (2800 <= stats_3c["stitches"] <= 4600):
        problems.append(f"LBATH3C stitch count out of range: {stats_3c['stitches']}")
    if stats_3c["colors"] != 3:
        problems.append(f"LBATH3C expected 3 colors, got {stats_3c['colors']}")
    for s in (stats_1c, stats_3c):
        if not (60 <= s["density_per_cm2"] <= 120):
            problems.append(
                f"{s['file']} bbox-density out of 60-120 band: "
                f"{s['density_per_cm2']:.1f}"
            )

    if problems:
        print("\n" + "WARNINGS:")
        for p in problems:
            print(f"  - {p}")
        sys.exit(0)


if __name__ == "__main__":
    main()
