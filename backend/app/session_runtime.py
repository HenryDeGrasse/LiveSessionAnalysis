from __future__ import annotations

import asyncio
import inspect
import json
import logging
import time
from typing import TYPE_CHECKING, Any

import numpy as np

from .audio_processor.pipeline import AudioProcessor
from .config import settings
from .metrics_engine.engine import MetricsEngine
from .models import Nudge, NudgePriority, Role
from .session_manager import SessionRoom
from .video_processor.pipeline import VideoProcessor

if TYPE_CHECKING:
    from .livekit_worker import LiveKitAnalyticsWorker

logger = logging.getLogger(__name__)

# Per-session resources (created when session starts)
_session_resources: dict[str, dict] = {}


def trace_recorder(room: SessionRoom):
    return getattr(room, "trace_recorder", None)


def get_or_create_resources(room: SessionRoom) -> dict:
    """Get or create processing resources for a session."""
    sid = room.session_id
    if sid not in _session_resources:
        resources: dict = {
            "video_tutor": VideoProcessor(),
            "video_student": VideoProcessor(),
            "audio_tutor": AudioProcessor(),
            "audio_student": AudioProcessor(),
            "metrics_engine": MetricsEngine(sid),
        }
        # Dynamically create per-student processors for extra students (index 1+).
        for idx in room.extra_student_participants:
            resources[f"video_student_{idx}"] = VideoProcessor()
            resources[f"audio_student_{idx}"] = AudioProcessor()

        # Transcription resources (created once, shared across streams)
        if settings.enable_transcription:
            from .transcription import TranscriptBuffer, TranscriptStore, SessionClock

            resources["transcript_buffer"] = TranscriptBuffer(
                window_seconds=settings.transcription_buffer_window_seconds,
            )
            resources["transcript_store"] = TranscriptStore(
                session_id=sid,
            )
            resources["session_clock"] = SessionClock()

        # Uncertainty detector (per-student, created for the primary student)
        if settings.enable_uncertainty_detection:
            from .uncertainty import UncertaintyDetector

            resources["uncertainty_detector_0"] = UncertaintyDetector(
                student_index=0,
                persistence_utterances=settings.uncertainty_persistence_utterances,
                persistence_window_seconds=settings.uncertainty_persistence_window_seconds,
                uncertainty_threshold=settings.uncertainty_ui_threshold,
            )
            for idx in room.extra_student_participants:
                resources[f"uncertainty_detector_{idx}"] = UncertaintyDetector(
                    student_index=idx,
                    persistence_utterances=settings.uncertainty_persistence_utterances,
                    persistence_window_seconds=settings.uncertainty_persistence_window_seconds,
                    uncertainty_threshold=settings.uncertainty_ui_threshold,
                )

        ai_copilot = _build_ai_copilot(room)
        if ai_copilot is not None:
            resources["ai_copilot"] = ai_copilot

        _session_resources[sid] = resources
    else:
        # If extra students were added after initial resource creation,
        # create any missing per-student processors.
        resources = _session_resources[sid]
        for idx in room.extra_student_participants:
            if f"video_student_{idx}" not in resources:
                resources[f"video_student_{idx}"] = VideoProcessor()
                resources[f"audio_student_{idx}"] = AudioProcessor()
            if settings.enable_uncertainty_detection and f"uncertainty_detector_{idx}" not in resources:
                from .uncertainty import UncertaintyDetector

                resources[f"uncertainty_detector_{idx}"] = UncertaintyDetector(
                    student_index=idx,
                    persistence_utterances=settings.uncertainty_persistence_utterances,
                    persistence_window_seconds=settings.uncertainty_persistence_window_seconds,
                    uncertainty_threshold=settings.uncertainty_ui_threshold,
                )
    return _session_resources[sid]


