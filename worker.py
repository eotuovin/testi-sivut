"""Background workers.

  python worker.py core          outbox delivery, live-call polling, prospecting runs
  python worker.py intelligence  recordings → transcription → call analysis → insight reports
  python worker.py               both in one loop (development only)

They are separate processes in production because one agent turn or one
transcription can take minutes, and live-call status must keep updating
every ~1.5 s while a caller is on the phone."""
import logging
import sys
import time

import httpx

from app.config import settings
from app.services.integrations.dispatcher import dispatch_one
from app.services.intelligence.pipeline import tick as intelligence_tick
from app.services.prospecting.runner import claim_next_run, execute_run
from app.services.telephony.service import poll_active_sessions

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("worker")


def core_tick(client: httpx.Client) -> tuple[bool, int]:
    busy = False
    while dispatch_one(client):
        busy = True
    try:
        active_calls = poll_active_sessions(client)
    except Exception:  # noqa: BLE001
        log.exception("telephony poll failed")
        active_calls = 0
    run = claim_next_run()
    if run:
        busy = True
        log.info("prospecting run %s: %s", run["id"], run["criteria"])
        execute_run(run["id"], run["campaign_id"], run["criteria"])
    return busy, active_calls


def main(mode: str = "all") -> None:
    log.info("luuri worker started (%s)", mode)
    with httpx.Client(timeout=20.0) as client:
        while True:
            busy, active_calls = False, 0
            if mode in ("core", "all"):
                busy, active_calls = core_tick(client)
            if mode in ("intelligence", "all"):
                busy |= intelligence_tick(client)
            if not busy:
                # poll faster while someone is on a call so the UI follows along
                time.sleep(1.5 if active_calls else settings.WORKER_POLL_SECONDS)


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "all")
