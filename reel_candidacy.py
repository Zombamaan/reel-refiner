"""reel_candidacy.py — SPEC.md §7's candidacy must-have: a computed verdict
on whether a source is worth upscaling, before hours are spent on one that
wasn't (CAPTURE.md's friction #3, the only one classed Trust / evaluation).

Samples frames across the file, computes SPEC.md §8's three candidacy
metrics over each (candidacy_verify.frame_metrics), takes the median, and
maps the result to a verdict. Every metric is reported beside the number of
frames sampled, and a run that finds no usable frames is "broken" rather
than "no defects found" — CLAUDE.md's denominator rule.

The exit code carries the verdict (0 worth / 3 marginal / 4 not worth), so a
run chains straight into the upscale wrapper:

    python reel_candidacy.py clip.mp4 && python reel_upscale.py clip.mp4 --model ahq-12

That was an explicit owner decision, and it is the reason this tool needs
hard thresholds at all — the report text can hedge, an exit code cannot.
Every threshold is a flag whose default is annotated with the measurement it
came from; none was guessed (docs/SPEC-FEEDBACK.md finding #17).

**What this tool cannot do**, stated on every run rather than buried: the
effective-resolution metric catches conventional stretched upscales, not AI
ones. See candidacy_verify.CAVEAT and docs/SPEC-FEEDBACK.md finding #16.

Frames are sampled with fast seeks (-ss before -i) at evenly spaced
timestamps, skipping the first and last 5% so a black intro or outro doesn't
dominate the sample. Analysis happens at the source's **native** resolution:
downscaling first would destroy the very high-frequency content the
effective-resolution metric measures.

File safety (CLAUDE.md): same three-branch rule as its two siblings — a real
clip's reports go next to the input, a samples/ clip's go to out/<clip>/,
and --out overrides both. Re-running overwrites the previous report
deliberately: unlike an upscale, a run costs seconds and a newer answer
supersedes an older one rather than competing with it.

This module deliberately does not import reel_subtitles or reel_upscale
(CLAUDE.md: each tool independently runnable, no import-time dependency on
the others), which is why it carries its own small ffprobe helper rather
than reusing upscale_verify's.
"""
from __future__ import annotations

import argparse
import datetime
import json
import os
import subprocess
import sys
import time
from pathlib import Path

import numpy as np

from candidacy_verify import (
    CAVEAT,
    DEFAULT_FRAMES,
    _evaluate,
    add_threshold_args,
    default_thresholds,
    frame_metrics,
    summary_line,
    threshold_kwargs,
)

FFMPEG = os.environ.get("REEL_FFMPEG", "ffmpeg")
FFPROBE = os.environ.get("REEL_FFPROBE", "ffprobe")
SAMPLES_ROOT = (Path(__file__).parent / "samples").resolve()
DEV_OUT_ROOT = (Path(__file__).parent / "out").resolve()

EDGE_SKIP = 0.05  # ignore the first and last 5% — black intros/outros aren't representative


def probe_video(path: Path) -> dict:
    """ffprobe path -> {width, height, duration, codec}. Raises RuntimeError on
    an unprobeable file, so the caller has a single failure channel to convert
    into exit 1.

    Duration prefers the video stream's own figure, then frames ÷ frame rate
    (`-count_packets` walks packet headers without decoding), and only then the
    container's. It matters because a duration of 0 makes sample_timestamps
    degenerate: every sample lands on the same frame, and the run would report
    N usable frames having examined one."""
    cmd = [FFPROBE, "-v", "error", "-print_format", "json",
           "-show_format", "-show_streams", "-count_packets", str(path)]
    proc = subprocess.run(cmd, capture_output=True, text=True,
                          encoding="utf-8", errors="replace")
    if proc.returncode != 0:
        raise RuntimeError(f"ffprobe failed on {path}:\n{proc.stderr[-2000:]}")
    try:
        data = json.loads(proc.stdout)
    except json.JSONDecodeError as e:
        raise RuntimeError(f"ffprobe produced unparseable output for {path}: {e}")

    video = [s for s in data.get("streams", []) if s.get("codec_type") == "video"]
    if not video:
        raise RuntimeError(f"no video stream in {path}")
    vs = video[0]

    def _f(value):
        try:
            return float(value)
        except (TypeError, ValueError):
            return 0.0

    duration = _f(vs.get("duration"))
    if duration <= 0:
        frames = 0
        for key in ("nb_frames", "nb_read_packets"):
            frames = int(_f(vs.get(key)))
            if frames > 0:
                break
        num, _, den = (vs.get("r_frame_rate") or "0/1").partition("/")
        fps = _f(num) / _f(den) if _f(den) else 0.0
        if frames > 0 and fps > 0:
            duration = frames / fps
    if duration <= 0:
        duration = _f(data.get("format", {}).get("duration"))

    return dict(
        width=int(vs.get("width", 0) or 0),
        height=int(vs.get("height", 0) or 0),
        duration=duration,
        codec=vs.get("codec_name"),
    )


