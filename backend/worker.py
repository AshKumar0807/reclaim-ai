# FILE: backend/worker.py
"""Standalone worker process (spec 18: workers scale independently of the API).

Used for the RabbitMQ profile:  python worker.py
Consumes recovery jobs and runs each through the LangGraph workflow. For the
LOCAL profile the API process already runs an in-process worker, so this is
optional there.
"""
from __future__ import annotations

import signal
import time

from app import db, seed
from app.config import get_settings
from app.jobs import start_worker
from app.logging_config import configure_logging, get_logger

logger = get_logger("reclaimai.worker")


def main() -> None:
    configure_logging()
    settings = get_settings()
    db.init_db()
    if not db.query_one("SELECT id FROM merchants LIMIT 1"):
        seed.run()
    logger.info("worker_boot", extra={"ctx_queue": settings.queue_provider})
    start_worker()

    stop = {"flag": False}

    def _handle(_sig, _frame):
        stop["flag"] = True

    signal.signal(signal.SIGINT, _handle)
    signal.signal(signal.SIGTERM, _handle)
    while not stop["flag"]:
        time.sleep(0.5)
    logger.info("worker_shutdown")


if __name__ == "__main__":
    main()
