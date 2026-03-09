from __future__ import annotations

import math
from collections import Counter
from dataclasses import dataclass, field

from app.config import settings
from app.coaching_system.coach import Coach, CoachingEvaluation
from app.metrics_engine.engine import MetricsEngine
from app.models import MetricsSnapshot, Nudge, Role
from app.observability.trace_models import AudioSignalPoint, SessionTrace, VisualSignalPoint


@dataclass
class ReplayResult:
    snapshot: MetricsSnapshot
    coach_nudges: list[Nudge] = field(default_factory=list)
    coach_evaluation: CoachingEvaluation | None = None
    attention_state_counts: dict[str, dict[str, int]] = field(default_factory=dict)


def _role(value: str) -> Role:
    return Role.TUTOR if value == "tutor" else Role.STUDENT


def _rms_energy_from_db(rms_db: float | None, speech_active: bool) -> float:
    if rms_db is None:
        return 0.5 if speech_active else 0.0
    return max(0.0, (10 ** (rms_db / 20.0)) / 0.3)


def _angles_for_visual_point(point: VisualSignalPoint) -> tuple[float | None, float | None]:
    if point.gaze_on_camera:
        return 0.0, 0.0

    state = point.attention_state or ""
    if state == "SCREEN_ENGAGED":
        return 18.0, 4.0
    if state == "DOWN_ENGAGED":
        return 10.0, 20.0
    if state == "OFF_TASK_AWAY":
        return 40.0, 0.0
    if state == "FACE_MISSING":
        return None, None

    if point.gaze_on_camera is False:
        return 40.0, 0.0
    return None, None


def replay_trace_signals(trace: SessionTrace) -> ReplayResult:
    """Replay compact signal traces through production metrics/coaching code."""
    engine = MetricsEngine(trace.session_id)
    counters: dict[str, Counter] = {
        "tutor": Counter(),
        "student": Counter(),
    }

    combined = []
    for point in trace.visual_signals:
        combined.append((point.t_ms, point.seq, "visual", point))
    for point in trace.audio_signals:
        combined.append((point.t_ms, point.seq, "audio", point))
    combined.sort(key=lambda item: (item[0], item[1]))

    final_time_s = 0.0
    for t_ms, _, kind, point in combined:
        timestamp_s = t_ms / 1000.0
        final_time_s = max(final_time_s, timestamp_s)

        if kind == "visual":
            point = point  # type: ignore[assignment]
            assert isinstance(point, VisualSignalPoint)
            if point.attention_state:
                counters[point.role][point.attention_state] += 1
            horizontal, vertical = _angles_for_visual_point(point)
            if point.face_present and point.gaze_on_camera is not None and horizontal is not None and vertical is not None:
                engine.update_gaze(
                    _role(point.role),
                    timestamp_s,
                    point.gaze_on_camera,
                    horizontal,
                    vertical,
                )
            else:
                engine.update_visual_observation(
                    _role(point.role),
                    timestamp_s,
                    face_detected=point.face_present,
                    on_camera=point.gaze_on_camera,
                    horizontal_angle_deg=horizontal,
                    vertical_angle_deg=vertical,
                )
            continue

        assert isinstance(point, AudioSignalPoint)
        rms_energy = _rms_energy_from_db(point.rms_db, point.speech_active)
        engine.update_audio(
            _role(point.role),
            timestamp_s,
            point.speech_active,
            rms_energy,
            0.5 if point.speech_active else 0.0,
            rms_db=point.rms_db,
        )

    snapshot = engine.compute_snapshot(current_time=final_time_s)
    coach = Coach()
    elapsed_seconds = max(trace.duration_seconds, settings.global_nudge_warmup_seconds + 1)
    coach_evaluation = coach.evaluate(
        snapshot,
        elapsed_seconds=elapsed_seconds,
        now=max(1000.0, elapsed_seconds + 1000.0),
    )
    return ReplayResult(
        snapshot=snapshot,
        coach_nudges=coach_evaluation.nudges,
        coach_evaluation=coach_evaluation,
        attention_state_counts={
            role: dict(counter) for role, counter in counters.items()
        },
    )
