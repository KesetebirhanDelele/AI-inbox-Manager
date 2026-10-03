"""Add notification_opt_outs (the app's own record of STOP requests)

Revision ID: 005_notification_opt_outs
Revises: 004_notification_inbound
Create Date: 2026-10-02

New table only (production relies on create_all, which cannot add columns to existing tables).
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = "005_notification_opt_outs"
down_revision: Union[str, None] = "004_notification_inbound"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "notification_opt_outs",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("phone_tail", sa.String(10), nullable=False),
        sa.Column("channel", sa.String(10), nullable=False),
        sa.Column("source", sa.String(30), nullable=False),
        sa.Column("sequence_id", sa.Integer()),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP")),
    )
    op.create_index("ix_notification_opt_outs_phone_tail", "notification_opt_outs", ["phone_tail"])


def downgrade() -> None:
    op.drop_table("notification_opt_outs")
