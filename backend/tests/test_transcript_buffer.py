"""Tests for TranscriptBuffer."""

from __future__ import annotations

import pytest

from app.transcription.buffer import TranscriptBuffer
from app.transcription.models import FinalUtterance, WordTiming


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _utt(
    role: str = "student",
    text: str = "hello",
    start: float = 0.0,
    end: float = 1.0,
    utterance_id: str = "",
) -> FinalUtterance:
    return FinalUtterance(
        role=role,  # type: ignore[arg-type]
        text=text,
        start_time=start,
        end_time=end,
        utterance_id=utterance_id,
    )


# ---------------------------------------------------------------------------
# Construction
# ---------------------------------------------------------------------------


class TestConstruction:
    def test_default_window(self):
        buf = TranscriptBuffer()
        assert buf.window_seconds == 120.0
        assert len(buf) == 0

    def test_custom_window(self):
        buf = TranscriptBuffer(window_seconds=60.0)
        assert buf.window_seconds == 60.0

    def test_invalid_window(self):
        with pytest.raises(ValueError, match="window_seconds must be > 0"):
            TranscriptBuffer(window_seconds=0)
        with pytest.raises(ValueError, match="window_seconds must be > 0"):
            TranscriptBuffer(window_seconds=-5)


# ---------------------------------------------------------------------------
# Rolling window trimming
# ---------------------------------------------------------------------------


class TestRollingWindow:
    def test_add_and_len(self):
        buf = TranscriptBuffer(window_seconds=10.0)
        buf.add(_utt(end=1.0))
        buf.add(_utt(end=2.0))
        assert len(buf) == 2

    def test_trimming_removes_old(self):
        buf = TranscriptBuffer(window_seconds=5.0)
        buf.add(_utt(text="old", start=0.0, end=1.0))
        buf.add(_utt(text="mid", start=3.0, end=4.0))
        buf.add(_utt(text="new", start=6.0, end=7.0))
        # old (end=1.0) should be trimmed because 7.0 - 5.0 = 2.0 > 1.0
        assert len(buf) == 2
        assert buf.recent_text() == "[Student]: mid\n[Student]: new"

    def test_trim_keeps_boundary(self):
        """Utterances exactly at the window boundary are kept."""
        buf = TranscriptBuffer(window_seconds=5.0)
        buf.add(_utt(text="edge", start=0.0, end=5.0))
        buf.add(_utt(text="new", start=9.0, end=10.0))
        # cutoff = 10.0 - 5.0 = 5.0; edge.end_time == 5.0 → kept (>=)
        assert len(buf) == 2

    def test_trim_all_stale(self):
        buf = TranscriptBuffer(window_seconds=2.0)
        buf.add(_utt(text="a", end=1.0))
        buf.add(_utt(text="b", end=2.0))
        buf.add(_utt(text="c", end=100.0))
        # Both a and b should be trimmed
        assert len(buf) == 1
        assert buf.recent_text() == "[Student]: c"


# ---------------------------------------------------------------------------
# Text formatting
# ---------------------------------------------------------------------------


class TestRecentText:
    def test_empty_buffer(self):
        buf = TranscriptBuffer()
        assert buf.recent_text() == ""

    def test_role_labels(self):
        buf = TranscriptBuffer()
        buf.add(_utt(role="tutor", text="How are you?", end=1.0))
        buf.add(_utt(role="student", text="Good thanks", end=2.0))
        expected = "[Tutor]: How are you?\n[Student]: Good thanks"
        assert buf.recent_text() == expected

    def test_recent_text_with_seconds_filter(self):
        buf = TranscriptBuffer(window_seconds=100.0)
        buf.add(_utt(role="tutor", text="Old question", start=0.0, end=5.0))
        buf.add(_utt(role="student", text="Recent answer", start=90.0, end=95.0))
        buf.add(_utt(role="tutor", text="Follow up", start=95.0, end=100.0))
        # Last 10 seconds: only utterances with end_time >= 90.0
        result = buf.recent_text(seconds=10.0)
        assert "Old question" not in result
        assert "Recent answer" in result
        assert "Follow up" in result


class TestStudentRecentText:
    def test_filters_to_student_only(self):
        buf = TranscriptBuffer()
        buf.add(_utt(role="tutor", text="What is 2+2?", end=1.0))
        buf.add(_utt(role="student", text="Four", end=2.0))
        buf.add(_utt(role="tutor", text="Correct!", end=3.0))
        assert buf.student_recent_text() == "Four"

    def test_empty_when_no_student(self):
        buf = TranscriptBuffer()
        buf.add(_utt(role="tutor", text="Hello", end=1.0))
        assert buf.student_recent_text() == ""


# ---------------------------------------------------------------------------
# Word counts
# ---------------------------------------------------------------------------


class TestWordCount:
    def test_basic_counts(self):
        buf = TranscriptBuffer()
        buf.add(_utt(role="tutor", text="one two three", end=1.0))
        buf.add(_utt(role="student", text="four five", end=2.0))
        counts = buf.word_count_by_role()
        assert counts == {"tutor": 3, "student": 2}

    def test_counts_with_seconds_filter(self):
        buf = TranscriptBuffer(window_seconds=100.0)
        buf.add(_utt(role="tutor", text="old words here", end=5.0))
        buf.add(_utt(role="student", text="recent", end=95.0))
        buf.add(_utt(role="tutor", text="now", end=100.0))
        counts = buf.word_count_by_role(seconds=10.0)
        assert counts == {"tutor": 1, "student": 1}

    def test_empty_buffer(self):
        buf = TranscriptBuffer()
        assert buf.word_count_by_role() == {"tutor": 0, "student": 0}


# ---------------------------------------------------------------------------
# Topic keywords
# ---------------------------------------------------------------------------


class TestTopicKeywords:
    def test_basic_keywords(self):
        buf = TranscriptBuffer()
        buf.add(_utt(role="tutor", text="Let us discuss fractions and decimals", end=1.0))
        buf.add(_utt(role="student", text="I understand fractions but not decimals", end=2.0))
        kws = buf.last_topic_keywords(n=5)
        assert isinstance(kws, list)
        assert len(kws) <= 5
        assert "fractions" in kws
        assert "decimals" in kws

    def test_empty_buffer_returns_empty(self):
        buf = TranscriptBuffer()
        assert buf.last_topic_keywords() == []

    def test_limits_to_n(self):
        buf = TranscriptBuffer()
        buf.add(_utt(
            role="tutor",
            text="algebra geometry calculus trigonometry statistics probability",
            end=1.0,
        ))
        kws = buf.last_topic_keywords(n=3)
        assert len(kws) == 3
