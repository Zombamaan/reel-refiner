# Milestone 3 — candidacy analyser, measured results

The numbers behind `docs/SPEC.md` §7's candidacy must-have and §8's candidacy Class A row. Written
down here for the same reason `MILESTONE-1`/`MILESTONE-2` exist — this is the durable record, not
console output from a session that's already over.

**Build state: built.** All three §8 metrics are implemented, all three verdict bands are reachable,
the denominator rule fires correctly, the chain into `reel_upscale.py` works — and the tool has now
been observed working on **113 real files from three collections with zero failures**, which is what
`CLAUDE.md`'s "built" requires. See "Real-clip calibration" below; that run also corrected the
thresholds, which had been set from synthetic material and were materially wrong.

The synthetic ground-truth sections come first because they are what the metrics were *designed*
against and remain the clearest demonstration that the maths is right. The real-library section is
what they were *calibrated* against.

## What the tool is and how it decides

`reel_candidacy.py` samples N frames with fast seeks across the middle 90% of a file, computes four
numbers per frame at the source's **native** resolution (downscaling first would destroy the very
high-frequency content being measured), takes the **median** across frames, and maps the result to a
verdict through an ordered ladder — severe bars first, so a file can only be marginal if it trips no
severe bar.

The exit code carries the verdict, an explicit owner decision so a run chains into the upscale wrapper.
That decision is what forced hard thresholds to exist at all; `docs/SPEC-FEEDBACK.md` finding #17
records them with their measured basis.

```
0  worth upscaling      3  marginal      4  not worth upscaling
1  usage / IO error     2  sampled no usable frames — BROKEN
```

## The effective-resolution metric (`candidacy_verify.frame_metrics`)

Method: Hann-windowed 2-D FFT of the luma plane, power binned by a **separable** (square) normalized
radius — scalers band-limit each axis independently, so a stretched source's cutoff is a box, not a
disc — then a single reverse-cumulative sum gives residual energy above every candidate cutoff at once.
The reported figure is where that residual crosses 1e-4 of AC energy.

**Ground truth, through the shipped tool.** 1080p containers built from known true sources
(`ffmpeg testsrc2`, downscaled then scaled back to 1920×1080, crf 14), 10 frames each:

| True source | Reported | Error |
|---|---|---|
| 1080p (untouched) | 1063p | −1.6% |
| 720p → 1080p | 730p | +1.4% |
| 540p → 1080p | 574p | +6.3% |
| 360p → 1080p | 388p | +7.8% |
| 270p → 1080p | 308p | +14.1% |

Consistently errs high — a resampler's rolloff is gradual, not a brick wall — and the error grows as
the true resolution falls. Ample to separate "this 1080p file really holds 388p" from "this 1080p file
is 1080p," which is the only question being asked.

**Against synthetic band-limited planes** (`tests/test_candidacy_verify.py`), where the true cutoff is
exact rather than resampler-dependent, accuracy is under 3%:

| Built at (fraction of Nyquist) | Measured |
|---|---|
| 0.20 | 0.207 |
| 0.30 | 0.309 |
| 0.50 | 0.512 |
| 0.70 | 0.707 |

## The blind spot — stated here because it is the most important result

Run against this repo's own `out/degraded/upscaled.ahq-12.crf20.mp4` — a Topaz `tvai_up` **2× upscale
of 270p content**, produced by milestone 2, so its true provenance is certain:

| | Container | Reported effective resolution | Verdict |
|---|---|---|---|
| Topaz 2× upscale of 270p | 960×540 | **520p (96% of container)** | missed entirely |

`tvai_up` *synthesizes* plausible high-frequency detail rather than interpolating, so it fills exactly
the spectral gap this test looks for. **This is structural, not a tuning problem.** A second, narrower
blind spot: nearest-neighbour expansion reads >0.9 however far it was expanded, because hard square
edges are spectrally broadband — asserted in the test suite so it can't be quietly rediscovered.

The consequence is recorded as `docs/SPEC-FEEDBACK.md` finding #16, and it is sharper than a footnote:
detectability falls as the prior upscaler gets better, so the cheap half of the already-upscaled-once
case is caught and the expensive half is not. Every run and every report prints the caveat.

## Blocking and banding

**Blocking** — mean |Δ| across the codec's 8-px grid ÷ mean |Δ| elsewhere, both axes averaged. Tracks
compression cleanly on one source:

| Encode | Blocking |
|---|---|
| crf 20 | 4.59 |
| crf 30 | 4.52 |
| crf 40 | 7.43 |
| crf 51 | 12.17 |

But its **baseline moves with content** — a clean natural/gradient source measured **1.00**, a clean
`testsrc2` measured **4.72**, because `testsrc2`'s hard edges align with the 8-px grid. Recorded as
`docs/SPEC-FEEDBACK.md` finding #19; it is the weakest of the three metrics and the effective-resolution
figure should carry more weight.

