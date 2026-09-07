from __future__ import annotations

from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel

from app.api.auth import ApiPrincipal, require_control_plane_read
from app.api.deps import get_proof_inspector
from app.domain.enums import PlatformProofStatus
from app.services.proof_inspector import ProofInspector

router = APIRouter(prefix="/v1/control-plane", tags=["control-plane"])


class OperatorSessionResponse(BaseModel):
    authenticated: bool
    capability: str
    publication_authority: bool


@router.get("/session", response_model=OperatorSessionResponse)
def get_operator_session(
    principal: Annotated[ApiPrincipal, Depends(require_control_plane_read)],
) -> OperatorSessionResponse:
    return OperatorSessionResponse(
        authenticated=True,
        capability=principal.capability,
        publication_authority=principal.publication_authority,
    )


@router.get("/proofs", response_model=list[dict[str, Any]])
def list_proof_runs(
    _principal: Annotated[ApiPrincipal, Depends(require_control_plane_read)],
    inspector: Annotated[ProofInspector, Depends(get_proof_inspector)],
    platform: str | None = None,
    proof_status: Annotated[PlatformProofStatus | None, Query(alias="status")] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> list[dict[str, Any]]:
    return inspector.list_runs(platform=platform, status=proof_status, limit=limit)


@router.get("/proofs/{run_id}", response_model=dict[str, Any])
def get_proof_run(
    run_id: UUID,
    _principal: Annotated[ApiPrincipal, Depends(require_control_plane_read)],
    inspector: Annotated[ProofInspector, Depends(get_proof_inspector)],
) -> dict[str, Any]:
    try:
        return inspector.inspect_run(run_id)
    except RuntimeError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="proof run not found",
        ) from exc
