"""Browser calls through Telnyx: token minting (credential created once), the
session the browser reports into, the worker's stale-session timeout, the
outcome linking to the session, and recording fetch by Telnyx session id."""
import json
import threading
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, HTTPServer

import httpx
import pytest
from sqlalchemy import text

from app.config import settings
from app.db import db_conn
from app.services.intelligence import pipeline
from app.services.telephony import service
from tests.conftest import unique

AUDIO = b"ID3fake-mp3-bytes" * 10


class FakeTelnyx(BaseHTTPRequestHandler):
    calls: list[tuple[str, str, dict | None]] = []
    recordings: list[dict] = []

    def _send(self, code, body, ctype="application/json"):
        data = body if isinstance(body, bytes) else json.dumps(body).encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_POST(self):
        n = int(self.headers.get("Content-Length") or 0)
        body = json.loads(self.rfile.read(n) or b"{}") if n else None
        FakeTelnyx.calls.append(("POST", self.path, body))
        if self.headers.get("Authorization") != "Bearer test-key":
            return self._send(401, {"errors": [{"detail": "bad key"}]})
        if self.path == "/v2/telephony_credentials":
            return self._send(201, {"data": {"id": "cred-123", "name": body["name"], "connection_id": body["connection_id"]}})
        if self.path == "/v2/telephony_credentials/cred-123/token":
            return self._send(201, b"eyJ.fake.jwt", "text/plain")
        self._send(404, {"errors": []})

    def do_GET(self):
        FakeTelnyx.calls.append(("GET", self.path, None))
        if self.path.startswith("/v2/recordings"):
            if "call_session_id%5D=sess-abc" in self.path or "call_session_id]=sess-abc" in self.path:
                return self._send(200, {"data": FakeTelnyx.recordings})
            return self._send(200, {"data": []})
        if self.path == "/rec/abc.mp3":
            return self._send(200, AUDIO, "audio/mpeg")
        self._send(404, {})

    def log_message(self, *a):  # quiet
        pass


@pytest.fixture(scope="module")
def telnyx():
    srv = HTTPServer(("127.0.0.1", 0), FakeTelnyx)
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    yield f"http://127.0.0.1:{srv.server_port}"
    srv.shutdown()


@pytest.fixture
def telnyx_on(monkeypatch, telnyx):
    monkeypatch.setattr(settings, "TELEPHONY_PROVIDER", "telnyx")
    monkeypatch.setattr(settings, "TELNYX_API_KEY", "test-key")
    monkeypatch.setattr(settings, "TELNYX_CONNECTION_ID", "conn-1")
    monkeypatch.setattr(settings, "TELNYX_API_BASE", telnyx + "/v2")
    monkeypatch.setattr(settings, "TELEPHONY_FROM_NUMBER", "+358101234567")
    monkeypatch.setattr(settings, "TELEPHONY_RECORD_CALLS", True)
    FakeTelnyx.calls.clear()
    FakeTelnyx.recordings = [{"id": "rec-1", "call_session_id": "sess-abc", "status": "completed", "duration_millis": 83000,
                              "download_urls": {"mp3": telnyx + "/rec/abc.mp3"}}]


def _company_with_contact(client):
    import random
    co = client.post("/api/companies", json={"name": unique("Selainfirma"), "business_id": f"{random.randint(1000000, 9999999)}-{random.randint(0, 9)}"}).json()
    ct = client.post(f"/api/companies/{co['id']}/contacts", json={"name": "Pirkko", "phone": f"040 {random.randint(100, 999)} {random.randint(1000, 9999)}"}).json()
    return co, ct


def test_status_reports_browser_mode(admin_client, telnyx_on):
    s = admin_client.get("/api/telephony/status").json()
    assert s["enabled"] and s["provider"] == "telnyx" and s["browser"] is True


def test_token_creates_credential_once(admin_client, telnyx_on):
    r = admin_client.post("/api/telephony/webrtc/token")
    assert r.status_code == 200, r.text
    assert r.json()["token"] == "eyJ.fake.jwt" and r.json()["from_number"] == "+358101234567"
    r2 = admin_client.post("/api/telephony/webrtc/token")
    assert r2.status_code == 200
    creates = [c for c in FakeTelnyx.calls if c[1] == "/v2/telephony_credentials"]
    assert len(creates) == 1 and creates[0][2]["connection_id"] == "conn-1"
    with db_conn() as conn:
        assert conn.execute(text("SELECT count(*) FROM users WHERE telnyx_credential_id='cred-123'")).scalar_one() >= 1


