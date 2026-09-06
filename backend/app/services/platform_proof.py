from __future__ import annotations

from uuid import UUID

from app.domain.enums import CapabilitySupport, PlatformProofStatus, PublicationStatus
from app.models.platform_proof import PlatformCapabilitySnapshot, PlatformProofRun
from app.platforms.proof.base import (
    AmbiguousRemotePublishError,
    PlatformProofAdapter,
    ProofPublishRequest,
)
from app.services.proof_security import UnsafeEvidenceError, ensure_safe_evidence
from app.services.proof_store import ProofStore, utcnow


class ProofError(RuntimeError):
    pass


class ProofStateError(ProofError):
    pass


class ProofRecoveryRequired(ProofError):
    pass


class PlatformProofHarness:
    def __init__(self, session_factory) -> None:
        self.session_factory = session_factory
        self.store = ProofStore(session_factory)

    def create_account(
        self,
        *,
        platform: str,
        external_account_id: str,
        api_family: str,
        display_name: str | None = None,
        account_type: str | None = None,
    ):
        return self.store.create_account(
            platform=platform,
            external_account_id=external_account_id,
            api_family=api_family,
            display_name=display_name,
            account_type=account_type,
        )

    def start_run(
        self,
        *,
        platform_account_id: UUID,
        proof_key: str,
        media_uri: str,
        caption: str = "",
    ) -> PlatformProofRun:
        return self.store.start_run(
            platform_account_id=platform_account_id,
            proof_key=proof_key,
            media_uri=media_uri,
            caption=caption,
        )

    def capture_capabilities(
        self, run_id: UUID, adapter: PlatformProofAdapter
    ) -> PlatformCapabilitySnapshot:
        with self.session_factory() as session:
            run, account = self.store.load_run_account(session, run_id)
            self._verify_adapter(account, adapter)
            if run.status not in {PlatformProofStatus.CREATED, PlatformProofStatus.READY}:
                raise ProofStateError("capabilities may only be captured before remote publication")
            external_account_id = account.external_account_id

        report = adapter.inspect_capabilities(external_account_id)
        evidence = {
            "api_family": report.api_family,
            "api_version": report.api_version,
            "evidence": report.evidence,
        }
        ensure_safe_evidence(evidence)

        with self.session_factory() as session:
            run, account = self.store.load_run_account(session, run_id)
            if run.status not in {PlatformProofStatus.CREATED, PlatformProofStatus.READY}:
                raise ProofStateError(
                    "proof run crossed publication boundary during capability capture"
                )
            snapshot = PlatformCapabilitySnapshot(
                platform_account_id=account.id,
                api_family=report.api_family,
                api_version=report.api_version,
                capabilities={key: value.value for key, value in report.capabilities.items()},
                evidence=evidence,
            )
            session.add(snapshot)
            session.flush()
            run.capability_snapshot_id = snapshot.id
            run.status = PlatformProofStatus.READY
            self.store.append_event(
                session,
                run.id,
                "CAPABILITIES_CAPTURED",
                {"snapshot_id": str(snapshot.id), "capabilities": snapshot.capabilities},
            )
            session.commit()
            session.refresh(snapshot)
            session.expunge(snapshot)
            return snapshot

    def publish_once(self, run_id: UUID, adapter: PlatformProofAdapter) -> PlatformProofRun:
        with self.session_factory() as session:
            run, account = self.store.load_run_account(session, run_id)
            self._verify_adapter(account, adapter)
            if run.status != PlatformProofStatus.READY:
                raise ProofStateError(f"proof run cannot publish from {run.status}")
            if run.capability_snapshot_id is None:
                raise ProofStateError("capabilities must be captured before publish")
            snapshot = session.get(PlatformCapabilitySnapshot, run.capability_snapshot_id)
            if snapshot is None:
                raise ProofStateError("capability snapshot is missing")
            if snapshot.capabilities.get("can_publish_video") != CapabilitySupport.SUPPORTED.value:
                raise ProofStateError("video publication capability has not been proven supported")
            run.status = PlatformProofStatus.PUBLISHING
            self.store.append_event(session, run.id, "REMOTE_PUBLISH_STARTED", {})
            session.commit()
            external_account_id = account.external_account_id
            request = ProofPublishRequest(
                media_uri=run.media_uri,
                caption=run.caption,
                idempotency_key=run.idempotency_key,
            )

        def checkpoint(remote_context: dict[str, object]) -> None:
            ensure_safe_evidence(remote_context)
            with self.session_factory() as session:
                current = session.get(PlatformProofRun, run_id)
                if current is None:
                    raise ProofError("proof run disappeared during remote checkpoint")
                if current.status != PlatformProofStatus.PUBLISHING:
                    raise ProofStateError("remote checkpoint arrived outside PUBLISHING")
                current.remote_context = {**(current.remote_context or {}), **remote_context}
                self.store.append_event(
                    session, current.id, "REMOTE_CHECKPOINT", {"context": remote_context}
                )
                session.commit()

        try:
            receipt = adapter.publish_controlled(
                external_account_id, request, checkpoint=checkpoint
            )
            ensure_safe_evidence(receipt.raw)
        except AmbiguousRemotePublishError as exc:
            if exc.remote_context:
                self._merge_remote_context(run_id, exc.remote_context)
            self._mark_recovery_required(run_id, f"remote publish is ambiguous: {exc}")
            raise ProofRecoveryRequired("remote publication requires reconciliation") from exc
        except Exception as exc:
            self._mark_failed(run_id, f"remote publish failed before receipt: {exc}")
            raise

        try:
            return self._persist_publish_receipt(run_id, receipt)
        except Exception as exc:
            self._mark_recovery_required(
                run_id, f"remote publish may have succeeded but receipt persistence failed: {exc}"
            )
            raise ProofRecoveryRequired("remote publication requires reconciliation") from exc

    def reconcile(self, run_id: UUID, adapter: PlatformProofAdapter) -> PlatformProofRun:
        with self.session_factory() as session:
            run, account = self.store.load_run_account(session, run_id)
            self._verify_adapter(account, adapter)
            if run.status not in {
                PlatformProofStatus.PUBLISHING,
                PlatformProofStatus.PUBLISHED,
                PlatformProofStatus.RECOVERY_REQUIRED,
            }:
                raise ProofStateError(f"proof run cannot reconcile from {run.status}")
            external_account_id = account.external_account_id
            platform_post_id = run.platform_post_id
            idempotency_key = run.idempotency_key
            remote_context = dict(run.remote_context or {})

        status = adapter.reconcile_publish(
            external_account_id,
            platform_post_id=platform_post_id,
            idempotency_key=idempotency_key,
            remote_context=remote_context,
        )
        ensure_safe_evidence(status.raw)

        with self.session_factory() as session:
            run = session.get(PlatformProofRun, run_id)
            if run is None:
                raise ProofError("proof run disappeared")
            if status.platform_post_id:
                run.platform_post_id = status.platform_post_id
            if status.canonical_url:
                run.canonical_url = status.canonical_url
            if status.status == PublicationStatus.PUBLISHED:
                run.status = PlatformProofStatus.PUBLISHED
                run.published_at = run.published_at or utcnow()
                run.last_error = None
            elif status.status in {PublicationStatus.REJECTED, PublicationStatus.QUARANTINED}:
                run.status = PlatformProofStatus.FAILED
                run.last_error = f"platform reconciliation returned {status.status}"
            else:
                run.status = PlatformProofStatus.RECOVERY_REQUIRED
                run.last_error = f"platform reconciliation returned {status.status}"
            self.store.append_event(
                session,
                run.id,
                "PUBLISH_RECONCILED",
                {"status": status.status.value, "raw": status.raw},
            )
            session.commit()
            session.refresh(run)
            session.expunge(run)
            return run

    def collect_metrics(self, run_id: UUID, adapter: PlatformProofAdapter) -> PlatformProofRun:
        with self.session_factory() as session:
            run, account = self.store.load_run_account(session, run_id)
            self._verify_adapter(account, adapter)
            if run.status not in {PlatformProofStatus.PUBLISHED, PlatformProofStatus.MEASURING}:
                raise ProofStateError(f"proof run cannot measure from {run.status}")
            if not run.platform_post_id:
                raise ProofStateError("published proof run is missing platform_post_id")
            run.status = PlatformProofStatus.MEASURING
            session.commit()
            external_account_id = account.external_account_id
            platform_post_id = run.platform_post_id

        try:
            metrics = adapter.fetch_metrics(external_account_id, platform_post_id=platform_post_id)
            ensure_safe_evidence(metrics.raw)
        except Exception as exc:
            with self.session_factory() as session:
                run = session.get(PlatformProofRun, run_id)
                if run is not None:
                    run.status = PlatformProofStatus.PUBLISHED
                    run.last_error = f"metrics unavailable: {exc}"
                    self.store.append_event(
                        session, run.id, "METRICS_RETRYABLE", {"error": str(exc)}
                    )
                    session.commit()
            raise

        with self.session_factory() as session:
            run = session.get(PlatformProofRun, run_id)
            if run is None:
                raise ProofError("proof run disappeared")
            run.status = PlatformProofStatus.PASSED
            run.result_json = {"metrics": metrics.metrics, "raw": metrics.raw}
            run.last_error = None
            run.completed_at = utcnow()
            self.store.append_event(
                session,
                run.id,
                "METRICS_CAPTURED",
                {"metrics": metrics.metrics, "raw": metrics.raw},
            )
            session.commit()
            session.refresh(run)
            session.expunge(run)
            return run

    def get_run(self, run_id: UUID) -> PlatformProofRun:
        try:
            return self.store.get_run(run_id)
        except RuntimeError as exc:
            raise ProofError(str(exc)) from exc

    def _persist_publish_receipt(self, run_id: UUID, receipt) -> PlatformProofRun:
        with self.session_factory() as session:
            run = session.get(PlatformProofRun, run_id)
            if run is None:
                raise ProofError("proof run disappeared")
            if run.status != PlatformProofStatus.PUBLISHING:
                raise ProofStateError("receipt arrived for a proof run outside PUBLISHING")
            run.platform_post_id = receipt.platform_post_id
            run.remote_context = {
                **(run.remote_context or {}),
                "media_id": receipt.platform_post_id,
                "stage": "RECEIPT_PERSISTED",
            }
            run.canonical_url = receipt.canonical_url
            run.published_at = receipt.published_at or utcnow()
            run.status = (
                PlatformProofStatus.PUBLISHED
                if receipt.status == PublicationStatus.PUBLISHED
                else PlatformProofStatus.RECOVERY_REQUIRED
            )
            self.store.append_event(
                session,
                run.id,
                "REMOTE_PUBLISH_RECEIPT",
                {
                    "platform_post_id": receipt.platform_post_id,
                    "status": receipt.status.value,
                    "raw": receipt.raw,
                },
            )
            session.commit()
            session.refresh(run)
            session.expunge(run)
            return run

    def _merge_remote_context(self, run_id: UUID, remote_context: dict[str, object]) -> None:
        ensure_safe_evidence(remote_context)
        with self.session_factory() as session:
            run = session.get(PlatformProofRun, run_id)
            if run is None:
                return
            run.remote_context = {**(run.remote_context or {}), **remote_context}
            self.store.append_event(
                session, run.id, "REMOTE_CONTEXT_RECOVERED", {"context": remote_context}
            )
            session.commit()

    def _mark_failed(self, run_id: UUID, error: str) -> None:
        with self.session_factory() as session:
            run = session.get(PlatformProofRun, run_id)
            if run is None:
                return
            run.status = PlatformProofStatus.FAILED
            run.last_error = error
            self.store.append_event(session, run.id, "PROOF_FAILED", {"error": error})
            session.commit()

    def _mark_recovery_required(self, run_id: UUID, error: str) -> None:
        with self.session_factory() as session:
            run = session.get(PlatformProofRun, run_id)
            if run is None:
                return
            run.status = PlatformProofStatus.RECOVERY_REQUIRED
            run.last_error = error
            self.store.append_event(session, run.id, "RECOVERY_REQUIRED", {"error": error})
            session.commit()

    @staticmethod
    def _verify_adapter(account, adapter: PlatformProofAdapter) -> None:
        if adapter.platform != account.platform:
            raise ValueError("adapter platform does not match platform account")
        if adapter.api_family != account.api_family:
            raise ValueError("adapter api_family does not match platform account")


__all__ = [
    "PlatformProofHarness",
    "ProofError",
    "ProofRecoveryRequired",
    "ProofStateError",
    "UnsafeEvidenceError",
    "ensure_safe_evidence",
]
