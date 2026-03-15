"""SessionClock – monotonic time alignment for the transcription pipeline.

Maps provider-relative audio timestamps to a unified session timeline.
Each role-key (e.g. ``"tutor"``, ``"student-0"``) maintains its own list of
pause segments so that muting or reconnection on one track does not shift
timestamps on another.

Provider timestamps advance only while audio is sent. Session time, however,
should continue advancing through silence gaps, so pause durations are ADDED to
provider-relative timestamps when mapping back onto the session timeline.

All wall-clock references use ``time.monotonic()`` exclusively – never
``time.time()`` – to avoid issues with NTP adjustments or daylight-saving
changes.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional


@dataclass(frozen=True)
class _PauseSegment:
    """A completed pause interval for a single role-key.

    Attributes
    ----------
    provider_time_start:
        The provider audio time at which the pause began (seconds).
    duration_s:
        Duration of the pause in seconds (monotonic wall-clock difference).
    """

    provider_time_start: float
    duration_s: float


@dataclass()
class _ActivePause:
    """An in-progress (not yet resumed) pause.

    Attributes
    ----------
    provider_time_start:
        The provider audio time at which the pause began (seconds).
    wall_start_mono:
        ``time.monotonic()`` snapshot when the pause was initiated.
    """

    provider_time_start: float
    wall_start_mono: float


class SessionClock:
    """Monotonic session clock with per-role pause tracking.

    Parameters
    ----------
    mono_fn:
        Callable returning a monotonic timestamp.  Defaults to
        ``time.monotonic``; override in tests for deterministic control.
    """

    def __init__(self, *, mono_fn=time.monotonic) -> None:
        self._mono_fn = mono_fn
        self._start: float = self._mono_fn()
        self._pauses: Dict[str, List[_PauseSegment]] = {}
        self._active_pauses: Dict[str, _ActivePause] = {}

    # -- Session-level helpers ------------------------------------------------

    def session_time(self) -> float:
        """Seconds elapsed since the clock was created (monotonic)."""
        return self._mono_fn() - self._start

    # -- Pause / resume management -------------------------------------------

    def pause(self, role_key: str, provider_audio_time: float) -> None:
        """Begin a pause for *role_key* at the given provider audio time.

        If the role is already paused the call is a no-op so callers don't
        need to guard against double-pause.
        """
        if role_key in self._active_pauses:
            return  # already paused – ignore
        self._active_pauses[role_key] = _ActivePause(
            provider_time_start=provider_audio_time,
            wall_start_mono=self._mono_fn(),
        )

    def resume(self, role_key: str) -> None:
        """End the active pause for *role_key*.

        If the role is not paused the call is a no-op.
        """
        active = self._active_pauses.pop(role_key, None)
        if active is None:
            return
        duration = self._mono_fn() - active.wall_start_mono
        self._pauses.setdefault(role_key, []).append(
            _PauseSegment(
                provider_time_start=active.provider_time_start,
                duration_s=duration,
            )
        )

    def reset_pauses(self, role_key: str) -> None:
        """Clear all pause segments for *role_key* (e.g. after reconnect).

        Also cancels any active pause for the role.
        """
        self._pauses.pop(role_key, None)
        self._active_pauses.pop(role_key, None)

    # -- Provider → session time mapping -------------------------------------

    def provider_to_session_time(
        self,
        provider_audio_time: float,
        role_key: str,
    ) -> float:
        """Convert a provider-relative timestamp to session time.

        Only pause segments whose ``provider_time_start`` is **≤**
        ``provider_audio_time`` contribute their offset.  This ensures that
        late-arriving STT results (with provider timestamps that precede
        a pause) are *not* incorrectly shifted by pauses that hadn't happened
        yet from the audio stream's perspective.
        """
        total_pause = 0.0
        for seg in self._pauses.get(role_key, []):
            if provider_audio_time >= seg.provider_time_start:
                total_pause += seg.duration_s

        # If there's an active (unresolved) pause and the provider time falls
        # after the pause start, count the elapsed wall-clock time so far.
        active = self._active_pauses.get(role_key)
        if active is not None and provider_audio_time >= active.provider_time_start:
            total_pause += self._mono_fn() - active.wall_start_mono

        return provider_audio_time + total_pause
