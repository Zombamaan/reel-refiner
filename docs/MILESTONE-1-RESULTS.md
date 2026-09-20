# Milestone 1 — measured results

The numbers SPEC.md §12's milestone was supposed to produce. Written down here because they weren't
the first time (see `docs/SPEC-FEEDBACK.md`'s pointer to this file) — this is the durable record, not
console output from a session that's already over.

## Clip and backend

- **Clip:** [Shimpei Takahashi's TED talk](https://www.ted.com/talks/shimpei_takahashi_play_this_word_game_to_come_up_with_original_ideas)
  (Japanese source audio, TED's own official English and Japanese subtitle tracks as reference)
- **Backend:** `faster-whisper` (ctranslate2 4.8.2), `medium` model, `--task translate`
- **Command:** `python reel_subtitles.py samples/2208.wav --out out --device {cuda,cpu} --model medium --language ja`

## The §8 language check (`srt_verify.py`)

| Device | Wall time | Exit | Detected | Confidence | Cues | Scoreable chars |
|---|---|---|---|---|---|---|
| CUDA | 26.3s | 0 (pass) | en | 1.0000 | 94 | 3619 |
| CPU | 170.8s | 0 (pass) | en | 1.0000 | 95 | 3711 |

Both devices were actually exercised, not just wired up — build state is **built**, not
built-partial (CLAUDE.md's build-state rule). CUDA is ~6.5× faster than CPU on this clip.

The two devices produce slightly different output (94 vs 95 cues) — expected, since the CUDA path
runs `float16` and the CPU path `int8`. Neither is the canonical result; both pass the §8 check.

**Both runs write the same filename.** `reel_subtitles.py` names its output `<stem>.<lang>.srt` with
no device component, so running CUDA then CPU overwrites the first result with the second. Keeping
both requires renaming between runs — see "Reproducing these numbers" below. Recorded as a CLI gap
in `docs/SPEC-FEEDBACK.md` finding #8.

## Translation-quality evidence (`scripts/score_srt.py`) — does not gate the milestone

SPEC.md §12's pass condition is the table above (a verified-English `.srt`). These numbers are
evidence for backend choice and for reading the milestone's quality honestly, not a similarity floor.

chrF is scored **document-level** (all cue text concatenated per side, compared as one segment), not
cue-by-cue — whisper segments on VAD/attention boundaries, TED chunks for reading speed, so cue *n*
on one side isn't cue *n* on the other; pairing positionally would silently score misaligned text.

| Device | chrF (vs TED's official English) | Cue-timing overlap |
|---|---|---|
| CUDA | 51.11 | 97.1% |
| CPU | 50.40 | 98.9% |

## FLEURS baseline (`scripts/fleurs_baseline.py`) — for reading the number above against something

TED's English track is a condensed, edited human translation — a different kind of target from a
literal one, so 51.11 alone doesn't say whether that's good or mediocre for this backend.
[FLEURS](https://huggingface.co/datasets/google/fleurs) (`google/fleurs`, cc-by-4.0) gives short,
literally-translated parallel sentences as a second, cleaner target.

| N (distinct sentences) | Corpus chrF | Backend | Device | Wall time |
|---|---|---|---|---|
| 40 | **42.16** | faster-whisper `medium` | cuda | 96.8s |

Command: `python scripts/fleurs_baseline.py --n 40 --device cuda --model medium`

FLEURS' `ja_jp`/`en_us` configs are matched by their shared FLoRes sentence `id` (not positional —
row order differs between the two streams), and ids are deduplicated so the 40 scored sentences are
40 *distinct* ones, not some sentences counted twice because ~2 speakers recorded each one.

**Reading the two together — with care.** The FLEURS score (42.16) is *lower* than the TED score
(~50–51). That is worth recording, but the two figures are **not on a comparable scale**: different
reference style (literal vs condensed), different content domain, different utterance length, N=40
single-sentence reads against one 331s continuous talk, and one run each with no repeats. A gap of
this size between two such different targets is not evidence of anything on its own.

One untested hypothesis, recorded so a later run can check it rather than because it is established:
the TED talk gives the model continuous discourse context that isolated FLEURS sentences don't, and
that may matter more than how literal the reference is. **Nothing here confirms that.** Testing it
would need the same backend scored on both targets at matched utterance lengths.

What the numbers do support: on both a real talk and an unrelated context-free benchmark, this
backend produces serviceable gist-quality translation — SPEC.md §2's stated bar — rather than a
high-fidelity one. Their durable value is as a regression baseline for later backend or model
changes.

## Reproducing these numbers

All commands assume `.venv/` is set up per `requirements.txt` and `samples/2208.wav` /
`samples/2208.en.srt` exist (fetched per `docs/SPEC-FEEDBACK.md` finding #6). `out/` is git-ignored,
so no generated `.srt` is committed here.

Because both devices write to the same `out/2208.en.srt`, the CUDA result must be moved aside before
the CPU run:

```
python reel_subtitles.py samples/2208.wav --out out --device cuda --model medium --language ja
mv out/2208.en.srt out/2208.en.cuda.srt

python reel_subtitles.py samples/2208.wav --out out --device cpu --model medium --language ja
mv out/2208.en.srt out/2208.en.cpu.srt

python scripts/score_srt.py out/2208.en.cuda.srt samples/2208.en.srt
python scripts/score_srt.py out/2208.en.cpu.srt  samples/2208.en.srt
```
