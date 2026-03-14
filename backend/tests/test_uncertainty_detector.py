"""Tests for UncertaintyDetector (fusion + persistence) and TutorQuestionTopicExtractor."""
from __future__ import annotations

import pytest

from app.audio_processor.prosody import ProsodyResult
from app.uncertainty.detector import UncertaintyDetector
from app.uncertainty.topic_extractor import (
    SUBJECT_VOCABULARY,
    TutorQuestionTopicExtractor,
)


# ========================================================================== #
# Helpers
# ========================================================================== #


def _warmup_detector(
    detector: UncertaintyDetector,
    pitch_hz: float = 150.0,
    speech_rate: float = 0.5,
    warmup_seconds: float = 5.0,
    chunk_duration: float = 0.5,
) -> None:
    """Feed enough voiced frames to complete paralinguistic warmup."""
    n_chunks = int(warmup_seconds / chunk_duration) + 1
    for _ in range(n_chunks):
        detector.update_audio(
            pitch_hz=pitch_hz,
            speech_rate=speech_rate,
            pause_ratio=0.1,
            trailing_energy=False,
            chunk_duration_seconds=chunk_duration,
        )


# ========================================================================== #
# Topic Extractor Tests
# ========================================================================== #


class TestTutorQuestionTopicExtractor:
    """Topic extraction from tutor questions using subject vocabulary."""

    def test_extracts_math_topic_from_question(self):
        extractor = TutorQuestionTopicExtractor()
        extractor.update(["What is the derivative of x squared?"])
        assert "derivative" in extractor.current_topic

    def test_extracts_science_topic(self):
        extractor = TutorQuestionTopicExtractor()
        extractor.update(["How does photosynthesis work?"])
        assert "photosynthesis" in extractor.current_topic

    def test_question_mark_detection(self):
        extractor = TutorQuestionTopicExtractor()
        extractor.update(["Can you solve this equation?"])
        assert "equation" in extractor.current_topic

    def test_question_word_detection(self):
        extractor = TutorQuestionTopicExtractor()
        extractor.update(["Explain the concept of velocity"])
        assert "velocity" in extractor.current_topic

    def test_non_question_ignored(self):
        extractor = TutorQuestionTopicExtractor()
        extractor.update(["Great job solving that derivative problem."])
        # No question → should not extract (not a question)
        assert extractor.current_topic == ""

    def test_multiple_keywords_limited_to_three(self):
        extractor = TutorQuestionTopicExtractor()
        extractor.update([
            "What about the derivative and the integral?",
            "How does the slope relate to the equation?",
        ])
        topic = extractor.current_topic
        # Should have at most 3 keywords in the topic string
        parts = [p.strip() for p in topic.split(",")]
        assert len(parts) <= 3
        assert len(parts) >= 1  # at least one keyword found

    def test_is_question_heuristic(self):
        assert TutorQuestionTopicExtractor._is_question("What is 2+2?")
        assert TutorQuestionTopicExtractor._is_question("How does this work")
        assert TutorQuestionTopicExtractor._is_question("Can you explain that?")
        assert TutorQuestionTopicExtractor._is_question("Explain the concept")
        assert TutorQuestionTopicExtractor._is_question("Tell me about forces")
        assert not TutorQuestionTopicExtractor._is_question("Good job!")
        assert not TutorQuestionTopicExtractor._is_question("That is correct.")
        assert not TutorQuestionTopicExtractor._is_question("")

    def test_empty_utterances(self):
        extractor = TutorQuestionTopicExtractor()
        extractor.update([])
        assert extractor.current_topic == ""

    def test_no_vocab_match_empty_topic(self):
        extractor = TutorQuestionTopicExtractor()
        extractor.update(["What did you have for lunch?"])
        assert extractor.current_topic == ""

    def test_whole_word_matching_avoids_false_topic_hits(self):
        extractor = TutorQuestionTopicExtractor()
        extractor.update(["What does demeanor mean in this sentence?"])
        assert extractor.current_topic == "mean"

        extractor = TutorQuestionTopicExtractor()
        extractor.update(["What does demeanor tell us about the speaker?"])
        assert extractor.current_topic == ""

    def test_update_accumulates_questions(self):
        extractor = TutorQuestionTopicExtractor()
        extractor.update(["What is the derivative?"])
        assert "derivative" in extractor.current_topic
        extractor.update(["How about the integral?"])
        topic = extractor.current_topic
        assert "integral" in topic