def sample_timestamps(duration: float, count: int) -> list:
    """Evenly spaced across the middle 90% of the file.

    An unknown duration yields **one** timestamp, not `count` copies of zero.
    Returning N identical timestamps would have the run analyse frame 0 N
    times and then report N usable frames — a denominator claiming a breadth
    of sampling that never happened, which is exactly what CLAUDE.md's rule
    exists to prevent. run() refuses an unknown duration outright; this keeps
    the function honest on its own terms too."""
    if count <= 0:
        return []
    if duration <= 0:
        return [0.0]
    lo, hi = duration * EDGE_SKIP, duration * (1 - EDGE_SKIP)
    if hi <= lo:
        lo, hi = 0.0, max(duration - 0.001, 0.0)
    if count == 1:
        return [(lo + hi) / 2]
    step = (hi - lo) / (count - 1)
    return [lo + i * step for i in range(count)]


def extract_frame(video_path: Path, timestamp: float, width: int, height: int):
    """One luma plane at `timestamp` as a HxW uint8 array, or None if the
    frame could not be decoded. A failed frame is counted, never fatal —
    that is what the decoded-vs-requested denominator tier is for."""
    cmd = [
        FFMPEG, "-hide_banner", "-loglevel", "error",
        "-ss", f"{timestamp:.3f}", "-i", str(video_path),  # -ss before -i: fast seek
        "-frames:v", "1", "-vf", "format=gray", "-f", "rawvideo", "pipe:1",
    ]
    proc = subprocess.run(cmd, capture_output=True)
    expected = width * height
    if proc.returncode != 0 or len(proc.stdout) < expected:
        return None
    return np.frombuffer(proc.stdout[:expected], dtype=np.uint8).reshape(height, width)


def _assert_distinct_from_input(out_path: Path, video_path: Path) -> None:
    if out_path.resolve() == video_path.resolve():
        raise RuntimeError("refusing to write output over the input file")


def _build_report_paths(video_path: Path, out_dir: str | None) -> tuple:
    """(txt_path, json_path, is_dev_default), following the same three-branch
    rule as reel_subtitles.py and reel_upscale.py."""
    is_dev_default = out_dir is None and SAMPLES_ROOT in video_path.parents

    if out_dir is not None:
        out_dir_path = Path(out_dir).resolve()
        stem = f"{video_path.stem}.candidacy"
    elif is_dev_default:
        out_dir_path = DEV_OUT_ROOT / video_path.parent.name
        stem = "candidacy"
    else:
        # Real clip, no --out: next to the input (CLAUDE.md's File Safety
        # section), never into this repo's out/.
        out_dir_path = video_path.parent
        stem = f"{video_path.stem}.candidacy"

    out_dir_path.mkdir(parents=True, exist_ok=True)
    txt_path = out_dir_path / f"{stem}.txt"
    json_path = out_dir_path / f"{stem}.json"
    _assert_distinct_from_input(txt_path, video_path)
    _assert_distinct_from_input(json_path, video_path)
    return txt_path, json_path, is_dev_default


def render_report(result, info: dict, elapsed: float) -> str:
    lines = [
        "Reel Refiner — candidacy report",
        f"source:     {result.source_path}",
        f"container:  {result.container_width}x{result.container_height}"
        f"  {info.get('duration', 0.0):.2f}s  {info.get('codec')}",
        f"generated:  {datetime.datetime.now().isoformat(timespec='seconds')}"
        f"  ({elapsed:.1f}s wall time)",
        "",
        f"frames_requested={result.frames_requested} "
        f"frames_decoded={result.frames_decoded} frames_usable={result.frames_usable}",
        "",
    ]
    if result.frames_usable:
        lines += [
            f"  effective_resolution   ~{result.effective_resolution_px}p of "
            f"{result.container_height}p  ({result.effective_resolution_ratio * 100:.0f}% of container)",
            f"  blocking_score         {result.blocking:.2f}   (clean content ~1.0)",
            f"  banding_score          {result.banding:.2f}   (clean content ~1.0)",
            f"  hf_energy_ratio        {result.hf_energy_ratio:.3e}",
            "",
        ]
    # The reasons are listed once, under "because" — result.message already
    # embeds them for the console/summary line, so repeating it here verbatim
    # would print each reason twice.
    if result.reasons:
        lines += [
            f"VERDICT: {result.verdict.upper()}"
            f"  (over {result.frames_usable} usable frames of {result.frames_requested} sampled)",
            "  because:",
        ] + [f"    - {r}" for r in result.reasons] + [""]
    else:
        lines += [f"VERDICT: {result.verdict.upper()}", f"  {result.message}", ""]

    # Deliberately *after* the verdict, because it qualifies it rather than
    # competing with it. The verdict answers "is there headroom worth hours?";
    # this answers "how far could the measured detail actually be taken?".
    # Those come apart — a 4K container holding 1055p can be worth processing
    # for cleanup while gaining no resolution at all — and printing the target
    # first made that read as a contradiction.
    if result.suggested_target_px:
        lines += [
            f"SUGGESTED TARGET: {result.suggested_target_px}p"
            f"  — how far the measured detail could be taken, which is a",
            "                        different question from the verdict above",
            f"  {result.target_note}",
            f"  (derived from measured detail, never the container: "
            f"{result.thresholds.get('detail_multiplier')}x {result.effective_resolution_px}p "
            f"= {result.raw_target_px}p, snapped down to a standard",
            "   tier — past that an upscaler invents rather than resolves. "
            "Override with --detail-multiplier.)",
            "",
        ]
    lines += [f"CAVEAT: {result.caveat}", "",
              f"thresholds: {json.dumps(result.thresholds, sort_keys=True)}",
              f"exit_code:  {result.exit_code}"]
    return "\n".join(lines) + "\n"


