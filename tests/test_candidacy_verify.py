"""Tests for SPEC.md §8's candidacy metrics and CLAUDE.md's denominator rule,
enforced by candidacy_verify.py.

Two layers:

1. The maths itself, against numpy arrays built with known properties. This
   repo's samples/ has no video (docs/SPEC-FEEDBACK.md finding #14), but a
   luma plane is just a 2-D array — a stretched source, a quantized gradient
   and an 8px block grid can all be constructed directly, so the metrics get
   real coverage with no fixture.

2. The verdict and the denominator rule, against synthetic per-frame dicts
   fed to the pure _evaluate() — the same shape as test_upscale_verify.py.
"""
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import reel_candidacy  # noqa: E402
from candidacy_verify import (  # noqa: E402
    DEFAULT_FRAMES,
    _evaluate,
    default_thresholds,
    frame_metrics,
)

# ---------------------------------------------------------------- layer 1: the maths


def _detailed(height=256, width=256, seed=0):
    """Full-spectrum content: detail present at every scale."""
    rng = np.random.default_rng(seed)
    return (rng.random((height, width)) * 255).astype(np.uint8)


def _band_limited(ratio, size=256, seed=0):
    """An image with zero spectral energy above `ratio` of Nyquist — what a
    smooth (bicubic/Lanczos) upscale from a smaller source actually leaves
    behind, and what the effective-resolution metric claims to recover."""
    rng = np.random.default_rng(seed)
    spec = np.fft.fftshift(np.fft.fft2(rng.random((size, size))))
    centre = size // 2
    y, x = np.ogrid[:size, :size]
    r = np.maximum(np.abs(y - centre) / (size / 2), np.abs(x - centre) / (size / 2))
    spec[r > ratio] = 0
    img = np.real(np.fft.ifft2(np.fft.ifftshift(spec)))
    img -= img.min()
    peak = img.max()
    if peak:
        img /= peak
    return (img * 255).astype(np.uint8)


def test_detailed_content_reads_as_full_resolution():
    m = frame_metrics(_detailed())
    assert m["usable"]
    assert m["effective_resolution_ratio"] > 0.9


def test_stretched_content_reads_below_container():
    """The headline metric: content band-limited to 30% of Nyquist must not
    claim full resolution."""
    m = frame_metrics(_band_limited(0.30))
    assert m["usable"]
    assert m["effective_resolution_ratio"] < 0.5


def test_effective_resolution_recovers_the_true_cutoff():
    """Not merely monotonic — the reported figure should be the real one,
    since it is printed as '~389p of 1080p' and acted on."""
    for built in (0.20, 0.30, 0.50, 0.70):
        measured = frame_metrics(_band_limited(built))["effective_resolution_ratio"]
        assert abs(measured - built) < 0.03, f"built {built}, measured {measured}"


def test_effective_resolution_is_monotonic_in_the_cutoff():
    r2 = frame_metrics(_band_limited(0.20))["effective_resolution_ratio"]
    r4 = frame_metrics(_band_limited(0.45))["effective_resolution_ratio"]
    r8 = frame_metrics(_band_limited(0.80))["effective_resolution_ratio"]
    assert r2 < r4 < r8


def test_nearest_neighbour_expansion_is_a_known_blind_spot():
    """Recorded as behaviour, not aspiration. Nearest-neighbour replication
    leaves hard square edges whose spectrum is broadband, so it reads as
    full resolution however far it was expanded. Real scalers interpolate
    smoothly and ARE caught (see the ffmpeg ground-truth ladder in
    docs/MILESTONE-3-RESULTS.md); this is the narrower cousin of the
    AI-upscale blind spot in docs/SPEC-FEEDBACK.md finding #16."""
    rng = np.random.default_rng(0)
    small = (rng.random((32, 32)) * 255).astype(np.uint8)
    expanded = np.kron(small, np.ones((8, 8), dtype=np.uint8))
    assert frame_metrics(expanded)["effective_resolution_ratio"] > 0.9


