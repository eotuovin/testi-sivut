"""Bridged calls through a fake 46elks, and the Mira agent client against a
fake miragen runner. Both run against real Postgres."""
import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import httpx
from sqlalchemy import text

from app.config import settings
from app.db import db_conn
from app.services import llm
from app.services.telephony import service
from tests.conftest import unique
from tests.test_call_flow import _make_campaign, _make_company


class FakeElks(BaseHTTPRequestHandler):
    calls: dict[str, dict] = {}
    posted: list[dict] = []

    def _send(self, code, body):
        data = json.dumps(body).encode()
        self.send_response(code)
        self.send_header("content-type", "application/json")
        self.end_headers()
        self.wfile.write(data)

    def do_POST(self):
        length = int(self.headers.get("content-length", 0))
        from urllib.parse import parse_qs

        form = {k: v[0] for k, v in parse_qs(self.rfile.read(length).decode()).items()}
        if self.path.endswith("/calls"):
            if self.headers.get("authorization") is None:
                return self._send(401, {"error": "no auth"})
            cid = "c" + unique("")[1:]
            FakeElks.posted.append(form)
            FakeElks.calls[cid] = {"id": cid, "state": "ongoing", "from": form["from"], "to": form["to"], "direction": "outgoing", "legs": []}
            return self._send(200, FakeElks.calls[cid])
        cid = self.path.rsplit("/", 1)[-1]
        if form.get("hangup") and cid in FakeElks.calls:
            FakeElks.calls[cid].update(state="success", duration=5, legs=[{"state": "success", "duration": 5}])
            return self._send(200, FakeElks.calls[cid])
        return self._send(404, {})

    def do_GET(self):
        cid = self.path.rsplit("/", 1)[-1]
        c = FakeElks.calls.get(cid)
        return self._send(200, c) if c else self._send(404, {})

    def log_message(self, *a):
        pass


def _serve(handler):
    server = HTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server, f"http://127.0.0.1:{server.server_address[1]}"


def test_dial_requires_own_phone_and_config(sales_client, monkeypatch):
    monkeypatch.setattr(settings, "TELEPHONY_PROVIDER", None)
    r = sales_client.post("/api/telephony/dial", json={"company_id": "00000000-0000-0000-0000-000000000000"})
    assert r.status_code == 409
    assert sales_client.get("/api/telephony/status").json()["enabled"] is False


def test_bridged_call_flow(admin_client, sales_client, monkeypatch):
    server, base = _serve(FakeElks)
    monkeypatch.setattr(settings, "TELEPHONY_PROVIDER", "46elks")
    monkeypatch.setattr(settings, "ELKS_API_BASE", base + "/a1")
    monkeypatch.setattr(settings, "ELKS_API_USER", "u")
    monkeypatch.setattr(settings, "ELKS_API_PASSWORD", "p")
    monkeypatch.setattr(settings, "TELEPHONY_FROM_NUMBER", "+358101234567")
    try:
        status = sales_client.get("/api/telephony/status").json()
        assert status["enabled"] and status["provider"] == "46elks"

        campaign = _make_campaign(admin_client)
        company, contact = _make_company(admin_client)
        admin_client.post(f"/api/campaigns/{campaign['id']}/enqueue", json={"company_ids": [company["id"]]})
        task = sales_client.post("/api/calls/next", params={"campaign_id": campaign["id"]}).json()

        # no own number yet
        r = sales_client.post("/api/telephony/dial", json={"task_id": task["id"]})
        assert r.status_code == 422 and "oma puhelinnumero" in r.json()["detail"].lower()
        assert sales_client.patch("/api/me", json={"phone": "045 777 8888"}).json()["phone_e164"] == "+358457778888"
        assert sales_client.get("/api/me").json()["phone_e164"] == "+358457778888"

        r = sales_client.post("/api/telephony/dial", json={"task_id": task["id"]})
        assert r.status_code == 201, r.text
        session = r.json()
        assert session["state"] == "dialing_agent" and session["agent_number"] == "+358457778888"
        assert session["customer_number"] == contact["phone_e164"] and session["from_number"] == "+358101234567"
        posted = FakeElks.posted[-1]
        assert posted["to"] == "+358457778888" and posted["from"] == "+358101234567"
        assert json.loads(posted["voice_start"])["connect"] == contact["phone_e164"]

        # second call while one is active → 409
        assert sales_client.post("/api/telephony/dial", json={"task_id": task["id"]}).status_code == 409

        # provider: agent answered, customer leg ongoing
        FakeElks.calls[session["provider_call_id"]].update(start="2026-10-25T20:00:00", legs=[{"state": "ongoing", "to": contact["phone_e164"]}])
        with httpx.Client(timeout=5) as c:
            assert service.poll_active_sessions(c) == 1
        assert sales_client.get(f"/api/telephony/sessions/{session['id']}").json()["state"] == "in_progress"

        # customer hung up after 95 s
        FakeElks.calls[session["provider_call_id"]].update(state="success", duration=100, cost=12000, legs=[{"state": "success", "duration": 95, "to": contact["phone_e164"]}])
        with httpx.Client(timeout=5) as c:
            service.poll_active_sessions(c)
        s2 = sales_client.get(f"/api/telephony/sessions/{session['id']}").json()
        assert s2["state"] == "ended" and s2["duration_seconds"] == 95 and s2["cost_cents"] == 120

        # outcome log picks up the duration and links the session
        r = sales_client.post("/api/calls", json={"task_id": task["id"], "session_id": session["id"], "outcome": "callback", "callback_at": "2030-01-01T09:00:00+02:00"})
        assert r.status_code == 201, r.text
        assert r.json()["call"]["duration_seconds"] == 95 and r.json()["call"]["phone_dialed"] == contact["phone_e164"]
        with db_conn() as conn:
            linked = conn.execute(text("SELECT call_id FROM call_sessions WHERE id=:id"), {"id": session["id"]}).scalar()
        assert str(linked) == r.json()["call"]["id"]

        # hangup path
        r = sales_client.post("/api/telephony/dial", json={"company_id": company["id"], "phone": "040 111 2222"})
        assert r.status_code == 201
        s3 = sales_client.post(f"/api/telephony/sessions/{r.json()['id']}/hangup").json()
        assert s3["state"] == "ended"
        assert FakeElks.calls[r.json()["provider_call_id"]]["state"] == "success"

        # caller never answered their own phone
        r = sales_client.post("/api/telephony/dial", json={"company_id": company["id"], "phone": "040 333 4444"})
        FakeElks.calls[r.json()["provider_call_id"]].update(state="busy")
        with httpx.Client(timeout=5) as c:
            service.poll_active_sessions(c)
        assert sales_client.get(f"/api/telephony/sessions/{r.json()['id']}").json()["state"] == "failed"
    finally:
        server.shutdown()


