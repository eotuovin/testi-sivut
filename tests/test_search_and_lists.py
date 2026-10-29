"""Search desk: company search merges Luuri's own companies with register hits,
person search filters contacts, lists collect both and push into a queue."""
import random

from sqlalchemy import text

from app.db import db_conn
from app.routers import search as search_router
from app.services.prospecting.prh import RegisterCompany
from tests.conftest import unique


def _bid() -> str:
    return f"{random.randint(1000000, 9999999)}-{random.randint(0, 9)}"


def _company(client, **extra):
    r = client.post("/api/companies", json={"name": unique("Hakuyritys"), "business_id": _bid(), "city": "Jyväskylä", "industry_label": "Ravintolat", **extra})
    assert r.status_code == 201, r.text
    return r.json()


def test_company_search_merges_local_and_register(admin_client, monkeypatch):
    local = _company(admin_client)
    admin_client.post(f"/api/companies/{local['id']}/contacts", json={"name": "Maija", "title": "Toimitusjohtaja", "phone": "040 111 2222", "management_level": "c_level"})
    reg_bid = _bid()
    fake = [
        RegisterCompany(business_id=local["business_id"], name=local["name"], company_form="Osakeyhtiö", industry_code="56101",
                        industry_label="Ravintolat", website=None, city="Jyväskylä", postal_code="40100", street_address=None, registration_date="2019-05-01"),
        RegisterCompany(business_id=reg_bid, name="Rekisterifirma " + reg_bid, company_form="Osakeyhtiö", industry_code="56101",
                        industry_label="Ravintolat", website="rekisterifirma.fi", city="Jyväskylä", postal_code="40100", street_address=None, registration_date="2021-02-02"),
    ]
    seen = {}
    def fake_search(**kw):
        seen.update(kw)
        return fake, 2
    monkeypatch.setattr(search_router.prh, "search_companies", fake_search)

    r = admin_client.get("/api/search/companies", params={"q": local["name"], "location": "Jyväskylä"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert seen["page"] == 1 and seen["name"] == local["name"]
    ids = [(i["business_id"], i["in_db"]) for i in body["items"]]
    assert (local["business_id"], True) in ids          # the local row wins
    assert (reg_bid, False) in ids                       # register hit not yet in Luuri
    assert ids.count((local["business_id"], True)) == 1 and (local["business_id"], False) not in ids
    local_row = next(i for i in body["items"] if i["in_db"])
    assert local_row["phone_count"] == 1 and local_row["contact_count"] == 1
    assert body["register_total"] == 2

    # a filter the register cannot answer turns the search local-only
    seen.clear()
    r = admin_client.get("/api/search/companies", params={"q": local["name"], "has_phone": "true"})
    assert r.status_code == 200 and seen == {}
    assert all(i["in_db"] for i in r.json()["items"])
    assert r.json()["register_total"] == 0


def test_contact_search_filters(admin_client, monkeypatch):
    monkeypatch.setattr(search_router.prh, "search_companies", lambda **kw: ([], 0))
    c = _company(admin_client)
    admin_client.post(f"/api/companies/{c['id']}/contacts", json={"name": unique("Pekka"), "title": "Myyntijohtaja", "department": "Myynti", "management_level": "director", "phone": "040 333 4444"})
    admin_client.post(f"/api/companies/{c['id']}/contacts", json={"name": unique("Liisa"), "title": "Kirjanpitäjä", "email": "liisa@x.fi"})

    r = admin_client.get("/api/search/contacts", params={"company": c["name"], "management_level": "director"})
    assert r.status_code == 200, r.text
    items = r.json()["items"]
    assert len(items) == 1 and items[0]["title"] == "Myyntijohtaja" and items[0]["company_name"] == c["name"]

    r = admin_client.get("/api/search/contacts", params={"company": c["name"], "has_phone": "true"})
    assert [i["title"] for i in r.json()["items"]] == ["Myyntijohtaja"]
    r = admin_client.get("/api/search/contacts", params={"company": c["name"], "title": "kirjanpit"})
    assert [i["email"] for i in r.json()["items"]] == ["liisa@x.fi"]
    assert admin_client.get("/api/search/contacts", params={"management_level": "boss"}).status_code == 422


def test_lists_collect_register_hits_and_enqueue(admin_client):
    c = _company(admin_client)
    ct = admin_client.post(f"/api/companies/{c['id']}/contacts", json={"name": "Kalle", "phone": "040 555 6666"}).json()
    r = admin_client.post("/api/lists", json={"name": unique("Jyväskylän ravintolat")})
    assert r.status_code == 201, r.text
    lst = r.json()
    assert lst["member_count"] == 0

    reg_bid = _bid()
    r = admin_client.post(
        f"/api/lists/{lst['id']}/members",
        json={"company_ids": [c["id"]], "register": [{"business_id": reg_bid, "name": "Reki " + reg_bid, "city": "Jyväskylä", "industry_label": "Ravintolat", "registration_date": "2020-01-01"}]},
    )
    assert r.status_code == 200, r.text
    assert r.json()["added"] == 2 and r.json()["list"]["company_count"] == 2
    # the register hit is now a company in Luuri, saved once
    r2 = admin_client.post(f"/api/lists/{lst['id']}/members", json={"register": [{"business_id": reg_bid, "name": "Reki " + reg_bid}]})
    assert r2.json()["added"] == 0
    with db_conn() as conn:
        assert conn.execute(text("SELECT count(*) FROM companies WHERE business_id=:b"), {"b": reg_bid}).scalar_one() == 1
        assert conn.execute(text("SELECT source FROM companies WHERE business_id=:b"), {"b": reg_bid}).scalar_one() == "prh"

    # contact list membership and the company page knowing its lists
    r = admin_client.post(f"/api/lists/{lst['id']}/members", json={"contact_ids": [ct["id"]]})
    assert r.json()["added"] == 1
    detail = admin_client.get(f"/api/lists/{lst['id']}").json()
    assert len(detail["members"]) == 3 and any(m["contact_name"] == "Kalle" for m in detail["members"])
    page = admin_client.get(f"/api/companies/{c['id']}").json()
    assert [li["id"] for li in page["lists"]] == [lst["id"]]

    # list → campaign queue, once per company; the pinned contact is kept
    camp = admin_client.post("/api/campaigns", json={"name": unique("Kampanja"), "product": "Esittely"}).json()
    r = admin_client.post(f"/api/lists/{lst['id']}/enqueue", json={"campaign_id": camp["id"]})
    assert r.status_code == 200 and r.json()["enqueued"] == 2
    assert admin_client.post(f"/api/lists/{lst['id']}/enqueue", json={"campaign_id": camp["id"]}).json()["enqueued"] == 0
    with db_conn() as conn:
        pinned = conn.execute(text("SELECT contact_id FROM call_tasks WHERE campaign_id=:cp AND company_id=:co"), {"cp": camp["id"], "co": c["id"]}).scalar_one()
        assert str(pinned) == ct["id"]
        kinds = {r[0] for r in conn.execute(text("SELECT event_type FROM outbox_events WHERE aggregate_id=:id"), {"id": lst["id"]})}
        assert kinds == {"list.created", "list.members_added"}

    csv_body = admin_client.get(f"/api/lists/{lst['id']}/export.csv").text
    assert csv_body.startswith("company,business_id") and "Kalle" in csv_body

    # search filtered to the list
    r = admin_client.get("/api/search/companies", params={"list_id": lst["id"]})
    assert {i["id"] for i in r.json()["items"]} == {m["company_id"] for m in detail["members"]}

    assert admin_client.delete(f"/api/lists/{lst['id']}").status_code == 204
    assert admin_client.get(f"/api/lists/{lst['id']}").status_code == 404


def test_saved_search_and_profile_fields(admin_client):
    r = admin_client.post("/api/saved-searches", json={"name": unique("Ravintolat JKL"), "scope": "company", "criteria": {"location": "Jyväskylä", "industry": "56", "q": "", "has_phone": False}})
    assert r.status_code == 201, r.text
    assert r.json()["criteria"] == {"location": "Jyväskylä", "industry": "56"}
    sid = r.json()["id"]
    assert any(s["id"] == sid for s in admin_client.get("/api/saved-searches").json())
    assert admin_client.delete(f"/api/saved-searches/{sid}").status_code == 204

    c = _company(admin_client)
    r = admin_client.patch(f"/api/companies/{c['id']}", json={"employees": 25, "revenue_eur": 1200000, "founded_year": 2011, "technologies": ["Shopify", "HubSpot"], "phone": "014 123 456"})
    assert r.status_code == 200, r.text
    assert r.json()["employees"] == 25 and r.json()["technologies"] == ["Shopify", "HubSpot"]
    r = admin_client.get("/api/search/companies", params={"q": c["name"], "employees_min": 10, "employees_max": 50, "include_register": "false"})
    assert [i["id"] for i in r.json()["items"]] == [c["id"]]
    assert admin_client.get("/api/search/companies", params={"q": c["name"], "employees_min": 100}).json()["items"] == []

    ct = admin_client.post(f"/api/companies/{c['id']}/contacts", json={"name": "Ville", "phone": "040 777 8888"}).json()
    r = admin_client.patch(f"/api/contacts/{ct['id']}", json={"title": "CEO", "management_level": "c_level", "verified": True})
    assert r.status_code == 200 and r.json()["management_level"] == "c_level" and r.json()["verified_at"]
    assert admin_client.delete(f"/api/contacts/{ct['id']}").status_code == 204

    facets = admin_client.get("/api/search/facets").json()
    assert "c_level" in facets["management_levels"] and any(x["city"] == "Jyväskylä" for x in facets["cities"])
