import pytest
from app.metrics_engine.speaking_time import SpeakingTimeTracker


def test_initial_state():
    tracker = SpeakingTimeTracker()
    assert tracker.tutor_ratio() == 0.0
    assert tracker.student_ratio() == 0.0
    assert tracker.tutor_seconds == 0.0
    assert tracker.student_seconds == 0.0
    assert tracker.tutor_speaking is False
    assert tracker.student_speaking is False


def test_tutor_only_speaking():
    tracker = SpeakingTimeTracker()
    for i in range(10):
        tracker.update(i * 0.03, tutor_speaking=True, student_speaking=False)
    assert tracker.tutor_ratio() == 1.0
    assert tracker.student_ratio() == 0.0


def test_student_only_speaking():
    tracker = SpeakingTimeTracker()
    for i in range(10):
        tracker.update(i * 0.03, tutor_speaking=False, student_speaking=True)
    assert tracker.tutor_ratio() == 0.0
    assert tracker.student_ratio() == 1.0


def test_equal_speaking():
    tracker = SpeakingTimeTracker()
    # Both speak for same amount of chunks
    for i in range(10):
        tracker.update(i * 0.03, tutor_speaking=True, student_speaking=False)
    for i in range(10):
        tracker.update((10 + i) * 0.03, tutor_speaking=False, student_speaking=True)
    assert abs(tracker.tutor_ratio() - 0.5) < 0.01
    assert abs(tracker.student_ratio() - 0.5) < 0.01


def test_simultaneous_speaking():
    """Both speaking simultaneously should count for both."""
    tracker = SpeakingTimeTracker()
    for i in range(10):
        tracker.update(i * 0.03, tutor_speaking=True, student_speaking=True)
    assert tracker.tutor_seconds > 0
    assert tracker.student_seconds > 0
    assert abs(tracker.tutor_ratio() - 0.5) < 0.01


def test_silence_no_accumulation():
    """Silence should not accumulate speaking time."""
    tracker = SpeakingTimeTracker()
    for i in range(100):
        tracker.update(i * 0.03, tutor_speaking=False, student_speaking=False)
    assert tracker.tutor_seconds == 0.0
    assert tracker.student_seconds == 0.0
    assert tracker.tutor_ratio() == 0.0


def test_custom_chunk_duration():
    tracker = SpeakingTimeTracker()
    tracker.update(0.0, True, False, chunk_duration_s=1.0)
    assert tracker.tutor_seconds == 1.0


def test_ratio_with_70_30_split():
    """Test a typical lecture ratio of 70/30."""
    tracker = SpeakingTimeTracker()
    for i in range(70):
        tracker.update(i * 0.03, tutor_speaking=True, student_speaking=False)
    for i in range(30):
        tracker.update((70 + i) * 0.03, tutor_speaking=False, student_speaking=True)
    assert abs(tracker.tutor_ratio() - 0.7) < 0.01
    assert abs(tracker.student_ratio() - 0.3) < 0.01


def test_student_silence_when_speaking():
    tracker = SpeakingTimeTracker()
    tracker.update(0.0, False, True)
    assert tracker.student_silence_duration(1.0) == 0.0


def test_student_silence_when_not_speaking_after_speech():
    tracker = SpeakingTimeTracker()
    tracker.update(0.0, False, True)
    tracker.update(0.03, False, False)
    assert tracker.student_silence_duration(1.03) == pytest.approx(1.0, abs=0.05)


def test_student_silence_when_never_spoke():
    tracker = SpeakingTimeTracker()
    tracker.update(0.0, False, False)
    assert tracker.student_silence_duration(1.0) == pytest.approx(1.0, abs=0.05)
    assert tracker.time_since_student_spoke(1.0) == pytest.approx(1.0, abs=0.05)


def test_mutual_silence_duration():
    tracker = SpeakingTimeTracker()
    tracker.update(0.0, True, False)
    tracker.update(0.03, False, False)
    assert tracker.mutual_silence_duration(1.03) == pytest.approx(1.0, abs=0.05)


def test_current_tutor_monologue_duration():
    tracker = SpeakingTimeTracker()
    tracker.update(0.0, True, False)
    tracker.update(0.03, True, False)
    assert tracker.current_tutor_monologue_duration(1.03) == pytest.approx(1.03, abs=0.05)


def test_student_response_latency_after_tutor_stops():
    tracker = SpeakingTimeTracker()
    tracker.update(0.0, True, False)
    tracker.update(0.03, False, False)
    tracker.update(0.53, False, True)
    assert tracker.last_student_response_latency_seconds == pytest.approx(0.47, abs=0.1)
    assert tracker.student_turn_count == 1
