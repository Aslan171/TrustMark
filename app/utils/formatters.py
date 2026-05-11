from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from html import escape

from app.config import settings
from app.database.models import Evidence, Status, StatusType, User

STATUS_LABELS: dict[StatusType, str] = {
    StatusType.guarantor: "✅ Гарант",
    StatusType.trusted_user: "🛡️ Поручитель",
    StatusType.unknown: "⚪ Не найден в базе",
    StatusType.suspicious: "🟠 Подозрительная личность",
    StatusType.scammer: "⛔ Подтверждённый скамер",
}

STATUS_RISKS: dict[StatusType, int] = {
    StatusType.guarantor: 0,
    StatusType.trusted_user: 1,
    StatusType.unknown: 50,
    StatusType.suspicious: 75,
    StatusType.scammer: 99,
}


def status_label(status_type: StatusType | str | None) -> str:
    if not status_type:
        return STATUS_LABELS[StatusType.unknown]
    if isinstance(status_type, str):
        status_type = StatusType(status_type)
    return STATUS_LABELS[status_type]


def risk_for_status(status_type: StatusType | str | None) -> int:
    if not status_type:
        return STATUS_RISKS[StatusType.unknown]
    if isinstance(status_type, str):
        status_type = StatusType(status_type)
    return STATUS_RISKS[status_type]


def profile_link(user: User) -> str | None:
    if user.username:
        return f"https://t.me/{user.username}"
    return f"tg://user?id={user.telegram_user_id}" if user.telegram_user_id else None


def format_money(amount: Decimal | None, currency: str | None = "USD") -> str:
    if amount is None:
        return "не указан"
    normalized = amount.normalize()
    return f"{normalized:f} {currency or ''}".strip()


def format_date(value: datetime | None) -> str:
    if not value:
        return "не указана"
    return value.strftime("%d.%m.%Y")


def format_evidence_links(evidence: list[Evidence]) -> str:
    links: list[str] = []
    for index, item in enumerate(evidence, start=1):
        url = item.evidence_message_url or item.external_url
        if not url:
            continue
        title = item.title or item.file_type or "Материал"
        links.append(f'{index}. <a href="{escape(url)}">{escape(title)}</a>')
    if not links:
        return "Доказательства не опубликованы."
    return "\n".join(links)


def format_check_card_text(
    user: User | None,
    status: Status | None,
    evidence: list[Evidence],
    history_count: int = 0,
    known_groups: list[str] | None = None,
    not_found_target: str | None = None,
) -> str:
    if user is None:
        target = escape(not_found_target or "пользователь")
        return (
            "⚪ <b>Пользователь не найден в базе.</b>\n\n"
            f"Запрос: <code>{target}</code>\n\n"
            "Данных недостаточно для оценки риска.\n\n"
            "Рекомендуется:\n"
            "• проводить сделки через гаранта\n"
            "• не переводить крупные суммы без проверки\n\n"
            "⚠️ Username может быть изменён. Основная проверка идёт по Telegram ID."
        )

    current_status = status.status_type if status else StatusType.unknown
    link = profile_link(user)
    groups = ", ".join(escape(group) for group in known_groups or []) or "нет данных"
    coverage_line = ""
    if status and status.coverage_limit_amount is not None:
        coverage_line = (
            "\n\n<b>Лимит покрытия:</b>\n"
            f"до {escape(format_money(status.coverage_limit_amount, status.coverage_currency))}"
        )
    reason_line = ""
    if status and status.reason:
        reason_line = f"\n\n<b>Причина:</b>\n{escape(status.reason)}"
    issued_line = ""
    if status and status.issued_at:
        issued_line = f"\n\n<b>Дата выдачи:</b>\n{format_date(status.issued_at)}"

    return (
        f"👤 <b>Пользователь:</b> {escape(user.display_name)}\n"
        f"🆔 <b>ID:</b> <code>{user.telegram_user_id or 'неизвестен'}</code>\n"
        f"🔗 <b>Ссылка:</b> {escape(link) if link else 'нет данных'}\n"
        f"💬 <b>Известные группы:</b> {groups}\n\n"
        f"<b>Статус:</b> {status_label(current_status)}\n"
        f"<b>Риск сделки:</b> {risk_for_status(current_status)}%"
        f"{coverage_line}"
        f"{issued_line}"
        f"{reason_line}\n\n"
        f"<b>Доказательства:</b>\n{format_evidence_links(evidence)}\n\n"
        f"📜 История статусов: {history_count} записей\n\n"
        "⚠️ Username может быть изменён. Основная проверка идёт по Telegram ID.\n"
        "⚠️ Администрация ручается только в рамках лимита покрытия.\n\n"
        f"Создатель TrustMark: @{escape(settings.bot_owner_username)}"
    )

