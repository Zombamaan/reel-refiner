# CLAUDE.md — Reel Refiner

Working rules for Claude Code sessions in this repository. Edit freely; this is the owner's file, not
a generated one.

## What this repo is

Three small, independently runnable maintenance tools for staged video, in Python:

1. **Subtitles** — one command from a non-English clip to gist-quality English `.srt`, with a check
   that the output really is English.
2. **Upscale** — a wrapper around Topaz Video AI 7.1.5's `tvai_up` FFmpeg filter, piped straight into
   an H.265/AV1 encode at a chosen CRF so output doesn't inflate 5–10× over source.
3. **Candidacy** — a computed verdict on whether a source is worth upscaling at all, before hours are
   spent on one that wasn't.

Invoked manually, one file at a time. **No queue, no scheduler, no shared state between the three.**

## The contract

**`docs/SPEC.md` governs.** It is the full specification, written before this repo existed.

Read it completely before writing code, and do not silently diverge from it. Where it is wrong,
incomplete, ambiguous, or contradicted by what actually happens on this machine, **write that down in
`docs/SPEC-FEEDBACK.md` and tell me**. On a first build, that list is worth as much as the code — it is
how the specification process gets corrected. Do not quietly work around a bad spec.

`docs/CAPTURE.md` is the elicitation record the spec was written from. Read it when the spec cites it
or when you need to know why something is the way it is.

## Build one thing at a time

**The first milestone is the subtitle path only**: one real non-English clip end to end, through to a
verified-English `.srt`.

Not the upscale wrapper. Not the candidacy analyser. The subtitle path goes first because that is where
the GPU risk below is untested, and proving it either way de-risks everything else.

**Stop when it passes and report.** Do not continue into the second tool.

**Status, subtitles: done.** Milestone 1 passed on both `--device cuda` and `--device cpu` against a
real clip — see `docs/MILESTONE-1-RESULTS.md` for the numbers and `docs/SPEC-FEEDBACK.md` for what
building it found wrong with the spec.

