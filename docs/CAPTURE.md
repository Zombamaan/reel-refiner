# Project 3 — Video Processing

**Date:** 2026-09-05
**Batch:** 3 (processing)
**Path / Program:** Path C / Program 5
**Status:** Elicitation complete. Shortest batch.

---

## Two structural findings that predate the questions

**Processing creates variants.** Upscaling produces a second file of the same content at a different
quality — a self-inflicted duplicate landing directly in Program 4's identity model. More usefully:
**your own processing output is a provenance tier**, like curated-pack versus user-upload. Program 5's
outputs must be marked as such so adjudication can distinguish "my upscale" from "someone else's
re-encode."

**Subtitles are sidecars, like scripts.** Replace a video with a better copy and the subtitle must
follow, be renamed, and stay aligned — the same reconciliation problem recorded for scripts in `12_`
and `14_`. Re-encode frame-shift affects subtitles identically. **Misalignment detection is one
capability serving two consumers**, not two features.

---

## Subtitles

### What was done

Once. Described as "quite a hassle." The workflow followed:

1. Capture audio
2. Machine transcription to text
3. Google Translate to English
4. Another LLM to clean up the translation
5. Subtitle Edit to manually match it to the video

### The quality bar

> *"I would be fine with loose translation — the gist of speech is fine for this content."*

**This is the finding.** The workflow above is FunscriptToolbox's *high-quality* path, built around
manual review checkpoints and contextual AI translation. The user does not need that standard. **The
pain was self-inflicted by following a workflow optimised for a quality bar he doesn't require.**

### The replacement

**Corrected 2026-09-07 by pre-work item 7.** The first version of this section named an FFmpeg command
that does not do what it claimed.

Whisper performs speech-to-English in **one pass with timestamps**:

```
whisper "clip.mp4" --model medium --language Japanese --task translate --output_format srt
```

That collapses steps 3, 4 and most of 5.

**FFmpeg 8.0's `whisper` filter cannot do this.** It has no `task` option — its full option set is
`model`, `language`, `queue`, `use_gpu`, `gpu_device`, `destination`, `format` and four `vad_*`
options. It transcribes in the source language only. The earlier claim that
`ffmpeg -af whisper=...:task=translate` produced English subtitles was **wrong**, and the failure would
have looked like success: a populated `.srt` full of Japanese.

It also needs a build with `--enable-whisper` and GGML model files, so a stock FFmpeg likely can't run
it at all.

`whisper-cli` from whisper.cpp would be faster on GPU and should support translation — **verify with
`whisper-cli -h`**.

**P3.1 drops from a project to a one-liner plus a batch wrapper.**

---

## Upscaling

### Current use

Somewhat active, infrequent. Triggered **reactively** — some content exists only in a poor or heavily
compressed version and the user wants it cleaned up. Time-consuming on large videos, so deliberately
targeted.

### Three frictions

| # | Friction | Kind |
|---|---|---|
| 1 | Not knowledgeable on models and compression methods | **Config / knowledge** |
| 2 | Output ends up 5–10× larger; unsure if it could be compressed smaller without quality loss | **Config** |
| 3 | Unsure whether the upscale was worth doing at all | **Trust / evaluation** |

### Topaz licensing — resolved

The user holds a **perpetual licence for Topaz Video AI 7**, the last non-subscription version, with
no preference between Topaz and open source, and openness to paying if the subscription is
substantially better.

- **7.1.5 is the final perpetual-licence version.** Check whether you're on it — free within what you own.
- The current product is a separate, **subscription-only** app: Personal $299/yr, Pro $699/yr.
- Perpetual holders keep their version, frozen. No new models.
- **Adobe has agreed to acquire Topaz Labs in H2 2026.** Transaction pending, no announced changes to
  existing licences. Live uncertainty.
- Topaz remains the quality benchmark for desktop AI upscaling in 2026.

**Recommendation: do not subscribe.** A subscription addresses none of the three frictions above. For a
reactive, infrequent, targeted activity, $299/year buys newer models for a problem the user does not
have.

### The size explosion is a settings issue

Topaz's default output targets high-bitrate intermediate formats. Because it **ships its own FFmpeg
with the `tvai_*` filters**, upscale and sane re-encode can happen in one command — `tvai_up` into
H.265 or AV1 at a chosen CRF. **This is the single highest-value fix in this batch after the subtitle
one-liner**, and it is knowledge, not capability.

---

## Candidacy vs result — the sixth instance

**Candidacy is computable, before spending hours.** Whether a source has recoverable detail: is it
genuinely 1080p or a 480p upscale in a 1080p container, how much blocking and banding is present, how
much high-frequency energy survives. For these sources the already-upscaled-once case is common, and
catching it is pure saved time.

**Result quality is not computable.** Upscaling deliberately changes the image, so similarity metrics
against the source measure change rather than improvement. Human eyes required.

Same shape as card triage (loadability vs aesthetics), video dedup (quality vs placement), and script
quality (Class A vs Class B). **Sixth consecutive project.**

---

## Program 5 reframed

> *"Not anywhere officially in the pipeline. Mostly a maintenance task when I feel I have time and
> have some specific targets."*

It is **not** a job orchestrator over the library. It is three small things:

1. **Candidacy analyser** — is this worth upscaling?
2. **Configured wrapper** — model choice plus sane encode settings.
3. **Subtitle batch** — the one-liner, applied to a list.

**Effort class drops below Thin.** Arguably the smallest deliverable in the portfolio.

---

## Must-have vs nice-to-have

**Must**
- Subtitle generation at gist quality, one command
- Upscale wrapper with encode settings that don't inflate output 5–10×
- Candidacy analysis before committing hours

**Nice**
- Batch queue (the activity is targeted, so a queue may never be needed)
- Provenance marking of processed output feeding Program 4

---

## Definition of done

**Two commands the user can run without re-learning anything**, producing subtitles at gist quality
and upscales that don't inflate storage, with a way to know beforehand whether upscaling will help.

---

## Open questions

1. Is the install already on 7.1.5?
2. Which `tvai_*` model suits heavily compressed web sources specifically? Model selection is friction
   #1 and is not answered by this session.
3. Does the candidacy analyser belong in Program 5 or Program 4? It is arguably a library-wide quality
   survey, not a per-job step.
