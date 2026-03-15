"""TranscriptStore – full-session utterance persistence store.

Accumulates every ``FinalUtterance`` for the lifetime of a session and
provides export helpers that produce payloads suitable for Postgres (compact,
word timings stripped except for key moments) and S3 (full fidelity).
"""

from __future__ import annotations

from dataclasses import asdict
from typing import Any, Dict, List, Optional, Set

from app.transcription.models import FinalUtterance


class TranscriptStore:
    """Append-only store of ``FinalUtterance`` objects for one session.

    Parameters
    ----------
    session_id:
        Unique session identifier attached to export payloads.
    """

    def __init__(self, session_id: str = "") -> None:
        self._session_id: str = session_id
        self._utterances: List[FinalUtterance] = []
        self._key_moment_ids: Set[str] = set()

    # ------------------------------------------------------------------
    # Mutation
    # ------------------------------------------------------------------

    def add(self, utterance: FinalUtterance) -> None:
        """Append an utterance to the store."""
        self._utterances.append(utterance)

    def mark_key_moment(self, utterance_id: str) -> None:
        """Flag an utterance as a key moment (preserves word timings in PG export)."""
        self._key_moment_ids.add(utterance_id)

    # ------------------------------------------------------------------
    # Export helpers
    # ------------------------------------------------------------------

    def to_postgres_payload(self) -> Dict[str, Any]:
        """Return a compact payload for Postgres storage.

        Word timings are stripped from non-key-moment utterances to keep the
        JSONB column small.
        """
        items: List[Dict[str, Any]] = []
        for u in self._utterances:
            d = self._utterance_to_dict(u)
            if u.utterance_id not in self._key_moment_ids:
                d.pop("words", None)
            items.append(d)
        return {
            "session_id": self._session_id,
            "utterances": items,
            "word_count": self._count_words(),
            "searchable_text": self._to_searchable_text(),
        }

    def to_s3_artifact(self) -> Dict[str, Any]:
        """Return a full-fidelity payload for S3 / artifact storage.

        All word timings are preserved.
        """
        items = [self._utterance_to_dict(u) for u in self._utterances]
        return {
            "session_id": self._session_id,
            "utterances": items,
            "word_count": self._count_words(),
            "searchable_text": self._to_searchable_text(),
        }

    # ------------------------------------------------------------------
    # Introspection
    # ------------------------------------------------------------------

    def __len__(self) -> int:
        return len(self._utterances)

    @property
    def utterances(self) -> List[FinalUtterance]:
        """Read-only access to stored utterances."""
        return list(self._utterances)

    @property
    def key_moment_ids(self) -> Set[str]:
        return set(self._key_moment_ids)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _utterance_to_dict(u: FinalUtterance) -> Dict[str, Any]:
        """Serialize a single utterance to a plain dict."""
        d = asdict(u)
        return d

    def _count_words(self) -> int:
        """Total word count across all stored utterances."""
        return sum(len(u.text.split()) for u in self._utterances)

    def _to_searchable_text(self) -> str:
        """Concatenated text for full-text search indexing."""
        return " ".join(u.text for u in self._utterances if u.text)