def test_browser_session_flow_outcome_and_recording(admin_client, telnyx_on):
    co, ct = _company_with_contact(admin_client)
    r = admin_client.post("/api/telephony/sessions", json={"company_id": co["id"], "contact_id": ct["id"]})
    assert r.status_code == 201, r.text
    sess = r.json()
    assert sess["state"] == "connecting" and sess["agent_number"] == "browser" and sess["customer_number"] == ct["phone_e164"]

    r = admin_client.post(f"/api/telephony/sessions/{sess['id']}/state", json={"state": "in_progress", "provider_session_id": "sess-abc"})
    assert r.status_code == 200 and r.json()["answered_at"]
    assert admin_client.post(f"/api/telephony/sessions/{sess['id']}/state", json={"state": "nonsense"}).status_code == 422
    r = admin_client.post(f"/api/telephony/sessions/{sess['id']}/state", json={"state": "ended"})
    assert r.json()["state"] == "ended" and r.json()["duration_seconds"] is not None
    # terminal stays terminal
    assert admin_client.post(f"/api/telephony/sessions/{sess['id']}/state", json={"state": "in_progress"}).json()["state"] == "ended"

    # outcome links to the session, with consent → the worker fetches the recording by Telnyx session id
    r = admin_client.post("/api/calls", json={"company_id": co["id"], "contact_id": ct["id"], "session_id": sess["id"], "outcome": "callback",
                                              "callback_at": "2030-01-01T10:00:00Z", "recording_consent": True})
    assert r.status_code in (200, 201), r.text
    with db_conn() as conn:
        conn.execute(text("UPDATE call_sessions SET ended_at = now() - interval '2 minutes' WHERE id=:id"), {"id": sess["id"]})
    with httpx.Client() as client:
        assert pipeline.fetch_recordings(client) >= 1
        pipeline.fetch_recordings(client)  # a second pass must not duplicate
    with db_conn() as conn:
        rec = conn.execute(text("SELECT source, provider, provider_recording_id, audio_bytes, duration_seconds, status FROM call_recordings WHERE session_id=:s"), {"s": sess["id"]}).mappings().one()
    assert rec["provider"] == "telnyx" and rec["source"] == "upload" and rec["provider_recording_id"] == "rec-1"
    assert rec["audio_bytes"] == len(AUDIO) and rec["duration_seconds"] == 83 and rec["status"] == "pending"


def test_stale_browser_session_is_closed_by_worker(admin_client, telnyx_on, monkeypatch):
    co, ct = _company_with_contact(admin_client)
    sess = admin_client.post("/api/telephony/sessions", json={"company_id": co["id"], "contact_id": ct["id"]}).json()
    admin_client.post(f"/api/telephony/sessions/{sess['id']}/state", json={"state": "in_progress"})
    with httpx.Client() as client:
        assert service.poll_active_sessions(client) >= 1
    assert admin_client.get(f"/api/telephony/sessions/{sess['id']}").json()["state"] == "in_progress"
    with db_conn() as conn:
        conn.execute(text("UPDATE call_sessions SET client_seen_at = now() - interval '10 minutes', answered_at = now() - interval '12 minutes' WHERE id=:id"), {"id": sess["id"]})
    with httpx.Client() as client:
        service.poll_active_sessions(client)
    s = admin_client.get(f"/api/telephony/sessions/{sess['id']}").json()
    assert s["state"] == "failed" and "selaimeen" in s["error"] and s["duration_seconds"] == 120

    # a new browser call replaces a lost one instead of being blocked by it
    sess2 = admin_client.post("/api/telephony/sessions", json={"company_id": co["id"], "contact_id": ct["id"]}).json()
    admin_client.post(f"/api/telephony/sessions/{sess2['id']}/state", json={"state": "in_progress"})
    r = admin_client.post("/api/telephony/sessions", json={"company_id": co["id"], "contact_id": ct["id"]})
    assert r.status_code == 201
    assert admin_client.get(f"/api/telephony/sessions/{sess2['id']}").json()["state"] == "failed"


def test_do_not_call_blocks_browser_session(admin_client, telnyx_on):
    co, ct = _company_with_contact(admin_client)
    admin_client.post("/api/do-not-call", json={"phone": ct["phone_e164"], "reason": "testi"})
    r = admin_client.post("/api/telephony/sessions", json={"company_id": co["id"], "contact_id": ct["id"]})
    assert r.status_code == 422
