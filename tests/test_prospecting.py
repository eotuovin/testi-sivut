"""Prospecting: a run finds companies, enrichment pulls contacts from the
website text, review approves them into companies + the campaign queue."""
import json

from sqlalchemy import text

from app.db import db_conn
from app.phone import canonical_phone, find_phones
from app.services.prospecting import enrich, prh, runner
from app.services.prospecting.enrich import enrich_company
from app.services.prospecting.prh import RegisterCompany
from tests.conftest import unique


def test_phone_rules_match_backend():
    assert canonical_phone("040 123 4567") == "+358401234567"
    assert canonical_phone("+358 (0)40 1234567") == "+358401234567"
    assert canonical_phone("00358401234567") == "+358401234567"
    assert canonical_phone("(014) 123 456") == "+35814123456"
    assert canonical_phone("") is None
    assert find_phones("Soita 040 123 4567 tai 014 123456. Y-tunnus 1234567-8") == ["+358401234567", "+35814123456"]
    # business ids, EDI/OVT codes and foreign numbers must not become Finnish phones
    assert find_phones("Y-tunnus 0208265-2, OVT 003702082652200, puh +358 10 767 3000, viite 02082652") == ["+358107673000"]
    assert canonical_phone("0046 70 123 4567") == "+46701234567"


def test_enrich_extracts_contacts_from_site(monkeypatch):
    html = """<html><body><h1>Firma Oy</h1><p>Toimitusjohtaja Pekka Virtanen, pekka.virtanen@firma.fi, puh. 040 555 1234</p>
    <p>info@firma.fi · 014 222 333</p><script>var x = '050 000 0000';</script></body></html>"""

    class R:
        status_code = 200
        headers = {"content-type": "text/html; charset=utf-8"}
        text = html

    class C:
        def get(self, url, **kw):
            return R()

        def close(self):
            pass

    monkeypatch.setattr(enrich.settings, "ENRICH_FETCH_WEBSITES", True)
    monkeypatch.setattr(enrich.settings, "ANTHROPIC_API_KEY", None)
    result = enrich_company("Firma Oy", "firma.fi", "Testipalvelu", client=C())
    assert "+358405551234" in result.phones and "+35814222333" in result.phones
    assert "+358500000000" not in result.phones  # script text is stripped
    assert result.emails == ["pekka.virtanen@firma.fi", "info@firma.fi"]
    assert result.contacts[0].name == "Pekka Virtanen" and result.contacts[0].email == "pekka.virtanen@firma.fi"


def test_run_then_review_creates_company_and_queue(admin_client, monkeypatch):
    bid = unique("9")[:9]
    fake = [RegisterCompany(business_id=bid, name="Prospekti " + bid, company_form="Osakeyhtiö", industry_code="62010",
                            industry_label="Ohjelmistot", website="prospekti.fi", city="Jyväskylä", postal_code="40100",
                            street_address="Kauppakatu 1", registration_date="2020-01-01")]
    monkeypatch.setattr(runner, "search_companies", lambda **kw: (fake, 1))
    monkeypatch.setattr(runner, "enrich_company", lambda *a, **kw: enrich.Enrichment(
        website="prospekti.fi", phones=["+358401112222"], emails=["cto@prospekti.fi"],
        contacts=[enrich.ContactCandidate(name="Cto Henkilö", phone="+358401112222", email="cto@prospekti.fi", confidence=0.7)],
        summary="Tekee softaa", fit_score=0.8))

    campaign = admin_client.post("/api/campaigns", json={"name": unique("K"), "product": "Testipalvelu"}).json()
    r = admin_client.post("/api/prospecting/runs", json={"campaign_id": campaign["id"], "location": "Jyväskylä", "industry": "62010", "max_results": 10})
    assert r.status_code == 201, r.text
    run = r.json()
    claimed = runner.claim_next_run()
    assert str(claimed["id"]) == run["id"]
    runner.execute_run(claimed["id"], claimed["campaign_id"], claimed["criteria"])

    runs = {x["id"]: x for x in admin_client.get("/api/prospecting/runs").json()}
    assert runs[run["id"]]["status"] == "done" and runs[run["id"]]["stats"]["new"] == 1 and runs[run["id"]]["pending"] == 1
    prospects = admin_client.get("/api/prospecting/prospects", params={"run_id": run["id"]}).json()
    assert len(prospects) == 1 and prospects[0]["score"] == 0.8 and prospects[0]["found_contacts"][0]["name"] == "Cto Henkilö"

    r = admin_client.post("/api/prospecting/review", json={"approve": [prospects[0]["id"]], "enqueue_campaign_id": campaign["id"]})
    assert r.status_code == 200, r.text
    company_id = r.json()["approved"][0]
    detail = admin_client.get(f"/api/companies/{company_id}").json()
    assert detail["business_id"] == bid and detail["source"] == "agent" and detail["notes"] == "Tekee softaa"
    assert detail["contacts"][0]["phone_e164"] == "+358401112222" and float(detail["contacts"][0]["confidence"]) == 0.7
    assert detail["tasks"][0]["campaign_id"] == campaign["id"] and detail["tasks"][0]["contact_id"] == detail["contacts"][0]["id"]

    # the same business id on a second run is flagged as duplicate, not re-created
    r = admin_client.post("/api/prospecting/runs", json={"location": "Jyväskylä"})
    claimed = runner.claim_next_run()
    runner.execute_run(claimed["id"], None, claimed["criteria"])
    with db_conn() as conn:
        stats = conn.execute(text("SELECT stats FROM prospecting_runs WHERE id=:id"), {"id": claimed["id"]}).scalar()
        dup = conn.execute(text("SELECT review_status FROM prospects WHERE run_id=:id"), {"id": claimed["id"]}).scalar()
    assert stats["known"] == 1 and dup == "duplicate"
