"""survey_candidates.py — finds clips that would make good *test material*
for the three tools. Dev tooling, not a product feature.

**This is not the library-survey mode SPEC.md §2/§13 excludes, and must not
become it.** It emits no candidacy verdict and never decides whether anything
is worth upscaling — that judgement stays in reel_candidacy.py, invoked per
file by the owner. All this does is read metadata and group files by which
*untested dimension* they would exercise, so verification material can be
chosen for coverage instead of guessed at. Same scope as scripts/score_srt.py
and scripts/fleurs_baseline.py: build-time evidence, not a shipped feature
(docs/SPEC-FEEDBACK.md finding #7).

It is strictly read-only — ffprobe only, no decoding, nothing written
anywhere, including into the directory being scanned.

What it can see: container and codec spread, bits-per-pixel-per-second (the
best cheap proxy for "heavily compressed"), variable frame rate, interlacing,
bit depth, audio track count and codec, and whether the container reports
nb_frames — which is exactly the fallback path upscale_verify.probe_media and
reel_candidacy.probe_video take when it is missing.

**What it cannot see: grain, and whether something was already upscaled.**
Grain is not in metadata at all, and it is the single dimension most likely to
move a candidacy number (it adds real broadband energy, which may inflate the
effective-resolution estimate and misfire --blocking-worth). Prior upscaling
needs decoding, and detecting the AI kind is impossible even then
(docs/SPEC-FEEDBACK.md finding #16). Pick those two by eye.
"""
from __future__ import annotations

import argparse
import concurrent.futures
import json
import os
import subprocess
import sys
from pathlib import Path

FFPROBE = os.environ.get("REEL_FFPROBE", "ffprobe")

VIDEO_EXTS = {".mp4", ".mkv", ".avi", ".mov", ".ts", ".m2ts", ".webm", ".wmv",
              ".flv", ".m4v", ".mpg", ".mpeg", ".vob", ".divx", ".rmvb", ".asf"}

# Bits per pixel per second: bitrate / (width * height * fps). Content-
# independent enough to compare a 4K file against a 480p one, which raw
# bitrate is not. Rough bands from common encoding practice.
BPP_HEAVY = 0.04   # below this, aggressively compressed — the core use case
BPP_CLEAN = 0.15   # above this, a high-quality source worth using as a control

DIMENSIONS = [
    ("low-bpp-highres", "heavily compressed at a high resolution — the core use case, "
                        "and the most likely place a stretched source hides"),
    ("clean-highres", "high bitrate at a high resolution — the control case, should read 'not worth'"),
    ("no-nb-frames", "container reports no frame count — exercises the probe fallbacks added "
                     "for the truncation gate"),
    ("odd-container", "transport streams and the like — least-tested muxing path"),
    ("variable-frame-rate", "avg and base frame rates disagree — exercises -fps_mode passthrough "
                            "in the upscale pipe"),
    ("interlaced", "field order is not progressive — wholly untested"),
    ("ten-bit", "10-bit source — note reel_upscale defaults to --pix-fmt yuv420p (8-bit), so "
                "this would be silently downconverted unless you pass yuv420p10le"),
    ("multi-audio", "more than one audio track — exercises -map 1:a? passthrough"),
    ("lossy-non-aac", "audio codec other than aac — exercises -c:a copy across codecs"),
]


def _f(value) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _rate(value: str) -> float:
    num, _, den = (value or "0/1").partition("/")
    numerator, denominator = _f(num), _f(den)
    return numerator / denominator if denominator else 0.0


def probe(path: Path) -> dict | None:
    """Metadata only — no -count_packets, no -count_frames, nothing that
    walks or decodes the file. Returns None for anything unprobeable."""
    cmd = [FFPROBE, "-v", "error", "-print_format", "json",
           "-show_format", "-show_streams", str(path)]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
    except (subprocess.TimeoutExpired, OSError):
        return None
    if proc.returncode != 0:
        return None
    try:
        data = json.loads(proc.stdout)
    except json.JSONDecodeError:
        return None

    streams = data.get("streams", [])
    video = [s for s in streams if s.get("codec_type") == "video"]
    audio = [s for s in streams if s.get("codec_type") == "audio"]
    if not video:
        return None
    vs, fmt = video[0], data.get("format", {})

    width, height = int(_f(vs.get("width"))), int(_f(vs.get("height")))
    fps = _rate(vs.get("r_frame_rate"))
    avg_fps = _rate(vs.get("avg_frame_rate"))
    bitrate = _f(vs.get("bit_rate")) or _f(fmt.get("bit_rate"))
    pixels_per_second = width * height * fps
    bpp = bitrate / pixels_per_second if pixels_per_second else 0.0

    return dict(
        path=path, width=width, height=height, fps=fps, avg_fps=avg_fps,
        bitrate=bitrate, bpp=bpp,
        codec=vs.get("codec_name"), pix_fmt=vs.get("pix_fmt") or "",
        field_order=vs.get("field_order") or "progressive",
        has_nb_frames=bool(_f(vs.get("nb_frames"))),
        duration=_f(fmt.get("duration")),
        size=_f(fmt.get("size")),
        audio_count=len(audio),
        audio_codecs=[a.get("codec_name") for a in audio],
        ext=path.suffix.lower(),
    )