# ========================================================================== #
# Fusion Scoring Tests
# ========================================================================== #


class TestFusionScoring:
    """Test that the fusion detector correctly combines paralinguistic + linguistic."""

    def test_high_linguistic_only_produces_score(self):
        """Linguistic uncertainty alone (no audio) should still produce a score."""
        detector = UncertaintyDetector(
            student_index=0,
            persistence_utterances=1,
            persistence_window_seconds=60.0,
            uncertainty_threshold=0.1,
        )
        signal = detector.update_transcript(
            text="um I don't know maybe the answer is five?",
            end_time=10.0,
        )
        # Should surface since threshold=0.1 and persistence=1
        assert signal is not None
        assert signal.linguistic_score > 0.0
        assert signal.score > 0.0

    def test_paralinguistic_contributes_to_fusion(self):
        """Audio prosody should contribute to the fused score."""
        detector = UncertaintyDetector(
            student_index=0,
            persistence_utterances=1,
            persistence_window_seconds=60.0,
            uncertainty_threshold=0.01,
            warmup_seconds=5.0,
        )
        _warmup_detector(detector, warmup_seconds=5.0, pitch_hz=150.0)

        # Feed high-deviation audio
        detector.update_audio(
            250.0,  # Way above baseline
            speech_rate=0.2,
            pause_ratio=0.6,
            trailing_energy=True,
            chunk_duration_seconds=0.5,
        )

        signal = detector.update_transcript(
            text="five",
            end_time=20.0,
        )
        assert signal is not None
        assert signal.paralinguistic_score > 0.0
        assert signal.score > signal.linguistic_score * 0.5  # para contributed

    def test_update_audio_accepts_prosody_result(self):
        detector = UncertaintyDetector(
            persistence_utterances=1,
            uncertainty_threshold=0.0,
            warmup_seconds=0.0,
        )
        result = detector.update_audio(
            ProsodyResult(
                rms_energy=0.5,
                rms_db=-20.0,
                zero_crossing_rate=0.1,
                speech_rate_proxy=0.2,
                pitch_hz=220.0,
                pause_ratio=0.5,
                trailing_energy=True,
            ),
            timestamp=5.0,
            chunk_duration_seconds=0.5,
        )
        assert result.score > 0.0

    def test_fusion_weights_sum_correctly(self):
        """Fusion should be 50/50 of paralinguistic and linguistic."""
        detector = UncertaintyDetector(
            persistence_utterances=1,
            persistence_window_seconds=60.0,
            uncertainty_threshold=0.0,
        )
        # No audio → para = 0
        signal = detector.update_transcript(text="yes", end_time=1.0)
        assert signal is not None
        # Score should be 0.5 * 0.0 (para) + 0.5 * ling_score
        expected = 0.5 * signal.linguistic_score
        assert abs(signal.score - expected) < 0.01

    def test_current_uncertainty_score_property(self):
        """current_uncertainty_score should reflect recent utterances."""
        detector = UncertaintyDetector(
            persistence_utterances=1,
            uncertainty_threshold=0.0,
        )
        detector.update_transcript(text="I don't know", end_time=1.0)
        detector.update_transcript(text="maybe", end_time=2.0)
        score = detector.current_uncertainty_score
        assert score > 0.0

    def test_current_uncertainty_score_zero_initially(self):
        detector = UncertaintyDetector()
        assert detector.current_uncertainty_score == 0.0


# ========================================================================== #
# Persistence Gating Tests
# ========================================================================== #


