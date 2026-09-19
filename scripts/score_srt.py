"""score_srt.py — backend-selection evidence and a SPEC-FEEDBACK datapoint.

Does NOT gate the milestone: SPEC.md §12's pass condition is a
verified-English .srt (srt_verify.py's job), not a similarity floor. This
script answers a different question — how close to the reference translation
did it get — for choosing between backends and for reporting honestly.

Two independent numbers, because wording and timing fail independently and a
single score would hide which one is off:

  chrF   — sacrebleu's chrF, scored DOCUMENT-LEVEL: all cue text on each side
           concatenated into one string and compared as a single segment.
           Cue-by-cue pairing is deliberately NOT done — whisper segments on
           VAD/attention boundaries, TED chunks for reading speed, so cue n
           on one side is not the same sentence as cue n on the other. Pairing
           positionally would silently score misaligned text and report a
           meaningless-low number that looks like a real result.

  timing — the share of the reference's total cue duration that is covered by
           some hypothesis cue's [start, end) interval. This is where
           segmentation belongs, measured on purpose rather than leaking into
           the wording score above.
"""
from __future__ import annotations

import argparse
import sys

import srt as srt_lib
from sacrebleu.metrics import CHRF


def load_cues(path: str):
    with open(path, encoding="utf-8-sig", errors="replace") as f:
        return list(srt_lib.parse(f.read(), ignore_errors=True))


def document_text(cues) -> str:
    return " ".join(c.content.strip().replace("\n", " ") for c in cues if c.content.strip())


def chrf_score(hyp_cues, ref_cues) -> float:
    hyp_text = document_text(hyp_cues)
    ref_text = document_text(ref_cues)
    if not hyp_text or not ref_text:
        return 0.0
    return CHRF().sentence_score(hyp_text, [ref_text]).score


def timing_overlap(hyp_cues, ref_cues) -> float:
    """Share of reference cue-seconds covered by some hypothesis cue."""
    ref_intervals = sorted((c.start.total_seconds(), c.end.total_seconds()) for c in ref_cues)
    hyp_intervals = sorted((c.start.total_seconds(), c.end.total_seconds()) for c in hyp_cues)
    if not ref_intervals or not hyp_intervals:
        return 0.0

    total_ref_seconds = sum(end - start for start, end in ref_intervals)
    if total_ref_seconds <= 0:
        return 0.0

    covered = 0.0
    hi = 0
    for r_start, r_end in ref_intervals:
        while hi < len(hyp_intervals) and hyp_intervals[hi][1] <= r_start:
            hi += 1
        j = hi
        while j < len(hyp_intervals) and hyp_intervals[j][0] < r_end:
            h_start, h_end = hyp_intervals[j]
            covered += max(0.0, min(r_end, h_end) - max(r_start, h_start))
            j += 1
    return covered / total_ref_seconds


def score(hyp_path: str, ref_path: str) -> dict:
    hyp_cues = load_cues(hyp_path)
    ref_cues = load_cues(ref_path)
    return {
        "hyp_cues": len(hyp_cues),
        "ref_cues": len(ref_cues),
        "chrf": chrf_score(hyp_cues, ref_cues),
        "timing_overlap": timing_overlap(hyp_cues, ref_cues),
    }


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="Score a generated .srt against a reference translation "
                     "(evidence for backend choice — does not gate the milestone)."
    )
    parser.add_argument("hypothesis", help="generated .srt")
    parser.add_argument("reference", help="reference (e.g. official) .srt, same language")
    args = parser.parse_args(argv)

    result = score(args.hypothesis, args.reference)
    print(f"hyp_cues={result['hyp_cues']} ref_cues={result['ref_cues']}")
    print(f"chrF (document-level) = {result['chrf']:.2f}")
    print(f"cue-timing overlap    = {result['timing_overlap']:.3f} "
          f"({result['timing_overlap'] * 100:.1f}% of reference cue-seconds covered)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
