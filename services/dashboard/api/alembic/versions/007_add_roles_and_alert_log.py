"""Add role_assignments and alert_log (roles instead of people; send-once alerts)

Revision ID: 007_roles_alert_log
Revises: 006_student_verifications
Create Date: 2026-10-03

New tables only (production relies on create_all, which cannot add columns to existing tables).
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = "007_roles_alert_log"
down_revision: Union[str, None] = "006_student_verifications"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "role_assignments",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("role", sa.String(40), nullable=False),
        sa.Column("email", sa.String(255)),
        sa.Column("display_name", sa.String(255)),
        sa.Column("scope", sa.String(100)),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("updated_by", sa.String(100)),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP")),
    )
    op.create_index("ix_role_assignments_role", "role_assignments", ["role"])
    op.create_table(
        "alert_log",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("kind", sa.String(40), nullable=False),
        sa.Column("key", sa.String(100), nullable=False),
        sa.Column("sent_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("detail", sa.Text()),
    )
    op.create_index("ix_alert_log_kind", "alert_log", ["kind"])
    op.create_index("uq_alert_kind_key", "alert_log", ["kind", "key"], unique=True)


def downgrade() -> None:
    op.drop_table("alert_log")
    op.drop_table("role_assignments")
