"""Call intelligence end to end against real Postgres, with a fake mirarun hub
(agent sessions API, ADR-035) and a fake OpenAI-compatible STT server."""
import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import httpx
from sqlalchemy import text

from app.config import settings
from app.db import db_conn
from app.services import llm
from app.services.intelligence import pipeline
from app.services.intelligence.contract import CallAnalysis, redact
from tests.conftest import unique
from tests.test_call_flow import _make_campaign, _make_company

ANALYSIS = {
    "sentiment": "mixed", "interest_level": 3, "reached_decision_maker": True, "stage_reached": "objection_handling",
    "objections": [
        {"category": "price", "detail_fi": "Piti hintaa korkeana, soita 040 123 4567", "quote_redacted": "liian kallis meille", "handled": True},
        {"category": "timing", "detail_fi": "Kiireinen kausi", "quote_redacted": None, "handled": False},
        {"category": "made_up_category", "detail_fi": "x", "handled": False},
    ],
    "blockers": [{"category": "no_budget", "detail_fi": "Budjetti lukittu vuodeksi"}],
    "buying_signals": [{"signal_fi": "Kysyi referenssejä"}],
    "friction": [{"moment_fi": "Hinnan kohdalla", "cause_fi": "Hinta tuli ennen arvoa"}],
    "next_step_fi": "Soitto tammikuussa", "summary_fi": "Kiinnostunut mutta ajoitus huono.", "coaching_fi": "Kerro arvo ennen hintaa.",
}
FUNNEL = {"headline_fi": "Hinta tulee liian aikaisin", "findings": [{"title_fi": "Hinta", "evidence_fi": "1/1", "impact": "high"}],
          "recommendations": [], "script_changes": [{"objection_category": "price", "suggested_reply_fi": "Ymmärrän…"}], "data_gaps_fi": ["vähän dataa"]}


class FakeHub(BaseHTTPRequestHandler):
    sessions: dict[str, dict] = {}
    created: list[dict] = []
    closed: list[str] = []
    token = "hub-token"

    def _send(self, code, body):
        data = json.dumps(body).encode()
        self.send_response(code)
        self.send_header("content-type", "application/json")
        self.end_headers()
        self.wfile.write(data)

    def _auth(self):
        return self.headers.get("authorization") == f"Bearer {FakeHub.token}"

    def do_POST(self):
        if not self._auth():
            return self._send(401, {"detail": "unauthorised"})
        body = json.loads(self.rfile.read(int(self.headers.get("content-length", 0))) or b"{}")
        if self.path == "/api/agent-sessions":
            FakeHub.created.append(body)
            sid = "s-" + unique("")[1:]
            output = json.dumps(FUNNEL if body["agent"] == "sales-funnel-analyst" else ANALYSIS, ensure_ascii=False)
            # answer arrives on the first poll, wrapped in prose the parser must tolerate
            FakeHub.sessions[sid] = {"session": {"id": sid, "agent": body["agent"], "status": "open"},
                                     "turns": [{"id": "t1", "status": "succeeded", "output": "Tässä:\n```json\n" + output + "\n```",
                                                "model": "anthropic:claude-haiku-5-5", "input_tokens": 1200, "output_tokens": 300}]}
            return self._send(201, {"session": FakeHub.sessions[sid]["session"], "turn": {"id": "t1", "status": "running"}, "duplicate": False})
        if self.path.endswith("/close"):
            FakeHub.closed.append(self.path.split("/")[3])
            return self._send(200, {"id": self.path.split("/")[3], "status": "closed"})
        return self._send(404, {})

    def do_GET(self):
        if not self._auth():
            return self._send(401, {})
        if self.path.startswith("/api/agent-sessions?"):
            return self._send(200, {"count": 0, "sessions": []})
        sid = self.path.rsplit("/", 1)[-1]
        return self._send(200, FakeHub.sessions.get(sid, {"session": {}, "turns": []}))

    def log_message(self, *a):
        pass