def cleanup_resources(session_id: str):
    """Clean up processing resources for a session."""
    resources = _session_resources.pop(session_id, None)
    if not resources:
        return

    pending_stops: list[Any] = []
    for key, value in resources.items():
        stop = getattr(value, "stop", None)
        if key.startswith("transcription_stream_") and callable(stop):
            try:
                stop_result = stop()
            except Exception:
                logger.debug(
                    "Session %s: failed to stop transcription resource %s",
                    session_id,
                    key,
                    exc_info=True,
                )
            else:
                if inspect.isawaitable(stop_result):
                    pending_stops.append(stop_result)

        close = getattr(value, "close", None)
        if callable(close):
            close()

    if not pending_stops:
        return

    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        # No running event loop — best-effort sync cleanup.
        # This happens during test teardown or sync finalization.
        for stop_coro in pending_stops:
            try:
                asyncio.run(stop_coro)
            except Exception:
                # Stream may reference tasks on a closed loop; safe to ignore.
                pass
    else:
        for stop_coro in pending_stops:
            loop.create_task(stop_coro)


def _transcription_enabled_for_role(role: Role) -> bool:
    """Return True if transcription is enabled and the role should be transcribed."""
    return (
        settings.enable_transcription
        and role.value in settings.transcription_roles
    )


def _build_ai_copilot(room: SessionRoom) -> Any:
    """Create an AI coaching copilot for the session when configured.

    Returns ``None`` when AI coaching is disabled or when no production LLM
    credentials are available.
    """
    if not settings.enable_ai_coaching:
        return None

    try:
        from .ai_coaching import AICoachingCopilot
        from .ai_coaching.llm_client import (
            AnthropicLLMClient,
            OpenRouterLLMClient,
        )
    except ImportError:
        logger.debug("AI coaching imports unavailable", exc_info=True)
        return None

    # Build LLM client based on provider config
    llm_client = None
    provider = settings.ai_coaching_provider

    if provider == "openrouter":
        if not settings.openrouter_api_key:
            logger.warning(
                "Session %s: AI coaching enabled but openrouter_api_key is missing",
                room.session_id,
            )
            return None
        llm_client = OpenRouterLLMClient(
            api_key=settings.openrouter_api_key,
            model=settings.ai_coaching_model,
        )
    elif provider == "anthropic":
        if not settings.anthropic_api_key:
            logger.warning(
                "Session %s: AI coaching enabled but anthropic_api_key is missing",
                room.session_id,
            )
            return None
        llm_client = AnthropicLLMClient(
            api_key=settings.anthropic_api_key,
            model=settings.ai_coaching_model,
        )
    else:
        logger.warning(
            "Session %s: unsupported AI coaching provider %s",
            room.session_id,
            provider,
        )
        return None

    try:
        return AICoachingCopilot(
            llm_client,
            session_type=room.session_type,
            baseline_interval_s=settings.ai_coaching_baseline_interval_seconds,
            burst_interval_s=settings.ai_coaching_burst_interval_seconds,
            max_calls_per_hour=settings.ai_coaching_max_calls_per_hour,
        )
    except Exception:
        logger.warning(
            "Session %s: failed to initialize AI coaching copilot",
            room.session_id,
            exc_info=True,
        )
        return None


def _coerce_ai_nudge_priority(priority: str | None) -> NudgePriority:
    normalized = (priority or "medium").lower()
    if normalized == NudgePriority.HIGH.value:
        return NudgePriority.HIGH
    if normalized == NudgePriority.LOW.value:
        return NudgePriority.LOW
    return NudgePriority.MEDIUM


