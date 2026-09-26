#!/usr/bin/env python3
"""
gpx_animate.py — Turn a GPX file into a short animated MP4.

Pipeline: GPX -> resampled points -> matplotlib frames -> ffmpeg -> MP4

Usage:
    python gpx_animate.py trip.gpx
    python gpx_animate.py trip.gpx --style osm --duration 5 --hold 1 --out trip.mp4
"""

from __future__ import annotations

import argparse
import math
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

import contextily as cx
import gpxpy
import matplotlib
import pyproj
import requests


# Identify your app to OSM tile servers (required by their usage policy)
# Change the email/URL to something that identifies you.
requests.utils.default_headers()["User-Agent"] = (
    "GPX-Animate/1.0 (+https://github.com/enarroied/mess_box/tree/master/gpx_stuff; eric.narro.ied@gmail.com)"
)

matplotlib.use("Agg")
# E402: these must follow matplotlib.use("Agg") or pyplot picks a GUI backend.
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
from matplotlib.collections import LineCollection  # noqa: E402


# ---------------------------------------------------------------------------
# CONFIG — edit here, override via CLI flags
# ---------------------------------------------------------------------------

# Mixed value types (str, float, int, None, Path), overridden per run from the
# CLI, so `Any` is deliberate here. SPECS US-2 replaces this bag with a typed
# RenderConfig.
CONFIG: dict[str, Any] = {
    # --- map appearance ---
    "style": "topo",  # positron | osm | topo | dark | voyager | satellite
    "zoom_padding": 0.15,  # extra margin around the track bbox
    # --- animation timing ---
    "duration": 5.0,  # seconds of the drawing phase
    "hold": 1.0,  # seconds to hold the finished trace
    "fps": 30,
    # --- output ---
    "size": "16:9",  # 16:9 | 1:1 | 9:16  (YouTube / Medium / Shorts)
    "dpi": 150,
    "out": None,  # None -> <gpx_stem>.mp4
    # --- look & feel ---
    "bg_color": "#f5f5f2",  # matches positron nicely
    "track_faint": "#b8b8b8",  # full route, drawn underneath
    "track_bright": "#e63946",  # the growing line
    "marker_color": "#1d3557",  # current position dot
    "hud_color": "#1d3557",
    "title_color": "#1d3557",
    "font": "DejaVu Sans",
    "logo": None,  # path to a PNG with transparency, optional
    "logo_position": "bottom-right",  # bottom-right | bottom-left | top-right | top-left
}


# Basemap presets (contextily / tile providers)
def _carto(url_template, key_env="CARTO_API_KEY"):
    """Build a Carto provider dict, injecting the API key if available."""
    key = os.environ.get(key_env)
    if not key:
        return None  # signal: fall back
    url = url_template.replace("{key}", key)
    return {
        "url": url,
        "attribution": "© OpenStreetMap contributors, © CARTO",
        "max_zoom": 20,
    }


STYLES = {
    # Key-free providers (always work)
    # The three suppressions below are for static analysis only:
    # xyzservices.providers is populated at runtime by Bunch, so ty cannot see
    # the members. They come out with the file at M2 (SPECS US-2).
    "osm": cx.providers.OpenStreetMap.Mapnik,  # ty: ignore[unresolved-attribute]
    "topo": cx.providers.OpenTopoMap,  # ty: ignore[unresolved-attribute]
    "satellite": cx.providers.Esri.WorldImagery,  # ty: ignore[unresolved-attribute]
    # Carto providers — require CARTO_API_KEY env var
    "positron": _carto(
        "https://basemaps.cartocdn.com/rastertiles/positron/{z}/{x}/{y}.png?key={key}"
    ),
    "voyager": _carto(
        "https://basemaps.cartocdn.com/rastertiles/voyager/{z}/{x}/{y}.png?key={key}"
    ),
    "dark": _carto(
        "https://basemaps.cartocdn.com/rastertiles/dark_all/{z}/{x}/{y}.png?key={key}"
    ),
}

# Drop any Carto styles that had no key available
STYLES = {k: v for k, v in STYLES.items() if v is not None}

SIZES = {
    "16:9": (12.8, 7.2),
    "1:1": (9.0, 9.0),
    "9:16": (7.2, 12.8),
}

# ---------------------------------------------------------------------------
# GPX parsing
# ---------------------------------------------------------------------------


