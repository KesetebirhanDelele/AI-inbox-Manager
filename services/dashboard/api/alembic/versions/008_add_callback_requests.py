"""Add callback_requests (students who call back about an interview)

Revision ID: 008_callback_requests
Revises: 007_roles_alert_log
Create Date: 2026-10-04

New table only (production relies on create_all, which cannot add columns to existing tables).
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = "008_callback_requests"
down_revision: Union[str, None] = "007_roles_alert_log"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "callback_requests",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("ghl_call_id", sa.String(100), nullable=False, unique=True),
        sa.Column("contact_id", sa.String(100)),
        sa.Column("student_id", sa.Integer(), sa.ForeignKey("students.id")),
        sa.Column("caller_number", sa.String(40)),
        sa.Column("received_at", sa.DateTime(), nullable=False),
        sa.Column("duration_seconds", sa.Integer()),
        sa.Column("said", sa.Text()),
        sa.Column("status", sa.String(10), nullable=False, server_default="open"),
        sa.Column("done_by", sa.String(100)),
        sa.Column("done_at", sa.DateTime()),
        sa.Column("alerted_at", sa.DateTime()),
        sa.Column("sla_alerted_at", sa.DateTime()),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP")),
    )
    op.create_index("ix_callback_requests_student_id", "callback_requests", ["student_id"])
    op.create_index("ix_callback_requests_received_at", "callback_requests", ["received_at"])
    op.create_index("ix_callback_requests_status", "callback_requests", ["status"])


def downgrade() -> None:
    op.drop_table("callback_requests")
