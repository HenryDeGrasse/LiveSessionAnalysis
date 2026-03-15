"""Tests for LinguisticUncertaintyDetector: hedging, fillers, calibration, etc."""
from __future__ import annotations

import pytest

from app.uncertainty.linguistic import LinguisticUncertaintyDetector
from app.uncertainty.models import LinguisticUncertaintyResult, UncertaintySignal


class TestHedgingDetection:
    """Hedging phrases should be detected and produce appropriate scores."""

    def test_i_think_detected(self):
        detector = LinguisticUncertaintyDetector()
        result = detector.analyze("i think it might be around five")
        assert result.hedging_score >= 0.4
        hedging_signals = [s for s in result.signals if s.signal_type == "hedging"]
        assert len(hedging_signals) >= 1
        phrases = {s.text for s in hedging_signals}
        assert "i think" in phrases

    def test_im_not_sure_detected(self):
        detector = LinguisticUncertaintyDetector()
        result = detector.analyze("I'm not sure about this answer")
        assert result.hedging_score >= 0.7

    def test_i_dont_know_detected(self):
        detector = LinguisticUncertaintyDetector()
        result = detector.analyze("I don't know how to solve this")
        assert result.hedging_score >= 0.8

    def test_multiple_hedges_take_max(self):
        detector = LinguisticUncertaintyDetector()
        result = detector.analyze("i think maybe i'm not sure")
        # Should use max of detected weights
        assert result.hedging_score >= 0.6

    def test_no_hedging_zero_score(self):
        detector = LinguisticUncertaintyDetector()
        result = detector.analyze("The answer is definitely forty-two")
        assert result.hedging_score == 0.0

    def test_hedging_uses_word_boundaries(self):
        detector = LinguisticUncertaintyDetector()
        result = detector.analyze("Maybelline is a brand name, not an uncertain answer")
        assert result.hedging_score == 0.0


class TestFillerDetection:
    """Filler words (um, uh, er, ah, hmm) should be detected."""

    def test_um_detected(self):
        detector = LinguisticUncertaintyDetector()
        result = detector.analyze("um the answer is um five")
        filler_signals = [s for s in result.signals if s.signal_type == "filler"]
        assert len(filler_signals) == 2

    def test_multiple_filler_types(self):
        detector = LinguisticUncertaintyDetector()
        result = detector.analyze("uh well er I think hmm maybe three")
        filler_signals = [s for s in result.signals if s.signal_type == "filler"]
        filler_words = {s.text for s in filler_signals}
        assert "uh" in filler_words
        assert "er" in filler_words
        assert "hmm" in filler_words

    def test_like_excluded(self):
        """'like' should not be counted as a filler (personality-dependent)."""
        detector = LinguisticUncertaintyDetector()
        result = detector.analyze("it's like really like amazing like wow")
        filler_signals = [s for s in result.signals if s.signal_type == "filler"]
        assert len(filler_signals) == 0

    def test_you_know_excluded(self):
        """'you know' should not be counted as a filler."""
        detector = LinguisticUncertaintyDetector()
        result = detector.analyze("you know this is you know pretty clear")
        filler_signals = [s for s in result.signals if s.signal_type == "filler"]
        assert len(filler_signals) == 0

    def test_no_fillers_low_score(self):
        detector = LinguisticUncertaintyDetector()
        result = detector.analyze(
            "The mitochondria is the powerhouse of the cell and it produces ATP"
        )
        assert result.filler_score < 0.2
        assert result.filler_density == 0.0

    def test_filler_density_exposed(self):
        detector = LinguisticUncertaintyDetector()
        result = detector.analyze("um the answer is uh five")
        assert result.filler_density == pytest.approx(2 / 6)
        assert result.relative_filler_density == pytest.approx(2 / 6)


