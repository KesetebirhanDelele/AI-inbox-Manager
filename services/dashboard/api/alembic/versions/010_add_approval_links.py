"""Add approval_links (secure review-and-approve links in alert emails)

Revision ID: 010_approval_links
Revises: 009_interview_follow_ups
Create Date: 2026-10-20

New table only (production relies on create_all, which cannot add columns to existing tables).
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = "010_approval_links"
down_revision: Union[str, None] = "009_interview_follow_ups"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "approval_links",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("token_hash", sa.String(64), nullable=False, unique=True),
        sa.Column("draft_id", sa.Integer(), sa.ForeignKey("notification_drafts.id"), nullable=False),
        sa.Column("role", sa.String(30), nullable=False),
        sa.Column("recipient_email", sa.String(255), nullable=False),
        sa.Column("created_at", sa.DateTime()),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.Column("used_at", sa.DateTime()),
        sa.Column("used_action", sa.String(20)),
    )
    op.create_index("ix_approval_links_token_hash", "approval_links", ["token_hash"], unique=True)
    op.create_index("ix_approval_links_draft_id", "approval_links", ["draft_id"])


def downgrade() -> None:
    op.drop_table("approval_links")
