from app.db.session import SessionLocal
from app.services.jobs import BackgroundJobStore


def get_job_store() -> BackgroundJobStore:
    return BackgroundJobStore(SessionLocal)