class FakeSTT(BaseHTTPRequestHandler):
    calls: list[dict] = []

    def do_POST(self):
        length = int(self.headers.get("content-length", 0))
        raw = self.rfile.read(length)
        FakeSTT.calls.append({"path": self.path, "bytes": length, "has_model": b'name="model"' in raw, "lang_fi": b"\r\n\r\nfi\r\n" in raw})
        body = {"text": "Hei, täällä Eemeli. Meillä ei oikein ole budjettia tähän nyt, liian kallis meille. Soittakaa tammikuussa.",
                "language": "finnish", "duration": 95.2,
                "segments": [{"start": 0.0, "end": 3.1, "text": " Hei, täällä Eemeli."}]}
        data = json.dumps(body).encode()
        self.send_response(200)
        self.send_header("content-type", "application/json")
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, *a):
        pass


def _serve(handler):
    server = HTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server, f"http://127.0.0.1:{server.server_address[1]}"


def _drain():
    with httpx.Client(timeout=10) as c:
        while pipeline.analyze_one(c) or pipeline.transcribe_one() or pipeline.report_one(c):
            pass


def _use_hub(monkeypatch, base):
    monkeypatch.setattr(settings, "MIRARUN_URL", base)
    monkeypatch.setattr(settings, "MIRARUN_SESSION_TOKEN", FakeHub.token)
    monkeypatch.setattr(settings, "MIRA_POLL_SECONDS", 0.05)
    monkeypatch.setattr(settings, "MIRA_AGENT_URL", None)


def _clear_queues():
    with db_conn() as conn:
        conn.execute(text("UPDATE call_analyses SET status='skipped' WHERE status IN ('pending','running')"))
        conn.execute(text("UPDATE call_recordings SET status='failed' WHERE status IN ('pending','transcribing')"))
        conn.execute(text("UPDATE insight_reports SET status='failed' WHERE status IN ('pending','running')"))


def test_contract_validation_and_redaction():
    a = CallAnalysis.model_validate({**ANALYSIS, "sentiment": "ecstatic", "interest_level": "9", "stage_reached": "??"}).redacted()
    assert a.sentiment is None and a.interest_level == 5 and a.stage_reached is None
    assert [o.category for o in a.objections] == ["price", "timing", "other"]
    assert "040" not in a.objections[0].detail_fi and "[numero]" in a.objections[0].detail_fi
    assert redact("maili matti@firma.fi") == "maili [sähköposti]"


def test_extract_json_tolerates_prose_and_fences():
    assert llm.extract_json('Tässä {"a": {"b": "}"}} loppu') == {"a": {"b": "}"}}
    assert llm.extract_json("ei jsonia") is None


def test_hub_backend_preferred_and_agent_per_task(monkeypatch):
    server, base = _serve(FakeHub)
    _use_hub(monkeypatch, base)
    monkeypatch.setattr(settings, "MIRA_AGENT_URL", "http://should-not-be-used:8080")
    try:
        assert llm.provider() == "mirarun"
        res = llm.complete_json("x", task="call_analysis", key="k1")
        assert res.provider == "mirarun" and res.agent == "sales-call-analyst" and res.data["interest_level"] == 3
        assert res.model == "anthropic:claude-haiku-5-5" and res.input_tokens == 1200
        assert FakeHub.created[-1]["agent"] == "sales-call-analyst" and FakeHub.created[-1]["idempotency_key"] == "luuri:call_analysis:k1"
        assert res.run_id in FakeHub.closed  # one prompt, one session, closed after
        assert llm.complete_json("y", task="prospect").agent == "luuri-prospector"
        health = llm.health()
        assert health["reachable"] and health["agents"]["funnel_insights"] == "sales-funnel-analyst"
        monkeypatch.setattr(settings, "MIRARUN_SESSION_TOKEN", "wrong")
        bad = llm.complete_json("z", task="prospect")
        assert bad.data is None and "MIRARUN_SESSION_CLIENT" in bad.error
    finally:
        server.shutdown()


