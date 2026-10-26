import logging
import os

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import text

from app.auth import hash_password
from app.config import settings
from app.db import db_conn
from app.routers import calls, campaigns, companies, integrations, intelligence, prospecting, session, telephony

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

app = FastAPI(title="Luuri – myyntipuhelut", version="0.1.0")

for r in (session, companies, campaigns, calls, prospecting, integrations, telephony, intelligence):
    app.include_router(r.router, prefix="/api")


@app.get("/api/health")
def health():
    with db_conn() as conn:
        conn.execute(text("SELECT 1"))
    return {"ok": True}


def bootstrap_admin() -> None:
    """Create the first admin from env if the users table is empty."""
    if not (settings.BOOTSTRAP_ADMIN_EMAIL and settings.BOOTSTRAP_ADMIN_PASSWORD):
        return
    with db_conn() as conn:
        if conn.execute(text("SELECT count(*) FROM users")).scalar():
            return
        conn.execute(
            text("INSERT INTO users (email, name, role, password_hash) VALUES (:e, 'Admin', 'admin', :h)"),
            {"e": settings.BOOTSTRAP_ADMIN_EMAIL, "h": hash_password(settings.BOOTSTRAP_ADMIN_PASSWORD)},
        )
        logging.getLogger(__name__).info("bootstrap admin created: %s", settings.BOOTSTRAP_ADMIN_EMAIL)


@app.on_event("startup")
def _startup():
    bootstrap_admin()


# Built frontend (frontend/dist) is served by the same process in production.
_DIST = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "frontend", "dist")
if os.path.isdir(_DIST):
    app.mount("/assets", StaticFiles(directory=os.path.join(_DIST, "assets")), name="assets")

    @app.get("/{full_path:path}", include_in_schema=False)
    def spa(full_path: str):
        return FileResponse(os.path.join(_DIST, "index.html"))
