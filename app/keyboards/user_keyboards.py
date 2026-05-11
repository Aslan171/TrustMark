from __future__ import annotations

from aiogram.types import InlineKeyboardMarkup, KeyboardButton, ReplyKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder


def main_menu_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="🔎 Проверить пользователя")],
            [KeyboardButton(text="🧾 Подать жалобу"), KeyboardButton(text="📜 Правила")],
            [KeyboardButton(text="👤 Мой профиль")],
        ],
        resize_keyboard=True,
        input_field_placeholder="Напишите: чек @username",
    )


def check_result_keyboard(user_db_id: int | None = None) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="🔎 Проверить другого", callback_data="check:start")
    builder.button(text="🧾 Подать жалобу", callback_data="report:start")
    builder.button(text="📜 Правила", callback_data="rules:show")
    if user_db_id:
        builder.button(text="📁 Доказательства", callback_data=f"check:evidence:{user_db_id}")
        builder.button(text="📜 История", callback_data=f"check:history:{user_db_id}")
    builder.adjust(1, 2, 2)
    return builder.as_markup()


def report_evidence_keyboard(has_evidence: bool = False) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="➕ Добавить ещё", callback_data="report:evidence:more")
    if has_evidence:
        builder.button(text="✅ Завершить", callback_data="report:evidence:done")
    builder.button(text="❌ Отменить", callback_data="report:cancel")
    builder.adjust(1)
    return builder.as_markup()


def report_confirm_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="✅ Отправить жалобу", callback_data="report:confirm")
    builder.button(text="❌ Отменить", callback_data="report:cancel")
    builder.adjust(1)
    return builder.as_markup()