**Status, upscale wrapper: built-partial.** `reel_upscale.py` pipes Topaz's `tvai_up` into a
system-ffmpeg CRF encode (Topaz's own bundled ffmpeg has no software H.265/AV1 encoder — see
`docs/SPEC-FEEDBACK.md` finding #10), with the §8 encode-size check (`upscale_verify.py`) and its own
denominator rule (truncation + size-ratio gates, both exercised). Verified end to end on both
`--device cuda`/`auto` and `--device cpu` — see `docs/MILESTONE-2-RESULTS.md`. Partial because no real
clip has gone through yet: no video clip exists in this repo's `samples/`, so verification used a
synthetically generated degraded clip instead. Findings #10–#15 in `docs/SPEC-FEEDBACK.md` are what
building it found wrong with or missing from the spec.

**Status, candidacy analyser: built-partial.** `reel_candidacy.py` samples frames across a source and
computes §8's three metrics (`candidacy_verify.py`) — an effective-resolution estimate, blocking and
banding scores, and a high-frequency energy ratio — then maps them to a verdict carried in the exit
code (0 worth / 3 marginal / 4 not worth), so a run chains into `reel_upscale.py`. The denominator rule
is tiered `requested → decoded → usable` and gates on *usable*, so an all-black source reads "broken"
rather than clean. Reports are written as `.txt` and `.json` beside the input (or `out/<clip>/` for a
`samples/` clip). See `docs/MILESTONE-3-RESULTS.md`. Partial for the same reason as the upscale
wrapper: no real-world footage has gone through, only synthetic clips and milestone 2's own output.

**Its most important result is a limit, not a feature** (`docs/SPEC-FEEDBACK.md` finding #16): the
effective-resolution metric catches *stretched* upscales but not AI ones — verified against this repo's
own Topaz output, which read as 96% genuine. Detectability falls as the prior upscaler gets better, so
the expensive half of the "already upscaled once" case escapes. Every run prints that caveat; don't let
a clean reading be reported as evidence a source was never upscaled.

**All three §7 tools now exist.** Findings #16–#20 in `docs/SPEC-FEEDBACK.md` are what building the
candidacy analyser found wrong with or missing from the spec.

Dev/test clips live in `samples/<clip>/`, never committed — `source.<ext>` is what gets fed to the
tool, `reference.<lang>.<ext>` is ground-truth material for scoring only, never fed to the tool
itself. **Never write outputs there** — this is the one exception to the File Safety rule below,
scoped specifically to this repo's own test clips. Output for a `samples/` clip goes to `out/<clip>/`
instead (also not committed), device-suffixed (`en.cuda.srt`, `en.cpu.srt`) so testing multiple
devices against the same clip doesn't overwrite one result with the other. Running a tool against a
`samples/` clip that has a matching `reference.<lang>.*` file also (re)generates
`samples/<clip>/compare_in_beyond_compare.bat`, a one-click launcher for eyeballing the output
against ground truth (`dev_compare.py`; `REEL_BCOMPARE` env var to override the exe path).

A **real clip** (anywhere outside `samples/`) is not covered by that exception — see File Safety.

## The GPU assumption — the main risk in this repo

**Assume any tool that bundles its own CUDA libraries and predates 2025 is broken on this machine until
proven otherwise.** The card is Blackwell / sm_120, and two separate applications have already failed
on exactly this, one of them with `CUBLAS_STATUS_NOT_SUPPORTED`.

Consequences, both required:

- Neither whisper candidate is depended on until it has actually been observed to run here.
- Both need a working **`--device cpu` fallback**, so a broken CUDA build cannot block the tool
  outright. CPU is slower; subtitle generation is not latency-sensitive, so that is an acceptable
  answer and sometimes the right one.

Report which candidate ran, on which device, and how long it took. That result is part of the
milestone, not an aside. **Done for subtitles** — `docs/MILESTONE-1-RESULTS.md` has the numbers;
`docs/SPEC-FEEDBACK.md` has the backend comparison (faster-whisper chosen over whisper.cpp and
openai-whisper) and the correction this found for the GPU-risk rule above (compiled SM architecture
is the real risk factor, not release date — a 2026-built binary still failed this way).

## The denominator rule

This repo carries **no process ceremony** (see below), with one exception, because it is the mechanism
behind the subtitle requirement rather than overhead on top of it:

**Any check that could report "clean" and "examined nothing" in the same words must carry its
denominator and fail distinctly on zero.**

The two concrete cases here:

- A `.srt` with **zero cues** is *"examined nothing"*, never *"language check passed."* Report the
  detected language, the confidence, and **the number of cues examined**.
- A candidacy run that sampled **zero frames** is *"broken"*, never *"no defects found."* Report every
  metric alongside **the number of frames sampled**.

## Build states

Track three states explicitly and never report one as another:

- **built** — works and has been observed working
- **built-partial** — works for some inputs, paths or devices; say which
- **stub** — exists, does nothing real

"Subtitles work" when only the CPU path has ever run is **built-partial**, and should say so.

## File safety

These tools write outputs next to inputs the owner names on the command line. There is no managed
library and no destructive path — **as long as an output name is always distinct from its input.**
Never write over a source file. Never move or rename one.

The one exception is this repo's own `samples/` dev/test clips, covered above — never write there,
`out/<clip>/` instead. Everywhere else, next to the input is the rule.

## What this repo deliberately does not do

Do not add any of these. Each was decided against, not overlooked:

- **No batch or "process the library" mode.** The activity is reactive and targeted.
- **No Topaz model selection logic.** The wrapper takes a model name as an argument; choosing it is
  permanently the owner's call.
- **No demosaicing or decensoring.** Out of scope portfolio-wide.
- **No translation-quality work** — no contextual re-translation, no human-in-the-loop review. Gist
  quality is the stated bar. This is about not *improving* translation, not about never *measuring*
  it: `scripts/score_srt.py` and `scripts/fleurs_baseline.py` exist to give the gist-quality bar a
  number instead of an assertion, scoped as backend-selection/regression dev tooling, not a product
  feature — a real clip has no reference translation to score against, so they can't run on every
  invocation the way the shipped tool's checks do (`docs/SPEC.md` §9, `docs/SPEC-FEEDBACK.md`
  finding #7).
- **No provenance marking or pipeline integration.** The program it would feed does not exist yet.
- **No process ceremony.** No append-only decision log, no git hooks, no propose-then-confirm
  confirmation flow. This is deliberate: the specification says this two-day deliverable would cost
  more in ceremony than it is worth. Do not add it back.

## Small conventions

- **Python.** Chosen for subprocess glue around FFmpeg, the whisper tooling and Topaz's `tvai_*`
  filters.
- Each tool is **independently runnable** with no import-time dependency on the others.
- Cite by identifier or heading — `docs/SPEC.md` §8, not a line number.
- Keep the dependency list short. Prefer calling FFmpeg over wrapping it in a library.
