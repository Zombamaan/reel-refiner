"""scripts/fleurs_baseline.py — a numeric ja->en translation baseline from
FLEURS, to give the TED chrF score (docs/MILESTONE-1-RESULTS.md) something to
be read against.

Why this exists: the milestone chose a TED talk specifically so translation
quality could be measured by a number, not eyes (SPEC.md §8). But TED's
official English track is a condensed, edited human translation — a
legitimately harder target than a literal one, so its chrF score alone
doesn't say whether ~50 is "good" or "mediocre" for this backend. FLEURS
(google/fleurs, cc-by-4.0, ungated) gives short, literally-translated
parallel sentences instead: a cleaner target to calibrate against. Read the
two numbers together, not either alone.

FLEURS is per-language, not a translation dataset directly — the `ja_jp`
config's `transcription` field is Japanese, not English. Getting a matched
English reference means pulling *both* `ja_jp` and `en_us` test splits and
matching rows by their shared `id` (FLEURS is n-way-parallel from FLoRes:
the same id is the same source sentence in every language config). Row
order differs between the two configs' streams (confirmed by inspection),
so this is a real id-based join, not a positional zip.

Ids are not unique within a single config's test split either — most
sentences were recorded by ~2 different speakers, sharing one id with
identical transcription text (confirmed by inspection: 0 of 350 distinct
en_us ids have conflicting text across their duplicate rows). Left
unhandled, this would let the same underlying sentence be scored twice
under two speakers instead of sampling N distinct sentences, so the source
loop skips any id it has already scored.

One-off benchmark tooling, run to produce a number for the record — not
part of the reactive per-file CLI (reel_subtitles.py), consistent with
CLAUDE.md's "no batch mode" for the shipped tool. Audio is streamed from
Hugging Face straight into a temp dir, never into samples/ (FLEURS clips
aren't the owner's material).

Denominator discipline matches the rest of the repo: N (matched pairs
actually scored) is reported alongside the corpus chrF, and a run that
matches zero pairs exits non-zero with a distinct message rather than ever
printing a score for nothing.
"""
from __future__ import annotations

import argparse
import itertools
import os
import sys
import tempfile
import time
from pathlib import Path

from datasets import Audio, load_dataset
from sacrebleu.metrics import CHRF

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))  # repo root, for reel_subtitles
from reel_subtitles import transcribe as backend_transcribe  # noqa: E402

DATASET = "google/fleurs"
SOURCE_CONFIG = "ja_jp"
REFERENCE_CONFIG = "en_us"
SPLIT = "test"


def _build_reference_map(limit: int | None = None) -> dict[int, str]:
    """id -> English reference text, from the en_us test split. Audio
    decoding is disabled — only text and id are needed here, and enabling
    it would require the torchcodec dependency for no benefit."""
    en = load_dataset(DATASET, REFERENCE_CONFIG, split=SPLIT, streaming=True)
    en = en.cast_column("audio", Audio(decode=False))
    items = itertools.islice(en, limit) if limit else en
    return {item["id"]: item["transcription"] for item in items}


def _iter_source_items(limit: int | None = None):
    ja = load_dataset(DATASET, SOURCE_CONFIG, split=SPLIT, streaming=True)
    ja = ja.cast_column("audio", Audio(decode=False))
    return itertools.islice(ja, limit) if limit else ja


def run_baseline(n: int, device: str, model_size: str, workdir: Path) -> dict:
    print(f"loading {REFERENCE_CONFIG} test split (text only) to build the id->reference map ...")
    ref_map = _build_reference_map()
    print(f"  {len(ref_map)} reference sentences available")

    hypotheses: list[str] = []
    references: list[str] = []
    matched_ids: list[int] = []
    seen_ids: set[int] = set()

    t0 = time.time()
    for item in _iter_source_items():
        if len(hypotheses) >= n:
            break
        if item["id"] in seen_ids:
            continue  # already scored this sentence under a different speaker
        ref_text = ref_map.get(item["id"])
        if ref_text is None:
            continue  # FLEURS' per-language QC drops a handful of ids per config; skip, don't fake it
        seen_ids.add(item["id"])

        # FLEURS audio is already a real WAV container (confirmed by
        # inspection) at 16kHz mono — write the bytes straight through,
        # no re-encode needed, and let the shared backend do the rest.
        clip_path = workdir / f"fleurs_{SOURCE_CONFIG}_{item['id']}.wav"
        clip_path.write_bytes(item["audio"]["bytes"])

        segments, detected_lang, lang_prob, _elapsed = backend_transcribe(
            clip_path, device, model_size, source_language="ja",
        )
        hypothesis = " ".join(seg.text.strip() for seg in segments)
        hypotheses.append(hypothesis)
        references.append(ref_text)
        matched_ids.append(item["id"])

    elapsed = time.time() - t0
    n_matched = len(hypotheses)

    if n_matched == 0:
        return {
            "n": 0,
            "chrf": None,
            "elapsed": elapsed,
            "exit_code": 2,
            "message": "examined nothing: 0 ja_jp/en_us id pairs matched",
        }

    chrf = CHRF().corpus_score(hypotheses, [references]).score
    return {
        "n": n_matched,
        "chrf": chrf,
        "elapsed": elapsed,
        "exit_code": 0,
        "message": f"pass: {n_matched} matched pairs, corpus chrF = {chrf:.2f}",
        "ids": matched_ids,
    }


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="FLEURS ja->en corpus-chrF baseline, for reading the TED score against."
    )
    parser.add_argument("--n", type=int, default=40, help="number of matched pairs to score (default: 40)")
    parser.add_argument("--device", choices=["cuda", "cpu"], default="cuda")
    parser.add_argument("--model", default="medium", help="faster-whisper model size (default: medium, "
                                                            "matching the milestone run)")
    args = parser.parse_args(argv)

    with tempfile.TemporaryDirectory(prefix="fleurs_baseline_") as tmp:
        result = run_baseline(args.n, args.device, args.model, Path(tmp))

    print(result["message"])
    print(f"n={result['n']} device={args.device} model={args.model} wall_seconds={result['elapsed']:.1f}")
    if result.get("ids"):
        print(f"matched ids (distinct sentences): {result['ids']}")
    return result["exit_code"]


if __name__ == "__main__":
    sys.exit(main())
