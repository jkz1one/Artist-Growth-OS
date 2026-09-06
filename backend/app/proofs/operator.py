from __future__ import annotations

from collections.abc import Callable
from typing import Any
from uuid import UUID

from app.domain.enums import PlatformProofStatus
from app.platforms.proof.base import PlatformProofAdapter
from app.services.platform_proof import PlatformProofHarness
from app.services.proof_security import ensure_safe_evidence

LIVE_PUBLISH_CONFIRMATION = "I_UNDERSTAND_THIS_WILL_POST_PUBLICLY"

MediaValidator = Callable[[str], None]


class OperatorConfigError(RuntimeError):
    pass


class PlatformProofOperator:
    """Shared operator safety layer for controlled platform proof runs.

    Live publication is disabled by default. A platform-specific runner must
    explicitly opt in and the caller must still supply the exact confirmation
    phrase before the harness can cross the remote publication boundary.
    """

    def __init__(
        self,
        harness: PlatformProofHarness,
        adapter: PlatformProofAdapter | None,
        *,
        platform_label: str,
        live_publish_enabled: bool = False,
        media_validator: MediaValidator | None = None,
    ) -> None:
        self.harness = harness
        self.adapter = adapter
        self.platform_label = platform_label
        self.live_publish_enabled = live_publish_enabled
        self.media_validator = media_validator

    def start(
        self,
        *,
        external_account_id: str,
        proof_key: str,
        media_uri: str,
        caption: str = "",
        display_name: str | None = None,
        account_type: str | None = None,
    ) -> dict[str, Any]:
        adapter = self._require_adapter()
        ensure_safe_evidence(
            {"proof_key": proof_key, "media_uri": media_uri, "caption": caption},
            path="operator_input",
        )
        if self.media_validator is not None:
            self.media_validator(media_uri)

        account = self.harness.create_account(
            platform=adapter.platform,
            external_account_id=external_account_id,
            api_family=adapter.api_family,
            display_name=display_name,
            account_type=account_type,
        )
        run = self.harness.start_run(
            platform_account_id=account.id,
            proof_key=proof_key,
            media_uri=media_uri,
            caption=caption,
        )
        snapshot = self.harness.capture_capabilities(run.id, adapter)
        refreshed = self.harness.get_run(run.id)
        return {
            "action": "STARTED_NO_PUBLISH",
            "run": self._run_summary(refreshed),
            "capability_snapshot_id": str(snapshot.id),
            "capabilities": dict(snapshot.capabilities),
        }

    def publish(self, *, run_id: UUID, confirmation: str) -> dict[str, Any]:
        if not self.live_publish_enabled:
            raise PermissionError(
                f"live publish disabled for {self.platform_label} proof operator"
            )
        if confirmation != LIVE_PUBLISH_CONFIRMATION:
            raise PermissionError(
                "live publish blocked: pass the exact confirmation phrase "
                f"{LIVE_PUBLISH_CONFIRMATION!r}"
            )
        adapter = self._require_adapter()
        run = self.harness.publish_once(run_id, adapter)
        return {"action": "LIVE_PUBLISH_REQUESTED", "run": self._run_summary(run)}

    def reconcile(self, *, run_id: UUID) -> dict[str, Any]:
        adapter = self._require_adapter()
        run = self.harness.reconcile(run_id, adapter)
        return {"action": "RECONCILED", "run": self._run_summary(run)}

    def metrics(self, *, run_id: UUID) -> dict[str, Any]:
        adapter = self._require_adapter()
        run = self.harness.collect_metrics(run_id, adapter)
        return {"action": "METRICS_CAPTURED", "run": self._run_summary(run)}

    def show(self, *, run_id: UUID) -> dict[str, Any]:
        run = self.harness.get_run(run_id)
        return {"action": "SHOW", "run": self._run_summary(run)}

    def _require_adapter(self) -> PlatformProofAdapter:
        if self.adapter is None:
            raise OperatorConfigError(
                f"this command requires {self.platform_label} proof runtime credentials"
            )
        return self.adapter

    @staticmethod
    def _run_summary(run) -> dict[str, Any]:
        status = run.status.value if isinstance(run.status, PlatformProofStatus) else str(run.status)
        data = {
            "id": str(run.id),
            "platform_account_id": str(run.platform_account_id),
            "proof_key": run.proof_key,
            "status": status,
            "media_uri": run.media_uri,
            "platform_post_id": run.platform_post_id,
            "canonical_url": run.canonical_url,
            "last_error": run.last_error,
            "remote_context": dict(run.remote_context or {}),
            "result": run.result_json,
            "created_at": run.created_at.isoformat() if run.created_at else None,
            "published_at": run.published_at.isoformat() if run.published_at else None,
            "completed_at": run.completed_at.isoformat() if run.completed_at else None,
        }
        ensure_safe_evidence(data)
        return data
