"""add durable background jobs

Revision ID: d4e2c1a9087f
Revises: c3a7f4b8d921
Create Date: 2026-09-06 13:12:00
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "d4e2c1a9087f"
down_revision: Union[str, None] = "c3a7f4b8d921"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "background_jobs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("job_type", sa.String(length=80), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("payload_hash", sa.String(length=64), nullable=False),
        sa.Column("result_json", sa.JSON(), nullable=True),
        sa.Column(
            "status",
            sa.Enum(
                "PENDING",
                "RUNNING",
                "RETRYABLE",
                "SUCCEEDED",
                "FAILED",
                "QUARANTINED",
                name="jobstatus",
                native_enum=False,
            ),
            nullable=False,
        ),
        sa.Column("attempt_count", sa.Integer(), nullable=False),
        sa.Column("max_attempts", sa.Integer(), nullable=False),
        sa.Column("next_attempt_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("leased_by", sa.String(length=160), nullable=True),
        sa.Column("lease_token", sa.String(length=64), nullable=True),
        sa.Column("idempotency_key", sa.String(length=160), nullable=False),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "job_type", "idempotency_key", name="uq_background_job_idempotency"
        ),
    )
    op.create_index(
        "ix_background_jobs_claim",
        "background_jobs",
        ["status", "next_attempt_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_background_jobs_claim", table_name="background_jobs")
    op.drop_table("background_jobs")
