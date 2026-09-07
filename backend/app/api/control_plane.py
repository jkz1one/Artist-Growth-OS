from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from app.api.auth import ApiPrincipal, require_control_plane_read

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