def load_track(gpx_path: Path):
    """Return (lons, lats, elevations, name) from the first track/segment."""
    with gpx_path.open() as f:
        gpx = gpxpy.parse(f)

    name = gpx.name or gpx_path.stem.replace("_", " ").title()
    points = []

    for track in gpx.tracks:
        for seg in track.segments:
            for p in seg.points:
                points.append((p.longitude, p.latitude, p.elevation or 0.0))

    if not points:
        # fall back to routes / waypoints
        for r in gpx.routes:
            for p in r.points:
                points.append((p.longitude, p.latitude, p.elevation or 0.0))

    if not points:
        raise ValueError(f"No track/route points found in {gpx_path}")

    arr = np.array(points, dtype=float)
    return arr[:, 0], arr[:, 1], arr[:, 2], name


# ---------------------------------------------------------------------------
# Geometry helpers
# ---------------------------------------------------------------------------


def haversine_km(lon1, lat1, lon2, lat2):
    R = 6371.0
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlam = math.radians(lon2 - lon1)
    a = (
        math.sin(dphi / 2) ** 2
        + math.cos(phi1) * math.cos(phi2) * math.sin(dlam / 2) ** 2
    )
    return 2 * R * math.asin(math.sqrt(a))


def cumulative_distance_km(lons, lats):
    d = np.zeros(len(lons))
    for i in range(1, len(lons)):
        d[i] = d[i - 1] + haversine_km(lons[i - 1], lats[i - 1], lons[i], lats[i])
    return d


def cumulative_gain_m(ele):
    gain = 0.0
    for i in range(1, len(ele)):
        if ele[i] > ele[i - 1]:
            gain += ele[i] - ele[i - 1]
    return gain


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------


def render_frames(cfg, lons, lats, ele, name, out_dir: Path):
    dists = cumulative_distance_km(lons, lats)
    total_km = float(dists[-1]) if len(dists) else 0.0
    total_gain = cumulative_gain_m(ele)

    n_draw_frames = int(cfg["duration"] * cfg["fps"])
    n_hold_frames = int(cfg["hold"] * cfg["fps"])
    n_frames = n_draw_frames + n_hold_frames

    transformer = pyproj.Transformer.from_crs("EPSG:4326", "EPSG:3857", always_xy=True)
    X, Y = transformer.transform(lons, lats)

    # figure
    W, H = SIZES[cfg["size"]]
    fig, ax = plt.subplots(figsize=(W, H), dpi=cfg["dpi"])
    fig.patch.set_facecolor(cfg["bg_color"])
    ax.set_facecolor(cfg["bg_color"])

    # bounds with padding
    pad_x = (X.max() - X.min()) * cfg["zoom_padding"] or 1.0
    pad_y = (Y.max() - Y.min()) * cfg["zoom_padding"] or 1.0
    ax.set_xlim(X.min() - pad_x, X.max() + pad_x)
    ax.set_ylim(Y.min() - pad_y, Y.max() + pad_y)

    # basemap
    provider = STYLES[cfg["style"]]
    cx.add_basemap(
        ax,
        source=provider,
        crs="EPSG:3857",
        attribution_size=6,
        zoom="auto",
        headers={
            "User-Agent": "GPX-Animate/1.0 (+https://github.com/enarroied/mess_box/tree/master/gpx_stuff; eric.narro.ied@gmail.com)"
        },
    )

    # faint full track
    ax.plot(
        X,
        Y,
        color=cfg["track_faint"],
        lw=3,
        alpha=0.7,
        solid_capstyle="round",
        zorder=3,
    )

    # bright growing line (will be a LineCollection updated each frame)
    segs = np.stack(
        [np.column_stack([X[:-1], Y[:-1]]), np.column_stack([X[1:], Y[1:]])], axis=1
    )
    lc = LineCollection(
        [],
        colors=cfg["track_bright"],
        linewidths=4,
        capstyle="round",
        joinstyle="round",
        zorder=4,
    )
    ax.add_collection(lc)

    (marker,) = ax.plot(
        [],
        [],
        "o",
        color=cfg["marker_color"],
        markersize=10,
        markeredgecolor="white",
        markeredgewidth=1.5,
        zorder=5,
    )

    # HUD
    hud = ax.text(
        0.02,
        0.98,
        "",
        transform=ax.transAxes,
        ha="left",
        va="top",
        fontsize=12,
        color=cfg["hud_color"],
        family=cfg["font"],
        zorder=10,
        bbox={
            "boxstyle": "round,pad=0.5",
            "facecolor": "white",
            "edgecolor": "none",
            "alpha": 0.75,
        },
    )

    # title
    ax.text(
        0.02,
        0.06,
        name,
        transform=ax.transAxes,
        ha="left",
        va="bottom",
        fontsize=18,
        weight="bold",
        color=cfg["title_color"],
        family=cfg["font"],
        zorder=10,
    )

    # logo
    logo_img = None
    if cfg["logo"]:
        logo_img = plt.imread(cfg["logo"])
        pos = {
            "bottom-right": (0.98, 0.05, "right", "bottom"),
            "bottom-left": (0.02, 0.05, "left", "bottom"),
            "top-right": (0.98, 0.95, "right", "top"),
            "top-left": (0.02, 0.95, "left", "top"),
        }[cfg["logo_position"]]
        lx, ly, ha, va = pos
        ax.imshow(
            logo_img,
            transform=ax.transAxes,
            zorder=10,
            extent=(lx - 0.12, lx, ly, ly + 0.12)
            if ha == "right"
            else (lx, lx + 0.12, ly, ly + 0.12),
            aspect="auto",
        )

    ax.set_axis_off()
    fig.tight_layout(pad=0)

    # render
    frame_paths = []
    for i in range(n_frames):
        # Hold frames reuse the final state.
        t = i / max(1, n_draw_frames - 1) if i < n_draw_frames else 1.0

        n_pts = max(2, int(round(t * (len(X) - 1))) + 1)
        n_pts = min(n_pts, len(X))

        # matplotlib's stub types set_segments too narrowly for a real ndarray.
        lc.set_segments(segs[: n_pts - 1])  # ty: ignore[invalid-argument-type]
        marker.set_data([X[n_pts - 1]], [Y[n_pts - 1]])

        done_km = float(dists[n_pts - 1])
        done_ele = float(ele[n_pts - 1])
        hud.set_text(
            f"Distance   {done_km:5.1f} / {total_km:.1f} km\n"
            f"Elevation  {done_ele:5.0f} m  (+{total_gain:.0f} m total)"
        )

        fp = out_dir / f"frame_{i:05d}.png"
        fig.savefig(fp, dpi=cfg["dpi"], facecolor=fig.get_facecolor())
        frame_paths.append(fp)

    plt.close(fig)
    return frame_paths, n_frames