def classify(info: dict) -> list:
    """Which untested dimensions this file would cover. A file can cover
    several; that makes it a better pick, not an ambiguous one."""
    tags = []
    tall = info["height"] >= 720

    if tall and 0 < info["bpp"] < BPP_HEAVY:
        tags.append("low-bpp-highres")
    if tall and info["bpp"] >= BPP_CLEAN:
        tags.append("clean-highres")
    if not info["has_nb_frames"]:
        tags.append("no-nb-frames")
    if info["ext"] in {".ts", ".m2ts", ".vob", ".mpg", ".mpeg", ".avi", ".wmv", ".asf", ".rmvb"}:
        tags.append("odd-container")
    if info["fps"] and info["avg_fps"] and abs(info["fps"] - info["avg_fps"]) > 0.01:
        tags.append("variable-frame-rate")
    if info["field_order"] not in ("progressive", "unknown", ""):
        tags.append("interlaced")
    if "10" in info["pix_fmt"] or "12" in info["pix_fmt"]:
        tags.append("ten-bit")
    if info["audio_count"] > 1:
        tags.append("multi-audio")
    if any(c and c != "aac" for c in info["audio_codecs"]):
        tags.append("lossy-non-aac")
    return tags


def find_videos(roots: list, max_files: int) -> list:
    found = []
    for root in roots:
        base = Path(root)
        if base.is_file():
            if base.suffix.lower() in VIDEO_EXTS:
                found.append(base)
            continue
        for dirpath, _dirnames, filenames in os.walk(base, onerror=lambda e: None):
            for name in filenames:
                if Path(name).suffix.lower() in VIDEO_EXTS:
                    found.append(Path(dirpath) / name)
                    if len(found) >= max_files:
                        return found
    return found


def describe(info: dict) -> str:
    seconds = info["duration"]
    length = f"{seconds:.0f}s" if seconds < 60 else f"{seconds / 60:.0f}min"
    audio = "+".join(c for c in info["audio_codecs"] if c) or "none"
    return (f"{info['width']}x{info['height']} {info['codec']} "
            f"{info['bitrate'] / 1000:,.0f}kbps bpp={info['bpp']:.3f} "
            f"{length} audio={audio}")


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="Group video files by which untested dimension they would cover, "
                    "to choose verification material. Emits no candidacy verdict."
    )
    parser.add_argument("roots", nargs="+", help="directories (or files) to scan")
    parser.add_argument("--per-dimension", type=int, default=4,
                         help="how many examples to show per dimension (default: 4)")
    parser.add_argument("--max-files", type=int, default=3000,
                         help="stop walking after this many video files (default: 3000)")
    parser.add_argument("--workers", type=int, default=8,
                         help="parallel ffprobe calls (default: 8)")
    args = parser.parse_args(argv)

    paths = find_videos(args.roots, args.max_files)
    if not paths:
        print("found no video files under: " + ", ".join(args.roots), file=sys.stderr)
        return 1
    print(f"probing {len(paths)} files (metadata only, nothing decoded) ...")

    infos = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=args.workers) as pool:
        for info in pool.map(probe, paths):
            if info:
                infos.append(info)

    unprobeable = len(paths) - len(infos)
    print(f"  {len(infos)} probed, {unprobeable} unprobeable or without a video stream\n")
    if not infos:
        return 1

    buckets = {name: [] for name, _ in DIMENSIONS}
    for info in infos:
        for tag in classify(info):
            buckets[tag].append(info)

    # Most extreme first within each bucket, so the strongest example leads.
    sort_keys = {
        "low-bpp-highres": lambda i: i["bpp"],
        "clean-highres": lambda i: -i["bpp"],
    }
    for name, why in DIMENSIONS:
        rows = buckets[name]
        if not rows:
            continue
        rows.sort(key=sort_keys.get(name, lambda i: -i["width"] * i["height"]))
        print(f"covers: {name}  ({len(rows)} found)")
        print(f"  {why}")
        for info in rows[:args.per_dimension]:
            print(f"    {info['path']}")
            print(f"      {describe(info)}")
        print()

    missing = [name for name, _ in DIMENSIONS if not buckets[name]]
    if missing:
        print("no candidate found for: " + ", ".join(missing))
        print("  (not a problem — those dimensions just stay untested for now)\n")

    print("NOT detectable from metadata, pick these by eye:")
    print("  - grainy / film-sourced footage — the dimension most likely to move a candidacy")
    print("    number, since grain adds real broadband energy")
    print("  - anything you already know was upscaled — valuable precisely because the tool")
    print("    should fail to detect it (docs/SPEC-FEEDBACK.md finding #16)")
    print("\nThen run the real tool, one file at a time:")
    print("  python reel_candidacy.py <path>")
    return 0


if __name__ == "__main__":
    sys.exit(main())