def get_or_create_transcription_stream(
    room: SessionRoom,
    role: Role,
    *,
    student_index: int = 0,
    worker: "LiveKitAnalyticsWorker | None" = None,
) -> Any:
    """Create and start a TranscriptionStream for a participant.

    Returns ``None`` when transcription is disabled for this role.  The
    stream is stored in the session resources keyed by identity so that
    reconnects can reuse it.

    Callbacks ``on_partial`` and ``on_final`` are wired to:
    1. Publish data packets to the tutor via the LiveKit worker.
    2. Feed the TranscriptBuffer / TranscriptStore.
    3. Record transcription events in the trace recorder.
    """
    if not _transcription_enabled_for_role(role):
        return None

    resources = get_or_create_resources(room)
    identity_key = f"{role.value}:{student_index}"
    stream_key = f"transcription_stream_{identity_key}"

    existing = resources.get(stream_key)
    if existing is not None:
        return existing

    clock = resources.get("session_clock")
    if clock is None:
        return None

    # Create provider based on config
    from .transcription.providers.mock import MockSTTProvider

    try:
        if settings.transcription_provider == "assemblyai" and settings.assemblyai_api_key:
            from .transcription.providers.assemblyai import AssemblyAISTTClient

            provider: Any = AssemblyAISTTClient(
                api_key=settings.assemblyai_api_key,
                sample_rate=16_000,
            )
        elif settings.transcription_provider == "deepgram" and settings.deepgram_api_key:
            from .transcription.providers.deepgram import DeepgramSTTClient

            provider = DeepgramSTTClient(
                api_key=settings.deepgram_api_key,
                model=settings.transcription_model,
                language=settings.transcription_language,
                enable_sentiment=settings.transcription_enable_sentiment,
                endpointing_ms=settings.deepgram_endpointing_ms,
                mip_opt_out=settings.deepgram_mip_opt_out,
            )
        else:
            provider = MockSTTProvider()
    except Exception:
        logger.exception("Failed to create STT provider, falling back to mock")
        provider = MockSTTProvider()

    # Build callbacks
    transcript_buffer = resources.get("transcript_buffer")
    transcript_store = resources.get("transcript_store")

    async def _on_partial(partial: Any) -> None:
        """Publish partial transcript to tutor via data packet."""
        if worker is not None:
            try:
                from .livekit_worker import TOPIC_TRANSCRIPT_PARTIAL

                payload = json.dumps({
                    "type": "transcript_partial",
                    "data": {
                        "utterance_id": partial.utterance_id,
                        "revision": partial.revision,
                        "role": partial.role,
                        "text": partial.text,
                        "confidence": partial.confidence,
                        "session_time": partial.session_time,
                    },
                }).encode()
                await worker.publish_data_to_tutor(
                    payload, topic=TOPIC_TRANSCRIPT_PARTIAL, reliable=False,
                )
            except Exception as exc:
                logger.debug(
                    "Session %s: failed to publish partial transcript: %s",
                    room.session_id,
                    exc,
                )

    async def _on_final(utterance: Any) -> None:
        """Process finalized utterance: buffer, store, publish, trace, uncertainty."""
        # Add to buffer and store
        if transcript_buffer is not None:
            transcript_buffer.add(utterance)
        if transcript_store is not None:
            transcript_store.add(utterance)

        # Publish to tutor
        if worker is not None:
            try:
                from .livekit_worker import TOPIC_TRANSCRIPT_FINAL

                payload = json.dumps({
                    "type": "transcript_final",
                    "data": {
                        "utterance_id": utterance.utterance_id,
                        "role": utterance.role,
                        "text": utterance.text,
                        "start_time": utterance.start_time,
                        "end_time": utterance.end_time,
                        "confidence": utterance.confidence,
                        "sentiment": utterance.sentiment,
                        "sentiment_score": utterance.sentiment_score,
                    },
                }).encode()
                await worker.publish_data_to_tutor(
                    payload, topic=TOPIC_TRANSCRIPT_FINAL, reliable=True,
                )
            except Exception as exc:
                logger.debug(
                    "Session %s: failed to publish final transcript: %s",
                    room.session_id,
                    exc,
                )

        # Trace recorder
        recorder = trace_recorder(room)
        if recorder is not None:
            recorder.record_event(
                "transcript_final",
                data={
                    "utterance_id": utterance.utterance_id,
                    "role": utterance.role,
                    "text": utterance.text,
                    "start_time": utterance.start_time,
                    "end_time": utterance.end_time,
                },
            )

        # Uncertainty detection on student utterances
        if (
            settings.enable_uncertainty_detection
            and getattr(utterance, "role", "") == "student"
        ):
            _sid = getattr(utterance, "student_index", student_index)
            _det_key = f"uncertainty_detector_{_sid}"
            _detector = resources.get(_det_key)
            if _detector is not None and transcript_buffer is not None:
                try:
                    # Gather recent tutor utterances for topic extraction
                    _tutor_texts = [
                        u.text
                        for u in transcript_buffer._within(seconds=60.0)
                        if u.role == "tutor"
                    ]
                    signal = _detector.update_transcript(
                        text=utterance.text,
                        end_time=utterance.end_time,
                        speaker_id=f"student-{_sid}",
                        recent_tutor_utterances=_tutor_texts,
                    )
                    if signal is not None and recorder is not None:
                        recorder.record_event(
                            "uncertainty_signal",
                            data={
                                "student_index": _sid,
                                "score": signal.score,
                                "paralinguistic_score": signal.paralinguistic_score,
                                "linguistic_score": signal.linguistic_score,
                                "topic": signal.topic,
                                "trigger_text": signal.trigger_text,
                                "confidence": signal.confidence,
                            },
                        )
                except Exception as exc:
                    logger.debug(
                        "Session %s: uncertainty transcript update failed: %s",
                        room.session_id,
                        exc,
                    )

    from .transcription import TranscriptionStream

    ts = TranscriptionStream(
        session_id=room.session_id,
        role=role,
        student_index=student_index,
        clock=clock,
        provider=provider,
        on_partial=_on_partial,
        on_final=_on_final,
    )

    resources[stream_key] = ts
    logger.info(
        "Session %s: created transcription stream for %s",
        room.session_id,
        identity_key,
    )
    return ts


