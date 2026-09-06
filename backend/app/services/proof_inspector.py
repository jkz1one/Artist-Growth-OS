from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.domain.enums import PlatformProofStatus
from app.models.platform_proof import (
    PlatformAccount,
    PlatformCapabilitySnapshot,
    PlatformProofEvent,
    PlatformProofRun,
)
from app.services.proof_security import ensure_safe_evidence


class ProofInspector:
    """Read-only projection of durable platform-proof state for operator UIs."""

    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self.session_factory = session_factory

    def list_runs(
        self,
        *,
        platform: str | None = None,
        status: PlatformProofStatus | None = None,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        if limit < 1 or limit > 200:
            raise ValueError("limit must be between 1 and 200")

        statement = (
            select(PlatformProofRun, PlatformAccount)
            .join(PlatformAccount, PlatformAccount.id == PlatformProofRun.platform_account_id)
            .order_by(PlatformProofRun.created_at.desc(), PlatformProofRun.id.desc())
            .limit(limit)
        )
        if platform:
            statement = statement.where(PlatformAccount.platform == platform)
        if status is not None:
            statement = statement.where(PlatformProofRun.status == status)

        with self.session_factory() as session:
            rows = session.execute(statement).all()
            result = [self._summary(run, account) for run, account in rows]

        ensure_safe_evidence(result, path="proof_inspector.runs")
        return result

    def inspect_run(self, run_id: UUID) -> dict[str, Any]:
        with self.session_factory() as session:
            row = session.execute(
                select(PlatformProofRun, PlatformAccount)
                .join(PlatformAccount, PlatformAccount.id == PlatformProofRun.platform_account_id)
                .where(PlatformProofRun.id == run_id)
            ).one_or_none()
            if row is None:
                raise RuntimeError("proof run not found")
            run, account = row

            snapshot = (
                session.get(PlatformCapabilitySnapshot, run.capability_snapshot_id)
                if run.capability_snapshot_id is not None
                else None
            )
            events = session.scalars(
                select(PlatformProofEvent)
                .where(PlatformProofEvent.proof_run_id == run.id)
                .order_by(PlatformProofEvent.sequence)
            ).all()

            result = {
                **self._summary(run, account),
                "caption": run.caption,
                "idempotency_key": run.idempotency_key,
                "remote_context": dict(run.remote_context or {}),
                "result": run.result_json,
                "capability_snapshot": self._snapshot(snapshot),
                "events": [self._event(event) for event in events],
            }

        ensure_safe_evidence(result, path="proof_inspector.run")
        return result

    @classmethod
    def _summary(
        cls, run: PlatformProofRun, account: PlatformAccount
    ) -> dict[str, Any]:
        return {
            "id": str(run.id),
            "proof_key": run.proof_key,
            "status": run.status.value,
            "platform": account.platform,
            "platform_account_id": str(account.id),
            "external_account_id": account.external_account_id,
            "display_name": account.display_name,
            "account_type": account.account_type,
            "account_active": account.active,
            "api_family": account.api_family,
            "media_uri": run.media_uri,
            "platform_post_id": run.platform_post_id,
            "canonical_url": run.canonical_url,
            "last_error": run.last_error,
            "created_at": run.created_at.isoformat(),
            "published_at": run.published_at.isoformat() if run.published_at else None,
            "completed_at": run.completed_at.isoformat() if run.completed_at else None,
            "attention": cls._attention(run.status),
        }

    @staticmethod
    def _snapshot(snapshot: PlatformCapabilitySnapshot | None) -> dict[str, Any] | None:
        if snapshot is None:
            return None
        return {
            "id": str(snapshot.id),
            "api_family": snapshot.api_family,
            "api_version": snapshot.api_version,
            "capabilities": dict(snapshot.capabilities or {}),
            "evidence": dict(snapshot.evidence or {}),
            "captured_at": snapshot.captured_at.isoformat(),
        }

    @staticmethod
    def _event(event: PlatformProofEvent) -> dict[str, Any]:
        return {
            "id": str(event.id),
            "sequence": event.sequence,
            "event_type": event.event_type,
            "payload": dict(event.payload or {}),
            "created_at": event.created_at.isoformat(),
        }

    @staticmethod
    def _attention(status: PlatformProofStatus) -> dict[str, Any]:
        mapping: dict[PlatformProofStatus, tuple[str, str, tuple[str, ...]]] = {
            PlatformProofStatus.CREATED: (
                "SETUP_REQUIRED",
                "capability capture has not completed",
                ("SHOW",),
            ),
            PlatformProofStatus.READY: (
                "READY_FOR_GUARDED_PUBLISH",
                "capabilities captured; any live publish still requires an enabled "
                "platform runner and explicit confirmation",
                ("SHOW", "PUBLISH_GUARDED"),
            ),
            PlatformProofStatus.PUBLISHING: (
                "RECONCILIATION_REQUIRED",
                "remote publication boundary is active; reconcile before considering any retry",
                ("SHOW", "RECONCILE"),
            ),
            PlatformProofStatus.PUBLISHED: (
                "METRICS_PENDING",
                "durable platform post exists; proof metrics remain to be captured",
                ("SHOW", "RECONCILE", "METRICS"),
            ),
            PlatformProofStatus.MEASURING: (
                "MEASURING",
                "metrics collection is in progress",
                ("SHOW",),
            ),
            PlatformProofStatus.PASSED: (
                "COMPLETE",
                "controlled proof completed with durable post evidence and metrics",
                ("SHOW",),
            ),
            PlatformProofStatus.FAILED: (
                "FAILED",
                "proof failed before satisfying the promotion gate",
                ("SHOW",),
            ),
            PlatformProofStatus.RECOVERY_REQUIRED: (
                "RECOVERY_REQUIRED",
                "publication outcome is ambiguous or incomplete; reconcile without republishing",
                ("SHOW", "RECONCILE"),
            ),
        }
        state, reason, actions = mapping[status]
        return {
            "state": state,
            "reason": reason,
            "available_actions": list(actions),
            "read_only": True,
        }
