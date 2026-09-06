from __future__ import annotations

import os
from uuid import uuid4

os.environ.setdefault("DATABASE_URL", "sqlite+pysqlite:///:memory:")

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.deps import get_job_store
from app.db.base import Base
from app.main import app
from app.models.jobs import BackgroundJob  # noqa: F401
from app.services.jobs import BackgroundJobStore


@pytest.fixture
def client() -> TestClient:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    store = BackgroundJobStore(factory)
    app.dependency_overrides[get_job_store] = lambda: store
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.clear()


def command_payload() -> dict[str, object]:
    return {
        "candidate_id": str(uuid4()),
        "artist_id": str(uuid4()),
        "concept_id": str(uuid4()),
        "audio_use_plan_id": str(uuid4()),
        "render_plan_id": str(uuid4()),
        "track_id": str(uuid4()),
        "asset_ids": [str(uuid4())],
        "target_platform": "FAKE",
        "policy_classification": {"classified": True},
        "caption": "test",
        "lineage": {"source": "api-test"},
    }


def test_publication_command_is_idempotent_and_inspectable(client: TestClient) -> None:
    payload = command_payload()
    first = client.post("/v1/jobs/publication", json=payload)
    assert first.status_code == 202, first.text
    first_body = first.json()
    assert first_body["status"] == "PENDING"
    assert first_body["reused"] is False

    second = client.post("/v1/jobs/publication", json=payload)
    assert second.status_code == 202, second.text
    second_body = second.json()
    assert second_body["id"] == first_body["id"]
    assert second_body["reused"] is True

    status = client.get(f"/v1/jobs/{first_body['id']}")
    assert status.status_code == 200
    assert status.json()["attempt_count"] == 0
    assert status.json()["status"] == "PENDING"


def test_same_idempotency_key_with_changed_command_is_conflict(client: TestClient) -> None:
    payload = command_payload()
    assert client.post("/v1/jobs/publication", json=payload).status_code == 202

    changed = {**payload, "caption": "different"}
    response = client.post("/v1/jobs/publication", json=changed)
    assert response.status_code == 409


def test_command_rejects_worker_owned_output_path(client: TestClient) -> None:
    payload = command_payload()
    payload["output_path"] = "/etc/sensitive-output.mp4"
    response = client.post(
        "/v1/jobs/publication",
        json=payload,
    )
    assert response.status_code == 422