def reset_session_resources():
    for session_id in list(_session_resources.keys()):
        cleanup_resources(session_id)


def generate_session_summary(room: SessionRoom):
    from .analytics.summary import generate_summary

    return generate_summary(
        room.session_id,
        room.metrics_history,
        tutor_id=room.tutor_id,
        student_user_id=room.student_user_id,
        session_type=room.session_type,
        session_title=room.session_title,
        media_provider=room.media_provider,
        nudges=room.nudges_sent,
    )


def save_session(room: SessionRoom):
    """Persist session summary to storage."""
    try:
        from .analytics import get_session_store

        summary = generate_session_summary(room)
        store = get_session_store()
        store.save(summary)
        return summary
    except Exception as exc:
        logger.error(f"Failed to save session: {exc}")
        return None


def _session_transcription_observability(resources: dict) -> dict[str, Any]:
    """Aggregate per-stream transcription observability for a session.

    Returns a compact dict with both per-stream details and a session-level
    summary suitable for metrics snapshots and trace recording.
    """
    stream_entries: list[dict[str, Any]] = []
    per_stream: dict[str, dict[str, Any]] = {}

    for key, value in resources.items():
        if not key.startswith("transcription_stream_"):
            continue
        observe = getattr(value, "observability", None)
        if not callable(observe):
            continue

        identity = key.replace("transcription_stream_", "")
        snapshot = observe()
        data = {
            "partial_latency_p50_ms": float(getattr(snapshot, "partial_latency_p50_ms", 0.0) or 0.0),
            "partial_latency_p95_ms": float(getattr(snapshot, "partial_latency_p95_ms", 0.0) or 0.0),
            "final_latency_p50_ms": float(getattr(snapshot, "final_latency_p50_ms", 0.0) or 0.0),
            "final_latency_p95_ms": float(getattr(snapshot, "final_latency_p95_ms", 0.0) or 0.0),
            "reconnect_count": int(getattr(snapshot, "reconnect_count", 0) or 0),
            "drop_rate": float(getattr(snapshot, "drop_rate", 0.0) or 0.0),
            "billed_seconds_estimate": float(getattr(snapshot, "billed_seconds_estimate", 0.0) or 0.0),
            "llm_call_count": int(getattr(snapshot, "llm_call_count", 0) or 0),
            "llm_total_tokens": int(getattr(snapshot, "llm_total_tokens", 0) or 0),
            "backpressure_level": int(getattr(snapshot, "backpressure_level", 0) or 0),
        }
        per_stream[identity] = data
        stream_entries.append(data)

    ai_copilot = resources.get("ai_copilot")
    llm_call_count = int(getattr(ai_copilot, "total_calls", 0) or 0)
    llm_total_tokens = int(getattr(ai_copilot, "total_tokens", 0) or 0)

    session_summary = {
        "partial_latency_p50_ms": max((item["partial_latency_p50_ms"] for item in stream_entries), default=0.0),
        "partial_latency_p95_ms": max((item["partial_latency_p95_ms"] for item in stream_entries), default=0.0),
        "final_latency_p50_ms": max((item["final_latency_p50_ms"] for item in stream_entries), default=0.0),
        "final_latency_p95_ms": max((item["final_latency_p95_ms"] for item in stream_entries), default=0.0),
        "reconnect_count": sum(item["reconnect_count"] for item in stream_entries),
        "drop_rate": max((item["drop_rate"] for item in stream_entries), default=0.0),
        "billed_seconds_estimate": sum(item["billed_seconds_estimate"] for item in stream_entries),
        "llm_call_count": llm_call_count,
        "llm_total_tokens": llm_total_tokens,
        "backpressure_level": max((item["backpressure_level"] for item in stream_entries), default=0),
    }

    return {
        "session": session_summary,
        "streams": per_stream,
    }


