from __future__ import annotations

import argparse
from uuid import UUID, uuid4

import pytest

from app.domain.enums import PlatformProofStatus
from app.proofs import proof_inspector_cli
from app.services.proof_security import UnsafeEvidenceError


class RecordingInspector:
    def __init__(self):
        self.list_calls = []
        self.show_calls = []
        self.runs = [{"id": "run-1", "status": "READY"}]
        self.run = {"id": "run-1", "status": "READY", "events": []}

    def list_runs(self, *, platform=None, status=None, limit=50):
        self.list_calls.append(
            {
                "platform": platform,
                "status": status,
                "limit": limit,
            }
        )
        return self.runs

    def inspect_run(self, run_id: UUID):
        self.show_calls.append(run_id)
        return self.run


class UnsafeInspector(RecordingInspector):
    def inspect_run(self, run_id: UUID):
        raise UnsafeEvidenceError("credential-bearing evidence blocked")


def test_list_cli_is_read_only_and_uses_default_filters(capsys):
    inspector = RecordingInspector()

    code = proof_inspector_cli.run_cli(["list"], inspector=inspector)

    assert code == 0
    assert inspector.list_calls == [{"platform": None, "status": None, "limit": 50}]
    output = capsys.readouterr().out
    assert '"action": "LIST"' in output
    assert '"status": "READY"' in output


def test_list_cli_normalizes_platform_and_status_and_forwards_limit(capsys):
    inspector = RecordingInspector()

    code = proof_inspector_cli.run_cli(
        ["list", "--platform", "instagram", "--status", "ready", "--limit", "7"],
        inspector=inspector,
    )

    assert code == 0
    assert inspector.list_calls == [
        {
            "platform": "INSTAGRAM",
            "status": PlatformProofStatus.READY,
            "limit": 7,
        }
    ]
    assert '"action": "LIST"' in capsys.readouterr().out


def test_show_cli_parses_uuid_and_returns_inspection(capsys):
    inspector = RecordingInspector()
    run_id = uuid4()

    code = proof_inspector_cli.run_cli(
        ["show", "--run-id", str(run_id)],
        inspector=inspector,
    )

    assert code == 0
    assert inspector.show_calls == [run_id]
    output = capsys.readouterr().out
    assert '"action": "SHOW"' in output
    assert '"events": []' in output


def test_unknown_status_is_rejected_before_inspector_call(capsys):
    inspector = RecordingInspector()

    with pytest.raises(SystemExit) as exc_info:
        proof_inspector_cli.run_cli(
            ["list", "--status", "not-a-status"],
            inspector=inspector,
        )

    assert exc_info.value.code == 2
    assert inspector.list_calls == []
    assert "unknown proof status" in capsys.readouterr().err


def test_empty_platform_is_rejected_before_inspector_call(capsys):
    inspector = RecordingInspector()

    with pytest.raises(SystemExit) as exc_info:
        proof_inspector_cli.run_cli(
            ["list", "--platform", "   "],
            inspector=inspector,
        )

    assert exc_info.value.code == 2
    assert inspector.list_calls == []
    assert "platform must not be empty" in capsys.readouterr().err


def test_cli_exposes_only_list_and_show_commands():
    parser = proof_inspector_cli.build_parser()
    subparsers_action = next(
        action for action in parser._actions if isinstance(action, argparse._SubParsersAction)
    )

    assert set(subparsers_action.choices) == {"list", "show"}
    assert not hasattr(proof_inspector_cli, "_build_adapter")
    assert not hasattr(proof_inspector_cli, "LIVE_PUBLISH_CONFIRMATION")


def test_unsafe_inspection_evidence_is_not_swallowed():
    inspector = UnsafeInspector()

    with pytest.raises(UnsafeEvidenceError, match="credential-bearing evidence blocked"):
        proof_inspector_cli.run_cli(
            ["show", "--run-id", str(uuid4())],
            inspector=inspector,
        )


def test_build_inspector_uses_database_session_only(monkeypatch):
    import app.db.session as db_session

    sentinel = object()
    monkeypatch.setattr(db_session, "SessionLocal", sentinel)

    class CapturingInspector:
        def __init__(self, session_factory):
            self.session_factory = session_factory

    monkeypatch.setattr(proof_inspector_cli, "ProofInspector", CapturingInspector)
    inspector = proof_inspector_cli._build_inspector()

    assert inspector.session_factory is sentinel
