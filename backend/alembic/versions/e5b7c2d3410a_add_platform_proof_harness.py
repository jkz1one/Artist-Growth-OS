"""add platform proof harness

Revision ID: e5b7c2d3410a
Revises: d4e2c1a9087f
Create Date: 2026-09-06 14:05:00
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "e5b7c2d3410a"
down_revision: Union[str, None] = "d4e2c1a9087f"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "platform_accounts",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("platform", sa.String(length=40), nullable=False),
        sa.Column("external_account_id", sa.String(length=240), nullable=False),
        sa.Column("display_name", sa.String(length=240), nullable=True),
        sa.Column("account_type", sa.String(length=80), nullable=True),
        sa.Column("api_family", sa.String(length=120), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False),
        sa.Column("metadata_json", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("platform", "external_account_id", name="uq_platform_external_account"),
    )
    op.create_index("ix_platform_accounts_platform", "platform_accounts", ["platform"], unique=False)
    op.create_table(
        "platform_capability_snapshots",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("platform_account_id", sa.Uuid(), nullable=False),
        sa.Column("api_family", sa.String(length=120), nullable=False),
        sa.Column("api_version", sa.String(length=80), nullable=True),
        sa.Column("capabilities", sa.JSON(), nullable=False),
        sa.Column("evidence", sa.JSON(), nullable=False),
        sa.Column("captured_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["platform_account_id"], ["platform_accounts.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_platform_capability_snapshots_platform_account_id", "platform_capability_snapshots", ["platform_account_id"], unique=False)
    op.create_table(
        "platform_proof_runs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("platform_account_id", sa.Uuid(), nullable=False),
        sa.Column("capability_snapshot_id", sa.Uuid(), nullable=True),
        sa.Column("proof_key", sa.String(length=160), nullable=False),
        sa.Column("status", sa.Enum("CREATED", "READY", "PUBLISHING", "PUBLISHED", "MEASURING", "PASSED", "FAILED", "RECOVERY_REQUIRED", name="platformproofstatus", native_enum=False), nullable=False),
        sa.Column("media_uri", sa.Text(), nullable=False),
        sa.Column("caption", sa.Text(), nullable=False),
        sa.Column("idempotency_key", sa.String(length=160), nullable=False),
        sa.Column("platform_post_id", sa.String(length=240), nullable=True),
        sa.Column("canonical_url", sa.Text(), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("result_json", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["capability_snapshot_id"], ["platform_capability_snapshots.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["platform_account_id"], ["platform_accounts.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("platform_account_id", "proof_key", name="uq_platform_proof_run_key"),
    )
    op.create_index("ix_platform_proof_runs_platform_account_id", "platform_proof_runs", ["platform_account_id"], unique=False)
    op.create_table(
        "platform_proof_events",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("proof_run_id", sa.Uuid(), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("event_type", sa.String(length=100), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["proof_run_id"], ["platform_proof_runs.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("proof_run_id", "sequence", name="uq_platform_proof_event_sequence"),
    )
    op.create_index("ix_platform_proof_events_proof_run_id", "platform_proof_events", ["proof_run_id"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_platform_proof_events_proof_run_id", table_name="platform_proof_events")
    op.drop_table("platform_proof_events")
    op.drop_index("ix_platform_proof_runs_platform_account_id", table_name="platform_proof_runs")
    op.drop_table("platform_proof_runs")
    op.drop_index("ix_platform_capability_snapshots_platform_account_id", table_name="platform_capability_snapshots")
    op.drop_table("platform_capability_snapshots")
    op.drop_index("ix_platform_accounts_platform", table_name="platform_accounts")
    op.drop_table("platform_accounts")