def _persist_transcript_data(
    room: SessionRoom,
    resources: dict,
    summary: Any | None,
) -> None:
    """Persist transcript store data to Postgres and S3/R2.

    Called during finalization when ``enable_transcript_storage`` is True.
    Compact payload goes to Postgres via the session store; full artifact
    goes to S3/R2 via the trace store.
    """
    transcript_store = resources.get("transcript_store")
    if transcript_store is None or len(transcript_store) == 0:
        return

    # Compact payload -> Postgres (stored alongside session summary)
    try:
        from .analytics import get_session_store

        store = get_session_store()
        pg_payload = transcript_store.to_postgres_payload()
        # Attach transcript data to the session summary if available
        if summary is not None:
            summary.transcript_compact = pg_payload
            summary.transcript_word_count = pg_payload.get("word_count", 0)
            store.save(summary)
            logger.info(
                "Session %s: persisted transcript compact payload to session store (%d words)",
                room.session_id,
                pg_payload.get("word_count", 0),
            )
    except Exception as exc:
        logger.warning(
            "Session %s: failed to persist transcript to session store: %s",
            room.session_id,
            exc,
        )

    # Full artifact -> S3/R2
    try:
        if settings.trace_storage_backend == "s3":
            from .observability import get_trace_store

            trace_store = get_trace_store()
            import json as _json

            artifact = transcript_store.to_s3_artifact()
            artifact_key = f"transcripts/{room.session_id}.json"
            trace_store._client.put_object(
                Bucket=trace_store._bucket,
                Key=f"{trace_store._prefix}{artifact_key}",
                Body=_json.dumps(artifact, default=str).encode("utf-8"),
                ContentType="application/json",
            )
            logger.info(
                "Session %s: persisted full transcript artifact to S3",
                room.session_id,
            )
    except Exception as exc:
        logger.warning(
            "Session %s: failed to persist transcript to S3: %s",
            room.session_id,
            exc,
        )


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

    # Persist transcript data before cleanup
    resources = _session_resources.get(room.session_id)
    if resources is not None and settings.enable_transcript_storage:
        _persist_transcript_data(room, resources, summary)

    # Enrich summary with transcript stats
    if resources is not None and summary is not None:
        transcript_store = resources.get("transcript_store")
        if transcript_store is not None and len(transcript_store) > 0:
            pg_payload = transcript_store.to_postgres_payload()
            summary.transcript_word_count = pg_payload.get("word_count", 0)

    # Record transcription stats before cleanup
    recorder = trace_recorder(room)
    if recorder is not None and resources is not None:
        # Collect transcription stats from all streams
        transcription_stats = {}
        for key, value in resources.items():
            if key.startswith("transcription_stream_"):
                identity = key.replace("transcription_stream_", "")
                transcription_stats[identity] = value.stats
        if transcription_stats:
            recorder.record_event(
                "transcription_stats",
                data=transcription_stats,
            )

        transcription_observability = _session_transcription_observability(resources)
        if transcription_observability["streams"] or transcription_observability["session"]["llm_call_count"]:
            recorder.record_event(
                "transcription_observability",
                data=transcription_observability,
            )

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
        # Collect all participants: tutor + primary student + extra students.
        all_participants = list(room.participants.values()) + list(
            room.extra_student_participants.values()
        )
        for participant in all_participants:
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

    # Populate uncertainty fields from the primary student's detector
    if settings.enable_uncertainty_detection and resources:
        uncertainty_detector = resources.get("uncertainty_detector_0")
        if uncertainty_detector is not None:
            active_signal = getattr(
                uncertainty_detector,
                "current_uncertainty_signal",
                None,
            )
            if active_signal is not None:
                snapshot.student_uncertainty_score = active_signal.score
                snapshot.student_uncertainty_topic = active_signal.topic or None
                snapshot.student_uncertainty_confidence = active_signal.confidence

    transcription_observability = None
    if resources:
        transcription_observability = _session_transcription_observability(resources)

    # Mark transcript availability on the snapshot when transcription resources
    # are active for the session, even before the first stream is created.
    if resources:
        snapshot.backpressure_level = int(
            (transcription_observability or {}).get("session", {}).get(
                "backpressure_level", 0
            )
        )

    if settings.enable_transcription and resources:
        snapshot.transcript_available = all(
            key in resources
            for key in ("transcript_buffer", "transcript_store", "session_clock")
        )

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
                coach = Coach(
                    session_type=room.session_type,
                    intensity=room.coaching_intensity,
                )
                resources["coach"] = coach
            evaluation = coach.evaluate(snapshot, room.elapsed_seconds())

            # Always attach lightweight coaching_status for the UI indicator
            snapshot.coaching_status = coach.get_status(
                elapsed_seconds=room.elapsed_seconds(),
                rules_evaluated=len(evaluation.candidates_evaluated),
                degraded=snapshot.degraded,
            )

            # Attach full decision only in debug mode (tutor ?debug=1)
            if room.debug_mode:
                snapshot.coaching_decision = {
                    "candidate_nudges": evaluation.candidate_nudges,
                    "candidate_rule_scores": evaluation.candidate_rule_scores,
                    "suppressed_reasons": evaluation.suppressed_reasons,
                    "emitted_nudge": evaluation.emitted_nudge_type,
                    "emitted_priority": evaluation.emitted_nudge_priority,
                    "fired_rule_score": evaluation.emitted_rule_score,
                    "trigger_features": evaluation.trigger_features,
                    "session_type": coach.session_type,
                    "coaching_intensity": coach.intensity,
                    "candidates_evaluated": evaluation.candidates_evaluated,
                    "fired_rule": evaluation.fired_rule,
                }

            # Trace recording is unconditional — always record for evals
            recorder = trace_recorder(room)
            if recorder is not None:
                recorder.record_coaching_decision(
                    candidate_nudges=evaluation.candidate_nudges,
                    emitted_nudge=evaluation.emitted_nudge_type,
                    suppressed_reasons=evaluation.suppressed_reasons,
                    metrics_index=metrics_index,
                    trigger_features={
                        **evaluation.trigger_features,
                        "candidate_rule_scores": evaluation.candidate_rule_scores,
                        "emitted_priority": evaluation.emitted_nudge_priority,
                        "fired_rule_score": evaluation.emitted_rule_score,
                    },
                    candidates_evaluated=evaluation.candidates_evaluated,
                    fired_rule=evaluation.fired_rule,
                )

            for nudge in evaluation.nudges:
                room.nudges_sent.append(nudge)
                if recorder is not None:
                    recorder.record_nudge(nudge)
                nudges_to_send.append(nudge)

            ai_copilot = resources.get("ai_copilot")
            transcript_buffer = resources.get("transcript_buffer")
            if ai_copilot is not None and transcript_buffer is not None:
                ai_suggestion = await ai_copilot.maybe_evaluate(
                    transcript_buffer,
                    elapsed_seconds=room.elapsed_seconds(),
                    uncertainty_score=float(snapshot.student_uncertainty_score or 0.0),
                    uncertainty_topic=snapshot.student_uncertainty_topic or "",
                    tutor_talk_ratio=float(snapshot.tutor.talk_time_percent),
                    student_talk_ratio=float(snapshot.student.talk_time_percent),
                    engagement_score=float(snapshot.session.engagement_score) / 100.0,
                    engagement_trend=snapshot.session.engagement_trend,
                    rule_nudge_fired=bool(evaluation.nudges),
                    now=now,
                    backpressure_level=int(snapshot.backpressure_level),
                )
                if ai_suggestion is not None:
                    snapshot.ai_suggestion = ai_suggestion.suggestion
                    ai_nudge = Nudge(
                        nudge_type="ai_coaching_suggestion",
                        message=ai_suggestion.suggestion,
                        priority=_coerce_ai_nudge_priority(ai_suggestion.priority),
                        trigger_metrics={
                            "source": "ai_copilot",
                            "action": ai_suggestion.action,
                            "topic": ai_suggestion.topic,
                            "observation": ai_suggestion.observation,
                            "suggested_prompt": ai_suggestion.suggested_prompt,
                            "confidence": ai_suggestion.confidence,
                            "uncertainty_score": snapshot.student_uncertainty_score,
                            "uncertainty_topic": snapshot.student_uncertainty_topic,
                        },
                    )
                    room.nudges_sent.append(ai_nudge)
                    if recorder is not None:
                        recorder.record_nudge(ai_nudge)
                    nudges_to_send.append(ai_nudge)
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


