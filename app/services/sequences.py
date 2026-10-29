"""Sequence engine. An enrollment walks through its sequence's steps on a
schedule; `tick()` (called from the core worker) materialises every step that
is due:

  call   → a call_task in the sequence's campaign queue, pinned to the enrolled
           person; the caller handles it on the Soita screen like any other
  email  → rendered from the template and sent over SMTP when configured,
           otherwise left `pending` in the task inbox for the seller to send
  task   → a to-do in the task inbox (LinkedIn, letter, whatever the step says)

A call outcome in `stop_on_outcomes` stops the enrollment (see on_call_logged),
so nobody keeps e-mailing a company that just said no."""
from __future__ import annotations

import logging
import smtplib
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.engine import Connection

from app.config import settings
from app.db import db_conn
from app.services.outbox import emit

log = logging.getLogger(__name__)


def render(template: str | None, ctx: dict[str, Any]) -> str:
    out = template or ""
    for k, v in ctx.items():
        out = out.replace("{{" + k + "}}", str(v or ""))
    return out


def _context(conn: Connection, enrollment: dict) -> dict[str, Any]:
    co = conn.execute(text("SELECT name, city, website FROM companies WHERE id=:id"), {"id": enrollment["company_id"]}).mappings().one()
    ct = conn.execute(text("SELECT name, title, email FROM contacts WHERE id=:id"), {"id": enrollment["contact_id"]}).mappings().first() if enrollment["contact_id"] else None
    seller = conn.execute(text("SELECT name, email FROM users WHERE id=:id"), {"id": enrollment["started_by"]}).mappings().first() if enrollment["started_by"] else None
    seq = conn.execute(
        text("SELECT s.name, cp.product FROM sequences s LEFT JOIN campaigns cp ON cp.id=s.campaign_id WHERE s.id=:id"), {"id": enrollment["sequence_id"]}
    ).mappings().one()
    name = (ct["name"] if ct else None) or ""
    return {
        "yritys": co["name"], "paikkakunta": co["city"], "nimi": name, "etunimi": name.split(" ")[0] if name else "",
        "titteli": ct["title"] if ct else "", "myyja": seller["name"] if seller else "", "myyja_email": seller["email"] if seller else "",
        "tuote": seq["product"] or "", "sekvenssi": seq["name"],
    }


def send_email(to: str, subject: str, body: str, reply_to: str | None = None) -> str:
    """Returns 'smtp' when sent; raises when SMTP is configured but fails;
    returns 'manual' when SMTP is not configured."""
    if not settings.SMTP_HOST:
        return "manual"
    msg = EmailMessage()
    msg["From"] = settings.SMTP_FROM or settings.SMTP_USER or "luuri@localhost"
    msg["To"] = to
    msg["Subject"] = subject
    if reply_to:
        msg["Reply-To"] = reply_to
    msg.set_content(body)
    with smtplib.SMTP(settings.SMTP_HOST, settings.SMTP_PORT, timeout=20) as s:
        if settings.SMTP_STARTTLS:
            s.starttls()
        if settings.SMTP_USER:
            s.login(settings.SMTP_USER, settings.SMTP_PASSWORD or "")
        s.send_message(msg)
    return "smtp"


def _finish(conn: Connection, enrollment_id: UUID, status: str, reason: str) -> None:
    row = conn.execute(
        text("UPDATE sequence_enrollments SET status=:st, finished_reason=:r, next_at=NULL WHERE id=:id AND status='active' RETURNING sequence_id, company_id"),
        {"st": status, "r": reason, "id": enrollment_id},
    ).mappings().first()
    if row:
        conn.execute(text("UPDATE sequence_actions SET status='skipped' WHERE enrollment_id=:e AND status='pending'"), {"e": enrollment_id})
        emit(conn, "sequence.finished", "sequence_enrollment", enrollment_id,
             {"sequence_id": row["sequence_id"], "company_id": row["company_id"], "finished_reason": reason, "status": status})


