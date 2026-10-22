"""Outbox dispatcher: claims pending events (FOR UPDATE SKIP LOCKED, like
movingfirm-backend's ops.py), delivers each to every enabled target whose
event_types match, records a delivery row per target, retries with backoff
and dead-letters after MAX_ATTEMPTS."""
from __future__ import annotations

import logging
from typing import Any

import httpx
from sqlalchemy import text

from app.db import db_conn
from app.services.integrations.base import ADAPTERS, DeliveryResult

log = logging.getLogger(__name__)

MAX_ATTEMPTS = 8
BACKOFF_MINUTES = (1, 2, 5, 15, 30, 60, 120, 240)

CLAIM_SQL = """
UPDATE outbox_events SET claimed_until = now() + interval '2 minutes', attempts = attempts + 1
WHERE id = (
    SELECT id FROM outbox_events
    WHERE status = 'pending' AND next_retry_at <= now() AND (claimed_until IS NULL OR claimed_until < now())
    ORDER BY created_at LIMIT 1 FOR UPDATE SKIP LOCKED
)
RETURNING id, event_type, aggregate_type, aggregate_id, payload, attempts, created_at
"""


def _matches(target_types: list[str], event_type: str) -> bool:
    for t in target_types:
        if t == "*" or t == event_type or (t.endswith(".*") and event_type.startswith(t[:-1])):
            return True
    return False


def dispatch_one(client: httpx.Client) -> bool:
    """Returns True if an event was processed (so the caller loops again)."""
    with db_conn() as conn:
        event = conn.execute(text(CLAIM_SQL)).mappings().first()
        if event is None:
            return False
        event = dict(event)
        targets = conn.execute(
            text("SELECT id, kind, name, config, event_types FROM integration_targets WHERE enabled ORDER BY created_at")
        ).mappings().all()

    all_ok = True
    for target in targets:
        if not _matches(list(target["event_types"]), event["event_type"]):
            continue
        adapter_cls = ADAPTERS.get(target["kind"])
        if adapter_cls is None:
            result = DeliveryResult(ok=False, error=f"no adapter for kind {target['kind']}")
        else:
            try:
                result = adapter_cls(dict(target["config"] or {})).deliver(event, client)
            except Exception as exc:  # noqa: BLE001
                log.exception("adapter %s crashed", target["kind"])
                result = DeliveryResult(ok=False, error=str(exc)[:500])
        _record(event["id"], target["id"], result)
        if not result.ok and not result.skipped:
            all_ok = False

    with db_conn() as conn:
        if all_ok:
            conn.execute(
                text("UPDATE outbox_events SET status='delivered', delivered_at=now(), claimed_until=NULL, last_error=NULL WHERE id=:id"),
                {"id": event["id"]},
            )
        elif event["attempts"] >= MAX_ATTEMPTS:
            conn.execute(
                text("UPDATE outbox_events SET status='dead', claimed_until=NULL, last_error='max attempts reached' WHERE id=:id"),
                {"id": event["id"]},
            )
        else:
            delay = BACKOFF_MINUTES[min(event["attempts"], len(BACKOFF_MINUTES)) - 1]
            conn.execute(
                text(
                    "UPDATE outbox_events SET claimed_until=NULL, next_retry_at = now() + make_interval(mins => :m), "
                    "last_error='one or more targets failed' WHERE id=:id"
                ),
                {"m": delay, "id": event["id"]},
            )
    return True


def _record(event_id, target_id, result: DeliveryResult) -> None:
    if result.skipped:
        return
    with db_conn() as conn:
        conn.execute(
            text(
                """
                INSERT INTO integration_deliveries (event_id, target_id, status, attempts, response_code, response_body, last_error)
                VALUES (:e, :t, :st, 1, :code, :body, :err)
                ON CONFLICT (event_id, target_id) DO UPDATE SET
                    status = EXCLUDED.status, attempts = integration_deliveries.attempts + 1,
                    response_code = EXCLUDED.response_code, response_body = EXCLUDED.response_body, last_error = EXCLUDED.last_error
                """
            ),
            {
                "e": event_id, "t": target_id, "st": "ok" if result.ok else "failed",
                "code": result.response_code, "body": result.response_body, "err": result.error,
            },
        )


def retry_event(event_id) -> None:
    with db_conn() as conn:
        conn.execute(
            text("UPDATE outbox_events SET status='pending', attempts=0, next_retry_at=now(), claimed_until=NULL WHERE id=:id"),
            {"id": event_id},
        )


def deliveries_for_target(target_id, limit: int = 50) -> list[dict[str, Any]]:
    with db_conn() as conn:
        rows = conn.execute(
            text(
                "SELECT d.*, e.event_type FROM integration_deliveries d JOIN outbox_events e ON e.id=d.event_id "
                "WHERE d.target_id=:t ORDER BY d.updated_at DESC LIMIT :l"
            ),
            {"t": target_id, "l": limit},
        ).mappings().all()
    return [dict(r) for r in rows]
