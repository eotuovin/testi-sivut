"""Background worker: delivers outbox events to integration targets and
executes queued prospecting runs. One process; both loops are cheap."""
import logging
import time

import httpx

from app.config import settings
from app.services.integrations.dispatcher import dispatch_one
from app.services.prospecting.runner import claim_next_run, execute_run
from app.services.telephony.service import poll_active_sessions

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("worker")


def main() -> None:
    log.info("luuri worker started")
    with httpx.Client(timeout=20.0) as client:
        while True:
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
            if not busy:
                # poll faster while someone is on a call so the UI follows along
                time.sleep(1.5 if active_calls else settings.WORKER_POLL_SECONDS)


if __name__ == "__main__":
    main()
