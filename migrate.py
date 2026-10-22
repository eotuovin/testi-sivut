"""One-shot: apply migrations/*.sql. Run before the app and worker start."""
import logging

from app.db import apply_migrations

logging.basicConfig(level=logging.INFO)
if __name__ == "__main__":
    applied = apply_migrations()
    print("applied:", ", ".join(applied))
