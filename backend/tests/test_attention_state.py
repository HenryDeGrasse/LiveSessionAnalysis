import pytest

from app.metrics_engine.attention_state import AttentionStateTracker


@pytest.mark.parametrize(
    ("updates", "expected_state"),
    [
        (
            [
                (0.0, False, None, None, None),
                (1.0, False, None, None, None),
                (2.0, False, None, None, None),
                (3.0, True, False, 18.0, 4.0),
                (4.0, False, None, None, None),
                (5.0, False, None, None, None),
            ],
            "FACE_MISSING",
        ),
        (
            [
                (0.0, True, None, None, None),
                (1.0, True, None, None, None),
                (2.0, True, None, None, None),
                (3.0, True, None, None, None),
                (4.0, True, None, None, None),
                (5.0, True, None, None, None),
            ],
            "LOW_CONFIDENCE",
        ),
        (
            [
                (0.0, True, True, 2.0, 1.0),
                (1.0, True, True, -3.0, 2.0),
                (2.0, True, True, 1.0, -1.0),
                (3.0, True, True, 0.0, 0.0),
                (4.0, True, True, -2.0, 1.0),
                (5.0, True, True, 3.0, -2.0),
            ],
            "CAMERA_FACING",
        ),
        (
            [
                (0.0, True, False, 18.0, 4.0),
                (1.0, True, False, 20.0, 2.0),
                (2.0, True, False, 16.0, 6.0),
                (3.0, True, False, 22.0, 3.0),
                (4.0, True, False, 19.0, 5.0),
                (5.0, True, False, 17.0, 4.0),
            ],
            "SCREEN_ENGAGED",
        ),
        (
            [
                (0.0, True, False, 4.0, 20.0),
                (1.0, True, False, 6.0, 22.0),
                (2.0, True, False, 5.0, 18.0),
                (3.0, True, False, 3.0, 24.0),
                (4.0, True, False, 6.0, 21.0),
                (5.0, True, False, 4.0, 19.0),
            ],
            "DOWN_ENGAGED",
        ),
        (
            [
                (0.0, True, False, 42.0, 2.0),
                (1.0, True, False, 45.0, 4.0),
                (2.0, True, False, 48.0, 3.0),
                (3.0, True, False, 40.0, 5.0),
                (4.0, True, False, 44.0, 1.0),
                (5.0, True, False, 46.0, 4.0),
            ],
            "OFF_TASK_AWAY",
        ),
    ],
)
def test_attention_state_classification(updates, expected_state):
    tracker = AttentionStateTracker(window_seconds=10.0)
    for timestamp, face_detected, on_camera, horizontal_angle_deg, vertical_angle_deg in updates:
        tracker.update(
            timestamp,
            face_detected=face_detected,
            on_camera=on_camera,
            horizontal_angle_deg=horizontal_angle_deg,
            vertical_angle_deg=vertical_angle_deg,
        )

    assert tracker.state() == expected_state
    assert 0.0 <= tracker.confidence() <= 1.0
    assert 0.0 <= tracker.visual_attention_score() <= 1.0


def test_faster_classification_with_4_samples():
    """New default min_samples=4 allows classification after just 4 observations (was 5)."""
    tracker = AttentionStateTracker(window_seconds=10.0)
    # 4 samples with full gaze data — should now classify (not LOW_CONFIDENCE)
    for t, h, v in [(0.0, 2.0, 1.0), (1.0, -3.0, 2.0), (2.0, 1.0, -1.0), (3.0, 0.0, 0.0)]:
        tracker.update(t, face_detected=True, on_camera=True, horizontal_angle_deg=h, vertical_angle_deg=v)

    state = tracker.state()
    assert state == "CAMERA_FACING", f"Expected CAMERA_FACING with 4 samples, got {state}"


def test_faster_gaze_classification_with_2_gaze_samples():
    """New default min_gaze_samples=2 allows gaze-based classification with only 2 gaze observations."""
    tracker = AttentionStateTracker(window_seconds=10.0, min_samples=4)
    # 4 face-present samples; only 2 have gaze data — should now classify with min_gaze_samples=2
    tracker.update(0.0, face_detected=True, on_camera=None, horizontal_angle_deg=None, vertical_angle_deg=None)
    tracker.update(1.0, face_detected=True, on_camera=None, horizontal_angle_deg=None, vertical_angle_deg=None)
    tracker.update(2.0, face_detected=True, on_camera=True, horizontal_angle_deg=1.0, vertical_angle_deg=0.0)
    tracker.update(3.0, face_detected=True, on_camera=True, horizontal_angle_deg=-1.0, vertical_angle_deg=1.0)

    state = tracker.state()
    assert state == "CAMERA_FACING", f"Expected CAMERA_FACING with 2 gaze samples, got {state}"


def test_recency_weighting_accelerates_state_transition():
    """Recency weighting should bias the classification toward the most recent observations,
    making transitions to a new state detectably faster when recent frames diverge from older ones."""
    tracker = AttentionStateTracker(window_seconds=10.0, min_samples=4)

    # Older observations: off-task (looking far right)
    for t in [0.0, 1.0, 2.0]:
        tracker.update(t, face_detected=True, on_camera=False, horizontal_angle_deg=45.0, vertical_angle_deg=2.0)

    # Recent observations: now camera-facing
    for t in [3.0, 4.0, 5.0]:
        tracker.update(t, face_detected=True, on_camera=True, horizontal_angle_deg=1.0, vertical_angle_deg=0.0)

    # With recency weighting, the recent camera-facing frames should dominate
    state = tracker.state()
    # The weighted on_camera_ratio should be well above 0.55 threshold
    assert state == "CAMERA_FACING", (
        f"Expected CAMERA_FACING (recency weighting should favor recent frames), got {state}"
    )


def test_new_default_window_seconds():
    """Default window is now short enough to prune older observations quickly."""
    tracker = AttentionStateTracker()  # uses configured defaults

    # Add 5 camera-facing observations within a 6s window
    for t in [0.0, 1.5, 3.0, 4.5, 6.0]:
        tracker.update(t, face_detected=True, on_camera=True, horizontal_angle_deg=1.0, vertical_angle_deg=0.0)

    # Querying at t=6.0 — all 5 are within the 6s window (oldest at t=0.0)
    state = tracker.state(now=6.0)
    assert state == "CAMERA_FACING"

    # Now add an observation far into the future — with the current shorter
    # default window only the newest point remains, so confidence drops.
    tracker.update(10.0, face_detected=True, on_camera=True, horizontal_angle_deg=1.0, vertical_angle_deg=0.0)
    state = tracker.state(now=10.0)
    assert state == "LOW_CONFIDENCE"


def test_instant_state_uses_latest_observation_without_window_lag():
    tracker = AttentionStateTracker(window_seconds=10.0, min_samples=4)

    for t in [0.0, 1.0, 2.0, 3.0]:
        tracker.update(
            t,
            face_detected=True,
            on_camera=True,
            horizontal_angle_deg=1.0,
            vertical_angle_deg=0.0,
        )

    # Rolling state is still camera-facing, but the newest frame should flip the
    # instantaneous state immediately to OFF_TASK_AWAY.
    tracker.update(
        4.0,
        face_detected=True,
        on_camera=False,
        horizontal_angle_deg=42.0,
        vertical_angle_deg=2.0,
    )

    assert tracker.state(now=4.0) == "CAMERA_FACING"
    assert tracker.instant_state(now=4.0) == "OFF_TASK_AWAY"
    assert tracker.instant_confidence(now=4.0) > 0.0
