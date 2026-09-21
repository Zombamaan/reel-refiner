"""Tests for the SPEC.md §8 denominator rule, enforced by upscale_verify.py,
plus reel_upscale.py's output-path file-safety guard.

Uses synthetic probe dicts rather than real media files — _evaluate() is the
pure decision logic over two already-probed media summaries, kept separate
from verify_upscale()'s file I/O and ffprobe calls precisely so it's
testable without a real video fixture (this repo's samples/ has none — see
docs/SPEC-FEEDBACK.md).
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import reel_upscale  # noqa: E402
from upscale_verify import DEFAULT_DURATION_TOLERANCE, DEFAULT_MAX_RATIO, _evaluate  # noqa: E402


def media(frames=240, duration=10.0, size=1_000_000):
    return dict(duration=duration, frames=frames, bytes=size,
                video_codec="hevc", audio_codec="aac", audio_duration=duration, has_audio=True)


def evaluate(source, output, model="ahq-12", crf=20, max_ratio=DEFAULT_MAX_RATIO,
             duration_tolerance=DEFAULT_DURATION_TOLERANCE):
    return _evaluate("src.mp4", "out.mkv", source, output, model, crf, max_ratio, duration_tolerance)


def test_zero_output_frames_measured_nothing():
    result = evaluate(media(), media(frames=0, duration=0.0, size=0))
    assert result.exit_code == 2
    assert "pass" not in result.message.lower()
    assert "measured nothing" in result.message.lower()


def test_zero_source_is_usage_error_not_a_verdict():
    """A source with no measurable video is a precondition failure, not
    something the ratio/truncation gates should even attempt to judge."""
    result = evaluate(media(frames=0, duration=0.0, size=0), media())
    assert result.exit_code == 1
    assert "pass" not in result.message.lower()


def test_truncated_output_fails_even_with_a_flattering_ratio():
    """A short-but-valid output (5s of a 20s source) has a small size ratio
    that would look like a pass by size alone — duration must catch it."""
    source = media(frames=480, duration=20.0, size=10_000_000)
    output = media(frames=120, duration=5.0, size=1_000_000)  # tiny ratio, badly truncated
    result = evaluate(source, output)
    assert result.exit_code == 3
    assert "pass" not in result.message.lower()
    assert "truncated" in result.message.lower()


def test_ratio_exceeded_fails_distinctly_from_truncation():
    source = media(frames=240, duration=10.0, size=1_000_000)
    output = media(frames=240, duration=10.0, size=60_000_000)  # 60x, full duration
    result = evaluate(source, output)
    assert result.exit_code == 4
    assert "pass" not in result.message.lower()
    assert result.size_ratio == 60.0


def test_healthy_upscale_passes_and_reports_ratio():
    source = media(frames=240, duration=10.0, size=1_000_000)
    output = media(frames=240, duration=10.0, size=3_000_000)  # a plausible 2x upscale
    result = evaluate(source, output)
    assert result.exit_code == 0
    assert result.size_ratio == 3.0
    assert "pass" in result.message.lower()


def test_raised_max_ratio_admits_a_larger_upscale_without_being_a_spurious_pass():
    """--max-ratio's default (5.0) assumes roughly a 2x upscale (4x the
    pixels); a 4x upscale (16x the pixels) can legitimately need more room.
    This confirms the gate is a plain, adjustable threshold — not hardcoded
    to 2x — by failing at the default and passing once raised for the same
    output."""
    source = media(frames=240, duration=10.0, size=1_000_000)
    output = media(frames=240, duration=10.0, size=9_000_000)  # 9x — over the 5x default
    failing = evaluate(source, output, max_ratio=DEFAULT_MAX_RATIO)
    assert failing.exit_code == 4
    passing = evaluate(source, output, max_ratio=12.0)
    assert passing.exit_code == 0


def test_denominators_reported_on_every_code_path():
    """The rule requires the denominator to be reported on every run, pass
    or fail — check it is present (not None) for every exit code we hit."""
    source = media(frames=240, duration=20.0, size=10_000_000)
    outputs = [
        media(frames=0, duration=0.0, size=0),               # -> measured nothing
        media(frames=120, duration=5.0, size=1_000_000),      # -> truncated
        media(frames=480, duration=20.0, size=60_000_000),    # -> ratio exceeded
        media(frames=480, duration=20.0, size=3_000_000),     # -> pass
    ]
    for output in outputs:
        result = evaluate(source, output)
        assert result.source_frames is not None
        assert result.source_duration is not None
        assert result.output_frames is not None
        assert result.output_duration is not None


def test_build_output_path_never_equals_input(tmp_path):
    video = tmp_path / "clip.mp4"
    video.write_bytes(b"fake")
    out_path, is_dev_default = reel_upscale._build_output_path(video, None, "ahq-12", 20, "mkv")
    assert out_path.resolve() != video.resolve()
    assert not is_dev_default


def test_build_output_path_includes_model_and_crf_so_repeat_runs_coexist(tmp_path):
    video = tmp_path / "clip.mp4"
    video.write_bytes(b"fake")
    out_a, _ = reel_upscale._build_output_path(video, None, "ahq-12", 20, "mkv")
    out_b, _ = reel_upscale._build_output_path(video, None, "ahq-12", 23, "mkv")
    out_c, _ = reel_upscale._build_output_path(video, None, "amq-13", 20, "mkv")
    assert len({out_a, out_b, out_c}) == 3


def test_self_overwrite_guard_refuses_a_forced_collision(tmp_path):
    """The guard is defense in depth, not something the naming scheme makes
    reachable in normal use (same as reel_subtitles.py's) — test the
    mechanism directly with a contrived equal path rather than relying on
    the CLI naming scheme to produce one."""
    video = tmp_path / "clip.mp4"
    video.write_bytes(b"fake")
    try:
        reel_upscale._assert_distinct_from_input(video, video)
        assert False, "expected a RuntimeError refusing to overwrite the input"
    except RuntimeError as e:
        assert "refus" in str(e).lower()
