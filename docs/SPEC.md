# Program 5 — Reel Refiner

**Date:** 2026-09-16
**Path:** C — Collection (`01_Portfolio_Decisions.md` §3)
**Repo:** `reel-refiner` (repo slugs are exempt from the naming document, `40_Naming_Convention.md` §7 — picked independently at spec time)
**Language:** Python. Not constrained by the capture; chosen for subprocess glue around FFmpeg, whisper tooling and Topaz's `tvai_*` filters, and to keep the candidacy analyser's metric code in the same language as whatever tests it.
**Effort class:** Below Thin (matches `01_Portfolio_Decisions.md` §2 and `06_Spec_Readiness.md` §1 — the effort-class agreement the doc checker enforces)
**Source captures:** `15_Capture_P3_Processing.md` (all sections); `06_Spec_Readiness.md` §2 Program 5, §3 item 7 and item 8; `01_Portfolio_Decisions.md` entries 36, 43, 53, 81

## 1. What this is

Three small, independently runnable maintenance tools for staged video: a candidacy analyser
that says whether a source is worth upscaling before hours are spent, a Topaz wrapper that
upscales with encode settings that don't inflate output 5–10×, and a subtitle one-liner that
produces gist-quality English subtitles and verifies they actually came out in English.
Invoked manually and reactively. No queue, no scheduler, no shared state between the three.

## 2. What this is not

- **Not a job orchestrator or pipeline stage.** Entry 36 (`01_Portfolio_Decisions.md`) settled
  this: reactive, targeted, maintenance-only. No "process the library" mode in v1.
- **Not a library-wide quality survey.** The capture's own open question (`15_`, Open
  questions #3) is whether the candidacy analyser belongs here or in Program 4 (Reel Intake,
  the staging area between acquisition and the library) as a batch-wide check. Unresolved
  either way — see §11. v1 keeps it here, invoked per file, partly because Program 4 is
  blocked on D12 (does Stash already cover staging?) and a batch mode would be new scope on
  top of an unresolved question.
- **Not a demosaicing/decensoring tool.** Already out of scope for all of Project 3
  (`04_Claude_Boundaries.md` §2); stated here only because "video enhancement" invites the
  association. `04_` confirms the rest of Project 3, subtitles and upscaling, is unaffected.
  **Note the numbering collision:** "Project 3" here is the elicitation-era project number for
  video processing, which became this program. It is **not** Program 3 (Reel Projector, the
  playback shell). `04_` §2 uses the same older numbering.
- **Not a translation-quality tool.** The owner's own bar is gist quality (`15_`: *"loose
  translation... the gist of speech is fine"*), not FunscriptToolbox's manual-review path.
  Nothing here does contextual re-translation or human-in-the-loop correction. This is about not
  *improving* translation quality — it says nothing about *measuring* it for backend selection,
  which is a build-time concern, not a product feature. See §9's backend-selection tooling.
- **Not a provenance/reconciliation system.** Seam S5 (`09_Interface_Contracts.md`) — marking
  processed output as "my upscale" for Program 4's adjudication — is real but deferred to
  after Program 4 exists. See §5 and §13.
- **Not a Topaz model recommendation engine.** Which `tvai_*` model suits heavily compressed
  sources is open question 2 in `15_` and stays the owner's manual, run-time choice; the
  wrapper accepts a model name, it doesn't pick one.

## 3. Definition of done

Two commands the owner can run without re-learning anything (`15_`, Definition of done): one
produces gist-quality English subtitles, one upscales without the 5–10× storage blowup, plus a
way to know beforehand whether upscaling is worth doing at all.

### The metric

No single throughput number was elicited here, unlike Programs 4 and 7. "Return to use" for
this program means the three frictions in `15_` stop recurring: (a) subtitle generation takes
one command instead of the five-step manual workflow it replaces, (b) upscale output stays
close to source size at a chosen CRF instead of 5–10×, (c) the analyser gives a verdict before
hours are spent on an upscale that wasn't worth it.

## 4. Constraints

### From `04_Claude_Boundaries.md`
- **§1 applies to both the candidacy analyser and upscale result quality.** Claude cannot view
  the video, so a "worth it?" verdict and any upscale-quality judgment must expose numbers
  rather than rest on a visual read. That's why candidacy is Class A (computable) below, and
  result quality stays Class B (human).
