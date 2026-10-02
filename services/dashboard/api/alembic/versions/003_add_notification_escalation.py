"""Add notification escalation tables (sequences, attempts, reply analyses)

Revision ID: 003_notification_escalation
Revises: 002_checklist_completions
Create Date: 2026-10-02

New tables only: production relies on create_all(), which cannot add columns to
existing tables, so nothing existing is altered. See
directives/student-notification-escalation.md.
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = "003_notification_escalation"
down_revision: Union[str, None] = "002_checklist_completions"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "notification_sequences",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("draft_id", sa.Integer(), sa.ForeignKey("notification_drafts.id"), nullable=False, unique=True),
        sa.Column("student_id", sa.Integer(), sa.ForeignKey("students.id"), nullable=True),
        sa.Column("status", sa.String(30), nullable=False, server_default="active"),
        sa.Column("timezone", sa.String(64), nullable=False),
        sa.Column("timezone_source", sa.String(30)),
        sa.Column("started_at", sa.DateTime(), nullable=False),
        sa.Column("started_by", sa.String(100)),
        sa.Column("ack_token", sa.String(64), unique=True),
        sa.Column("ack_at", sa.DateTime()),
        sa.Column("ack_channel", sa.String(20)),
        sa.Column("ack_kind", sa.String(20)),
        sa.Column("closed_by", sa.String(100)),
        sa.Column("closed_at", sa.DateTime()),
        sa.Column("rob_day1_alert_at", sa.DateTime()),
        sa.Column("rob_ended_alert_at", sa.DateTime()),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP")),
    )
    op.create_index("ix_notification_sequences_status", "notification_sequences", ["status"])
    op.create_index("ix_notification_sequences_student_id", "notification_sequences", ["student_id"])

    op.create_table(
        "notification_attempts",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("sequence_id", sa.Integer(), sa.ForeignKey("notification_sequences.id"), nullable=False),
        sa.Column("channel", sa.String(10), nullable=False),
        sa.Column("step", sa.String(20), nullable=False),
        sa.Column("planned_for", sa.DateTime(), nullable=False),
        sa.Column("scheduled_for", sa.DateTime(), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="pending"),
        sa.Column("sent_at", sa.DateTime()),
        sa.Column("detail", sa.Text()),
        sa.Column("provider_id", sa.String(100)),
        sa.Column("segments", sa.Integer()),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP")),
    )
    op.create_index("ix_notification_attempts_sequence_id", "notification_attempts", ["sequence_id"])
    op.create_index("ix_notification_attempts_status", "notification_attempts", ["status"])
    op.create_index("ix_notification_attempts_scheduled_for", "notification_attempts", ["scheduled_for"])
    op.create_index("idx_attempt_sequence_step_channel", "notification_attempts",
                    ["sequence_id", "step", "channel"], unique=True)
    op.create_index("idx_attempt_due", "notification_attempts", ["status", "scheduled_for"])

    op.create_table(
        "reply_analyses",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("sequence_id", sa.Integer(), sa.ForeignKey("notification_sequences.id"), nullable=False),
        sa.Column("channel", sa.String(10), nullable=False),
        sa.Column("message_text", sa.Text(), nullable=False),
        sa.Column("outcome", sa.String(20), nullable=False),
        sa.Column("confidence", sa.Float()),
        sa.Column("reason", sa.Text()),
        sa.Column("shadow", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("acted", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("human_verdict", sa.String(20)),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP")),
    )
    op.create_index("ix_reply_analyses_sequence_id", "reply_analyses", ["sequence_id"])
    op.create_index("ix_reply_analyses_created_at", "reply_analyses", ["created_at"])


def downgrade() -> None:
    op.drop_table("reply_analyses")
    op.drop_table("notification_attempts")
    op.drop_table("notification_sequences")
