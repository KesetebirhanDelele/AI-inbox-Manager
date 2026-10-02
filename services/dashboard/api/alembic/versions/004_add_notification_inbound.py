"""Add notification_inbound (messages read from the student's GHL Conversations)

Revision ID: 004_notification_inbound
Revises: 003_notification_escalation
Create Date: 2026-10-02

New table only (production relies on create_all, which cannot add columns to existing tables).
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = "004_notification_inbound"
down_revision: Union[str, None] = "003_notification_escalation"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "notification_inbound",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("sequence_id", sa.Integer(), sa.ForeignKey("notification_sequences.id"), nullable=False),
        sa.Column("ghl_message_id", sa.String(100), nullable=False, unique=True),
        sa.Column("channel", sa.String(10), nullable=False),
        sa.Column("direction", sa.String(10)),
        sa.Column("text", sa.Text()),
        sa.Column("received_at", sa.DateTime()),
        sa.Column("handled_as", sa.String(30), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP")),
    )
    op.create_index("ix_notification_inbound_sequence_id", "notification_inbound", ["sequence_id"])


def downgrade() -> None:
    op.drop_table("notification_inbound")
