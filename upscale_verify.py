"""upscale_verify.py — the SPEC.md §8 / CLAUDE.md denominator-rule check for
the upscale wrapper.

An "output is 0.4x source" report reads identically whether the encode
finished cleanly or died after 40 frames — size ratio alone can't tell a
correct small result from a truncated one. This module checks both: the
output's size ratio against source (SPEC.md §8's Class A row — "output size
vs source, as a ratio, alongside the model/CRF settings used to produce it")
and its duration against source, since a truncated pipe produces a short but
otherwise well-formed file that a size-only check would wave through.

Frame counts and durations are reported on *every* run, pass or fail, and
each failure kind gets its own exit code, so none of them can be reported in
the words of a pass — the same shape as srt_verify.py's denominator rule for
the subtitle path.

The actual pass/fail decision (_evaluate) is kept separate from the ffprobe
I/O (probe_media) and file-existence checks (verify_upscale) specifically so
it's testable against synthetic probe dicts, with no real video file needed
— see tests/test_upscale_verify.py.

Exit codes:
  0  pass — output exists, is not truncated, ratio within max_ratio, denominators > 0
  1  usage / IO error (bad path, unreadable, unprobeable, or a source with no
     measurable video at all — that's a precondition failure, not a verdict)
  2  zero denominator — "measured nothing": 0 frames or 0 duration in the output
  3  truncated — output duration below source duration * duration_tolerance
  4  size ratio exceeded max_ratio
"""
from __future__ import annotations

import argparse
import dataclasses
import json
import os
import subprocess
import sys
from typing import Optional

FFPROBE = os.environ.get("REEL_FFPROBE", "ffprobe")

DEFAULT_MAX_RATIO = 5.0  # SPEC.md §3's own number: "5-10x" is the stated failure.
# Measured against source bytes, so it implicitly assumes roughly a 2x
# upscale (4x the pixels) — a 4x upscale (16x the pixels) can legitimately
# exceed this at the same CRF; raise --max-ratio for it rather than treating
# a trip of this gate as automatically wrong.
DEFAULT_DURATION_TOLERANCE = 0.99


def probe_media(path: str) -> dict:
    """ffprobe path -> {duration, frames, bytes, video_codec, audio_codec,
    audio_duration, has_audio}. Raises RuntimeError on an unprobeable file
    (e.g. an unfinalized container from a killed encode — mp4 with no moov
    atom, mkv with a missing/garbage duration)."""
    cmd = [FFPROBE, "-v", "error", "-print_format", "json",
           "-show_format", "-show_streams", str(path)]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError(f"ffprobe failed on {path}:\n{proc.stderr[-2000:]}")

    try:
        data = json.loads(proc.stdout)
    except json.JSONDecodeError as e:
        raise RuntimeError(f"ffprobe produced unparseable output for {path}: {e}")

    fmt = data.get("format", {})
    streams = data.get("streams", [])
    video_streams = [s for s in streams if s.get("codec_type") == "video"]
    audio_streams = [s for s in streams if s.get("codec_type") == "audio"]

    file_bytes = int(fmt.get("size", 0) or 0)
    duration = float(fmt.get("duration", 0.0) or 0.0)

    frames = 0
    video_codec = None
    if video_streams:
        vs = video_streams[0]
        video_codec = vs.get("codec_name")
        nb_frames = vs.get("nb_frames")
        if nb_frames is not None:
            try:
                frames = int(nb_frames)
            except ValueError:
                frames = 0
        if frames == 0:
            # nb_frames is absent or unreliable (mkv routinely omits it) —
            # derive from duration * frame rate rather than paying for
            # -count_frames, which decodes the whole file.
            vs_duration = float(vs.get("duration", duration) or duration)
            num, _, den = vs.get("r_frame_rate", "0/1").partition("/")
            try:
                fps = float(num) / float(den) if float(den or 0) else 0.0
            except ValueError:
                fps = 0.0
            frames = int(round(vs_duration * fps))

    audio_codec = audio_streams[0].get("codec_name") if audio_streams else None
    audio_duration = float(audio_streams[0].get("duration", 0.0) or 0.0) if audio_streams else 0.0

    return dict(
        duration=duration, frames=frames, bytes=file_bytes,
        video_codec=video_codec, audio_codec=audio_codec,
        audio_duration=audio_duration, has_audio=bool(audio_streams),
    )


@dataclasses.dataclass
class UpscaleResult:
    source_path: str
    output_path: str
    model: Optional[str]
    crf: Optional[float]
    max_ratio: float
    duration_tolerance: float
    source_frames: int
    output_frames: int
    source_duration: float
    output_duration: float
    source_bytes: int
    output_bytes: int
    size_ratio: Optional[float]
    exit_code: int
    message: str

    @property
    def passed(self) -> bool:
        return self.exit_code == 0


def _result(source_path, output_path, model, crf, max_ratio, duration_tolerance,
            exit_code, message, **counts) -> UpscaleResult:
    defaults = dict(
        source_frames=0, output_frames=0,
        source_duration=0.0, output_duration=0.0,
        source_bytes=0, output_bytes=0,
        size_ratio=None,
    )
    defaults.update(counts)
    return UpscaleResult(
        source_path=source_path, output_path=output_path, model=model, crf=crf,
        max_ratio=max_ratio, duration_tolerance=duration_tolerance,
        exit_code=exit_code, message=message, **defaults,
    )


