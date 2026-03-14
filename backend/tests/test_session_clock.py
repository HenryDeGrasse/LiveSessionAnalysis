"""Tests for SessionClock – monotonic time alignment."""

from __future__ import annotations

from app.transcription.clock import SessionClock, _ActivePause, _PauseSegment


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class FakeMono:
    """Deterministic monotonic clock for testing."""

    def __init__(self, start: float = 1000.0) -> None:
        self._now = start

    def __call__(self) -> float:
        return self._now

    def advance(self, seconds: float) -> None:
        self._now += seconds


# ---------------------------------------------------------------------------
# Basic session_time
# ---------------------------------------------------------------------------


class TestSessionTime:
    def test_starts_at_zero(self):
        mono = FakeMono()
        clock = SessionClock(mono_fn=mono)
        assert clock.session_time() == 0.0

    def test_advances_with_monotonic(self):
        mono = FakeMono()
        clock = SessionClock(mono_fn=mono)
        mono.advance(5.0)
        assert clock.session_time() == 5.0

    def test_fractional_seconds(self):
        mono = FakeMono()
        clock = SessionClock(mono_fn=mono)
        mono.advance(0.123)
        assert abs(clock.session_time() - 0.123) < 1e-9


# ---------------------------------------------------------------------------
# Pause / resume accumulation
# ---------------------------------------------------------------------------


class TestPauseResume:
    def test_single_pause_resume(self):
        mono = FakeMono()
        clock = SessionClock(mono_fn=mono)

        # Pause at provider_audio_time=2.0, wall time = 1000.0
        clock.pause("tutor", provider_audio_time=2.0)
        mono.advance(3.0)  # paused for 3 seconds
        clock.resume("tutor")

        # Provider time 5.0 is after the pause start (2.0), so the 3s silence
        # gap is added back into session time.
        result = clock.provider_to_session_time(5.0, "tutor")
        assert abs(result - 8.0) < 1e-9  # 5.0 + 3.0

    def test_multiple_pause_resume(self):
        mono = FakeMono()
        clock = SessionClock(mono_fn=mono)

        clock.pause("tutor", provider_audio_time=1.0)
        mono.advance(2.0)
        clock.resume("tutor")

        clock.pause("tutor", provider_audio_time=5.0)
        mono.advance(1.0)
        clock.resume("tutor")

        # Provider time 6.0 is after both pauses → total added gap = 3.0
        result = clock.provider_to_session_time(6.0, "tutor")
        assert abs(result - 9.0) < 1e-9  # 6.0 + 2.0 + 1.0

    def test_double_pause_is_noop(self):
        mono = FakeMono()
        clock = SessionClock(mono_fn=mono)

        clock.pause("tutor", provider_audio_time=1.0)
        mono.advance(1.0)
        # Second pause should be ignored
        clock.pause("tutor", provider_audio_time=2.0)
        mono.advance(1.0)
        clock.resume("tutor")

        # Only one pause of 2s total from the first pause call
        result = clock.provider_to_session_time(3.0, "tutor")
        assert abs(result - 5.0) < 1e-9  # 3.0 + 2.0

    def test_resume_without_pause_is_noop(self):
        mono = FakeMono()
        clock = SessionClock(mono_fn=mono)

        # Should not raise
        clock.resume("tutor")

        # No offset applied
        result = clock.provider_to_session_time(5.0, "tutor")
        assert abs(result - 5.0) < 1e-9


# ---------------------------------------------------------------------------
# Provider-time-anchored pauses: late-arriving results NOT shifted
# ---------------------------------------------------------------------------


class TestLateResults:
    def test_late_result_before_pause_not_shifted(self):
        """STT result with provider time *before* a pause start must not
        be shifted by that pause."""
        mono = FakeMono()
        clock = SessionClock(mono_fn=mono)

        # Pause at provider time 10.0
        clock.pause("student-0", provider_audio_time=10.0)
        mono.advance(5.0)
        clock.resume("student-0")

        # Late result arrives with provider_audio_time=8.0 (before the pause)
        result = clock.provider_to_session_time(8.0, "student-0")
        assert abs(result - 8.0) < 1e-9  # NOT shifted

    def test_result_at_pause_boundary_is_shifted(self):
        """Provider time exactly at pause start IS shifted."""
        mono = FakeMono()
        clock = SessionClock(mono_fn=mono)

        clock.pause("student-0", provider_audio_time=10.0)
        mono.advance(2.0)
        clock.resume("student-0")

        result = clock.provider_to_session_time(10.0, "student-0")
        assert abs(result - 12.0) < 1e-9  # 10.0 + 2.0

    def test_result_after_pause_is_shifted(self):
        mono = FakeMono()
        clock = SessionClock(mono_fn=mono)

        clock.pause("tutor", provider_audio_time=5.0)
        mono.advance(3.0)
        clock.resume("tutor")

        result = clock.provider_to_session_time(12.0, "tutor")
        assert abs(result - 15.0) < 1e-9  # 12.0 + 3.0

    def test_mixed_late_and_current_results(self):
        """Two pauses; late result only affected by the first."""
        mono = FakeMono()
        clock = SessionClock(mono_fn=mono)

        # Pause 1: provider time 5.0, duration 2s
        clock.pause("tutor", provider_audio_time=5.0)
        mono.advance(2.0)
        clock.resume("tutor")

        # Pause 2: provider time 15.0, duration 4s
        clock.pause("tutor", provider_audio_time=15.0)
        mono.advance(4.0)
        clock.resume("tutor")

        # Late result at provider_time=7.0 → only pause 1 applies
        r1 = clock.provider_to_session_time(7.0, "tutor")
        assert abs(r1 - 9.0) < 1e-9  # 7.0 + 2.0

        # Current result at provider_time=20.0 → both pauses apply
        r2 = clock.provider_to_session_time(20.0, "tutor")
        assert abs(r2 - 26.0) < 1e-9  # 20.0 + 2.0 + 4.0


