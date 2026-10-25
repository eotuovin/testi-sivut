"""The caller's loop against a real Postgres: campaign → enqueue → next task →
outcomes → booking → outbox events → dispatcher delivers to a webhook."""
import hashlib
import hmac
import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import httpx
from sqlalchemy import text

from app.db import db_conn
from app.services.integrations.dispatcher import dispatch_one
from tests.conftest import unique


def _unique_phone() -> str:
    import random
    return "045" + str(random.randint(1000000, 9999999))


def _make_company(client, name=None, phone=None):
    phone = phone or _unique_phone()
    r = client.post("/api/companies", json={"name": name or unique("Firma"), "business_id": unique("Y")[:9], "city": "Jyväskylä"})
    assert r.status_code == 201, r.text
    company = r.json()
    r = client.post(f"/api/companies/{company['id']}/contacts", json={"name": "Matti Meikäläinen", "phone": phone, "is_primary": True})
    assert r.status_code == 201, r.text
    return company, r.json()


def _make_campaign(admin_client, **kw):
    body = {"name": unique("Kampanja"), "product": "Testipalvelu", "script": "Hei, tässä ...", "max_attempts": 2, "retry_after_minutes": 5}
    body.update(kw)
    r = admin_client.post("/api/campaigns", json=body)
    assert r.status_code == 201, r.text
    return r.json()


def test_phone_is_canonicalised_and_dnc_blocks_enqueue(admin_client):
    company, contact = _make_company(admin_client, phone="+358 40 123 4567")
    assert contact["phone_e164"] == "+358401234567"
    # a second company with the same number, then blacklist it
    company2, _ = _make_company(admin_client, phone="040-1234567")
    r = admin_client.post("/api/do-not-call", json={"phone": "0401234567", "reason": "pyysi"})
    assert r.status_code == 201 and r.json()["phone_e164"] == "+358401234567"
    detail = admin_client.get(f"/api/companies/{company2['id']}").json()
    assert detail["contacts"][0]["do_not_call"] is True


def test_full_loop_books_and_emits_events(admin_client, sales_client):
    campaign = _make_campaign(admin_client)
    company, contact = _make_company(admin_client)
    r = admin_client.post(f"/api/campaigns/{campaign['id']}/enqueue", json={"company_ids": [company["id"]]})
    assert r.json() == {"enqueued": 1, "skipped_no_phone": 0}
    # idempotent
    assert admin_client.post(f"/api/campaigns/{campaign['id']}/enqueue", json={"company_ids": [company["id"]]}).json()["enqueued"] == 0

    task = sales_client.post("/api/calls/next", params={"campaign_id": campaign["id"]}).json()
    assert task and task["company_id"] == company["id"] and task["contact_id"] == contact["id"]
    assert task["status"] == "in_progress" and task["script"] == "Hei, tässä ..."

    # another caller must not get the same task while it is leased
    assert sales_client.post("/api/calls/next", params={"campaign_id": campaign["id"]}).json()["id"] == task["id"]
    assert admin_client.post("/api/calls/next", params={"campaign_id": campaign["id"]}).json() is None

    # no answer → back to queue with a future due_at
    r = sales_client.post("/api/calls", json={"task_id": task["id"], "outcome": "no_answer", "duration_seconds": 20})
    assert r.status_code == 201, r.text
    with db_conn() as conn:
        row = conn.execute(text("SELECT status, attempts, due_at > now() AS later FROM call_tasks WHERE id=:id"), {"id": task["id"]}).mappings().one()
    assert row["status"] == "queued" and row["attempts"] == 1 and row["later"] is True
    assert sales_client.post("/api/calls/next", params={"campaign_id": campaign["id"]}).json() is None  # not due yet

    with db_conn() as conn:
        conn.execute(text("UPDATE call_tasks SET due_at = now() WHERE id=:id"), {"id": task["id"]})
    task2 = sales_client.post("/api/calls/next", params={"campaign_id": campaign["id"]}).json()
    assert task2["id"] == task["id"] and task2["attempts"] == 1 and task2["last_outcome"] == "no_answer"

    # booked
    r = sales_client.post(
        "/api/calls",
        json={
            "task_id": task["id"], "outcome": "booked", "duration_seconds": 300, "notes": "Kiinnostui",
            "booking": {"scheduled_at": "2026-11-03T10:00:00+02:00", "value_eur": 490.0},
        },
    )
    assert r.status_code == 201, r.text
    booking = r.json()["booking"]
    assert booking["product"] == "Testipalvelu" and booking["status"] == "booked"
    with db_conn() as conn:
        t = conn.execute(text("SELECT status FROM call_tasks WHERE id=:id"), {"id": task["id"]}).scalar()
        c = conn.execute(text("SELECT status FROM companies WHERE id=:id"), {"id": company["id"]}).scalar()
        events = conn.execute(
            text("SELECT event_type FROM outbox_events WHERE aggregate_id IN (:b, :co) ORDER BY created_at"),
            {"b": booking["id"], "co": company["id"]},
        ).scalars().all()
    assert t == "done" and c == "qualified"  # a booked meeting; 'customer' only when the booking is completed
    assert "company.created" in events and "booking.created" in events

    stats = admin_client.get("/api/stats/overview", params={"days": 1}).json()
    me = next(u for u in stats["per_user"] if u["name"] == "Testi Myyjä" and u["booked"] >= 1)
    assert me["calls"] >= 2


