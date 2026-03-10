from __future__ import annotations

import asyncio
import json
import logging
import time

import numpy as np

from .audio_processor.pipeline import AudioProcessor
from .config import settings
from .metrics_engine.engine import MetricsEngine
from .models import Role
from .session_manager import SessionRoom
from .video_processor.pipeline import VideoProcessor

logger = logging.getLogger(__name__)

# Per-session resources (created when session starts)
_session_resources: dict[str, dict] = {}


def trace_recorder(room: SessionRoom):
    return getattr(room, "trace_recorder", None)


def get_or_create_resources(room: SessionRoom) -> dict:
    """Get or create processing resources for a session."""
    sid = room.session_id
    if sid not in _session_resources:
        _session_resources[sid] = {
            "video_tutor": VideoProcessor(),
            "video_student": VideoProcessor(),
            "audio_tutor": AudioProcessor(),
            "audio_student": AudioProcessor(),
            "metrics_engine": MetricsEngine(sid),
        }
    return _session_resources[sid]


def cleanup_resources(session_id: str):
    """Clean up processing resources for a session."""
    resources = _session_resources.pop(session_id, None)
    if resources:
        resources["video_tutor"].close()
        resources["video_student"].close()


def reset_session_resources():
    for session_id in list(_session_resources.keys()):
        cleanup_resources(session_id)


def generate_session_summary(room: SessionRoom):
    from .analytics.summary import generate_summary

    return generate_summary(
        room.session_id,
        room.metrics_history,
        tutor_id=room.tutor_id,
        session_type=room.session_type,
        media_provider=room.media_provider,
        nudges=room.nudges_sent,
    )


def save_session(room: SessionRoom):
    """Persist session summary to storage."""
    try:
        from .analytics.session_store import SessionStore

        summary = generate_session_summary(room)
        store = SessionStore()
        store.save(summary)
        return summary
    except Exception as exc:
        logger.error(f"Failed to save session: {exc}")
        return None


def finalize_session(room: SessionRoom):
    """End session, save data, clean up resources.

    Sends session_end to any still-connected participant via a fire-and-forget task.
    """
    if room.ended_at is not None:
        return  # Already finalized

    room.ended_at = time.time()
    duration = room.elapsed_seconds()
    if room._metrics_task:
        room._metrics_task.cancel()

    try:
        from .livekit_worker import stop_livekit_analytics_worker

        stop_livekit_analytics_worker(room.session_id)
    except Exception:
        pass

    summary = save_session(room)
    if summary is None:
        try:
            summary = generate_session_summary(room)
        except Exception:
            summary = None

    recorder = trace_recorder(room)
    if recorder is not None:
        recorder.record_event(
            "session_end",
            data={
                "session_id": room.session_id,
                "duration_seconds": duration,
            },
        )
        if summary is not None:
            recorder.finalize(summary=summary, duration_seconds=duration)

    cleanup_resources(room.session_id)
    logger.info(f"Session {room.session_id}: finalized")

    async def _notify():
        for participant in room.participants.values():
            if participant.connected and participant.websocket:
                try:
                    await participant.websocket.send_json({
                        "type": "session_end",
                        "data": {
                            "session_id": room.session_id,
                            "duration_seconds": duration,
                        },
                    })
                    await participant.websocket.close(code=1000, reason="Session ended")
                except Exception:
                    pass

    try:
        loop = asyncio.get_running_loop()
        loop.create_task(_notify())
    except RuntimeError:
        pass  # No event loop — called from sync context (e.g., tests)


