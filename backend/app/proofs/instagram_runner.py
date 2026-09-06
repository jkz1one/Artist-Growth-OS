from __future__ import annotations

import argparse
import json
import os
import sys
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlsplit
from uuid import UUID

from app.domain.enums import PlatformProofStatus
from app.platforms.proof.instagram import InstagramProofAdapter, InstagramProofConfig
from app.services.platform_proof import PlatformProofHarness
from app.services.proof_security import ensure_safe_evidence

LIVE_PUBLISH_CONFIRMATION = "I_UNDERSTAND_THIS_WILL_POST_PUBLICLY"


class OperatorConfigError(RuntimeError):
    pass


@dataclass(frozen=True)
class InstagramOperatorConfig:
    api_version: str
    access_token: str = field(repr=False)
    allowed_media_hosts: tuple[str, ...]

    @classmethod
    def from_env(cls, environ: Mapping[str, str]) -> InstagramOperatorConfig:
        api_version = environ.get("INSTAGRAM_PROOF_API_VERSION", "").strip()
        access_token = environ.get("INSTAGRAM_PROOF_ACCESS_TOKEN", "").strip()
        raw_hosts = environ.get("INSTAGRAM_PROOF_MEDIA_HOSTS", "")
        hosts = tuple(
            dict.fromkeys(
                value.strip().lower()
                for value in raw_hosts.split(",")
                if value.strip()
            )
        )
        missing = []
        if not api_version:
            missing.append("INSTAGRAM_PROOF_API_VERSION")
        if not access_token:
            missing.append("INSTAGRAM_PROOF_ACCESS_TOKEN")
        if not hosts:
            missing.append("INSTAGRAM_PROOF_MEDIA_HOSTS")
        if missing:
            raise OperatorConfigError(
                "missing Instagram proof runtime configuration: " + ", ".join(missing)
            )
        return cls(
            api_version=api_version,
            access_token=access_token,
            allowed_media_hosts=hosts,
        )

    def build_adapter(self) -> InstagramProofAdapter:
        return InstagramProofAdapter(
            InstagramProofConfig(
                api_version=self.api_version,
                access_token=self.access_token,
                allowed_media_hosts=self.allowed_media_hosts,
            )
        )


class InstagramProofOperator:
    def __init__(self, harness: PlatformProofHarness, adapter: InstagramProofAdapter | None) -> None:
        self.harness = harness
        self.adapter = adapter

    def start(
        self,
        *,
        external_account_id: str,
        proof_key: str,
        media_url: str,
        caption: str = "",
        display_name: str | None = None,
        account_type: str | None = None,
    ) -> dict[str, Any]:
        adapter = self._require_adapter()
        ensure_safe_evidence(
            {"proof_key": proof_key, "media_url": media_url, "caption": caption},
            path="operator_input",
        )
        parsed_media_url = urlsplit(media_url)
        if parsed_media_url.query or parsed_media_url.fragment:
            raise ValueError(
                "proof media URL must be a stable public URL without query string or fragment"
            )
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
            media_uri=media_url,
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

    def _require_adapter(self) -> InstagramProofAdapter:
        if self.adapter is None:
            raise OperatorConfigError("this command requires Instagram proof runtime credentials")
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


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="artist-growth-instagram-proof",
        description="Operator-only Instagram proof runner. No command publishes implicitly.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    start = sub.add_parser("start", help="create a proof run and capture capabilities; never publishes")
    start.add_argument("--external-account-id", required=True)
    start.add_argument("--proof-key", required=True)
    start.add_argument("--media-url", required=True)
    start.add_argument("--caption", default="")
    start.add_argument("--display-name")
    start.add_argument("--account-type")

    publish = sub.add_parser("publish", help="perform the one controlled public Reel publish")
    publish.add_argument("--run-id", required=True, type=UUID)
    publish.add_argument(
        "--confirm-live-publish",
        required=True,
        metavar="PHRASE",
        help=f"must equal: {LIVE_PUBLISH_CONFIRMATION}",
    )

    reconcile = sub.add_parser("reconcile", help="reconcile a durable proof run without republishing")
    reconcile.add_argument("--run-id", required=True, type=UUID)

    metrics = sub.add_parser("metrics", help="collect media insights without publishing")
    metrics.add_argument("--run-id", required=True, type=UUID)

    show = sub.add_parser("show", help="show durable proof state; no Instagram credentials required")
    show.add_argument("--run-id", required=True, type=UUID)
    return parser


def _build_harness() -> PlatformProofHarness:
    from app.db.session import SessionLocal

    return PlatformProofHarness(SessionLocal)


def _build_adapter(environ: Mapping[str, str]) -> InstagramProofAdapter:
    return InstagramOperatorConfig.from_env(environ).build_adapter()


def run_cli(argv: list[str] | None = None, *, environ: Mapping[str, str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    env = os.environ if environ is None else environ
    harness = _build_harness()
    adapter = None if args.command == "show" else _build_adapter(env)
    operator = InstagramProofOperator(harness, adapter)

    if args.command == "start":
        result = operator.start(
            external_account_id=args.external_account_id,
            proof_key=args.proof_key,
            media_url=args.media_url,
            caption=args.caption,
            display_name=args.display_name,
            account_type=args.account_type,
        )
    elif args.command == "publish":
        result = operator.publish(
            run_id=args.run_id,
            confirmation=args.confirm_live_publish,
        )
    elif args.command == "reconcile":
        result = operator.reconcile(run_id=args.run_id)
    elif args.command == "metrics":
        result = operator.metrics(run_id=args.run_id)
    else:
        result = operator.show(run_id=args.run_id)

    print(json.dumps(result, indent=2, sort_keys=True, default=str))
    return 0


def main() -> None:
    try:
        raise SystemExit(run_cli())
    except (OperatorConfigError, PermissionError, ValueError, RuntimeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        raise SystemExit(2) from exc


if __name__ == "__main__":
    main()
