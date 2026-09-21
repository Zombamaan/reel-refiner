# Milestone 2 — upscale wrapper, measured results

The numbers behind SPEC.md §7's upscale must-have and §8's encode-size Class A row. Written down here
for the same reason `docs/MILESTONE-1-RESULTS.md` exists — this is the durable record, not console
output from a session that's already over.

**Build state: built-partial.** The pipe, the CRF encode, audio passthrough, and both denominator-rule
gates (`upscale_verify.py`'s truncation and size-ratio checks) are all proven against real ffmpeg
processes and a real file. What hasn't run is an actual real-world clip — real codecs, interlacing,
unusual pixel formats, multi-track or multi-language audio. See `docs/SPEC-FEEDBACK.md` finding #14
for why (no video clip exists anywhere in this repo's `samples/`) and the "Real clip" section below for
what running one would look like.

## What Topaz's own ffmpeg can and can't do (`docs/SPEC-FEEDBACK.md` finding #10)

Topaz Video AI 7.1.5's bundled `ffmpeg.exe` has **no software H.265/AV1 encoder** — its encoders are
`hevc_nvenc`, `av1_nvenc`, `hevc_qsv`, `av1_qsv`, `hevc_amf`, `av1_amf`, none of which take a true
`-crf`. The only CRF-capable encoder in that binary is `libvpx-vp9`, neither H.265 nor AV1. Confirmed:
`ffmpeg -h encoder=libx265` against Topaz's binary reports *"Codec 'libx265' is not recognized by
FFmpeg."* SPEC.md §9's "one command" is read here as "one invocation of this wrapper," not "one ffmpeg
process" — `reel_upscale.py` runs `tvai_up` in Topaz's ffmpeg piped into a second, system ffmpeg
process (gyan.dev 8.1.2-full, which does carry `libx265`/`libsvtav1`) for the actual CRF encode.

`TVAI_MODEL_DIR` (`docs/SPEC-FEEDBACK.md` finding #11) must be set to
`C:\ProgramData\Topaz Labs LLC\Topaz Video AI\models` or `tvai_up` fails immediately with
`Model not found`, before any GPU work — `reel_upscale.py` sets this itself
(`REEL_TVAI_MODEL_DIR`-overridable). `TVAI_FFMPEG` is pinned explicitly to the 7.1.5 install
(`REEL_TVAI_FFMPEG`-overridable) since a separate, subscription-era "Topaz Video" 1.2.1 install
coexists on this machine and is not the spec'd perpetual version.

## Synthetic degraded clip and command

No video clip exists in `samples/` (finding #14), so this milestone's clip was generated rather than
sourced — recorded as a substitution, not hidden as one:

```
ffmpeg -f lavfi -i testsrc2=size=640x360:rate=24:duration=20 \
       -f lavfi -i sine=frequency=440:duration=20 \
       -c:v libx264 -crf 40 -preset veryfast -vf scale=480:270 \
       -c:a aac -shortest samples/degraded/source.mp4
```

480×270, 24fps, 20s, 480 video frames, mono AAC audio track, **445,543 bytes** — deliberately crushed
(`-crf 40`) to imitate a low-quality web source. `testsrc2` is a synthetic noise-heavy pattern, which
compresses worse than typical real footage at a given CRF; that matters for reading the ratios below —
see "Reading these numbers" at the end.

```
python reel_upscale.py samples/degraded/source.mp4 --model ahq-12 --scale 2 --crf 20
```
(no `--out` needed — the tool detects the sample clip and writes to `out/degraded/` itself, per the
same `samples/`→`out/<clip>/` convention `reel_subtitles.py` uses)

## The §8 encode-size check (`upscale_verify.py`)

| Device | Wall time | Exit | Output size | Ratio vs source | Frames | Duration |
|---|---|---|---|---|---|---|
| auto (GPU) | 6.1s | 4 (ratio exceeded) | 2,430,289 B | 5.45× | 480/480 | 20.00s/20.00s |
| CPU | 121.6s | 4 (ratio exceeded) | 2,429,408 B | 5.45× | 480/480 | 20.00s/20.00s |

Both devices were actually exercised (SPEC.md §4's required CPU fallback). GPU is ~20× faster than CPU
on this clip — a much larger gap than milestone 1's ~6.5× for faster-whisper, consistent with an
upscale model doing much more per-frame work than a speech model does per audio-second.

GPU and CPU produce slightly different output byte counts (2,430,289 vs 2,429,408) on an otherwise
identical command — the same class of minor cross-device nondeterminism milestone 1 recorded for
faster-whisper's float16/int8 paths, not a bug in either.

**Exit 4 here is the `--max-ratio` gate correctly firing, not a tool failure — see "Reading these
numbers" below for why 5.45× exceeds the 5.0× default on this specific synthetic clip.** The pipe, the
encode, and both denominator-rule gates all did their job; `docs/SPEC-FEEDBACK.md` finding #12 records
that no default `--max-ratio` for the gate itself was fixed by the spec either — `5.0` was chosen this
session as "roughly a 2× upscale's worth of headroom," documented in the flag's own `--help` text.

### Truncation gate, exercised independently

A short-but-well-formed 5s clip cut from the 20s output (`ffmpeg -t 5 -c copy`, not a killed process —
a killed process leaves an unfinalized container that fails to probe at all, testing the wrong thing):

```
$ python upscale_verify.py samples/degraded/source.mp4 <5s-cut> --model ahq-12 --crf 20
truncated output: 5.08s vs source 20.00s (tolerance 0.99), 122 vs 480 frames
exit code: 3
```

A flattering size ratio (a 5s file is naturally small) does not save it — duration is checked
independently and catches it. `"pass"` does not appear in the message.

### `--max-ratio` forced low, to confirm the gate actually fires

```
$ python upscale_verify.py samples/degraded/source.mp4 out/degraded/upscaled.ahq-12.crf20.mp4 \
      --model ahq-12 --crf 20 --max-ratio 0.01
size ratio exceeded: 5.45x source (2429408 vs 445543 bytes), max is 0.01x, model=ahq-12 crf=20.0
exit code: 4
```

## Scale sensitivity — `--max-ratio`'s default assumes ~2×, not 4×

A 4× upscale is 16× the pixel count of the source, not 4×. Run at `--scale 4` instead of the default
`--scale 2`, everything else unchanged:

| Scale | Output size | Ratio vs source | Wall time (GPU) |
|---|---|---|---|
| 2× (960×540) | 2,430,289 B | 5.45× | 6.1s |
| 4× (1920×1080) | 6,475,392 B | **14.53×** | 17.5s |

14.53× is a legitimate result of 16× the pixels at the same CRF, not a defect — confirms the advisor's
concern during planning that the 5.0× default would produce a false failure at higher scales. Recorded
here as the number to raise `--max-ratio` against, rather than left as an untested assumption.

## Reading these numbers — the ratio the spec actually cares about

SPEC.md §3/§7's complaint is Topaz's own output being **5–10× larger than necessary**, not larger than
source in absolute terms — an upscale legitimately has more pixels to encode. The comparison that
matters is this wrapper's CRF encode against what Topaz produces with **no quality parameter at all**,
which is the literal mechanism CAPTURE.md's friction #2 describes. Same clip, same `tvai_up` scale=2
pass, piped into Topaz's own documented Windows/NVIDIA H.265 preset
(`models/video-encoders.json`'s `h265-main-win-nvidia`: `-c:v hevc_nvenc -profile:v main -pix_fmt
yuv420p -b_ref_mode disabled -tag:v hvc1 -g 30` — no `-cq`, no `-crf`, nothing):

| Encode | Size | Ratio vs source |
|---|---|---|
| Topaz's own no-quality-parameter NVENC preset | 5,381,098 B | 12.08× |
| This wrapper, `libx265 -crf 20` | 2,430,289 B | 5.45× |

**This wrapper's default is 2.2× smaller than Topaz's own preset for the identical upscale.** Both
numbers are inflated by `testsrc2` being an adversarial, noise-heavy pattern that compresses worse
than typical real footage at any given CRF/quality setting — real footage should land both encodes
lower in absolute terms, likely bringing the wrapper's own ratio comfortably under the 5.0× default
gate on ordinary content. That's exactly the kind of claim this milestone's synthetic clip can't settle
on its own — see "Real clip" below.

## Preflight and the segfault it exists to route around (`docs/SPEC-FEEDBACK.md` finding #15)

A bad `--model` name fails in **0.154s**, before any GPU work — `preflight()`'s point, proven:

```
$ time python reel_upscale.py samples/degraded/source.mp4 --model totally-fake-model --scale 2 --crf 20
RuntimeError: model 'totally-fake-model' not found in C:\ProgramData\Topaz Labs LLC\Topaz Video AI\models
real 0m0.154s
```

Building that check required discovering, by direct probing, that `tvai_up` **segfaults** — not a
clean ffmpeg error, no stderr at all — on fewer than 4 input frames. Bisected on this machine: 1, 2,
and 3 frames all segfault identically (exit 139); 4 and above run cleanly, with a normal, legible
ffmpeg error for a genuinely bad model name at 8 frames. The preflight smoke test uses 8 frames
specifically to stay clear of that threshold with margin. Full writeup in `docs/SPEC-FEEDBACK.md`
finding #15 — recorded as a third GPU/CUDA-adjacent failure signature alongside
`CUBLAS_STATUS_NOT_SUPPORTED` (crashes) and milestone 1's silent 10×-slower-while-claiming-CUDA case
(degrades without error): this one crashes the whole process on a too-short input rather than
reporting "insufficient frames."

## Audio and metadata passthrough (`docs/SPEC-FEEDBACK.md` finding #13)

Neither SPEC.md nor CAPTURE.md says anything about audio handling — a raw video pipe (the only route
to a true CRF encode, per finding #10) carries no audio stream at all, so this had to be designed from
scratch rather than found in the spec. Verified against the output file directly:

| | Source | Output |
|---|---|---|
| Audio codec | aac | aac (unchanged — `-c:a copy`, no re-encode) |
| Audio duration | 20.000000s | 20.000000s (exact match) |

## File safety

Source file's checksum and size confirmed unchanged after every run in this session
(`md5sum samples/degraded/source.mp4`, before and after). Nothing was written into `samples/` at any
point — only `out/degraded/`, per `CLAUDE.md`'s `samples/`→`out/<clip>/` carve-out. A real-clip run
(input outside this repo) was also exercised: output landed next to the input,
`<stem>.upscaled.<model>.crf<N>.<ext>`, never in this repo's `out/` — confirming the same three-branch
rule `reel_subtitles.py` uses.

## Reproducing these numbers

Assumes `.venv/` is set up per `requirements.txt`, Topaz Video AI 7.1.5 is installed at its default
path, and system ffmpeg 8.1.2+ (with `libx265`/`libsvtav1`) is on `PATH` or set via `REEL_FFMPEG`.
`samples/` and `out/` are both git-ignored, so the clip below isn't committed — regenerate it first:

```
mkdir samples/degraded
ffmpeg -f lavfi -i testsrc2=size=640x360:rate=24:duration=20 \
       -f lavfi -i sine=frequency=440:duration=20 \
       -c:v libx264 -crf 40 -preset veryfast -vf scale=480:270 \
       -c:a aac -shortest samples/degraded/source.mp4

python reel_upscale.py samples/degraded/source.mp4 --model ahq-12 --scale 2 --crf 20
python reel_upscale.py samples/degraded/source.mp4 --model ahq-12 --scale 2 --crf 20 --device cpu
python reel_upscale.py samples/degraded/source.mp4 --model ahq-12 --scale 4 --crf 20 --max-ratio 20
```

## Real clip — not yet run

This milestone's synthetic clip proves the mechanism (the pipe, the CRF encode, both gates, audio
passthrough) but not the tool against actual footage. When a real, heavily-compressed clip is
available: `python reel_upscale.py <path> --model <owner's choice> --crf 20`, no `--out` needed for a
real clip either (writes next to the input). Update this document's build state to **built** once
that's run and the "Reading these numbers" caveat above is either confirmed or corrected against real
content.