**Banding** — luma histogram occupancy, `span / distinct levels present`. The plan originally specified
a per-block level count; it was built, tested, and **replaced** after it scored 13.0 on clean detailed
content (a false positive) and found zero qualifying blocks on a clean gradient, with scores swinging
1.57 / 8.92 / 13.00 / 1.15 on one frame depending on block-selection criteria. The owner approved the
substitution before it was made. Occupancy measures the quantization that *causes* banding:

| Content | Banding |
|---|---|
| Clean gradient | 1.00 |
| Dithered gradient | 1.00 |
| Real crf40 clip | 1.00 |
| Topaz upscale | 1.04 |
| Detailed `testsrc2` | 1.17 |
| Quantized to 32 levels | 8.14 |
| Quantized to 16 levels | 10.00 |
| Quantized to 5 levels | 21.50 |

Clean content sits at 1.00–1.17, quantized content at 8+. The `--banding-worth 3.0` default sits in a
wide empty gap rather than on a contested boundary.

## All three verdict bands, reachable on real files

A natural 1080p source (gradients + grain) re-encoded at descending quality, 6 frames each:

| Encode | Effective resolution | Blocking | Verdict | Exit |
|---|---|---|---|---|
| crf 20 | 100% | 0.92 | not worth | 4 |
| crf 22 | 100% | 1.03 | not worth | 4 |
| **crf 23** | 100% | **1.63** | **marginal** | **3** |
| crf 24 | 100% | 3.05 | worth | 0 |
| crf 42 | 77% | 2.50 | worth | 0 |

The marginal band is narrow on this content — it occupies roughly one CRF step — but it is genuinely
reachable without contrivance. The crf42 row is also `docs/SPEC-FEEDBACK.md` finding #20 in the wild:
that file was **never resized**, yet read at 77% of container, because heavy compression strips high
frequencies exactly as a stretch does. The verdict is right and the reason text names both causes.

## The denominator rule (`CLAUDE.md`)

Tiered denominators follow `srt_verify.py`'s cues → non-empty → scoreable precedent: a solid black
frame has no measurable spectrum and would poison every metric, exactly as a `[Music]`-only cue has no
language to detect. So **frames_requested → frames_decoded → frames_usable**, and the zero test gates
on *usable*.

An all-black 5s clip, 8 frames requested:

```
broken: sampled nothing usable — 8 frames requested, 8 decoded, 0 usable (a usable frame
needs luma variation above std 1.0; an all-black or single-colour source reaches here)
frames_requested=8 frames_decoded=8 frames_usable=0 effective_resolution_px=None ... verdict=broken
exit code: 2
```

All three tiers are named, every metric is reported as `None` rather than as a flattering zero, and the
word "broken" leads. A non-video file and a missing path both return **1**, not 2 — a precondition
failure is not a verdict.

**Correction — a fourth way to overstate the denominator, found by a later code review and fixed.**
`sample_timestamps` returned `[0.0] * count` when the duration was unknown, so every sample landed on
frame 0 and the report claimed `frames_usable=20` having examined **one frame twenty times**. That is
the same failure this rule exists to prevent, arriving through the sampling layer rather than the
metric layer. Two changes: `probe_video` now recovers a duration from the video stream, then from
frames ÷ frame rate via `-count_packets`, before falling back to the container (a `.ts` capture with no
container duration now probes correctly at 10.0s instead of 0), and `run()` **refuses outright** when
the duration is still unknown rather than sampling, saying so in those terms. `sample_timestamps` now
returns a single timestamp rather than `count` copies of zero, so it cannot fabricate a denominator
even if called directly.

## Chaining (`reel_candidacy.py && reel_upscale.py`)

The reason the exit code carries the verdict. Verified both directions:

```
$ python reel_candidacy.py <crf42 clip> && python reel_upscale.py <clip> --model ahq-12 ...
  -> candidacy exit 0, upscale ran, wrote chain.upscaled.ahq-12.crf20.mp4 in 19.7s

$ python reel_candidacy.py <clean clip> && python reel_upscale.py ...
  -> candidacy exit 4, upscale correctly skipped
```

## Re-verdicting a saved report without decoding the video

`candidacy_verify.py` runs standalone against a `.candidacy.json`, reusing its stored per-frame
metrics — so "what if I move the bar?" costs nothing:

```
$ python candidacy_verify.py myclip.candidacy.json                       -> exit 0 (worth)
$ python candidacy_verify.py myclip.candidacy.json --blocking-worth 9 \
      --min-resolution-ratio 0.5 --resolution-marginal 0.5 ...           -> exit 4 (not worth)
```

