from __future__ import annotations

import os
import secrets
from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

CONTROL_PLANE_READ_TOKEN_ENV = "CONTROL_PLANE_READ_TOKEN"
JOB_API_TOKEN_ENV = "JOB_API_TOKEN"
MIN_TOKEN_LENGTH = 32

bearer = HTTPBearer(auto_error=False)


@dataclass(frozen=True)
class ApiPrincipal:
    capability: str
    publication_authority: bool = False


def _require_bearer(
    *,
    credentials: HTTPAuthorizationCredentials | None,
    env_name: str,
    capability: str,
) -> ApiPrincipal:
    expected = os.getenv(env_name)
    if not expected or len(expected) < MIN_TOKEN_LENGTH:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"{capability} authentication is not configured",
        )

    if credentials is None or credentials.scheme.lower() != "bearer":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="bearer credential required",
            headers={"WWW-Authenticate": "Bearer"},
        )

    if not secrets.compare_digest(credentials.credentials, expected):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="invalid bearer credential",
            headers={"WWW-Authenticate": "Bearer"},
        )

    return ApiPrincipal(capability=capability)


def require_control_plane_read(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)],
) -> ApiPrincipal:
    return _require_bearer(
        credentials=credentials,
        env_name=CONTROL_PLANE_READ_TOKEN_ENV,
        capability="control-plane read",
    )


def require_job_api_access(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)],
) -> ApiPrincipal:
    return _require_bearer(
        credentials=credentials,
        env_name=JOB_API_TOKEN_ENV,
        capability="job API",
    )
