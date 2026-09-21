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

**Status: done.** Milestone 1 passed on both `--device cuda` and `--device cpu` against a real clip —
see `docs/MILESTONE-1-RESULTS.md` for the numbers and `docs/SPEC-FEEDBACK.md` for what building it
found wrong with the spec. The next tool in line, when picked up, is the upscale wrapper (§7's
ordering) or the candidacy analyser — owner's call which.

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
  it: `scripts/score_srt.py` and `scripts/fleurs_baseline.py` already exist to give the gist-quality
  bar a number instead of an assertion — that's a different thing from what this bullet forbids, but
  the spec itself doesn't clearly draw that line yet (`docs/SPEC-FEEDBACK.md` finding #7, still open).
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
