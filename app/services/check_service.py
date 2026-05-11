from __future__ import annotations

from dataclasses import dataclass

from aiogram import Bot
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import Evidence, HistoryLog, Status, StatusType, User
from app.services import user_service
from app.utils.formatters import risk_for_status
from app.utils.validators import ParsedTarget


@dataclass(slots=True)
class CheckResult:
    user: User | None
    status: Status | None
    evidence: list[Evidence]
    history_count: int
    known_groups: list[str]
    not_found_target: str | None = None


async def get_active_status(session: AsyncSession, user_id: int) -> Status | None:
    result = await session.execute(
        select(Status)
        .where(Status.user_id == user_id, Status.is_active.is_(True))
        .order_by(Status.issued_at.desc()),
    )
    return result.scalars().first()


async def get_status_evidence(session: AsyncSession, user: User, status: Status | None) -> list[Evidence]:
    filters = [Evidence.related_user_id == user.id]
    if status:
        filters.append(Evidence.related_status_id == status.id)
    result = await session.execute(
        select(Evidence)
        .where(or_(*filters))
        .order_by(Evidence.created_at.desc())
        .limit(10),
    )
    return list(result.scalars().all())


async def get_history_count(session: AsyncSession, user_id: int) -> int:
    result = await session.execute(
        select(func.count(HistoryLog.id)).where(HistoryLog.user_id == user_id),
    )
    return int(result.scalar_one() or 0)


async def resolve_target_via_telegram(
    session: AsyncSession,
    bot: Bot,
    target: ParsedTarget,
) -> User | None:
    chat_ref: int | str | None = None
    if target.user_id:
        chat_ref = target.user_id
    elif target.username:
        chat_ref = f"@{target.username}"
    if chat_ref is None:
        return None

    try:
        chat = await bot.get_chat(chat_ref)
    except Exception:
        return None

    if chat.type != "private":
        return None

    return await user_service.upsert_user_identity(
        session,
        telegram_user_id=chat.id,
        username=chat.username or target.username,
        first_name=getattr(chat, "full_name", None) or getattr(chat, "first_name", None),
    )


async def check_target(session: AsyncSession, bot: Bot, target: ParsedTarget) -> CheckResult:
    user = await user_service.find_user_by_target(session, target)
    if user is None:
        user = await resolve_target_via_telegram(session, bot, target)

    if user is None:
        return CheckResult(
            user=None,
            status=None,
            evidence=[],
            history_count=0,
            known_groups=[],
            not_found_target=target.display,
        )

    status = await get_active_status(session, user.id)
    evidence = await get_status_evidence(session, user, status)
    history_count = await get_history_count(session, user.id)
    groups = await user_service.get_known_group_names(session, user.id)
    return CheckResult(
        user=user,
        status=status,
        evidence=evidence,
        history_count=history_count,
        known_groups=groups,
        not_found_target=None,
    )


def unknown_status_stub() -> tuple[StatusType, int]:
    return StatusType.unknown, risk_for_status(StatusType.unknown)
