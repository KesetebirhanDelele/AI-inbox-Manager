"""Add approval_codes (one-time email codes that unlock an approval link)

Revision ID: 011_approval_codes
Revises: 010_approval_links
Create Date: 2026-10-20

New table only (production relies on create_all, which cannot add columns to existing tables).
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = "011_approval_codes"
down_revision: Union[str, None] = "010_approval_links"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "approval_codes",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("link_id", sa.Integer(), sa.ForeignKey("approval_links.id"), nullable=False),
        sa.Column("salt", sa.String(32), nullable=False),
        sa.Column("code_hash", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime()),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("consumed_at", sa.DateTime()),
    )
    op.create_index("ix_approval_codes_link_id", "approval_codes", ["link_id"])


def downgrade() -> None:
    op.drop_table("approval_codes")