def report_json(result, info: dict, elapsed: float) -> str:
    payload = dict(
        source_path=result.source_path,
        container_width=result.container_width,
        container_height=result.container_height,
        duration=info.get("duration"),
        codec=info.get("codec"),
        generated=datetime.datetime.now().isoformat(timespec="seconds"),
        wall_seconds=round(elapsed, 2),
        frames_requested=result.frames_requested,
        frames_decoded=result.frames_decoded,
        frames_usable=result.frames_usable,
        effective_resolution_px=result.effective_resolution_px,
        effective_resolution_ratio=result.effective_resolution_ratio,
        blocking=result.blocking,
        banding=result.banding,
        hf_energy_ratio=result.hf_energy_ratio,
        suggested_target_px=result.suggested_target_px,
        raw_target_px=result.raw_target_px,
        target_note=result.target_note,
        thresholds=result.thresholds,
        verdict=result.verdict,
        reasons=result.reasons,
        exit_code=result.exit_code,
        caveat=result.caveat,
        per_frame=result.per_frame,
    )
    return json.dumps(payload, indent=2, sort_keys=True) + "\n"


def run(
    input_path: str,
    out_dir: str | None = None,
    frames: int = DEFAULT_FRAMES,
    write_reports: bool = True,
    **threshold_overrides,
) -> int:
    video_path = Path(input_path).resolve()
    if not video_path.is_file():
        print(f"usage error: no such file: {video_path}", file=sys.stderr)
        return 1

    thresholds = default_thresholds(**threshold_overrides)

    try:
        info = probe_video(video_path)
    except RuntimeError as e:
        print(f"usage error: could not probe source: {e}", file=sys.stderr)
        return 1

    width, height, duration = info["width"], info["height"], info["duration"]
    if duration <= 0:
        # Refused rather than sampled: every timestamp would land on frame 0,
        # and the report would claim N frames examined on the strength of one.
        print(f"usage error: could not determine the duration of {video_path} "
              f"(no video-stream duration, no frame count, no container duration). "
              f"Sampling would analyse the same frame {frames} times and report it as "
              f"{frames} frames examined; refusing rather than overstating the denominator.",
              file=sys.stderr)
        return 1

    print(f"analysing {video_path.name} ({width}x{height}, {duration:.1f}s) "
          f"over {frames} sampled frames ...")

    t0 = time.time()
    per_frame = []
    for ts in sample_timestamps(duration, frames):
        gray = extract_frame(video_path, ts, width, height)
        if gray is None:
            per_frame.append(None)
            continue
        metrics = frame_metrics(gray)
        metrics["timestamp"] = round(ts, 3)
        per_frame.append(metrics)
    elapsed = time.time() - t0

    result = _evaluate(str(video_path), width, height, frames, per_frame, thresholds)

    print(f"  {result.frames_usable} usable of {result.frames_decoded} decoded "
          f"({frames} requested), {elapsed:.1f}s wall time")
    print(result.message)
    if result.suggested_target_px:
        print(f"suggested target: {result.suggested_target_px}p — {result.target_note}")
    print(summary_line(result))
    print(f"CAVEAT: {CAVEAT}")

    if write_reports:
        txt_path, json_path, _ = _build_report_paths(video_path, out_dir)
        txt_path.write_text(render_report(result, info, elapsed), encoding="utf-8")
        json_path.write_text(report_json(result, info, elapsed), encoding="utf-8")
        print(f"wrote {txt_path}")
        print(f"wrote {json_path}")

    return result.exit_code


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="Decide whether a video source is worth upscaling, before spending the hours."
    )
    parser.add_argument("input", help="path to the source video file")
    parser.add_argument("--frames", type=int, default=DEFAULT_FRAMES,
                         help=f"how many frames to sample (default: {DEFAULT_FRAMES}); reported as "
                              f"the denominator on every run, per CLAUDE.md")
    parser.add_argument("--out", default=None,
                         help="output directory for the reports (default: next to the input for a "
                              "real clip; out/<clip>/ when the input is under this repo's samples/)")
    parser.add_argument("--no-report", dest="write_reports", action="store_false",
                         help="print to the console only, write no .txt/.json report files")
    add_threshold_args(parser)
    args = parser.parse_args(argv)

    if args.frames < 1:
        parser.error("--frames must be at least 1")

    return run(args.input, out_dir=args.out, frames=args.frames,
               write_reports=args.write_reports, **threshold_kwargs(args))


if __name__ == "__main__":
    sys.exit(main())
