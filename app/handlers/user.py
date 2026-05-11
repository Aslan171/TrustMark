from __future__ import annotations

from aiogram import F, Router
from aiogram.filters import Command, CommandStart
from aiogram.types import CallbackQuery, Message

from app.config import settings
from app.keyboards.user_keyboards import main_menu_keyboard

router = Router(name="user")


RULES_TEXT = (
    "📜 <b>Правила TrustMark</b>\n\n"
    "1. Главный идентификатор проверки — Telegram ID.\n"
    "2. Username может быть изменён, поэтому проверка только по @username не считается полной.\n"
    "3. Статусы «скамер» и «подозрительная личность» выдаются только после проверки материалов.\n"
    "4. Для серьёзной жалобы нужно полное видео сделки от начала до конца без обрезок.\n"
    "5. Компенсация поручителя возможна только в пределах лимита покрытия.\n"
    "6. Перед крупной сделкой используйте гаранта и не переводите деньги без проверки.\n\n"
    f"Создатель и владелец: @{settings.bot_owner_username}"
)


@router.message(CommandStart())
async def start(message: Message) -> None:
    await message.answer(
        f"Добро пожаловать в <b>{settings.project_name}</b>.\n\n"
        "Это система проверки репутации Telegram-пользователей, антискам-база, "
        "поручительство и оценка риска сделки.\n\n"
        "В любом чате можно написать:\n"
        "• <code>чек @username</code>\n"
        "• <code>чек 7258447737</code>\n"
        "• <code>чек ми</code>\n"
        "• ответить <code>чек</code> на сообщение пользователя",
        reply_markup=main_menu_keyboard(),
    )


@router.message(Command("help"))
async def help_command(message: Message) -> None:
    await start(message)


@router.message(F.text == "📜 Правила")
async def rules_from_menu(message: Message) -> None:
    await message.answer(RULES_TEXT, disable_web_page_preview=True)


@router.callback_query(F.data == "rules:show")
async def rules_from_callback(callback: CallbackQuery) -> None:
    await callback.message.answer(RULES_TEXT, disable_web_page_preview=True)
    await callback.answer()

