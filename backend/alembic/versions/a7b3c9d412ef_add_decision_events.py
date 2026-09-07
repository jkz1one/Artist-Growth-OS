"""add decision events

Revision ID: a7b3c9d412ef
Revises: f6a1d9e240bc
Create Date: 2026-09-07 09:40:00
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "a7b3c9d412ef"
down_revision: Union[str, None] = "f6a1d9e240bc"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "decision_events",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("candidate_id", sa.Uuid(), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("event_key", sa.String(length=200), nullable=False),
        sa.Column("event_type", sa.String(length=100), nullable=False),
        sa.Column("status", sa.String(length=40), nullable=True),
        sa.Column("rule_version", sa.String(length=80), nullable=True),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["candidate_id"], ["candidates.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("candidate_id", "event_key", name="uq_decision_event_key"),
        sa.UniqueConstraint("candidate_id", "sequence", name="uq_decision_event_sequence"),
    )
    op.create_index(
        op.f("ix_decision_events_candidate_id"),
        "decision_events",
        ["candidate_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_decision_events_candidate_id"), table_name="decision_events")
    op.drop_table("decision_events")
