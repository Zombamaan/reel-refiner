"""srt_verify.py — the SPEC.md §8 / CLAUDE.md denominator-rule check.

A ``.srt`` with zero cues is "examined nothing," never "language check
passed." This module (importable, and runnable standalone) enforces that: it
reports cue counts, detected language and confidence on *every* run, pass or
fail, and uses a distinct, non-zero exit code per failure kind so none of them
can be reported in the words of a pass.

Cue count alone is not a trustworthy denominator — a file of "[Music]" / "♪" /
"..." cues is populated but has nothing to check. Cues whose text is only
that kind of marker are excluded from the "scoreable" counts, which is what
actually gates pass/fail.

Two independent language signals are used, because one detector's confidence
is not evidence on its own: py3langid's normalized class probability, and a
dependency-free CJK-vs-Latin character ratio, which is decisive for the
English/Japanese question this repo cares about and can't fail the way a
statistical model can.

Exit codes:
  0  pass — target language detected, confidence >= threshold, denominators > 0
  1  usage / IO error (bad path, unreadable file, unparseable content)
  2  zero denominator — "examined nothing", never "passed"
  3  wrong language detected
  4  target language detected but below the confidence threshold
"""
from __future__ import annotations

import argparse
import dataclasses
import os
import re
import sys
from typing import Optional

import srt as srt_lib
from py3langid.langid import LanguageIdentifier, MODEL_DIR, MODEL_FILE

DEFAULT_THRESHOLD = 0.90

# CJK range covers the Japanese/Chinese blocks in common use; used as a
# second, model-free language signal alongside py3langid's statistical one.
_CJK_RE = re.compile(r"[぀-ヿ㐀-䶿一-鿿豈-﫿]")
_LATIN_RE = re.compile(r"[A-Za-z]")

# Stripped one kind at a time so each rule stays legible and independently
# testable, rather than one dense regex that's hard to trust by inspection.
_BRACKETED_RE = re.compile(r"[\[(][^\])]*[\])]")  # [Music], (laughs)
_MUSIC_NOTE_RE = re.compile(r"[♪♫♩♬]")  # ♪ ♫ ♩ ♬
_PUNCT_ONLY_RE = re.compile(r"[\s.…\-–—'\"]+")  # ... – — ' " and whitespace

_identifier: Optional[LanguageIdentifier] = None


def _get_identifier() -> LanguageIdentifier:
    global _identifier
    if _identifier is None:
        model_path = os.path.join(MODEL_DIR, MODEL_FILE)
        _identifier = LanguageIdentifier.from_modelpath(model_path, norm_probs=True)
    return _identifier


def _is_marker_only(text: str) -> bool:
    """True if a cue's text carries no spoken content — only music notes,
    bracketed/parenthetical annotations, or punctuation/whitespace."""
    stripped = text.strip()
    if not stripped:
        return True
    stripped = _BRACKETED_RE.sub("", stripped)
    stripped = _MUSIC_NOTE_RE.sub("", stripped)
    stripped = _PUNCT_ONLY_RE.sub("", stripped)
    return stripped == ""


@dataclasses.dataclass
class VerificationResult:
    path: str
    target_lang: str
    threshold: float
    cue_count: int
    nonempty_cue_count: int
    scoreable_cue_count: int
    scoreable_chars: int
    detected_lang: Optional[str]
    confidence: Optional[float]
    cjk_ratio: Optional[float]
    latin_ratio: Optional[float]
    exit_code: int
    message: str

    @property
    def passed(self) -> bool:
        return self.exit_code == 0


def _result(path, target_lang, threshold, exit_code, message, **counts) -> VerificationResult:
    defaults = dict(
        cue_count=0, nonempty_cue_count=0, scoreable_cue_count=0, scoreable_chars=0,
        detected_lang=None, confidence=None, cjk_ratio=None, latin_ratio=None,
    )
    defaults.update(counts)
    return VerificationResult(
        path=path, target_lang=target_lang, threshold=threshold,
        exit_code=exit_code, message=message, **defaults,
    )


