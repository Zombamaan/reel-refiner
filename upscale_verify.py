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
  3  truncated — the output's *video stream* is short: its duration or its
     frame count is below the source's * duration_tolerance
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


def _as_float(value) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _as_int(*values) -> int:
    """First of `values` that parses as a positive int, else 0 — ffprobe
    writes "N/A", None or a missing key depending on container."""
    for value in values:
        try:
            parsed = int(value)
        except (TypeError, ValueError):
            continue
        if parsed > 0:
            return parsed
    return 0


def _parse_rate(rate: str) -> float:
    num, _, den = (rate or "0/1").partition("/")
    numerator, denominator = _as_float(num), _as_float(den)
    return numerator / denominator if denominator else 0.0


def probe_media(path: str) -> dict:
    """ffprobe path -> {duration, frames, bytes, video_codec, audio_codec,
    audio_duration, has_audio, container_duration, duration_source}. Raises
    RuntimeError on an unprobeable file (e.g. an unfinalized container from a
    killed encode — mp4 with no moov atom, mkv with a missing/garbage duration).

    **`duration` and `frames` describe the video stream specifically, never
    the container.** reel_upscale.py copies the source's full-length audio
    into the output, so `format.duration` is the *max* of the video and audio
    streams. A pipe that dies mid-encode leaves a short video stream beside a
    complete audio one, and a container-level reading reports the audio's
    length — which made the truncation gate pass a file missing 60% of its
    video. Measured: a 4.08s / 102-frame video muxed with 10s of audio reports
    `format.duration=10.0`. `duration_source` records which of the three
    fallbacks supplied the figure, so a container-level guess is visible in
    the report rather than silent."""
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

    fmt = data.get("format", {})
    streams = data.get("streams", [])
    video_streams = [s for s in streams if s.get("codec_type") == "video"]
    audio_streams = [s for s in streams if s.get("codec_type") == "audio"]

    file_bytes = _as_int(fmt.get("size"))
    container_duration = _as_float(fmt.get("duration"))

    frames = 0
    duration = 0.0
    duration_source = "none"
    video_codec = None
    if video_streams:
        vs = video_streams[0]
        video_codec = vs.get("codec_name")
        fps = _parse_rate(vs.get("r_frame_rate"))
        # nb_frames where the container records it; else nb_read_packets from
        # -count_packets, which walks packet headers without decoding (mkv
        # routinely omits nb_frames). -count_frames would decode the whole
        # file and is not worth it.
        frames = _as_int(vs.get("nb_frames"), vs.get("nb_read_packets"))
        stream_duration = _as_float(vs.get("duration"))

        if stream_duration > 0:
            duration, duration_source = stream_duration, "stream"
        elif frames > 0 and fps > 0:
            duration, duration_source = frames / fps, "frames"
        else:
            # Last resort only. Audio-inflated, so it can overstate a
            # truncated video — the frame-count gate in _evaluate is what
            # catches that case when we land here.
            duration, duration_source = container_duration, "container"

        if frames == 0 and fps > 0 and duration > 0:
            frames = int(round(duration * fps))

    audio_codec = audio_streams[0].get("codec_name") if audio_streams else None
    audio_duration = _as_float(audio_streams[0].get("duration")) if audio_streams else 0.0

    return dict(
        duration=duration, frames=frames, bytes=file_bytes,
        video_codec=video_codec, audio_codec=audio_codec,
        audio_duration=audio_duration, has_audio=bool(audio_streams),
        container_duration=container_duration, duration_source=duration_source,
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

    # Two independent truncation signals, because either can be the only one
    # available: some containers give a reliable video-stream duration, others
    # only a frame count. Whichever fires, the output is short.
    short_duration = output_info["duration"] < source_info["duration"] * duration_tolerance
    short_frames = (
        source_info["frames"] > 0
        and output_info["frames"] < source_info["frames"] * duration_tolerance
    )
    if short_duration or short_frames:
        tripped = "duration and frame count" if (short_duration and short_frames) else (
            "duration" if short_duration else "frame count")
        return _result(
            source_path, output_path, model, crf, max_ratio, duration_tolerance, 3,
            f"truncated output ({tripped} short): {output_info['duration']:.2f}s vs source "
            f"{source_info['duration']:.2f}s, {output_info['frames']} vs "
            f"{source_info['frames']} frames (tolerance {duration_tolerance})",
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

    # size_ratio is None when ffprobe reports no format.size — report that
    # plainly instead of formatting None, which raised TypeError here.
    ratio_text = (f"{size_ratio:.2f}x source size "
                  f"({output_info['bytes']} vs {source_info['bytes']} bytes)"
                  if size_ratio is not None else
                  "size ratio unavailable (source size unreported by ffprobe)")
    return _result(
        source_path, output_path, model, crf, max_ratio, duration_tolerance, 0,
        f"pass: {ratio_text}, "
        f"{output_info['duration']:.2f}s output vs {source_info['duration']:.2f}s source, "
        f"{output_info['frames']} vs {source_info['frames']} frames, model={model} crf={crf}",
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
