"""Add student_verifications (Rob confirms students the pipeline had to guess)

Revision ID: 006_student_verifications
Revises: 005_notification_opt_outs
Create Date: 2026-10-03

New table only (production relies on create_all, which cannot add columns to existing tables).
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = "006_student_verifications"
down_revision: Union[str, None] = "005_notification_opt_outs"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "student_verifications",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("student_id", sa.Integer(), sa.ForeignKey("students.id"), nullable=False, unique=True),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("basis", sa.String(30), nullable=False),
        sa.Column("guessed_name", sa.String(255)),
        sa.Column("evidence", sa.Text()),
        sa.Column("verified_by", sa.String(100)),
        sa.Column("verified_at", sa.DateTime()),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP")),
    )
    op.create_index("ix_student_verifications_student_id", "student_verifications", ["student_id"])


def downgrade() -> None:
    op.drop_table("student_verifications")
