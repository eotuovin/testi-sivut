"""Migration 005: lists, saved searches and the new profile columns exist and
are re-run safe."""
from sqlalchemy import text

from app.db import apply_migrations, db_conn
from tests.conftest import unique


def test_migration_005_is_rerun_safe():
    applied = apply_migrations()
    assert "005_lists_and_search.sql" in applied
    assert "005_lists_and_search.sql" in apply_migrations()


def test_new_columns_and_tables_exist():
    with db_conn() as conn:
        cols = {
            r[0]
            for r in conn.execute(text("SELECT column_name FROM information_schema.columns WHERE table_name='companies'"))
        }
        assert {"employees", "revenue_eur", "founded_year", "description", "phone", "technologies", "owner_id"} <= cols
        ccols = {
            r[0]
            for r in conn.execute(text("SELECT column_name FROM information_schema.columns WHERE table_name='contacts'"))
        }
        assert {"department", "management_level", "linkedin_url", "verified_at"} <= ccols
        tables = {r[0] for r in conn.execute(text("SELECT table_name FROM information_schema.tables WHERE table_schema='public'"))}
        assert {"lists", "list_members", "saved_searches"} <= tables


def test_list_member_uniqueness():
    with db_conn() as conn:
        company_id = conn.execute(
            text("INSERT INTO companies (name) VALUES (:n) RETURNING id"), {"n": unique("Listayritys")}
        ).scalar_one()
        list_id = conn.execute(text("INSERT INTO lists (name) VALUES (:n) RETURNING id"), {"n": unique("lista")}).scalar_one()
        conn.execute(
            text("INSERT INTO list_members (list_id, company_id) VALUES (:l, :c) ON CONFLICT DO NOTHING"),
            {"l": list_id, "c": company_id},
        )
        conn.execute(
            text("INSERT INTO list_members (list_id, company_id) VALUES (:l, :c) ON CONFLICT DO NOTHING"),
            {"l": list_id, "c": company_id},
        )
        n = conn.execute(text("SELECT count(*) FROM list_members WHERE list_id=:l"), {"l": list_id}).scalar_one()
        assert n == 1