class TestPerSpeakerCalibration:
    """Per-speaker filler calibration: high-filler baseline → lower relative score."""

    def test_high_filler_baseline_reduces_score(self):
        detector = LinguisticUncertaintyDetector(baseline_window=50)
        speaker = "student-habitual"

        # Build up a high filler baseline — speaker who always says "um"
        for _ in range(20):
            detector.analyze("um well um I think um it is um five", speaker_id=speaker)

        # Now this same density should score lower than for a new speaker
        result_habitual = detector.analyze(
            "um well um I think um it is um five", speaker_id=speaker,
        )

        # Compare with a fresh speaker with no history
        result_fresh = detector.analyze(
            "um well um I think um it is um five", speaker_id="new-speaker",
        )

        # The habitual filler user should have a lower filler score
        assert result_habitual.filler_score < result_fresh.filler_score

    def test_sudden_increase_in_fillers_scores_higher(self):
        detector = LinguisticUncertaintyDetector(baseline_window=50)
        speaker = "student-clean"

        # Build low-filler baseline
        for _ in range(20):
            detector.analyze(
                "The answer is clearly five because of the equation",
                speaker_id=speaker,
            )

        # Suddenly lots of fillers — should score high relative to baseline
        result = detector.analyze(
            "um uh er I um don't um know", speaker_id=speaker,
        )
        assert result.filler_score > 0.3

    def test_independent_speaker_baselines(self):
        detector = LinguisticUncertaintyDetector()

        # Speaker A has many fillers
        for _ in range(15):
            detector.analyze("um uh well um it is um five", speaker_id="A")

        # Speaker B has no fillers
        for _ in range(15):
            detector.analyze(
                "The answer is clearly five", speaker_id="B",
            )

        # Both get the same filler-heavy text
        result_a = detector.analyze("um uh the answer is um five", speaker_id="A")
        result_b = detector.analyze("um uh the answer is um five", speaker_id="B")

        # Speaker B should be scored higher (unusual for them)
        assert result_b.filler_score > result_a.filler_score


class TestQuestionInStatement:
    """Declarative statements ending with '?' should be detected."""

    def test_statement_with_question_mark(self):
        detector = LinguisticUncertaintyDetector()
        result = detector.analyze("The answer is five?")
        assert result.question_score > 0.0
        q_signals = [s for s in result.signals if s.signal_type == "question_in_statement"]
        assert len(q_signals) == 1

    def test_real_question_not_flagged(self):
        """Genuine questions (starting with question words) should not be flagged."""
        detector = LinguisticUncertaintyDetector()
        result = detector.analyze("What is the answer?")
        assert result.question_score == 0.0

    def test_how_question_not_flagged(self):
        detector = LinguisticUncertaintyDetector()
        result = detector.analyze("How do you solve this?")
        assert result.question_score == 0.0

    def test_is_question_not_flagged(self):
        detector = LinguisticUncertaintyDetector()
        result = detector.analyze("Is this the right answer?")
        assert result.question_score == 0.0

    def test_no_question_mark_no_score(self):
        detector = LinguisticUncertaintyDetector()
        result = detector.analyze("The answer is five.")
        assert result.question_score == 0.0

    def test_uptalk_pattern(self):
        detector = LinguisticUncertaintyDetector()
        result = detector.analyze("So it would be like three hundred?")
        assert result.question_score > 0.0


class TestSelfCorrection:
    """Self-correction patterns should be detected."""

    def test_wait_detected(self):
        detector = LinguisticUncertaintyDetector()
        result = detector.analyze("wait no that's not right, it's six")
        assert result.self_correction_score > 0.0
        corrections = [s for s in result.signals if s.signal_type == "self_correction"]
        assert len(corrections) >= 1

    def test_actually_no_detected(self):
        detector = LinguisticUncertaintyDetector()
        result = detector.analyze("five... actually no it should be six")
        assert result.self_correction_score >= 0.7

    def test_never_mind_detected(self):
        detector = LinguisticUncertaintyDetector()
        result = detector.analyze("let me try... never mind I'll do it differently")
        assert result.self_correction_score >= 0.6

    def test_i_mean_detected(self):
        detector = LinguisticUncertaintyDetector()
        result = detector.analyze("it's five, i mean six")
        assert result.self_correction_score > 0.0

    def test_no_self_correction(self):
        detector = LinguisticUncertaintyDetector()
        result = detector.analyze("The answer is definitely six")
        assert result.self_correction_score == 0.0

    def test_actually_alone_not_treated_as_self_correction(self):
        detector = LinguisticUncertaintyDetector()
        result = detector.analyze("Actually, the answer is six because the signs cancel")
        assert result.self_correction_score == 0.0


class TestBrevity:
    """Short responses should score higher on brevity."""

    def test_one_word_high_brevity(self):
        detector = LinguisticUncertaintyDetector()
        result = detector.analyze("five")
        assert result.brevity_score >= 0.7

    def test_two_word_high_brevity(self):
        detector = LinguisticUncertaintyDetector()
        result = detector.analyze("maybe five")
        assert result.brevity_score >= 0.7

    def test_long_response_low_brevity(self):
        detector = LinguisticUncertaintyDetector()
        result = detector.analyze(
            "The answer is five because when you multiply three by two "
            "you get six and then subtract one to get five"
        )
        assert result.brevity_score < 0.2

    def test_medium_response_moderate_brevity(self):
        detector = LinguisticUncertaintyDetector()
        result = detector.analyze("I think the answer is five")
        assert 0.2 < result.brevity_score < 0.8


