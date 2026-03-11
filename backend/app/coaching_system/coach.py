from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Optional

from ..config import INTENSITY_MULTIPLIERS, settings
from ..models import MetricsSnapshot, Nudge
from .profiles import SessionProfile, get_profile
from .rules import CoachingRule, DEFAULT_RULES


@dataclass
class CoachingEvaluation:
    nudges: list[Nudge] = field(default_factory=list)
    candidate_nudges: list[str] = field(default_factory=list)
    suppressed_reasons: list[str] = field(default_factory=list)
    emitted_nudge_type: Optional[str] = None
    trigger_features: dict = field(default_factory=dict)
    candidates_evaluated: list[str] = field(default_factory=list)
    fired_rule: Optional[str] = None


class Coach:
    """Rule engine that converts MetricsSnapshots into coaching Nudges.

    Respects cooldowns, minimum session elapsed time, global budget,
    session-type profiles, and selective suppression gates.

    The ``intensity`` parameter scales the built-in coaching thresholds:

    * ``off``        – no nudges ever fire (max_per_session set to 0).
    * ``subtle``     – warmup/cooldown doubled, max_per_session lowered by 1.
    * ``normal``     – settings defaults used as-is.
    * ``aggressive`` – warmup/cooldown halved, max_per_session doubled.
    """

    def __init__(
        self,
        rules: list[CoachingRule] | None = None,
        session_type: str = "general",
        intensity: str = "normal",
    ):
        self._rules = rules or DEFAULT_RULES
        self._session_type = session_type
        normalized_intensity = intensity if intensity in INTENSITY_MULTIPLIERS else "normal"
        self._intensity = normalized_intensity
        self._profile = get_profile(session_type)
        self._last_fired: dict[str, float] = {}  # rule name -> timestamp
        self._last_nudge_at: float | None = None
        self._session_nudges_sent: int = 0

        # Store the raw multiplier so evaluate() can apply it at call time
        # (keeping settings patchable for tests while still scaling thresholds).
        self._intensity_multiplier = INTENSITY_MULTIPLIERS[normalized_intensity]

    @property
    def profile(self) -> SessionProfile:
        return self._profile

    @property
    def session_type(self) -> str:
        return self._session_type

    @property
    def intensity(self) -> str:
        return self._intensity

    def _trigger_features(self, snapshot: MetricsSnapshot) -> dict:
        return {
            "tutor_talk": snapshot.tutor.talk_time_percent,
            "student_eye_contact": snapshot.student.eye_contact_score,
            "student_talk": snapshot.student.talk_time_percent,
            "student_silence_duration": snapshot.session.silence_duration_current,
            "tutor_energy": snapshot.tutor.energy_score,
            "student_energy": snapshot.student.energy_score,
            "interruptions": snapshot.session.interruption_count,
            "recent_interruptions": snapshot.session.recent_interruptions,
            "hard_interruptions": snapshot.session.hard_interruption_count,
            "recent_hard_interruptions": snapshot.session.recent_hard_interruptions,
            "backchannel_overlaps": snapshot.session.backchannel_overlap_count,
            "recent_backchannel_overlaps": snapshot.session.recent_backchannel_overlaps,
            "echo_suspected": float(snapshot.session.echo_suspected),
            "tutor_cutoffs": snapshot.session.tutor_cutoffs,
            "student_cutoffs": snapshot.session.student_cutoffs,
            "student_attention_state": snapshot.student.attention_state,
            "student_time_in_state": snapshot.student.time_in_attention_state_seconds,
            "session_type": self._session_type,
        }

    def evaluate(
        self,
        snapshot: MetricsSnapshot,
        elapsed_seconds: float,
        *,
        now: float | None = None,
    ) -> CoachingEvaluation:
        """Evaluate rules and return a trace-friendly decision object."""
        now = time.time() if now is None else now
        evaluation = CoachingEvaluation()

        # Compute effective thresholds from settings * intensity multiplier.
        # Reading settings dynamically keeps test-time patching effective.
        multiplier = self._intensity_multiplier
        if multiplier is None:
            # "off" intensity — no nudges ever fire
            evaluation.suppressed_reasons.append("global_nudge_budget_exhausted")
            return evaluation

        effective_warmup = settings.global_nudge_warmup_seconds * multiplier
        effective_interval = settings.global_nudge_min_interval_seconds * multiplier
        if self._intensity == "aggressive":
            effective_max = settings.global_nudge_max_per_session * 2
        elif self._intensity == "subtle":
            effective_max = max(1, settings.global_nudge_max_per_session - 1)
        else:
            effective_max = settings.global_nudge_max_per_session

        # Global safety rails for minimal, high-precision live coaching.
        if snapshot.degraded:
            evaluation.suppressed_reasons.append("session_degraded")
            return evaluation
        if elapsed_seconds < effective_warmup:
            evaluation.suppressed_reasons.append("global_warmup")
            return evaluation
        if self._session_nudges_sent >= effective_max:
            evaluation.suppressed_reasons.append("global_nudge_budget_exhausted")
            return evaluation
        if (
            self._last_nudge_at is not None
            and now - self._last_nudge_at < effective_interval
        ):
            evaluation.suppressed_reasons.append("global_min_interval")
            return evaluation

        matched_rules: list[CoachingRule] = []
        for rule in self._rules:
            evaluation.candidates_evaluated.append(rule.name)

            if elapsed_seconds < rule.min_session_elapsed:
                evaluation.suppressed_reasons.append(f"rule_min_elapsed:{rule.name}")
                continue

            last = self._last_fired.get(rule.name, 0.0)
            effective_cooldown = rule.cooldown_seconds * multiplier
            if now - last < effective_cooldown:
                evaluation.suppressed_reasons.append(f"rule_cooldown:{rule.name}")
                continue

            # Selective visual-confidence gate: only suppress visual rules
            # when confidence is low. Audio-based rules (interruptions, tech
            # check) should still fire even with poor visual data.
            if rule.requires_visual_confidence:
                if snapshot.student.attention_state_confidence < 0.4:
                    evaluation.suppressed_reasons.append(
                        f"low_visual_confidence:{rule.name}"
                    )
                    continue

            if rule.condition(snapshot, elapsed_seconds, self._profile):
                evaluation.candidate_nudges.append(rule.nudge_type)
                matched_rules.append(rule)

        if not matched_rules:
            return evaluation

        selected_rule = matched_rules[0]
        trigger_features = self._trigger_features(snapshot)
        nudge = Nudge(
            nudge_type=selected_rule.nudge_type,
            message=selected_rule.message_template,
            priority=selected_rule.priority,
            trigger_metrics=trigger_features,
        )
        self._last_fired[selected_rule.name] = now
        self._last_nudge_at = now
        self._session_nudges_sent += 1

        evaluation.nudges = [nudge]
        evaluation.emitted_nudge_type = nudge.nudge_type
        evaluation.fired_rule = selected_rule.name
        evaluation.trigger_features = trigger_features
        return evaluation

    def check(
        self,
        snapshot: MetricsSnapshot,
        elapsed_seconds: float,
    ) -> list[Nudge]:
        """Backward-compatible wrapper returning only emitted nudges."""
        return self.evaluate(snapshot, elapsed_seconds).nudges

    def reset_cooldown(self, rule_name: str):
        """Reset cooldown for a specific rule (for testing)."""
        self._last_fired.pop(rule_name, None)

    def reset_all_cooldowns(self):
        """Reset all cooldowns."""
        self._last_fired.clear()
        self._last_nudge_at = None
        self._session_nudges_sent = 0
