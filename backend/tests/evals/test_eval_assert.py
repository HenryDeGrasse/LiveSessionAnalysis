from datetime import datetime

from app.models import MetricsSnapshot, ParticipantMetrics, SessionMetrics, SessionSummary
from app.observability.trace_models import SessionEvent, SessionTrace

from .eval_assert import (
    assert_replay_matches_expectation,
    assert_replay_matches_trace,
    assert_trace_matches_expectation,
)
from .eval_case_schema import EvalExpectation
from .replay import ReplayResult


def test_replay_assertions_support_exact_value_paths():
    replay = ReplayResult(
        snapshot=MetricsSnapshot(
            session_id="session-1",
            timestamp=datetime(2025, 1, 1, 12, 0, 0),
            tutor=ParticipantMetrics(),
            student=ParticipantMetrics(attention_state="DOWN_ENGAGED"),
            session=SessionMetrics(),
        )
    )
    expectation = EvalExpectation.model_validate(
        {
            "value_assertions": [
                {
                    "path": "snapshot.student.attention_state",
                    "equals": "DOWN_ENGAGED"
                }
            ]
        }
    )

    assert_replay_matches_expectation(replay, expectation)


def test_trace_assertions_support_required_event_types():
    trace = SessionTrace(
        session_id="session-1",
        tutor_id="alice",
        session_type="practice",
        created_at=datetime(2025, 1, 1, 12, 0, 0),
        started_at=datetime(2025, 1, 1, 12, 0, 5),
        ended_at=datetime(2025, 1, 1, 12, 5, 0),
        duration_seconds=295.0,
        events=[
            SessionEvent(
                seq=1,
                t_ms=0,
                timestamp=datetime(2025, 1, 1, 12, 0, 5),
                event_type="participant_disconnected",
                role="student",
                data={},
            )
        ],
        summary=SessionSummary(
            session_id="session-1",
            tutor_id="alice",
            session_type="practice",
            start_time=datetime(2025, 1, 1, 12, 0, 5),
            end_time=datetime(2025, 1, 1, 12, 5, 0),
            duration_seconds=295.0,
        ),
    )
    expectation = EvalExpectation.model_validate(
        {
            "contains_event_types": ["participant_disconnected"]
        }
    )

    assert_trace_matches_expectation(trace, expectation)


def test_replay_assertions_support_comparison_to_recorded_trace():
    trace = SessionTrace(
        session_id="session-1",
        tutor_id="alice",
        session_type="practice",
        created_at=datetime(2025, 1, 1, 12, 0, 0),
        started_at=datetime(2025, 1, 1, 12, 0, 5),
        ended_at=datetime(2025, 1, 1, 12, 5, 0),
        duration_seconds=295.0,
        metrics_history=[
            MetricsSnapshot(
                session_id="session-1",
                timestamp=datetime(2025, 1, 1, 12, 4, 0),
                tutor=ParticipantMetrics(talk_time_percent=0.82),
                student=ParticipantMetrics(attention_state="SCREEN_ENGAGED"),
                session=SessionMetrics(),
            )
        ],
        summary=SessionSummary(
            session_id="session-1",
            tutor_id="alice",
            session_type="practice",
            start_time=datetime(2025, 1, 1, 12, 0, 5),
            end_time=datetime(2025, 1, 1, 12, 5, 0),
            duration_seconds=295.0,
        ),
    )
    replay = ReplayResult(
        snapshot=MetricsSnapshot(
            session_id="session-1",
            timestamp=datetime(2025, 1, 1, 12, 5, 0),
            tutor=ParticipantMetrics(talk_time_percent=0.80),
            student=ParticipantMetrics(attention_state="SCREEN_ENGAGED"),
            session=SessionMetrics(),
        )
    )
    expectation = EvalExpectation.model_validate(
        {
            "replay_matches_trace": [
                {
                    "replay_path": "snapshot.tutor.talk_time_percent",
                    "trace_path": "metrics_history.0.tutor.talk_time_percent",
                    "tolerance": 0.05
                },
                {
                    "replay_path": "snapshot.student.attention_state",
                    "trace_path": "metrics_history.0.student.attention_state"
                }
            ]
        }
    )

    assert_replay_matches_trace(replay, trace, expectation)
