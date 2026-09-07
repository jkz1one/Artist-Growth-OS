from __future__ import annotations

import argparse
import json
import sys
from uuid import UUID

from app.domain.enums import PlatformProofStatus
from app.services.proof_inspector import ProofInspector


def _parse_platform(value: str) -> str:
    normalized = value.strip().upper()
    if not normalized:
        raise argparse.ArgumentTypeError("platform must not be empty")
    return normalized


def _parse_status(value: str) -> PlatformProofStatus:
    normalized = value.strip().upper()
    try:
        return PlatformProofStatus(normalized)
    except ValueError as exc:
        choices = ", ".join(status.value for status in PlatformProofStatus)
        raise argparse.ArgumentTypeError(
            f"unknown proof status {value!r}; expected one of: {choices}"
        ) from exc


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="artist-growth-proof-inspect",
        description=(
            "Read-only platform-proof inspector. This command never loads social credentials "
            "or performs platform actions."
        ),
    )
    sub = parser.add_subparsers(dest="command", required=True)

    list_runs = sub.add_parser("list", help="list durable proof runs; database reads only")
    list_runs.add_argument("--platform", type=_parse_platform)
    list_runs.add_argument("--status", type=_parse_status)
    list_runs.add_argument("--limit", type=int, default=50)

    show = sub.add_parser("show", help="show one durable proof run and event timeline")
    show.add_argument("--run-id", required=True, type=UUID)
    return parser


def _build_inspector() -> ProofInspector:
    from app.db.session import SessionLocal

    return ProofInspector(SessionLocal)


def run_cli(
    argv: list[str] | None = None,
    *,
    inspector: ProofInspector | None = None,
) -> int:
    args = build_parser().parse_args(argv)
    active_inspector = inspector if inspector is not None else _build_inspector()

    if args.command == "list":
        result = {
            "action": "LIST",
            "runs": active_inspector.list_runs(
                platform=args.platform,
                status=args.status,
                limit=args.limit,
            ),
        }
    else:
        result = {
            "action": "SHOW",
            "run": active_inspector.inspect_run(args.run_id),
        }

    print(json.dumps(result, indent=2, sort_keys=True, default=str))
    return 0


def main() -> None:
    try:
        raise SystemExit(run_cli())
    except (ValueError, RuntimeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        raise SystemExit(2) from exc


if __name__ == "__main__":
    main()