async def emit_metrics_snapshot(
    room: SessionRoom,
    *,
    record_history: bool,
    allow_coaching: bool,
    min_interval_seconds: float = 0.0,
):
    """Send a metrics snapshot to the tutor, optionally recording/coaching.

    The periodic loop records analytics history and evaluates coaching rules.
    Fast-path emits from audio updates are UI-only and intentionally skip both.

    Coaching evaluation now runs BEFORE the snapshot is serialized so that
    ``coaching_decision`` is included in the payload sent to the tutor when
    ``room.debug_mode`` is active.  Trace recording of coaching decisions
    happens unconditionally regardless of debug mode.
    """
    if room.ended_at is not None:
        return None

    now = time.time()
    if (
        min_interval_seconds > 0
        and now - room._last_metrics_emit_at < min_interval_seconds
    ):
        return None

    resources = _session_resources.get(room.session_id)
    if not resources:
        return None

    engine: MetricsEngine = resources["metrics_engine"]

    aggregation_start = time.time()
    p50, p95 = room.latency_percentiles()
    snapshot = engine.compute_snapshot(
        degraded=room.degradation_level > 0,
        gaze_unavailable=room.degradation_level >= 3,
        processing_ms=room.rolling_avg_processing_ms(),
        latency_p50_ms=p50,
        latency_p95_ms=p95,
        degradation_reason=room.degradation_reason(),
        target_fps=room.current_fps,
    )
    room.record_aggregation_time((time.time() - aggregation_start) * 1000)

    metrics_index = None
    if record_history:
        room.metrics_history.append(snapshot)
        metrics_index = len(room.metrics_history) - 1
        recorder = trace_recorder(room)
        if recorder is not None:
            recorder.record_metrics_snapshot(snapshot)

    # ── Coaching evaluation (before send) ────────────────────────────
    # Evaluate coaching rules BEFORE serializing the snapshot so that
    # coaching_decision is present in the JSON sent to the frontend.
    # The decision dict is only attached when debug_mode is active to
    # avoid sending verbose diagnostic data in normal operation.
    nudges_to_send: list = []
    if allow_coaching:
        try:
            from .coaching_system.coach import Coach

            coach = resources.get("coach")
            if coach is None:
                coach = Coach(session_type=room.session_type)
                resources["coach"] = coach
            evaluation = coach.evaluate(snapshot, room.elapsed_seconds())

            # Attach to snapshot only in debug mode (tutor ?debug=1)
            if room.debug_mode:
                snapshot.coaching_decision = {
                    "candidate_nudges": evaluation.candidate_nudges,
                    "suppressed_reasons": evaluation.suppressed_reasons,
                    "emitted_nudge": evaluation.emitted_nudge_type,
                    "trigger_features": evaluation.trigger_features,
                    "session_type": coach.session_type,
                }

            # Trace recording is unconditional — always record for evals
            recorder = trace_recorder(room)
            if recorder is not None:
                recorder.record_coaching_decision(
                    candidate_nudges=evaluation.candidate_nudges,
                    emitted_nudge=evaluation.emitted_nudge_type,
                    suppressed_reasons=evaluation.suppressed_reasons,
                    metrics_index=metrics_index,
                    trigger_features=evaluation.trigger_features,
                )

            for nudge in evaluation.nudges:
                room.nudges_sent.append(nudge)
                if recorder is not None:
                    recorder.record_nudge(nudge)
                nudges_to_send.append(nudge)
        except ImportError:
            pass

    # ── Send metrics snapshot ────────────────────────────────────────
    tutor = room.participants[Role.TUTOR]
    metrics_sent = False

    # Prefer LiveKit data packets when the worker is connected
    try:
        from .livekit_worker import get_active_worker, TOPIC_METRICS

        worker = get_active_worker(room.session_id)
        if worker is not None:
            payload = json.dumps(
                {"type": "metrics", "data": snapshot.model_dump(mode="json")}
            ).encode()
            metrics_sent = await worker.publish_data_to_tutor(
                payload, topic=TOPIC_METRICS, reliable=False
            )
    except ImportError:
        pass

    # Fallback to websocket if data packet wasn't sent
    if not metrics_sent and tutor.connected and tutor.websocket:
        try:
            await tutor.websocket.send_json({
                "type": "metrics",
                "data": snapshot.model_dump(mode="json"),
            })
            metrics_sent = True
        except Exception as exc:
            logger.error(f"Failed to send metrics to tutor: {exc}")

    if metrics_sent:
        room._last_metrics_emit_at = now

    # ── Send nudges ──────────────────────────────────────────────────
    for nudge in nudges_to_send:
        nudge_sent = False
        try:
            from .livekit_worker import get_active_worker, TOPIC_NUDGE

            worker = get_active_worker(room.session_id)
            if worker is not None:
                payload = json.dumps(
                    {"type": "nudge", "data": nudge.model_dump(mode="json")}
                ).encode()
                nudge_sent = await worker.publish_data_to_tutor(
                    payload, topic=TOPIC_NUDGE, reliable=True
                )
        except ImportError:
            pass

        if not nudge_sent and tutor.connected and tutor.websocket:
            try:
                await tutor.websocket.send_json({
                    "type": "nudge",
                    "data": nudge.model_dump(mode="json"),
                })
            except Exception:
                pass

    return snapshot


async def metrics_emit_loop(room: SessionRoom):
    """Emit MetricsSnapshot on the normal periodic cadence."""
    try:
        while room.ended_at is None:
            await asyncio.sleep(settings.metrics_emit_interval_seconds)

            if room.ended_at is not None:
                break

            await emit_metrics_snapshot(
                room,
                record_history=True,
                allow_coaching=True,
            )

    except asyncio.CancelledError:
        pass


