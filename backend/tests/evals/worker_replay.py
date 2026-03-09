from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field

from app.coaching_system.coach import Coach, CoachingEvaluation
from app.livekit import livekit_identity, livekit_role_for_identity
from app.metrics_engine.engine import MetricsEngine
from app.models import MetricsSnapshot, Nudge, Role
from app.observability.trace_models import AudioSignalPoint, SessionTrace, VisualSignalPoint

from .replay import _angles_for_visual_point, _rms_energy_from_db


@dataclass
class WorkerReplayResult:
    snapshot: MetricsSnapshot
    coach_nudges: list[Nudge] = field(default_factory=list)
    coach_evaluation: CoachingEvaluation | None = None
    attention_state_counts: dict[str, dict[str, int]] = field(default_factory=dict)


def _resolved_role(session_id: str, role_name: str) -> Role:
    role = Role.TUTOR if role_name == "tutor" else Role.STUDENT
    identity = livekit_identity(session_id, role)
    resolved = livekit_role_for_identity(session_id, identity)
    if resolved is None:
        raise AssertionError(f"Failed to resolve role from identity {identity}")
    return resolved


def replay_trace_signals_via_livekit_worker(trace: SessionTrace) -> WorkerReplayResult:
    """Replay compact trace signals as if they arrived through the LiveKit worker.

    This intentionally reuses the production MetricsEngine + Coach path, but resolves
    participant roles through the same LiveKit identity mapping used by the hidden
    worker subscriber (`session_id:role`).
    """

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
            assert isinstance(point, VisualSignalPoint)
            role = _resolved_role(trace.session_id, point.role)
            if point.attention_state:
                counters[point.role][point.attention_state] += 1
            horizontal, vertical = _angles_for_visual_point(point)
            if (
                point.face_present
                and point.gaze_on_camera is not None
                and horizontal is not None
                and vertical is not None
            ):
                engine.update_gaze(
                    role,
                    timestamp_s,
                    point.gaze_on_camera,
                    horizontal,
                    vertical,
                )
            else:
                engine.update_visual_observation(
                    role,
                    timestamp_s,
                    face_detected=point.face_present,
                    on_camera=point.gaze_on_camera,
                    horizontal_angle_deg=horizontal,
                    vertical_angle_deg=vertical,
                )
            continue

        assert isinstance(point, AudioSignalPoint)
        role = _resolved_role(trace.session_id, point.role)
        rms_energy = _rms_energy_from_db(point.rms_db, point.speech_active)
        engine.update_audio(
            role,
            timestamp_s,
            point.speech_active,
            rms_energy,
            0.5 if point.speech_active else 0.0,
            rms_db=point.rms_db,
        )

    snapshot = engine.compute_snapshot(current_time=final_time_s)
    coach = Coach()
    coach_evaluation = coach.evaluate(
        snapshot,
        elapsed_seconds=trace.duration_seconds,
        now=max(1000.0, trace.duration_seconds + 1000.0),
    )

    return WorkerReplayResult(
        snapshot=snapshot,
        coach_nudges=coach_evaluation.nudges,
        coach_evaluation=coach_evaluation,
        attention_state_counts={
            role: dict(counter) for role, counter in counters.items()
        },
    )