def test_dnc_blocks_dial(admin_client, sales_client, monkeypatch):
    monkeypatch.setattr(settings, "TELEPHONY_PROVIDER", "46elks")
    monkeypatch.setattr(settings, "ELKS_API_USER", "u")
    monkeypatch.setattr(settings, "ELKS_API_PASSWORD", "p")
    monkeypatch.setattr(settings, "TELEPHONY_FROM_NUMBER", "+358101234567")
    sales_client.patch("/api/me", json={"phone": "0451112233"})
    company, contact = _make_company(admin_client)
    admin_client.post("/api/do-not-call", json={"phone": contact["phone_e164"]})
    r = sales_client.post("/api/telephony/dial", json={"company_id": company["id"], "contact_id": contact["id"]})
    assert r.status_code == 422


class FakeMira(BaseHTTPRequestHandler):
    runs: dict[str, dict] = {}
    prompts: list[str] = []
    ready = True

    def _send(self, code, body):
        data = json.dumps(body).encode()
        self.send_response(code)
        self.send_header("content-type", "application/json")
        self.end_headers()
        self.wfile.write(data)

    def do_POST(self):
        if self.headers.get("X-Miragen-Token") != "mira-token":
            return self._send(401, {"detail": "bad token"})
        if not FakeMira.ready:
            return self._send(503, {"detail": "not ready"})
        length = int(self.headers.get("content-length", 0))
        body = json.loads(self.rfile.read(length))
        FakeMira.prompts.append(body["prompt"])
        rid = "run-" + unique("")[1:]
        FakeMira.runs[rid] = {"status": "running"}
        # finishes on first poll
        FakeMira.runs[rid] = {"status": "succeeded", "output": 'Tässä tulos:\n{"summary": "Tekee sähkötöitä", "contacts": [{"name": "Matti Sähkö", "title": "Toimitusjohtaja", "phone": "040 123 4567", "email": null, "confidence": 0.8}], "fit_score": 0.7, "fit_reason": "pk-yritys"}'}
        return self._send(200, {"run_id": rid, "status": "running"})

    def do_GET(self):
        if self.path == "/health":
            return self._send(200, {"agent": "luuri-prospector", "status": "ready", "version": "0.2.0"})
        rid = self.path.rsplit("/", 1)[-1]
        return self._send(200, FakeMira.runs.get(rid, {"status": "failed", "error": "unknown run"}))

    def log_message(self, *a):
        pass


def test_mira_client_and_enrichment(monkeypatch):
    server, base = _serve(FakeMira)
    monkeypatch.setattr(settings, "MIRA_AGENT_URL", base)
    monkeypatch.setattr(settings, "MIRA_AGENT_TOKEN", "mira-token")
    monkeypatch.setattr(settings, "MIRA_POLL_SECONDS", 0.05)
    monkeypatch.setattr(settings, "ANTHROPIC_API_KEY", "should-not-be-used")
    try:
        assert llm.provider() == "mira"
        h = llm.health()
        assert h["reachable"] and h["agent"] == "luuri-prospector"
        res = llm.complete_json("Palauta JSON")
        assert res.provider == "mira" and res.data["summary"] == "Tekee sähkötöitä" and res.error is None

        # enrichment uses it and marks provenance
        from app.services.prospecting import enrich

        class R:
            status_code = 200
            headers = {"content-type": "text/html"}
            text = "<html><body>Sähkö-Mesta Oy. Puh 040 123 4567. matti.sahko@sahkomesta.fi</body></html>"

        class C:
            def get(self, url, **kw):
                return R()

            def close(self):
                pass

        monkeypatch.setattr(enrich.settings, "ENRICH_FETCH_WEBSITES", True)
        e = enrich.enrich_company("Sähkö-Mesta Oy", "sahkomesta.fi", "Testipalvelu", client=C())
        assert e.enriched_by == "mira" and e.fit_score == 0.7 and e.contacts[0].name == "Matti Sähkö"
        assert "Sähkö-Mesta Oy" in FakeMira.prompts[-1] and "Testipalvelu" in FakeMira.prompts[-1]

        # agent not ready → graceful fallback to rules
        FakeMira.ready = False
        e2 = enrich.enrich_company("Sähkö-Mesta Oy", "sahkomesta.fi", None, client=C())
        assert e2.enriched_by == "rules" and e2.contacts[0].email == "matti.sahko@sahkomesta.fi"
        FakeMira.ready = True

        # wrong token → error, no crash
        monkeypatch.setattr(settings, "MIRA_AGENT_TOKEN", "wrong")
        bad = llm.complete_json("x")
        assert bad.data is None and "401" in bad.error
    finally:
        server.shutdown()
