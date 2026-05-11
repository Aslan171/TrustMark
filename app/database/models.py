from __future__ import annotations

import enum
from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class StatusType(str, enum.Enum):
    guarantor = "guarantor"
    trusted_user = "trusted_user"
    unknown = "unknown"
    suspicious = "suspicious"
    scammer = "scammer"


class ReportStatus(str, enum.Enum):
    new = "new"
    insufficient = "insufficient"
    reviewing = "reviewing"
    approved = "approved"
    rejected = "rejected"


class EvidenceFileType(str, enum.Enum):
    photo = "photo"
    video = "video"
    document = "document"
    link = "link"
    text = "text"
    card = "card"
    payment = "payment"


class CompensationStatus(str, enum.Enum):
    pending = "pending"
    paid = "paid"
    rejected = "rejected"


def enum_values(enum_cls: type[enum.Enum]) -> list[str]:
    return [item.value for item in enum_cls]


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


class User(Base, TimestampMixin):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    telegram_user_id: Mapped[int | None] = mapped_column(BigInteger, unique=True, index=True)
    username: Mapped[str | None] = mapped_column(String(32), index=True)
    first_name: Mapped[str | None] = mapped_column(String(255))

    statuses: Mapped[list[Status]] = relationship(back_populates="user", cascade="all, delete-orphan")
    username_history: Mapped[list[UsernameHistory]] = relationship(
        back_populates="user",
        cascade="all, delete-orphan",
    )
    evidence: Mapped[list[Evidence]] = relationship(
        back_populates="related_user",
        foreign_keys="Evidence.related_user_id",
    )
    memberships: Mapped[list[UserChatMembership]] = relationship(
        back_populates="user",
        cascade="all, delete-orphan",
    )

    @property
    def display_name(self) -> str:
        if self.username:
            return f"@{self.username}"
        if self.first_name:
            return self.first_name
        if self.telegram_user_id:
            return f"ID {self.telegram_user_id}"
        return "Пользователь"


class UsernameHistory(Base):
    __tablename__ = "username_history"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    old_username: Mapped[str | None] = mapped_column(String(32))
    new_username: Mapped[str | None] = mapped_column(String(32))
    changed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    user: Mapped[User] = relationship(back_populates="username_history")


class Status(Base):
    __tablename__ = "statuses"
    __table_args__ = (
        Index("ix_statuses_user_active", "user_id", "is_active"),
        Index("ix_statuses_type_active", "status_type", "is_active"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    status_type: Mapped[StatusType] = mapped_column(
        Enum(StatusType, values_callable=enum_values, name="status_type"),
        nullable=False,
    )
    risk_percent: Mapped[int] = mapped_column(Integer, nullable=False)
    reason: Mapped[str | None] = mapped_column(Text)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    issued_by_admin_id: Mapped[int | None] = mapped_column(BigInteger, index=True)
    issued_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    coverage_limit_amount: Mapped[Decimal | None] = mapped_column(Numeric(18, 8))
    coverage_currency: Mapped[str | None] = mapped_column(String(32))

    user: Mapped[User] = relationship(back_populates="statuses")
    evidence: Mapped[list[Evidence]] = relationship(
        back_populates="related_status",
        foreign_keys="Evidence.related_status_id",
    )


class ScamReport(Base, TimestampMixin):
    __tablename__ = "scam_reports"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    reporter_user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    accused_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), index=True)
    accused_raw: Mapped[str | None] = mapped_column(String(255))
    amount: Mapped[Decimal | None] = mapped_column(Numeric(18, 8))
    currency: Mapped[str | None] = mapped_column(String(32))
    description: Mapped[str] = mapped_column(Text)
    status: Mapped[ReportStatus] = mapped_column(
        Enum(ReportStatus, values_callable=enum_values, name="report_status"),
        default=ReportStatus.new,
        nullable=False,
    )
    admin_comment: Mapped[str | None] = mapped_column(Text)
    assigned_admin_id: Mapped[int | None] = mapped_column(BigInteger)
    admin_chat_message_id: Mapped[int | None] = mapped_column(BigInteger)

    reporter: Mapped[User] = relationship(foreign_keys=[reporter_user_id])
    accused: Mapped[User | None] = relationship(foreign_keys=[accused_user_id])
    evidence: Mapped[list[Evidence]] = relationship(
        back_populates="related_report",
        foreign_keys="Evidence.related_report_id",
    )