def _evaluate(
    source_path: str,
    output_path: str,
    source_info: dict,
    output_info: dict,
    model: Optional[str],
    crf: Optional[float],
    max_ratio: float,
    duration_tolerance: float,
) -> UpscaleResult:
    """The pass/fail decision over two already-probed media summaries — pure,
    no I/O, so it's testable against synthetic probe dicts."""
    counts = dict(
        source_frames=source_info["frames"], output_frames=output_info["frames"],
        source_duration=source_info["duration"], output_duration=output_info["duration"],
        source_bytes=source_info["bytes"], output_bytes=output_info["bytes"],
    )

    if source_info["frames"] <= 0 or source_info["duration"] <= 0:
        # The source is a precondition, not a verdict subject — if it has no
        # measurable video, nothing below can mean anything.
        return _result(
            source_path, output_path, model, crf, max_ratio, duration_tolerance, 1,
            f"usage error: source has no measurable video "
            f"({source_info['frames']} frames, {source_info['duration']:.2f}s)",
            **counts,
        )

    if output_info["frames"] <= 0 or output_info["duration"] <= 0:
        return _result(
            source_path, output_path, model, crf, max_ratio, duration_tolerance, 2,
            f"measured nothing: output has {output_info['frames']} frames, "
            f"{output_info['duration']:.2f}s duration (source: {source_info['frames']} frames, "
            f"{source_info['duration']:.2f}s)",
            **counts,
        )

    if output_info["duration"] < source_info["duration"] * duration_tolerance:
        return _result(
            source_path, output_path, model, crf, max_ratio, duration_tolerance, 3,
            f"truncated output: {output_info['duration']:.2f}s vs source "
            f"{source_info['duration']:.2f}s (tolerance {duration_tolerance}), "
            f"{output_info['frames']} vs {source_info['frames']} frames",
            **counts,
        )

    size_ratio = output_info["bytes"] / source_info["bytes"] if source_info["bytes"] else None
    counts["size_ratio"] = size_ratio

    if size_ratio is not None and size_ratio > max_ratio:
        return _result(
            source_path, output_path, model, crf, max_ratio, duration_tolerance, 4,
            f"size ratio exceeded: {size_ratio:.2f}x source "
            f"({output_info['bytes']} vs {source_info['bytes']} bytes), max is {max_ratio}x, "
            f"model={model} crf={crf}",
            **counts,
        )

    return _result(
        source_path, output_path, model, crf, max_ratio, duration_tolerance, 0,
        f"pass: {size_ratio:.2f}x source size ({output_info['bytes']} vs {source_info['bytes']} bytes), "
        f"{output_info['duration']:.2f}s output vs {source_info['duration']:.2f}s source, "
        f"model={model} crf={crf}",
        **counts,
    )


def verify_upscale(
    source_path: str,
    output_path: str,
    model: Optional[str] = None,
    crf: Optional[float] = None,
    max_ratio: float = DEFAULT_MAX_RATIO,
    duration_tolerance: float = DEFAULT_DURATION_TOLERANCE,
) -> UpscaleResult:
    if not os.path.isfile(source_path):
        return _result(source_path, output_path, model, crf, max_ratio, duration_tolerance,
                        1, f"usage error: no such file: {source_path}")
    if not os.path.isfile(output_path):
        return _result(source_path, output_path, model, crf, max_ratio, duration_tolerance,
                        1, f"usage error: no such file: {output_path}")

    try:
        source_info = probe_media(source_path)
    except RuntimeError as e:
        return _result(source_path, output_path, model, crf, max_ratio, duration_tolerance,
                        1, f"usage error: could not probe source: {e}")
    try:
        output_info = probe_media(output_path)
    except RuntimeError as e:
        return _result(source_path, output_path, model, crf, max_ratio, duration_tolerance,
                        1, f"usage error: could not probe output: {e}")

    return _evaluate(source_path, output_path, source_info, output_info,
                      model, crf, max_ratio, duration_tolerance)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="Verify an upscale output per SPEC.md §8's denominator rule."
    )
    parser.add_argument("source_path")
    parser.add_argument("output_path")
    parser.add_argument("--model", default=None, help="model name used, for the report (default: unknown)")
    parser.add_argument("--crf", type=float, default=None, help="CRF used, for the report (default: unknown)")
    parser.add_argument("--max-ratio", type=float, default=DEFAULT_MAX_RATIO,
                         help=f"fail if output/source size exceeds this (default: {DEFAULT_MAX_RATIO}; "
                              "assumes roughly a 2x upscale — raise it for --scale 4 and similar)")
    parser.add_argument("--duration-tolerance", type=float, default=DEFAULT_DURATION_TOLERANCE,
                         help="fail if output duration falls below source duration times this fraction "
                              f"(default: {DEFAULT_DURATION_TOLERANCE})")
    args = parser.parse_args(argv)

    result = verify_upscale(args.source_path, args.output_path, model=args.model, crf=args.crf,
                             max_ratio=args.max_ratio, duration_tolerance=args.duration_tolerance)
    print(result.message)
    print(
        f"source_frames={result.source_frames} output_frames={result.output_frames} "
        f"source_duration={result.source_duration} output_duration={result.output_duration} "
        f"source_bytes={result.source_bytes} output_bytes={result.output_bytes} "
        f"size_ratio={result.size_ratio} model={result.model} crf={result.crf}"
    )
    return result.exit_code


if __name__ == "__main__":
    sys.exit(main())