async def process_video_frame_bytes(
    room: SessionRoom,
    role: Role,
    payload: bytes,
    student_index: int = 0,
):
    """Process a JPEG video frame through the full pipeline."""
    if not room.should_process_video_frame(role):
        return

    resources = get_or_create_resources(room)
    if role == Role.STUDENT and student_index > 0:
        processor = resources.get(f"video_student_{student_index}")
        if processor is None:
            return
    else:
        processor = resources[f"video_{role.value}"]
    engine: MetricsEngine = resources["metrics_engine"]

    deg_level = room.degradation_level
    skip_expression = deg_level >= 2
    skip_gaze = deg_level >= 3

    before_visual = engine.current_visual_signal(
        role,
        student_index=student_index,
    )
    result = processor.process_frame(
        payload,
        skip_expression=skip_expression,
        skip_gaze=skip_gaze,
    )

    visual_state_changed = _apply_video_result(
        room,
        role,
        engine,
        result,
        student_index=student_index,
        previous_visual_signal=before_visual,
    )
    if visual_state_changed:
        await emit_metrics_snapshot(
            room,
            record_history=False,
            allow_coaching=False,
            min_interval_seconds=settings.live_metrics_min_emit_interval_seconds,
        )


async def process_video_frame_array(
    room: SessionRoom,
    role: Role,
    frame_bgr: np.ndarray,
    student_index: int = 0,
):
    """Process a decoded BGR video frame through the full pipeline."""
    if not room.should_process_video_frame(role):
        return

    resources = get_or_create_resources(room)
    if role == Role.STUDENT and student_index > 0:
        processor = resources.get(f"video_student_{student_index}")
        if processor is None:
            return
    else:
        processor = resources[f"video_{role.value}"]
    engine: MetricsEngine = resources["metrics_engine"]

    deg_level = room.degradation_level
    skip_expression = deg_level >= 2
    skip_gaze = deg_level >= 3

    before_visual = engine.current_visual_signal(
        role,
        student_index=student_index,
    )
    result = processor.process_frame_array(
        frame_bgr,
        skip_expression=skip_expression,
        skip_gaze=skip_gaze,
    )

    visual_state_changed = _apply_video_result(
        room,
        role,
        engine,
        result,
        student_index=student_index,
        previous_visual_signal=before_visual,
    )
    if visual_state_changed:
        await emit_metrics_snapshot(
            room,
            record_history=False,
            allow_coaching=False,
            min_interval_seconds=settings.live_metrics_min_emit_interval_seconds,
        )


