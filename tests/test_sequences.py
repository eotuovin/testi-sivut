"""Sequences: enrol → the engine materialises steps on schedule (call → queue,
email → SMTP or inbox, task → inbox) and a 'stop' call outcome ends the chain."""
import random
import threading
from datetime import datetime, timedelta, timezone

from sqlalchemy import text

from app.db import db_conn
from app.services import sequences as engine
from tests.conftest import unique


def _bid():
    return f"{random.randint(1000000, 9999999)}-{random.randint(0, 9)}"


def _phone():
    return f"040 {random.randint(100, 999)} {random.randint(1000, 9999)}"


def _setup(client):
    camp = client.post("/api/campaigns", json={"name": unique("Seq-kampanja"), "product": "Esittely"}).json()
    co = client.post("/api/companies", json={"name": unique("Seqfirma"), "business_id": _bid(), "city": "Jyväskylä"}).json()
    ct = client.post(f"/api/companies/{co['id']}/contacts", json={"name": "Maija Meikäläinen", "title": "TJ", "phone": _phone(), "email": "maija@seqfirma.fi", "is_primary": True}).json()
    seq = client.post("/api/sequences", json={
        "name": unique("Esittelyketju"), "campaign_id": camp["id"],
        "steps": [
            {"kind": "email", "delay_days": 0, "title": "Hei {{etunimi}} – {{yritys}}", "body": "Moi {{etunimi}}, terveisin {{myyja}}"},
            {"kind": "call", "delay_days": 2},
            {"kind": "task", "delay_days": 1, "title": "LinkedIn-yhteys {{nimi}}"},
        ],
    })
    assert seq.status_code == 201, seq.text
    return camp, co, ct, seq.json()


def _due_now(enrollment_id):
    with db_conn() as conn:
        conn.execute(text("UPDATE sequence_enrollments SET next_at = now() - interval '1 minute' WHERE id=:id"), {"id": enrollment_id})


def _enrollment(client, seq_id):
    return client.get(f"/api/sequences/{seq_id}").json()["enrollments"][0]


def test_enrol_and_walk_steps_without_smtp(admin_client, monkeypatch):
    monkeypatch.setattr(engine.settings, "SMTP_HOST", None)
    camp, co, ct, seq = _setup(admin_client)
    r = admin_client.post(f"/api/sequences/{seq['id']}/enroll", json={"company_ids": [co["id"]]})
    assert r.status_code == 200 and r.json()["enrolled"] == 1, r.text
    assert admin_client.post(f"/api/sequences/{seq['id']}/enroll", json={"company_ids": [co["id"]]}).json()["skipped"] == 1  # already active
    enr = _enrollment(admin_client, seq["id"])
    assert enr["contact_id"] == ct["id"] and enr["current_step"] == 0

    # step 1: email with no SMTP → pending in the inbox, rendered from the template
    assert engine.tick() is True
    inbox = admin_client.get("/api/sequences/inbox", params={"status": "pending"}).json()
    mine = [a for a in inbox if a["company_id"] == co["id"]]
    assert len(mine) == 1 and mine[0]["kind"] == "email" and mine[0]["email_to"] == "maija@seqfirma.fi"
    assert mine[0]["subject"].startswith("Hei Maija – ") and "terveisin Testi Admin" in mine[0]["body"]
    enr = _enrollment(admin_client, seq["id"])
    assert enr["current_step"] == 1 and enr["status"] == "active"
    due = datetime.fromisoformat(enr["next_at"])
    assert timedelta(days=1, hours=23) < due - datetime.now(timezone.utc) < timedelta(days=2, minutes=1)

    # the seller sends it by hand and marks it done
    r = admin_client.post(f"/api/sequences/actions/{mine[0]['id']}/done", json={"status": "done"})
    assert r.status_code == 200 and r.json()["sent_via"] == "manual"

    # step 2 (not due yet): nothing happens; then force it → call task in the campaign queue
    assert engine.tick() is False
    _due_now(enr["id"])
    assert engine.tick() is True
    with db_conn() as conn:
        task = conn.execute(text("SELECT id, status, contact_id, priority FROM call_tasks WHERE campaign_id=:cp AND company_id=:co"), {"cp": camp["id"], "co": co["id"]}).mappings().one()
    assert task["status"] == "queued" and str(task["contact_id"]) == ct["id"] and task["priority"] == 10

    # the call ends with 'not_interested' → the enrollment stops, the task step is never created
    r = admin_client.post("/api/calls/next", params={"campaign_id": camp["id"]})
    assert r.status_code == 200 and r.json()["id"] == str(task["id"])
    r = admin_client.post("/api/calls", json={"task_id": str(task["id"]), "outcome": "not_interested"})
    assert r.status_code in (200, 201), r.text
    enr = _enrollment(admin_client, seq["id"])
    assert enr["status"] == "stopped" and "not_interested" in enr["finished_reason"]
    _due_now(enr["id"])
    assert engine.tick() is False
    with db_conn() as conn:
        kinds = {r[0] for r in conn.execute(text("SELECT event_type FROM outbox_events WHERE aggregate_id=:id"), {"id": enr["id"]})}
        assert kinds == {"sequence.enrolled", "sequence.finished"}


