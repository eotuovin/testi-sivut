"""Migration 007: browser-call columns exist and the migration is re-run safe."""
from sqlalchemy import text

from app.db import apply_migrations, db_conn


def test_migration_007_rerun_safe_and_columns_present():
    assert "007_browser_calls.sql" in apply_migrations()
    assert "007_browser_calls.sql" in apply_migrations()
    with db_conn() as conn:
        users = {r[0] for r in conn.execute(text("SELECT column_name FROM information_schema.columns WHERE table_name='users'"))}
        sessions = {r[0] for r in conn.execute(text("SELECT column_name FROM information_schema.columns WHERE table_name='call_sessions'"))}
        recs = {r[0] for r in conn.execute(text("SELECT column_name FROM information_schema.columns WHERE table_name='call_recordings'"))}
    assert "telnyx_credential_id" in users
    assert {"provider_session_id", "client_seen_at", "muted"} <= sessions
    assert "provider" in recs
