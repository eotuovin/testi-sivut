import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import httpx
from sqlalchemy import text

from app.db import db_conn
from app.services import calendar
from app.services.integrations.dispatcher import dispatch_one
from tests.conftest import unique
from tests.test_call_flow import _make_campaign, _make_company


def test_draft_notes_survive_and_fold_into_outcome(admin_client, sales_client):
    campaign = _make_campaign(admin_client)
    company, _ = _make_company(admin_client)
    admin_client.post(f"/api/campaigns/{campaign['id']}/enqueue", json={"company_ids": [company["id"]]})
    task = sales_client.post("/api/calls/next", params={"campaign_id": campaign["id"]}).json()
    assert task["notes_draft"] == ""

    r = sales_client.put(f"/api/calls/tasks/{task['id']}/draft", json={"notes": "Puhuin Matin kanssa, kiinnostui"})
    assert r.status_code == 200 and r.json()["saved_at"]
    # reload → same task back, draft included
    again = sales_client.post("/api/calls/next", params={"campaign_id": campaign["id"]}).json()
    assert again["id"] == task["id"] and again["notes_draft"] == "Puhuin Matin kanssa, kiinnostui"

    # log without notes → draft becomes the call's notes, draft removed
    r = sales_client.post("/api/calls", json={"task_id": task["id"], "outcome": "not_interested"})
    assert r.status_code == 201 and r.json()["call"]["notes"] == "Puhuin Matin kanssa, kiinnostui"
    with db_conn() as conn:
        assert conn.execute(text("SELECT count(*) FROM call_drafts WHERE task_id=:t"), {"t": task["id"]}).scalar() == 0


def test_booking_with_meeting_details_and_ics(admin_client, sales_client):
    campaign = _make_campaign(admin_client)
    company, contact = _make_company(admin_client)
    admin_client.post(f"/api/companies/{company['id']}/contacts", json={"name": "Liisa Päättäjä", "email": "liisa@firma.fi", "phone": "0401234999"})
    admin_client.post(f"/api/campaigns/{campaign['id']}/enqueue", json={"company_ids": [company["id"]]})
    task = sales_client.post("/api/calls/next", params={"campaign_id": campaign["id"]}).json()
    r = sales_client.post(
        "/api/calls",
        json={
            "task_id": task["id"], "outcome": "booked", "notes": "Sovittiin demo",
            "booking": {"scheduled_at": "2026-11-05T10:00:00+02:00", "duration_minutes": 45, "location": "Teams",
                        "meeting_url": "https://teams.example/abc", "attendee_email": "liisa@firma.fi", "value_eur": 1200},
        },
    )
    assert r.status_code == 201, r.text
    booking = r.json()["booking"]
    assert booking["duration_minutes"] == 45 and booking["location"] == "Teams" and booking["attendee_email"] == "liisa@firma.fi"
    # a booked meeting is 'qualified'; completing it makes a customer
    assert admin_client.get(f"/api/companies/{company['id']}").json()["status"] == "qualified"
    admin_client.patch(f"/api/bookings/{booking['id']}", json={"status": "completed"})
    assert admin_client.get(f"/api/companies/{company['id']}").json()["status"] == "customer"

    ics = sales_client.get(f"/api/bookings/{booking['id']}/ics")
    assert ics.status_code == 200 and ics.headers["content-type"].startswith("text/calendar")
    body = ics.text
    assert "BEGIN:VEVENT" in body and "DTSTART:20261105T080000Z" in body and "DTEND:20261105T084500Z" in body
    assert f"SUMMARY:Testipalvelu – {company['name']}" in body
    assert "ATTENDEE;CN=" in body and "mailto:liisa@firma.fi" in body
    assert "URL:https://teams.example/abc" in body and "LOCATION:Teams" in body
    assert "Sovittiin demo" not in body  # call notes are internal; only booking notes go to the invite


def test_enqueue_skips_companies_without_a_number(admin_client):
    campaign = _make_campaign(admin_client)
    r = admin_client.post("/api/companies", json={"name": unique("Numeroton"), "city": "Jyväskylä"})
    nophone = r.json()
    company, _ = _make_company(admin_client)
    r = admin_client.post(f"/api/campaigns/{campaign['id']}/enqueue", json={"company_ids": [nophone["id"], company["id"]]})
    assert r.json() == {"enqueued": 1, "skipped_no_phone": 1}


