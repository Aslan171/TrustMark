from __future__ import annotations

import logging
from html import escape

from aiogram import Bot, F, Router
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State
from aiogram.types import BufferedInputFile, CallbackQuery, Message
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import Evidence, HistoryLog, User, UsernameHistory
from app.keyboards.user_keyboards import check_result_keyboard
from app.services import check_service, user_service
from app.services.card_service import generate_user_card
from app.states.check_states import CheckStates
from app.utils.formatters import format_check_card_text, format_date, status_label
from app.utils.validators import ParsedTarget, parse_check_command, parse_forwarded_user, parse_target_text

logger = logging.getLogger(__name__)
router = Router(name="checks")


def _self_target(message: Message) -> ParsedTarget:
    assert message.from_user is not None
    return ParsedTarget(
        raw=str(message.from_user.id),
        user_id=message.from_user.id,
        username=message.from_user.username,
        hidden_name=message.from_user.full_name,
    )


def _reply_target(message: Message) -> ParsedTarget | None:
    if not message.reply_to_message or not message.reply_to_message.from_user:
        return None
    user = message.reply_to_message.from_user
    return ParsedTarget(
        raw=str(user.id),
        user_id=user.id,
        username=user.username,
        hidden_name=user.full_name,
    )


def _extract_target_from_message(message: Message, explicit_text: str | None = None) -> ParsedTarget | None:
    forwarded = parse_forwarded_user(message)
    if forwarded:
        return forwarded

    text = explicit_text if explicit_text is not None else message.text
    if text:
        lowered = text.strip().casefold()
        if lowered in {"ми", "me", "я", "себя"}:
            return _self_target(message)
        parsed = parse_target_text(text)
        if parsed:
            return parsed

    return _reply_target(message)


async def send_check_result(
    message: Message,
    bot: Bot,
    session: AsyncSession,
    target: ParsedTarget,
) -> None:
    result = await check_service.check_target(session, bot, target)
    text = format_check_card_text(
        result.user,
        result.status,
        result.evidence,
        result.history_count,
        result.known_groups,
        result.not_found_target,
    )

    if result.user:
        try:
            card = await generate_user_card(bot, result.user, result.status)
            await message.answer_photo(
                BufferedInputFile(card, filename="trustmark_card.png"),
                caption="TrustMark проверка пользователя",
            )
        except Exception:
            logger.exception("Failed to generate TrustMark card")

    await message.answer(
        text,
        reply_markup=check_result_keyboard(result.user.id if result.user else None),
        disable_web_page_preview=True,
    )


@router.callback_query(F.data == "check:start")
async def ask_check_target(callback: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(CheckStates.waiting_target)
    await callback.message.answer(
        "Введите Telegram ID, @username или перешлите сообщение пользователя.\n\n"
        "В любом чате также можно написать: <code>чек @username</code> или <code>чек ми</code>."
    )
    await callback.answer()


@router.message(F.text == "🔎 Проверить пользователя")
async def ask_check_target_from_menu(message: Message, state: FSMContext) -> None:
    await state.set_state(CheckStates.waiting_target)
    await message.answer(
        "Введите Telegram ID, @username или перешлите сообщение пользователя.\n\n"
        "Username может быть изменён. Основная проверка идёт по Telegram ID."
    )


@router.message(CheckStates.waiting_target)
async def check_from_state(message: Message, bot: Bot, session: AsyncSession, state: FSMContext) -> None:
    target = _extract_target_from_message(message)
    if not target:
        await message.answer("Не удалось распознать пользователя. Укажите ID, @username или перешлите сообщение.")
        return
    await state.clear()
    await send_check_result(message, bot, session, target)


@router.message(F.text.func(lambda text: parse_check_command(text) is not None))
async def check_from_group_command(message: Message, bot: Bot, session: AsyncSession) -> None:
    command_arg = parse_check_command(message.text)
    if command_arg is None:
        return
    target = _extract_target_from_message(message, command_arg)
    if not target and command_arg == "":
        target = _reply_target(message)
    if not target:
        await message.answer(
            "Напишите <code>чек @username</code>, <code>чек ID</code>, <code>чек ми</code> "
            "или ответьте словом <code>чек</code> на сообщение пользователя."
        )
        return
    await send_check_result(message, bot, session, target)


@router.message(F.text == "👤 Мой профиль")
async def check_self_from_menu(message: Message, bot: Bot, session: AsyncSession) -> None:
    await send_check_result(message, bot, session, _self_target(message))


@router.callback_query(F.data.startswith("check:evidence:"))
async def show_evidence(callback: CallbackQuery, session: AsyncSession) -> None:
    user_id = int(callback.data.rsplit(":", 1)[-1])
    result = await session.execute(
        select(Evidence).where(Evidence.related_user_id == user_id).order_by(Evidence.created_at.desc()).limit(20),
    )
    evidence = result.scalars().all()
    if not evidence:
        await callback.message.answer("📁 Доказательства по пользователю пока не опубликованы.")
        await callback.answer()
        return
    lines = ["📁 <b>Доказательства</b>"]
    for index, item in enumerate(evidence, start=1):
        url = item.evidence_message_url or item.external_url
        title = item.title or item.file_type
        lines.append(
            f'{index}. <a href="{escape(url)}">{escape(title)}</a>'
            if url
            else f"{index}. {escape(title)}"
        )
    await callback.message.answer("\n".join(lines), disable_web_page_preview=True)
    await callback.answer()


@router.callback_query(F.data.startswith("check:history:"))
async def show_history(callback: CallbackQuery, session: AsyncSession) -> None:
    user_id = int(callback.data.rsplit(":", 1)[-1])
    result = await session.execute(
        select(HistoryLog).where(HistoryLog.user_id == user_id).order_by(HistoryLog.created_at.desc()).limit(10),
    )
    history = result.scalars().all()
    username_result = await session.execute(
        select(UsernameHistory)
        .where(UsernameHistory.user_id == user_id)
        .order_by(UsernameHistory.changed_at.desc())
        .limit(10),
    )
    username_history = username_result.scalars().all()
    if not history and not username_history:
        await callback.message.answer("📜 История статусов и username пока пустая.")
        await callback.answer()
        return
    lines = ["📜 <b>История статусов</b>"]
    for item in history:
        lines.append(
            f"{format_date(item.created_at)}: {item.old_status or 'нет'} → "
            f"{item.new_status or 'удалён'}\nПричина: {item.reason or 'не указана'}"
        )
    if username_history:
        lines.append("\n<b>История username</b>")
        for item in username_history:
            lines.append(
                f"{format_date(item.changed_at)}: @{item.old_username or 'нет'} → "
                f"@{item.new_username or 'нет'}"
            )
    await callback.message.answer("\n\n".join(lines))
    await callback.answer()


@router.callback_query(F.data.startswith("check:card:"))
async def open_card_from_admin(callback: CallbackQuery, bot: Bot, session: AsyncSession) -> None:
    user_db_id = int(callback.data.rsplit(":", 1)[-1])
    result = await session.execute(select(User).where(User.id == user_db_id))
    user = result.scalar_one_or_none()
    if not user:
        await callback.answer("Пользователь не найден.", show_alert=True)
        return
    target = ParsedTarget(raw=str(user.telegram_user_id or user.username), user_id=user.telegram_user_id, username=user.username)
    await send_check_result(callback.message, bot, session, target)
    await callback.answer()
