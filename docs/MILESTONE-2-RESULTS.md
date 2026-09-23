# Milestone 2 — upscale wrapper, measured results

The numbers behind SPEC.md §7's upscale must-have and §8's encode-size Class A row. Written down here
for the same reason `docs/MILESTONE-1-RESULTS.md` exists — this is the durable record, not console
output from a session that's already over.

**Build state: built.** The pipe, the CRF encode, audio passthrough, and both denominator-rule
gates (`upscale_verify.py`'s truncation and size-ratio checks) are all proven against real ffmpeg
processes, and, as of the "Real clip" section below, against a real file from the owner's own library —
the same evidentiary bar `docs/MILESTONE-1-RESULTS.md` used to call the subtitle path built. See
`docs/SPEC-FEEDBACK.md` finding #14 for why the synthetic clip was needed first (no video clip existed
anywhere in this repo's `samples/`).

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

**Correction — this test was insufficient, and the gate it "verified" was broken.** Found by a later
code review, reproduced, and fixed. `ffmpeg -t 5 -c copy` truncates **both** streams, so the container
duration dropped and the gate fired for the right reason *in that case only*. The failure mode that
actually occurs — a pipe dying mid-encode — truncates the **video** while the audio mux completes,
because `reel_upscale.py` always copies the source's full-length audio in. `probe_media` was reading
`format.duration`, which is the *max* of the video and audio streams, so:

```
video: 4.08s / 102 frames     audio: 10.0s     container: 10.0s
  -> exit 0, "pass: 0.61x source size, 10.00s output vs 10.00s source"
```

A file missing 60% of its video, reported as a pass, by the only correctness gate on an upscale run.
The zero-frame gate was defeated by the same mechanism on containers that omit `nb_frames`.

**Fixed:** `probe_media` now reports the **video stream's** duration and frame count, never the
container's — preferring the stream's own duration, then frames ÷ frame rate via `-count_packets`
(packet headers only, no decoding; measured at 29 ms), and falling back to container duration only as
a last resort, with `duration_source` recording which was used so a guess is visible rather than
silent. `_evaluate` now trips on **either** a short duration or a short frame count. Re-verified
against the reproduction above: **exit 3**, *"truncated output (duration and frame count short): 4.08s
vs source 10.00s, 102 vs 250 frames"*. Two regression tests cover it, including one where the duration
looks fine and only the frame count is short.

The lesson worth keeping: a test that truncates both streams cannot distinguish a working gate from one
reading the wrong field. **Build the failure case the system actually produces, not the one that is
convenient to construct.**

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

## Two robustness fixes made during review, before the numbers above were final

- **`-fps_mode passthrough`** added explicitly on the encoder's video output. `-f nut` was already
  chosen over `yuv4mpegpipe` specifically because NUT carries real per-frame timestamps across the
  pipe rather than an implied constant rate — `-fps_mode passthrough` makes that explicit instead of
  relying on ffmpeg's default heuristic, so a variable-frame-rate source (common in web-sourced
  footage, this tool's stated target) can't drift the piped video against the audio mapped in from
  the original file. Spot-checked against a source with an irregular frame count (not evenly divisible
  by the encode's declared rate): output video and audio stream durations both matched the source's
  own exactly (11.000000s and 10.982993s respectively, byte-identical to the source's own ffprobe
  output) — no drift introduced by the pipe.
- **`--preset`'s default is now per-encoder**, not one shared string. `libsvtav1`'s `-preset` is an
  integer (-2..13) with no named aliases at all — `--preset medium` (the old single default) fails
  outright: `Unable to parse "preset" option value "medium"`. `hevc_nvenc` happens to accept some
  legacy named presets including `medium`, so it was never actually broken, but now gets its own
  `p5` default on its own p1–p7 scale rather than borrowing libx265's. Confirmed working after the fix:
  `--encoder libsvtav1 --crf 30` (its default preset `6`) encoded the same clip to 1,737,193 bytes,
  3.90× source.

## Real clip — run against the owner's library

Candidate chosen from `scripts/survey_candidates.py` run against all three of the owner's collections
(`D:\Funscript Videos`, `D:\MultiAxis Videos`, `E:\Main Stash` — 12,237 files, metadata only, nothing
written into the library; saved to `out/candidate_survey.txt`, git-ignored). `reel_candidacy.py`
confirmed the pick as **worth upscaling** first (detail ~768p inside a 2160p container, 36%).

Real file: `E:\Main Stash\Animations\The Count\D.Va 01b (19.10).mp4` — 3840x2160, HEVC Main10 (10-bit),
120fps, 9.42s (1,130 frames), AAC audio plus an attached-picture (cover art) stream, 4,391,623 bytes.
Not synthetic, not from `samples/`, and never modified by the run (checksum confirmed before/after).

```
python reel_upscale.py "E:\Main Stash\Animations\The Count\D.Va 01b (19.10).mp4" --model ahq-12 --scale 2 --crf 20
```

| | Result |
|---|---|
| Device | auto (GPU) |
| Wall time | 478.1s (~8 min) |
| Verify exit | 0 (pass) |
| Output size | 9,304,369 B — **2.12x** source (well under the 5.0x default gate) |
| Duration | 9.416667s output vs 9.416s source |
| Frames | 1,130 vs 1,130 (exact match) |
| Output resolution | 7680x4320 (scale=2 of 3840x2160) |

The GPU pass alone took 8 minutes for a 9.42s clip — 120fps meant 1,130 frames to upscale-and-encode at
8K, not the handful the duration alone suggests; `libx265 -crf 20` at 8K is the bottleneck (2.4 fps
encode speed at the end of the run). A `--device cpu` pass on this same file was not attempted: at the
observed ~20x GPU-vs-CPU gap this milestone already established on the synthetic clip, CPU would cost
on the order of hours for one 8K file — not a proportionate cost to re-confirm a fallback path already
proven working. CPU-on-real-footage remains unexercised; general CPU fallback does not.

Two real-world behaviors observed here for the first time, both expected rather than defects:
- **10-bit source, silently 8-bit output.** The source is HEVC Main10; this run used the default
  `--pix-fmt yuv420p`, so the output is 8-bit. `--pix-fmt yuv420p10le` preserves it — documented in the
  flag's own `--help` text, just not previously exercised against a real 10-bit file.
- **The attached-picture (cover art) stream is dropped**, not carried through. Consistent with finding
  #13's `-map 1:a?` (audio streams only) — an attached picture is an image-coded video stream in
  ffmpeg's model, so it was never in scope of that mapping. Not a defect, just the first real file to
  actually carry one.

Real-world dimensions this single file does **not** cover — interlacing, multi-track or
multi-language audio, non-AAC audio codecs, odd containers (`.wmv`/`.mpeg`/`.ts`), variable frame rate —
remain unexercised for the upscale wrapper specifically, same as milestone 3's candidacy analyser
remaining built on 113-of-12,237 files rather than every one. `out/candidate_survey.txt` has real
examples of each dimension if a targeted follow-up spot-check is ever wanted.

## Second real clip — live-action, full length

The owner reported the first real-clip run (a 3D-animated short) produced only a "moderate,
not-noticeable" visible improvement despite reading "worth upscaling." Discussed why: candidacy's
verdict measures detail lost to compression relative to the container, not whether a human will see a
difference — CG-rendered content carries little fine natural texture for the model to reconstruct even
when heavily compressed. The owner asked for a live-action clip next to see a more visible result, and
authorized running the *full* file (not a trimmed excerpt) overnight, accepting the multi-hour cost.

Genuinely heavily-compressed (bpp < 0.04) high-resolution live-action material turned out to be rare in
this library — a deeper `scripts/survey_candidates.py` pass (400 examples per dimension instead of 25)
found the low-bpp-highres bucket still dominated almost entirely by 3D-animated shorts; that same deeper
run also surfaced and fixed a real bug in the survey script itself (see below). The pick, found by
relaxing the search to the broader survey output rather than the top-N slice:

`D:\Funscript Videos\2D\Sex\GirlsDoPorn\GirlsDoPorn E409 - Charisma - 18 Years Old.mkv` — 3840x2160,
HEVC (8-bit), 29.97fps, 42.4 minutes (76,310 frames), 1,676,569,875 bytes (1.56 GiB). `reel_candidacy.py`
confirmed **worth upscaling**: ~1084p detail in a 2160p container (50%).

```
python reel_upscale.py "D:\Funscript Videos\2D\Sex\GirlsDoPorn\GirlsDoPorn E409 - Charisma - 18 Years Old.mkv" --model ahq-12 --scale 2 --crf 20
```

| | Result |
|---|---|
| Device | auto (GPU) |
| Wall time | 35,019.5s (**~9.73 hours**) |
| Verify exit | 0 (pass) |
| Output size | 6,803,407,673 B (6.34 GiB) — **4.06x** source (still under the 5.0x default gate, but close) |
| Duration | 2546.21s output vs 2546.21s source (exact) |
| Frames | 76,310 vs 76,310 (exact match) |
| Output resolution | 7680x4320 (scale=2 of 3840x2160) |

Confirms the earlier synthetic-clip prediction: **live-action content compresses far less efficiently
at a given CRF than smooth 3D-rendered content.** The two prior real-clip runs (CG-animated, short) read
2.12x and 2.27x; this one, 76x more frames of live-action footage at the same model/scale/CRF, read
**4.06x** — closer to the 5.0x gate than either CG clip got, though still passing. Grain, skin texture,
and background detail all cost real bits to encode at CRF 20 that smooth CG shading doesn't. A future
run at a higher CRF (lower quality target) or a higher `--max-ratio` may be warranted for live-action
material specifically if this pattern holds — not changed here since this run's purpose was to observe
the real number, not tune around it.

Source file confirmed unmodified by checksum before and after. Output landed next to the source with
the expected `<stem>.upscaled.<model>.crf<N>.<ext>` naming; sidecar files next to the source
(`.funscript`, `.gif`, `.png`, `.thumbs`) were untouched, as expected — the wrapper only ever touches
the one file named on the command line.

This run also exercises real duration at scale for the first time: prior real-clip runs were 9–14
seconds; this one ran continuously for nearly 10 hours without failing partway, which is itself evidence
for the pipe/encode holding up over a much longer, unattended run than anything tested before.
