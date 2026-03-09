from __future__ import annotations

import math
import time

from ..config import settings
from ..models import MetricsSnapshot, ParticipantMetrics, SessionMetrics, Role
from .eye_contact import EyeContactTracker
from .speaking_time import SpeakingTimeTracker
from .interruptions import InterruptionTracker, OverlapEvent
from .energy import EnergyTracker
from .attention_drift import AttentionDriftDetector
from .attention_state import AttentionStateTracker


class MetricsEngine:
    """Cross-participant metrics aggregator.

    Collects per-participant signals and computes the MetricsSnapshot
    that drives the coaching system and analytics.

    Uses a fixed periodic emit loop for analytics history, with optional
    faster UI refreshes on meaningful audio/overlap state changes.
    """

    def __init__(self, session_id: str):
        self.session_id = session_id

        # Per-participant trackers
        self.tutor_eye_contact = EyeContactTracker()
        self.student_eye_contact = EyeContactTracker()
        self.tutor_energy = EnergyTracker()
        self.student_energy = EnergyTracker()
        self.tutor_drift = AttentionDriftDetector()
        self.student_drift = AttentionDriftDetector()
        self.tutor_attention_state = AttentionStateTracker()
        self.student_attention_state = AttentionStateTracker()

        # Cross-participant trackers
        self.speaking_time = SpeakingTimeTracker()
        self.interruptions = InterruptionTracker()

        # Session-level
        self._session_start: float = time.time()
        self._engagement_history: list[float] = []
        self._latest_tutor_rms_db: float = -100.0
        self._latest_student_rms_db: float = -100.0

    def update_visual_observation(
        self,
        role: Role,
        timestamp: float,
        *,
        face_detected: bool,
        on_camera: bool | None = None,
        horizontal_angle_deg: float | None = None,
        vertical_angle_deg: float | None = None,
    ):
        """Update face presence / gaze-derived attention state for a participant."""
        tracker = (
            self.tutor_attention_state if role == Role.TUTOR else self.student_attention_state
        )
        tracker.update(
            timestamp,
            face_detected=face_detected,
            on_camera=on_camera,
            horizontal_angle_deg=horizontal_angle_deg,
            vertical_angle_deg=vertical_angle_deg,
        )
        if not face_detected:
            if role == Role.TUTOR:
                self.tutor_eye_contact.update(timestamp, False)
            else:
                self.student_eye_contact.update(timestamp, False)

    def update_gaze(
        self,
        role: Role,
        timestamp: float,
        on_camera: bool,
        horizontal_angle_deg: float | None = None,
        vertical_angle_deg: float | None = None,
    ):
        """Update eye contact for a participant."""
        self.update_visual_observation(
            role,
            timestamp,
            face_detected=True,
            on_camera=on_camera,
            horizontal_angle_deg=horizontal_angle_deg,
            vertical_angle_deg=vertical_angle_deg,
        )
        if role == Role.TUTOR:
            self.tutor_eye_contact.update(timestamp, on_camera)
        else:
            self.student_eye_contact.update(timestamp, on_camera)

    def update_expression(self, role: Role, valence: float):
        """Update facial expression valence for a participant."""
        if role == Role.TUTOR:
            self.tutor_energy.update_expression(valence)
        else:
            self.student_energy.update_expression(valence)

    def current_visual_signal(self, role: Role, now: float | None = None) -> dict:
        if now is None:
            now = time.time()
        tracker = (
            self.tutor_attention_state if role == Role.TUTOR else self.student_attention_state
        )
        return {
            "attention_state": tracker.state(now),
            "confidence": tracker.confidence(now),
            "face_presence_score": tracker.face_presence_score(now),
            "visual_attention_score": tracker.visual_attention_score(now),
        }

    def drain_overlap_events(self) -> list[OverlapEvent]:
        return self.interruptions.drain_completed_events()

    def update_audio(
        self,
        role: Role,
        timestamp: float,
        is_speech: bool,
        rms_energy: float,
        speech_rate_proxy: float,
        rms_db: float | None = None,
    ) -> bool:
        """Update audio metrics for a participant.

        Returns True when live UI metrics should ideally refresh quickly.
        """
        before_key = (
            self.speaking_time.tutor_speaking,
            self.speaking_time.student_speaking,
            self.speaking_time.tutor_turn_count,
            self.speaking_time.student_turn_count,
            self.interruptions.live_state_key(timestamp),
        )

        # Allow old call sites/tests to omit raw dB and derive an approximation.
        if rms_db is None:
            rms_db = 20.0 * math.log10(max(rms_energy * 0.3, 1e-6))

        # Update energy tracker
        if role == Role.TUTOR:
            self.tutor_energy.update_audio(rms_energy, speech_rate_proxy)
            self._latest_tutor_rms_db = rms_db
            tutor_speaking = is_speech
            student_speaking = self.speaking_time.student_speaking
        else:
            self.student_energy.update_audio(rms_energy, speech_rate_proxy)
            self._latest_student_rms_db = rms_db
            tutor_speaking = self.speaking_time.tutor_speaking
            student_speaking = is_speech

        # Update cross-participant speaking time
        self.speaking_time.update(
            timestamp, tutor_speaking, student_speaking
        )

        # Update interruption tracking
        interruption_state_changed = self.interruptions.update(
            timestamp,
            tutor_speaking,
            student_speaking,
            tutor_rms_db=self._latest_tutor_rms_db,
            student_rms_db=self._latest_student_rms_db,
        )

        after_key = (
            self.speaking_time.tutor_speaking,
            self.speaking_time.student_speaking,
            self.speaking_time.tutor_turn_count,
            self.speaking_time.student_turn_count,
            self.interruptions.live_state_key(timestamp),
        )
        return interruption_state_changed or before_key != after_key

    def compute_snapshot(
        self,
        degraded: bool = False,
        gaze_unavailable: bool = False,
        processing_ms: float = 0.0,
        target_fps: int = 3,
        current_time: float | None = None,
    ) -> MetricsSnapshot:
        """Compute the current MetricsSnapshot.

        Called by the periodic metrics emit loop and occasional fast-path UI refreshes.
        """
        now = time.time() if current_time is None else current_time

        # Per-participant metrics
        tutor_eye = self.tutor_eye_contact.score()
        student_eye = self.student_eye_contact.score()
        tutor_en = self.tutor_energy.score
        student_en = self.student_energy.score

        tutor_attention_state = self.tutor_attention_state.state(now)
        tutor_attention_confidence = self.tutor_attention_state.confidence(now)
        tutor_face_presence = self.tutor_attention_state.face_presence_score(now)
        tutor_visual_attention = self.tutor_attention_state.visual_attention_score(now)
        tutor_time_in_state = self.tutor_attention_state.time_in_current_state(now)

        student_attention_state = self.student_attention_state.state(now)
        student_attention_confidence = self.student_attention_state.confidence(now)
        student_face_presence = self.student_attention_state.face_presence_score(now)
        student_visual_attention = self.student_attention_state.visual_attention_score(now)
        student_time_in_state = self.student_attention_state.time_in_current_state(now)

        # Compute engagement composite
        engagement = self._compute_engagement(
            student_eye,
            student_visual_attention,
            student_attention_state,
            tutor_en,
            student_en,
        )
        self._engagement_history.append(engagement)

        # Update drift detectors
        self.tutor_drift.update(now, tutor_en)
        self.student_drift.update(now, student_en)

        # Determine overall trend (use student drift as primary signal)
        trend = self.student_drift.trend()

        return MetricsSnapshot(
            session_id=self.session_id,
            tutor=ParticipantMetrics(
                eye_contact_score=tutor_eye,
                talk_time_percent=self.speaking_time.tutor_ratio(),
                energy_score=tutor_en,
                energy_drop_from_baseline=self.tutor_energy.drop_from_baseline,
                is_speaking=self.speaking_time.tutor_speaking,
                attention_state=tutor_attention_state,
                attention_state_confidence=tutor_attention_confidence,
                face_presence_score=tutor_face_presence,
                visual_attention_score=tutor_visual_attention,
                time_in_attention_state_seconds=tutor_time_in_state,
            ),
            student=ParticipantMetrics(
                eye_contact_score=student_eye,
                talk_time_percent=self.speaking_time.student_ratio(),
                energy_score=student_en,
                energy_drop_from_baseline=self.student_energy.drop_from_baseline,
                is_speaking=self.speaking_time.student_speaking,
                attention_state=student_attention_state,
                attention_state_confidence=student_attention_confidence,
                face_presence_score=student_face_presence,
                visual_attention_score=student_visual_attention,
                time_in_attention_state_seconds=student_time_in_state,
            ),
            session=SessionMetrics(
                interruption_count=self.interruptions.total_count,
                recent_interruptions=self.interruptions.recent_count(
                    settings.interruption_spike_window,
                    now,
                ),
                hard_interruption_count=self.interruptions.hard_count,
                recent_hard_interruptions=self.interruptions.recent_hard_count(
                    settings.interruption_spike_window,
                    now,
                ),
                backchannel_overlap_count=self.interruptions.backchannel_count,
                recent_backchannel_overlaps=self.interruptions.recent_backchannel_count(
                    settings.interruption_spike_window,
                    now,
                ),
                echo_suspected=self.interruptions.echo_suspected,
                active_overlap_duration_current=self.interruptions.current_overlap_duration(now),
                active_overlap_state=self.interruptions.current_overlap_state(now),
                tutor_cutoffs=self.interruptions.recent_tutor_cutoffs(
                    settings.interruption_spike_window,
                    now,
                ),
                student_cutoffs=self.interruptions.recent_student_cutoffs(
                    settings.interruption_spike_window,
                    now,
                ),
                silence_duration_current=self.speaking_time.student_silence_duration(now),
                time_since_student_spoke=self.speaking_time.time_since_student_spoke(now),
                mutual_silence_duration_current=self.speaking_time.mutual_silence_duration(now),
                tutor_monologue_duration_current=self.speaking_time.current_tutor_monologue_duration(now),
                tutor_turn_count=self.speaking_time.tutor_turn_count,
                student_turn_count=self.speaking_time.student_turn_count,
                student_response_latency_last_seconds=self.speaking_time.last_student_response_latency_seconds,
                tutor_response_latency_last_seconds=self.speaking_time.last_tutor_response_latency_seconds,
                recent_tutor_talk_percent=self.speaking_time.recent_tutor_ratio(now),
                engagement_trend=trend,
                engagement_score=engagement,
            ),
            degraded=degraded,
            gaze_unavailable=gaze_unavailable,
            server_processing_ms=processing_ms,
            target_fps=target_fps,
        )

    def _compute_engagement(
        self,
        student_eye_contact: float,
        student_visual_attention: float,
        student_attention_state: str,
        tutor_energy: float,
        student_energy: float,
    ) -> float:
        """Compute composite engagement score (0-100)."""
        attention_signal = (
            max(student_eye_contact, student_visual_attention)
            if student_attention_state == "LOW_CONFIDENCE"
            else student_visual_attention
        )
        score = (
            attention_signal * 40  # 40% weight on student visual attention
            + min(tutor_energy, student_energy) * 30  # 30% on energy alignment
            + (1.0 - abs(self.speaking_time.tutor_ratio() - 0.5)) * 30  # 30% on balanced talk time
        )
        return max(0, min(100, score))