def verify_srt(path: str, target_lang: str = "en", threshold: float = DEFAULT_THRESHOLD) -> VerificationResult:
    if not os.path.isfile(path):
        return _result(path, target_lang, threshold, 1, f"usage error: no such file: {path}")

    with open(path, encoding="utf-8-sig", errors="replace") as f:
        content = f.read()

    try:
        # ignore_errors=True: garbled or non-SRT content should read as
        # "zero cues found" (exit 2, examined nothing), not as a usage
        # error — the file was readable, it just isn't a populated .srt.
        cues = list(srt_lib.parse(content, ignore_errors=True))
    except Exception as e:  # noqa: BLE001 — a genuinely unrecoverable parse is a usage error
        return _result(
            path, target_lang, threshold, 1,
            f"usage error: could not parse SRT ({type(e).__name__}: {e})",
        )

    cue_count = len(cues)
    nonempty_cues = [c for c in cues if c.content.strip()]
    scoreable_cues = [c for c in nonempty_cues if not _is_marker_only(c.content)]
    scoreable_text = "\n".join(c.content for c in scoreable_cues)
    scoreable_chars = len(scoreable_text.replace("\n", "").replace(" ", ""))

    counts = dict(
        cue_count=cue_count,
        nonempty_cue_count=len(nonempty_cues),
        scoreable_cue_count=len(scoreable_cues),
        scoreable_chars=scoreable_chars,
    )

    if cue_count == 0 or not scoreable_cues or scoreable_chars == 0:
        return _result(
            path, target_lang, threshold, 2,
            f"examined nothing: {cue_count} cues, {len(nonempty_cues)} non-empty, "
            f"{len(scoreable_cues)} scoreable, {scoreable_chars} scoreable characters",
            **counts,
        )

    identifier = _get_identifier()
    detected_lang, confidence = identifier.classify(scoreable_text)

    cjk_chars = len(_CJK_RE.findall(scoreable_text))
    latin_chars = len(_LATIN_RE.findall(scoreable_text))
    total_scripted = cjk_chars + latin_chars
    cjk_ratio = cjk_chars / total_scripted if total_scripted else 0.0
    latin_ratio = latin_chars / total_scripted if total_scripted else 0.0
    counts.update(detected_lang=detected_lang, confidence=confidence,
                  cjk_ratio=cjk_ratio, latin_ratio=latin_ratio)

    if detected_lang != target_lang:
        return _result(
            path, target_lang, threshold, 3,
            f"wrong language: detected '{detected_lang}' (confidence {confidence:.4f}), "
            f"target was '{target_lang}', over {cue_count} cues / {scoreable_chars} chars",
            **counts,
        )

    if confidence < threshold:
        return _result(
            path, target_lang, threshold, 4,
            f"below confidence threshold: detected '{detected_lang}' at {confidence:.4f}, "
            f"threshold is {threshold}, over {cue_count} cues / {scoreable_chars} chars",
            **counts,
        )

    return _result(
        path, target_lang, threshold, 0,
        f"pass: detected '{detected_lang}' at confidence {confidence:.4f}, "
        f"{cue_count} cues examined ({len(scoreable_cues)} scoreable, "
        f"{scoreable_chars} scoreable characters)",
        **counts,
    )


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="Verify a .srt's language per SPEC.md §8's denominator rule."
    )
    parser.add_argument("srt_path")
    parser.add_argument("--lang", default="en", help="target language code (default: en)")
    parser.add_argument("--threshold", type=float, default=DEFAULT_THRESHOLD,
                         help=f"minimum confidence to pass (default: {DEFAULT_THRESHOLD})")
    args = parser.parse_args(argv)

    result = verify_srt(args.srt_path, args.lang, args.threshold)
    print(result.message)
    print(
        f"cues={result.cue_count} nonempty={result.nonempty_cue_count} "
        f"scoreable_cues={result.scoreable_cue_count} scoreable_chars={result.scoreable_chars} "
        f"detected={result.detected_lang} confidence={result.confidence} "
        f"cjk_ratio={result.cjk_ratio} latin_ratio={result.latin_ratio}"
    )
    return result.exit_code


if __name__ == "__main__":
    sys.exit(main())