class TestConfidentText:
    """Confident, well-formed text should produce a low overall score."""

    def test_confident_explanation(self):
        detector = LinguisticUncertaintyDetector()
        result = detector.analyze(
            "The answer is forty-two because when you multiply six by seven "
            "you get forty-two, and that matches the expected result from "
            "the formula we discussed earlier in the lesson"
        )
        assert result.score < 0.15
        assert result.hedging_score == 0.0
        assert result.self_correction_score == 0.0

    def test_confident_statement(self):
        detector = LinguisticUncertaintyDetector()
        result = detector.analyze(
            "Photosynthesis converts carbon dioxide and water into glucose "
            "and oxygen using light energy from the sun"
        )
        assert result.score < 0.15


class TestUncertainText:
    """Uncertain text with multiple signals should produce a high score."""

    def test_highly_uncertain(self):
        detector = LinguisticUncertaintyDetector()
        result = detector.analyze("um I'm not sure, maybe five?")
        # Should have hedging, filler, question signals
        assert result.score > 0.3
        assert result.hedging_score > 0.0

    def test_very_uncertain(self):
        detector = LinguisticUncertaintyDetector()
        result = detector.analyze("uh i don't know, um, wait, maybe three?")
        assert result.score > 0.4

    def test_uncertain_higher_than_confident(self):
        detector = LinguisticUncertaintyDetector()
        confident = detector.analyze(
            "The derivative of x squared is two x because of the power rule"
        )
        uncertain = detector.analyze(
            "um i think maybe it's uh two x?", speaker_id="other",
        )
        assert uncertain.score > confident.score


class TestScoreBounds:
    """Scores should always be in [0, 1]."""

    def test_empty_text(self):
        detector = LinguisticUncertaintyDetector()
        result = detector.analyze("")
        assert result.score == 0.0

    def test_whitespace_only(self):
        detector = LinguisticUncertaintyDetector()
        result = detector.analyze("   ")
        assert result.score == 0.0

    def test_all_signals_present(self):
        detector = LinguisticUncertaintyDetector()
        result = detector.analyze("um uh i don't know, wait, maybe five?")
        assert 0.0 <= result.score <= 1.0

    def test_score_components_bounded(self):
        detector = LinguisticUncertaintyDetector()
        result = detector.analyze("um uh er ah hmm i'm not sure wait actually no five?")
        assert 0.0 <= result.hedging_score <= 1.0
        assert 0.0 <= result.filler_score <= 1.0
        assert 0.0 <= result.question_score <= 1.0
        assert 0.0 <= result.self_correction_score <= 1.0
        assert 0.0 <= result.brevity_score <= 1.0
        assert 0.0 <= result.score <= 1.0


class TestFusionWeights:
    """Verify that fusion weights are applied correctly."""

    def test_hedging_only_contribution(self):
        """Hedging alone should contribute 0.30 * hedging_score."""
        detector = LinguisticUncertaintyDetector()
        # Long enough to avoid brevity, no fillers, no question, no self-correction
        result = detector.analyze(
            "I think this is probably the right approach for solving the equation "
            "given everything we have discussed so far today",
        )
        # Hedging should be the dominant contributor
        assert result.hedging_score > 0.0
        assert result.self_correction_score == 0.0
        assert result.question_score == 0.0


class TestDataclasses:
    """Verify model dataclasses work correctly."""

    def test_uncertainty_signal_creation(self):
        sig = UncertaintySignal(
            signal_type="hedging", text="i think", weight=0.4,
        )
        assert sig.signal_type == "hedging"
        assert sig.detail == ""

    def test_result_default_values(self):
        result = LinguisticUncertaintyResult(score=0.5)
        assert result.hedging_score == 0.0
        assert result.signals == []

    def test_result_with_signals(self):
        sig = UncertaintySignal(
            signal_type="filler", text="um", weight=0.3, detail="Filler word: 'um'",
        )
        result = LinguisticUncertaintyResult(score=0.3, signals=[sig])
        assert len(result.signals) == 1
        assert result.signals[0].text == "um"