async def process_video_frame_bytes(room: SessionRoom, role: Role, payload: bytes):
    """Process a JPEG video frame through the full pipeline."""
    if not room.should_process_video_frame(role):
        return

    resources = get_or_create_resources(room)
    processor = resources[f"video_{role.value}"]
    engine: MetricsEngine = resources["metrics_engine"]

    deg_level = room.degradation_level
    skip_expression = deg_level >= 2
    skip_gaze = deg_level >= 3

    result = processor.process_frame(
        payload,
        skip_expression=skip_expression,
        skip_gaze=skip_gaze,
    )

    _apply_video_result(room, role, engine, result)


async def process_video_frame_array(room: SessionRoom, role: Role, frame_bgr: np.ndarray):
    """Process a decoded BGR video frame through the full pipeline."""
    if not room.should_process_video_frame(role):
        return

    resources = get_or_create_resources(room)
    processor = resources[f"video_{role.value}"]
    engine: MetricsEngine = resources["metrics_engine"]

    deg_level = room.degradation_level
    skip_expression = deg_level >= 2
    skip_gaze = deg_level >= 3

    result = processor.process_frame_array(
        frame_bgr,
        skip_expression=skip_expression,
        skip_gaze=skip_gaze,
    )

    _apply_video_result(room, role, engine, result)


def _apply_video_result(
    room: SessionRoom,
    role: Role,
    engine: MetricsEngine,
    result,
):
    now = time.time()
    if result.gaze is not None:
        engine.update_gaze(
            role,
            now,
            result.gaze.on_camera,
            result.gaze.horizontal_angle_deg,
            result.gaze.vertical_angle_deg,
        )
    else:
        engine.update_visual_observation(
            role,
            now,
            face_detected=result.face_detected,
        )
    if result.expression is not None:
        engine.update_expression(role, result.expression.valence)

    recorder = trace_recorder(room)
    if recorder is not None:
        visual_signal = engine.current_visual_signal(role, now)
        recorder.record_visual_signal(
            role=role.value,
            face_present=result.face_detected,
            gaze_on_camera=result.gaze.on_camera if result.gaze is not None else None,
            attention_state=visual_signal.get("attention_state"),
            confidence=float(visual_signal.get("confidence", 0.0)),
        )

    room.record_processing_time(result.total_ms)
    room.record_stage_times(
        decode_ms=result.decode_ms,
        facemesh_ms=result.facemesh_ms,
        gaze_ms=result.gaze_ms,
        expression_ms=result.expression_ms,
    )
    previous_degradation = room.degradation_level
    room.check_degradation()
    if recorder is not None and room.degradation_level != previous_degradation:
        recorder.record_event(
            "degradation_changed",
            data={
                "previous_level": previous_degradation,
                "new_level": room.degradation_level,
                "target_fps": room.current_fps,
            },
        )


async def process_audio_chunk(room: SessionRoom, role: Role, payload: bytes):
    """Process an audio chunk through VAD and prosody."""
    resources = get_or_create_resources(room)
    processor = resources[f"audio_{role.value}"]
    engine: MetricsEngine = resources["metrics_engine"]

    participant = room.participants[role]
    result = processor.process_chunk(
        payload,
        force_muted=participant.audio_muted,
    )

    audio_timestamp = time.time()
    state_changed = engine.update_audio(
        role,
        audio_timestamp,
        result.is_speech,
        result.prosody.rms_energy,
        result.prosody.speech_rate_proxy,
        rms_db=result.prosody.rms_db,
    )

    recorder = trace_recorder(room)
    if recorder is not None:
        recorder.record_audio_signal(
            role=role.value,
            speech_active=result.is_speech,
            rms_db=result.prosody.rms_db,
            noise_floor_db=result.noise_floor_db,
        )
        for event in engine.drain_overlap_events():
            overlap_type = "meaningful"
            if event.echo_like:
                overlap_type = "echo_suspected"
            elif event.hard:
                overlap_type = "hard"
            elif event.backchannel:
                overlap_type = "backchannel"
            recorder.record_overlap_segment(
                start_t_ms=recorder.to_t_ms(event.timestamp),
                end_t_ms=recorder.to_t_ms(event.timestamp + event.duration_s),
                overlap_type=overlap_type,
            )

    if state_changed:
        await emit_metrics_snapshot(
            room,
            record_history=False,
            allow_coaching=False,
            min_interval_seconds=settings.live_metrics_min_emit_interval_seconds,
        )