class _FakeSMTP:
    sent: list[dict] = []

    def __init__(self, host, port, timeout=None):
        self.host = host

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def starttls(self):
        pass

    def login(self, u, p):
        pass

    def send_message(self, msg):
        _FakeSMTP.sent.append({"to": msg["To"], "subject": msg["Subject"], "body": msg.get_content(), "reply_to": msg["Reply-To"]})


def test_email_step_goes_over_smtp_when_configured(admin_client, monkeypatch):
    monkeypatch.setattr(engine.settings, "SMTP_HOST", "smtp.test")
    monkeypatch.setattr(engine.settings, "SMTP_FROM", "Luuri <myynti@muutto365.fi>")
    monkeypatch.setattr(engine.smtplib, "SMTP", _FakeSMTP)
    _FakeSMTP.sent.clear()
    camp, co, ct, seq = _setup(admin_client)
    admin_client.post(f"/api/sequences/{seq['id']}/enroll", json={"contact_ids": [ct["id"]]})
    _due_now(_enrollment(admin_client, seq["id"])["id"])
    assert engine.tick() is True
    assert len(_FakeSMTP.sent) == 1 and _FakeSMTP.sent[0]["to"] == "maija@seqfirma.fi" and "Moi Maija" in _FakeSMTP.sent[0]["body"]
    assert _FakeSMTP.sent[0]["reply_to"]  # the seller's address, so replies reach a person
    acts = admin_client.get("/api/sequences/inbox", params={"status": "all"}).json()
    a = next(x for x in acts if x["company_id"] == co["id"])
    assert a["status"] == "done" and a["sent_via"] == "smtp"


def test_enrol_from_list_and_stop_by_hand(admin_client, monkeypatch):
    monkeypatch.setattr(engine.settings, "SMTP_HOST", None)
    camp, co, ct, seq = _setup(admin_client)
    lst = admin_client.post("/api/lists", json={"name": unique("Seq-lista")}).json()
    admin_client.post(f"/api/lists/{lst['id']}/members", json={"company_ids": [co["id"]]})
    r = admin_client.post(f"/api/sequences/{seq['id']}/enroll", json={"list_id": lst["id"]})
    assert r.json()["enrolled"] == 1
    enr = _enrollment(admin_client, seq["id"])
    assert admin_client.post(f"/api/sequences/enrollments/{enr['id']}/stop").status_code == 200
    assert _enrollment(admin_client, seq["id"])["status"] == "stopped"
    page = admin_client.get(f"/api/companies/{co['id']}/sequences").json()
    assert len(page) == 1 and page[0]["status"] == "stopped" and page[0]["step_count"] == 3

    # a company with no e-mail: the email step fails but the chain carries on to the call
    co2 = admin_client.post("/api/companies", json={"name": unique("Eimailia"), "business_id": _bid()}).json()
    admin_client.post(f"/api/companies/{co2['id']}/contacts", json={"name": "Kalle", "phone": _phone()})
    admin_client.post(f"/api/sequences/{seq['id']}/enroll", json={"company_ids": [co2["id"]]})
    enr2 = next(e for e in admin_client.get(f"/api/sequences/{seq['id']}").json()["enrollments"] if e["company_id"] == co2["id"])
    _due_now(enr2["id"])
    engine.tick()
    acts = [a for a in admin_client.get("/api/sequences/inbox", params={"status": "all"}).json() if a["company_id"] == co2["id"]]
    assert acts[0]["status"] == "failed" and "sähköposti" in acts[0]["error"]
    enr2 = next(e for e in admin_client.get(f"/api/sequences/{seq['id']}").json()["enrollments"] if e["company_id"] == co2["id"])
    assert enr2["status"] == "active" and enr2["current_step"] == 1