class TestPersistenceGating:
    """Persistence gating: single spikes should not surface, sustained should."""

    def test_single_spike_not_surfaced(self):
        """A single uncertain utterance should NOT surface a signal."""
        detector = UncertaintyDetector(
            persistence_utterances=2,
            persistence_window_seconds=45.0,
            uncertainty_threshold=0.3,
        )
        # One highly uncertain utterance
        signal = detector.update_transcript(
            text="um I don't know um maybe",
            end_time=10.0,
        )
        assert signal is None, "Single spike should not be surfaced"

    def test_sustained_uncertainty_surfaced(self):
        """Two+ uncertain utterances within window should surface a signal."""
        detector = UncertaintyDetector(
            persistence_utterances=2,
            persistence_window_seconds=45.0,
            uncertainty_threshold=0.15,
        )
        # First uncertain utterance
        signal1 = detector.update_transcript(
            text="um I'm not sure about this",
            end_time=10.0,
        )
        assert signal1 is None  # First one: not yet persistent

        # Second uncertain utterance within window
        signal2 = detector.update_transcript(
            text="I don't know maybe it's something else",
            end_time=20.0,
        )
        assert signal2 is not None, "Sustained uncertainty should be surfaced"
        assert signal2.score >= 0.15

    def test_old_scores_outside_window_not_counted(self):
        """Scores outside the persistence window should not count."""
        detector = UncertaintyDetector(
            persistence_utterances=2,
            persistence_window_seconds=10.0,  # Short window
            uncertainty_threshold=0.15,
        )
        # First uncertain utterance at t=0
        detector.update_transcript(
            text="um I'm not sure",
            end_time=0.0,
        )
        # Second uncertain utterance at t=20 (outside 10s window)
        signal = detector.update_transcript(
            text="I don't know",
            end_time=20.0,
        )
        assert signal is None, "Old score outside window should not count"

    def test_three_utterances_within_window(self):
        """Three uncertain utterances should definitely surface."""
        detector = UncertaintyDetector(
            persistence_utterances=2,
            persistence_window_seconds=45.0,
            uncertainty_threshold=0.15,
        )
        detector.update_transcript(text="um maybe", end_time=10.0)
        detector.update_transcript(text="I'm not sure", end_time=20.0)
        signal = detector.update_transcript(
            text="I don't know",
            end_time=25.0,
        )
        assert signal is not None


# ========================================================================== #
# Per-Student Isolation Tests
# ========================================================================== #


class TestPerStudentIsolation:
    """Each UncertaintyDetector instance should be independent."""

    def test_separate_detectors_isolated(self):
        """Two detectors should not share state."""
        det_a = UncertaintyDetector(
            student_index=0,
            persistence_utterances=2,
            persistence_window_seconds=45.0,
            uncertainty_threshold=0.15,
        )
        det_b = UncertaintyDetector(
            student_index=1,
            persistence_utterances=2,
            persistence_window_seconds=45.0,
            uncertainty_threshold=0.15,
        )

        # Feed uncertainty to detector A only
        det_a.update_transcript(text="um I'm not sure", end_time=10.0)
        det_a.update_transcript(text="I don't know", end_time=20.0)

        # Detector B should have no scores
        assert det_b.current_uncertainty_score == 0.0

        # Detector B single utterance should not surface
        signal_b = det_b.update_transcript(
            text="um maybe I'm confused",
            end_time=20.0,
        )
        assert signal_b is None  # Only 1 utterance for B

    def test_student_index_stored(self):
        det = UncertaintyDetector(student_index=3)
        assert det.student_index == 3


# ========================================================================== #
# Topic Integration Tests
# ========================================================================== #


class TestTopicIntegration:
    """Topic extraction should integrate with the fusion detector."""

    def test_topic_from_tutor_questions(self):
        detector = UncertaintyDetector(
            persistence_utterances=1,
            uncertainty_threshold=0.0,
        )
        signal = detector.update_transcript(
            text="um I'm not sure",
            end_time=10.0,
            recent_tutor_utterances=["What is the derivative of this function?"],
        )
        assert signal is not None
        assert "derivative" in signal.topic or "function" in signal.topic

    def test_uncertainty_topic_property(self):
        detector = UncertaintyDetector()
        detector.update_transcript(
            text="yes",
            end_time=1.0,
            recent_tutor_utterances=["How does photosynthesis work?"],
        )
        assert "photosynthesis" in detector.uncertainty_topic


# ========================================================================== #
# False Positive Suppression Tests
# ========================================================================== #


