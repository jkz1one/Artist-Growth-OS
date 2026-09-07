from __future__ import annotations

import os
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient

os.environ.setdefault("DATABASE_URL", "sqlite+pysqlite:///:memory:")

from app.api.auth import CONTROL_PLANE_READ_TOKEN_ENV, JOB_API_TOKEN_ENV
from app.api.deps import get_proof_inspector
from app.domain.enums import PlatformProofStatus
from app.main import app

READ_TOKEN = "control-plane-read-api-test-0123456789abcdef"
JOB_TOKEN = "job-api-proof-read-test-0123456789abcdef"


class FakeProofInspector:
    def __init__(self) -> None:
        self.list_call: dict[str, object] | None = None
        self.inspect_call: UUID | None = None

    def list_runs(
        self,
        *,
        platform: str | None = None,
        status: PlatformProofStatus | None = None,
        limit: int = 50,
    ) -> list[dict[str, object]]:
        self.list_call = {"platform": platform, "status": status, "limit": limit}
        return [
            {
                "id": str(uuid4()),
                "platform": platform or "INSTAGRAM",
                "status": (status or PlatformProofStatus.READY).value,
                "attention": {"read_only": True},
            }
        ]

    def inspect_run(self, run_id: UUID) -> dict[str, object]:
        self.inspect_call = run_id
        return {
            "id": str(run_id),
            "platform": "INSTAGRAM",
            "status": PlatformProofStatus.READY.value,
            "events": [],
            "attention": {"read_only": True},
        }


@pytest.fixture
def inspector() -> FakeProofInspector:
    return FakeProofInspector()


@pytest.fixture
def client(
    monkeypatch: pytest.MonkeyPatch,
    inspector: FakeProofInspector,
) -> TestClient:
    monkeypatch.setenv(CONTROL_PLANE_READ_TOKEN_ENV, READ_TOKEN)
    monkeypatch.setenv(JOB_API_TOKEN_ENV, JOB_TOKEN)
    app.dependency_overrides[get_proof_inspector] = lambda: inspector
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.clear()


def bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def test_list_proofs_requires_control_plane_auth(client: TestClient) -> None:
    response = client.get("/v1/control-plane/proofs")
    assert response.status_code == 401


def test_job_token_cannot_list_proofs(client: TestClient) -> None:
    response = client.get("/v1/control-plane/proofs", headers=bearer(JOB_TOKEN))
    assert response.status_code == 401


def test_list_proofs_forwards_bounded_filters(
    client: TestClient,
    inspector: FakeProofInspector,
) -> None:
    response = client.get(
        "/v1/control-plane/proofs",
        params={"platform": "TIKTOK", "status": "READY", "limit": 25},
        headers=bearer(READ_TOKEN),
    )
    assert response.status_code == 200, response.text
    assert inspector.list_call == {
        "platform": "TIKTOK",
        "status": PlatformProofStatus.READY,
        "limit": 25,
    }
    assert response.json()[0]["attention"]["read_only"] is True


def test_list_proofs_rejects_out_of_range_limit(client: TestClient) -> None:
    response = client.get(
        "/v1/control-plane/proofs",
        params={"limit": 201},
        headers=bearer(READ_TOKEN),
    )
    assert response.status_code == 422


def test_get_proof_returns_read_only_projection(
    client: TestClient,
    inspector: FakeProofInspector,
) -> None:
    run_id = uuid4()
    response = client.get(
        f"/v1/control-plane/proofs/{run_id}",
        headers=bearer(READ_TOKEN),
    )
    assert response.status_code == 200, response.text
    assert inspector.inspect_call == run_id
    assert response.json()["id"] == str(run_id)
    assert response.json()["attention"]["read_only"] is True


def test_get_proof_maps_missing_run_to_404(
    client: TestClient,
    inspector: FakeProofInspector,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def missing(_run_id: UUID) -> dict[str, object]:
        raise RuntimeError("proof run not found")

    monkeypatch.setattr(inspector, "inspect_run", missing)
    response = client.get(
        f"/v1/control-plane/proofs/{uuid4()}",
        headers=bearer(READ_TOKEN),
    )
    assert response.status_code == 404


def test_control_plane_exposes_no_proof_write_route(client: TestClient) -> None:
    response = client.post(
        "/v1/control-plane/proofs",
        json={},
        headers=bearer(READ_TOKEN),
    )
    assert response.status_code == 405