def test_callback_is_assigned_to_caller_and_due_at_callback_time(admin_client, sales_client):
    campaign = _make_campaign(admin_client)
    company, _ = _make_company(admin_client)
    admin_client.post(f"/api/campaigns/{campaign['id']}/enqueue", json={"company_ids": [company["id"]]})
    task = sales_client.post("/api/calls/next", params={"campaign_id": campaign["id"]}).json()
    r = sales_client.post("/api/calls", json={"task_id": task["id"], "outcome": "callback", "callback_at": "2030-01-01T09:00:00+02:00"})
    assert r.status_code == 201, r.text
    cbs = sales_client.get("/api/calls/callbacks").json()
    assert any(c["task_id"] == task["id"] for c in cbs)
    assert not any(c["task_id"] == task["id"] for c in admin_client.get("/api/calls/callbacks").json())
    r = sales_client.post("/api/calls", json={"task_id": task["id"], "outcome": "callback"})
    assert r.status_code == 422


def test_do_not_call_outcome_blacklists_number(admin_client, sales_client):
    campaign = _make_campaign(admin_client)
    company, contact = _make_company(admin_client)
    admin_client.post(f"/api/campaigns/{campaign['id']}/enqueue", json={"company_ids": [company["id"]]})
    task = sales_client.post("/api/calls/next", params={"campaign_id": campaign["id"]}).json()
    r = sales_client.post("/api/calls", json={"task_id": task["id"], "outcome": "do_not_call"})
    assert r.status_code == 201, r.text
    dnc = {d["phone_e164"] for d in admin_client.get("/api/do-not-call").json()}
    assert contact["phone_e164"] in dnc
    assert admin_client.get(f"/api/companies/{company['id']}").json()["status"] == "do_not_call"


class _Receiver(BaseHTTPRequestHandler):
    received: list[tuple[dict, dict]] = []

    def do_POST(self):
        length = int(self.headers.get("content-length", 0))
        body = self.rfile.read(length)
        _Receiver.received.append((dict(self.headers), json.loads(body)))
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"ok")

    def log_message(self, *a):  # silence
        pass


def test_dispatcher_delivers_signed_webhook(admin_client, monkeypatch):
    server = HTTPServer(("127.0.0.1", 0), _Receiver)
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    monkeypatch.setenv("TEST_HOOK_SECRET", "hook-secret")
    try:
        with db_conn() as conn:
            conn.execute(text("UPDATE integration_targets SET enabled=false"))
            conn.execute(text("UPDATE outbox_events SET status='delivered' WHERE status='pending'"))
        r = admin_client.post(
            "/api/integrations/targets",
            json={"kind": "webhook", "name": unique("hook"), "config": {"url": f"http://127.0.0.1:{port}/in", "secret_env": "TEST_HOOK_SECRET"},
                  "event_types": ["company.*", "booking.created"]},
        )
        assert r.status_code == 201, r.text
        target = r.json()
        # secrets inline are rejected
        bad = admin_client.post("/api/integrations/targets", json={"kind": "webhook", "name": "x", "config": {"url": "http://x", "api_key": "abc"}})
        assert bad.status_code == 422

        company, _ = _make_company(admin_client)
        with httpx.Client(timeout=5) as client:
            while dispatch_one(client):
                pass
        bodies = [b for _, b in _Receiver.received if b["aggregate_id"] == company["id"]]
        assert bodies and bodies[0]["type"] == "company.created" and bodies[0]["data"]["name"] == company["name"]
        headers, _ = next((h, b) for h, b in _Receiver.received if b["aggregate_id"] == company["id"])
        raw_body = json.dumps(bodies[0], default=str)
        expected = hmac.new(b"hook-secret", f"{headers['X-Luuri-Timestamp']}.{raw_body}".encode(), hashlib.sha256).hexdigest()
        assert headers["X-Luuri-Signature"] == f"sha256={expected}"
        # contact.created was emitted but the target does not subscribe → no delivery row, event still delivered
        deliveries = admin_client.get(f"/api/integrations/targets/{target['id']}/deliveries").json()
        assert all(d["event_type"] != "contact.created" for d in deliveries)
        assert all(d["status"] == "ok" for d in deliveries)
        with db_conn() as conn:
            statuses = conn.execute(
                text("SELECT status FROM outbox_events WHERE aggregate_id=:id OR payload->>'company_id'=:id"), {"id": company["id"]}
            ).scalars().all()
        assert statuses and set(statuses) == {"delivered"}
    finally:
        server.shutdown()
        with db_conn() as conn:
            conn.execute(text("UPDATE integration_targets SET enabled=false WHERE id=:id"), {"id": target["id"]})


def test_sales_role_cannot_create_campaign(sales_client):
    assert sales_client.post("/api/campaigns", json={"name": "x", "product": "y"}).status_code == 403


def test_api_key_scopes(admin_client):
    r = admin_client.post("/api/api-keys", json={"name": unique("crm"), "scopes": ["read"]})
    assert r.status_code == 201
    key = r.json()["key"]
    from fastapi.testclient import TestClient
    anon = TestClient(admin_client.app)
    r = anon.get("/api/companies", headers={"Authorization": f"Bearer {key}"})
    assert r.status_code == 200
    r = anon.post("/api/companies", json={"name": "x"}, headers={"Authorization": f"Bearer {key}"})
    assert r.status_code == 403
    assert anon.get("/api/companies").status_code == 401