def test_notes_are_analysed_after_logging(admin_client, sales_client, monkeypatch):
    server, base = _serve(FakeHub)
    _use_hub(monkeypatch, base)
    _clear_queues()
    try:
        campaign = _make_campaign(admin_client)
        company, _ = _make_company(admin_client)
        admin_client.post(f"/api/campaigns/{campaign['id']}/enqueue", json={"company_ids": [company["id"]]})
        task = sales_client.post("/api/calls/next", params={"campaign_id": campaign["id"]}).json()
        short = sales_client.post("/api/calls", json={"task_id": task["id"], "outcome": "no_answer", "notes": "ei vast."}).json()["call"]
        with db_conn() as conn:
            assert conn.execute(text("SELECT count(*) FROM call_analyses WHERE call_id=:c"), {"c": short["id"]}).scalar() == 0

        with db_conn() as conn:
            conn.execute(text("UPDATE call_tasks SET due_at=now() WHERE id=:id"), {"id": task["id"]})
        task = sales_client.post("/api/calls/next", params={"campaign_id": campaign["id"]}).json()
        notes = "Puhuin toimitusjohtajan kanssa. Piti hintaa liian kalliina ja sanoi että nyt on kiireinen kausi, soitetaan tammikuussa."
        call = sales_client.post("/api/calls", json={"task_id": task["id"], "outcome": "callback", "callback_at": "2030-01-10T10:00:00+02:00",
                                                    "notes": notes}).json()["call"]
        _drain()
        a = sales_client.get(f"/api/calls/{call['id']}/analysis").json()
        assert len(a["analyses"]) == 1
        row = a["analyses"][0]
        assert row["source"] == "notes" and row["status"] == "done" and row["provider"] == "mirarun" and row["agent"] == "sales-call-analyst"
        assert row["sentiment"] == "mixed" and row["interest_level"] == 3
        assert {o["category"] for o in row["objections"]} == {"price", "timing", "other"}
        assert "040 123 4567" not in json.dumps(row)  # redacted before storage
        prompt = next(c for c in reversed(FakeHub.created) if c["agent"] == "sales-call-analyst")["prompt"]
        assert notes in prompt and "Testipalvelu" in prompt and "callback" in prompt
        with db_conn() as conn:
            ev = conn.execute(text("SELECT payload FROM outbox_events WHERE event_type='call.analyzed' AND aggregate_id=:c"), {"c": call["id"]}).scalar()
        assert ev["objection_categories"] == ["other", "price", "timing"] and "detail_fi" not in json.dumps(ev)
    finally:
        server.shutdown()


def test_upload_transcribe_analyse_and_purge(admin_client, sales_client, monkeypatch):
    hub, hub_base = _serve(FakeHub)
    stt_server, stt_base = _serve(FakeSTT)
    _use_hub(monkeypatch, hub_base)
    monkeypatch.setattr(settings, "STT_BASE_URL", stt_base + "/v1")
    _clear_queues()
    try:
        campaign = _make_campaign(admin_client)
        company, _ = _make_company(admin_client)
        admin_client.post(f"/api/campaigns/{campaign['id']}/enqueue", json={"company_ids": [company["id"]]})
        task = sales_client.post("/api/calls/next", params={"campaign_id": campaign["id"]}).json()
        call = sales_client.post("/api/calls", json={"task_id": task["id"], "outcome": "not_interested"}).json()["call"]

        audio = b"RIFF" + b"\x00" * 2048
        # no consent → refused, nothing stored
        r = sales_client.post(f"/api/calls/{call['id']}/recording", files={"file": ("c.wav", audio, "audio/wav")})
        assert r.status_code == 422
        r = sales_client.post(f"/api/calls/{call['id']}/recording", files={"file": ("c.txt", b"hi", "text/plain")}, data={"consent": "true"})
        assert r.status_code == 415
        r = sales_client.post(f"/api/calls/{call['id']}/recording", files={"file": ("c.wav", audio, "audio/wav")}, data={"consent": "true"})
        assert r.status_code == 201, r.text

        _drain()
        assert FakeSTT.calls[-1]["path"] == "/v1/audio/transcriptions" and FakeSTT.calls[-1]["has_model"] and FakeSTT.calls[-1]["lang_fi"]
        a = sales_client.get(f"/api/calls/{call['id']}/analysis").json()
        assert a["recordings"][0]["status"] == "transcribed" and a["recordings"][0]["duration_seconds"] == 95
        assert a["transcript"]["text"].startswith("Hei, täällä") and a["transcript"]["segments"][0]["text"] == "Hei, täällä Eemeli."
        tr = next(x for x in a["analyses"] if x["source"] == "transcript")
        assert tr["status"] == "done"
        with db_conn() as conn:
            assert conn.execute(text("SELECT audio FROM call_recordings WHERE call_id=:c"), {"c": call["id"]}).scalar() is None
            assert conn.execute(text("SELECT recording_consent FROM calls WHERE id=:c"), {"c": call["id"]}).scalar() is True
            # retention: text goes, analysis stays
            conn.execute(text("UPDATE call_transcripts SET purge_after = now() - interval '1 minute' WHERE call_id=:c"), {"c": call["id"]})
        pipeline.purge()
        a = sales_client.get(f"/api/calls/{call['id']}/analysis").json()
        assert a["transcript"]["text"] is None and a["transcript"]["purged_at"]
        assert any(x["status"] == "done" for x in a["analyses"])
        # re-analysis of a purged transcript is refused
        assert sales_client.post(f"/api/calls/{call['id']}/analyze", json={"source": "transcript"}).status_code == 422
    finally:
        hub.shutdown()
        stt_server.shutdown()