## Timing

20 frames (the default), measured end to end including frame extraction:

| Resolution | 20 frames | Per frame |
|---|---|---|
| 480p | 2.0s | 0.10s |
| 1080p | 5.9s | 0.29s |
| 4K | 21.2s | 1.06s |

21 seconds at 4K against an upscale measured in hours. The centre-crop fallback the plan held in
reserve was not needed. The per-cutoff sweep was replaced early with a single radial histogram plus
reverse-cumulative sum — **13× faster at 4K** (1.08s → 0.08s) than re-masking the array per candidate
cutoff.

## File safety

Source checksums unchanged after every run. Reports for a real clip land next to the input
(`myclip.candidacy.txt` / `.json`); a `samples/` clip routes to `out/<clip>/` and **nothing was written
into `samples/`** — verified by listing it after a run. Re-running overwrites the previous report
deliberately: unlike an upscale, a run costs seconds and a newer answer supersedes rather than competes.

## Reproducing these numbers

Assumes `.venv/` per `requirements.txt` and system ffmpeg on `PATH` (or `REEL_FFMPEG`). Both `samples/`
and `out/` are git-ignored, so nothing below is committed.

```
# Ground-truth resolution ladder
for r in 1080 720 540 360 270; do
  ffmpeg -f lavfi -i testsrc2=size=1920x1080:rate=24:duration=6 \
         -vf "scale=-2:$r,scale=1920:1080" -c:v libx264 -crf 14 from$r.mp4
  python reel_candidacy.py from$r.mp4 --frames 10 --no-report
done

# The blind spot (needs milestone 2's output)
python reel_candidacy.py out/degraded/upscaled.ahq-12.crf20.mp4 --frames 10 --no-report

# Verdict bands
ffmpeg -f lavfi -i gradients=size=1920x1080:rate=24:duration=6 \
       -vf noise=alls=10:allf=t+u -c:v libx264 -crf 12 natural.mp4
for q in 20 22 23 24 42; do
  ffmpeg -i natural.mp4 -c:v libx264 -crf $q n$q.mp4
  python reel_candidacy.py n$q.mp4 --frames 6 --no-report
done

# Denominator rule
ffmpeg -f lavfi -i color=c=black:size=640x360:rate=24:duration=5 -c:v libx264 black.mp4
python reel_candidacy.py black.mp4 --frames 8 --no-report   # exit 2
```

## Real-clip calibration — 113 files, three collections

Everything above this section was measured on synthetic material. This section is what happened when
the tool met a real library: **113 files sampled from `D:\Funscript Videos`, `D:\MultiAxis Videos` and
`E:\Main Stash`** (12,237 files, ~29 TB total), stratified by collection × resolution tier × bitrate
tier × whether the filename marks it as a previous upscale.

**113 runs, 113 produced metrics, 0 failures, 0 files with an unusable frame.** The probe fallbacks,
the frame sampling and the tiered denominator all held on real containers — including `wmv3`/`wmav2`,
`mpeg2video`/`mp2`, mkv without `nb_frames`, ProRes 10-bit and variable-frame-rate 4K120.

### Finding #16 confirmed with controls, not with one file

The milestone-3 claim above rested on a single synthetic Topaz output reading 96%. It now rests on this:

| Group | n | p25 | median | range |
|---|---|---|---|---|
| Filename marks a previous upscale | 31 | 51% | **76%** | 32–96% |
| No such marking | 82 | 71% | **82%** | 37–99% |

Heavily overlapping. More telling: at n=26 and n=50 the upscaled group read *higher* than the control;
at n=113 it reads *lower*. **The direction is not stable across subsamples**, which is the cleanest
demonstration available that there is no signal here — only overlap. The metric cannot identify a
previous upscale, and this is now evidence rather than inference.

### The detail ratio is dominated by container tier

| Container | n | median detail ratio | median true detail |
|---|---|---|---|
| ≤720p | 31 | 91% | 497p |
| 1080p | 31 | 85% | 894p |
| 1440p | 7 | — | 1168p |
| 2160p | 38 | **72%** | **1409p** |
| >2160p | 6 | — | 3128p |

A typical 4K file in this library holds ~1409p of real detail — 65% of what its container claims.
Library-wide, 72% of files hold under 90% of container and 44% under 80%. **Of 40 4K-container files,
15 hold under 60%** — the "served as 4K but containing a lower resolution video" case, at 38% of 4K
material.

### The thresholds were wrong, and by how much

The original bars came from synthetic sources where clean content reads 100% and damage reads 7–20.
Real compressed video never reaches either. Measured across the 113:

