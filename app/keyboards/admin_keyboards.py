from __future__ import annotations

from aiogram.types import InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from app.database.models import StatusType


def admin_menu_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="🔍 Найти пользователя", callback_data="admin:find")
    builder.button(text="✅ Выдать гаранта", callback_data=f"admin:status:{StatusType.guarantor.value}")
    builder.button(text="🛡️ Выдать поручителя", callback_data=f"admin:status:{StatusType.trusted_user.value}")
    builder.button(text="🟠 Подозрительный", callback_data=f"admin:status:{StatusType.suspicious.value}")
    builder.button(text="⛔ Скамер", callback_data=f"admin:status:{StatusType.scammer.value}")
    builder.button(text="💵 Изменить лимит", callback_data="admin:change_limit")
    builder.button(text="🧹 Удалить статус", callback_data="admin:remove_status")
    builder.button(text="🗑️ Удалить доказательство", callback_data="admin:delete_evidence")
    builder.button(text="⛔ Список скамеров", callback_data=f"admin:list:{StatusType.scammer.value}")
    builder.button(text="🟠 Список подозрительных", callback_data=f"admin:list:{StatusType.suspicious.value}")
    builder.button(text="✅ Список гарантов", callback_data=f"admin:list:{StatusType.guarantor.value}")
    builder.button(text="🛡️ Список поручителей", callback_data=f"admin:list:{StatusType.trusted_user.value}")
    builder.adjust(1, 2, 2, 2, 1, 2, 2)
    return builder.as_markup()


def admin_evidence_keyboard(has_evidence: bool, status_type: StatusType) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="➕ Добавить ещё", callback_data="admin:evidence:more")
    can_finish = has_evidence or status_type in {
        StatusType.guarantor,
        StatusType.trusted_user,
        StatusType.suspicious,
    }
    if can_finish:
        builder.button(text="✅ Завершить", callback_data="admin:evidence:done")
    builder.button(text="❌ Отменить", callback_data="admin:cancel")
    builder.adjust(1)
    return builder.as_markup()


def admin_confirm_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="✅ Подтвердить выдачу статуса", callback_data="admin:confirm_status")
    builder.button(text="❌ Отменить", callback_data="admin:cancel")
    builder.adjust(1)
    return builder.as_markup()


def admin_report_keyboard(report_id: int, accused_user_id: int | None = None) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="✅ Подтвердить скам", callback_data=f"admin_report:approve:{report_id}")
    builder.button(text="❌ Отклонить", callback_data=f"admin_report:reject:{report_id}")
    builder.button(text="🕓 На проверке", callback_data=f"admin_report:review:{report_id}")
    builder.button(text="📎 Добавить доказательство", callback_data=f"admin_report:evidence:{report_id}")
    builder.button(text="✏️ Добавить комментарий", callback_data=f"admin_report:comment:{report_id}")
    if accused_user_id:
        builder.button(text="📁 Открыть карточку", callback_data=f"check:card:{accused_user_id}")
    builder.adjust(1, 2, 2, 1)
    return builder.as_markup()


def admin_cancel_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="❌ Отменить", callback_data="admin:cancel")
    return builder.as_markup()


def admin_report_evidence_collect_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="➕ Добавить ещё", callback_data="admin_report:evidence_more")
    builder.button(text="✅ Завершить", callback_data="admin_report:evidence_done")
    builder.button(text="❌ Отменить", callback_data="admin:cancel")
    builder.adjust(1)
    return builder.as_markup()
