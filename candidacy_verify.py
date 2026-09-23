"""candidacy_verify.py — SPEC.md §8's candidacy metrics, and CLAUDE.md's
denominator rule applied to them.

SPEC.md §8 names three computable candidacy metrics: an effective-resolution
estimate, a blocking/banding score, and a high-frequency energy ratio. This
module computes all of them over one luma plane (frame_metrics), aggregates
across sampled frames, and maps the result to a verdict (_evaluate).

**What the effective-resolution metric can and cannot do.** Given content
band-limited at a known cutoff it recovers that cutoff to within 3% — the
maths is sound, and tests/test_candidacy_verify.py proves it against
synthetic planes. What it *cannot* do is tell you a real file was upscaled
before. Measured across 113 files from three real collections, the 31 whose
names mark a prior upscale read median 76% and the 82 unmarked ones 82% —
heavily overlapping, and which group reads higher flips between subsamples.
AI upscalers synthesize genuine high-frequency detail, which is exactly what
this test looks for, and real files vary in detail for many reasons other
than upscaling — compression above all — which swamp the one being sought.
Every report carries that caveat. See docs/SPEC-FEEDBACK.md finding #16 and
docs/MILESTONE-3-RESULTS.md.

What it *does* measure reliably is how much detail a file carries relative to
its container, which is a different and still-useful question — and it is
what suggest_target() reasons from.

Banding is measured as luma-histogram occupancy (span / distinct levels
present) rather than per-block level counting. The block approach was tried
first and abandoned: it scored 13.0 on clean detailed content (a false
positive) and found zero qualifying blocks on a clean gradient, with scores
swinging 1.57/8.92/13.00/1.15 on one frame depending on block-selection
criteria. Occupancy measures the quantization that *causes* banding and
separates cleanly — clean content 1.00-1.17, quantized content 8-21.

Tiered denominators, following srt_verify.py's cues -> non-empty ->
scoreable: a solid black or single-colour frame has no measurable spectrum
and would poison every metric, exactly as a "[Music]"-only cue has no
language to detect. So frames_requested -> frames_decoded -> frames_usable,
and the zero test gates on **usable**, never on decoded.

Unlike srt_verify.py and upscale_verify.py this module is not stdlib-only —
it needs numpy for the FFT. _evaluate() is still pure and media-free, so the
verdict logic stays testable against synthetic per-frame dicts.

Exit codes:
  0  worth upscaling
  1  usage / IO error (bad path, unreadable report, no measurable dimensions)
  2  zero denominator — no usable frames: "broken", never "no defects found"
  3  marginal
  4  not worth upscaling
"""
from __future__ import annotations

import argparse
import dataclasses
import json
import os
import statistics
import sys
from typing import Optional

import numpy as np

DEFAULT_FRAMES = 20  # 20 fast-seek extractions measured at 1.1s on a 20s clip

# Thresholds. Each is a keyword arg and a CLI flag; the defaults below are the
# values measured during the build (docs/MILESTONE-3-RESULTS.md), not guesses.
# Recalibrated against 113 files from three real collections (n=113, zero
# failures) — docs/MILESTONE-3-RESULTS.md. The original values came from
# synthetic testsrc2/gradient sources, where clean content reads 100% and
# damage reads 7-20. Real compressed video never reaches those figures: the
# measured detail ratio runs p25=70% med=82% p75=91%, and blocking spans
# 0.98-1.72 against an original 2.0 bar it never once crossed.
DEFAULT_MIN_RESOLUTION_RATIO = 0.70   # real: p25=0.70; synthetic-era value was 0.80
DEFAULT_RESOLUTION_MARGINAL = 0.90    # real: p75=0.91; synthetic-era value was 0.95
DEFAULT_BLOCKING_WORTH = 1.5          # real: p95=1.53, max=1.72; synthetic-era value was 2.0
DEFAULT_BLOCKING_MARGINAL = 1.25      # real: median=1.13

# Banding does not gate by default — None disables its checks entirely.
# Across those same 113 real files it spanned 1.00-1.20 and crossed neither
# its old 3.0 "worth" bar nor its 1.5 "marginal" bar even once. It measures
# luma-histogram occupancy, i.e. quantization, and modern encodes are dithered
# enough that the histogram stays full. It is still computed and reported on
# every run (SPEC.md §8 asks for the metric, not for it to decide anything),
# and per-frame values still reach the .json, so passing --banding-worth a
# number re-enables it without any code change.
DEFAULT_BANDING_WORTH = None
DEFAULT_BANDING_MARGINAL = None

