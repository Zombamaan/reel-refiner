# Spec feedback — Reel Refiner

What `docs/SPEC.md` got wrong, left out, or stated ambiguously, discovered by building.

This file is the build's second deliverable. It goes back to the specification space, where the spec is
corrected and the lesson is recorded. An empty file after a completed milestone is itself a result
worth stating — say so explicitly rather than leaving it blank.

Format: one entry per finding, newest last.

**The actual measured numbers from milestone 1 (chrF, timing overlap, the FLEURS baseline) are in
`docs/MILESTONE-1-RESULTS.md`, not here** — this file is for defects found in the spec, that one is
the results record.

**Status: all 9 findings from milestone 1 are resolved.** Every one either got applied directly to
`docs/SPEC.md` (findings #1, #2, #3, #7, #9), was a confirmation needing no correction (#4, #5), was
judged not a spec defect (#6), or was already fixed in code with a note here (#8). Nothing from
milestone 1 is still waiting on a decision.

**Status: findings #10-#20 are now resolved too, and applied to `docs/SPEC.md`.** #10 → §9's upscale
note; #11 and #15 → §4; #12 and #13 → §9; #14 → §12's milestone table (history, not a spec defect);
#16 → §8's candidacy row, its corrections subsection, and a new §13 out-of-scope entry; #17, #19 and
#20 → §8's corrections subsection; #18 → §6. Nothing from any of the three milestones is still waiting
on a decision.

**Status: finding #21 (real-library calibration) is resolved and applied.** Running the candidacy
analyser over 113 files from three real collections showed the §8 thresholds had been set from
synthetic material and were materially wrong — blocking and banding never crossed a bar in 113 files.
Thresholds recalibrated, banding demoted to diagnostic-only, §8's table updated.

#16 is the one that mattered most: it does not report a missing detail, it reports that a premise §8
and `CAPTURE.md` both rest on is only conditionally true, and is *least* true in the case the capture
says is most common. It is also the finding the real-library run most strengthened — from one
synthetic file to a 113-file control comparison.

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

**Resolved.** §9 and §12 now state plainly that neither original candidate was installed and that
acquiring/evaluating candidates from scratch was real, unbudgeted effort against the "Below Thin"
effort class — recorded as history rather than rescoped, since the milestone is already done.

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
`CUBLAS_STATUS_NOT_SUPPORTED` — this one doesn't crash, it silently degrades. Also confirms
`CAPTURE.md`'s open task — *"`whisper-cli` would be faster on GPU and should support translation —
verify with `whisper-cli -h`"* — half right: `-tr, --translate` is genuinely present (confirmed via
`whisper-cli -h`), but "faster on GPU" doesn't hold for this specific build; see above.

**Resolved.** §4 now states the risk factor as compiled SM architecture rather than release date,
names the non-crashing "claims CUDA, isn't faster" failure signature alongside
`CUBLAS_STATUS_NOT_SUPPORTED`, and gives the `torch.cuda.get_device_capability()` cross-check.

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

**Resolved, together with finding #9 below.** §9's table now has a row for `openai-whisper`
(CAPTURE's worked example) alongside the two originally-named candidates and the one actually
accepted — all four in one table, with why each was or wasn't depended on.

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

**Resolved — scoped as dev tooling, neither of the two options above.** Not a §8 Class A row (a
real clip has no reference translation to score against, so it structurally can't run on every
invocation like §8's other rows) and not deleted either (§9 now documents them as backend-selection
tooling with durable regression-baseline value). §2's "not a translation-quality tool" bullet now
says explicitly that not-improving and not-measuring are different claims, and only the first one
was ever meant.

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

**Resolved — the other direction from the suggested correction above.** Instead of updating §4 to
match the code, `reel_subtitles.py` was updated to match §4: a real clip (anywhere outside this
repo) now gets its output written next to the input, exactly as §4 states, with no `out/` involved
at all. `out/` remains only as `CLAUDE.md`'s dev-testing carve-out for the repo's own `samples/`
clips — now `out/<clip>/`, device-suffixed (`en.cuda.srt`, `en.cpu.srt`), which also closes this
finding's second point: both device runs coexist automatically, no manual `mv` needed. See
`docs/MILESTONE-1-RESULTS.md`'s "Reproducing these numbers" for the corrected commands.

*Source: external spec review, not discovered by building.*

### 9. The milestone's winning backend is neither candidate §9/§12 literally name

**Spec says:** §9's table names exactly two subtitle candidates: "Purfview Faster-Whisper-XXL" and
whisper.cpp's `whisper-cli`. §12's milestone condition is "proving that whisper-cli (or a fixed
Faster-Whisper-XXL) actually runs on the owner's GPU."
**What actually happened:** `whisper-cli`'s CPU path worked, but its CUDA build silently degrades
10× on this card (finding #2) — not depended on for GPU use. Faster-Whisper-XXL specifically was
never installed or tested at all; the milestone passed using a third, related-but-distinct artifact
instead: `pip install faster-whisper` (SYSTRAN's package, ctranslate2 4.8.2). Both projects
sit on the same underlying `faster-whisper`/ctranslate2 technology, but "a fixed Faster-Whisper-XXL"
specifically meant Purfview's bundle (the one that failed with `CUBLAS_STATUS_NOT_SUPPORTED`, per §4)
getting fixed — not a different distribution of the same library being installed instead. Finding #1
mentions installing `faster-whisper`/ctranslate2 from PyPI as acquisition overhead but never states
this plainly: §12's literal pass condition was not met by either named candidate; it was met by a
substitution.
**Suggested correction:** Either broaden §9/§12 to name "a faster-whisper/ctranslate2 distribution"
generically rather than Purfview's specific bundle, or treat this as a second, independent
substitution alongside finding #3's (openai-whisper vs CAPTURE's worked example) — the pattern is
now two-for-two: every backend actually evaluated across this build was something the spec didn't
literally name.

**Resolved — took the "formally accept the substitution" path**, not the "broaden the wording" one.
§9's table now names `pip install faster-whisper` as the accepted candidate outright, marks
Purfview's Faster-Whisper-XXL as superseded (never installed or tested here), and keeps
`whisper-cli` and `openai-whisper` as evaluated-but-not-depended-on rows. §12 states the accepted
candidate isn't the one originally named, pointing at §9 for the detail.

### 10. §9's "`tvai_up` straight into an H.265/AV1 encode... one command" is not satisfiable on this machine

**Spec says:** §9's reference-material table: *"Piping `tvai_up` straight into an H.265 or AV1 encode
at a chosen CRF, one command."* §3's metric and §7's must-have both restate "one command" as the
shape of the fix.
**What actually happened:** Topaz Video AI 7.1.5's bundled ffmpeg has no software H.265/AV1 encoder —
its encoder list is `hevc_nvenc`, `av1_nvenc`, `hevc_qsv`, `av1_qsv`, `hevc_amf`, `av1_amf`, none of
which accept `-crf`. The only CRF-capable encoder in that binary is `libvpx-vp9`, which is neither
H.265 nor AV1. Confirmed by direct probe (`ffmpeg -h encoder=libx265` against Topaz's own `ffmpeg.exe`
reports *"Codec 'libx265' is not recognized"*) and by reading its build configuration
(`--enable-nvenc --enable-libvpx --enable-libaom`, no `--enable-libx265`, no `--enable-libsvtav1`).
A genuinely single-process, true-CRF `tvai_up`-to-H.265/AV1 command does not exist on this machine.
**Suggested correction:** Read "one command" as "one pipeline the owner runs with one invocation of
this wrapper," not "one ffmpeg process." `reel_upscale.py` runs `tvai_up` in Topaz's ffmpeg piped into
a *second*, system ffmpeg process (which does have `libx265`/`libsvtav1`) for the CRF encode —
verified working end to end (§8's numbers are in `docs/MILESTONE-2-RESULTS.md`). The owner still runs
exactly one command; two ffmpeg processes run underneath it. Update §9's phrasing if "one command" is
meant to promise a single process specifically, since that promise can't be kept here.

**Resolved — applied to §9.** The reference table's `tvai_up` row now says "**Not one ffmpeg process — see below**", and a new subsection under it records the full encoder inventory of Topaz's bundled ffmpeg, the two-process pipe that replaces the single-process reading, and the instruction to read "one command" as the owner's invocation rather than the process count.

### 11. `TVAI_MODEL_DIR` is mandatory and appears nowhere in the spec or the capture

**Spec says:** Nothing — §4's "Other" section confirms Topaz 7.1.5 is installed and licensed, but
records no environment variable, install path, or model directory.
**What actually happened:** Running Topaz's `tvai_up` filter without `TVAI_MODEL_DIR` set fails
immediately with `Model not found: <name>`, exit -22, before any GPU work starts — confirmed by
probing with and without the variable set. The correct value
(`C:\ProgramData\Topaz Labs LLC\Topaz Video AI\models`) was found only by reading Topaz's own log file
(`%APPDATA%\Topaz Labs LLC\Topaz Video AI\logs\*.tzlog`, line `TVAI_MODEL_DIR, veaiDataFolder ...`),
not from any Topaz or repo documentation. A second variable, `TVAI_MODEL_DATA_DIR`, set to the same
path, was present in every working probe in this session; not confirmed independently required, but
carried along rather than risking removing it without re-testing.
**Suggested correction:** Record `TVAI_MODEL_DIR` (and `TVAI_MODEL_DATA_DIR`) as a required piece of
this machine's Topaz setup, the same way §4 records the CUDA DLL search-path requirement for
faster-whisper. `reel_upscale.py` sets both itself (`REEL_TVAI_MODEL_DIR` env-overridable, matching
the `REEL_FFMPEG`/`REEL_BCOMPARE` convention) so the owner never has to know this by hand.

**Resolved — applied to §4.** "Other" now carries a Topaz-environment block: `TVAI_MODEL_DIR` as a hard requirement with its value and the log line it was recovered from, `TVAI_MODEL_DATA_DIR` alongside it (marked as not independently confirmed), the two-coexisting-installs hazard, and the `REEL_TVAI_FFMPEG` / `REEL_TVAI_MODEL_DIR` overrides the tools expose.

### 12. No default CRF is specified anywhere in the spec

**Spec says:** §9 says "at a chosen CRF"; nowhere states what that value should default to.
**What actually happened:** Not a defect exactly — SPEC.md §2/§13 permanently keeps *model* choice
the owner's manual call, and the capture never treats CRF the same way, so its absence reads as an
oversight rather than a deliberate parallel to the model-selection rule.
**Suggested correction:** Resolved by owner decision this session, recorded here rather than guessed:
default CRF is **20** (`reel_upscale.py`'s `DEFAULT_CRF`), chosen deliberately conservative — an
upscale spends real GPU time synthesizing high-frequency detail, and a default that discards more of
it than necessary would be working against the tool's own output. `--crf` remains fully overridable
per run. If the owner ever wants this locked to "no default, same as `--model`," that's a one-line
change (`required=True`) with no other structural impact.

**Resolved — applied to §9.** The new upscale subsection records CRF 20 as the v1 default with its reasoning (don't discard the detail the upscale just paid for), and adds the per-encoder preset defaults, including why a single shared preset string cannot work across libx265, libsvtav1 and hevc_nvenc.

### 13. Total silence on audio, container, and metadata passthrough

**Spec says:** Nothing. Neither §9 nor CAPTURE.md's upscale section mentions audio codec handling,
stream mapping, container choice, chapters, or metadata passthrough anywhere.
**What actually happened:** These aren't optional details — a raw video pipe (the only route to a
true CRF encode per finding #10) carries no audio at all, so an upscale wrapper that only piped
`tvai_up`'s output would silently produce a video-only file. This had to be designed from scratch:
the original file is given to the encoder as a *second* input, its audio is mapped through untouched
(`-map 1:a? -c:a copy`), and its container metadata is copied by default (`-map_metadata 1`,
`--no-keep-metadata` to opt out). Verified end to end: output audio matches source audio's codec
(`aac`) and duration (20.00s vs 20.00s) exactly — see `docs/MILESTONE-2-RESULTS.md`.
**Suggested correction:** Record the audio/metadata passthrough behavior in §9 or §13 as a stated
design decision, not a silent implementation detail — the next person building against this spec
should not have to discover independently that a naive `tvai_up`-into-encoder pipe drops audio.

**Resolved — applied to §9.** The same subsection now states the audio and metadata passthrough design as a deliberate decision rather than an implementation detail: original-as-second-input, `-map 1:a? -c:a copy`, `-map_metadata 1`, `-fps_mode passthrough`, and why the pipe uses `nut` rather than `yuv4mpegpipe`.

### 14. No video clip exists in `samples/` — milestone 2 could not meet milestone 1's "one real clip" bar the same way

**Spec says:** §12's precedent (milestone 1) is "one real clip end to end." Nothing in §12 covers the
upscale wrapper specifically — see its own note that milestone 1 deliberately left it for later.
**What actually happened:** `samples/2208/source.wav` (the only sample clip in this repo) is audio
only — there is no video clip anywhere in `samples/` to upscale. Getting a real clip requires the
owner (the same `yt-dlp`-against-a-live-URL friction finding #6 already recorded), so this session
verified against a synthetically generated degraded clip instead (`ffmpeg testsrc2` + a sine-wave
audio track, hard-compressed to imitate a low-quality web source) rather than blocking on one.
**Suggested correction:** Not a spec defect to fix — recorded per `CLAUDE.md`'s instruction not to
silently substitute without saying so. Build state is **built-partial**: the pipe, the CRF encode,
audio passthrough, and both denominator-rule gates (truncation, size ratio) are all proven against
real ffmpeg processes and a real (if synthetic) file, but no actual codec/interlacing/multi-track-audio
variety of a real clip has gone through yet. See `docs/MILESTONE-2-RESULTS.md`.

**Resolved as history, not as a spec correction** — there is no defect here to fix. Recorded in §12's new milestone table, which states both built-partial tools' single shared cause (no real clip has run) and names the untested dimensions, with grain flagged as the one most likely to move a candidacy number.

### 15. `tvai_up` segfaults, rather than erroring cleanly, on fewer than 4 input frames

**Spec says:** Nothing — no capture or spec text anticipates any `tvai_up` failure mode, clean or
otherwise, distinct from the general GPU-risk rule in §4.
**What actually happened:** A one-frame `tvai_up` smoke-test probe (`testsrc2=size=64x64:rate=1:
duration=1`, intended as a fast preflight sanity check) segfaulted Topaz's ffmpeg outright — exit code
139/SIGSEGV, no stderr, no ffmpeg error message at all. Bisected on this machine: 1, 2, and 3 input
frames all segfault identically; 4 frames and above run cleanly, with a normal, informative ffmpeg
error for an actually-invalid model name at 8 frames. This reads as an unfilled temporal/lookahead
buffer the model expects before it will run, not anything specific to a bad argument — this is a
**third** GPU/CUDA-adjacent failure signature for the §4 list, alongside `CUBLAS_STATUS_NOT_SUPPORTED`
(crashes) and the silent 10×-slower-while-claiming-CUDA case from milestone 1 (degrades without
error): a filter that crashes the whole process on a too-short input instead of reporting "insufficient
frames" or similar.
**Suggested correction:** Add to §4's GPU-risk list: **never probe or preflight-check a Topaz `tvai_*`
filter with fewer than a handful of frames** — a segfault under a preflight check will otherwise read
as this tool's own crash rather than an upstream limitation. `reel_upscale.py`'s preflight smoke test
uses 8 frames specifically to stay clear of this threshold with margin.

**Resolved — applied to §4.** The GPU/CUDA section now lists this as the **third** failure signature alongside `CUBLAS_STATUS_NOT_SUPPORTED` and the silent 10×-slower degradation, with the bisected frame threshold and the standing rule never to probe a `tvai_*` filter with fewer than a handful of frames.

### 16. "Is it genuinely 1080p or a 480p upscale in a 1080p container" is computable only for *stretched* upscales — and the premise is weakest exactly where the capture says the need is greatest

**Spec says:** §8's candidacy Class A row: *"is this source genuinely high-resolution, or an
upscaled-once source sitting in a bigger container."* `CAPTURE.md`'s "Candidacy vs result" section
states the mechanism and the motive together: *"is it genuinely 1080p or a 480p upscale in a 1080p
container... For these sources the already-upscaled-once case is common, and catching it is pure saved
time."*
**What actually happened:** The metric works, and works well, for *conventional* upscales. A source
scaled up with an ordinary resampler has nothing above its original Nyquist limit — interpolation
invents no detail — so its spectrum falls off a cliff exactly where the true resolution ran out.
Ground truth through the shipped tool, 1080p containers built from known sources: 1080p→1063p,
720p→730p, 540p→574p, 360p→388p, 270p→308p. Against synthetic band-limited planes the estimate is
accurate to under 3% (built at 0.20/0.30/0.50/0.70 of Nyquist, measured 0.207/0.309/0.512/0.707).

It does **not** work for AI upscales, and this was verified rather than assumed. Run against this
repo's own `out/degraded/upscaled.ahq-12.crf20.mp4` — a Topaz `tvai_up` 2× upscale of 270p content,
produced by milestone 2 — the analyser reported **520p of a 540p container, 96% "genuine."** `tvai_up`
*synthesizes* plausible high-frequency detail; that synthesized detail is real spectral energy, and it
fills precisely the gap this test looks for. A second, narrower blind spot exists for
nearest-neighbour expansion (hard square edges are spectrally broadband, so an 8× NN expansion still
reads >0.9) — recorded in `tests/test_candidacy_verify.py` as asserted behaviour rather than left to
be rediscovered.

**This is not simply "the metric has a limitation."** Detectability falls as the prior upscaler gets
better. A lazy stretch is caught easily; a modern AI upscale — increasingly the likely one, and by far
the most expensive to redo — is not caught at all. The capture's claim that *"the already-upscaled-once
case is common, and catching it is pure saved time"* is therefore true for the cheap half of that case
and false for the expensive half.
**Suggested correction:** Qualify §8's row and CAPTURE's sentence to say *stretched* or *interpolated*
upscale rather than upscale generally, and state plainly that a clean effective-resolution reading is
not evidence a source was never upscaled. `candidacy_verify.CAVEAT` prints exactly that on every run
and in every report, so the tool never makes the claim the spec currently implies it can. Detecting AI
upscales is research-grade and well outside the "Below Thin" effort class — it should be recorded as
out of scope, not left as an implied capability.

**Evidence upgraded after real-library testing.** The claim above rested on a single synthetic
Topaz output. It has since been tested against 113 files from three real collections: 31 whose
filenames mark a previous upscale read p25=51% / median=76%, against 82 unmarked files at p25=71% /
median=82% — heavily overlapping. At n=26 and n=50 the upscaled group read *higher* than the control;
at n=113 it reads *lower*. The direction is not stable across subsamples, which is the cleanest
available demonstration that there is no signal, only overlap. See `docs/MILESTONE-3-RESULTS.md`.

**Resolved — applied to §8 and §13.** §8's candidacy row now reads "**conventionally (interpolated) upscaled-once**", and a new "Corrections to the candidacy row" subsection carries the ground-truth ladder, the 96%-genuine Topaz result, and the statement that a clean reading is not evidence a source was never upscaled. §13 gains an **AI-upscale detection** out-of-scope entry saying why a detector is not the answer. The tool prints the caveat on every run and in every report, so the claim is never made in the first place.

### 17. No threshold exists anywhere for any candidacy metric, and the exit-code decision made them mandatory

**Spec says:** §8 names three metrics — *"an effective-resolution estimate, a blocking/banding score,
a high-frequency energy ratio"* — and gives no numeric bar for any of them. §7 and §3 both call for a
*"verdict,"* and §4 requires that verdict to *"expose numbers rather than rest on a visual read."*
**What actually happened:** A verdict needs boundaries. The owner chose this session to have the exit
code carry the verdict (`0` worth / `3` marginal / `4` not worth) so a run can chain into
`reel_upscale.py` — which means the tool cannot hedge its way out of a hard cut, even though the
report text does hedge. Every threshold had to be invented. Following finding #12's precedent (the CRF
default, *"resolved by owner decision this session, recorded here rather than guessed"*), they were
put to the owner with their measured basis and approved rather than chosen silently:

| Threshold | Value | Measured basis |
|---|---|---|
| `--min-resolution-ratio` | 0.80 | clean sources measured 1.00; stretched ones 0.28–0.68 |
| `--blocking-worth` | 2.0 | clean natural source 1.00; crf40 7.43; crf51 12.17 |
| `--banding-worth` | 3.0 | clean 1.00–1.17; quantized 8.14–21.50 |
| `--resolution-marginal` / `--blocking-marginal` / `--banding-marginal` | 0.95 / 1.5 / 1.5 | mild elevation over the clean baselines above |

**Suggested correction:** Record these in §8 as the v1 bars with their provenance, or state explicitly
that thresholds are deliberately left to the tool. All six are flags, so nothing is frozen — but the
spec should not continue to imply a "computable verdict" exists without saying what makes it compute.

**Resolved — applied to §8.** The corrections subsection records all six thresholds in a table with the measured basis for each, states that the exit-code-as-verdict decision is what made hard boundaries mandatory, and notes that all six are flags so nothing is frozen.

### 18. §6 says a report is written "next to the input file" without naming a format, and without reconciling against finding #8

**Spec says:** §6: *"The candidacy analyser writes a report of computed metrics next to the input file
for the owner to read; that's a report, not a data model this program owns."*
**What actually happened:** Two gaps. First, no format is named — "for the owner to read" implies
human-readable, but nothing says whether a machine-readable artifact is wanted alongside. Resolved by
owner decision: both a `.txt` (what you actually read months later when asking "did I already look at
this?") and a `.json` (every metric, all three denominators, the thresholds used, and the per-frame
values — too noisy for the report, exactly what a later comparison needs). Second, "next to the input
file" collides with finding #8's resolution in the same way `reel_subtitles.py` did: a `samples/` clip
must write to `out/<clip>/` instead. Implemented with the same three-branch rule as both sibling tools.
**Suggested correction:** §6 should say "next to the input, or `out/<clip>/` for this repo's own
`samples/` clips," matching the correction finding #8 already applied to §4.

**Resolved — applied to §6.** That section now specifies both files and what each is for, states that "next to the input file" carries finding #8's `samples/`→`out/<clip>/` carve-out, and records that re-running overwrites deliberately.

### 19. The blocking metric's baseline is content-dependent, so its threshold is a heuristic rather than a calibrated bar

**Spec says:** §8 asks for *"a blocking/banding score"* as a Class A computable, with no caveat about
how it should be read.
**What actually happened:** Blocking is measured as gradient across the codec's 8-px grid ÷ gradient
elsewhere, and it tracks compression cleanly on a given source (crf51 12.17 → crf40 7.43 → crf30 4.52
→ crf20 4.59). But the *baseline* moves with content: a clean smooth/natural source measured **1.00**
while a clean `testsrc2` measured **4.72**, because `testsrc2`'s hard synthetic edges align with the
8-px grid. That is pathological content rather than representative, but it is enough to make an
absolute threshold a heuristic. Observed live during verification: every clip in the `testsrc2`-based
resolution ladder returned "worth upscaling" on blocking alone, including the untouched native 1080p
one.
**Suggested correction:** Note in §8 that the blocking score is comparative, most trustworthy when read
against the same source at different encode settings, and that a single absolute reading on
grid-aligned synthetic content can mislead. The effective-resolution metric should carry the most
weight of the three; blocking is the weakest.

**Resolved — applied to §8.** The corrections subsection records both clean baselines (1.00 natural, 4.72 grid-aligned synthetic), states that blocking is best read comparatively, and names it the weakest of the three metrics.

### 20. Heavy compression and a stretched source are not distinguishable by the effective-resolution metric

**Spec says:** §8 treats the effective-resolution estimate and the blocking/banding score as separate
metrics answering separate questions — *"is this source genuinely high-resolution"* versus *"how much
blocking/banding."*
**What actually happened:** They are not independent. Heavy compression strips high-frequency detail,
which reads exactly like a stretch. A natural 1080p source re-encoded at crf42 — never resized at all —
measured **827p of 1080p (77%)**, tripping the stretched-source bar. The verdict was still correct
(that file genuinely is worth restoring), but the *reason* would have been wrong.
**Suggested correction:** Not a defect to fix in the metric — the two causes are genuinely
indistinguishable from a single frame's spectrum, and both mean "detail is missing," which is what the
verdict actually turns on. Fixed in the wording instead: the tool reports *"a stretched source, or high
frequencies stripped by heavy compression"* rather than asserting the first. Worth stating in §8 so the
two rows are not read as more independent than they are.

**Resolved — applied to §8.** Recorded in the corrections subsection with the crf42 measurement (77% of container on a clip that was never resized), and noted that the verdict is unaffected while the reason would have been wrong. Fixed in the tool's wording, which names both causes.

### 21. Two of §8's three candidacy metrics barely move on real video, and one does not move at all

**Spec says:** §8's candidacy row names three computable metrics — *"an effective-resolution estimate,
a blocking/banding score, a high-frequency energy ratio"* — and treats them as co-equal inputs to a
verdict.
**What actually happened:** Calibrated against synthetic sources, all three looked discriminating: a
clean gradient banded at 1.00 against 8.14–21.50 for quantized content, and blocking ran 1.00 clean
against 7.43 at crf40. Measured across 113 files from three real collections:

| Metric | real range | real median | "worth" bar | times crossed |
|---|---|---|---|---|
| effective-resolution ratio | 32–99% | 82% | < 0.80 | fired constantly |
| blocking | 0.98–1.72 | 1.13 | > 2.0 | **0 / 113** |
| banding | **1.00–1.20** | 1.16 | > 3.0 | **0 / 113** |

Blocking never crossed its bar; banding never crossed even its *marginal* bar, and its entire spread
across a real library is 0.20 wide. Banding measures luma-histogram occupancy — quantization — and
modern encodes are dithered enough that the histogram stays full. **On real video it has no
discriminating power whatever.** In practice the verdict was being decided by the resolution ratio
alone, while appearing to weigh three signals.

The deeper issue is that the synthetic calibration was not merely imprecise, it was measuring a
different population: `testsrc2` and quantized gradients exhibit damage that real encodes do not, and
carry detail to Nyquist that real encodes do not. Every bar derived from them was wrong in the same
direction.
**Suggested correction:** §8 should say that the three metrics are not co-equal — the
effective-resolution estimate carries the verdict, blocking is a weak secondary signal, and banding is
diagnostic only. **Applied:** thresholds recalibrated to the measured distribution (resolution
0.80→0.70 and 0.95→0.90; blocking 2.0→1.5 and 1.5→1.25), and banding's thresholds now default to
`None`, disabling its checks while it continues to be computed, printed and written per-frame to the
`.json`. Passing `--banding-worth` a number re-enables it with no code change. Recalibration moved
"not worth upscaling" from 8% of the sampled library to 22% — before it, the tool declined almost
nothing, including a 255 Mbps ProRes master.
