import os
import uuid

import pytest

os.environ.setdefault("DATABASE_URL", "postgresql+psycopg2://postgres@/salesdesk?host=/tmp&port=5433")
os.environ.setdefault("SESSION_SECRET", "test-secret")
os.environ.setdefault("ENRICH_FETCH_WEBSITES", "false")
os.environ.setdefault("STT_PROVIDER", "none")  # tests opt in per case; never download a model by accident

from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import text  # noqa: E402

from app.auth import hash_password  # noqa: E402
from app.db import apply_migrations, db_conn  # noqa: E402
from app.main import app  # noqa: E402


@pytest.fixture(scope="session", autouse=True)
def migrated():
    apply_migrations()


def unique(prefix: str) -> str:
    """Per-run unique values: tests share a persistent database."""
    return f"{prefix}-{uuid.uuid4().hex[:10]}"


@pytest.fixture
def admin_client():
    email = unique("admin") + "@test.fi"
    with db_conn() as conn:
        conn.execute(
            text("INSERT INTO users (email, name, role, password_hash) VALUES (:e, 'Testi Admin', 'admin', :h)"),
            {"e": email, "h": hash_password("salasana123")},
        )
    client = TestClient(app)
    r = client.post("/api/login", json={"email": email, "password": "salasana123"})
    assert r.status_code == 200, r.text
    return client


@pytest.fixture
def sales_client():
    email = unique("myyja") + "@test.fi"
    with db_conn() as conn:
        conn.execute(
            text("INSERT INTO users (email, name, role, password_hash) VALUES (:e, 'Testi Myyjä', 'sales', :h)"),
            {"e": email, "h": hash_password("salasana123")},
        )
    client = TestClient(app)
    r = client.post("/api/login", json={"email": email, "password": "salasana123"})
    assert r.status_code == 200, r.text
    return client
