from __future__ import annotations

import os

import pytest
from fastapi.testclient import TestClient

os.environ.setdefault("DATABASE_URL", "sqlite+pysqlite:///:memory:")

from app.api.auth import CONTROL_PLANE_READ_TOKEN_ENV, JOB_API_TOKEN_ENV
from app.main import app

READ_TOKEN = "control-plane-read-test-0123456789abcdef"
JOB_TOKEN = "job-api-access-test-0123456789abcdef"


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setenv(CONTROL_PLANE_READ_TOKEN_ENV, READ_TOKEN)
    monkeypatch.setenv(JOB_API_TOKEN_ENV, JOB_TOKEN)
    return TestClient(app)


def bearer(value: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {value}"}


def test_control_plane_session_requires_bearer(client: TestClient) -> None:
    response = client.get("/v1/control-plane/session")
    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "Bearer"


def test_control_plane_session_rejects_wrong_token(client: TestClient) -> None:
    response = client.get("/v1/control-plane/session", headers=bearer("x" * 40))
    assert response.status_code == 401


def test_control_plane_read_token_has_no_publication_authority(client: TestClient) -> None:
    response = client.get("/v1/control-plane/session", headers=bearer(READ_TOKEN))
    assert response.status_code == 200
    assert response.json() == {
        "authenticated": True,
        "capability": "control-plane read",
        "publication_authority": False,
    }


def test_job_token_cannot_read_control_plane(client: TestClient) -> None:
    response = client.get("/v1/control-plane/session", headers=bearer(JOB_TOKEN))
    assert response.status_code == 401


def test_control_plane_token_cannot_access_jobs(client: TestClient) -> None:
    response = client.get("/v1/jobs/00000000-0000-0000-0000-000000000000", headers=bearer(READ_TOKEN))
    assert response.status_code == 401


def test_job_api_requires_bearer(client: TestClient) -> None:
    response = client.get("/v1/jobs/00000000-0000-0000-0000-000000000000")
    assert response.status_code == 401


def test_missing_control_plane_configuration_fails_closed(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv(CONTROL_PLANE_READ_TOKEN_ENV)
    response = client.get("/v1/control-plane/session", headers=bearer(READ_TOKEN))
    assert response.status_code == 503


def test_missing_job_configuration_fails_closed(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv(JOB_API_TOKEN_ENV)
    response = client.get("/v1/jobs/00000000-0000-0000-0000-000000000000", headers=bearer(JOB_TOKEN))
    assert response.status_code == 503


def test_weak_configured_token_fails_closed(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(CONTROL_PLANE_READ_TOKEN_ENV, "too-short")
    response = client.get("/v1/control-plane/session", headers=bearer("too-short"))
    assert response.status_code == 503