def _apply_video_result(
    room: SessionRoom,
    role: Role,
    engine: MetricsEngine,
    result,
    student_index: int = 0,
    previous_visual_signal: dict | None = None,
) -> bool:
    now = time.time()
    if result.gaze is not None:
        engine.update_gaze(
            role,
            now,
            result.gaze.on_camera,
            result.gaze.horizontal_angle_deg,
            result.gaze.vertical_angle_deg,
            student_index=student_index,
        )
    else:
        engine.update_visual_observation(
            role,
            now,
            face_detected=result.face_detected,
            student_index=student_index,
        )
    if result.expression is not None:
        engine.update_expression(role, result.expression.valence, student_index=student_index)

    visual_signal = engine.current_visual_signal(
        role,
        now,
        student_index=student_index,
    )
    recorder = trace_recorder(room)
    if recorder is not None:
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

    if previous_visual_signal is None:
        return False

    return (
        previous_visual_signal.get("instant_attention_state")
        != visual_signal.get("instant_attention_state")
        or previous_visual_signal.get("attention_state")
        != visual_signal.get("attention_state")
    )


async def process_audio_chunk(
    room: SessionRoom,
    role: Role,
    payload: bytes,
    student_index: int = 0,
):
    """Process an audio chunk through VAD and prosody.

    Returns the audio processing result (with ``is_speech`` attribute) so
    that the caller (e.g. LiveKit worker) can feed the transcription stream.
    """
    resources = get_or_create_resources(room)
    if role == Role.STUDENT and student_index > 0:
        processor = resources.get(f"audio_student_{student_index}")
        if processor is None:
            return None
        participant = room.get_student_participant(student_index)
    else:
        processor = resources[f"audio_{role.value}"]
        participant = room.participants[role]
    engine: MetricsEngine = resources["metrics_engine"]

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
        student_index=student_index,
    )

    # Update uncertainty detector with prosody (student only)
    if (
        settings.enable_uncertainty_detection
        and role == Role.STUDENT
        and result.is_speech
    ):
        detector_key = f"uncertainty_detector_{student_index}"
        uncertainty_detector = resources.get(detector_key)
        if uncertainty_detector is not None:
            try:
                uncertainty_detector.update_audio(
                    result.prosody,
                    timestamp=audio_timestamp,
                    role="student",
                )
            except Exception as exc:
                logger.debug(
                    "Session %s: uncertainty detector audio update failed: %s",
                    room.session_id,
                    exc,
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

    return result
