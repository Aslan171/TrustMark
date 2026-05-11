from __future__ import annotations

from datetime import UTC, datetime

from aiogram.types import Chat as TgChat
from aiogram.types import User as TgUser
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import Chat, User, UserChatMembership, UsernameHistory
from app.utils.validators import ParsedTarget


async def get_user_by_telegram_id(session: AsyncSession, telegram_user_id: int) -> User | None:
    result = await session.execute(
        select(User).where(User.telegram_user_id == telegram_user_id),
    )
    return result.scalar_one_or_none()


async def get_user_by_username(session: AsyncSession, username: str) -> User | None:
    lowered = username.lower().lstrip("@")
    result = await session.execute(
        select(User).where(func.lower(User.username) == lowered).order_by(User.updated_at.desc()),
    )
    user = result.scalars().first()
    if user:
        return user

    history_result = await session.execute(
        select(User)
        .join(UsernameHistory)
        .where(
            or_(
                func.lower(UsernameHistory.old_username) == lowered,
                func.lower(UsernameHistory.new_username) == lowered,
            ),
        )
        .order_by(UsernameHistory.changed_at.desc()),
    )
    return history_result.scalars().first()


async def upsert_user_identity(
    session: AsyncSession,
    telegram_user_id: int | None,
    username: str | None = None,
    first_name: str | None = None,
) -> User:
    user: User | None = None
    if telegram_user_id is not None:
        user = await get_user_by_telegram_id(session, telegram_user_id)
    if user is None and username:
        user = await get_user_by_username(session, username)

    normalized_username = username.lstrip("@") if username else None
    if user is None:
        user = User(
            telegram_user_id=telegram_user_id,
            username=normalized_username,
            first_name=first_name,
        )
        session.add(user)
        await session.flush()
        return user

    if telegram_user_id is not None and user.telegram_user_id is None:
        user.telegram_user_id = telegram_user_id

    if normalized_username != user.username:
        session.add(
            UsernameHistory(
                user_id=user.id,
                old_username=user.username,
                new_username=normalized_username,
            ),
        )
        user.username = normalized_username

    if first_name and first_name != user.first_name:
        user.first_name = first_name

    await session.flush()
    return user


async def upsert_from_telegram(session: AsyncSession, tg_user: TgUser) -> User:
    return await upsert_user_identity(
        session=session,
        telegram_user_id=tg_user.id,
        username=tg_user.username,
        first_name=tg_user.full_name,
    )


async def find_user_by_target(session: AsyncSession, target: ParsedTarget) -> User | None:
    if target.user_id:
        user = await get_user_by_telegram_id(session, target.user_id)
        if user:
            return user
    if target.username:
        return await get_user_by_username(session, target.username)
    return None


async def touch_chat_membership(
    session: AsyncSession,
    user: User,
    tg_chat: TgChat,
    role: str | None = None,
) -> None:
    if tg_chat.type == "private":
        return

    now = datetime.now(UTC)
    result = await session.execute(
        select(Chat).where(Chat.telegram_chat_id == tg_chat.id),
    )
    chat = result.scalar_one_or_none()
    if chat is None:
        chat = Chat(
            telegram_chat_id=tg_chat.id,
            type=tg_chat.type,
            title=tg_chat.title,
            username=tg_chat.username,
            last_seen_at=now,
        )
        session.add(chat)
        await session.flush()
    else:
        chat.type = tg_chat.type
        chat.title = tg_chat.title
        chat.username = tg_chat.username
        chat.last_seen_at = now

    membership_result = await session.execute(
        select(UserChatMembership).where(
            UserChatMembership.user_id == user.id,
            UserChatMembership.chat_id == chat.id,
        ),
    )
    membership = membership_result.scalar_one_or_none()
    if membership is None:
        membership = UserChatMembership(user_id=user.id, chat_id=chat.id, role=role, last_seen_at=now)
        session.add(membership)
    else:
        membership.role = role or membership.role
        membership.last_seen_at = now
    await session.flush()


async def get_known_group_names(session: AsyncSession, user_id: int, limit: int = 5) -> list[str]:
    result = await session.execute(
        select(Chat)
        .join(UserChatMembership)
        .where(UserChatMembership.user_id == user_id)
        .order_by(UserChatMembership.last_seen_at.desc())
        .limit(limit),
    )
    return [chat.display_name for chat in result.scalars().all()]

