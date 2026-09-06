"""add proof remote context

Revision ID: f6a1d9e240bc
Revises: e5b7c2d3410a
Create Date: 2026-09-06 14:22:00
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "f6a1d9e240bc"
down_revision: Union[str, None] = "e5b7c2d3410a"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "platform_proof_runs",
        sa.Column(
            "remote_context",
            sa.JSON(),
            nullable=False,
            server_default=sa.text("'{}'"),
        ),
    )


def downgrade() -> None:
    op.drop_column("platform_proof_runs", "remote_context")
