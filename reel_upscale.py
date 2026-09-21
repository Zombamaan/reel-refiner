r"""reel_upscale.py — SPEC.md §7's upscale must-have: `tvai_up` piped into a
CRF-quality H.265/AV1 encode so output doesn't inflate 5-10x over source
(CAPTURE.md's friction #2), with the §8 encode-size check.

Topaz's bundled ffmpeg (7.1.5) has **no software H.265/AV1 encoder** — only
hevc_nvenc/av1_nvenc/hevc_qsv/av1_qsv/hevc_amf/av1_amf, none of which take a
true -crf. The only CRF-capable encoder in that binary is libvpx-vp9, which
is neither H.265 nor AV1. SPEC.md §9's "one command" is therefore not
satisfiable on this machine as literally written — see docs/SPEC-FEEDBACK.md.
This module runs `tvai_up` in Topaz's ffmpeg piped into a *second*, system
ffmpeg process (which does have libx265/libsvtav1) for the actual CRF encode.
Confirms CAPTURE.md's own framing: the size problem is "a settings issue...
knowledge, not capability" — Topaz's own encoder presets carry no quality
parameter at all (models/video-encoders.json's h265-main-win-nvidia:
`-c:v hevc_nvenc -profile:v main -pix_fmt yuv420p -b_ref_mode disabled
-tag:v hvc1 -g 30`), which is the concrete mechanism behind the inflation.

Two environment facts this machine needed, recorded nowhere in the spec:
- TVAI_MODEL_DIR must point at Topaz's model directory
  (C:\ProgramData\Topaz Labs LLC\Topaz Video AI\models by default) or
  tvai_up fails immediately with "Model not found", before any GPU work —
  confirmed against Topaz's own log line `TVAI_MODEL_DIR, veaiDataFolder`.
- Two Topaz installs can coexist on one machine (the spec'd perpetual
  "Topaz Video AI" 7.1.5, and a separate subscription-era "Topaz Video").
  REEL_TVAI_FFMPEG pins the 7.1.5 binary explicitly.

Audio bypasses the pipe entirely: a raw video pipe carries no audio stream,
so the original file is given to the encoder as a second input and its
audio is copied straight through (-map 1:a? -c:a copy), never touching
tvai_up. tvai_up does not change frame rate, so this stays in sync — but
upscale_verify.py checks output duration against source rather than
assuming it, since a truncated pipe would otherwise look identical to a
clean short clip.

File safety (CLAUDE.md): the same three-branch output-location rule as
reel_subtitles.py (next to a real clip, out/<clip>/ for this repo's own
samples/, --out overrides both). Model and CRF are folded into the output
filename so repeat runs at different settings coexist instead of
overwriting each other, the same reasoning that put the device into
en.cuda.srt. The self-overwrite guard is kept as an explicit assert, same
as reel_subtitles.py's — the naming scheme (an appended
".upscaled.<model>.crf<N>" segment) makes a real collision just as
unreachable here as there; it stays load-bearing enough to assert rather
than assume.
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from upscale_verify import DEFAULT_DURATION_TOLERANCE, DEFAULT_MAX_RATIO, verify_upscale

FFMPEG = os.environ.get("REEL_FFMPEG", "ffmpeg")
TVAI_FFMPEG = os.environ.get(
    "REEL_TVAI_FFMPEG",
    r"C:\Program Files\Topaz Labs LLC\Topaz Video AI\ffmpeg.exe",  # 7.1.5, not "Topaz Video" 1.2.1
)
TVAI_MODEL_DIR = os.environ.get(
    "REEL_TVAI_MODEL_DIR",
    r"C:\ProgramData\Topaz Labs LLC\Topaz Video AI\models",
)
SAMPLES_ROOT = (Path(__file__).parent / "samples").resolve()
DEV_OUT_ROOT = (Path(__file__).parent / "out").resolve()

DEFAULT_CRF = 20  # conservative: don't discard the detail tvai_up just spent GPU time synthesizing
DEFAULT_SCALE = 2

# The only CRF-capable encoders exercised here; the flag each one takes for
# "roughly CRF." hevc_nvenc's -cq is NVENC's constant-quality mode, not a
# true CRF — offered for speed, not as the default (see module docstring).
ENCODER_CRF_FLAGS = {
    "libx265": "-crf",
    "libsvtav1": "-crf",
    "hevc_nvenc": "-cq",
}

_CONTAINER_EXTS = {"mkv", "mp4", "mov"}
_TVAI_DEVICE_ALIASES = {"auto": "-2", "cpu": "-1"}  # else a bare GPU index, e.g. "0"


def _tvai_device_arg(device: str) -> str:
    return _TVAI_DEVICE_ALIASES.get(device, device)


def _tvai_env() -> dict:
    env = os.environ.copy()
    env["TVAI_MODEL_DIR"] = TVAI_MODEL_DIR
    env["TVAI_MODEL_DATA_DIR"] = TVAI_MODEL_DIR
    return env


def _pick_container(input_suffix: str, container_arg: str | None) -> str:
    if container_arg:
        return container_arg.lstrip(".")
    ext = input_suffix.lstrip(".").lower()
    return ext if ext in _CONTAINER_EXTS else "mkv"


def _assert_distinct_from_input(out_path: Path, video_path: Path) -> None:
    if out_path.resolve() == video_path.resolve():
        raise RuntimeError("refusing to write output over the input file")


def _build_output_path(
    video_path: Path, out_dir: str | None, model: str, crf: float, container: str,
) -> tuple[Path, bool]:
    # Only true when out_dir wasn't given AND the input lives under this
    # repo's samples/ — the one case CLAUDE.md says must never write output
    # in place. Everything else (a real clip, or an explicit --out even for
    # a sample clip) is the caller's own choice of location.
    is_dev_default = out_dir is None and SAMPLES_ROOT in video_path.parents

    if out_dir is not None:
        out_dir_path = Path(out_dir).resolve()
        out_name = f"{video_path.stem}.upscaled.{model}.crf{crf:g}.{container}"
    elif is_dev_default:
        clip_name = video_path.parent.name
        out_dir_path = DEV_OUT_ROOT / clip_name
        out_name = f"upscaled.{model}.crf{crf:g}.{container}"
    else:
        # Real clip, no --out given: write next to the input (CLAUDE.md's
        # File Safety section), never into this repo's out/.
        out_dir_path = video_path.parent
        out_name = f"{video_path.stem}.upscaled.{model}.crf{crf:g}.{container}"

    out_dir_path.mkdir(parents=True, exist_ok=True)
    out_path = out_dir_path / out_name
    _assert_distinct_from_input(out_path, video_path)
    return out_path, is_dev_default


def preflight(model: str, encoder: str) -> None:
    """Fail in seconds, not after committing GPU hours: Topaz's ffmpeg and
    tvai_up exist, the model name is real, the chosen encoder is available,
    and a one-frame tvai_up smoke run against a synthetic source actually
    succeeds (validates model dir *and* entitlement together — the same
    class of check SPEC.md §4's GPU rule demands, applied before hours of
    GPU time instead of after)."""
    if not Path(TVAI_FFMPEG).is_file():
        raise RuntimeError(
            f"Topaz ffmpeg not found at {TVAI_FFMPEG} (set REEL_TVAI_FFMPEG if "
            "7.1.5 is installed somewhere else — a separate, subscription-era "
            "'Topaz Video' install does not have the same binary)"
        )
    filters = subprocess.run([TVAI_FFMPEG, "-hide_banner", "-filters"], capture_output=True, text=True)
    if "tvai_up" not in filters.stdout:
        raise RuntimeError(f"{TVAI_FFMPEG} does not expose the tvai_up filter")

    model_dir = Path(TVAI_MODEL_DIR)
    if not model_dir.is_dir():
        raise RuntimeError(f"Topaz model dir not found: {model_dir} (set REEL_TVAI_MODEL_DIR)")
    if not (model_dir / f"{model}.json").is_file():
        raise RuntimeError(
            f"model '{model}' not found in {model_dir} — SPEC.md §2/§13: this "
            "wrapper never picks a model, the name must match one exactly"
        )

    encoders = subprocess.run([FFMPEG, "-hide_banner", "-encoders"], capture_output=True, text=True)
    if encoder not in encoders.stdout:
        raise RuntimeError(f"{FFMPEG} does not have the '{encoder}' encoder available")

    smoke_cmd = [
        TVAI_FFMPEG, "-hide_banner", "-loglevel", "error",
        # rate=8 duration=1, not rate=1: tvai_up **segfaults** (not a clean
        # error — confirmed on this machine) on fewer than 4 input frames,
        # presumably a temporal/lookahead buffer the model needs filled
        # before it will run at all. 8 frames stays well clear of that
        # threshold while keeping the smoke test at well under a second of
        # actual model work. See docs/SPEC-FEEDBACK.md.
        "-f", "lavfi", "-i", "testsrc2=size=64x64:rate=8:duration=1",
        "-vf", f"tvai_up=model={model}:scale=1:download=0",
        "-f", "null", "-",
    ]
    smoke = subprocess.run(smoke_cmd, capture_output=True, text=True, env=_tvai_env())
    if smoke.returncode != 0:
        raise RuntimeError(f"tvai_up smoke test failed for model '{model}':\n{smoke.stderr[-2000:]}")


def run_pipe(
    video_path: Path,
    out_path: Path,
    model: str,
    scale: int | None,
    width: int | None,
    height: int | None,
    device: str,
    crf: float,
    encoder: str,
    preset: str,
    pix_fmt: str,
    keep_metadata: bool,
) -> float:
    """Runs Topaz's tvai_up piped into a system-ffmpeg CRF encode. Returns
    wall_seconds. Raises RuntimeError, including Topaz's stderr tail, if
    either process fails — a Topaz-side failure otherwise surfaces only as a
    confusing "broken pipe"-shaped error from the encoder side."""
    tvai_filter = f"tvai_up=model={model}:device={_tvai_device_arg(device)}:download=0"
    if width or height:
        tvai_filter += f":w={width or 0}:h={height or 0}"
    else:
        tvai_filter += f":scale={scale}"

    tvai_cmd = [
        TVAI_FFMPEG, "-hide_banner", "-y", "-i", str(video_path),
        "-vf", tvai_filter, "-an",
        "-pix_fmt", pix_fmt, "-f", "nut", "-c:v", "rawvideo", "pipe:1",
    ]

    crf_flag = ENCODER_CRF_FLAGS[encoder]
    enc_cmd = [
        FFMPEG, "-hide_banner", "-y",
        "-f", "nut", "-i", "pipe:0",
        "-i", str(video_path),
        "-map", "0:v", "-map", "1:a?",
    ]
    if keep_metadata:
        enc_cmd += ["-map_metadata", "1"]
    enc_cmd += [
        "-c:v", encoder, crf_flag, str(crf), "-preset", preset,
        "-c:a", "copy",
        str(out_path),
    ]

    t0 = time.time()
    with tempfile.TemporaryDirectory(prefix="reel_upscale_") as tmp:
        tvai_log_path = Path(tmp) / "tvai_stderr.log"
        with open(tvai_log_path, "w", encoding="utf-8", errors="replace") as tvai_log_fh:
            producer = subprocess.Popen(tvai_cmd, stdout=subprocess.PIPE, stderr=tvai_log_fh, env=_tvai_env())
            consumer = subprocess.Popen(enc_cmd, stdin=producer.stdout, stderr=subprocess.PIPE, text=True)
            producer.stdout.close()  # so the producer sees a broken pipe if the consumer dies first

            enc_tail: list[str] = []
            for line in consumer.stderr:
                enc_tail.append(line)
                enc_tail = enc_tail[-40:]
                stripped = line.strip()
                if stripped:
                    print(f"  encode: {stripped}")

            consumer.wait()
            producer.wait()

        tvai_stderr_tail = tvai_log_path.read_text(encoding="utf-8", errors="replace")[-2000:]

    elapsed = time.time() - t0

    if producer.returncode != 0 or consumer.returncode != 0:
        raise RuntimeError(
            f"upscale pipe failed (tvai exit={producer.returncode}, encode exit={consumer.returncode})\n"
            f"--- Topaz ffmpeg stderr (tail) ---\n{tvai_stderr_tail}\n"
            f"--- encoder stderr (tail) ---\n{''.join(enc_tail)}"
        )
    return elapsed


def run(
    input_path: str,
    model: str,
    out_dir: str | None = None,
    scale: int | None = None,
    width: int | None = None,
    height: int | None = None,
    device: str = "auto",
    crf: float = DEFAULT_CRF,
    encoder: str = "libx265",
    preset: str = "medium",
    pix_fmt: str = "yuv420p",
    container: str | None = None,
    keep_metadata: bool = True,
    max_ratio: float = DEFAULT_MAX_RATIO,
    duration_tolerance: float = DEFAULT_DURATION_TOLERANCE,
    skip_preflight: bool = False,
) -> int:
    video_path = Path(input_path).resolve()
    if not video_path.is_file():
        print(f"usage error: no such file: {video_path}", file=sys.stderr)
        return 1

    if encoder not in ENCODER_CRF_FLAGS:
        print(f"usage error: unknown --encoder '{encoder}' (choices: {', '.join(sorted(ENCODER_CRF_FLAGS))})",
              file=sys.stderr)
        return 1

    if width is None and height is None and scale is None:
        scale = DEFAULT_SCALE

    resolved_container = _pick_container(video_path.suffix, container)
    out_path, is_dev_default = _build_output_path(video_path, out_dir, model, crf, resolved_container)

    if not skip_preflight:
        print(f"preflight: checking Topaz ffmpeg, model '{model}', and encoder '{encoder}' ...")
        preflight(model, encoder)
        print("  preflight passed")

    scale_desc = f"{width or '?'}x{height or '?'}" if (width or height) else f"scale={scale}"
    print(f"upscaling {video_path.name} (model={model}, {scale_desc}, device={device}) "
          f"into {encoder} crf={crf} ...")
    elapsed = run_pipe(
        video_path, out_path, model, scale, width, height, device,
        crf, encoder, preset, pix_fmt, keep_metadata,
    )
    print(f"wrote {out_path} in {elapsed:.1f}s wall time on {device}")

    # The verification is part of the command, not a separate chore (SPEC.md
    # §8's denominator rule) — its exit code is this command's exit code.
    result = verify_upscale(str(video_path), str(out_path), model=model, crf=crf,
                             max_ratio=max_ratio, duration_tolerance=duration_tolerance)
    print(result.message)
    print(
        f"source_frames={result.source_frames} output_frames={result.output_frames} "
        f"source_duration={result.source_duration} output_duration={result.output_duration} "
        f"source_bytes={result.source_bytes} output_bytes={result.output_bytes} "
        f"size_ratio={result.size_ratio} model={result.model} crf={result.crf} "
        f"wall_seconds={elapsed:.1f} device={device}"
    )

    return result.exit_code


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="Upscale a clip with Topaz's tvai_up, piped into a CRF-quality H.265/AV1 encode."
    )
    parser.add_argument("input", help="path to the source video file")
    parser.add_argument("--model", required=True,
                         help="tvai_up model short name, e.g. ahq-12 (SPEC.md §2/§13: this wrapper "
                              "never picks a model, the owner's call permanently)")
    parser.add_argument("--scale", type=int, default=None,
                         help="tvai_up output scale, 1-4 (default: 2, unless --width/--height given)")
    parser.add_argument("--width", type=int, default=None,
                         help="estimate scale from output width instead of --scale (pairs with --height)")
    parser.add_argument("--height", type=int, default=None,
                         help="estimate scale from output height instead of --scale (pairs with --width)")
    parser.add_argument("--crf", type=float, default=DEFAULT_CRF,
                         help=f"encoder CRF (default: {DEFAULT_CRF} — conservative, preserves the detail "
                              "tvai_up just spent GPU time synthesizing)")
    parser.add_argument("--encoder", choices=sorted(ENCODER_CRF_FLAGS), default="libx265",
                         help="default: libx265 — true CRF, per SPEC.md §9. Topaz's bundled ffmpeg has "
                              "no software H.265/AV1 encoder, so this runs in a second, system ffmpeg "
                              "process (see docs/SPEC-FEEDBACK.md)")
    parser.add_argument("--preset", default="medium", help="encoder preset (default: medium)")
    parser.add_argument("--pix-fmt", default="yuv420p",
                         help="pipe/output pixel format (default: yuv420p; use yuv420p10le for 10-bit)")
    parser.add_argument("--device", default="auto",
                         help="tvai_up device: auto, cpu, or a GPU index (default: auto). "
                              "SPEC.md §4 requires a working cpu fallback")
    parser.add_argument("--container", default=None,
                         help="output container extension (default: matches the input's, falling back "
                              "to mkv if that's not mkv/mp4/mov)")
    parser.add_argument("--out", default=None,
                         help="output directory (default: next to the input for a real clip; "
                              "out/<clip>/ when the input is under this repo's samples/)")
    parser.add_argument("--no-keep-metadata", dest="keep_metadata", action="store_false",
                         help="drop the source file's container metadata instead of copying it through")
    parser.add_argument("--max-ratio", type=float, default=DEFAULT_MAX_RATIO,
                         help=f"fail if output/source size exceeds this (default: {DEFAULT_MAX_RATIO}; "
                              "assumes roughly a 2x upscale — raise it for --scale 4 and similar)")
    parser.add_argument("--duration-tolerance", type=float, default=DEFAULT_DURATION_TOLERANCE,
                         help="fail if output duration falls below source duration times this fraction "
                              f"(default: {DEFAULT_DURATION_TOLERANCE})")
    parser.add_argument("--skip-preflight", action="store_true",
                         help="skip the pre-encode sanity checks (model exists, encoder available, "
                              "a one-frame tvai_up smoke test)")
    args = parser.parse_args(argv)

    if args.scale is not None and (args.width is not None or args.height is not None):
        parser.error("--scale cannot be combined with --width/--height")

    return run(
        args.input, args.model, out_dir=args.out, scale=args.scale,
        width=args.width, height=args.height, device=args.device, crf=args.crf,
        encoder=args.encoder, preset=args.preset, pix_fmt=args.pix_fmt,
        container=args.container, keep_metadata=args.keep_metadata,
        max_ratio=args.max_ratio, duration_tolerance=args.duration_tolerance,
        skip_preflight=args.skip_preflight,
    )


if __name__ == "__main__":
    sys.exit(main())
