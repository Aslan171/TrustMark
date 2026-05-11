from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from typing import Any

from aiogram import BaseMiddleware
from aiogram.types import Message, TelegramObject
from sqlalchemy.ext.asyncio import AsyncSession

from app.services import user_service

logger = logging.getLogger(__name__)


class UserTrackingMiddleware(BaseMiddleware):
    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        session: AsyncSession | None = data.get("session")
        if isinstance(event, Message) and session and event.from_user:
            try:
                user = await user_service.upsert_from_telegram(session, event.from_user)
                await user_service.touch_chat_membership(session, user, event.chat)
                if event.reply_to_message and event.reply_to_message.from_user:
                    replied_user = await user_service.upsert_from_telegram(
                        session,
                        event.reply_to_message.from_user,
                    )
                    await user_service.touch_chat_membership(session, replied_user, event.chat)
            except Exception:
                logger.exception("Failed to track user or chat membership")
        return await handler(event, data)

