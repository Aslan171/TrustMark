from __future__ import annotations

import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import ErrorEvent

from app.config import settings
from app.database.session import create_db_schema, dispose_engine
from app.handlers import admin, checks, reports, user
from app.middlewares.admin_check import AdminOnlyMiddleware
from app.middlewares.db import DbSessionMiddleware
from app.middlewares.throttling import ThrottlingMiddleware
from app.middlewares.user_tracking import UserTrackingMiddleware
from app.utils.logger import setup_logging

logger = logging.getLogger(__name__)


def build_dispatcher() -> Dispatcher:
    dp = Dispatcher(storage=MemoryStorage())
    dp.update.middleware(DbSessionMiddleware())
    dp.message.middleware(UserTrackingMiddleware())
    dp.message.middleware(ThrottlingMiddleware())
    dp.callback_query.middleware(ThrottlingMiddleware())

    admin.router.message.middleware(AdminOnlyMiddleware())
    admin.router.callback_query.middleware(AdminOnlyMiddleware())

    dp.include_router(admin.router)
    dp.include_router(reports.router)
    dp.include_router(checks.router)
    dp.include_router(user.router)

    @dp.errors()
    async def errors_handler(event: ErrorEvent) -> bool:
        logger.exception("Unhandled update error", exc_info=event.exception)
        return True

    return dp


async def main() -> None:
    settings.validate_runtime()
    setup_logging(settings.log_level)

    if settings.create_db_on_startup:
        await create_db_schema()

    bot = Bot(
        token=settings.bot_token,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    dp = build_dispatcher()

    try:
        await bot.delete_webhook(drop_pending_updates=True)
        logger.info("TrustMark bot is starting")
        await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())
    finally:
        await bot.session.close()
        await dispose_engine()


if __name__ == "__main__":
    asyncio.run(main())

