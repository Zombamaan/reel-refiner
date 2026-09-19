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
  Nothing here does contextual re-translation or human-in-the-loop correction.
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
**Assume any tool bundling its own CUDA libraries and predating 2025 is broken on the owner's
GPU until proven otherwise.** Entry 53 (`01_`) records two instances of exactly this failure
already: Faster-Whisper-XXL r192.3.4 and SyncPlayer 2.0.0.2's LibTorch, both against the
owner's Blackwell/sm_120 card. Consequence for this spec: neither whisper candidate in §9 is
depended on until milestone 1 proves it runs, and both need a `--device cpu` fallback path so
a broken GPU build doesn't block the tool entirely — CPU is slower, but subtitle generation
here isn't latency-sensitive.

### Other
Topaz Video AI: perpetual licence, version 7.1.5 (the final non-subscription release).
`06_Spec_Readiness.md` item 8 reports this is already confirmed installed. No subscription.

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
| A — computable | Candidacy: is this source genuinely high-resolution, or an upscaled-once source sitting in a bigger container; how much blocking/banding; how much high-frequency detail survives | Scalar metrics (an effective-resolution estimate, a blocking/banding score, a high-frequency energy ratio) computed over a sampled set of frames, reported with the number of frames sampled |
| A — computable | Subtitle output is actually in the target language (English) | Language-detect the generated `.srt` text; report the detected language, a confidence score, and the number of subtitle cues examined |
| A — computable | Upscale encode size | Output size vs source, as a ratio, alongside the model/CRF settings used to produce it |
| B — human | Whether the upscale itself looks better | Owner's eyes. Not computable per `15_`: *"upscaling deliberately changes the image, so similarity metrics against the source measure change rather than improvement"* |

**Denominator rule** (`08_Process_Adoption.md` §3 — formally reaching this program via entry
81's side effect, which named this exact subtitle check). Both computable checks above must
fail distinctly on zero: a subtitle file with zero cues is "examined nothing," not "language
check passed"; a candidacy run that sampled zero frames is "broken," not "no defects found."
This is the one general-quality rule this program inherits — see §10.

## 9. Reference material

Per D18 (`01_` — reference implementation, not extraction): no Studio Loom code is reused
here; this program has no reuse target there. Reference material is external tooling.

| Source | What to read | For |
|---|---|---|
| `06_Spec_Readiness.md` §3, item 7 status | Purfview Faster-Whisper-XXL's usage (`-l ja -m medium --task translate`) | Subtitle candidate #1 — documented as blocked on the owner's GPU with `CUBLAS_STATUS_NOT_SUPPORTED` until a newer release or `--device cpu` |
| `15_Capture_P3_Processing.md`, Subtitles → The replacement | `whisper-cli -h` (whisper.cpp) | Subtitle candidate #2 — untested for `--task translate` support and for its own CUDA build's provenance; subject to the same until-proven-otherwise assumption, §4 |
| Topaz Video AI 7.1.5, the `tvai_up` FFmpeg filter | Piping `tvai_up` straight into an H.265/AV1 encode at a chosen CRF, one command | The upscale wrapper — `15_` names this the fix for the 5–10× size problem |
| `04_Claude_Boundaries.md` §1 | The instrumentation requirement for anything judged visually | Candidacy analyser's metric design |

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
Proving that whisper-cli (or a fixed Faster-Whisper-XXL) actually runs on the owner's GPU, or
confirming CPU fallback is fast enough to live with, is the milestone that de-risks the rest of
the program. It exercises the whole subtitle must-have and its language-verification check in
one shot on a real case.

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
