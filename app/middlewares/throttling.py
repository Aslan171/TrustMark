from __future__ import annotations

import time
from collections.abc import Awaitable, Callable
from typing import Any

from aiogram import BaseMiddleware
from aiogram.types import CallbackQuery, Message, TelegramObject

from app.config import settings


class ThrottlingMiddleware(BaseMiddleware):
    def __init__(self, rate_limit_seconds: float | None = None) -> None:
        self.rate_limit_seconds = rate_limit_seconds or settings.rate_limit_seconds
        self._last_seen: dict[int, float] = {}

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        user = data.get("event_from_user")
        if user is None or settings.is_admin(user.id):
            return await handler(event, data)

        now = time.monotonic()
        last = self._last_seen.get(user.id, 0)
        if now - last < self.rate_limit_seconds:
            if isinstance(event, CallbackQuery):
                await event.answer("Слишком часто. Попробуйте через секунду.", show_alert=False)
            elif isinstance(event, Message):
                await event.answer("Слишком часто. Попробуйте через секунду.")
            return None
        self._last_seen[user.id] = now
        return await handler(event, data)

