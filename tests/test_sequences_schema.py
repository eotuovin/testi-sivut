"""Migration 006: sequence tables exist and are re-run safe."""
from sqlalchemy import text

from app.db import apply_migrations, db_conn
from tests.conftest import unique


def test_migration_006_is_rerun_safe():
    assert "006_sequences.sql" in apply_migrations()
    assert "006_sequences.sql" in apply_migrations()


def test_sequence_tables_and_one_active_enrollment_per_company():
    with db_conn() as conn:
        tables = {r[0] for r in conn.execute(text("SELECT table_name FROM information_schema.tables WHERE table_schema='public'"))}
        assert {"sequences", "sequence_steps", "sequence_enrollments", "sequence_actions"} <= tables
        seq = conn.execute(text("INSERT INTO sequences (name) VALUES (:n) RETURNING id"), {"n": unique("seq")}).scalar_one()
        co = conn.execute(text("INSERT INTO companies (name) VALUES (:n) RETURNING id"), {"n": unique("Seqfirma")}).scalar_one()
        conn.execute(text("INSERT INTO sequence_enrollments (sequence_id, company_id) VALUES (:s, :c)"), {"s": seq, "c": co})
        dup = conn.execute(
            text("INSERT INTO sequence_enrollments (sequence_id, company_id) VALUES (:s, :c) ON CONFLICT DO NOTHING RETURNING id"),
            {"s": seq, "c": co},
        ).first()
        assert dup is None
        # a finished run does not block a new one
        conn.execute(text("UPDATE sequence_enrollments SET status='finished' WHERE sequence_id=:s"), {"s": seq})
        again = conn.execute(text("INSERT INTO sequence_enrollments (sequence_id, company_id) VALUES (:s, :c) RETURNING id"), {"s": seq, "c": co}).first()
        assert again is not None
