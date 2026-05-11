from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from aiogram import BaseMiddleware
from aiogram.types import CallbackQuery, Message, TelegramObject

from app.config import settings


class AdminOnlyMiddleware(BaseMiddleware):
    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        user = data.get("event_from_user")
        if user and settings.is_admin(user.id):
            return await handler(event, data)

        if isinstance(event, CallbackQuery):
            await event.answer("Недостаточно прав.", show_alert=True)
        elif isinstance(event, Message):
            await event.answer("Недостаточно прав.")
        return None

