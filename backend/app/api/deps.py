from app.db.session import SessionLocal
from app.services.jobs import BackgroundJobStore
from app.services.proof_inspector import ProofInspector


def get_job_store() -> BackgroundJobStore:
    return BackgroundJobStore(SessionLocal)


def get_proof_inspector() -> ProofInspector:
    return ProofInspector(SessionLocal)
