from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.ai_coaching.context import AISuggestion
from app.ai_coaching.copilot import AICoachingCopilot
from app.ai_coaching.llm_client import MockLLMClient
from app.coaching_system.coach import CoachingEvaluation
from app.metrics_engine.engine import MetricsEngine
from app.models import Nudge, NudgePriority, Role
from app.session_manager import SessionRoom
from app.session_runtime import _session_resources, emit_metrics_snapshot
from app.transcription.buffer import TranscriptBuffer
from app.transcription.models import FinalUtterance


class _FakeCoach:
    def __init__(self, evaluation: CoachingEvaluation | None = None):
        self.session_type = "general"
        self.intensity = "normal"
        self._evaluation = evaluation or CoachingEvaluation()

    def evaluate(self, snapshot, elapsed_seconds):
        return self._evaluation

    def get_status(self, *, elapsed_seconds, rules_evaluated, degraded):
        return {
            "enabled": True,
            "elapsed_seconds": elapsed_seconds,
            "rules_evaluated": rules_evaluated,
            "degraded": degraded,
        }


def _make_room() -> SessionRoom:
    room = SessionRoom(
        session_id="test-ai-copilot-runtime",
        tutor_token="tutor-token",
        student_token="student-token",
        session_type="math",
    )
    room.started_at = 1.0
    tutor = room.participants[Role.TUTOR]
    tutor.connected = True
    tutor.websocket = AsyncMock()
    tutor.websocket.send_json = AsyncMock()
    return room


def _install_resources(room: SessionRoom) -> dict:
    resources = {
        "metrics_engine": MetricsEngine(room.session_id),
        "transcript_buffer": TranscriptBuffer(window_seconds=300.0),
        "coach": _FakeCoach(),
        "video_tutor": MagicMock(),
        "video_student": MagicMock(),
        "audio_tutor": MagicMock(),
        "audio_student": MagicMock(),
    }
    _session_resources[room.session_id] = resources
    return resources


def _add_transcript_words(buffer: TranscriptBuffer, count: int = 24) -> None:
    text = " ".join(f"word{i}" for i in range(count))
    buffer.add(
        FinalUtterance(
            role="student",
            text=text,
            start_time=0.0,
            end_time=8.0,
            utterance_id="utt-1",
        )
    )


class _FakeTranscriptionStream:
    def __init__(self, *, backpressure_level: int = 0):
        self._backpressure_level = backpressure_level

    def observability(self):
        return type(
            "Obs",
            (),
            {
                "partial_latency_p50_ms": 110.0,
                "partial_latency_p95_ms": 1800.0,
                "final_latency_p50_ms": 220.0,
                "final_latency_p95_ms": 900.0,
                "reconnect_count": 2,
                "drop_rate": 0.02,
                "billed_seconds_estimate": 42.0,
                "llm_call_count": 0,
                "llm_total_tokens": 0,
                "backpressure_level": self._backpressure_level,
            },
        )()


@pytest.mark.asyncio
async def test_emit_metrics_snapshot_converts_ai_suggestion_to_nudge():
    room = _make_room()
    resources = _install_resources(room)
    _add_transcript_words(resources["transcript_buffer"])

    llm = MockLLMClient(
        response=json.dumps(
            {
                "action": "probe",
                "topic": "fractions",
                "observation": "Student sounds unsure",
                "suggestion": "Ask the student to explain what the denominator means.",
                "suggested_prompt": "What does the bottom number tell us?",
                "priority": "high",
                "confidence": 0.91,
            }
        )
    )
    resources["ai_copilot"] = AICoachingCopilot(
        llm,
        session_type="math",
        baseline_interval_s=0.0,
        topic_cooldown_s=0.0,
    )

    try:
        snapshot = await emit_metrics_snapshot(
            room,
            record_history=False,
            allow_coaching=True,
        )
    finally:
        _session_resources.pop(room.session_id, None)

    assert snapshot is not None
    assert snapshot.ai_suggestion == "Ask the student to explain what the denominator means."
    assert any(n.nudge_type == "ai_coaching_suggestion" for n in room.nudges_sent)

    ai_nudge = next(n for n in room.nudges_sent if n.nudge_type == "ai_coaching_suggestion")
    assert ai_nudge.priority == NudgePriority.HIGH
    assert ai_nudge.trigger_metrics["topic"] == "fractions"
    assert ai_nudge.trigger_metrics["source"] == "ai_copilot"

    sent_types = [call.args[0]["type"] for call in room.participants[Role.TUTOR].websocket.send_json.call_args_list]
    assert sent_types == ["metrics", "nudge"]
    sent_nudge = room.participants[Role.TUTOR].websocket.send_json.call_args_list[1].args[0]
    assert sent_nudge["data"]["nudge_type"] == "ai_coaching_suggestion"


@pytest.mark.asyncio
async def test_emit_metrics_snapshot_passes_rule_nudge_signal_to_ai_copilot():
    room = _make_room()
    resources = _install_resources(room)
    _add_transcript_words(resources["transcript_buffer"])

    resources["coach"] = _FakeCoach(
        CoachingEvaluation(
            nudges=[
                Nudge(
                    nudge_type="check_understanding",
                    message="Pause and check understanding.",
                    priority=NudgePriority.MEDIUM,
                )
            ],
            candidate_nudges=["check_understanding"],
            emitted_nudge_type="check_understanding",
            emitted_nudge_priority="medium",
        )
    )

    ai_copilot = AsyncMock()
    ai_copilot.maybe_evaluate = AsyncMock(return_value=None)
    resources["ai_copilot"] = ai_copilot

    try:
        await emit_metrics_snapshot(
            room,
            record_history=False,
            allow_coaching=True,
        )
    finally:
        _session_resources.pop(room.session_id, None)

    ai_copilot.maybe_evaluate.assert_awaited_once()
    assert ai_copilot.maybe_evaluate.await_args.kwargs["rule_nudge_fired"] is True


@pytest.mark.asyncio
async def test_emit_metrics_snapshot_passes_backpressure_level_to_ai_copilot():
    room = _make_room()
    resources = _install_resources(room)
    _add_transcript_words(resources["transcript_buffer"])
    resources["transcription_stream_student:0"] = _FakeTranscriptionStream(
        backpressure_level=2
    )

    ai_copilot = AsyncMock()
    ai_copilot.maybe_evaluate = AsyncMock(return_value=None)
    resources["ai_copilot"] = ai_copilot

    try:
        snapshot = await emit_metrics_snapshot(
            room,
            record_history=False,
            allow_coaching=True,
        )
    finally:
        _session_resources.pop(room.session_id, None)

    assert snapshot is not None
    assert snapshot.backpressure_level == 2
    ai_copilot.maybe_evaluate.assert_awaited_once()
    assert ai_copilot.maybe_evaluate.await_args.kwargs["backpressure_level"] == 2