class Evidence(Base):
    __tablename__ = "evidence"
    __table_args__ = (
        Index("ix_evidence_related_user", "related_user_id"),
        Index("ix_evidence_related_status", "related_status_id"),
        Index("ix_evidence_related_report", "related_report_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    related_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    related_status_id: Mapped[int | None] = mapped_column(ForeignKey("statuses.id", ondelete="CASCADE"))
    related_report_id: Mapped[int | None] = mapped_column(ForeignKey("scam_reports.id", ondelete="CASCADE"))
    uploaded_by_admin_id: Mapped[int | None] = mapped_column(BigInteger, index=True)
    telegram_file_id: Mapped[str | None] = mapped_column(String(512))
    file_type: Mapped[str] = mapped_column(String(32), nullable=False)
    title: Mapped[str | None] = mapped_column(String(255))
    text_content: Mapped[str | None] = mapped_column(Text)
    external_url: Mapped[str | None] = mapped_column(String(2048))
    evidence_channel_id: Mapped[int | None] = mapped_column(BigInteger)
    evidence_message_id: Mapped[int | None] = mapped_column(BigInteger)
    evidence_message_url: Mapped[str | None] = mapped_column(String(2048))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    related_user: Mapped[User | None] = relationship(
        back_populates="evidence",
        foreign_keys=[related_user_id],
    )
    related_status: Mapped[Status | None] = relationship(
        back_populates="evidence",
        foreign_keys=[related_status_id],
    )
    related_report: Mapped[ScamReport | None] = relationship(
        back_populates="evidence",
        foreign_keys=[related_report_id],
    )


class Guarantor(Base, TimestampMixin):
    __tablename__ = "guarantors"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), unique=True)
    issued_status_id: Mapped[int | None] = mapped_column(ForeignKey("statuses.id", ondelete="SET NULL"))
    entry_fee_amount: Mapped[Decimal] = mapped_column(Numeric(18, 8), default=Decimal("20"))
    entry_fee_currency: Mapped[str] = mapped_column(String(16), default="USD", nullable=False)
    reviews_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    nft_usernames_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    nft_gifts_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    verified_by_admin_id: Mapped[int | None] = mapped_column(BigInteger)
    admin_comment: Mapped[str | None] = mapped_column(Text)

    user: Mapped[User] = relationship()
    issued_status: Mapped[Status | None] = relationship()


class TrustedUser(Base, TimestampMixin):
    __tablename__ = "trusted_users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), unique=True)
    issued_status_id: Mapped[int | None] = mapped_column(ForeignKey("statuses.id", ondelete="SET NULL"))
    payment_amount: Mapped[Decimal] = mapped_column(Numeric(18, 8), nullable=False)
    payment_currency: Mapped[str] = mapped_column(String(32), default="USD", nullable=False)
    coverage_percent: Mapped[int] = mapped_column(Integer, nullable=False)
    coverage_limit_amount: Mapped[Decimal] = mapped_column(Numeric(18, 8), nullable=False)
    issued_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    admin_comment: Mapped[str | None] = mapped_column(Text)
    payment_evidence: Mapped[str | None] = mapped_column(Text)

    user: Mapped[User] = relationship()
    issued_status: Mapped[Status | None] = relationship()


class Compensation(Base, TimestampMixin):
    __tablename__ = "compensations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    report_id: Mapped[int | None] = mapped_column(ForeignKey("scam_reports.id", ondelete="SET NULL"))
    amount: Mapped[Decimal] = mapped_column(Numeric(18, 8), nullable=False)
    currency: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[CompensationStatus] = mapped_column(
        Enum(CompensationStatus, values_callable=enum_values, name="compensation_status"),
        default=CompensationStatus.pending,
        nullable=False,
    )
    comment: Mapped[str | None] = mapped_column(Text)


class HistoryLog(Base):
    __tablename__ = "history_logs"
    __table_args__ = (Index("ix_history_logs_user_created", "user_id", "created_at"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    actor_admin_id: Mapped[int | None] = mapped_column(BigInteger, index=True)
    action: Mapped[str] = mapped_column(String(64), nullable=False)
    old_status: Mapped[str | None] = mapped_column(String(32))
    new_status: Mapped[str | None] = mapped_column(String(32))
    reason: Mapped[str | None] = mapped_column(Text)
    data: Mapped[dict[str, Any]] = mapped_column("metadata", JSONB, default=dict, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    user: Mapped[User | None] = relationship()


class AdminAction(Base):
    __tablename__ = "admin_actions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    admin_telegram_user_id: Mapped[int] = mapped_column(BigInteger, index=True, nullable=False)
    action: Mapped[str] = mapped_column(String(64), nullable=False)
    target_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), index=True)
    report_id: Mapped[int | None] = mapped_column(ForeignKey("scam_reports.id", ondelete="SET NULL"), index=True)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )


class Chat(Base):
    __tablename__ = "chats"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    telegram_chat_id: Mapped[int] = mapped_column(BigInteger, unique=True, index=True)
    type: Mapped[str] = mapped_column(String(32), nullable=False)
    title: Mapped[str | None] = mapped_column(String(255))
    username: Mapped[str | None] = mapped_column(String(32))
    last_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    memberships: Mapped[list[UserChatMembership]] = relationship(
        back_populates="chat",
        cascade="all, delete-orphan",
    )

    @property
    def display_name(self) -> str:
        if self.username:
            return f"@{self.username}"
        return self.title or str(self.telegram_chat_id)


class UserChatMembership(Base):
    __tablename__ = "user_chat_memberships"
    __table_args__ = (
        UniqueConstraint("user_id", "chat_id", name="uq_user_chat_membership"),
        Index("ix_user_chat_memberships_user_seen", "user_id", "last_seen_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    chat_id: Mapped[int] = mapped_column(ForeignKey("chats.id", ondelete="CASCADE"))
    role: Mapped[str | None] = mapped_column(String(64))
    last_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    user: Mapped[User] = relationship(back_populates="memberships")
    chat: Mapped[Chat] = relationship(back_populates="memberships")
