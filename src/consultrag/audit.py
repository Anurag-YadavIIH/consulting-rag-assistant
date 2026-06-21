"""
Append-only audit log. Every ingestion and every query is recorded with a
timestamp, the user, and what was touched. In a confidentiality-sensitive
setting this is what lets compliance answer "who accessed this client's
material and when" — and it's a concrete, defensible feature to point to.

Redaction counts are logged, but the redacted *values* never are.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path


class AuditLog:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def _write(self, event: dict) -> None:
        event["ts"] = datetime.now(timezone.utc).isoformat()
        with open(self.path, "a", encoding="utf-8") as f:
            f.write(json.dumps(event) + "\n")

    def log_ingest(self, source_path: str, n_chunks: int,
                   redaction_counts: dict, user_id: str = "system") -> None:
        self._write(
            {
                "event": "ingest",
                "user_id": user_id,
                "source_path": source_path,
                "n_chunks": n_chunks,
                "redaction_counts": redaction_counts,
            }
        )

    def log_query(self, user_id: str, query: str,
                  retrieved_ids: list[str], n_blocked: int) -> None:
        self._write(
            {
                "event": "query",
                "user_id": user_id,
                "query": query,
                "retrieved_ids": retrieved_ids,
                "n_blocked_by_access": n_blocked,
            }
        )