# ---------------------------------------------------------------------------
# ffmpeg
# ---------------------------------------------------------------------------


def frames_to_video(frame_dir: Path, fps: int, out_path: Path):
    if shutil.which("ffmpeg") is None:
        sys.exit("ffmpeg not found on PATH. Install it and retry.")

    cmd = [
        "ffmpeg",
        "-y",
        "-framerate",
        str(fps),
        "-i",
        str(frame_dir / "frame_%05d.png"),
        "-c:v",
        "libx264",
        "-pix_fmt",
        "yuv420p",
        "-crf",
        "18",
        "-preset",
        "slow",
        str(out_path),
    ]
    subprocess.run(cmd, check=True)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def parse_args():
    p = argparse.ArgumentParser(description="Animate a GPX file into a short MP4.")
    p.add_argument("gpx", type=Path)
    p.add_argument("--style", choices=list(STYLES.keys()), help="basemap style")
    p.add_argument("--duration", type=float, help="drawing duration in seconds")
    p.add_argument("--hold", type=float, help="hold time at the end, seconds")
    p.add_argument("--fps", type=int)
    p.add_argument("--size", choices=list(SIZES.keys()))
    p.add_argument("--out", type=Path)
    p.add_argument("--logo", type=Path)
    p.add_argument(
        "--logo-position",
        choices=["bottom-right", "bottom-left", "top-right", "top-left"],
    )
    return p.parse_args()


def main():
    args = parse_args()
    cfg = dict(CONFIG)

    for k in (
        "style",
        "duration",
        "hold",
        "fps",
        "size",
        "out",
        "logo",
        "logo_position",
    ):
        v = getattr(args, k, None)
        if v is not None:
            cfg[k] = v

    if cfg["out"] is None:
        cfg["out"] = args.gpx.with_suffix(".mp4")
    cfg["out"] = Path(cfg["out"])

    print(f"→ Parsing {args.gpx}")
    lons, lats, ele, name = load_track(args.gpx)
    print(f"  {len(lons)} points · route: {name}")

    with tempfile.TemporaryDirectory() as td:
        tdp = Path(td)
        print(
            f"→ Rendering frames ({cfg['style']}, {cfg['duration']}s + {cfg['hold']}s hold @ {cfg['fps']}fps)"
        )
        _, n_frames = render_frames(cfg, lons, lats, ele, name, tdp)
        print(f"  {n_frames} frames")

        print(f"→ Encoding {cfg['out']}")
        frames_to_video(tdp, cfg["fps"], cfg["out"])

    print(f"✓ Done: {cfg['out']}")


if __name__ == "__main__":
    main()
