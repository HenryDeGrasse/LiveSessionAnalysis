import pytest
from app.metrics_engine.attention_drift import AttentionDriftDetector


def test_initial_state():
    detector = AttentionDriftDetector()
    assert detector.is_drifting is False
    assert detector.trend() == "stable"


def test_stable_engagement():
    """Constant engagement should not trigger drift."""
    detector = AttentionDriftDetector(window_seconds=60, slope_threshold=-0.2)
    for i in range(20):
        detector.update(i * 3.0, 0.7)  # Stable at 0.7
    assert detector.is_drifting is False
    assert detector.trend() == "stable"


def test_declining_engagement():
    """Steadily declining engagement should trigger drift."""
    detector = AttentionDriftDetector(window_seconds=60, slope_threshold=-0.002)
    for i in range(20):
        score = 0.8 - i * 0.03  # Drops from 0.8 to ~0.2
        detector.update(i * 3.0, score)
    assert detector.is_drifting is True
    assert detector.trend() == "declining"


def test_rising_engagement():
    """Rising engagement should not trigger drift."""
    detector = AttentionDriftDetector(window_seconds=60, slope_threshold=-0.002)
    for i in range(20):
        score = 0.3 + i * 0.03  # Rises from 0.3 to ~0.9
        detector.update(i * 3.0, score)
    assert detector.is_drifting is False
    assert detector.trend() == "rising"


def test_too_few_samples():
    """With fewer than 5 samples, should not detect drift."""
    detector = AttentionDriftDetector()
    for i in range(3):
        detector.update(i * 3.0, 0.8 - i * 0.3)  # Sharp drop
    assert detector.is_drifting is False
    assert detector.trend() == "stable"


def test_window_pruning():
    """Old samples should be pruned from the window."""
    detector = AttentionDriftDetector(window_seconds=10, slope_threshold=-0.002)
    # Add stable data at t=0..9
    for i in range(10):
        detector.update(float(i), 0.7)
    # Add declining data at t=50..60 (old data should be pruned)
    for i in range(10):
        detector.update(50.0 + i, 0.7 - i * 0.05)
    # Should only see the declining portion
    assert detector.is_drifting is True


def test_recovery_after_drift():
    """Drift should stop when engagement recovers."""
    detector = AttentionDriftDetector(window_seconds=30, slope_threshold=-0.002)
    # Decline
    for i in range(10):
        detector.update(float(i), 0.8 - i * 0.05)
    assert detector.is_drifting is True

    # Recovery at later timestamps (old decline gets pruned)
    for i in range(15):
        detector.update(50.0 + float(i), 0.3 + i * 0.04)
    assert detector.is_drifting is False
