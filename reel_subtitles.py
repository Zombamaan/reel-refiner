"""reel_subtitles.py — SPEC.md §7's subtitle must-have: one command from a
non-English clip to gist-quality English .srt, with the §8 language check.

Backend: faster-whisper (ctranslate2 4.8.2), chosen over the spec's other
named candidate and one off-spec alternative after probing all three on this
machine — see docs/SPEC-FEEDBACK.md for the full comparison. It is the only
one that showed clean, reproducible CUDA use with no silent degradation.

GPU / CUDA (SPEC.md §4): assume broken until proven otherwise. This machine's
ctranslate2 needs CUDA 12.x's cublas/cudnn, which the system driver (CUDA 13)
does not supply as loadable DLLs by itself — so this module adds the
pip-installed nvidia-cublas-cu12 / nvidia-cudnn-cu12 packages' bin directories
to the DLL search path before touching CUDA. --device cpu always works
without any of this and is the required fallback.

File safety (CLAUDE.md): a **real clip** (anywhere outside this repo's
samples/) gets its output written next to the input, `<stem>.<lang>.srt` —
"these tools write outputs next to inputs the owner names on the command
line." A **sample clip** (under samples/, dev-testing only) never writes
there — CLAUDE.md's explicit carve-out — so it goes to out/<clip>/ instead,
device-suffixed (`en.cuda.srt`, `en.cpu.srt`) so testing both devices
against the same clip doesn't silently overwrite one result with the other.
Explicit --out always overrides both defaults, plain `<stem>.<lang>.srt`
naming, caller's own responsibility. An output name is always distinct from
its input either way — never a move, never a rename, never in place.
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import srt as srt_lib

from dev_compare import write_compare_script
from srt_verify import DEFAULT_THRESHOLD, verify_srt

FFMPEG = os.environ.get("REEL_FFMPEG", "ffmpeg")
SAMPLES_ROOT = (Path(__file__).parent / "samples").resolve()
DEV_OUT_ROOT = (Path(__file__).parent / "out").resolve()


def _add_cuda_runtime_to_path() -> None:
    """Make the pip-installed CUDA 12.x cublas/cudnn wheels' DLLs loadable.

    ctranslate2 4.8.2 links against CUDA 12's cublas64_12.dll and
    cudnn64_9.dll specifically. This machine's driver is CUDA 13; those
    libraries aren't on PATH unless something puts them there. The
    nvidia-cublas-cu12 / nvidia-cudnn-cu12 pip packages ship them — this
    finds those packages' bin directories and adds them, so --device cuda
    works without the caller having to set up PATH by hand.
    """
    try:
        import nvidia.cublas as _cublas  # type: ignore
        import nvidia.cudnn as _cudnn  # type: ignore
    except ImportError:
        return  # not installed — --device cuda will fail with a clear error later

    for pkg in (_cublas, _cudnn):
        pkg_dir = Path(list(pkg.__path__)[0])
        bin_dir = pkg_dir / "bin"
        if bin_dir.is_dir():
            os.environ["PATH"] = str(bin_dir) + os.pathsep + os.environ.get("PATH", "")
            if hasattr(os, "add_dll_directory"):  # Windows-only, Python 3.8+
                os.add_dll_directory(str(bin_dir))


def extract_audio(video_path: Path, workdir: Path) -> Path:
    """ffmpeg video/audio -> 16kHz mono wav, into workdir (never next to the
    source, never overwriting it)."""
    audio_path = workdir / (video_path.stem + ".16k.wav")
    cmd = [
        FFMPEG, "-y", "-i", str(video_path),
        "-ar", "16000", "-ac", "1", "-vn",
        str(audio_path),
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError(f"ffmpeg audio extraction failed:\n{proc.stderr[-2000:]}")
    return audio_path


def transcribe(
    audio_path: Path,
    device: str,
    model_size: str,
    source_language: str | None,
) -> tuple[list, str, float, float]:
    """Returns (segments, detected_source_lang, lang_probability, wall_seconds)."""
    if device == "cuda":
        _add_cuda_runtime_to_path()

    from faster_whisper import WhisperModel  # imported late: torch/ct2 are heavy

    compute_type = "float16" if device == "cuda" else "int8"
    model = WhisperModel(model_size, device=device, compute_type=compute_type)

    t0 = time.time()
    segments, info = model.transcribe(
        str(audio_path), language=source_language, task="translate",
    )
    segments = list(segments)  # the generator does the actual work; materialize it here
    elapsed = time.time() - t0
    return segments, info.language, info.language_probability, elapsed


def segments_to_srt(segments) -> str:
    subs = [
        srt_lib.Subtitle(
            index=i,
            start=srt_lib.timedelta(seconds=seg.start),
            end=srt_lib.timedelta(seconds=seg.end),
            content=seg.text.strip(),
        )
        for i, seg in enumerate(segments, start=1)
    ]
    return srt_lib.compose(subs)


def run(
    input_path: str,
    out_dir: str | None = None,
    device: str = "cuda",
    model_size: str = "medium",
    source_language: str | None = None,
    target_lang: str = "en",
    confidence_threshold: float = DEFAULT_THRESHOLD,
) -> int:
    video_path = Path(input_path).resolve()
    if not video_path.is_file():
        print(f"usage error: no such file: {video_path}", file=sys.stderr)
        return 1

    # Only true when out_dir wasn't given AND the input lives under this
    # repo's samples/ — the one case CLAUDE.md says must never write output
    # in place. Everything else (a real clip, or an explicit --out even for
    # a sample clip) is the caller's own choice of location.
    is_dev_default = out_dir is None and SAMPLES_ROOT in video_path.parents

    if out_dir is not None:
        out_dir_path = Path(out_dir).resolve()
        srt_name = f"{video_path.stem}.{target_lang}.srt"
    elif is_dev_default:
        clip_name = video_path.parent.name
        out_dir_path = DEV_OUT_ROOT / clip_name
        srt_name = f"{target_lang}.{device}.srt"
    else:
        # Real clip, no --out given: write next to the input (CLAUDE.md's
        # File Safety section), never into this repo's out/.
        out_dir_path = video_path.parent
        srt_name = f"{video_path.stem}.{target_lang}.srt"

    out_dir_path.mkdir(parents=True, exist_ok=True)
    srt_path = out_dir_path / srt_name
    if srt_path.resolve() == video_path.resolve():
        # Unreachable given the suffix, but the file-safety rule (CLAUDE.md,
        # SPEC.md §4) is load-bearing enough to assert rather than assume.
        raise RuntimeError("refusing to write output over the input file")

    with tempfile.TemporaryDirectory(prefix="reel_subtitles_") as tmp:
        tmp_path = Path(tmp)
        print(f"extracting audio from {video_path.name} ...")
        audio_path = extract_audio(video_path, tmp_path)

        print(f"transcribing with faster-whisper ({model_size}, device={device}, task=translate) ...")
        segments, detected_src_lang, src_lang_prob, elapsed = transcribe(
            audio_path, device, model_size, source_language,
        )
        print(f"  source language detected: {detected_src_lang} (p={src_lang_prob:.3f}), "
              f"{len(segments)} segments, {elapsed:.1f}s wall time on {device}")

    srt_text = segments_to_srt(segments)
    srt_path.write_text(srt_text, encoding="utf-8")
    print(f"wrote {srt_path}")

    # The verification is part of the command, not a separate chore (SPEC.md
    # §8's denominator rule) — its exit code is this command's exit code.
    result = verify_srt(str(srt_path), target_lang=target_lang, threshold=confidence_threshold)
    print(result.message)
    print(
        f"cues={result.cue_count} nonempty={result.nonempty_cue_count} "
        f"scoreable_cues={result.scoreable_cue_count} scoreable_chars={result.scoreable_chars} "
        f"detected={result.detected_lang} confidence={result.confidence} "
        f"cjk_ratio={result.cjk_ratio} latin_ratio={result.latin_ratio}"
    )

    if is_dev_default:
        # Only where a reference transcript actually accompanies this
        # sample clip — nothing to compare against otherwise.
        reference_matches = sorted(video_path.parent.glob(f"reference.{target_lang}.*"))
        if reference_matches:
            script_path = write_compare_script(
                clip_dir=video_path.parent,
                reference_path=reference_matches[0],
                candidate_dir=out_dir_path,
                candidate_glob=f"{target_lang}.*.srt",
            )
            if script_path:
                print(f"updated {script_path}")

    return result.exit_code


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="Generate a verified-English .srt from a non-English video clip."
    )
    parser.add_argument("input", help="path to the source video/audio file")
    parser.add_argument("--out", default=None,
                         help="output directory (default: next to the input for a real clip; "
                              "out/<clip>/ when the input is under this repo's samples/)")
    parser.add_argument("--device", choices=["cuda", "cpu"], default="cuda",
                         help="SPEC.md §4 requires a working cpu fallback; default cuda")
    parser.add_argument("--model", default="medium",
                         help="faster-whisper model size (default: medium)")
    parser.add_argument("--language", default=None,
                         help="source spoken language code, e.g. 'ja' (default: auto-detect)")
    parser.add_argument("--target-lang", default="en",
                         help="expected output language for the §8 check (default: en)")
    parser.add_argument("--confidence-threshold", type=float, default=DEFAULT_THRESHOLD)
    args = parser.parse_args(argv)

    return run(
        args.input, out_dir=args.out, device=args.device, model_size=args.model,
        source_language=args.language, target_lang=args.target_lang,
        confidence_threshold=args.confidence_threshold,
    )


if __name__ == "__main__":
    sys.exit(main())
