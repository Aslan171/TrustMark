from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "20260510_0001"
down_revision = None
branch_labels = None
depends_on = None


status_type = postgresql.ENUM(
    "guarantor",
    "trusted_user",
    "unknown",
    "suspicious",
    "scammer",
    name="status_type",
)
report_status = postgresql.ENUM(
    "new",
    "insufficient",
    "reviewing",
    "approved",
    "rejected",
    name="report_status",
)
compensation_status = postgresql.ENUM(
    "pending",
    "paid",
    "rejected",
    name="compensation_status",
)


def upgrade() -> None:
    status_type.create(op.get_bind(), checkfirst=True)
    report_status.create(op.get_bind(), checkfirst=True)
    compensation_status.create(op.get_bind(), checkfirst=True)

    op.create_table(
        "users",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("telegram_user_id", sa.BigInteger(), nullable=True),
        sa.Column("username", sa.String(length=32), nullable=True),
        sa.Column("first_name", sa.String(length=255), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index(op.f("ix_users_telegram_user_id"), "users", ["telegram_user_id"], unique=True)
    op.create_index(op.f("ix_users_username"), "users", ["username"], unique=False)

    op.create_table(
        "username_history",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("old_username", sa.String(length=32), nullable=True),
        sa.Column("new_username", sa.String(length=32), nullable=True),
        sa.Column("changed_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index(op.f("ix_username_history_user_id"), "username_history", ["user_id"])

    op.create_table(
        "statuses",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("status_type", status_type, nullable=False),
        sa.Column("risk_percent", sa.Integer(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("issued_by_admin_id", sa.BigInteger(), nullable=True),
        sa.Column("issued_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("coverage_limit_amount", sa.Numeric(18, 8), nullable=True),
        sa.Column("coverage_currency", sa.String(length=32), nullable=True),
    )
    op.create_index(op.f("ix_statuses_user_id"), "statuses", ["user_id"])
    op.create_index("ix_statuses_user_active", "statuses", ["user_id", "is_active"])
    op.create_index("ix_statuses_type_active", "statuses", ["status_type", "is_active"])
    op.create_index(op.f("ix_statuses_issued_by_admin_id"), "statuses", ["issued_by_admin_id"])

    op.create_table(
        "scam_reports",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("reporter_user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("accused_user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("accused_raw", sa.String(length=255), nullable=True),
        sa.Column("amount", sa.Numeric(18, 8), nullable=True),
        sa.Column("currency", sa.String(length=32), nullable=True),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("status", report_status, nullable=False, server_default="new"),
        sa.Column("admin_comment", sa.Text(), nullable=True),
        sa.Column("assigned_admin_id", sa.BigInteger(), nullable=True),
        sa.Column("admin_chat_message_id", sa.BigInteger(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index(op.f("ix_scam_reports_reporter_user_id"), "scam_reports", ["reporter_user_id"])
    op.create_index(op.f("ix_scam_reports_accused_user_id"), "scam_reports", ["accused_user_id"])

    op.create_table(
        "evidence",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("related_user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=True),
        sa.Column("related_status_id", sa.Integer(), sa.ForeignKey("statuses.id", ondelete="CASCADE"), nullable=True),
        sa.Column("related_report_id", sa.Integer(), sa.ForeignKey("scam_reports.id", ondelete="CASCADE"), nullable=True),
        sa.Column("uploaded_by_admin_id", sa.BigInteger(), nullable=True),
        sa.Column("telegram_file_id", sa.String(length=512), nullable=True),
        sa.Column("file_type", sa.String(length=32), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=True),
        sa.Column("text_content", sa.Text(), nullable=True),
        sa.Column("external_url", sa.String(length=2048), nullable=True),
        sa.Column("evidence_channel_id", sa.BigInteger(), nullable=True),
        sa.Column("evidence_message_id", sa.BigInteger(), nullable=True),
        sa.Column("evidence_message_url", sa.String(length=2048), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_evidence_related_user", "evidence", ["related_user_id"])
    op.create_index("ix_evidence_related_status", "evidence", ["related_status_id"])
    op.create_index("ix_evidence_related_report", "evidence", ["related_report_id"])
    op.create_index(op.f("ix_evidence_uploaded_by_admin_id"), "evidence", ["uploaded_by_admin_id"])

    op.create_table(
        "guarantors",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False, unique=True),
        sa.Column("issued_status_id", sa.Integer(), sa.ForeignKey("statuses.id", ondelete="SET NULL"), nullable=True),
        sa.Column("entry_fee_amount", sa.Numeric(18, 8), nullable=False),
        sa.Column("entry_fee_currency", sa.String(length=16), nullable=False, server_default="USD"),
        sa.Column("reviews_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("nft_usernames_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("nft_gifts_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("verified_by_admin_id", sa.BigInteger(), nullable=True),
        sa.Column("admin_comment", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )

    op.create_table(
        "trusted_users",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False, unique=True),
        sa.Column("issued_status_id", sa.Integer(), sa.ForeignKey("statuses.id", ondelete="SET NULL"), nullable=True),
        sa.Column("payment_amount", sa.Numeric(18, 8), nullable=False),
        sa.Column("payment_currency", sa.String(length=32), nullable=False, server_default="USD"),
        sa.Column("coverage_percent", sa.Integer(), nullable=False),
        sa.Column("coverage_limit_amount", sa.Numeric(18, 8), nullable=False),
        sa.Column("issued_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("admin_comment", sa.Text(), nullable=True),
        sa.Column("payment_evidence", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )

    op.create_table(
        "compensations",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("report_id", sa.Integer(), sa.ForeignKey("scam_reports.id", ondelete="SET NULL"), nullable=True),
        sa.Column("amount", sa.Numeric(18, 8), nullable=False),
        sa.Column("currency", sa.String(length=32), nullable=False),
        sa.Column("status", compensation_status, nullable=False, server_default="pending"),
        sa.Column("comment", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index(op.f("ix_compensations_user_id"), "compensations", ["user_id"])

    op.create_table(
        "history_logs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=True),
        sa.Column("actor_admin_id", sa.BigInteger(), nullable=True),
        sa.Column("action", sa.String(length=64), nullable=False),
        sa.Column("old_status", sa.String(length=32), nullable=True),
        sa.Column("new_status", sa.String(length=32), nullable=True),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("metadata", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index(op.f("ix_history_logs_user_id"), "history_logs", ["user_id"])
    op.create_index(op.f("ix_history_logs_actor_admin_id"), "history_logs", ["actor_admin_id"])
    op.create_index("ix_history_logs_user_created", "history_logs", ["user_id", "created_at"])

    op.create_table(
        "admin_actions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("admin_telegram_user_id", sa.BigInteger(), nullable=False),
        sa.Column("action", sa.String(length=64), nullable=False),
        sa.Column("target_user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("report_id", sa.Integer(), sa.ForeignKey("scam_reports.id", ondelete="SET NULL"), nullable=True),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index(op.f("ix_admin_actions_admin_telegram_user_id"), "admin_actions", ["admin_telegram_user_id"])
    op.create_index(op.f("ix_admin_actions_target_user_id"), "admin_actions", ["target_user_id"])
    op.create_index(op.f("ix_admin_actions_report_id"), "admin_actions", ["report_id"])

    op.create_table(
        "chats",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("telegram_chat_id", sa.BigInteger(), nullable=False, unique=True),
        sa.Column("type", sa.String(length=32), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=True),
        sa.Column("username", sa.String(length=32), nullable=True),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index(op.f("ix_chats_telegram_chat_id"), "chats", ["telegram_chat_id"], unique=True)

    op.create_table(
        "user_chat_memberships",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("chat_id", sa.Integer(), sa.ForeignKey("chats.id", ondelete="CASCADE"), nullable=False),
        sa.Column("role", sa.String(length=64), nullable=True),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("user_id", "chat_id", name="uq_user_chat_membership"),
    )
    op.create_index("ix_user_chat_memberships_user_seen", "user_chat_memberships", ["user_id", "last_seen_at"])


def downgrade() -> None:
    op.drop_table("user_chat_memberships")
    op.drop_table("chats")
    op.drop_table("admin_actions")
    op.drop_table("history_logs")
    op.drop_table("compensations")
    op.drop_table("trusted_users")
    op.drop_table("guarantors")
    op.drop_table("evidence")
    op.drop_table("scam_reports")
    op.drop_table("statuses")
    op.drop_table("username_history")
    op.drop_table("users")

    compensation_status.drop(op.get_bind(), checkfirst=True)
    report_status.drop(op.get_bind(), checkfirst=True)
    status_type.drop(op.get_bind(), checkfirst=True)

