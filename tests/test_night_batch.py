"""Claim a specific task, queue summary, bulk status, contact do-not-call, campaign clear-queue."""
import random

from sqlalchemy import text

from app.db import db_conn
from tests.conftest import unique


def _co(client, **kw):
    return client.post("/api/companies", json={"name": unique("Yöfirma"), "business_id": f"{random.randint(1000000, 9999999)}-{random.randint(0, 9)}", **kw}).json()


def _phone():
    return f"040 {random.randint(100, 999)} {random.randint(1000, 9999)}"


def test_claim_specific_task_and_queue_summary(admin_client, sales_client):
    camp = admin_client.post("/api/campaigns", json={"name": unique("Claim"), "product": "Esittely"}).json()
    a, b = _co(admin_client), _co(admin_client)
    for c in (a, b):
        admin_client.post(f"/api/companies/{c['id']}/contacts", json={"name": "X", "phone": _phone()})
    admin_client.post(f"/api/campaigns/{camp['id']}/enqueue", json={"company_ids": [a["id"], b["id"]]})
    with db_conn() as conn:
        tb = conn.execute(text("SELECT id FROM call_tasks WHERE campaign_id=:c AND company_id=:co"), {"c": camp["id"], "co": b["id"]}).scalar_one()

    q = admin_client.get("/api/calls/queue", params={"campaign_id": camp["id"]}).json()
    assert q["due_now"] == 2 and q["in_progress"] == 0

    r = admin_client.post(f"/api/calls/tasks/{tb}/claim")
    assert r.status_code == 200 and r.json()["company_id"] == b["id"] and r.json()["status"] == "in_progress"
    # someone else cannot take it; the owner can re-claim (reload)
    assert sales_client.post(f"/api/calls/tasks/{tb}/claim").status_code == 409
    assert admin_client.post(f"/api/calls/tasks/{tb}/claim").status_code == 200
    q = admin_client.get("/api/calls/queue", params={"campaign_id": camp["id"]}).json()
    assert q["due_now"] == 1 and q["in_progress"] == 1
    # after logging, it is done and cannot be claimed
    admin_client.post("/api/calls", json={"task_id": str(tb), "outcome": "not_interested"})
    assert admin_client.post(f"/api/calls/tasks/{tb}/claim").status_code == 409
    assert admin_client.post(f"/api/calls/tasks/{random.randint(10**9, 10**10)}/claim").status_code == 422


def test_bulk_status_and_contact_dnc(admin_client):
    a, b = _co(admin_client), _co(admin_client)
    r = admin_client.post("/api/companies/bulk-status", json={"company_ids": [a["id"], b["id"]], "status": "disqualified"})
    assert r.status_code == 200 and r.json()["updated"] == 2
    assert admin_client.get(f"/api/companies/{a['id']}").json()["status"] == "disqualified"
    assert admin_client.post("/api/companies/bulk-status", json={"company_ids": [a["id"]], "status": "disqualified"}).json()["updated"] == 0
    assert admin_client.post("/api/companies/bulk-status", json={"company_ids": [a["id"]], "status": "nope"}).status_code == 422

    ct = admin_client.post(f"/api/companies/{a['id']}/contacts", json={"name": "Kielto", "phone": _phone()}).json()
    r = admin_client.post(f"/api/contacts/{ct['id']}/do-not-call", json={"do_not_call": True, "blacklist_number": True, "reason": "pyysi"})
    assert r.status_code == 200
    with db_conn() as conn:
        assert conn.execute(text("SELECT do_not_call FROM contacts WHERE id=:id"), {"id": ct["id"]}).scalar_one() is True
        assert conn.execute(text("SELECT reason FROM do_not_call WHERE phone_e164=:p"), {"p": ct["phone_e164"]}).scalar_one() == "pyysi"
    # lifting it removes the number from the global list too
    admin_client.post(f"/api/contacts/{ct['id']}/do-not-call", json={"do_not_call": False})
    with db_conn() as conn:
        assert conn.execute(text("SELECT do_not_call FROM contacts WHERE id=:id"), {"id": ct["id"]}).scalar_one() is False
        assert conn.execute(text("SELECT 1 FROM do_not_call WHERE phone_e164=:p"), {"p": ct["phone_e164"]}).first() is None


def test_campaign_queue_stats_and_clear(admin_client, sales_client):
    camp = admin_client.post("/api/campaigns", json={"name": unique("Clear"), "product": "Esittely"}).json()
    cos = [_co(admin_client) for _ in range(3)]
    for c in cos:
        admin_client.post(f"/api/companies/{c['id']}/contacts", json={"name": "X", "phone": _phone()})
    admin_client.post(f"/api/campaigns/{camp['id']}/enqueue", json={"company_ids": [c["id"] for c in cos]})
    task = admin_client.post("/api/calls/next", params={"campaign_id": camp["id"]}).json()
    admin_client.post("/api/calls", json={"task_id": task["id"], "outcome": "callback", "callback_at": "2030-01-01T10:00:00Z"})
    row = next(x for x in admin_client.get("/api/campaigns").json() if x["id"] == camp["id"])
    assert row["queued_tasks"] == 2 and row["callback_tasks"] == 1 and row["skipped_tasks"] == 0
    assert sales_client.post(f"/api/campaigns/{camp['id']}/clear-queue").status_code == 403
    assert admin_client.post(f"/api/campaigns/{camp['id']}/clear-queue").json()["skipped"] == 2
    row = next(x for x in admin_client.get("/api/campaigns").json() if x["id"] == camp["id"])
    assert row["queued_tasks"] == 0 and row["callback_tasks"] == 1 and row["skipped_tasks"] == 2
