from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Optional

from ..config import settings
from ..models import MetricsSnapshot, Nudge
from .rules import CoachingRule, DEFAULT_RULES


@dataclass
class CoachingEvaluation:
    nudges: list[Nudge] = field(default_factory=list)
    candidate_nudges: list[str] = field(default_factory=list)
    suppressed_reasons: list[str] = field(default_factory=list)
    emitted_nudge_type: Optional[str] = None
    trigger_features: dict = field(default_factory=dict)


class Coach:
    """Rule engine that converts MetricsSnapshots into coaching Nudges.

    Respects cooldowns and minimum session elapsed time.
    """

    def __init__(self, rules: list[CoachingRule] | None = None):
        self._rules = rules or DEFAULT_RULES
        self._last_fired: dict[str, float] = {}  # rule name -> timestamp
        self._last_nudge_at: float | None = None
        self._session_nudges_sent: int = 0

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

        # Global safety rails for minimal, high-precision live coaching.
        if snapshot.degraded:
            evaluation.suppressed_reasons.append("session_degraded")
            return evaluation
        if elapsed_seconds < settings.global_nudge_warmup_seconds:
            evaluation.suppressed_reasons.append("global_warmup")
            return evaluation
        if self._session_nudges_sent >= settings.global_nudge_max_per_session:
            evaluation.suppressed_reasons.append("global_nudge_budget_exhausted")
            return evaluation
        if (
            self._last_nudge_at is not None
            and now - self._last_nudge_at < settings.global_nudge_min_interval_seconds
        ):
            evaluation.suppressed_reasons.append("global_min_interval")
            return evaluation

        matched_rules: list[CoachingRule] = []
        for rule in self._rules:
            if elapsed_seconds < rule.min_session_elapsed:
                evaluation.suppressed_reasons.append(f"rule_min_elapsed:{rule.name}")
                continue

            last = self._last_fired.get(rule.name, 0.0)
            if now - last < rule.cooldown_seconds:
                evaluation.suppressed_reasons.append(f"rule_cooldown:{rule.name}")
                continue

            if rule.condition(snapshot, elapsed_seconds):
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
