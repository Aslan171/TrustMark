from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
import logging
from html import escape

from aiogram import Bot
from aiogram.types import BufferedInputFile
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database.models import (
    AdminAction,
    Guarantor,
    HistoryLog,
    Status,
    StatusType,
    TrustedUser,
    User,
)
from app.services import check_service, user_service
from app.services.card_service import generate_user_card
from app.services.evidence_service import (
    EvidenceInput,
    create_evidence_record,
    evidence_channel_url,
    publish_and_store_evidence,
)
from app.utils.formatters import risk_for_status, status_label
from app.utils.validators import ParsedTarget

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class StatusPayload:
    target: ParsedTarget
    status_type: StatusType
    reason: str | None
    admin_id: int
    evidence: list[EvidenceInput] = field(default_factory=list)
    trusted_payment_amount: Decimal | None = None
    trusted_payment_currency: str | None = None
    trusted_coverage_percent: int | None = None
    guarantor_reviews: int = 0
    guarantor_nft_usernames: int = 0
    guarantor_nft_gifts: int = 0
    admin_comment: str | None = None


async def resolve_admin_target(session: AsyncSession, bot: Bot, target: ParsedTarget) -> User:
    user = await user_service.find_user_by_target(session, target)
    if user:
        return user

    resolved = await check_service.resolve_target_via_telegram(session, bot, target)
    if resolved:
        return resolved

    if target.user_id:
        return await user_service.upsert_user_identity(
            session,
            telegram_user_id=target.user_id,
            username=target.username,
            first_name=target.hidden_name,
        )

    raise ValueError(
        "Не удалось получить Telegram ID по username. Попросите переслать сообщение пользователя "
        "или укажите числовой Telegram ID."
    )


def validate_status_payload(payload: StatusPayload) -> None:
    reason = (payload.reason or "").strip()
    has_evidence = bool(payload.evidence)

    if payload.status_type == StatusType.scammer and (not reason or not has_evidence):
        raise ValueError("Для статуса скамера обязательны и причина, и доказательства.")

    if payload.status_type == StatusType.suspicious and not reason and not has_evidence:
        raise ValueError("Для подозрительного статуса нужна причина или хотя бы один материал.")

    if payload.status_type == StatusType.trusted_user:
        if payload.trusted_payment_amount is None:
            raise ValueError("Для поручителя нужна сумма оплаты.")
        if payload.trusted_coverage_percent is None:
            raise ValueError("Для поручителя нужен процент покрытия.")
        if not 1 <= payload.trusted_coverage_percent <= 100:
            raise ValueError("Процент покрытия должен быть от 1 до 100.")


async def deactivate_active_statuses(session: AsyncSession, user_id: int) -> Status | None:
    result = await session.execute(
        select(Status).where(Status.user_id == user_id, Status.is_active.is_(True)),
    )
    old_statuses = list(result.scalars().all())
    for status in old_statuses:
        status.is_active = False
    await session.flush()
    return old_statuses[0] if old_statuses else None


async def _upsert_guarantor(
    session: AsyncSession,
    user: User,
    status: Status,
    payload: StatusPayload,
) -> None:
    result = await session.execute(select(Guarantor).where(Guarantor.user_id == user.id))
    guarantor = result.scalar_one_or_none()
    if guarantor is None:
        guarantor = Guarantor(user_id=user.id)
        session.add(guarantor)
    guarantor.issued_status_id = status.id
    guarantor.entry_fee_amount = Decimal("20")
    guarantor.entry_fee_currency = "USD"
    guarantor.reviews_count = payload.guarantor_reviews
    guarantor.nft_usernames_count = payload.guarantor_nft_usernames
    guarantor.nft_gifts_count = payload.guarantor_nft_gifts
    guarantor.verified_by_admin_id = payload.admin_id
    guarantor.admin_comment = payload.admin_comment or payload.reason


async def _upsert_trusted_user(
    session: AsyncSession,
    user: User,
    status: Status,
    payload: StatusPayload,
) -> None:
    assert payload.trusted_payment_amount is not None
    assert payload.trusted_coverage_percent is not None
    coverage = (
        payload.trusted_payment_amount * Decimal(payload.trusted_coverage_percent) / Decimal(100)
    ).quantize(Decimal("0.01"))

    result = await session.execute(select(TrustedUser).where(TrustedUser.user_id == user.id))
    trusted = result.scalar_one_or_none()
    if trusted is None:
        trusted = TrustedUser(
            user_id=user.id,
            payment_amount=payload.trusted_payment_amount,
            coverage_percent=payload.trusted_coverage_percent,
            coverage_limit_amount=coverage,
        )
        session.add(trusted)

    trusted.issued_status_id = status.id
    trusted.payment_amount = payload.trusted_payment_amount
    trusted.payment_currency = payload.trusted_payment_currency or "USD"
    trusted.coverage_percent = payload.trusted_coverage_percent
    trusted.coverage_limit_amount = coverage
    trusted.admin_comment = payload.admin_comment or payload.reason
    status.coverage_limit_amount = coverage
    status.coverage_currency = trusted.payment_currency


def _status_summary(user: User, status: Status, payload: StatusPayload) -> str:
    reason = payload.reason or "Решение администрации TrustMark."
    return (
        f"{status_label(status.status_type)}\n\n"
        f"Пользователь: {user.display_name}\n"
        f"Telegram ID: {user.telegram_user_id or 'неизвестен'}\n"
        f"Риск сделки: {status.risk_percent}%\n"
        f"Причина: {reason}\n\n"
        f"Решение администратора: {payload.admin_id}\n"
        "Username может быть изменён. Основная проверка идёт по Telegram ID."
    )


