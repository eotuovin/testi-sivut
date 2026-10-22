import glob
import logging
import os
from contextlib import contextmanager
from typing import Iterator

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Connection

from app.config import settings

log = logging.getLogger(__name__)

MIGRATIONS_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "migrations")
_MIGRATIONS_LOCK_KEY = 7_120_441_902

engine = create_engine(settings.DATABASE_URL, pool_pre_ping=True, future=True)


@contextmanager
def db_conn() -> Iterator[Connection]:
    """One transaction per request / unit of work. Commits on success."""
    with engine.begin() as conn:
        yield conn


def apply_migrations() -> list[str]:
    """Apply migrations/*.sql in filename order. Every file is re-run safe.

    Runs under a session advisory lock so two containers starting together
    cannot race on IF NOT EXISTS DDL (which Postgres does not make atomic
    across sessions). Uses SQLAlchemy's AUTOCOMMIT execution option rather
    than the driver's autocommit flag so nothing leaks into the pool.
    Each file is executed as one script through the DBAPI cursor because
    files contain multiple statements and dollar-quoted function bodies,
    which text() parameter parsing would mangle.
    """
    applied: list[str] = []
    with engine.connect().execution_options(isolation_level="AUTOCOMMIT") as conn:
        conn.execute(text("SELECT pg_advisory_lock(:k)"), {"k": _MIGRATIONS_LOCK_KEY})
        try:
            for path in sorted(glob.glob(os.path.join(MIGRATIONS_DIR, "*.sql"))):
                with open(path, encoding="utf-8") as f:
                    sql = f.read()
                raw = conn.connection.cursor()
                try:
                    raw.execute(sql)
                finally:
                    raw.close()
                applied.append(os.path.basename(path))
                log.info("migration applied: %s", os.path.basename(path))
        finally:
            conn.execute(text("SELECT pg_advisory_unlock(:k)"), {"k": _MIGRATIONS_LOCK_KEY})
    return applied
