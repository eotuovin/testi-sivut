"""Seller-day report: today's figures per caller, hourly buckets, outcomes, bookings."""
import random

from tests.conftest import unique


def test_stats_day_counts_todays_calls(admin_client):
    camp = admin_client.post("/api/campaigns", json={"name": unique("Päiväkampanja"), "product": "Esittely"}).json()
    co = admin_client.post("/api/companies", json={"name": unique("Päiväfirma"), "business_id": f"{random.randint(1000000, 9999999)}-{random.randint(0, 9)}"}).json()
    ct = admin_client.post(f"/api/companies/{co['id']}/contacts", json={"name": "Päivi", "phone": f"040 {random.randint(100, 999)} {random.randint(1000, 9999)}"}).json()
    admin_client.post(f"/api/campaigns/{camp['id']}/enqueue", json={"company_ids": [co["id"]]})
    task = admin_client.post("/api/calls/next", params={"campaign_id": camp["id"]}).json()
    me = admin_client.get("/api/me").json()["id"]

    before = admin_client.get("/api/stats/day").json()
    mine_before = next((u for u in before["per_user"] if u["user_id"] == me), None)
    calls_before = mine_before["calls"] if mine_before else 0

    r = admin_client.post("/api/calls", json={"task_id": task["id"], "outcome": "booked", "duration_seconds": 240, "contact_id": ct["id"],
                                              "booking": {"scheduled_at": "2030-01-10T10:00:00Z", "value_eur": 500}})
    assert r.status_code in (200, 201), r.text

    after = admin_client.get("/api/stats/day").json()
    mine = next(u for u in after["per_user"] if u["user_id"] == me)
    assert mine["calls"] == calls_before + 1 and mine["booked"] >= 1 and mine["conversations"] >= 1 and mine["talk_seconds"] >= 240
    assert after["me"] == me and after["day"]
    assert any(h["user_id"] == me and h["calls"] >= 1 for h in after["hourly"])
    assert any(o["user_id"] == me and o["outcome"] == "booked" for o in after["outcomes"])
    assert any(b["company_id"] == co["id"] and b["user_id"] == me for b in after["bookings"])
    # explicit date in the past has nothing from us
    old = admin_client.get("/api/stats/day", params={"date": "2020-01-01"}).json()
    assert all(u["calls"] == 0 for u in old["per_user"]) and old["bookings"] == []
    assert admin_client.get("/api/stats/day", params={"date": "nope"}).status_code == 422
