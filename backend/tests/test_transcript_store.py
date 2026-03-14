"""Tests for TranscriptStore."""

from __future__ import annotations

import pytest

from app.transcription.store import TranscriptStore
from app.transcription.models import FinalUtterance, WordTiming


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _utt(
    role: str = "student",
    text: str = "hello",
    start: float = 0.0,
    end: float = 1.0,
    utterance_id: str = "u1",
    words: list[WordTiming] | None = None,
) -> FinalUtterance:
    return FinalUtterance(
        role=role,  # type: ignore[arg-type]
        text=text,
        start_time=start,
        end_time=end,
        utterance_id=utterance_id,
        words=words or [],
    )


def _words(text: str) -> list[WordTiming]:
    """Create simple WordTiming list from text."""
    result = []
    t = 0.0
    for w in text.split():
        result.append(WordTiming(word=w, start=t, end=t + 0.3, confidence=0.99))
        t += 0.4
    return result


# ---------------------------------------------------------------------------
# Construction & add
# ---------------------------------------------------------------------------


class TestConstruction:
    def test_empty_store(self):
        store = TranscriptStore(session_id="sess-1")
        assert len(store) == 0
        assert store.utterances == []

    def test_add_utterances(self):
        store = TranscriptStore(session_id="sess-1")
        store.add(_utt(text="hello", utterance_id="u1"))
        store.add(_utt(text="world", utterance_id="u2"))
        assert len(store) == 2


# ---------------------------------------------------------------------------
# Key moments
# ---------------------------------------------------------------------------


class TestKeyMoments:
    def test_mark_key_moment(self):
        store = TranscriptStore()
        store.add(_utt(utterance_id="u1"))
        store.mark_key_moment("u1")
        assert "u1" in store.key_moment_ids

    def test_mark_nonexistent_id(self):
        """Marking a non-existent ID is allowed (idempotent flag)."""
        store = TranscriptStore()
        store.mark_key_moment("nope")
        assert "nope" in store.key_moment_ids


# ---------------------------------------------------------------------------
# Postgres payload
# ---------------------------------------------------------------------------


class TestPostgresPayload:
    def test_strips_word_timings_for_non_key_moments(self):
        store = TranscriptStore(session_id="sess-1")
        store.add(_utt(
            text="hello world",
            utterance_id="u1",
            words=_words("hello world"),
        ))
        store.add(_utt(
            text="key insight",
            utterance_id="u2",
            words=_words("key insight"),
        ))
        store.mark_key_moment("u2")

        payload = store.to_postgres_payload()
        assert payload["session_id"] == "sess-1"
        assert len(payload["utterances"]) == 2

        # Non-key moment: words stripped
        u1_dict = payload["utterances"][0]
        assert "words" not in u1_dict

        # Key moment: words preserved
        u2_dict = payload["utterances"][1]
        assert "words" in u2_dict
        assert len(u2_dict["words"]) == 2

    def test_word_count(self):
        store = TranscriptStore(session_id="s")
        store.add(_utt(text="one two three"))
        store.add(_utt(text="four five"))
        payload = store.to_postgres_payload()
        assert payload["word_count"] == 5

    def test_searchable_text(self):
        store = TranscriptStore()
        store.add(_utt(text="hello world"))
        store.add(_utt(text="foo bar"))
        payload = store.to_postgres_payload()
        assert payload["searchable_text"] == "hello world foo bar"


# ---------------------------------------------------------------------------
# S3 artifact
# ---------------------------------------------------------------------------


class TestS3Artifact:
    def test_preserves_all_word_timings(self):
        store = TranscriptStore(session_id="sess-1")
        store.add(_utt(
            text="hello world",
            utterance_id="u1",
            words=_words("hello world"),
        ))
        store.add(_utt(
            text="another one",
            utterance_id="u2",
            words=_words("another one"),
        ))
        # Do NOT mark any key moment
        artifact = store.to_s3_artifact()
        assert artifact["session_id"] == "sess-1"
        # Both should have words
        for u in artifact["utterances"]:
            assert "words" in u
            assert len(u["words"]) == 2

    def test_word_count_matches_postgres(self):
        store = TranscriptStore()
        store.add(_utt(text="a b c"))
        store.add(_utt(text="d"))
        assert store.to_s3_artifact()["word_count"] == store.to_postgres_payload()["word_count"]
        assert store.to_s3_artifact()["word_count"] == 4

    def test_searchable_text(self):
        store = TranscriptStore()
        store.add(_utt(text="alpha beta"))
        artifact = store.to_s3_artifact()
        assert artifact["searchable_text"] == "alpha beta"


# ---------------------------------------------------------------------------
# Key moment preservation in postgres vs s3
# ---------------------------------------------------------------------------


class TestKeyMomentPreservation:
    def test_postgres_strips_non_key_keeps_key(self):
        store = TranscriptStore()
        store.add(_utt(text="normal", utterance_id="a", words=_words("normal")))
        store.add(_utt(text="important", utterance_id="b", words=_words("important")))
        store.add(_utt(text="also normal", utterance_id="c", words=_words("also normal")))
        store.mark_key_moment("b")

        pg = store.to_postgres_payload()
        s3 = store.to_s3_artifact()

        # S3: all have words
        for u in s3["utterances"]:
            assert "words" in u

        # PG: only 'b' has words
        for u in pg["utterances"]:
            if u["utterance_id"] == "b":
                assert "words" in u
                assert len(u["words"]) == 1
            else:
                assert "words" not in u


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


class TestEdgeCases:
    def test_empty_store_payloads(self):
        store = TranscriptStore(session_id="empty")
        pg = store.to_postgres_payload()
        s3 = store.to_s3_artifact()
        assert pg["utterances"] == []
        assert s3["utterances"] == []
        assert pg["word_count"] == 0
        assert s3["word_count"] == 0
        assert pg["searchable_text"] == ""
        assert s3["searchable_text"] == ""

    def test_utterance_with_empty_text(self):
        store = TranscriptStore()
        store.add(_utt(text=""))
        assert store.to_postgres_payload()["word_count"] == 0
        assert store.to_postgres_payload()["searchable_text"] == ""