# Target suggestion. Derived from *measured detail*, never from the container
# — which is the whole point. Deriving from the container fails in both
# directions: a flat 4K target over-applies on a low-resolution original, and
# a flat 2x explodes a low-quality 8K input to 16K. Measured detail is immune
# to both, because it is what the file actually contains rather than what its
# header claims.
STANDARD_HEIGHTS = (480, 720, 1080, 1440, 2160, 4320)
DEFAULT_DETAIL_MULTIPLIER = 2.0  # an upscaler resolves ~2x real detail; beyond that it invents

_RESIDUAL_FLOOR = 1e-4  # spectral energy above the cutoff, as a fraction of AC energy
_RADIAL_BINS = 256      # ~0.4% of frame height per bin
_MIN_SWEEP_BIN = int(0.06 * _RADIAL_BINS)  # never claim an effective resolution below 6%
_FLAT_FRAME_STD = 1.0   # below this a frame carries no measurable detail at all
_BLOCK = 8              # the DCT block grid every mainstream codec works in

CAVEAT = (
    "this measures how much detail a file carries relative to its container — it does NOT "
    "detect whether a file was upscaled before. Across 113 real files, 31 marked as prior "
    "upscales read median 76% against 82% for 82 unmarked ones: overlapping, with the "
    "direction flipping between subsamples. A clean reading is not evidence a source was "
    "never upscaled. See docs/SPEC-FEEDBACK.md finding #16."
)