# ---------------------------------------------------------------------------
# Initial silence accounting
# ---------------------------------------------------------------------------


class TestInitialSilence:
    def test_no_pauses_identity(self):
        """Without pauses, provider time maps to itself."""
        mono = FakeMono()
        clock = SessionClock(mono_fn=mono)

        assert clock.provider_to_session_time(0.0, "tutor") == 0.0
        assert clock.provider_to_session_time(42.5, "tutor") == 42.5

    def test_early_silence_no_offset(self):
        """Without an explicit pause segment, elapsed wall-clock time alone
        does not affect the mapping."""
        mono = FakeMono()
        clock = SessionClock(mono_fn=mono)
        mono.advance(3.0)  # 3 seconds of silence on wall-clock

        # Provider reports first word at provider_audio_time=3.0
        result = clock.provider_to_session_time(3.0, "tutor")
        assert abs(result - 3.0) < 1e-9


# ---------------------------------------------------------------------------
# Reconnect reset
# ---------------------------------------------------------------------------


class TestReconnectReset:
    def test_reset_clears_completed_pauses(self):
        mono = FakeMono()
        clock = SessionClock(mono_fn=mono)

        clock.pause("tutor", provider_audio_time=1.0)
        mono.advance(5.0)
        clock.resume("tutor")

        # Before reset, the 5s pause is added back into the session mapping
        assert abs(clock.provider_to_session_time(10.0, "tutor") - 15.0) < 1e-9

        clock.reset_pauses("tutor")

        # After reset, no offset
        assert abs(clock.provider_to_session_time(10.0, "tutor") - 10.0) < 1e-9

    def test_reset_cancels_active_pause(self):
        mono = FakeMono()
        clock = SessionClock(mono_fn=mono)

        clock.pause("tutor", provider_audio_time=1.0)
        mono.advance(3.0)

        clock.reset_pauses("tutor")

        # Active pause was cancelled – no offset
        assert abs(clock.provider_to_session_time(5.0, "tutor") - 5.0) < 1e-9

    def test_reset_nonexistent_role_is_noop(self):
        mono = FakeMono()
        clock = SessionClock(mono_fn=mono)
        # Should not raise
        clock.reset_pauses("unknown-role")


# ---------------------------------------------------------------------------
# Multiple tracks independent
# ---------------------------------------------------------------------------


class TestMultipleTracks:
    def test_independent_pause_tracking(self):
        mono = FakeMono()
        clock = SessionClock(mono_fn=mono)

        # Pause tutor for 3s
        clock.pause("tutor", provider_audio_time=2.0)
        mono.advance(3.0)
        clock.resume("tutor")

        # Pause student for 1s
        clock.pause("student-0", provider_audio_time=4.0)
        mono.advance(1.0)
        clock.resume("student-0")

        # Tutor: 10.0 + 3.0 = 13.0
        assert abs(clock.provider_to_session_time(10.0, "tutor") - 13.0) < 1e-9

        # Student: 10.0 + 1.0 = 11.0
        assert abs(clock.provider_to_session_time(10.0, "student-0") - 11.0) < 1e-9

    def test_reset_one_does_not_affect_other(self):
        mono = FakeMono()
        clock = SessionClock(mono_fn=mono)

        # Pause both roles
        clock.pause("tutor", provider_audio_time=1.0)
        clock.pause("student-0", provider_audio_time=1.0)
        mono.advance(2.0)
        clock.resume("tutor")
        clock.resume("student-0")

        # Reset only tutor
        clock.reset_pauses("tutor")

        # Tutor has no offset
        assert abs(clock.provider_to_session_time(5.0, "tutor") - 5.0) < 1e-9

        # Student still has the 2s silence gap applied
        assert abs(clock.provider_to_session_time(5.0, "student-0") - 7.0) < 1e-9

    def test_unrelated_role_has_no_offset(self):
        mono = FakeMono()
        clock = SessionClock(mono_fn=mono)

        clock.pause("tutor", provider_audio_time=1.0)
        mono.advance(10.0)
        clock.resume("tutor")

        # A role that was never paused has no offset
        assert abs(clock.provider_to_session_time(5.0, "student-1") - 5.0) < 1e-9


# ---------------------------------------------------------------------------
# Active pause (unresolved) contributes to mapping
# ---------------------------------------------------------------------------


class TestActivePauseMapping:
    def test_active_pause_included_in_mapping(self):
        """While a pause is active, provider_to_session_time should account
        for the elapsed pause duration so far."""
        mono = FakeMono()
        clock = SessionClock(mono_fn=mono)

        clock.pause("tutor", provider_audio_time=5.0)
        mono.advance(3.0)

        # Still paused – 3s elapsed
        result = clock.provider_to_session_time(8.0, "tutor")
        assert abs(result - 11.0) < 1e-9  # 8.0 + 3.0

    def test_active_pause_not_applied_to_earlier_provider_time(self):
        mono = FakeMono()
        clock = SessionClock(mono_fn=mono)

        clock.pause("tutor", provider_audio_time=10.0)
        mono.advance(5.0)

        # Provider time before pause → not shifted
        result = clock.provider_to_session_time(7.0, "tutor")
        assert abs(result - 7.0) < 1e-9
