"""Tests for the SPEC.md §8 denominator rule, enforced by srt_verify.py.

The rule is about what the tool *says*, not only what it returns: a zero-cue
or examined-nothing file must exit non-zero AND must not contain pass wording.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from srt_verify import verify_srt  # noqa: E402

FIXTURES = os.path.join(os.path.dirname(__file__), "fixtures")


def fixture(name):
    return os.path.join(FIXTURES, name)


def test_empty_file_examined_nothing():
    result = verify_srt(fixture("empty.srt"), target_lang="en")
    assert result.exit_code == 2
    assert result.cue_count == 0
    assert "pass" not in result.message.lower()
    assert "examined nothing" in result.message.lower()


def test_zero_cues_examined_nothing():
    result = verify_srt(fixture("zero_cues.srt"), target_lang="en")
    assert result.exit_code == 2
    assert result.cue_count == 0
    assert "pass" not in result.message.lower()


def test_music_markers_only_examined_nothing():
    """Four populated cues, but every one of them is a non-speech marker —
    this must fail the same way as zero cues, not report a language pass."""
    result = verify_srt(fixture("music_markers_only.srt"), target_lang="en")
    assert result.cue_count == 4  # the denominator that would fool a naive check
    assert result.scoreable_cue_count == 0
    assert result.exit_code == 2
    assert "pass" not in result.message.lower()
    assert "examined nothing" in result.message.lower()


def test_valid_english_passes():
    result = verify_srt(fixture("valid_english.srt"), target_lang="en")
    assert result.exit_code == 0
    assert result.detected_lang == "en"
    assert result.confidence >= 0.90
    assert result.cue_count == 3
    assert result.scoreable_chars > 0


def test_valid_japanese_passes_when_targeted():
    result = verify_srt(fixture("valid_japanese.srt"), target_lang="ja")
    assert result.exit_code == 0
    assert result.detected_lang == "ja"
    assert result.cjk_ratio > 0.9


def test_japanese_file_fails_english_target():
    """Wrong-language and below-confidence are distinct failures with
    distinct codes — this is the wrong-language case."""
    result = verify_srt(fixture("valid_japanese.srt"), target_lang="en")
    assert result.exit_code == 3
    assert result.detected_lang == "ja"


def test_english_file_fails_japanese_target():
    result = verify_srt(fixture("valid_english.srt"), target_lang="ja")
    assert result.exit_code == 3


def test_missing_file_is_usage_error_not_language_failure():
    result = verify_srt(fixture("does_not_exist.srt"), target_lang="en")
    assert result.exit_code == 1


def test_denominators_reported_on_every_code_path():
    """The rule requires the denominator to be reported on every run, pass
    or fail — check it is present (not None) for every exit code we hit."""
    for name, lang in [
        ("empty.srt", "en"),
        ("zero_cues.srt", "en"),
        ("music_markers_only.srt", "en"),
        ("valid_english.srt", "en"),
        ("valid_japanese.srt", "ja"),
        ("valid_japanese.srt", "en"),
    ]:
        result = verify_srt(fixture(name), target_lang=lang)
        assert result.cue_count is not None
        assert result.scoreable_chars is not None
