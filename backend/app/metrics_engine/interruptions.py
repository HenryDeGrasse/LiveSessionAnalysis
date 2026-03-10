from __future__ import annotations

from collections import deque
from dataclasses import dataclass

from ..config import settings
from ..models import Role


@dataclass
class OverlapEvent:
    timestamp: float
    duration_s: float
    interrupter: Role | None = None
    interrupted: Role | None = None
    hard: bool = False
    cutoff: bool = False
    backchannel: bool = False
    echo_like: bool = False


class InterruptionTracker:
    """Tracks overlapping speech with fewer false positives.

    Overlaps are only counted once they persist for a minimum duration.
    Longer overlaps where the later speaker is not significantly quieter are
    treated as hard interruptions. Short or much quieter overlaps are tracked
    separately as backchannels, and repeated extremely quiet overlaps can mark
    the session as echo-suspected.
    """

    def __init__(self):
        self._count: int = 0
        self._hard_count: int = 0
        self._backchannel_count: int = 0
        self._timestamps: deque[float] = deque(maxlen=500)
        self._hard_timestamps: deque[float] = deque(maxlen=500)
        self._backchannel_timestamps: deque[float] = deque(maxlen=500)
        self._echo_like_timestamps: deque[float] = deque()
        self._tutor_cutoff_timestamps: deque[float] = deque(maxlen=500)
        self._student_cutoff_timestamps: deque[float] = deque(maxlen=500)
        self._completed_events: deque[OverlapEvent] = deque(maxlen=100)
        self._tutor_interrupts_student: int = 0
        self._student_interrupts_tutor: int = 0
        self._echo_suspected = False

        self._prev_tutor_speaking = False
        self._prev_student_speaking = False
        self._tutor_segment_start: float | None = None
        self._student_segment_start: float | None = None

        self._in_overlap = False
        self._overlap_start: float | None = None
        self._interrupter: Role | None = None
        self._interrupted: Role | None = None
        self._prior_speaker_duration_s: float = 0.0
        self._peak_tutor_rms_db: float = -100.0
        self._peak_student_rms_db: float = -100.0

    def update(
        self,
        timestamp: float,
        tutor_speaking: bool,
        student_speaking: bool,
        tutor_rms_db: float = -100.0,
        student_rms_db: float = -100.0,
    ) -> bool:
        """Update interruption state from smoothed speech activity.

        Returns True when interruption-related UI state changed enough that a
        faster live metrics push would be useful.
        """
        before_key = self.live_state_key(timestamp)

        tutor_started = tutor_speaking and not self._prev_tutor_speaking
        student_started = student_speaking and not self._prev_student_speaking

        if tutor_started:
            self._tutor_segment_start = timestamp
        if student_started:
            self._student_segment_start = timestamp

        both_now = tutor_speaking and student_speaking

        if both_now and not self._in_overlap:
            self._start_overlap(
                timestamp,
                tutor_started,
                student_started,
                tutor_rms_db,
                student_rms_db,
            )
        elif both_now and self._in_overlap:
            self._peak_tutor_rms_db = max(self._peak_tutor_rms_db, tutor_rms_db)
            self._peak_student_rms_db = max(
                self._peak_student_rms_db, student_rms_db
            )
        elif not both_now and self._in_overlap:
            self._finish_overlap(timestamp, tutor_speaking, student_speaking)

        self._prev_tutor_speaking = tutor_speaking
        self._prev_student_speaking = student_speaking
        return before_key != self.live_state_key(timestamp)

    def _start_overlap(
        self,
        timestamp: float,
        tutor_started: bool,
        student_started: bool,
        tutor_rms_db: float,
        student_rms_db: float,
    ):
        self._in_overlap = True
        self._overlap_start = timestamp
        self._peak_tutor_rms_db = tutor_rms_db
        self._peak_student_rms_db = student_rms_db
        self._interrupter = None
        self._interrupted = None
        self._prior_speaker_duration_s = 0.0

        if tutor_started and not student_started and self._student_segment_start is not None:
            self._interrupter = Role.TUTOR
            self._interrupted = Role.STUDENT
            self._prior_speaker_duration_s = max(
                0.0, timestamp - self._student_segment_start
            )
        elif student_started and not tutor_started and self._tutor_segment_start is not None:
            self._interrupter = Role.STUDENT
            self._interrupted = Role.TUTOR
            self._prior_speaker_duration_s = max(
                0.0, timestamp - self._tutor_segment_start
            )
        elif (
            self._tutor_segment_start is not None
            and self._student_segment_start is not None
        ):
            delta = self._tutor_segment_start - self._student_segment_start
            if abs(delta) <= settings.interruption_simultaneous_start_margin_seconds:
                self._interrupter = None
                self._interrupted = None
            elif delta > 0:
                self._interrupter = Role.TUTOR
                self._interrupted = Role.STUDENT
                self._prior_speaker_duration_s = delta
            else:
                self._interrupter = Role.STUDENT
                self._interrupted = Role.TUTOR
                self._prior_speaker_duration_s = -delta

    def _finish_overlap(
        self,
        timestamp: float,
        tutor_speaking: bool,
        student_speaking: bool,
    ):
        if self._overlap_start is None:
            self._reset_overlap_state()
            return

        duration_s = max(0.0, timestamp - self._overlap_start)
        event = OverlapEvent(
            timestamp=self._overlap_start,
            duration_s=duration_s,
            interrupter=self._interrupter,
            interrupted=self._interrupted,
        )

        self._classify_overlap(event, tutor_speaking, student_speaking)

        if duration_s > 0:
            self._completed_events.append(event)

        if duration_s >= settings.overlap_min_duration_seconds and not event.echo_like:
            self._count += 1
            self._timestamps.append(self._overlap_start)
            if event.backchannel:
                self._backchannel_count += 1
                self._backchannel_timestamps.append(self._overlap_start)

        self._reset_overlap_state()

    def _classify_overlap(
        self,
        event: OverlapEvent,
        tutor_speaking_after: bool,
        student_speaking_after: bool,
    ):
        if event.interrupter is None or event.interrupted is None:
            return

        interrupter_peak = (
            self._peak_tutor_rms_db
            if event.interrupter == Role.TUTOR
            else self._peak_student_rms_db
        )
        interrupted_peak = (
            self._peak_student_rms_db
            if event.interrupted == Role.STUDENT
            else self._peak_tutor_rms_db
        )
        quiet_margin_db = interrupted_peak - interrupter_peak

        event.backchannel = (
            event.duration_s < settings.hard_interruption_min_duration_seconds
            or quiet_margin_db >= settings.interruption_backchannel_quiet_margin_db
        )

        # If it qualifies as hard, override backchannel — they're mutually exclusive
        # (a loud, long overlap is an interruption, not a backchannel)

        interrupted_continues = (
            student_speaking_after if event.interrupted == Role.STUDENT else tutor_speaking_after
        )
        interrupter_drops = (
            not tutor_speaking_after if event.interrupter == Role.TUTOR else not student_speaking_after
        )
        event.echo_like = (
            quiet_margin_db >= settings.echo_suspect_quiet_margin_db
            and event.duration_s < settings.hard_interruption_min_duration_seconds
            and interrupted_continues
            and interrupter_drops
        )
        if event.echo_like:
            self._echo_like_timestamps.append(event.timestamp)
            self._prune_echo_like(event.timestamp)
            if len(self._echo_like_timestamps) >= settings.echo_suspect_repeat_count:
                self._echo_suspected = True

        hard_loud_enough = (
            interrupter_peak
            >= interrupted_peak - settings.interruption_hard_quiet_margin_db
        )

        if (
            not event.echo_like
            and event.duration_s >= settings.hard_interruption_min_duration_seconds
            and hard_loud_enough
            and self._prior_speaker_duration_s
            >= settings.interruption_prior_speaker_min_duration_seconds
        ):
            event.hard = True
            event.backchannel = False  # hard overrides backchannel
            self._hard_count += 1
            self._hard_timestamps.append(event.timestamp)
            if event.interrupter == Role.TUTOR:
                self._tutor_interrupts_student += 1
            else:
                self._student_interrupts_tutor += 1

        yielded_quickly = (
            event.duration_s <= settings.interruption_cutoff_yield_window_seconds
        )
        if event.interrupted == Role.STUDENT:
            interrupted_stopped = not student_speaking_after and tutor_speaking_after
        else:
            interrupted_stopped = not tutor_speaking_after and student_speaking_after

        if not event.echo_like and yielded_quickly and interrupted_stopped:
            event.cutoff = True
            if event.interrupter == Role.TUTOR:
                self._tutor_cutoff_timestamps.append(event.timestamp)
            else:
                self._student_cutoff_timestamps.append(event.timestamp)

    def _prune_echo_like(self, now: float):
        cutoff = now - settings.echo_suspect_window_seconds
        while self._echo_like_timestamps and self._echo_like_timestamps[0] < cutoff:
            self._echo_like_timestamps.popleft()

    def _reset_overlap_state(self):
        self._in_overlap = False
        self._overlap_start = None
        self._interrupter = None
        self._interrupted = None
        self._prior_speaker_duration_s = 0.0
        self._peak_tutor_rms_db = -100.0
        self._peak_student_rms_db = -100.0

    @property
    def total_count(self) -> int:
        return self._count

    @property
    def hard_count(self) -> int:
        return self._hard_count

    @property
    def backchannel_count(self) -> int:
        return self._backchannel_count

    @property
    def echo_suspected(self) -> bool:
        return self._echo_suspected

    @property
    def tutor_interrupts_student(self) -> int:
        return self._tutor_interrupts_student

    @property
    def student_interrupts_tutor(self) -> int:
        return self._student_interrupts_tutor

    @property
    def tutor_cutoffs(self) -> int:
        return len(self._tutor_cutoff_timestamps)

    @property
    def student_cutoffs(self) -> int:
        return len(self._student_cutoff_timestamps)

    def recent_count(self, window_seconds: float, current_time: float) -> int:
        cutoff = current_time - window_seconds
        return sum(1 for t in self._timestamps if t >= cutoff)

    def recent_hard_count(self, window_seconds: float, current_time: float) -> int:
        cutoff = current_time - window_seconds
        return sum(1 for t in self._hard_timestamps if t >= cutoff)

    def recent_backchannel_count(self, window_seconds: float, current_time: float) -> int:
        cutoff = current_time - window_seconds
        return sum(1 for t in self._backchannel_timestamps if t >= cutoff)

    def recent_tutor_cutoffs(self, window_seconds: float, current_time: float) -> int:
        cutoff = current_time - window_seconds
        return sum(1 for t in self._tutor_cutoff_timestamps if t >= cutoff)

    def recent_student_cutoffs(self, window_seconds: float, current_time: float) -> int:
        cutoff = current_time - window_seconds
        return sum(1 for t in self._student_cutoff_timestamps if t >= cutoff)

    def current_overlap_duration(self, current_time: float) -> float:
        if not self._in_overlap or self._overlap_start is None:
            return 0.0
        return max(0.0, current_time - self._overlap_start)

    def current_overlap_state(self, current_time: float) -> str:
        if not self._in_overlap or self._overlap_start is None:
            return "none"

        duration_s = self.current_overlap_duration(current_time)
        if duration_s < settings.overlap_min_duration_seconds:
            return "candidate"

        if self._interrupter is None or self._interrupted is None:
            return "meaningful"

        interrupter_peak = (
            self._peak_tutor_rms_db
            if self._interrupter == Role.TUTOR
            else self._peak_student_rms_db
        )
        interrupted_peak = (
            self._peak_student_rms_db
            if self._interrupted == Role.STUDENT
            else self._peak_tutor_rms_db
        )
        quiet_margin_db = interrupted_peak - interrupter_peak

        if (
            quiet_margin_db >= settings.echo_suspect_quiet_margin_db
            and duration_s < settings.hard_interruption_min_duration_seconds
        ):
            return "echo_like"

        if (
            duration_s >= settings.hard_interruption_min_duration_seconds
            and interrupter_peak
            >= interrupted_peak - settings.interruption_hard_quiet_margin_db
            and self._prior_speaker_duration_s
            >= settings.interruption_prior_speaker_min_duration_seconds
        ):
            return "hard"

        if quiet_margin_db >= settings.interruption_backchannel_quiet_margin_db:
            return "backchannel"

        return "meaningful"

    def live_state_key(self, current_time: float) -> tuple:
        duration_bucket = int(self.current_overlap_duration(current_time) / 0.25)
        return (
            self._in_overlap,
            self.total_count,
            self.hard_count,
            self.backchannel_count,
            self.echo_suspected,
            self.current_overlap_state(current_time),
            duration_bucket,
        )

    def drain_completed_events(self) -> list[OverlapEvent]:
        events = list(self._completed_events)
        self._completed_events.clear()
        return events

    @property
    def timestamps(self) -> list[float]:
        return list(self._timestamps)