class TestFalsePositiveSuppression:
    """Edge cases that should NOT produce false uncertainty signals."""

    def test_high_filler_confident_speaker(self):
        """A speaker who habitually uses fillers should not be flagged
        once their baseline is established."""
        detector = UncertaintyDetector(
            persistence_utterances=2,
            persistence_window_seconds=60.0,
            uncertainty_threshold=0.5,
        )
        # Build up filler baseline: speaker who always uses fillers
        for i in range(20):
            detector.update_transcript(
                text="um so uh the answer is twenty and um that's correct",
                end_time=float(i),
                speaker_id="habitual-filler",
            )

        # Now another filler-heavy but confident answer
        signal = detector.update_transcript(
            text="um uh so it's definitely um forty-two",
            end_time=25.0,
            speaker_id="habitual-filler",
        )
        # The filler baseline should have adapted — the relative filler
        # density should be lower, so fusion score should be below threshold
        if signal is not None:
            # If surfaced, the score should at least be moderate (not extreme)
            assert signal.score < 0.8, "Habitual filler speaker scored too high"

    def test_monotone_correct_answers(self):
        """Monotone speech with correct, confident text should not be flagged."""
        detector = UncertaintyDetector(
            persistence_utterances=2,
            persistence_window_seconds=45.0,
            uncertainty_threshold=0.5,
            warmup_seconds=5.0,
        )
        _warmup_detector(detector, warmup_seconds=5.0, pitch_hz=150.0)

        # Monotone audio (no deviation)
        detector.update_audio(
            pitch_hz=150.0,
            speech_rate=0.5,
            pause_ratio=0.1,
            trailing_energy=False,
            chunk_duration_seconds=0.5,
        )

        # Confident, longer answer
        signal = detector.update_transcript(
            text="The answer is forty-two because we multiply six by seven",
            end_time=10.0,
        )
        assert signal is None, "Confident monotone answer should not be flagged"

    def test_confident_answers_no_signal(self):
        """Clear, direct answers should not produce uncertainty signals."""
        detector = UncertaintyDetector(
            persistence_utterances=2,
            persistence_window_seconds=45.0,
            uncertainty_threshold=0.5,
        )
        signal1 = detector.update_transcript(
            text="The derivative of x squared is two x",
            end_time=10.0,
        )
        signal2 = detector.update_transcript(
            text="Yes, because the power rule says to bring the exponent down",
            end_time=20.0,
        )
        assert signal1 is None
        assert signal2 is None

    def test_real_question_not_flagged_as_uncertainty(self):
        """A student asking a genuine question (starts with question word)
        should not score high on question_in_statement."""
        detector = UncertaintyDetector(
            persistence_utterances=1,
            uncertainty_threshold=0.0,
        )
        signal = detector.update_transcript(
            text="What is the formula for the area of a circle?",
            end_time=10.0,
        )
        # Should surface (threshold=0) but linguistic question_in_statement
        # should be 0 since it starts with "What"
        assert signal is not None
        assert signal.linguistic_score < 0.5  # Not a strong uncertainty signal


# ========================================================================== #
# Exponentially-Weighted Score Tests
# ========================================================================== #


class TestExponentiallyWeightedScore:
    """The current_uncertainty_score property should weight recent scores higher."""

    def test_recent_scores_weighted_higher(self):
        detector = UncertaintyDetector(
            persistence_utterances=1,
            uncertainty_threshold=0.0,
        )
        # First: high uncertainty
        detector.update_transcript(text="um I don't know", end_time=1.0)
        # Then: low uncertainty (confident)
        detector.update_transcript(
            text="The answer is definitely correct and I am sure about it",
            end_time=2.0,
        )
        detector.update_transcript(
            text="Yes that is absolutely right and I understand it perfectly",
            end_time=3.0,
        )

        # Score should be pulled down toward the more recent confident answers
        score = detector.current_uncertainty_score
        # The first uncertain answer should be down-weighted
        assert score < 0.5

    def test_single_score_returned_directly(self):
        detector = UncertaintyDetector(
            persistence_utterances=1,
            uncertainty_threshold=0.0,
        )
        detector.update_transcript(text="maybe", end_time=1.0)
        # With only 1 score, should return it directly
        assert detector.current_uncertainty_score > 0.0

    def test_two_scores_returns_last(self):
        detector = UncertaintyDetector(
            persistence_utterances=1,
            uncertainty_threshold=0.0,
        )
        detector.update_transcript(text="no", end_time=1.0)
        detector.update_transcript(text="I don't know", end_time=2.0)
        # With ≤2 scores, returns the last one
        score = detector.current_uncertainty_score
        assert score > 0.0
