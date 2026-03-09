from pathlib import Path

import pytest

from app.observability.trace_models import SessionTrace

from .eval_assert import (
    assert_replay_matches_expectation,
    assert_replay_matches_trace,
    load_expectation,
)
from .eval_case_schema import load_eval_cases
from .replay import replay_trace_signals
from .worker_replay import replay_trace_signals_via_livekit_worker

FIXTURES_DIR = Path(__file__).parent / "fixtures"


@pytest.mark.eval_replay
def test_livekit_worker_replay_cases_match_recorded_traces_and_baseline_replay():
    cases = load_eval_cases(FIXTURES_DIR / "replay_cases.json")
    assert cases

    for case in cases:
        trace = SessionTrace.model_validate_json(
            (FIXTURES_DIR / case.fixture).read_text()
        )
        expectation = load_expectation(FIXTURES_DIR / case.expectation)

        baseline = replay_trace_signals(trace)
        worker_replay = replay_trace_signals_via_livekit_worker(trace)

        assert_replay_matches_expectation(worker_replay, expectation)
        assert_replay_matches_trace(worker_replay, trace, expectation)

        assert worker_replay.snapshot.student.attention_state == baseline.snapshot.student.attention_state
        assert worker_replay.snapshot.tutor.attention_state == baseline.snapshot.tutor.attention_state
        assert worker_replay.snapshot.session.echo_suspected == baseline.snapshot.session.echo_suspected
        assert worker_replay.snapshot.session.interruption_count == baseline.snapshot.session.interruption_count
        assert worker_replay.snapshot.session.hard_interruption_count == baseline.snapshot.session.hard_interruption_count
        assert worker_replay.snapshot.session.backchannel_overlap_count == baseline.snapshot.session.backchannel_overlap_count
        assert worker_replay.snapshot.session.recent_hard_interruptions == baseline.snapshot.session.recent_hard_interruptions

        assert worker_replay.snapshot.tutor.talk_time_percent == pytest.approx(
            baseline.snapshot.tutor.talk_time_percent,
            abs=0.01,
        )
        assert worker_replay.snapshot.student.talk_time_percent == pytest.approx(
            baseline.snapshot.student.talk_time_percent,
            abs=0.01,
        )
        assert worker_replay.snapshot.session.recent_tutor_talk_percent == pytest.approx(
            baseline.snapshot.session.recent_tutor_talk_percent,
            abs=0.01,
        )

        assert [nudge.nudge_type for nudge in worker_replay.coach_nudges] == [
            nudge.nudge_type for nudge in baseline.coach_nudges
        ]
