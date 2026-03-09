import pytest
from app.metrics_engine.interruptions import InterruptionTracker
from app.models import Role


def test_initial_state():
    tracker = InterruptionTracker()
    assert tracker.total_count == 0
    assert tracker.hard_count == 0
    assert tracker.timestamps == []


def test_short_overlap_not_counted():
    """Sub-threshold overlap should be ignored."""
    tracker = InterruptionTracker()
    tracker.update(0.00, True, False, tutor_rms_db=-18, student_rms_db=-100)
    tracker.update(0.30, True, True, tutor_rms_db=-18, student_rms_db=-20)
    tracker.update(0.45, True, False, tutor_rms_db=-18, student_rms_db=-100)
    assert tracker.total_count == 0
    assert tracker.hard_count == 0


def test_meaningful_overlap_counts_once():
    tracker = InterruptionTracker()
    tracker.update(0.00, True, False, tutor_rms_db=-18, student_rms_db=-100)
    tracker.update(0.30, True, True, tutor_rms_db=-18, student_rms_db=-19)
    tracker.update(0.70, True, False, tutor_rms_db=-18, student_rms_db=-100)
    assert tracker.total_count == 1
    assert tracker.hard_count == 0


def test_hard_interruption_counts_directionally():
    tracker = InterruptionTracker()
    tracker.update(0.00, False, True, tutor_rms_db=-100, student_rms_db=-18)
    tracker.update(0.35, True, True, tutor_rms_db=-17, student_rms_db=-18)
    tracker.update(1.10, True, False, tutor_rms_db=-17, student_rms_db=-100)

    assert tracker.total_count == 1
    assert tracker.hard_count == 1
    assert tracker.tutor_interrupts_student == 1
    assert tracker.student_interrupts_tutor == 0


def test_simultaneous_start_is_not_hard_interruption():
    tracker = InterruptionTracker()
    tracker.update(0.00, True, True, tutor_rms_db=-18, student_rms_db=-18)
    tracker.update(0.80, False, True, tutor_rms_db=-100, student_rms_db=-18)
    assert tracker.total_count == 1
    assert tracker.hard_count == 0


def test_quick_yield_counts_as_cutoff():
    tracker = InterruptionTracker()
    tracker.update(0.00, False, True, tutor_rms_db=-100, student_rms_db=-17)
    tracker.update(0.35, True, True, tutor_rms_db=-16, student_rms_db=-17)
    tracker.update(0.55, True, False, tutor_rms_db=-16, student_rms_db=-100)
    assert tracker.total_count == 0  # too short to count as a meaningful overlap
    assert tracker.tutor_cutoffs == 1


def test_recent_count_filters_by_window():
    tracker = InterruptionTracker()

    # Hard interruption near t=0.35
    tracker.update(0.00, False, True, tutor_rms_db=-100, student_rms_db=-18)
    tracker.update(0.35, True, True, tutor_rms_db=-17, student_rms_db=-18)
    tracker.update(1.10, True, False, tutor_rms_db=-17, student_rms_db=-100)

    # Meaningful but not hard overlap near t=10.30
    tracker.update(10.00, True, False, tutor_rms_db=-18, student_rms_db=-100)
    tracker.update(10.30, True, True, tutor_rms_db=-18, student_rms_db=-24)
    tracker.update(10.70, True, False, tutor_rms_db=-18, student_rms_db=-100)

    assert tracker.total_count == 2
    assert tracker.hard_count == 1
    assert tracker.recent_count(5.0, 10.7) == 1
    assert tracker.recent_hard_count(15.0, 10.7) == 1


def test_short_quiet_overlap_is_backchannel_not_hard():
    tracker = InterruptionTracker()
    tracker.update(0.00, False, True, tutor_rms_db=-100, student_rms_db=-16)
    tracker.update(0.35, True, True, tutor_rms_db=-25, student_rms_db=-16)
    tracker.update(0.80, False, True, tutor_rms_db=-100, student_rms_db=-16)

    assert tracker.total_count == 1
    assert tracker.hard_count == 0
    assert tracker.backchannel_count == 1
    assert tracker.echo_suspected is False


def test_repeated_very_quiet_overlaps_trigger_echo_suspicion_and_are_excluded():
    tracker = InterruptionTracker()

    for base in (0.0, 2.0, 4.0):
        tracker.update(base, False, True, tutor_rms_db=-100, student_rms_db=-15)
        tracker.update(base + 0.35, True, True, tutor_rms_db=-32, student_rms_db=-15)
        tracker.update(base + 0.75, False, True, tutor_rms_db=-100, student_rms_db=-15)

    assert tracker.echo_suspected is True
    assert tracker.total_count == 0
    assert tracker.hard_count == 0


def test_active_overlap_state_is_visible_before_overlap_finishes():
    tracker = InterruptionTracker()
    tracker.update(0.00, False, True, tutor_rms_db=-100, student_rms_db=-16)
    tracker.update(0.35, True, True, tutor_rms_db=-18, student_rms_db=-16)
    assert tracker.current_overlap_duration(0.62) == pytest.approx(0.27, abs=0.05)
    assert tracker.current_overlap_state(0.62) in {"backchannel", "meaningful"}
