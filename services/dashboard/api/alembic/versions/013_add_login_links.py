"""Add allowed_users and login_links (sign in by an emailed one-time link)

Revision ID: 013_login_links
Revises: 012_interview_gate_reviews
Create Date: 2026-11-09

New tables only (production relies on create_all, which cannot add columns to existing tables).
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = "013_login_links"
down_revision: Union[str, None] = "012_interview_gate_reviews"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "allowed_users",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("email", sa.String(255), nullable=False, unique=True),
        sa.Column("name", sa.String(100)),
        sa.Column("role", sa.String(20), nullable=False, server_default="admin"),
        sa.Column("can_manage", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime()),
        sa.Column("added_by", sa.String(255)),
        sa.Column("last_login_at", sa.DateTime()),
    )
    op.create_index("ix_allowed_users_email", "allowed_users", ["email"])
    op.create_table(
        "login_links",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("token_hash", sa.String(64), nullable=False, unique=True),
        sa.Column("email", sa.String(255), nullable=False),
        sa.Column("created_at", sa.DateTime()),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.Column("used_at", sa.DateTime()),
    )
    op.create_index("ix_login_links_token_hash", "login_links", ["token_hash"])
    op.create_index("ix_login_links_email", "login_links", ["email"])


def downgrade() -> None:
    op.drop_table("login_links")
    op.drop_table("allowed_users")
