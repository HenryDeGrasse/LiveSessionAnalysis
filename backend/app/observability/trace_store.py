from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Dict, Optional

from .trace_models import SessionTrace
from ..config import settings


class SessionTraceStore:
    """Persist privacy-safe trace artifacts to local disk."""

    def __init__(self, trace_dir: Optional[str] = None):
        self._dir = Path(trace_dir or settings.trace_dir)
        self._dir.mkdir(parents=True, exist_ok=True)

    def _safe_session_id(self, session_id: str) -> str:
        return re.sub(r"[^a-zA-Z0-9_\-]", "_", session_id)

    def path(self, session_id: str) -> Path:
        return self._dir / f"{self._safe_session_id(session_id)}.json"

    def ndjson_path(self, session_id: str) -> Path:
        return self._dir / f"{self._safe_session_id(session_id)}.ndjson"

    def append_record(self, session_id: str, record: Dict[str, Any]) -> None:
        path = self.ndjson_path(session_id)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, sort_keys=True))
            handle.write("\n")

    def save(self, trace: SessionTrace) -> None:
        self.path(trace.session_id).write_text(
            trace.model_dump_json(indent=2),
            encoding="utf-8",
        )

    def load(self, session_id: str) -> Optional[SessionTrace]:
        path = self.path(session_id)
        if not path.exists():
            return None
        try:
            return SessionTrace.model_validate_json(path.read_text(encoding="utf-8"))
        except Exception:
            return None
