from __future__ import annotations

from collections import deque


class SpeakingTimeTracker:
    """Tracks cumulative speaking time for cross-participant talk-time ratio.

    Since each participant has their own audio stream, we know exactly
    who is speaking without diarization.

    Also tracks recent windowed talk-time for coaching rules that need
    to detect recent conversation imbalances rather than cumulative ones.
    """

    def __init__(self, recent_window_seconds: float = 120.0):
        self._tutor_seconds: float = 0.0
        self._student_seconds: float = 0.0
        self._last_update: float = 0.0
        self._first_update: float | None = None
        self._last_tutor_speech_end: float | None = None
        self._last_student_speech_end: float | None = None
        self._tutor_speaking: bool = False
        self._student_speaking: bool = False

        self._tutor_turn_count: int = 0
        self._student_turn_count: int = 0
        self._current_tutor_monologue_start: float | None = None
        self._current_student_monologue_start: float | None = None
        self._last_student_response_latency_seconds: float = 0.0
        self._last_tutor_response_latency_seconds: float = 0.0

        # Windowed recent tracking: deque of (timestamp, tutor_speaking, student_speaking)
        self._recent_window_seconds = recent_window_seconds
        self._recent_events: deque[tuple[float, bool, bool, float]] = deque()
        # Each entry: (timestamp, tutor_speaking, student_speaking, chunk_duration)

    def update(
        self,
        timestamp: float,
        tutor_speaking: bool,
        student_speaking: bool,
        chunk_duration_s: float = 0.03,  # 30ms chunks
    ):
        """Record a speaking state update."""
        if self._first_update is None:
            self._first_update = timestamp

        previous_tutor_speaking = self._tutor_speaking
        previous_student_speaking = self._student_speaking
        chunk_end = timestamp + chunk_duration_s

        tutor_started = tutor_speaking and not previous_tutor_speaking
        student_started = student_speaking and not previous_student_speaking

        if tutor_started:
            self._tutor_turn_count += 1
            if (
                self._last_student_speech_end is not None
                and not student_speaking
                and timestamp >= self._last_student_speech_end
            ):
                self._last_tutor_response_latency_seconds = max(
                    0.0, timestamp - self._last_student_speech_end
                )

        if student_started:
            self._student_turn_count += 1
            if (
                self._last_tutor_speech_end is not None
                and not tutor_speaking
                and timestamp >= self._last_tutor_speech_end
            ):
                self._last_student_response_latency_seconds = max(
                    0.0, timestamp - self._last_tutor_speech_end
                )

        if tutor_speaking:
            self._tutor_seconds += chunk_duration_s
            self._last_tutor_speech_end = chunk_end
        if student_speaking:
            self._student_seconds += chunk_duration_s
            self._last_student_speech_end = chunk_end

        self._tutor_speaking = tutor_speaking
        self._student_speaking = student_speaking
        self._last_update = timestamp

        # Track active monologues.
        if tutor_speaking and not student_speaking:
            if self._current_tutor_monologue_start is None:
                self._current_tutor_monologue_start = timestamp
        else:
            self._current_tutor_monologue_start = None

        if student_speaking and not tutor_speaking:
            if self._current_student_monologue_start is None:
                self._current_student_monologue_start = timestamp
        else:
            self._current_student_monologue_start = None

        # Track recent window
        self._recent_events.append(
            (timestamp, tutor_speaking, student_speaking, chunk_duration_s)
        )
        self._prune_recent(timestamp)

    def _prune_recent(self, now: float):
        """Remove events older than the recent window."""
        cutoff = now - self._recent_window_seconds
        while self._recent_events and self._recent_events[0][0] < cutoff:
            self._recent_events.popleft()

    @property
    def tutor_speaking(self) -> bool:
        return self._tutor_speaking

    @property
    def student_speaking(self) -> bool:
        return self._student_speaking

    def tutor_ratio(self) -> float:
        """Get tutor's fraction of total talk time."""
        total = self._tutor_seconds + self._student_seconds
        if total < 0.001:
            return 0.0
        return self._tutor_seconds / total

    def student_ratio(self) -> float:
        """Get student's fraction of total talk time."""
        total = self._tutor_seconds + self._student_seconds
        if total < 0.001:
            return 0.0
        return self._student_seconds / total

    def recent_tutor_ratio(self, now: float | None = None) -> float:
        """Get tutor's fraction of talk time in the recent window."""
        if now is not None:
            self._prune_recent(now)

        tutor_s = 0.0
        student_s = 0.0
        for _, t_speaking, s_speaking, dur in self._recent_events:
            if t_speaking:
                tutor_s += dur
            if s_speaking:
                student_s += dur

        total = tutor_s + student_s
        if total < 0.001:
            return 0.0
        return tutor_s / total

    def recent_student_ratio(self, now: float | None = None) -> float:
        """Get student's fraction of talk time in the recent window."""
        if now is not None:
            self._prune_recent(now)

        tutor_s = 0.0
        student_s = 0.0
        for _, t_speaking, s_speaking, dur in self._recent_events:
            if t_speaking:
                tutor_s += dur
            if s_speaking:
                student_s += dur

        total = tutor_s + student_s
        if total < 0.001:
            return 0.0
        return student_s / total

    @property
    def tutor_seconds(self) -> float:
        return self._tutor_seconds

    @property
    def student_seconds(self) -> float:
        return self._student_seconds

    @property
    def tutor_turn_count(self) -> int:
        return self._tutor_turn_count

    @property
    def student_turn_count(self) -> int:
        return self._student_turn_count

    @property
    def last_student_response_latency_seconds(self) -> float:
        return self._last_student_response_latency_seconds

    @property
    def last_tutor_response_latency_seconds(self) -> float:
        return self._last_tutor_response_latency_seconds

    def student_silence_duration(self, current_time: float) -> float:
        """Estimate how long the student has been silent."""
        if self._student_speaking:
            return 0.0

        if self._last_student_speech_end is not None:
            return max(0.0, current_time - self._last_student_speech_end)

        if self._first_update is None:
            return 0.0

        return max(0.0, current_time - self._first_update)

    def time_since_student_spoke(self, current_time: float) -> float:
        """Alias with clearer semantics for tutoring/coaching logic."""
        return self.student_silence_duration(current_time)

    def mutual_silence_duration(self, current_time: float) -> float:
        """How long both participants have been silent simultaneously."""
        if self._tutor_speaking or self._student_speaking:
            return 0.0

        candidates = [
            value
            for value in (self._last_tutor_speech_end, self._last_student_speech_end)
            if value is not None
        ]
        if candidates:
            return max(0.0, current_time - max(candidates))

        if self._first_update is None:
            return 0.0

        return max(0.0, current_time - self._first_update)

    def current_tutor_monologue_duration(self, current_time: float) -> float:
        """How long the tutor has been speaking uninterrupted while the student is silent."""
        if (
            self._tutor_speaking
            and not self._student_speaking
            and self._current_tutor_monologue_start is not None
        ):
            return max(0.0, current_time - self._current_tutor_monologue_start)
        return 0.0

    def current_student_monologue_duration(self, current_time: float) -> float:
        """How long the student has been speaking uninterrupted while the tutor is silent."""
        if (
            self._student_speaking
            and not self._tutor_speaking
            and self._current_student_monologue_start is not None
        ):
            return max(0.0, current_time - self._current_student_monologue_start)
        return 0.0
