"""Funnel insights: measured aggregates over call_analyses (SQL, always
available) and an optional narrative written from them by the funnel agent.
The agent only sees these aggregates and redacted snippets — never raw
transcripts or contact details."""
from __future__ import annotations

import json
from datetime import datetime
from uuid import UUID

from sqlalchemy import text

from app.services.intelligence.contract import OBJECTION_CATEGORIES

OBJECTION_LABELS_FI = {
    "price": "Hinta", "no_need": "Ei tarvetta", "timing": "Ajoitus", "already_has_solution": "On jo ratkaisu",
    "no_authority": "Ei päätösvaltaa", "send_info": "Laita sähköpostia", "trust": "Luottamus", "contract_lock": "Sopimus voimassa",
    "too_busy": "Ei aikaa", "bad_experience": "Huono kokemus", "other": "Muu",
}

_SCOPE = """
FROM call_analyses a JOIN calls c ON c.id = a.call_id
WHERE a.status = 'done' AND c.started_at >= :start AND c.started_at < :end
  AND (CAST(:cid AS uuid) IS NULL OR c.campaign_id = CAST(:cid AS uuid))
  -- prefer the transcript analysis when a call has both
  AND (a.source = 'transcript' OR NOT EXISTS (
        SELECT 1 FROM call_analyses a2 WHERE a2.call_id = a.call_id AND a2.source = 'transcript' AND a2.status = 'done'))
"""


def compute_stats(conn, start: datetime, end: datetime, campaign_id: UUID | None) -> dict:
    p = {"start": start, "end": end, "cid": str(campaign_id) if campaign_id else None}
    calls = conn.execute(
        text(
            """
            SELECT count(*) AS calls,
                   count(*) FILTER (WHERE outcome NOT IN ('no_answer','busy','voicemail')) AS conversations,
                   count(*) FILTER (WHERE outcome = 'booked') AS booked
            FROM calls WHERE started_at >= :start AND started_at < :end
              AND (CAST(:cid AS uuid) IS NULL OR campaign_id = CAST(:cid AS uuid))
            """
        ),
        p,
    ).mappings().one()
    base = conn.execute(
        text(
            "SELECT count(*) AS analysed, count(*) FILTER (WHERE a.source='transcript') AS from_transcripts, "
            "count(*) FILTER (WHERE a.source='notes') AS from_notes, round(avg(a.interest_level)::numeric, 2) AS avg_interest, "
            "count(*) FILTER (WHERE a.reached_decision_maker) AS reached_dm " + _SCOPE
        ),
        p,
    ).mappings().one()
    objections = conn.execute(
        text(
            """
            SELECT o->>'category' AS category,
                   count(*) AS mentions,
                   count(DISTINCT a.call_id) AS calls,
                   count(*) FILTER (WHERE (o->>'handled')::boolean) AS handled,
                   count(DISTINCT a.call_id) FILTER (WHERE c.outcome = 'booked') AS calls_booked_anyway
            """ + _SCOPE.replace("FROM call_analyses a JOIN calls c ON c.id = a.call_id",
                                 "FROM call_analyses a JOIN calls c ON c.id = a.call_id, jsonb_array_elements(a.objections) o")
            + " GROUP BY 1 ORDER BY calls DESC"
        ),
        p,
    ).mappings().all()
    blockers = conn.execute(
        text(
            "SELECT b->>'category' AS category, count(DISTINCT a.call_id) AS calls "
            + _SCOPE.replace("FROM call_analyses a JOIN calls c ON c.id = a.call_id",
                             "FROM call_analyses a JOIN calls c ON c.id = a.call_id, jsonb_array_elements(a.blockers) b")
            + " GROUP BY 1 ORDER BY calls DESC"
        ),
        p,
    ).mappings().all()
    sentiment = conn.execute(text("SELECT a.sentiment, count(*) AS n " + _SCOPE + " GROUP BY 1 ORDER BY n DESC"), p).mappings().all()
    stages = conn.execute(
        text("SELECT a.stage_reached AS stage, count(*) AS n, count(*) FILTER (WHERE c.outcome='booked') AS booked " + _SCOPE + " GROUP BY 1 ORDER BY n DESC"),
        p,
    ).mappings().all()
    samples = conn.execute(
        text(
            "SELECT o->>'category' AS category, o->>'detail_fi' AS detail_fi, o->>'quote_redacted' AS quote "
            + _SCOPE.replace("FROM call_analyses a JOIN calls c ON c.id = a.call_id",
                             "FROM call_analyses a JOIN calls c ON c.id = a.call_id, jsonb_array_elements(a.objections) o")
            + " ORDER BY a.created_at DESC LIMIT 60"
        ),
        p,
    ).mappings().all()
    friction = conn.execute(
        text("SELECT f->>'moment_fi' AS moment_fi, f->>'cause_fi' AS cause_fi, count(*) AS n "
             + _SCOPE.replace("FROM call_analyses a JOIN calls c ON c.id = a.call_id",
                              "FROM call_analyses a JOIN calls c ON c.id = a.call_id, jsonb_array_elements(a.friction) f")
             + " GROUP BY 1, 2 ORDER BY n DESC, 1 LIMIT 25"),
        p,
    ).mappings().all()
    per_cat: dict[str, list] = {}
    for s in samples:
        bucket = per_cat.setdefault(s["category"], [])
        if len(bucket) < 4:
            bucket.append({"detail_fi": s["detail_fi"], "quote": s["quote"]})
    return {
        "period": {"start": start.isoformat(), "end": end.isoformat()},
        "campaign_id": str(campaign_id) if campaign_id else None,
        "calls": dict(calls),
        "analysed": {k: (float(v) if hasattr(v, "is_finite") else v) for k, v in dict(base).items()},
        "objections": [
            {**dict(o), "label_fi": OBJECTION_LABELS_FI.get(o["category"], o["category"]),
             "booked_rate": round(o["calls_booked_anyway"] / o["calls"], 3) if o["calls"] else None,
             "handled_rate": round(o["handled"] / o["mentions"], 3) if o["mentions"] else None,
             "examples": per_cat.get(o["category"], [])}
            for o in objections
        ],
        "blockers": [dict(b) for b in blockers],
        "sentiment": [dict(s) for s in sentiment],
        "stages": [dict(s) for s in stages],
        "friction_samples": [dict(f) for f in friction],
    }


