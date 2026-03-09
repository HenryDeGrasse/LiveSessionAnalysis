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