class FakeGoogle(BaseHTTPRequestHandler):
    events: dict[str, dict] = {}
    deleted: list[str] = []

    def _send(self, code, body=None):
        data = json.dumps(body or {}).encode()
        self.send_response(code)
        self.send_header("content-type", "application/json")
        self.end_headers()
        if code != 204:
            self.wfile.write(data)

    def _body(self):
        return json.loads(self.rfile.read(int(self.headers.get("content-length", 0))) or b"{}")

    def do_POST(self):
        if self.headers.get("authorization") != "Bearer fake-token":
            return self._send(401, {"error": "no token"})
        eid = "evt" + unique("")[1:]
        FakeGoogle.events[eid] = {**self._body(), "id": eid, "htmlLink": f"https://calendar.google.com/event?eid={eid}"}
        return self._send(200, FakeGoogle.events[eid])

    def do_PATCH(self):
        eid = self.path.rsplit("/", 1)[-1]
        FakeGoogle.events[eid].update(self._body())
        return self._send(200, FakeGoogle.events[eid])

    def do_DELETE(self):
        FakeGoogle.deleted.append(self.path.rsplit("/", 1)[-1])
        return self._send(204)

    def log_message(self, *a):
        pass


def test_google_calendar_adapter(admin_client, sales_client, monkeypatch):
    server = HTTPServer(("127.0.0.1", 0), FakeGoogle)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{server.server_address[1]}"
    monkeypatch.setattr(calendar, "_google_token", lambda sa: "fake-token")
    monkeypatch.setenv("TEST_SA_JSON", '{"type":"service_account"}')
    # point the adapter at the fake api
    orig_deliver = calendar.GoogleCalendarAdapter.deliver

    class Patched(calendar.GoogleCalendarAdapter):
        def deliver(self, event, client):
            real_client = client

            class C:
                def post(self, url, **kw): return real_client.post(url.replace("https://www.googleapis.com", base), **kw)
                def patch(self, url, **kw): return real_client.patch(url.replace("https://www.googleapis.com", base), **kw)
                def delete(self, url, **kw): return real_client.delete(url.replace("https://www.googleapis.com", base), **kw)
            return orig_deliver(self, event, C())

    from app.services.integrations import base as ibase

    monkeypatch.setitem(ibase.ADAPTERS, "google_calendar", Patched)
    try:
        with db_conn() as conn:
            conn.execute(text("UPDATE integration_targets SET enabled=false"))
            conn.execute(text("UPDATE outbox_events SET status='delivered' WHERE status='pending'"))
        r = admin_client.post("/api/integrations/targets", json={
            "kind": "google_calendar", "name": unique("cal"), "config": {"secret_env": "TEST_SA_JSON", "calendar_id": "team@group.calendar.google.com"},
            "event_types": ["booking.*"]})
        assert r.status_code == 201, r.text
        target = r.json()

        campaign = _make_campaign(admin_client)
        company, _ = _make_company(admin_client)
        admin_client.post(f"/api/campaigns/{campaign['id']}/enqueue", json={"company_ids": [company["id"]]})
        task = sales_client.post("/api/calls/next", params={"campaign_id": campaign["id"]}).json()
        booking = sales_client.post("/api/calls", json={"task_id": task["id"], "outcome": "booked",
                                                       "booking": {"scheduled_at": "2026-11-06T13:00:00+02:00", "location": "Puhelin"}}).json()["booking"]
        with httpx.Client(timeout=5) as c:
            while dispatch_one(c):
                pass
        with db_conn() as conn:
            row = conn.execute(text("SELECT calendar_event_id, calendar_html_link FROM sales_bookings WHERE id=:id"), {"id": booking["id"]}).mappings().one()
        assert row["calendar_event_id"] in FakeGoogle.events and row["calendar_html_link"].startswith("https://calendar.google.com")
        ev = FakeGoogle.events[row["calendar_event_id"]]
        assert ev["summary"] == f"Testipalvelu – {company['name']}" and ev["start"]["dateTime"].startswith("2026-11-06T13:00:00")
        listed = {b["id"]: b for b in admin_client.get("/api/bookings").json()}
        assert listed[booking["id"]]["calendar_html_link"] == row["calendar_html_link"]

        # reschedule → patch; cancel → delete
        admin_client.patch(f"/api/bookings/{booking['id']}", json={"scheduled_at": "2026-11-07T09:00:00+02:00"})
        with httpx.Client(timeout=5) as c:
            while dispatch_one(c):
                pass
        assert FakeGoogle.events[row["calendar_event_id"]]["start"]["dateTime"].startswith("2026-11-07T09:00:00")
        admin_client.patch(f"/api/bookings/{booking['id']}", json={"status": "cancelled"})
        with httpx.Client(timeout=5) as c:
            while dispatch_one(c):
                pass
        assert row["calendar_event_id"] in FakeGoogle.deleted
        deliveries = admin_client.get(f"/api/integrations/targets/{target['id']}/deliveries").json()
        assert deliveries and all(d["status"] == "ok" for d in deliveries)
    finally:
        server.shutdown()
        with db_conn() as conn:
            conn.execute(text("UPDATE integration_targets SET enabled=false WHERE kind='google_calendar'"))