def test_flat_frame_is_unusable_not_clean():
    """A solid frame has no measurable detail — it must be excluded from the
    denominator, not scored as if it were fine."""
    m = frame_metrics(np.full((256, 256), 128, dtype=np.uint8))
    assert m["usable"] is False
    assert m["effective_resolution_ratio"] is None
    assert m["blocking"] is None


def test_banding_near_one_for_a_smooth_ramp():
    ramp = np.tile(np.linspace(0, 255, 256, dtype=np.uint8), (256, 1))
    assert frame_metrics(ramp)["banding"] < 1.5


def test_banding_high_for_a_quantized_ramp():
    """Quantization is what causes banding; few occupied levels over a wide
    span is the signature."""
    ramp = np.tile(np.linspace(0, 255, 256), (256, 1))
    quantized = ((ramp // 52) * 52).astype(np.uint8)  # ~5 distinct levels
    assert frame_metrics(quantized)["banding"] > 5.0


def test_banding_does_not_false_positive_on_detailed_content():
    """The block-based metric this replaced scored 13.0 here — a false
    positive that would have called clean content damaged."""
    assert frame_metrics(_detailed())["banding"] < 2.0


def test_blocking_rises_when_an_8px_grid_is_injected():
    rng = np.random.default_rng(1)
    base = (rng.random((256, 256)) * 40 + 108).astype(np.uint8)
    clean = frame_metrics(base)["blocking"]
    blocky = base.copy().astype(np.int16)
    blocky[:, 7::8] += 60  # a discontinuity on the codec's block boundary
    blocky[7::8, :] += 60
    assert frame_metrics(np.clip(blocky, 0, 255).astype(np.uint8))["blocking"] > clean * 1.5


def test_frame_metrics_rejects_non_2d_input():
    try:
        frame_metrics(np.zeros((16, 16, 3), dtype=np.uint8))
        assert False, "expected ValueError for a 3-D array"
    except ValueError as e:
        assert "2-D" in str(e)


# ------------------------------------------------- layer 2: verdict + denominator rule


def frame(ratio=1.0, blocking=1.0, banding=1.0, hf=1e-3, usable=True):
    return dict(usable=usable, std=40.0, effective_resolution_ratio=ratio,
                blocking=blocking, banding=banding, hf_energy_ratio=hf)


def evaluate(per_frame, width=1920, height=1080, requested=None, **overrides):
    if requested is None:
        requested = len(per_frame)
    return _evaluate("clip.mp4", width, height, requested, per_frame,
                     default_thresholds(**overrides))


def test_stretched_source_is_worth_upscaling():
    r = evaluate([frame(ratio=0.36)] * 5)
    assert r.exit_code == 0
    assert r.verdict == "worth"
    assert r.effective_resolution_px == 389  # 0.36 * 1080


def test_heavy_blocking_alone_is_worth_upscaling():
    """Any one severe signal is enough — honest resolution plus real
    compression damage is still headroom."""
    r = evaluate([frame(blocking=7.4)] * 5)
    assert r.exit_code == 0
    assert r.verdict == "worth"


def test_heavy_banding_alone_is_worth_upscaling():
    r = evaluate([frame(banding=8.1)] * 5)
    assert r.exit_code == 0


def test_clean_honest_source_is_not_worth_upscaling():
    r = evaluate([frame()] * 5)
    assert r.exit_code == 4
    assert r.verdict == "not worth"


def test_mild_damage_is_marginal_and_reachable():
    """The ladder is ordered, so marginal only fires when no severe bar is
    tripped — this is the check that catches an unordered implementation."""
    r = evaluate([frame(blocking=1.7)] * 5)
    assert r.exit_code == 3
    assert r.verdict == "marginal"


def test_severe_bar_wins_over_mild_bar():
    """A file tripping both must read worth (0), never marginal (3)."""
    r = evaluate([frame(ratio=0.30, blocking=1.7)] * 5)
    assert r.exit_code == 0


def test_all_three_exit_codes_are_reachable():
    codes = {
        evaluate([frame(ratio=0.30)] * 3).exit_code,
        evaluate([frame(blocking=1.7)] * 3).exit_code,
        evaluate([frame()] * 3).exit_code,
    }
    assert codes == {0, 3, 4}


def test_zero_usable_frames_is_broken_never_clean():
    """The denominator rule: frames decoded fine but none carried detail."""
    r = evaluate([frame(usable=False)] * 20)
    assert r.exit_code == 2
    assert r.verdict == "broken"
    assert "broken" in r.message.lower()
    assert "no defects" not in r.message.lower()
    assert r.frames_decoded == 20
    assert r.frames_usable == 0


def test_failed_decodes_are_counted_not_fatal():
    """Some frames failed to decode; the rest still produce a verdict, and
    all three tiers are visible."""
    r = evaluate([None, None, frame(ratio=0.30), frame(ratio=0.30)], requested=4)
    assert r.frames_requested == 4
    assert r.frames_decoded == 2
    assert r.frames_usable == 2
    assert r.exit_code == 0


def test_zero_dimensions_is_usage_error_not_a_verdict():
    r = evaluate([frame()] * 3, width=0, height=0)
    assert r.exit_code == 1
    assert r.verdict == "error"


def test_median_not_mean_so_one_outlier_frame_cannot_flip_the_verdict():
    per_frame = [frame()] * 9 + [frame(ratio=0.1, blocking=50.0, banding=50.0)]
    r = evaluate(per_frame)
    assert r.exit_code == 4  # the nine clean frames win


def test_thresholds_are_adjustable_not_hardcoded():
    per_frame = [frame(blocking=1.7)] * 5
    assert evaluate(per_frame).exit_code == 3
    assert evaluate(per_frame, blocking_worth=1.6).exit_code == 0
    assert evaluate(per_frame, blocking_marginal=1.8).exit_code == 4


def test_denominators_and_caveat_reported_on_every_code_path():
    cases = [
        [frame(ratio=0.30)] * 3,       # worth
        [frame(blocking=1.7)] * 3,     # marginal
        [frame()] * 3,                 # not worth
        [frame(usable=False)] * 3,     # broken
    ]
    for per_frame in cases:
        r = evaluate(per_frame)
        assert r.frames_requested is not None
        assert r.frames_decoded is not None
        assert r.frames_usable is not None
        assert r.caveat and "AI upscale" in r.caveat


# ------------------------------------------------------------- sampling + file safety


def test_sample_timestamps_skip_the_edges_and_stay_in_range():
    ts = reel_candidacy.sample_timestamps(100.0, DEFAULT_FRAMES)
    assert len(ts) == DEFAULT_FRAMES
    assert ts[0] >= 5.0 and ts[-1] <= 95.0
    assert ts == sorted(ts)


def test_sample_timestamps_handles_a_very_short_clip():
    assert len(reel_candidacy.sample_timestamps(0.2, 5)) == 5


def test_unknown_duration_yields_one_timestamp_not_n_copies_of_zero():
    """Regression, code review finding #3. Returning [0.0] * count made every
    sample land on frame 0 while the report claimed `count` usable frames —
    a denominator asserting a breadth of sampling that never happened, which
    is the exact failure CLAUDE.md's rule exists to prevent."""
    assert reel_candidacy.sample_timestamps(0.0, 20) == [0.0]


def test_report_paths_never_equal_the_input(tmp_path):
    video = tmp_path / "clip.mp4"
    video.write_bytes(b"fake")
    txt, js, is_dev = reel_candidacy._build_report_paths(video, None)
    assert txt.resolve() != video.resolve()
    assert js.resolve() != video.resolve()
    assert txt.parent == video.parent  # real clip: next to the input
    assert not is_dev


def test_self_overwrite_guard_refuses_a_forced_collision(tmp_path):
    video = tmp_path / "clip.mp4"
    video.write_bytes(b"fake")
    try:
        reel_candidacy._assert_distinct_from_input(video, video)
        assert False, "expected a RuntimeError refusing to overwrite the input"
    except RuntimeError as e:
        assert "refus" in str(e).lower()