| Metric | real range | real median | old "worth" bar | times crossed |
|---|---|---|---|---|
| detail ratio | 32–99% | 82% | < 0.80 | (fired constantly) |
| blocking | 0.98–1.72 | 1.13 | > 2.0 | **0 / 113** |
| banding | **1.00–1.20** | 1.16 | > 3.0 | **0 / 113** |

Recalibrated to the measured distribution — `--min-resolution-ratio` 0.80 → **0.70** (the real p25),
`--resolution-marginal` 0.95 → **0.90** (the real p75), `--blocking-worth` 2.0 → **1.5** (real p95 is
1.53), `--blocking-marginal` 1.5 → **1.25**:

| Verdict | before | after |
|---|---|---|
| worth | 50 (44%) | 34 (30%) |
| marginal | 54 (48%) | 54 (48%) |
| **not worth** | **9 (8%)** | **25 (22%)** |

Before recalibration the tool declined 8% of a library — including, at one point, a 255 Mbps ProRes
master. It now declines 22%, which is the point of a tool meant to save hours.

### Banding reports but no longer decides

Across all 113 files banding spanned **1.00 to 1.20** and crossed neither its "worth" bar (3.0) nor its
"marginal" bar (1.5) even once. It measures luma-histogram occupancy — i.e. quantization — and modern
encodes are dithered enough that the histogram stays full. It has no discriminating power on real
video.

It is still computed, still printed, and still written per-frame to the `.json` (SPEC.md §8 asks for
the metric, not for it to gate anything). Its two thresholds now default to `None`, which disables the
checks; passing `--banding-worth` a number re-enables them with no code change, so a future
recalibration on different material costs nothing.

### Timing on real footage

| Tier | median | p90 | max |
|---|---|---|---|
| SD | 2.2s | 7.2s | 9.5s |
| HD | 8.2s | 21.5s | 100.7s |
| UHD | 25.2s | 60.2s | **277.0s** |

At 10 frames. The outliers are seek cost on large files over spinning disk, not analysis cost — the
FFT work is bounded by resolution, which the synthetic 4K benchmark above already characterised.

### Suggested target resolution — built on this evidence

The metric answers "how much detail is present relative to the container," which is **not** the same
question as "is this worth upscaling." The tool now reports both: the verdict, and separately a
suggested target derived from **measured detail, never the container**.

Deriving from the container fails in both directions, which is exactly what the owner flagged: a flat
4K target over-applies on a low-resolution original, and a flat 2× explodes a low-quality 8K input to
16K. Measured detail is immune to both, because it is what the file contains rather than what its
header claims. The target is the largest standard tier at or below 2× measured detail — snapped
**down**, because past that an upscaler invents rather than resolves. The raw figure prints alongside,
so an override upward is an informed one (`--detail-multiplier`).

Verified on real library files:

| Case | Container | Measured detail | Suggested target | Reads as |
|---|---|---|---|---|
| honest 1080p | 1920×1080 | 892p (83%) | **1440p** | headroom, ×1.3 on the container |
| 720p odd container | 1280×720 | 574p (80%) | **1080p** | headroom, ×1.5 |
| ProRes master | 1920×1080 | 991p (92%) | **1440p** | headroom, but verdict says *not worth* |
| fake-4K web rip | 3840×2160 | 962p (45%) | **1440p** | already 2160p — cleanup, not resolution |
| known upscaled 4K | 4096×2160 | 1080p (50%) | **2160p** | already there — cleanup, not resolution |

The last two are the owner's "served as 4K but containing a lower resolution video" case, correctly
identified and correctly described: processing may still be worthwhile, but it will not add resolution.

**The target prints after the verdict, deliberately.** It qualifies the verdict rather than competing
with it, and the two genuinely can point different ways — a 4K container holding 1055p is *worth*
processing for cleanup while gaining no resolution at all. Printed before the verdict, that read as a
contradiction.

## What the real-clip run closed, and what it didn't

**Closed.** This document previously ended by predicting that real footage would test grain,
interlacing, letterboxing and odd containers, and asking whether `--blocking-worth 2.0` would hold on
grainy content. It did not hold — blocking never reached even 1.72 across 113 files, and the bar came
down to 1.5. Container handling was the happier surprise: `wmv3`, `mpeg2video`, ProRes, VFR 4K120 and
mkv-without-`nb_frames` all ran clean with no code changes.

**Still open, and honestly so:**

- **Interlaced content.** The survey found no interlaced files in any of the three collections, so
  that path is still untested. It is the one dimension real footage was supposed to cover and didn't.
- **These thresholds come from one person's library.** 113 files across three collections is a real
  sample, not a universal one. Everything is a flag, and the per-frame data in each `.json` makes a
  recalibration cheap — but a different library could well want different bars.
- **Whether the verdict answers the right question at all.** See "What this did not settle" above.