def frame_metrics(gray: np.ndarray) -> dict:
    """All four SPEC.md §8 metrics for one luma plane. Pure numpy, no I/O.

    Returns a dict that always carries `usable`; when usable is False the
    metric values are None rather than misleading numbers."""
    if gray.ndim != 2:
        raise ValueError(f"expected a 2-D luma plane, got shape {gray.shape}")
    height, width = gray.shape
    a = gray.astype(np.float64)
    std = float(a.std())

    unusable = dict(usable=False, std=std, effective_resolution_ratio=None,
                    blocking=None, banding=None, hf_energy_ratio=None)
    if std < _FLAT_FRAME_STD or height < 2 * _BLOCK or width < 2 * _BLOCK:
        return unusable

    # --- spectral: effective resolution + high-frequency energy ---
    z = a - a.mean()
    window = np.outer(np.hanning(height), np.hanning(width))
    power = np.fft.fftshift(np.abs(np.fft.fft2(z * window)) ** 2)
    cy, cx = height // 2, width // 2
    y, x = np.ogrid[:height, :width]
    # Separable (square) radius, not Euclidean: scalers band-limit each axis
    # independently, so a stretched source's cutoff is a box, not a disc.
    radius = np.maximum(np.abs(y - cy) / (height / 2), np.abs(x - cx) / (width / 2))
    total = float(power.sum() - power[cy, cx])  # AC energy; DC carries no detail
    if total <= 0:
        return unusable

    # Bin the power by radius once, then a single reverse-cumsum answers
    # "how much energy lies above cutoff c" for every c — 13x faster than
    # re-masking the whole array per candidate cutoff (measured at 4K).
    idx = np.minimum((radius * _RADIAL_BINS).astype(np.int32), _RADIAL_BINS - 1)
    binned = np.bincount(idx.ravel(), weights=power.ravel(), minlength=_RADIAL_BINS)
    above = np.cumsum(binned[::-1])[::-1] / total

    ratio = 1.0
    for k in range(_MIN_SWEEP_BIN, _RADIAL_BINS):
        if above[k] < _RESIDUAL_FLOOR:
            ratio = k / _RADIAL_BINS
            break
    hf_energy_ratio = float(above[_RADIAL_BINS // 2])  # energy above half Nyquist

    # --- blocking: gradient across the codec's 8px grid vs everywhere else ---
    dh = np.abs(np.diff(a, axis=1))
    dv = np.abs(np.diff(a, axis=0))
    h_edge = dh[:, _BLOCK - 1::_BLOCK].mean()
    h_rest = np.delete(dh, np.s_[_BLOCK - 1::_BLOCK], axis=1).mean()
    v_edge = dv[_BLOCK - 1::_BLOCK, :].mean()
    v_rest = np.delete(dv, np.s_[_BLOCK - 1::_BLOCK], axis=0).mean()
    h_ratio = h_edge / h_rest if h_rest > 0 else 1.0
    v_ratio = v_edge / v_rest if v_rest > 0 else 1.0
    blocking = float((h_ratio + v_ratio) / 2)

    # --- banding: how many luma levels in the frame's range are occupied ---
    q = gray if gray.dtype == np.uint8 else np.clip(gray, 0, 255).astype(np.uint8)
    counts = np.bincount(q.ravel(), minlength=256)
    lo, hi = int(q.min()), int(q.max())
    span = hi - lo + 1
    occupied = int((counts[lo:hi + 1] > 0).sum())
    banding = float(span / occupied) if occupied else 1.0

    return dict(usable=True, std=std,
                effective_resolution_ratio=float(ratio),
                blocking=blocking, banding=banding,
                hf_energy_ratio=hf_energy_ratio)


def suggest_target(detail_px, container_height, multiplier=DEFAULT_DETAIL_MULTIPLIER):
    """(target_height, raw_px, note) — a defensible upscale target, or
    (None, None, None) when there is nothing measured to reason from.

    `raw_px` is multiplier x measured detail; `target_height` snaps to the
    largest standard tier **at or below** it. Snapping down rather than to the
    nearest is deliberate: past ~2x measured detail an upscaler is inventing
    rather than resolving, and the stated risk to avoid is over-application on
    low-resolution originals. The raw figure is reported alongside so an
    override upward is an informed one."""
    if not detail_px or detail_px <= 0 or not container_height or container_height <= 0:
        return None, None, None
    raw = detail_px * multiplier
    at_or_below = [h for h in STANDARD_HEIGHTS if h <= raw]
    target = at_or_below[-1] if at_or_below else STANDARD_HEIGHTS[0]

    if target <= container_height:
        note = (f"already {container_height}p, and its measured detail only supports ~{target}p — "
                f"an upscale would be cleanup, not added resolution")
    else:
        note = (f"{container_height}p container with ~{detail_px}p of real detail; "
                f"~{target}p is supportable (x{target / container_height:.1f} on the container)")
    return target, int(round(raw)), note


@dataclasses.dataclass
class CandidacyResult:
    source_path: str
    container_width: int
    container_height: int
    frames_requested: int
    frames_decoded: int
    frames_usable: int
    effective_resolution_ratio: Optional[float]
    effective_resolution_px: Optional[int]
    blocking: Optional[float]
    banding: Optional[float]
    hf_energy_ratio: Optional[float]
    suggested_target_px: Optional[int]
    raw_target_px: Optional[int]
    target_note: Optional[str]
    thresholds: dict
    per_frame: list
    verdict: str
    reasons: list
    exit_code: int
    message: str
    caveat: str

    @property
    def worth_upscaling(self) -> bool:
        return self.exit_code == 0


def _result(source_path, container_width, container_height, thresholds,
            exit_code, verdict, message, reasons=None, **counts) -> CandidacyResult:
    defaults = dict(
        frames_requested=0, frames_decoded=0, frames_usable=0,
        effective_resolution_ratio=None, effective_resolution_px=None,
        blocking=None, banding=None, hf_energy_ratio=None, per_frame=[],
        suggested_target_px=None, raw_target_px=None, target_note=None,
    )
    defaults.update(counts)
    return CandidacyResult(
        source_path=source_path, container_width=container_width,
        container_height=container_height, thresholds=thresholds,
        verdict=verdict, reasons=reasons or [], exit_code=exit_code,
        message=message, caveat=CAVEAT, **defaults,
    )


def default_thresholds(**overrides) -> dict:
    t = dict(
        min_resolution_ratio=DEFAULT_MIN_RESOLUTION_RATIO,
        blocking_worth=DEFAULT_BLOCKING_WORTH,
        banding_worth=DEFAULT_BANDING_WORTH,
        resolution_marginal=DEFAULT_RESOLUTION_MARGINAL,
        blocking_marginal=DEFAULT_BLOCKING_MARGINAL,
        banding_marginal=DEFAULT_BANDING_MARGINAL,
        detail_multiplier=DEFAULT_DETAIL_MULTIPLIER,
    )
    t.update({k: v for k, v in overrides.items() if v is not None})
    return t


def _evaluate(source_path, container_width, container_height,
              frames_requested, per_frame, thresholds) -> CandidacyResult:
    """The verdict over already-computed per-frame metrics — pure, no I/O, so
    it is testable against synthetic dicts with no video file anywhere."""
    decoded = [f for f in per_frame if f is not None]
    usable = [f for f in decoded if f.get("usable")]
    counts = dict(frames_requested=frames_requested,
                  frames_decoded=len(decoded),
                  frames_usable=len(usable),
                  per_frame=per_frame)

    if container_height <= 0 or container_width <= 0:
        return _result(source_path, container_width, container_height, thresholds, 1, "error",
                       f"usage error: source has no measurable video dimensions "
                       f"({container_width}x{container_height})", **counts)

    if not usable:
        # The denominator rule: this is "broken", never "no defects found".
        return _result(source_path, container_width, container_height, thresholds, 2, "broken",
                       f"broken: sampled nothing usable — {frames_requested} frames requested, "
                       f"{len(decoded)} decoded, {len(usable)} usable (a usable frame needs luma "
                       f"variation above std {_FLAT_FRAME_STD}; an all-black or single-colour "
                       f"source reaches here)", **counts)

    # Median, not mean — one scene cut, fade or atypical frame should not move the verdict.
    ratio = statistics.median(f["effective_resolution_ratio"] for f in usable)
    blocking = statistics.median(f["blocking"] for f in usable)
    banding = statistics.median(f["banding"] for f in usable)
    hf = statistics.median(f["hf_energy_ratio"] for f in usable)
    eff_px = int(round(ratio * container_height))

    target_px, raw_target_px, target_note = suggest_target(
        eff_px, container_height, thresholds.get("detail_multiplier", DEFAULT_DETAIL_MULTIPLIER))
    counts.update(effective_resolution_ratio=ratio, effective_resolution_px=eff_px,
                  blocking=blocking, banding=banding, hf_energy_ratio=hf,
                  suggested_target_px=target_px, raw_target_px=raw_target_px,
                  target_note=target_note)

    denom = (f"over {len(usable)} usable frames of {frames_requested} sampled")

    # Ordered ladder: severe bars first and return immediately, so a file can
    # only be marginal if it trips no severe bar. Any one severe signal is
    # enough — the three metrics are independent kinds of headroom, not a
    # score to average.
    reasons = []
    if ratio < thresholds["min_resolution_ratio"]:
        # Deliberately names both causes: heavy compression strips high
        # frequencies too, and reads the same way as a stretch. Observed at
        # crf42, which measured 77% of container without being stretched at all.
        reasons.append(f"detail consistent with ~{eff_px}p inside a {container_height}p container "
                       f"({ratio * 100:.0f}%) — a stretched source, or high frequencies stripped "
                       f"by heavy compression")
    if blocking > thresholds["blocking_worth"]:
        reasons.append(f"blocking {blocking:.2f} against ~1.1 median for real content — visible "
                       f"compression damage an upscale can clean up")
    # Banding gates only when given a bar; it is None by default because it
    # never once crossed a threshold across 113 real files. Still reported.
    if thresholds["banding_worth"] is not None and banding > thresholds["banding_worth"]:
        reasons.append(f"banding {banding:.2f} against ~1.16 median for real content — "
                       f"quantization contouring in smooth areas")
    if reasons:
        return _result(source_path, container_width, container_height, thresholds, 0, "worth",
                       f"worth upscaling ({denom}): " + "; ".join(reasons),
                       reasons=reasons, **counts)

    if ratio < thresholds["resolution_marginal"]:
        reasons.append(f"detail slightly under container ({eff_px}p of {container_height}p, "
                       f"{ratio * 100:.0f}%)")
    if blocking > thresholds["blocking_marginal"]:
        reasons.append(f"mild blocking {blocking:.2f}")
    if thresholds["banding_marginal"] is not None and banding > thresholds["banding_marginal"]:
        reasons.append(f"mild banding {banding:.2f}")
    if reasons:
        return _result(source_path, container_width, container_height, thresholds, 3, "marginal",
                       f"marginal ({denom}): " + "; ".join(reasons) +
                       " — some headroom, but modest; your call whether the hours are worth it",
                       reasons=reasons, **counts)

    reasons = [f"resolution is honest ({eff_px}p of {container_height}p, {ratio * 100:.0f}%)",
               f"blocking {blocking:.2f} and banding {banding:.2f} are both near clean"]
    return _result(source_path, container_width, container_height, thresholds, 4, "not worth",
                   f"not worth upscaling ({denom}): " + "; ".join(reasons) +
                   " — little headroom for an upscale to recover",
                   reasons=reasons, **counts)


def verify_candidacy(report_path: str, **threshold_overrides) -> CandidacyResult:
    """Re-run the verdict over a saved .candidacy.json with different
    thresholds, reusing its stored per-frame metrics — no video decoding, so
    asking "what if I move the bar?" costs nothing."""
    if not os.path.isfile(report_path):
        return _result(report_path, 0, 0, default_thresholds(**threshold_overrides), 1, "error",
                       f"usage error: no such file: {report_path}")
    try:
        with open(report_path, encoding="utf-8") as fh:
            data = json.load(fh)
    except (json.JSONDecodeError, OSError) as e:
        return _result(report_path, 0, 0, default_thresholds(**threshold_overrides), 1, "error",
                       f"usage error: could not read report ({type(e).__name__}: {e})")

    return _evaluate(
        data.get("source_path", report_path),
        int(data.get("container_width", 0) or 0),
        int(data.get("container_height", 0) or 0),
        int(data.get("frames_requested", 0) or 0),
        data.get("per_frame", []),
        default_thresholds(**threshold_overrides),
    )


def summary_line(result: CandidacyResult) -> str:
    """The flat key=value line every tool in this repo prints — every metric
    beside every denominator, on every code path (CLAUDE.md)."""
    return (
        f"frames_requested={result.frames_requested} frames_decoded={result.frames_decoded} "
        f"frames_usable={result.frames_usable} "
        f"effective_resolution_px={result.effective_resolution_px} "
        f"effective_resolution_ratio={result.effective_resolution_ratio} "
        f"container={result.container_width}x{result.container_height} "
        f"blocking={result.blocking} banding={result.banding} "
        f"hf_energy_ratio={result.hf_energy_ratio} "
        f"suggested_target_px={result.suggested_target_px} "
        f"raw_target_px={result.raw_target_px} verdict={result.verdict}"
    )


def add_threshold_args(parser: argparse.ArgumentParser) -> None:
    """Shared by this module's CLI and reel_candidacy.py's, so the two can
    never drift apart on defaults or help text."""
    parser.add_argument("--min-resolution-ratio", type=float, default=None,
                         help=f"below this fraction of the container height, the source carries "
                              f"materially less detail than it claims (default: "
                              f"{DEFAULT_MIN_RESOLUTION_RATIO}, the 25th percentile across 113 real "
                              f"files; synthetic sources read 1.00 and misled the original 0.80)")
    parser.add_argument("--resolution-marginal", type=float, default=None,
                         help=f"below this, detail is mildly short (default: "
                              f"{DEFAULT_RESOLUTION_MARGINAL}, the real-file 75th percentile)")
    parser.add_argument("--blocking-worth", type=float, default=None,
                         help=f"blocking above this counts as real damage (default: "
                              f"{DEFAULT_BLOCKING_WORTH}; real files span 0.98-1.72, median 1.13)")
    parser.add_argument("--blocking-marginal", type=float, default=None,
                         help=f"mild blocking bar (default: {DEFAULT_BLOCKING_MARGINAL})")
    parser.add_argument("--banding-worth", type=float, default=None,
                         help="banding above this counts as real damage (default: OFF — banding "
                              "spanned only 1.00-1.20 across 113 real files and never crossed any "
                              "bar, so it reports but does not gate; pass a number to re-enable)")
    parser.add_argument("--banding-marginal", type=float, default=None,
                         help="mild banding bar (default: OFF, as above)")
    parser.add_argument("--detail-multiplier", type=float, default=None,
                         help=f"how far past measured detail an upscale can be expected to resolve "
                              f"rather than invent (default: {DEFAULT_DETAIL_MULTIPLIER}). The "
                              f"suggested target is the largest standard tier at or below this "
                              f"multiple of measured detail — derived from detail, never from the "
                              f"container, so it can neither over-apply on a low-resolution original "
                              f"nor explode a low-quality 8K input")


def threshold_kwargs(args) -> dict:
    return dict(
        min_resolution_ratio=args.min_resolution_ratio,
        blocking_worth=args.blocking_worth,
        banding_worth=args.banding_worth,
        resolution_marginal=args.resolution_marginal,
        blocking_marginal=args.blocking_marginal,
        banding_marginal=args.banding_marginal,
        detail_multiplier=args.detail_multiplier,
    )


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="Re-verdict a saved .candidacy.json against different thresholds, "
                    "without re-decoding the video."
    )
    parser.add_argument("report_path", help="a .candidacy.json written by reel_candidacy.py")
    add_threshold_args(parser)
    args = parser.parse_args(argv)

    result = verify_candidacy(args.report_path, **threshold_kwargs(args))
    print(result.message)
    print(summary_line(result))
    print(f"CAVEAT: {result.caveat}")
    return result.exit_code


if __name__ == "__main__":
    sys.exit(main())
