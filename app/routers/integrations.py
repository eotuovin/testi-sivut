from __future__ import annotations

import json
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import text

from app.auth import Principal, require_admin, require_read
from app.db import db_conn
from app.services.integrations.base import ADAPTERS
from app.services.integrations.dispatcher import deliveries_for_target, retry_event
from app.services.outbox import EVENT_TYPES

router = APIRouter()


class TargetIn(BaseModel):
    kind: str
    name: str = Field(min_length=1, max_length=120)
    config: dict = Field(default_factory=dict, description="url/base_url/path/secret_env… no secrets inline")
    event_types: list[str] = Field(default_factory=lambda: ["*"])
    enabled: bool = True


class TargetPatch(BaseModel):
    name: str | None = None
    config: dict | None = None
    event_types: list[str] | None = None
    enabled: bool | None = None


def _validate(kind: str, config: dict, event_types: list[str]):
    if kind not in ADAPTERS:
        raise HTTPException(status_code=422, detail=f"kind must be one of {sorted(ADAPTERS)}")
    for key, value in config.items():
        if isinstance(value, str) and any(s in key.lower() for s in ("secret", "token", "key", "password")) and key != "secret_env":
            raise HTTPException(status_code=422, detail=f"put the secret in an env var and reference it as secret_env, not in {key}")
    for t in event_types:
        if t != "*" and not t.endswith(".*") and t not in EVENT_TYPES:
            raise HTTPException(status_code=422, detail=f"unknown event type {t}; known: {sorted(EVENT_TYPES)}")


@router.get("/integrations/targets")
def list_targets(_: Principal = Depends(require_read)):
    with db_conn() as conn:
        rows = conn.execute(
            text(
                """
                SELECT t.*,
                  (SELECT count(*) FROM integration_deliveries d WHERE d.target_id=t.id AND d.status='failed') AS failed,
                  (SELECT max(updated_at) FROM integration_deliveries d WHERE d.target_id=t.id AND d.status='ok') AS last_ok_at
                FROM integration_targets t ORDER BY created_at
                """
            )
        ).mappings().all()
    return [dict(r) for r in rows]


@router.post("/integrations/targets", status_code=201)
def create_target(body: TargetIn, _: Principal = Depends(require_admin)):
    _validate(body.kind, body.config, body.event_types)
    with db_conn() as conn:
        row = conn.execute(
            text(
                "INSERT INTO integration_targets (kind, name, config, event_types, enabled) "
                "VALUES (:k, :n, CAST(:c AS jsonb), :e, :en) RETURNING *"
            ),
            {"k": body.kind, "n": body.name, "c": json.dumps(body.config), "e": body.event_types, "en": body.enabled},
        ).mappings().one()
    return dict(row)


@router.patch("/integrations/targets/{target_id}")
def patch_target(target_id: UUID, body: TargetPatch, _: Principal = Depends(require_admin)):
    with db_conn() as conn:
        current = conn.execute(text("SELECT * FROM integration_targets WHERE id=:id"), {"id": target_id}).mappings().first()
        if current is None:
            raise HTTPException(status_code=404, detail="target not found")
        config = body.config if body.config is not None else current["config"]
        event_types = body.event_types if body.event_types is not None else list(current["event_types"])
        _validate(current["kind"], config, event_types)
        row = conn.execute(
            text(
                "UPDATE integration_targets SET name=COALESCE(:n,name), config=CAST(:c AS jsonb), event_types=:e, "
                "enabled=COALESCE(:en, enabled) WHERE id=:id RETURNING *"
            ),
            {"n": body.name, "c": json.dumps(config), "e": event_types, "en": body.enabled, "id": target_id},
        ).mappings().one()
    return dict(row)


@router.delete("/integrations/targets/{target_id}")
def delete_target(target_id: UUID, _: Principal = Depends(require_admin)):
    with db_conn() as conn:
        conn.execute(text("DELETE FROM integration_targets WHERE id=:id"), {"id": target_id})
    return {"ok": True}


@router.get("/integrations/targets/{target_id}/deliveries")
def target_deliveries(target_id: UUID, limit: int = Query(50, le=500), _: Principal = Depends(require_read)):
    return deliveries_for_target(target_id, limit)


@router.get("/integrations/events")
def list_events(status: str | None = None, limit: int = Query(100, le=1000), _: Principal = Depends(require_read)):
    with db_conn() as conn:
        rows = conn.execute(
            text(
                "SELECT id, event_type, aggregate_type, aggregate_id, status, attempts, next_retry_at, last_error, created_at, delivered_at "
                "FROM outbox_events WHERE (:st IS NULL OR status=:st) ORDER BY created_at DESC LIMIT :l"
            ),
            {"st": status, "l": limit},
        ).mappings().all()
    return [dict(r) for r in rows]


@router.get("/integrations/events/{event_id}")
def get_event(event_id: UUID, _: Principal = Depends(require_read)):
    with db_conn() as conn:
        row = conn.execute(text("SELECT * FROM outbox_events WHERE id=:id"), {"id": event_id}).mappings().first()
        if row is None:
            raise HTTPException(status_code=404, detail="event not found")
        deliveries = conn.execute(
            text("SELECT d.*, t.name AS target_name, t.kind FROM integration_deliveries d JOIN integration_targets t ON t.id=d.target_id WHERE d.event_id=:id"),
            {"id": event_id},
        ).mappings().all()
    return {**dict(row), "deliveries": [dict(d) for d in deliveries]}


@router.post("/integrations/events/{event_id}/retry")
def retry(event_id: UUID, _: Principal = Depends(require_admin)):
    retry_event(event_id)
    return {"ok": True}


@router.get("/integrations/catalog")
def catalog(_: Principal = Depends(require_read)):
    return {"kinds": sorted(ADAPTERS), "event_types": sorted(EVENT_TYPES)}
