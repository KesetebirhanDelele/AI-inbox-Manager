"""Add interview_follow_ups (an email about an interview the student was already told about)

Revision ID: 009_interview_follow_ups
Revises: 008_callback_requests
Create Date: 2026-10-16

New table only (production relies on create_all, which cannot add columns to existing tables).
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = "009_interview_follow_ups"
down_revision: Union[str, None] = "008_callback_requests"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "interview_follow_ups",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("event_id", sa.Integer(), sa.ForeignKey("interview_events.id"), nullable=False, unique=True),
        sa.Column("original_event_id", sa.Integer(), sa.ForeignKey("interview_events.id"), nullable=False),
        sa.Column("reason", sa.String(200)),
        sa.Column("created_at", sa.DateTime()),
    )
    op.create_index("ix_interview_follow_ups_event_id", "interview_follow_ups", ["event_id"])
    op.create_index("ix_interview_follow_ups_original_event_id", "interview_follow_ups", ["original_event_id"])


def downgrade() -> None:
    op.drop_table("interview_follow_ups")
