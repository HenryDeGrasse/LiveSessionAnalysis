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
