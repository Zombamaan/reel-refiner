# Spec feedback — Reel Refiner

What `docs/SPEC.md` got wrong, left out, or stated ambiguously, discovered by building.

This file is the build's second deliverable. It goes back to the specification space, where the spec is
corrected and the lesson is recorded. An empty file after a completed milestone is itself a result
worth stating — say so explicitly rather than leaving it blank.

Format: one entry per finding, newest last.

**The actual measured numbers from milestone 1 (chrF, timing overlap, the FLEURS baseline) are in
`docs/MILESTONE-1-RESULTS.md`, not here** — this file is for defects found in the spec, that one is
the results record.

---

## Findings

### 1. The milestone assumes a candidate exists to prove. Neither is installed.

**Spec says:** §12: prove that "whisper-cli (or a fixed Faster-Whisper-XXL) actually runs on the
owner's GPU." §9 documents both candidates as reference material to read, not to acquire.
**What actually happened:** Neither `whisper-cli` nor Faster-Whisper-XXL exists anywhere on this
machine (checked PATH and seven common install roots). Standing the milestone up required: creating
a Python 3.12 venv (system default is 3.14, whose only available torch wheel is CPU-only), installing
`faster-whisper`/ctranslate2 from PyPI, downloading and extracting a whisper.cpp release + a GGML
model from GitHub/HuggingFace to even evaluate candidate #2, and separately installing torch cu130 +
openai-whisper to evaluate a third option. None of that is in the effort-class budget (§0: "Below
Thin," a two-day deliverable).
**Suggested correction:** Either state explicitly that milestone 1 includes an acquisition step, or
scope it down to "verify one already-installed candidate," and have the owner pre-install one before
the session starts.

### 2. §4's GPU rule has no converse — it can only ever justify suspicion, never clearance

**Spec says:** "Assume any tool bundling its own CUDA libraries and predating 2025 is broken on the
owner's GPU until proven otherwise."
**What actually happened:** A 2026 build (torch 2.14.0+cu130, ctranslate2 4.8.2 with the
pip-installed `nvidia-cublas-cu12`/`nvidia-cudnn-cu12` runtime) runs real sm_120 kernels on this
card correctly and with a genuine, reproducible CUDA speedup over CPU (faster-whisper: 26.3s vs
170.8s on the full 331s clip; 2.3–2.7s steady-state vs 4.3s on a 30s slice). But a same-vintage,
2026-built whisper.cpp CUDA binary (whisper.cpp b5130, `whisper-cublas-12.4.0`) reported
`CUDA : ARCHS = 500,610,700,750,800,860,890,900` — no sm_120 — and ran the identical task **10×
slower than its own CPU path** (42.3s vs 4.36s on a 30s slice) while claiming to use the CUDA
backend, with no crash and no error. The predates-2025 rule would have cleared this exact binary.
**Suggested correction:** Restate the risk factor as "which SM architectures the binary was
compiled against," not release date. Recommend checking a CUDA-enabled tool's own printed arch list
against `torch.cuda.get_device_capability()` before trusting a non-crashing "used the GPU" claim, and
add "10x+ slower than CPU while claiming to use CUDA" as a second failure signature alongside
`CUBLAS_STATUS_NOT_SUPPORTED` — this one doesn't crash, it silently degrades.

### 3. §12 names two candidates; the capture's own replacement command is a third

**Spec says:** §9's reference-material table lists exactly two subtitle candidates: Faster-Whisper-XXL
and whisper.cpp's `whisper-cli`.
**What actually happened:** `docs/CAPTURE.md`'s own "The replacement" section, which §9 draws from,
gives this exact command as the fix: `whisper "clip.mp4" --model medium --language Japanese --task
translate --output_format srt` — the `openai-whisper` CLI, which appears nowhere in §9's table. When
probed here (torch cu130, sm_120 present in `get_arch_list()`), it showed unreliable device behavior:
the model object reported `cuda:0` throughout, yet `transcribe()` intermittently raised its own
internal "Performing inference on CPU when CUDA is available" warning mid-run, and output length
varied wildly run to run on identical input (78–670 characters for the same 30s slice). Not depended
on for that reason, independent of it being off-spec.
**Suggested correction:** Either add `openai-whisper` to §9 as a third candidate, or note explicitly
that CAPTURE's worked example and SPEC's candidate list disagree.

### 4. ffmpeg 8.1.2 here *does* ship `--enable-whisper` — CAPTURE's doubt is resolved, not confirmed

**Spec says:** CAPTURE.md, "The replacement": "a stock FFmpeg likely can't run it at all."
**What actually happened:** The installed ffmpeg (8.1.2-full_build, gyan.dev) is built with
`--enable-whisper` and exposes the `whisper` filter (`ffmpeg -hide_banner -filters` lists it).
**Suggested correction:** Update to "confirmed present in the gyan.dev full builds as of 8.1.2;
still worth checking per-machine since it's a non-default build flag."

### 5. CAPTURE's `task`-option correction still holds at 8.1.2, gained one more option since

**Spec says:** CAPTURE.md: the `whisper` filter's full option set is `model`, `language`, `queue`,
`use_gpu`, `gpu_device`, `destination`, `format`, and four `vad_*` options — no `task`.
**What actually happened:** Confirmed unchanged at 8.1.2, except the filter has since gained
`max_len`. Still no `task` option — transcribe-only, cannot translate, so it was correctly excluded
as a milestone path.
**Suggested correction:** None needed; recording this as a confirmation with a version number, since
an unconfirmed claim from an earlier capture is exactly the kind of thing that silently rots.

### 6. The clip itself needed an acquisition tool that also wasn't ready

**Spec says:** §12: "one real clip the owner has in a non-English source language" — implies the
clip is already in hand.
**What actually happened:** The owner sourced a Japanese TED talk via `yt-dlp`, specifying
`>=2026.08.19`. That exact version — also the newest release on PyPI as of 2026-09-19 — fails on
both the primary and fallback TED URLs with `TypeError: the JSON object must be str, bytes or
bytearray, not NoneType` (TED changed its page format; tracked at
[yt-dlp#17507](https://github.com/yt-dlp/yt-dlp/issues/17507), fixed by PR #17510, which has not
reached any PyPI release). Recovered only by installing a `yt-dlp-master-builds` nightly
(2026.09.16.074918). Also: the instructed `-f audio` format id doesn't exist for this content (only
`hls-audio0-{high,low,medium}` do); the documented `-x --audio-format wav` fallback was needed and
worked.
**Suggested correction:** Not really a spec defect — this is upstream churn on a fast-moving
dependency — but worth a standing note: "verify yt-dlp actually works against a live TED URL before
trusting a version-number pin; PyPI can lag a fix that's already merged."

### 7. §8 has no home for translation accuracy, and §2 says this isn't a translation-quality tool

**Spec says:** §2, "What this is not": *"Not a translation-quality tool."* §8's Class A table has
three computable rows — candidacy metrics, subtitle output language, upscale encode size. None of
them is translation accuracy.
**What actually happened:** The milestone produced two scoring tools the spec never asked for and
has nowhere to put: `scripts/score_srt.py` (chrF + cue-timing overlap against a reference) and
`scripts/fleurs_baseline.py` (corpus chrF against a parallel benchmark). Both were needed —
without them "gist quality" (§2's own bar) is an assertion with no number behind it, and
`04_Claude_Boundaries.md` §1 requires numbers exactly where a judgement can't be made by eye. But
as the spec currently reads they are out of scope by §2 and unrecorded by §8 at the same time.
**Suggested correction:** Decide one way in the spec, not in the repo. Either add a fourth Class A
row to §8 — "translation is serviceable at the gist bar: document-level chrF against a reference
translation, reported with the number of segments scored" — or state in §13 that accuracy scoring
is out of scope and delete both scripts. §2's line is about not *improving* translation quality
(no contextual re-translation, no human-in-the-loop); measuring it is a different thing, and the
spec should say so rather than leaving the two readings to collide.

*Source: external spec review, not discovered by building. Recorded here because this file is the
channel back to the specification space, and the defect is in the spec rather than the code.*

### 8. §4 says outputs are written next to the input; they are written to `out/`

**Spec says:** §4, the trust rule: *"it writes an output next to an input the owner named on the
command line. No destructive path exists as long as an output name is always distinct from its
input."*
**What actually happened:** `CLAUDE.md` instructs the opposite — *"Never write outputs there
[`samples/`] — write to `out/`"* — and `reel_subtitles.py` implements `CLAUDE.md`, defaulting to
`--out out`. The no-overwrite guarantee §4 actually cares about holds either way (the output path
is asserted distinct from the input before anything is written), so nothing unsafe happened. But
the spec and the repo's working rules state different destinations for the same file.

A second, smaller consequence of the same area: the output name is `<stem>.<lang>.srt` with no
device component, so `--device cuda` and `--device cpu` runs of the same clip overwrite each other.
Harmless for a single production run, awkward for the comparison runs the milestone itself needed —
`docs/MILESTONE-1-RESULTS.md` documents the manual `mv` this forced.
**Suggested correction:** Update §4 to say outputs go to a caller-specified directory defaulting to
`out/`, never in place of the input. Optionally add a device component to the output name, or a
`--suffix` flag, so comparison runs don't collide — small, but it is the difference between the
results record being reproducible by copy-paste and needing a footnote.

*Source: external spec review, not discovered by building.*
