from __future__ import annotations

import os
import socket
import time
from pathlib import Path

from app.api.jobs import PUBLICATION_JOB_TYPE
from app.db.session import SessionLocal
from app.services.jobs import BackgroundJobStore
from app.workers.base import DurableWorker
from app.workers.publication import PublicationJobHandler


def build_worker() -> DurableWorker:
    worker_id = os.getenv("WORKER_ID", f"{socket.gethostname()}:{os.getpid()}")
    render_root = Path(os.getenv("RENDER_ROOT", "var/renders")).resolve()
    store = BackgroundJobStore(SessionLocal)
    handler = PublicationJobHandler(session_factory=SessionLocal, render_root=render_root)
    return DurableWorker(
        store=store,
        worker_id=worker_id,
        handlers={PUBLICATION_JOB_TYPE: handler},
        lease_seconds=int(os.getenv("JOB_LEASE_SECONDS", "600")),
    )


def main() -> None:
    worker = build_worker()
    poll_seconds = float(os.getenv("JOB_POLL_SECONDS", "1.0"))
    while True:
        result = worker.run_once()
        if result is None:
            time.sleep(poll_seconds)


if __name__ == "__main__":
    main()
