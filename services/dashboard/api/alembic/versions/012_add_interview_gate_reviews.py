"""Add interview_gate_reviews (the third interview screen's verdict per email, and a person's judgement of it)

Revision ID: 012_interview_gate_reviews
Revises: 011_approval_codes
Create Date: 2026-10-26

New table only (production relies on create_all, which cannot add columns to existing tables).
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = "012_interview_gate_reviews"
down_revision: Union[str, None] = "011_approval_codes"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "interview_gate_reviews",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("email_id", sa.Integer(), sa.ForeignKey("emails.id"), nullable=False, unique=True),
        sa.Column("event_id", sa.Integer(), sa.ForeignKey("interview_events.id")),
        sa.Column("source", sa.String(10), nullable=False),
        sa.Column("mode", sa.String(10)),
        sa.Column("verdict", sa.String(20)),
        sa.Column("round", sa.String(10)),
        sa.Column("format", sa.String(15)),
        sa.Column("confidence", sa.Float()),
        sa.Column("reason", sa.String(300)),
        sa.Column("refers_to_event_id", sa.Integer()),
        sa.Column("would_hide", sa.Boolean()),
        sa.Column("error", sa.String(300)),
        sa.Column("new_text", sa.Text()),
        sa.Column("quoted_chars", sa.Integer()),
        sa.Column("history", sa.JSON()),
        sa.Column("cost_usd", sa.Float()),
        sa.Column("created_at", sa.DateTime()),
        sa.Column("human_decision", sa.String(10)),
        sa.Column("human_note", sa.String(300)),
        sa.Column("decided_by", sa.String(100)),
        sa.Column("decided_at", sa.DateTime()),
    )
    for col in ("email_id", "event_id", "verdict", "would_hide", "created_at", "human_decision"):
        op.create_index(f"ix_interview_gate_reviews_{col}", "interview_gate_reviews", [col])


def downgrade() -> None:
    op.drop_table("interview_gate_reviews")
