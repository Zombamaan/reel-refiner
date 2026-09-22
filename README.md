# Reel Refiner

Three small, independently runnable maintenance tools for staged video. Invoked manually, one file at
a time — no queue, no scheduler, no shared state between them.

| Tool | Answers |
|---|---|
| `reel_candidacy.py` | *Is this worth upscaling at all?* — run it **first** |
| `reel_upscale.py` | Upscale via Topaz, without the 5–10× file-size blowup |
| `reel_subtitles.py` | Non-English clip → verified-English `.srt`, one command |

Full specification: `docs/SPEC.md`. What building these found wrong with it: `docs/SPEC-FEEDBACK.md`.

## Setup

```
.venv\Scripts\activate
pip install -r requirements.txt
```

Needs Python 3.12 (not 3.14 — its only torch wheel here is CPU-only), a system **ffmpeg 8.x** with
`libx265` on `PATH`, and for upscaling, **Topaz Video AI 7.1.5** installed. The tools find Topaz and
set its environment themselves. Overrides if anything lives somewhere unusual: `REEL_FFMPEG`,
`REEL_FFPROBE`, `REEL_TVAI_FFMPEG`, `REEL_TVAI_MODEL_DIR`.

## The usual workflow

```bash
# 1. Is it worth the hours?
python reel_candidacy.py clip.mp4

# 2. If so, upscale it. --model is yours to choose and is never inferred.
python reel_upscale.py clip.mp4 --model ahq-12 --scale 2 --crf 20

# 3. Subtitles, if the source isn't English
python reel_subtitles.py clip.mp4 --language ja
```

Steps 1 and 2 chain, because the candidacy analyser's exit code *is* its verdict:

```bash
python reel_candidacy.py clip.mp4 && python reel_upscale.py clip.mp4 --model ahq-12
```

## Reading the exit codes

**The candidacy analyser is the odd one out** — its exit code reports the *verdict*, so a non-zero
result usually means "the answer was no," not "the tool broke":

```
0  worth upscaling      2  sampled no usable frames — BROKEN
1  usage / IO error     3  marginal        4  not worth upscaling
```

For the other two, non-zero means the output they produced is not good: `0` pass, `1` usage/IO error,
`2` examined nothing, `3` and `4` for the specific failure (wrong language / below confidence;
truncated output / size ratio exceeded).

`2` always means the same thing everywhere: **it measured nothing**, which is a breakage, never a
clean bill of health.

## One caveat worth knowing before you trust a result

`reel_candidacy.py` measures **how much real detail a file carries relative to its container**. On
synthetic ground truth it recovers a known band-limit to within 3%.

What it **cannot** do is tell you a file was upscaled before. Tested across 113 real files — 31 of
them marked as prior upscales — the two groups overlap almost entirely, and which reads higher flips
depending on the subsample. AI upscalers synthesize genuine high-frequency detail, which is exactly
what the test looks for.

So a clean reading is **not** evidence the source was never upscaled. The tool prints this on every
run. Detail: `docs/SPEC-FEEDBACK.md` finding #16 and `docs/MILESTONE-3-RESULTS.md`.

## Where output goes

Next to the input you named, with a distinct name — never over your source, never moved or renamed:

```
clip.mp4  ->  clip.en.srt
              clip.upscaled.ahq-12.crf20.mp4
              clip.candidacy.txt   clip.candidacy.json
```

`--out <dir>` overrides. Clips under this repo's own `samples/` are the one exception: their output
goes to `out/<clip>/` instead, so dev/test material never gets written into.

## Tuning without re-running

Every threshold is a flag, and defaults are annotated in `--help` with the measurement behind them —
all calibrated against 113 real files, not synthetic sources. Banding reports but does not gate by
default; pass `--banding-worth` a number to re-enable it.
The candidacy analyser saves per-frame data, so you can re-verdict a saved report against different
bars without decoding the video again:

```bash
python candidacy_verify.py clip.candidacy.json --blocking-worth 3.0
```

The other two check modules run standalone the same way — `srt_verify.py` on any `.srt`,
`upscale_verify.py` on a source/output pair.

## Tests

```
python -m pytest tests/ -q
```

## Where the numbers come from

Measured results, with the ground truth behind every default, live in `docs/MILESTONE-1-RESULTS.md`
(subtitles), `-2-` (upscale) and `-3-` (candidacy). `docs/CAPTURE.md` is the elicitation record the
spec was written from — read it when you want to know *why* something is the way it is.

**Build state:** subtitles **built**; candidacy **built** (113 real files, three collections, zero
failures); upscale wrapper **built-partial** — it works end to end but has only met synthetic clips.
See `docs/SPEC.md` §12.
