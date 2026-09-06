from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from app.domain.enums import PlatformProofStatus
from app.models.platform_proof import PlatformAccount, PlatformProofEvent, PlatformProofRun
from app.services.proof_security import ensure_safe_evidence


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class ProofStore:
    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self.session_factory = session_factory

    def create_account(
        self,
        *,
        platform: str,
        external_account_id: str,
        api_family: str,
        display_name: str | None,
        account_type: str | None,
    ) -> PlatformAccount:
        with self.session_factory() as session:
            account = session.scalar(
                select(PlatformAccount).where(
                    PlatformAccount.platform == platform,
                    PlatformAccount.external_account_id == external_account_id,
                )
            )
            if account is None:
                account = PlatformAccount(
                    platform=platform,
                    external_account_id=external_account_id,
                    display_name=display_name,
                    account_type=account_type,
                    api_family=api_family,
                )
                session.add(account)
                session.commit()
                session.refresh(account)
            elif account.api_family != api_family:
                raise ValueError("platform account already exists with a different api_family")
            session.expunge(account)
            return account

    def start_run(
        self,
        *,
        platform_account_id: UUID,
        proof_key: str,
        media_uri: str,
        caption: str,
    ) -> PlatformProofRun:
        with self.session_factory() as session:
            existing = session.scalar(
                select(PlatformProofRun).where(
                    PlatformProofRun.platform_account_id == platform_account_id,
                    PlatformProofRun.proof_key == proof_key,
                )
            )
            if existing is not None:
                if existing.media_uri != media_uri or existing.caption != caption:
                    raise ValueError("proof_key already exists with different proof input")
                session.expunge(existing)
                return existing

            run = PlatformProofRun(
                platform_account_id=platform_account_id,
                proof_key=proof_key,
                media_uri=media_uri,
                caption=caption,
                idempotency_key=f"proof:{platform_account_id}:{proof_key}",
                status=PlatformProofStatus.CREATED,
            )
            session.add(run)
            session.flush()
            self.append_event(session, run.id, "RUN_CREATED", {"proof_key": proof_key})
            session.commit()
            session.refresh(run)
            session.expunge(run)
            return run

    def get_run(self, run_id: UUID) -> PlatformProofRun:
        with self.session_factory() as session:
            run = session.get(PlatformProofRun, run_id)
            if run is None:
                raise RuntimeError("proof run not found")
            session.expunge(run)
            return run

    def load_run_account(
        self, session: Session, run_id: UUID
    ) -> tuple[PlatformProofRun, PlatformAccount]:
        run = session.get(PlatformProofRun, run_id)
        if run is None:
            raise RuntimeError("proof run not found")
        account = session.get(PlatformAccount, run.platform_account_id)
        if account is None or not account.active:
            raise RuntimeError("platform account is missing or inactive")
        return run, account

    def append_event(
        self,
        session: Session,
        run_id: UUID,
        event_type: str,
        payload: dict[str, Any],
    ) -> None:
        ensure_safe_evidence(payload)
        next_sequence = session.scalar(
            select(func.coalesce(func.max(PlatformProofEvent.sequence), 0)).where(
                PlatformProofEvent.proof_run_id == run_id
            )
        )
        session.add(
            PlatformProofEvent(
                id=uuid4(),
                proof_run_id=run_id,
                sequence=int(next_sequence or 0) + 1,
                event_type=event_type,
                payload=payload,
            )
        )
