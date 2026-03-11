import pytest
from app.metrics_engine.energy import EnergyTracker


def test_initial_score():
    """Initial energy should be 0.5 (neutral)."""
    tracker = EnergyTracker()
    assert tracker.score == 0.5


def test_high_rms_increases_score():
    """High RMS energy should increase score above baseline."""
    tracker = EnergyTracker()
    for _ in range(5):
        tracker.update_audio(rms_energy=0.8, speech_rate_proxy=0.5)
    assert tracker.score > 0.3  # Should be meaningfully above zero


def test_zero_rms_low_score():
    """Zero RMS should result in low score (only expression contributes)."""
    tracker = EnergyTracker()
    tracker.update_expression(0.0)
    for _ in range(5):
        tracker.update_audio(rms_energy=0.0, speech_rate_proxy=0.0)
    assert tracker.score < 0.1


def test_score_in_range():
    """Score should always be in [0, 1]."""
    tracker = EnergyTracker()
    for rms in [0.0, 0.1, 0.5, 0.8, 1.0]:
        tracker.update_audio(rms, 0.5)
        assert 0.0 <= tracker.score <= 1.0


def test_expression_contributes():
    """Expression valence should contribute to the score."""
    low = EnergyTracker()
    high = EnergyTracker()

    for _ in range(5):
        low.update_audio(0.5, 0.5)
        high.update_audio(0.5, 0.5)

    low.update_expression(0.0)
    high.update_expression(1.0)

    assert high.score > low.score


def test_variable_speech_rate():
    """Variable speech rate should contribute more than constant."""
    constant = EnergyTracker()
    variable = EnergyTracker()

    # Constant speech rate
    for _ in range(10):
        constant.update_audio(0.5, 0.5)

    # Variable speech rate
    for i in range(10):
        variable.update_audio(0.5, 0.1 if i % 2 == 0 else 0.9)

    assert variable.score >= constant.score


def test_session_average():
    tracker = EnergyTracker()
    tracker.update_audio(0.5, 0.5)
    avg = tracker.session_average
    assert isinstance(avg, float)
    assert 0.0 <= avg <= 1.0


class TestEnergyCalibration:
    """Verify the dB-scale recalibration produces sensible energy scores
    for real-world conversational audio levels."""

    def test_conversational_rms_produces_moderate_energy(self):
        """Normal conversational speech (RMS ~0.03-0.15) should produce
        energy in the 0.4-0.8 range, not squashed near zero."""
        tracker = EnergyTracker()
        # Simulate normal conversation: RMS ~0.08, moderate speech rate variation
        for i in range(15):
            tracker.update_audio(
                rms_energy=0.08,
                speech_rate_proxy=0.3 + (0.1 if i % 3 == 0 else 0.0),
            )
        assert tracker.score >= 0.35, (
            f"Conversational RMS ~0.08 should produce energy >= 0.35, got {tracker.score:.3f}"
        )
        assert tracker.score <= 0.85

    def test_quiet_speech_above_silence(self):
        """Quiet but present speech (RMS ~0.02) should be clearly above
        the silent baseline."""
        quiet = EnergyTracker()
        quiet.update_expression(0.5)
        for _ in range(10):
            quiet.update_audio(rms_energy=0.02, speech_rate_proxy=0.2)

        silent = EnergyTracker()
        silent.update_expression(0.5)
        for _ in range(10):
            silent.update_audio(rms_energy=0.0, speech_rate_proxy=0.0)

        assert quiet.score > silent.score + 0.1, (
            f"Quiet speech ({quiet.score:.3f}) should be noticeably above silence ({silent.score:.3f})"
        )

    def test_loud_speech_high_energy(self):
        """Loud, animated speech (RMS ~0.3+) should produce energy > 0.7."""
        tracker = EnergyTracker()
        tracker.update_expression(0.7)
        for i in range(15):
            tracker.update_audio(
                rms_energy=0.35,
                speech_rate_proxy=0.4 + (0.3 if i % 2 == 0 else 0.0),
            )
        assert tracker.score >= 0.65, (
            f"Loud speech should produce energy >= 0.65, got {tracker.score:.3f}"
        )

    def test_rms_to_db_score_mapping(self):
        """Spot-check the static dB mapping function."""
        # Silence → 0
        assert EnergyTracker._rms_to_db_score(0.0) == 0.0
        # Very quiet (RMS 0.001 → ~-60dB) → near 0
        assert EnergyTracker._rms_to_db_score(0.001) < 0.1
        # Conversational (RMS 0.05 → ~-26dB) → mid-range
        mid = EnergyTracker._rms_to_db_score(0.05)
        assert 0.3 <= mid <= 0.7, f"RMS 0.05 maps to {mid:.3f}, expected 0.3–0.7"
        # Loud (RMS 0.3 → ~-10.5dB) → near 1.0
        loud = EnergyTracker._rms_to_db_score(0.3)
        assert loud >= 0.9, f"RMS 0.3 maps to {loud:.3f}, expected >= 0.9"