async def set_user_status(
    session: AsyncSession,
    bot: Bot,
    payload: StatusPayload,
) -> tuple[User, Status]:
    validate_status_payload(payload)
    user = await resolve_admin_target(session, bot, payload.target)
    old_status = await deactivate_active_statuses(session, user.id)

    status = Status(
        user_id=user.id,
        status_type=payload.status_type,
        risk_percent=risk_for_status(payload.status_type),
        reason=payload.reason,
        issued_by_admin_id=payload.admin_id,
    )
    session.add(status)
    await session.flush()

    if payload.status_type == StatusType.guarantor:
        await _upsert_guarantor(session, user, status, payload)
    elif payload.status_type == StatusType.trusted_user:
        await _upsert_trusted_user(session, user, status, payload)

    if settings.evidence_channel_id is not None:
        try:
            card_bytes = await generate_user_card(bot, user, status)
            sent_card = await bot.send_photo(
                settings.evidence_channel_id,
                BufferedInputFile(card_bytes, filename="trustmark_status_card.png"),
                caption=f"TrustMark card • {status_label(status.status_type)} • {escape(user.display_name)}",
            )
            await create_evidence_record(
                session,
                EvidenceInput(
                    file_type="card",
                    title="Карточка TrustMark",
                    telegram_file_id=sent_card.photo[-1].file_id if sent_card.photo else None,
                    text_content=f"{status_label(status.status_type)} • {user.display_name}",
                ),
                related_user_id=user.id,
                related_status_id=status.id,
                uploaded_by_admin_id=payload.admin_id,
                channel_message_id=sent_card.message_id,
                channel_url=evidence_channel_url(sent_card.message_id),
            )
        except Exception:
            logger.exception("Failed to publish TrustMark status card")

    summary = EvidenceInput(
        file_type="text",
        title=f"Карточка статуса: {status_label(payload.status_type)}",
        text_content=_status_summary(user, status, payload),
    )
    await publish_and_store_evidence(
        session,
        bot,
        [summary, *payload.evidence],
        caption=f"TrustMark Evidence • {status_label(payload.status_type)}",
        related_user_id=user.id,
        related_status_id=status.id,
        uploaded_by_admin_id=payload.admin_id,
    )

    session.add(
        HistoryLog(
            user_id=user.id,
            actor_admin_id=payload.admin_id,
            action="status_set",
            old_status=old_status.status_type.value if old_status else None,
            new_status=status.status_type.value,
            reason=payload.reason,
            data={"target": payload.target.display},
        ),
    )
    session.add(
        AdminAction(
            admin_telegram_user_id=payload.admin_id,
            action="status_set",
            target_user_id=user.id,
            payload={
                "status_type": status.status_type.value,
                "reason": payload.reason,
                "evidence_count": len(payload.evidence),
            },
        ),
    )
    await session.flush()
    return user, status


async def remove_active_status(
    session: AsyncSession,
    target_user: User,
    admin_id: int,
    reason: str | None = None,
) -> bool:
    old_status = await deactivate_active_statuses(session, target_user.id)
    if not old_status:
        return False
    session.add(
        HistoryLog(
            user_id=target_user.id,
            actor_admin_id=admin_id,
            action="status_removed",
            old_status=old_status.status_type.value,
            new_status=None,
            reason=reason,
            data={},
        ),
    )
    session.add(
        AdminAction(
            admin_telegram_user_id=admin_id,
            action="status_removed",
            target_user_id=target_user.id,
            payload={"old_status": old_status.status_type.value, "reason": reason},
        ),
    )
    await session.flush()
    return True


async def list_users_by_status(
    session: AsyncSession,
    status_type: StatusType,
    limit: int = 30,
) -> list[tuple[User, Status]]:
    result = await session.execute(
        select(User, Status)
        .join(Status, Status.user_id == User.id)
        .where(Status.status_type == status_type, Status.is_active.is_(True))
        .order_by(Status.issued_at.desc())
        .limit(limit),
    )
    return list(result.all())


async def get_history(session: AsyncSession, user_id: int, limit: int = 10) -> list[HistoryLog]:
    result = await session.execute(
        select(HistoryLog)
        .where(HistoryLog.user_id == user_id)
        .order_by(HistoryLog.created_at.desc())
        .limit(limit),
    )
    return list(result.scalars().all())


async def update_coverage_limit(
    session: AsyncSession,
    user: User,
    amount: Decimal,
    currency: str,
    admin_id: int,
) -> Status:
    status = await check_service.get_active_status(session, user.id)
    if not status:
        raise ValueError("У пользователя нет активного статуса.")
    if status.status_type not in {StatusType.trusted_user, StatusType.guarantor}:
        raise ValueError("Лимит покрытия можно менять только гарантам и поручителям.")

    status.coverage_limit_amount = amount
    status.coverage_currency = currency

    trusted_result = await session.execute(select(TrustedUser).where(TrustedUser.user_id == user.id))
    trusted = trusted_result.scalar_one_or_none()
    if trusted:
        trusted.coverage_limit_amount = amount
        trusted.payment_currency = currency

    session.add(
        HistoryLog(
            user_id=user.id,
            actor_admin_id=admin_id,
            action="coverage_limit_updated",
            old_status=status.status_type.value,
            new_status=status.status_type.value,
            reason=f"Новый лимит покрытия: {amount} {currency}",
            data={"amount": str(amount), "currency": currency},
        ),
    )
    session.add(
        AdminAction(
            admin_telegram_user_id=admin_id,
            action="coverage_limit_updated",
            target_user_id=user.id,
            payload={"amount": str(amount), "currency": currency},
        ),
    )
    await session.flush()
    return status
