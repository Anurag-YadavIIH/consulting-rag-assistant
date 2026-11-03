"""
Audit logs. Every ingestion, deletion and query is recorded with a timestamp,
the user and what was touched. In a confidentiality-sensitive setting this is
what lets compliance answer "who accessed this client's material and when".

Redaction counts are logged, but the redacted *values* never are.

Two backends:

  * AuditLog: an append-only JSON-lines file, used by the offline CLI. Its
    query events include the question text (it never leaves the machine).
  * PgAuditLog: the `audit_events` table in Postgres, used by the API so the
    record survives container restarts. It deliberately stores NO question
    text, chunk text, document content or email addresses: only IDs, names
    and counts. Ingest and delete events are written inside the same
    transaction as the change itself (see PgVectorStore), so if the audit
    write fails the change rolls back. Query events are written separately;
    a failed write is logged and the query still succeeds.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger(__name__)


class AuditLog:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def _write(self, event: dict) -> None:
        event["ts"] = datetime.now(timezone.utc).isoformat()
        with open(self.path, "a", encoding="utf-8") as f:
            f.write(json.dumps(event) + "\n")

    def log_ingest(self, source_path: str, n_chunks: int,
                   redaction_counts: dict, user_id: str = "system",
                   engagement: str | None = None) -> None:
        self._write(
            {
                "event": "ingest",
                "user_id": user_id,
                "engagement": engagement,
                "source_path": source_path,
                "n_chunks": n_chunks,
                "redaction_counts": redaction_counts,
            }
        )

    def log_delete(self, source_path: str, n_chunks: int, user_id: str,
                   engagement: str | None = None) -> None:
        self._write(
            {
                "event": "delete",
                "user_id": user_id,
                "engagement": engagement,
                "source_path": source_path,
                "n_chunks": n_chunks,
            }
        )

    def log_query(self, user_id: str, query: str,
                  retrieved_ids: list[str], n_blocked: int,
                  engagement: str | None = None) -> None:
        self._write(
            {
                "event": "query",
                "user_id": user_id,
                "engagement": engagement,
                "query": query,
                "retrieved_ids": retrieved_ids,
                "n_blocked_by_access": n_blocked,
            }
        )


# --- Postgres -------------------------------------------------------------------

AUDIT_EVENT_TYPES = ("ingest", "delete", "query")


def ensure_audit_schema(conn) -> None:
    """Idempotent DDL for the API's audit table. Called by
    scripts/migrate_pg.py and when PgAuditLog starts."""
    with conn.cursor() as cur:
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS audit_events (
                id BIGSERIAL PRIMARY KEY,
                ts TIMESTAMPTZ NOT NULL DEFAULT now(),
                event TEXT NOT NULL CHECK (event IN ('ingest', 'delete', 'query')),
                user_id TEXT NOT NULL,
                engagement TEXT,
                document TEXT,
                n_chunks INT,
                redaction_counts JSONB,
                n_retrieved INT,
                n_blocked INT
            )
            """
        )
        cur.execute(
            "COMMENT ON TABLE audit_events IS "
            "'Who did what, when. No question text, chunk text, document content or emails.'"
        )
    conn.commit()


def _safe_document_name(name: str) -> str:
    # Filenames are user input and aren't redacted for citations; for the
    # audit record, run them through the same redactor so an email (or other
    # identifier) typed into a filename isn't stored here.
    from .security.redaction import Redactor

    return Redactor().redact(name)[0]


def insert_audit_event(cur, event: dict) -> None:
    """Writes one event using the caller's cursor, so it joins the caller's
    transaction (PgVectorStore's add/replace/delete)."""
    from psycopg.types.json import Jsonb

    if event.get("event") not in AUDIT_EVENT_TYPES:
        raise ValueError(f"unknown audit event type: {event.get('event')!r}")
    row = {
        "event": event["event"],
        "user_id": str(event["user_id"]),
        "engagement": event.get("engagement"),
        "document": event.get("document"),
        "n_chunks": event.get("n_chunks"),
        "redaction_counts": Jsonb(event["redaction_counts"]) if event.get("redaction_counts") is not None else None,
        "n_retrieved": event.get("n_retrieved"),
        "n_blocked": event.get("n_blocked"),
    }
    cur.execute(
        """
        INSERT INTO audit_events
            (event, user_id, engagement, document, n_chunks, redaction_counts, n_retrieved, n_blocked)
        VALUES (%(event)s, %(user_id)s, %(engagement)s, %(document)s, %(n_chunks)s,
                %(redaction_counts)s, %(n_retrieved)s, %(n_blocked)s)
        """,
        row,
    )


class PgAuditLog:
    """Audit log in Postgres, sharing PgVectorStore's connection pool.

    `transactional` tells the ingestion pipeline to hand ingest and delete
    events to the store, which writes them in the same transaction as the
    change. Query events go through log_query()."""

    transactional = True

    def __init__(self, pool):
        self._pool = pool
        with self._pool.connection() as conn:
            ensure_audit_schema(conn)

    @staticmethod
    def ingest_event(*, user_id: str, engagement: str | None, document: str,
                     n_chunks: int, redaction_counts: dict) -> dict:
        return {
            "event": "ingest", "user_id": user_id, "engagement": engagement,
            "document": _safe_document_name(document), "n_chunks": n_chunks,
            "redaction_counts": redaction_counts,
        }

    @staticmethod
    def delete_event(*, user_id: str, engagement: str, document: str, n_chunks: int) -> dict:
        return {
            "event": "delete", "user_id": user_id, "engagement": engagement,
            "document": _safe_document_name(document), "n_chunks": n_chunks,
        }

    def log_query(self, user_id: str, query: str, retrieved_ids: list[str],
                  n_blocked: int, engagement: str | None = None) -> None:
        # `query` and the retrieved chunk IDs are accepted for interface
        # parity with AuditLog but never stored: only counts.
        event = {
            "event": "query", "user_id": user_id, "engagement": engagement,
            "n_retrieved": len(retrieved_ids), "n_blocked": n_blocked,
        }
        try:
            with self._pool.connection() as conn, conn.transaction(), conn.cursor() as cur:
                insert_audit_event(cur, event)
        except Exception as e:
            # A query shouldn't fail because its audit record couldn't be
            # written, but the gap must be visible. Never log the question.
            logger.error("audit write failed for a query event (%s); the query still succeeded",
                         type(e).__name__)

    def recent(self, *, limit: int = 50, before: int | None = None,
               event: str | None = None) -> list[dict]:
        """Newest first. `before` is the id to page back from (exclusive);
        `event` keeps only one event type."""
        if event is not None and event not in AUDIT_EVENT_TYPES:
            raise ValueError(f"unknown audit event type: {event!r}")
        where: list[str] = []
        params: dict = {"limit": limit}
        if before is not None:
            where.append("id < %(before)s")
            params["before"] = before
        if event is not None:
            where.append("event = %(event)s")
            params["event"] = event
        sql = (
            "SELECT id, ts, event, user_id, engagement, document, n_chunks, "
            "redaction_counts, n_retrieved, n_blocked FROM audit_events "
        )
        if where:
            sql += "WHERE " + " AND ".join(where) + " "
        sql += "ORDER BY id DESC LIMIT %(limit)s"
        with self._pool.connection() as conn, conn.cursor() as cur:
            cur.execute(sql, params)
            cols = [d.name for d in cur.description]
            rows = [dict(zip(cols, r)) for r in cur.fetchall()]
        for r in rows:
            r["ts"] = r["ts"].astimezone(timezone.utc).isoformat()
        return rows