def test_insights_summary_and_report(admin_client, sales_client, monkeypatch):
    server, base = _serve(FakeHub)
    _use_hub(monkeypatch, base)
    _clear_queues()
    try:
        campaign = _make_campaign(admin_client)
        for outcome in ("booked", "not_interested"):
            company, _ = _make_company(admin_client)
            admin_client.post(f"/api/campaigns/{campaign['id']}/enqueue", json={"company_ids": [company["id"]]})
            task = sales_client.post("/api/calls/next", params={"campaign_id": campaign["id"]}).json()
            body = {"task_id": task["id"], "outcome": outcome, "notes": "Pitkä muistiinpano hinnasta ja ajoituksesta, jotta analyysi käynnistyy varmasti."}
            if outcome == "booked":
                body["booking"] = {"scheduled_at": "2026-11-10T10:00:00+02:00"}
            assert sales_client.post("/api/calls", json=body).status_code == 201
        _drain()

        s = sales_client.get("/api/insights/summary", params={"days": 1, "campaign_id": campaign["id"]}).json()
        assert s["analysed"]["analysed"] == 2 and s["calls"]["booked"] == 1
        price = next(o for o in s["objections"] if o["category"] == "price")
        assert price["calls"] == 2 and price["booked_rate"] == 0.5 and price["label_fi"] == "Hinta" and price["examples"]
        assert {b["category"] for b in s["blockers"]} == {"no_budget"}

        r = sales_client.post("/api/insights/reports", json={"days": 1, "campaign_id": campaign["id"]})
        assert r.status_code == 201
        _drain()
        rep = next(x for x in sales_client.get("/api/insights/reports").json() if x["id"] == r.json()["id"])
        assert rep["status"] == "done" and rep["narrative"]["headline_fi"] == "Hinta tulee liian aikaisin" and rep["agent"] == "sales-funnel-analyst"
        funnel_prompt = next(c for c in reversed(FakeHub.created) if c["agent"] == "sales-funnel-analyst")["prompt"]
        assert '"booked_rate": 0.5' in funnel_prompt and "040 123 4567" not in funnel_prompt

        empty = _make_campaign(admin_client)
        assert sales_client.post("/api/insights/reports", json={"days": 1, "campaign_id": empty["id"]}).status_code == 422
    finally:
        server.shutdown()


def test_status_endpoint(sales_client):
    s = sales_client.get("/api/intelligence/status").json()
    assert "analyses_pending" in s and s["stt"]["language"] == "fi"