def materialise_step(conn: Connection, enrollment: dict, step: dict) -> dict:
    ctx = _context(conn, enrollment)
    seq = conn.execute(text("SELECT campaign_id, stop_on_outcomes FROM sequences WHERE id=:id"), {"id": enrollment["sequence_id"]}).mappings().one()
    action: dict[str, Any] = {
        "e": enrollment["id"], "s": step["id"], "pos": step["position"], "kind": step["kind"], "status": "pending",
        "task": None, "to": None, "subject": render(step["title"], ctx), "body": render(step["body"], ctx), "via": None, "err": None,
    }
    if step["kind"] == "call":
        if seq["campaign_id"] is None:
            action["status"], action["err"] = "failed", "sekvenssillä ei ole kampanjaa, johon soitto jonotettaisiin"
        else:
            task_id = conn.execute(
                text(
                    """
                    INSERT INTO call_tasks (campaign_id, company_id, contact_id, priority, due_at)
                    VALUES (:cp, :co, COALESCE(:ct, (SELECT id FROM contacts c WHERE c.company_id=:co AND c.phone_e164 IS NOT NULL AND NOT c.do_not_call
                                                     ORDER BY c.is_primary DESC, c.confidence DESC NULLS LAST LIMIT 1)), 10, now())
                    ON CONFLICT (campaign_id, company_id) DO UPDATE
                        SET status = CASE WHEN call_tasks.status IN ('done', 'skipped') THEN 'queued' ELSE call_tasks.status END,
                            due_at = LEAST(call_tasks.due_at, now()), priority = GREATEST(call_tasks.priority, 10),
                            contact_id = COALESCE(EXCLUDED.contact_id, call_tasks.contact_id)
                    RETURNING id
                    """
                ),
                {"cp": seq["campaign_id"], "co": enrollment["company_id"], "ct": enrollment["contact_id"]},
            ).scalar_one()
            action["task"], action["status"] = task_id, "done"
    elif step["kind"] == "email":
        to = conn.execute(text("SELECT email FROM contacts WHERE id=:id"), {"id": enrollment["contact_id"]}).scalar() if enrollment["contact_id"] else None
        to = to or conn.execute(text("SELECT email FROM companies WHERE id=:id"), {"id": enrollment["company_id"]}).scalar()
        action["to"] = to
        if not to:
            action["status"], action["err"] = "failed", "ei sähköpostiosoitetta"
        else:
            try:
                via = send_email(to, action["subject"], action["body"], reply_to=ctx.get("myyja_email") or None)
            except Exception as exc:  # noqa: BLE001 — the action records the failure, the worker goes on
                action["status"], action["err"] = "failed", str(exc)[:500]
            else:
                action["via"] = via
                action["status"] = "done" if via == "smtp" else "pending"
    # task: stays pending for the seller
    row = conn.execute(
        text(
            """
            INSERT INTO sequence_actions (enrollment_id, step_id, position, kind, status, due_at, done_at, task_id, email_to, subject, body, sent_via, error)
            VALUES (:e, :s, :pos, :kind, :status, now(), CASE WHEN :status = 'done' THEN now() END, :task, :to, :subject, :body, :via, :err)
            RETURNING id
            """
        ),
        action,
    ).mappings().one()
    if action["status"] == "done":
        emit(conn, "sequence.step_done", "sequence_action", row["id"],
             {"sequence_id": enrollment["sequence_id"], "company_id": enrollment["company_id"], "step_kind": step["kind"],
              "step_position": step["position"], "sent_via": action["via"]})
    return {**action, "id": row["id"]}


def advance(conn: Connection, enrollment_id: UUID) -> bool:
    """Materialise the next step of one enrollment. Returns True when a step was processed."""
    enr = conn.execute(text("SELECT * FROM sequence_enrollments WHERE id=:id AND status='active' FOR UPDATE SKIP LOCKED"), {"id": enrollment_id}).mappings().first()
    if enr is None:
        return False
    steps = conn.execute(text("SELECT * FROM sequence_steps WHERE sequence_id=:s ORDER BY position"), {"s": enr["sequence_id"]}).mappings().all()
    idx = enr["current_step"]
    if idx >= len(steps):
        _finish(conn, enr["id"], "finished", "kaikki askeleet tehty")
        return True
    step = dict(steps[idx])
    materialise_step(conn, dict(enr), step)
    nxt = steps[idx + 1] if idx + 1 < len(steps) else None
    if nxt is None:
        conn.execute(text("UPDATE sequence_enrollments SET current_step=:i, next_at=NULL, status='finished', finished_reason='kaikki askeleet tehty' WHERE id=:id"), {"i": idx + 1, "id": enr["id"]})
        emit(conn, "sequence.finished", "sequence_enrollment", enr["id"], {"sequence_id": enr["sequence_id"], "company_id": enr["company_id"], "finished_reason": "kaikki askeleet tehty", "status": "finished"})
    else:
        due = datetime.now(timezone.utc) + timedelta(days=nxt["delay_days"], hours=nxt["delay_hours"])
        conn.execute(text("UPDATE sequence_enrollments SET current_step=:i, next_at=:n WHERE id=:id"), {"i": idx + 1, "n": due, "id": enr["id"]})
    return True


def tick(limit: int = 50) -> bool:
    """One worker pass: process every enrollment whose next step is due."""
    with db_conn() as conn:
        ids = [r[0] for r in conn.execute(
            text("SELECT e.id FROM sequence_enrollments e JOIN sequences s ON s.id=e.sequence_id WHERE e.status='active' AND s.status='active' AND e.next_at <= now() ORDER BY e.next_at LIMIT :l"),
            {"l": limit},
        )]
    busy = False
    for eid in ids:
        try:
            with db_conn() as conn:
                busy |= advance(conn, eid)
        except Exception:  # noqa: BLE001
            log.exception("sequence enrollment %s failed", eid)
            with db_conn() as conn:
                conn.execute(text("UPDATE sequence_enrollments SET status='failed', finished_reason='virhe, katso loki', next_at=NULL WHERE id=:id"), {"id": eid})
    return busy


def on_call_logged(conn: Connection, task_id: UUID | None, company_id: UUID, outcome: str) -> None:
    """A call outcome that means 'stop' ends every active enrollment of the company
    whose sequence lists that outcome."""
    rows = conn.execute(
        text(
            """
            SELECT e.id FROM sequence_enrollments e JOIN sequences s ON s.id=e.sequence_id
            WHERE e.status='active' AND e.company_id=:co AND :o = ANY(s.stop_on_outcomes)
            """
        ),
        {"co": company_id, "o": outcome},
    ).all()
    for (eid,) in rows:
        _finish(conn, eid, "stopped", f"puhelun tulos: {outcome}")
    if task_id is not None:
        conn.execute(
            text("UPDATE sequence_actions SET status='done', done_at=now() WHERE task_id=:t AND status='pending'"), {"t": task_id}
        )
