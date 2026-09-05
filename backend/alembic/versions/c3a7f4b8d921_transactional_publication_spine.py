"""transactional publication spine

Revision ID: c3a7f4b8d921
Revises: ba7301546eb8
Create Date: 2026-09-05 20:06:00
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "c3a7f4b8d921"
down_revision: Union[str, None] = "ba7301546eb8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("candidates") as batch_op:
        batch_op.alter_column("render_id", existing_type=sa.Uuid(), nullable=True)

    with op.batch_alter_table("renders") as batch_op:
        batch_op.create_unique_constraint("uq_render_plan_artifact", ["render_plan_id", "sha256"])

    with op.batch_alter_table("rights_decisions") as batch_op:
        batch_op.create_unique_constraint("uq_rights_decision_rule", ["candidate_id", "rule_version"])

    with op.batch_alter_table("policy_decisions") as batch_op:
        batch_op.create_unique_constraint("uq_policy_decision_rule", ["candidate_id", "rule_version"])

    op.add_column(
        "distinctness_decisions",
        sa.Column(
            "rule_version",
            sa.String(length=80),
            nullable=False,
            server_default="foundation-distinctness-v1",
        ),
    )
    with op.batch_alter_table("distinctness_decisions") as batch_op:
        batch_op.create_unique_constraint(
            "uq_distinctness_decision_rule", ["candidate_id", "rule_version"]
        )

    with op.batch_alter_table("publications") as batch_op:
        batch_op.create_unique_constraint(
            "uq_candidate_platform_publication", ["candidate_id", "platform"]
        )


def downgrade() -> None:
    with op.batch_alter_table("publications") as batch_op:
        batch_op.drop_constraint("uq_candidate_platform_publication", type_="unique")

    with op.batch_alter_table("distinctness_decisions") as batch_op:
        batch_op.drop_constraint("uq_distinctness_decision_rule", type_="unique")
    op.drop_column("distinctness_decisions", "rule_version")

    with op.batch_alter_table("policy_decisions") as batch_op:
        batch_op.drop_constraint("uq_policy_decision_rule", type_="unique")

    with op.batch_alter_table("rights_decisions") as batch_op:
        batch_op.drop_constraint("uq_rights_decision_rule", type_="unique")

    with op.batch_alter_table("renders") as batch_op:
        batch_op.drop_constraint("uq_render_plan_artifact", type_="unique")

    with op.batch_alter_table("candidates") as batch_op:
        batch_op.alter_column("render_id", existing_type=sa.Uuid(), nullable=False)
