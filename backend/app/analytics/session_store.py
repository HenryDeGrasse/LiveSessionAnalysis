from __future__ import annotations

import json
import os
import re
from datetime import datetime, timedelta
from typing import Optional

from ..models import SessionSummary
from ..config import settings


class SessionStore:
    """JSON file-based session persistence with retention enforcement."""

    def __init__(self, data_dir: str | None = None):
        self._dir = data_dir or settings.session_data_dir
        os.makedirs(self._dir, exist_ok=True)

    def _path(self, session_id: str) -> str:
        safe = re.sub(r"[^a-zA-Z0-9_\-]", "_", session_id)
        return os.path.join(self._dir, f"{safe}.json")

    def save(self, summary: SessionSummary) -> None:
        path = self._path(summary.session_id)
        with open(path, "w") as f:
            f.write(summary.model_dump_json(indent=2))

    def load(self, session_id: str) -> Optional[SessionSummary]:
        path = self._path(session_id)
        if not os.path.exists(path):
            return None
        try:
            with open(path) as f:
                data = json.load(f)
            return SessionSummary(**data)
        except (json.JSONDecodeError, Exception):
            return None

    def list_sessions(
        self,
        tutor_id: Optional[str] = None,
        student_user_id: Optional[str] = None,
        last_n: Optional[int] = None,
    ) -> list[SessionSummary]:
        sessions = []
        for fname in os.listdir(self._dir):
            if not fname.endswith(".json"):
                continue
            sid = fname[:-5]
            summary = self.load(sid)
            if summary is None:
                continue
            if tutor_id and summary.tutor_id != tutor_id:
                continue
            if student_user_id and summary.student_user_id != student_user_id:
                continue
            sessions.append(summary)
        # Sort by start_time descending (most recent first)
        sessions.sort(key=lambda s: s.start_time, reverse=True)
        if last_n is not None:
            sessions = sessions[:last_n]
        return sessions

    def delete(self, session_id: str) -> bool:
        path = self._path(session_id)
        if os.path.exists(path):
            os.remove(path)
            return True
        return False

    def cleanup_expired(self, retention_days: int | None = None) -> int:
        """Delete session files older than retention period.

        Returns the number of files deleted.
        """
        days = retention_days if retention_days is not None else settings.session_retention_days
        cutoff = datetime.utcnow() - timedelta(days=days)
        deleted = 0

        for fname in os.listdir(self._dir):
            if not fname.endswith(".json"):
                continue
            sid = fname[:-5]
            summary = self.load(sid)
            if summary is None:
                continue
            if summary.end_time < cutoff:
                self.delete(sid)
                deleted += 1

        return deleted