def build_funnel_prompt(stats: dict) -> str:
    return (
        "Olet myynnin kehittäjä. Alla on mitattu yhteenveto B2B-myyntipuheluista (tapaamisten bookkaus). "
        "Kaikki luvut ovat tietokannasta; esimerkit ovat analysoijan poimimia, anonymisoituja.\n"
        "Tehtävä: löydä mikä estää bookkauksia ja mitä kannattaa muuttaa spiikissä, kohdistuksessa tai tarjouksessa.\n\n"
        "Palauta VAIN yksi JSON-objekti:\n"
        '{"headline_fi": "yksi lause tärkeimmästä havainnosta",\n'
        ' "findings": [{"title_fi": "...", "evidence_fi": "viittaa lukuihin alta", "impact": "high|medium|low"}],\n'
        ' "recommendations": [{"action_fi": "...", "why_fi": "...", "area": "script|targeting|offer|caller_skill|data"}],\n'
        ' "script_changes": [{"objection_category": "' + "|".join(OBJECTION_CATEGORIES) + '", "suggested_reply_fi": "valmis repliikki soittajalle"}],\n'
        ' "data_gaps_fi": ["mitä ei voi päätellä koska dataa on liian vähän"]}\n'
        "Säännöt: käytä vain alla olevia lukuja, älä keksi prosentteja. Jos analysoituja puheluita on alle 20, "
        "sano se data_gaps_fi:ssä ja pidä suositukset varovaisina. Ei nimiä, numeroita tai yrityksiä tunnistettavasti.\n\n"
        f"<stats>\n{json.dumps(stats, ensure_ascii=False, default=str)[:60000]}\n</stats>"
    )
