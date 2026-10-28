"""Write-side of the outbox. Call emit() inside the same transaction as the
business change so an event can never exist without its cause, or vice versa.

Event catalogue (keep in sync with README "Events"):
  company.created, company.updated, contact.created,
  call.logged, booking.created, booking.updated,
  prospecting.run_finished, prospect.approved,
  call.analyzed, insight.report_created,
  list.created, list.members_added, search.saved
"""
from __future__ import annotations

import json
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.engine import Connection

EVENT_TYPES = frozenset(
    {
        "company.created",
        "company.updated",
        "contact.created",
        "call.logged",
        "booking.created",
        "booking.updated",
        "prospecting.run_finished",
        "prospect.approved",
        "call.analyzed",
        "insight.report_created",
        "list.created",
        "list.members_added",
        "search.saved",
    }
)


def _json_default(value: Any):
    if isinstance(value, UUID):
        return str(value)
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return str(value)


def emit(conn: Connection, event_type: str, aggregate_type: str, aggregate_id: UUID, payload: dict) -> UUID:
    if event_type not in EVENT_TYPES:
        raise ValueError(f"unknown event type {event_type!r}")
    row = conn.execute(
        text(
            """
            INSERT INTO outbox_events (event_type, aggregate_type, aggregate_id, payload)
            VALUES (:t, :agg, :aid, CAST(:p AS jsonb))
            RETURNING id
            """
        ),
        {
            "t": event_type,
            "agg": aggregate_type,
            "aid": aggregate_id,
            "p": json.dumps(payload, default=_json_default),
        },
    ).scalar_one()
    return row
