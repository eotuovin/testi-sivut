"""INBOUND_API_KEY: another of our services (the Avora website) gets a "write"
key installed from env at startup, and can create a company + contact with it."""
import uuid

from fastapi.testclient import TestClient
from sqlalchemy import text

from app import main
from app.config import settings
from app.db import db_conn
from tests.conftest import unique


def _install(monkeypatch, plain: str, name: str) -> None:
    monkeypatch.setattr(settings, "INBOUND_API_KEY", plain)
    monkeypatch.setattr(settings, "INBOUND_API_KEY_NAME", name)
    main.bootstrap_inbound_api_key()


def _active_keys(name: str) -> list[dict]:
    with db_conn() as conn:
        rows = conn.execute(text("SELECT scopes, active FROM api_keys WHERE name = :n"), {"n": name}).mappings().all()
    return [dict(r) for r in rows]


def test_inbound_key_can_create_company_and_contact(monkeypatch):
    plain, name = uuid.uuid4().hex, unique("avora")
    _install(monkeypatch, plain, name)

    client = TestClient(main.app)
    auth = {"Authorization": f"Bearer {plain}"}
    r = client.post("/api/companies", json={"name": unique("Kampaamo"), "notes": "Avora-esittelypyyntö", "source": "manual"}, headers=auth)
    assert r.status_code == 201, r.text
    r2 = client.post(f"/api/companies/{r.json()['id']}/contacts",
                     json={"name": "Testi Henkilö", "phone": "0401234567", "is_primary": True}, headers=auth)
    assert r2.status_code == 201, r2.text

    # Write scope only: admin endpoints stay closed.
    assert client.get("/api/api-keys", headers=auth).status_code == 403


def test_startup_is_idempotent_and_rotation_revokes_old_key(monkeypatch):
    name = unique("avora")
    old, new = uuid.uuid4().hex, uuid.uuid4().hex
    _install(monkeypatch, old, name)
    _install(monkeypatch, old, name)  # restart with the same value
    assert _active_keys(name) == [{"scopes": ["write"], "active": True}]

    _install(monkeypatch, new, name)
    assert sorted(k["active"] for k in _active_keys(name)) == [False, True]

    client = TestClient(main.app)
    assert client.post("/api/companies", json={"name": unique("Vanha")}, headers={"Authorization": f"Bearer {old}"}).status_code == 401
    assert client.post("/api/companies", json={"name": unique("Uusi")}, headers={"Authorization": f"Bearer {new}"}).status_code == 201


def test_no_key_configured_installs_nothing(monkeypatch):
    name = unique("avora")
    _install(monkeypatch, None, name)
    assert _active_keys(name) == []