- **§2's demosaicing carve-out doesn't touch this program**, confirmed in `04_` itself: *"The
  rest of Project 3 is unaffected — subtitles and upscaling are entirely fine."*

### From `01_Portfolio_Decisions.md` §5 — the trust rule
Not applicable in the propose→confirm sense: D21 (`01_` entry 81) limits that rule to Programs
4 and 7. This program doesn't place files into a managed library — it writes an output next
to an input the owner named on the command line. No destructive path exists as long as an
output name is always distinct from its input.

### GPU / CUDA — carried in for this session
**Corrected by milestone 1** (`docs/SPEC-FEEDBACK.md` finding #2): the risk factor is **which SM
architectures a CUDA binary was compiled against**, not its release date. A 2026-built whisper.cpp
CUDA binary still failed this way — compiled without sm_120 in its architecture list — while a
2026 `torch`/`ctranslate2` build with sm_120 present ran real kernels on this card correctly.
Release date can only ever justify suspicion; it can never justify clearance, so treat "recently
built" as no evidence either way.

Entry 53 (`01_`) records two instances of the *crashing* form of this failure already:
Faster-Whisper-XXL r192.3.4 and SyncPlayer 2.0.0.2's LibTorch, both against the owner's
Blackwell/sm_120 card, both with `CUBLAS_STATUS_NOT_SUPPORTED`. Milestone 1 found a second,
**non-crashing** failure signature that's just as disqualifying: a tool can claim to use CUDA, run
without error, and still be **10×+ slower than its own CPU path** because it silently falls back to
an unoptimized path for an unsupported architecture. Before trusting any CUDA-enabled tool's "used
the GPU" claim, check its own printed architecture list (or equivalent) against
`torch.cuda.get_device_capability()` for this card, and treat a CUDA run that isn't meaningfully
faster than CPU as a second kind of failure, not a slow success.

Consequence for this spec, unchanged: neither whisper candidate in §9 is depended on until
milestone 1 proves it runs, and both need a `--device cpu` fallback path so a broken GPU build
doesn't block the tool entirely — CPU is slower, but subtitle generation here isn't
latency-sensitive.

**A third failure signature, added by milestone 2** (`docs/SPEC-FEEDBACK.md` finding #15): a GPU
filter can crash the whole process on input it considers degenerate, with no error at all. Topaz's
`tvai_up` **segfaults** (exit 139, empty stderr) on fewer than **4 input frames** — bisected on this
machine: 1, 2 and 3 frames all segfault identically, 4 and above run cleanly. Practical rule: **never
probe or preflight-check a `tvai_*` filter with fewer than a handful of frames**, or an upstream
limitation will read as this repo's own crash. `reel_upscale.py`'s preflight smoke test uses 8 frames
to stay clear with margin. The three signatures to watch for are now: a hard `CUBLAS_STATUS_NOT_SUPPORTED`
crash, a silent 10×-slower-than-CPU degradation while claiming CUDA, and a segfault on degenerate input.

### Other
Topaz Video AI: perpetual licence, version 7.1.5 (the final non-subscription release).
`06_Spec_Readiness.md` item 8 reports this is already confirmed installed. No subscription.

**Topaz environment, added by milestone 2** (`docs/SPEC-FEEDBACK.md` finding #11) — none of this was
recorded anywhere before building, and the first two are hard requirements, not preferences:

- **`TVAI_MODEL_DIR` must be set** to `C:\ProgramData\Topaz Labs LLC\Topaz Video AI\models`, or
  `tvai_up` fails immediately with `Model not found`, before any GPU work. The correct value was
  recoverable only from Topaz's own log file (`%APPDATA%\Topaz Labs LLC\Topaz Video AI\logs\*.tzlog`,
  the line `TVAI_MODEL_DIR, veaiDataFolder …`). `TVAI_MODEL_DATA_DIR` is set to the same path
  alongside it — present in every working invocation, not independently confirmed as required.
- **Two Topaz installs can coexist** on one machine: the spec'd perpetual `Topaz Video AI` (7.1.5) and
  a separate subscription-era `Topaz Video` (1.2.1, a different product with a different binary). The
  7.1.5 binary must be pinned explicitly rather than resolved by name.
- `reel_upscale.py` and `reel_candidacy.py` set these themselves, overridable via `REEL_TVAI_FFMPEG`
  and `REEL_TVAI_MODEL_DIR`, so the owner never supplies them by hand.

## 5. Interfaces

Per `09_Interface_Contracts.md`.

| Direction | Seam | Carries | Status |
|---|---|---|---|
| 5 → 4 | S5 | Provenance claim ("this output is my upscale of that input") | **Deferred.** Program 4 (Reel Intake) is blocked on D12; invocation stays manual either way, and `09_` itself notes the trigger direction may never need a channel at all. Out of scope for v1 — see §13 |

No other program depends on Program 5's output format, and there is no inbound seam:
invocation is manual by design (`15_`: *"not anywhere officially in the pipeline"*).

## 6. Data model

None. Three stateless CLI tools operating on files the owner names — no database, no
persisted index, no shared state between runs. The candidacy analyser writes a report of
computed metrics next to the input file for the owner to read; that's a report, not a data
model this program owns.

**Report format and location, settled by milestone 3** (`docs/SPEC-FEEDBACK.md` finding #18 — this
section named neither):

- **Two files, not one.** `<stem>.candidacy.txt` is the human-readable one — what answers "did I
  already evaluate this?" months later without tooling. `<stem>.candidacy.json` carries every metric,
  all three denominators, the thresholds used and the **per-frame** values, which are too noisy for the
  report but are exactly what a later "did this change?" comparison needs. `candidacy_verify.py` can
  re-verdict that JSON against different thresholds without re-decoding the video.
- **"Next to the input file" carries finding #8's carve-out**, exactly as §4 does: a real clip's
  reports go beside it; a clip under this repo's own `samples/` writes to `out/<clip>/` instead;
  `--out` overrides both. Same three-branch rule as the other two tools.
- **Re-running overwrites the previous report, deliberately.** Unlike an upscale, a candidacy run
  costs seconds, so a newer answer supersedes an older one rather than competing with it.

## 7. Features

**Must** (from `15_`, Must-have vs nice-to-have)
- Subtitle generation at gist quality, one command, **with output-language verification**
- Upscale wrapper: owner-supplied model choice plus encode settings that don't inflate output 5–10×
- Candidacy analyser: computable verdict on whether a source is worth upscaling, before hours are spent

**Nice**
- Batch queue — the capture itself doubts this is ever needed, since the activity is targeted
- Provenance marking feeding Program 4 (Reel Intake) — deferred, §5 and §13

## 8. Quality measurement

| Class | What | How measured |
|---|---|---|
| A — computable | Candidacy: is this source genuinely high-resolution, or a **conventionally (interpolated) upscaled-once** source sitting in a bigger container; how much blocking/banding; how much high-frequency detail survives | Scalar metrics (an effective-resolution estimate, a blocking/banding score, a high-frequency energy ratio) computed over a sampled set of frames, reported with the number of frames sampled |
| A — computable | Subtitle output is actually in the target language (English) | Language-detect the generated `.srt` text; report the detected language, a confidence score, and the number of subtitle cues examined |
| A — computable | Upscale encode size | Output size vs source, as a ratio, alongside the model/CRF settings used to produce it |
| B — human | Whether the upscale itself looks better | Owner's eyes. Not computable per `15_`: *"upscaling deliberately changes the image, so similarity metrics against the source measure change rather than improvement"* |

**Denominator rule** (`08_Process_Adoption.md` §3 — formally reaching this program via entry
81's side effect, which named this exact subtitle check). Every computable check above must
fail distinctly on zero: a subtitle file with zero cues is "examined nothing," not "language
check passed"; a candidacy run that sampled zero frames is "broken," not "no defects found."
This is the one general-quality rule this program inherits — see §10.

**The denominator is tiered in practice, in both implemented cases.** A raw count is not a
trustworthy denominator, because a populated input can still carry nothing to measure. `srt_verify.py`
counts cues → non-empty → **scoreable** (a file of `[Music]` markers is populated but has no language
to detect) and gates on the last. `reel_candidacy.py` counts frames requested → decoded → **usable**
(an all-black frame decodes fine but has no measurable spectrum, and would poison every metric) and
likewise gates on the last. Both report all tiers on every run, pass or fail.

### Corrections to the candidacy row, from building it

**What the effective-resolution estimate can and cannot see** (`docs/SPEC-FEEDBACK.md` finding #16 —
the most consequential finding in this repo). It detects **conventional** upscales, where a resampler
stretched a smaller source and invented no detail, so the spectrum falls off a cliff at the original
Nyquist limit. Verified through the shipped tool: 720p→730p, 540p→574p, 360p→388p, 270p→308p inside
1080p containers. It does **not** detect AI upscales. Verified against this repo's own milestone-2
Topaz output, a known 2× upscale of 270p content: reported **96% genuine**. `tvai_up` synthesizes real
high-frequency detail, filling the exact gap the test looks for.

**Real-library testing made this worse, not better** (113 files, three collections — see
`docs/MILESTONE-3-RESULTS.md`). The 31 files whose names mark a prior upscale read p25=51% /
median=76%; the 82 unmarked ones read p25=71% / median=82%. Heavily overlapping — and at n=26 and n=50
the marked group read *higher* than the control, while at n=113 it reads *lower*. **The direction is
not stable across subsamples**, which is as clean a demonstration of "no signal, only overlap" as this
sample can give. The synthetic ladder above is genuine: given content band-limited at a known cutoff,
the estimate recovers it to within 3%. But real files vary in detail for many reasons other than
upscaling — compression above all — and those reasons swamp the one being looked for.

The consequence is not a footnote. **Detectability falls as the prior upscaler gets better**, so
`15_`'s claim that *"the already-upscaled-once case is common, and catching it is pure saved time"*
holds for the cheap half of that case and fails for the expensive half. **A clean effective-resolution
reading is not evidence a source was never upscaled**, and the tool prints that caveat on every run
and in every report rather than letting the number imply more than it supports. Detecting AI upscales
is research-grade and out of scope — see §13.

**What the metric does reliably measure** is how much detail a file carries relative to its container —
which is useful, and is not the same question. Library-wide, 72% of files hold under 90% of container
and 44% under 80%; of 40 4K-container files, 15 hold under 60%. That last group is the "served as 4K
but containing a lower resolution video" case, and finding it is genuine value the container alone
cannot give.

**The two damage metrics are not as independent as this table implies** (findings #19, #20). Blocking's
*baseline* moves with content — a clean natural source measured 1.00, a clean `testsrc2` measured 4.72,
because its synthetic edges align with the 8-px codec grid — so blocking is most trustworthy read
comparatively, and is the weakest of the three. And heavy compression strips high frequencies exactly
as a stretch does: a natural 1080p clip at crf42, never resized, measured 77% of container. The two
causes are indistinguishable from one frame's spectrum, so the tool names both rather than asserting a
stretch. The verdict is unaffected — both genuinely mean "detail is missing" — but the *reason* would
have been wrong.

**Thresholds exist, and did not before** (finding #17). This section names three metrics and no bar for
any of them, while §3, §4 and §7 all call for a *verdict*. The owner's decision to have the exit code
carry that verdict (0 worth / 3 marginal / 4 not worth, so a run chains into the upscale wrapper) made
hard boundaries mandatory — report text can hedge, an exit code cannot. Following entry #12's
precedent, they were put to the owner with their measured basis rather than chosen silently:

| Flag | default | Basis |
|---|---|---|
| `--min-resolution-ratio` | **0.70** | 25th percentile across 113 real files |
| `--resolution-marginal` | **0.90** | 75th percentile across the same |
| `--blocking-worth` | **1.5** | real range 0.98–1.72, p95 1.53 |
| `--blocking-marginal` | **1.25** | real median 1.13 |
| `--banding-worth` / `--banding-marginal` | **off** | see below |

**These were recalibrated after real-library testing** (`docs/SPEC-FEEDBACK.md` finding #21). The
original values — 0.80 / 0.95 / 2.0 / 3.0 / 1.5 / 1.5 — came from synthetic `testsrc2` and gradient
sources, where clean content reads 100% and damage reads 7–20. Real compressed video reaches neither:
across 113 files from three collections, blocking never crossed 2.0 and banding never crossed even its
1.5 marginal bar. The old bars declined only 8% of a real library, including a 255 Mbps ProRes master;
the new ones decline 22%.

**Banding no longer gates**, because across those 113 files it spanned 1.00–1.20 and crossed nothing.
It measures quantization, which dithered modern encodes do not exhibit. It is still computed, printed
and written per-frame to the `.json` — §8 asks for the metric, not for it to decide — and passing
`--banding-worth` a number re-enables it with no code change.

**The three metrics are not co-equal.** The effective-resolution estimate carries the verdict in
practice; blocking is a weak secondary signal; banding is diagnostic only. All bars remain flags.
Measured distributions: `docs/MILESTONE-3-RESULTS.md`.

**On the upscale-encode-size row**, one framing correction from `docs/MILESTONE-2-RESULTS.md`: §3's
metric (b) says output should stay *"close to source size,"* but an upscale has 4× the pixels at 2×
scale, so it will legitimately exceed source size. The comparison that actually tests the 5–10×
complaint is **against what Topaz's own no-quality-parameter preset produces for the identical
upscale** — measured at 12.08× source, against this wrapper's 5.45× at CRF 20 on the same clip, i.e.
2.2× smaller. Ratio-vs-source is still what the tool reports, because source size is the only figure
always available at run time; it just should not be read as the pass condition on its own.

**Translation accuracy is deliberately not a row here** (`docs/SPEC-FEEDBACK.md` finding #7,
resolved this way rather than by adding a fourth row). Every row above is something the tool
computes on *every* real invocation. Translation accuracy can't be — it needs a reference
translation to score against, which doesn't exist for an arbitrary real clip the owner points the
tool at. It's real, and it's necessary for choosing a backend, but it's build-time evaluation
tooling, not a per-run product guarantee — see §9.

## 9. Reference material

Per D18 (`01_` — reference implementation, not extraction): no Studio Loom code is reused
here; this program has no reuse target there. Reference material is external tooling.

**Subtitle candidates, corrected by milestone 1** (`docs/SPEC-FEEDBACK.md` findings #1, #3, #9): the
two candidates originally named below were reference material to *read*, not to acquire, and neither
was actually installed on the machine milestone 1 ran on — standing the milestone up required
installing and evaluating candidates from scratch, which is not free effort against the "Below Thin"
effort class stated at the top of this document. Of the three backends actually evaluated, the
milestone passed using a fourth, unnamed one:

| Source | What to read | For |
|---|---|---|
| `pip install faster-whisper` (SYSTRAN, ctranslate2-based) | `WhisperModel(..., device=..., compute_type=...)`, `task="translate"` | **Accepted candidate**, verified on this machine on both `--device cuda` (sm_120, needs `nvidia-cublas-cu12`/`nvidia-cudnn-cu12` on the DLL search path) and `--device cpu`. A different distribution of the same underlying library as Purfview's Faster-Whisper-XXL — that specific bundle was never installed here, and its `CUBLAS_STATUS_NOT_SUPPORTED` failure (entry 53, §4) was never re-tested against this one |
| `06_Spec_Readiness.md` §3, item 7 status | Purfview Faster-Whisper-XXL's usage (`-l ja -m medium --task translate`) | Originally named subtitle candidate #1. Superseded above — never installed or tested on this machine |
| `15_Capture_P3_Processing.md`, Subtitles → The replacement | `whisper-cli -h` (whisper.cpp) | Originally named subtitle candidate #2. `--translate` confirmed present; CPU path works, but the CUDA build tested (b5130, `whisper-cublas-12.4.0`) was compiled without sm_120 in its architecture list and ran 10× *slower* than its own CPU path while still claiming to use CUDA (§4's restated GPU rule) — not depended on for GPU use, viable CPU-only |
| `15_Capture_P3_Processing.md`, Subtitles → The replacement | `whisper "clip.mp4" --model medium --language Japanese --task translate --output_format srt` (`openai-whisper`) | The capture's own worked example, named nowhere in this table before milestone 1. Evaluated on a proven cu130/sm_120 torch stack: the model object reports being GPU-resident throughout, but `transcribe()` intermittently raises its own internal CPU-fallback warning mid-run, with output length varying run to run on identical input. Not depended on for that reliability reason |
| Topaz Video AI 7.1.5, the `tvai_up` FFmpeg filter | Piping `tvai_up` into an H.265/AV1 encode at a chosen CRF. **Not one ffmpeg process — see below** | The upscale wrapper — `15_` names this the fix for the 5–10× size problem |
| `04_Claude_Boundaries.md` §1 | The instrumentation requirement for anything judged visually | Candidacy analyser's metric design |

**The upscale row, corrected by milestone 2** (`docs/SPEC-FEEDBACK.md` findings #10, #12, #13). Three
things this table said, or failed to say, that building disproved:

- **"One command" cannot mean one ffmpeg process on this machine.** Topaz 7.1.5's bundled ffmpeg has
  **no software H.265/AV1 encoder** — its encoders are `hevc_nvenc`, `av1_nvenc`, `hevc_qsv`,
  `av1_qsv`, `hevc_amf`, `av1_amf`, none of which accepts a true `-crf`. The only CRF-capable encoder
  in that binary is `libvpx-vp9`, which is neither H.265 nor AV1 (`ffmpeg -h encoder=libx265` against
  Topaz's binary reports *"Codec 'libx265' is not recognized"*). `reel_upscale.py` therefore runs
  `tvai_up` in Topaz's ffmpeg **piped into a second, system ffmpeg process** that does carry
  `libx265`/`libsvtav1`. The owner still runs one command; two processes run beneath it. Read "one
  command" as the owner's invocation, not the process count. Confirms `15_`'s own framing that the size
  problem is *"knowledge, not capability"* — Topaz's default preset carries no quality parameter at all.
- **A default CRF is now specified: 20.** This document never named one. Chosen deliberately
  conservative — an upscale spends hours synthesizing high-frequency detail, and a higher CRF discards
  exactly what was just bought. `--crf` overrides per run. Encoder presets are per-encoder defaults
  (`medium` for libx265, `6` for libsvtav1, `p5` for hevc_nvenc), because their value spaces don't
  match: `--preset medium` is a hard error on libsvtav1, which takes an integer.
- **Audio and metadata passthrough had to be designed, not found here.** A raw video pipe carries no
  audio at all, so a naive `tvai_up`-into-encoder pipe would silently emit a video-only file. The
  original is supplied to the encoder as a **second input**, its audio mapped through untouched
  (`-map 1:a? -c:a copy`) and its container metadata copied by default (`-map_metadata 1`).
  `-fps_mode passthrough` is set explicitly, and the pipe uses `nut` rather than `yuv4mpegpipe`
  precisely because it carries real per-frame timestamps, so a variable-frame-rate source can't drift
  against the copied audio. Verified: output audio codec and duration match source exactly.

**Backend-selection tooling** (`docs/SPEC-FEEDBACK.md` finding #7): the table above compares
candidates by whether they run at all. Choosing between candidates that *do* run needed a number,
not an assertion — `scripts/score_srt.py` (chrF and cue-timing overlap against a reference
translation) and `scripts/fleurs_baseline.py` (the same, against a public benchmark) exist for
that. Deliberately **not** a §8 Class A row: they require a reference translation the tool itself
never has for a real clip, so they can't run on every invocation the way §8's rows do. Build-time
evaluation tooling, not a shipped feature — but not disposable either, per §2: their durable value
is as a regression baseline for the next backend or model change.

## 10. Process tier

`08_Process_Adoption.md` §8 is explicit: **no process tier for this program.** Tier 0, Tier 1
and Tier 2 ceremony would cost more than a two-day deliverable, which would itself violate the
portfolio's governing principle (`01_` §1 — organisation at the cost of throughput is a net
loss).

**One exception, not an addition of ceremony:** the denominator rule reaches this program
anyway, per entry 81's side effect. It's the mechanism behind the subtitle-language
requirement carried into this session, not process overhead layered on top of it. See §8.

## 11. Open decisions

None block this spec. `06_Spec_Readiness.md` marks Program 5 **READY, gated on nothing.** Two
items stay genuinely open without gating v1:
- Whether the candidacy analyser eventually moves into Program 4 (Reel Intake) as a
  library-wide survey (`15_`, Open questions #3) — revisit only if Program 4 unblocks on D12
  and batch behaviour turns out to be wanted.
- Which `tvai_*` model suits heavily compressed sources (`15_`, Open questions #2) — a
  knowledge item, the owner's manual choice at run time, not a spec gate.

## 12. First milestone

Run the subtitle one-liner end to end on one real clip the owner has in a non-English source
language, through to a verified-English `.srt`. Deliberately not the upscale wrapper, even
though `06_` calls the candidacy analyser "the only genuinely new piece" — the subtitle path
is where §4's GPU assumption is untested and where pre-work item 7 is currently blocked.
Proving that a whisper-family backend actually runs on the owner's GPU, or confirming CPU
fallback is fast enough to live with, is the milestone that de-risks the rest of the program. It
exercises the whole subtitle must-have and its language-verification check in one shot on a real
case.

**Completed** (`docs/MILESTONE-1-RESULTS.md`; corrections in `docs/SPEC-FEEDBACK.md` findings #1,
#3, #9): passed on both devices against a real clip. Proving it required installing and evaluating
candidates from scratch — none was pre-installed — and the candidate that passed is not the one
this section originally named; see §9's corrected table.

### Subsequent milestones

All three §7 must-haves now exist. Build states per `CLAUDE.md`'s rule, never reported as more than
they are:

| Milestone | Tool | State | Record | Findings |
|---|---|---|---|---|
| 1 | Subtitles (`reel_subtitles.py`, `srt_verify.py`) | **built** | `docs/MILESTONE-1-RESULTS.md` | #1–#9 |
| 2 | Upscale wrapper (`reel_upscale.py`, `upscale_verify.py`) | **built-partial** | `docs/MILESTONE-2-RESULTS.md` | #10–#15 |
| 3 | Candidacy analyser (`reel_candidacy.py`, `candidacy_verify.py`) | **built** | `docs/MILESTONE-3-RESULTS.md` | #16–#21 |

**Milestone 3 reached `built` by real-library testing**: 113 files across three collections, zero
failures and zero unusable frames, which also recalibrated §8's thresholds (finding #21). The
prediction this section previously carried — that grain would be the thing most likely to move a
number, and that `--blocking-worth 2.0` was the default to re-check — was half right. Blocking was
indeed the default that needed re-checking, and it did not hold: across 113 real files it never
reached even 1.72, and the bar came down to 1.5. Container handling was the happier surprise, with
`wmv3`, `mpeg2video`, ProRes 10-bit, VFR 4K120 and mkv-without-`nb_frames` all running unchanged.
**Interlaced content remains untested** — the survey found none across 12,237 files, so the one
dimension real footage was meant to cover, it didn't.

Milestone 2 remains **built-partial** for the original reason: no real clip has been through the
upscale wrapper. This repo's `samples/` holds no video (finding #14), so it was verified against
synthetically generated clips.

## 13. Out of scope for v1

- **Batch queue** — later, if ever; the capture doubts it's needed at all (§7).
- **Provenance marking to Program 4** (S5, §5) — later, once Program 4 unblocks on D12 and
  actually has somewhere to receive it; building the channel now means designing against a
  program that doesn't exist yet.
- **Candidacy-as-library-survey** — never decided either way (§11); v1 keeps it a per-file,
  owner-invoked check.
- **Topaz model selection logic** — never, by design; the owner's manual call permanently
  (§4, §9).
- **Demosaicing** — never, portfolio-wide (`04_` §2).
- **AI-upscale detection** — added by milestone 3 (`docs/SPEC-FEEDBACK.md` finding #16). The candidacy
  analyser's effective-resolution metric catches conventionally stretched sources and structurally
  cannot catch AI-upscaled ones, which synthesize genuine high-frequency detail. Signatures that might
  distinguish them (unnaturally uniform edge sharpness, absent sensor noise, over-regular texture) are
  research-grade, confounded by the heavy compression these sources already carry, and far outside the
  "Below Thin" effort class at the top of this document. Recorded as a stated limitation the tool
  prints on every run, not as an implied capability to build later.
- **Upscale *result* quality scoring** — unchanged from §8's Class B row, restated here because the
  candidacy analyser invites the confusion: it judges a source *before* an upscale, never the output
  after one. `15_`: *"upscaling deliberately changes the image, so similarity metrics against the
  source measure change rather than improvement."* Owner's eyes, permanently.
