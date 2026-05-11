from __future__ import annotations

from dataclasses import asdict
from decimal import Decimal
from html import escape

from aiogram import Bot, F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.filters import StateFilter
from aiogram.types import CallbackQuery, Message
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database.models import Evidence, ReportStatus, StatusType, User
from app.handlers.checks import send_check_result
from app.keyboards.admin_keyboards import (
    admin_cancel_keyboard,
    admin_confirm_keyboard,
    admin_evidence_keyboard,
    admin_menu_keyboard,
    admin_report_evidence_collect_keyboard,
)
from app.services import admin_service, report_service
from app.services.admin_service import StatusPayload
from app.services.evidence_service import EvidenceInput, create_evidence_record, evidence_from_message
from app.states.admin_states import (
    AdminDeleteEvidenceStates,
    AdminFindStates,
    AdminLimitStates,
    AdminRemoveStatusStates,
    AdminReportStates,
    AdminStatusStates,
)
from app.utils.currencies import normalize_currency, parse_amount
from app.utils.formatters import format_date, format_money, status_label
from app.utils.validators import ParsedTarget, parse_forwarded_user, parse_target_text

router = Router(name="admin")


def _target_to_dict(target: ParsedTarget) -> dict:
    return {
        "raw": target.raw,
        "user_id": target.user_id,
        "username": target.username,
        "hidden_name": target.hidden_name,
    }


def _target_from_dict(data: dict) -> ParsedTarget:
    return ParsedTarget(
        raw=data["raw"],
        user_id=data.get("user_id"),
        username=data.get("username"),
        hidden_name=data.get("hidden_name"),
    )


def _evidence_from_dict(data: dict) -> EvidenceInput:
    return EvidenceInput(**data)


def _parse_target_from_admin_message(message: Message) -> ParsedTarget | None:
    return parse_forwarded_user(message) or parse_target_text(message.text)


def _optional_text(text: str | None) -> str | None:
    if not text:
        return None
    normalized = text.strip()
    if normalized.casefold() in {"нет", "skip", "пропустить", "-", "без причины"}:
        return None
    return normalized


@router.message(Command("admin"))
async def admin_menu(message: Message) -> None:
    await message.answer(
        f"🛠 <b>Админ-панель {settings.project_name}</b>",
        reply_markup=admin_menu_keyboard(),
    )


@router.callback_query(F.data == "admin:cancel")
async def admin_cancel(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await callback.message.answer("Админ-действие отменено.")
    await callback.answer()


@router.callback_query(F.data == "admin:find")
async def admin_find_start(callback: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(AdminFindStates.target)
    await callback.message.answer("Укажите Telegram ID, @username или перешлите сообщение пользователя.")
    await callback.answer()


@router.message(AdminFindStates.target)
async def admin_find_target(
    message: Message,
    bot: Bot,
    session: AsyncSession,
    state: FSMContext,
) -> None:
    target = _parse_target_from_admin_message(message)
    if not target:
        await message.answer("Не удалось распознать пользователя.")
        return
    await state.clear()
    await send_check_result(message, bot, session, target)


@router.callback_query(F.data.startswith("admin:status:"))
async def admin_status_start(callback: CallbackQuery, state: FSMContext) -> None:
    status_type = StatusType(callback.data.rsplit(":", 1)[-1])
    await state.clear()
    await state.set_state(AdminStatusStates.target)
    await state.update_data(status_type=status_type.value, evidence=[])
    await callback.message.answer(
        f"{status_label(status_type)}\n\n"
        "Укажите Telegram ID, @username или перешлите сообщение пользователя.",
        reply_markup=admin_cancel_keyboard(),
    )
    await callback.answer()


@router.message(AdminStatusStates.target)
async def admin_status_target(message: Message, state: FSMContext) -> None:
    target = _parse_target_from_admin_message(message)
    if not target:
        await message.answer("Не удалось распознать пользователя. Нужен ID, @username или forwarded message.")
        return
    await state.update_data(target=_target_to_dict(target))
    await state.set_state(AdminStatusStates.reason)
    await message.answer(
        "Укажите причину или комментарий администрации.\n\n"
        "Для скамера причина обязательна. Для подозрительного статуса нужна причина или материал."
    )


@router.message(AdminStatusStates.reason)
async def admin_status_reason(message: Message, state: FSMContext) -> None:
    reason = _optional_text(message.text)
    data = await state.get_data()
    status_type = StatusType(data["status_type"])
    await state.update_data(reason=reason)

    if status_type == StatusType.trusted_user:
        await state.set_state(AdminStatusStates.trusted_payment_amount)
        await message.answer("Сумма оплаты поручителя. Например: <code>100</code>")
        return
    if status_type == StatusType.guarantor:
        await state.set_state(AdminStatusStates.guarantor_reviews)
        await message.answer("Количество настоящих отзывов. Минимум по правилам: 500+.")
        return

    await state.set_state(AdminStatusStates.evidence)
    await message.answer(
        "Прикрепите доказательства: фото, видео, документ, ссылку или текст.",
        reply_markup=admin_evidence_keyboard(False, status_type),
    )


@router.message(AdminStatusStates.trusted_payment_amount)
async def admin_trusted_payment_amount(message: Message, state: FSMContext) -> None:
    amount = parse_amount(message.text or "")
    if amount is None:
        await message.answer("Введите положительную сумму. Например: <code>100</code>.")
        return
    await state.update_data(trusted_payment_amount=str(amount))
    await state.set_state(AdminStatusStates.trusted_payment_currency)
    await message.answer("Валюта оплаты: USD, KZT, RUB, TON или Telegram Stars.")


@router.message(AdminStatusStates.trusted_payment_currency)
async def admin_trusted_payment_currency(message: Message, state: FSMContext) -> None:
    currency = normalize_currency(message.text or "")
    if not currency:
        await message.answer("Неподдерживаемая валюта.")
        return
    await state.update_data(trusted_payment_currency=currency)
    await state.set_state(AdminStatusStates.trusted_coverage_percent)
    await message.answer("Процент покрытия от 1 до 100. Например: <code>70</code>.")


@router.message(AdminStatusStates.trusted_coverage_percent)
async def admin_trusted_coverage(message: Message, state: FSMContext) -> None:
    try:
        percent = int((message.text or "").strip())
    except ValueError:
        await message.answer("Введите целое число от 1 до 100.")
        return
    if not 1 <= percent <= 100:
        await message.answer("Процент должен быть от 1 до 100.")
        return
    await state.update_data(trusted_coverage_percent=percent)
    await state.set_state(AdminStatusStates.evidence)
    await message.answer(
        "Прикрепите доказательства оплаты или нажмите «Завершить».",
        reply_markup=admin_evidence_keyboard(False, StatusType.trusted_user),
    )


@router.message(AdminStatusStates.guarantor_reviews)
async def admin_guarantor_reviews(message: Message, state: FSMContext) -> None:
    try:
        reviews = int((message.text or "").strip())
    except ValueError:
        await message.answer("Введите число отзывов.")
        return
    await state.update_data(guarantor_reviews=reviews)
    await state.set_state(AdminStatusStates.guarantor_nft_usernames)
    await message.answer("Количество NFT usernames. Минимум по правилам: 5+.")


@router.message(AdminStatusStates.guarantor_nft_usernames)
async def admin_guarantor_nft_usernames(message: Message, state: FSMContext) -> None:
    try:
        count = int((message.text or "").strip())
    except ValueError:
        await message.answer("Введите число.")
        return
    await state.update_data(guarantor_nft_usernames=count)
    await state.set_state(AdminStatusStates.guarantor_nft_gifts)
    await message.answer("Количество NFT gifts. Минимум по правилам: 10+.")


@router.message(AdminStatusStates.guarantor_nft_gifts)
async def admin_guarantor_nft_gifts(message: Message, state: FSMContext) -> None:
    try:
        count = int((message.text or "").strip())
    except ValueError:
        await message.answer("Введите число.")
        return
    await state.update_data(guarantor_nft_gifts=count)
    await state.set_state(AdminStatusStates.evidence)
    await message.answer(
        "Прикрепите материалы проверки гаранта или нажмите «Завершить».",
        reply_markup=admin_evidence_keyboard(False, StatusType.guarantor),
    )


@router.message(AdminStatusStates.evidence)
async def admin_status_evidence(message: Message, state: FSMContext) -> None:
    item = evidence_from_message(message)
    if not item:
        await message.answer("Поддерживаются фото, видео, документы, ссылки и текст.")
        return
    data = await state.get_data()
    status_type = StatusType(data["status_type"])
    evidence = list(data.get("evidence", []))
    evidence.append(asdict(item))
    await state.update_data(evidence=evidence)
    await message.answer(
        f"Материал добавлен. Всего: {len(evidence)}",
        reply_markup=admin_evidence_keyboard(True, status_type),
    )


@router.callback_query(F.data == "admin:evidence:more")
async def admin_evidence_more(callback: CallbackQuery) -> None:
    await callback.message.answer("Отправьте следующий материал.")
    await callback.answer()


@router.callback_query(F.data == "admin:evidence:done")
async def admin_evidence_done(callback: CallbackQuery, state: FSMContext) -> None:
    data = await state.get_data()
    status_type = StatusType(data["status_type"])
    evidence_count = len(data.get("evidence", []))
    reason = data.get("reason") or "не указана"
    await state.set_state(AdminStatusStates.confirm)
    await callback.message.answer(
        "Финальное подтверждение перед выдачей статуса:\n\n"
        f"Статус: {status_label(status_type)}\n"
        f"Цель: <code>{_target_from_dict(data['target']).display}</code>\n"
        f"Причина: {reason}\n"
        f"Доказательства: {evidence_count}",
        reply_markup=admin_confirm_keyboard(),
    )
    await callback.answer()


@router.callback_query(StateFilter(AdminStatusStates.confirm), F.data == "admin:confirm_status")
async def admin_confirm_status(
    callback: CallbackQuery,
    state: FSMContext,
    session: AsyncSession,
    bot: Bot,
) -> None:
    data = await state.get_data()
    status_type = StatusType(data["status_type"])
    evidence = [_evidence_from_dict(item) for item in data.get("evidence", [])]
    payload = StatusPayload(
        target=_target_from_dict(data["target"]),
        status_type=status_type,
        reason=data.get("reason"),
        admin_id=callback.from_user.id,
        evidence=evidence,
        trusted_payment_amount=Decimal(data["trusted_payment_amount"])
        if data.get("trusted_payment_amount")
        else None,
        trusted_payment_currency=data.get("trusted_payment_currency"),
        trusted_coverage_percent=data.get("trusted_coverage_percent"),
        guarantor_reviews=int(data.get("guarantor_reviews") or 0),
        guarantor_nft_usernames=int(data.get("guarantor_nft_usernames") or 0),
        guarantor_nft_gifts=int(data.get("guarantor_nft_gifts") or 0),
    )
    try:
        user, status = await admin_service.set_user_status(session, bot, payload)
    except ValueError as error:
        await callback.answer(str(error), show_alert=True)
        return
    await state.clear()
    await callback.message.answer(
        f"Статус выдан.\n\n"
        f"Пользователь: {escape(user.display_name)}\n"
        f"ID: <code>{user.telegram_user_id or 'неизвестен'}</code>\n"
        f"Статус: {status_label(status.status_type)}"
    )
    await callback.answer()


@router.callback_query(F.data == "admin:remove_status")
async def remove_status_start(callback: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(AdminRemoveStatusStates.target)
    await callback.message.answer("Укажите пользователя, у которого нужно удалить активный статус.")
    await callback.answer()


@router.callback_query(F.data == "admin:delete_evidence")
async def delete_evidence_start(callback: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(AdminDeleteEvidenceStates.evidence_id)
    await callback.message.answer("Укажите ID доказательства, которое нужно удалить.")
    await callback.answer()


@router.message(AdminDeleteEvidenceStates.evidence_id)
async def delete_evidence(message: Message, bot: Bot, session: AsyncSession, state: FSMContext) -> None:
    try:
        evidence_id = int((message.text or "").strip())
    except ValueError:
        await message.answer("ID доказательства должен быть числом.")
        return
    evidence = await session.get(Evidence, evidence_id)
    if not evidence:
        await message.answer("Доказательство не найдено.")
        return
    if evidence.evidence_channel_id and evidence.evidence_message_id:
        try:
            await bot.delete_message(evidence.evidence_channel_id, evidence.evidence_message_id)
        except Exception:
            pass
    await session.delete(evidence)
    await state.clear()
    await message.answer(f"Доказательство #{evidence_id} удалено.")


@router.callback_query(F.data == "admin:change_limit")
async def change_limit_start(callback: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(AdminLimitStates.target)
    await callback.message.answer("Укажите гаранта или поручителя, которому нужно изменить лимит покрытия.")
    await callback.answer()


@router.message(AdminLimitStates.target)
async def change_limit_target(
    message: Message,
    bot: Bot,
    session: AsyncSession,
    state: FSMContext,
) -> None:
    target = _parse_target_from_admin_message(message)
    if not target:
        await message.answer("Не удалось распознать пользователя.")
        return
    try:
        user = await admin_service.resolve_admin_target(session, bot, target)
    except ValueError as error:
        await message.answer(str(error))
        return
    await state.update_data(target_db_id=user.id)
    await state.set_state(AdminLimitStates.amount)
    await message.answer(
        f"Введите новый лимит покрытия для {escape(user.display_name)}.\n"
        "Формат: <code>70 USD</code> или просто <code>70</code>."
    )


@router.message(AdminLimitStates.amount)
async def change_limit_amount(message: Message, session: AsyncSession, state: FSMContext) -> None:
    parts = (message.text or "").strip().split(maxsplit=1)
    if not parts:
        await message.answer("Введите сумму.")
        return
    amount = parse_amount(parts[0])
    if amount is None:
        await message.answer("Введите положительную сумму.")
        return
    currency = normalize_currency(parts[1]) if len(parts) > 1 else "USD"
    if not currency:
        await message.answer("Неподдерживаемая валюта.")
        return
    data = await state.get_data()
    user = await session.get(User, data["target_db_id"])
    if not user:
        await message.answer("Пользователь не найден.")
        await state.clear()
        return
    try:
        status = await admin_service.update_coverage_limit(
            session,
            user,
            amount,
            currency,
            message.from_user.id if message.from_user else 0,
        )
    except ValueError as error:
        await message.answer(str(error))
        return
    await state.clear()
    await message.answer(
        f"Лимит покрытия обновлён: {format_money(status.coverage_limit_amount, status.coverage_currency)}"
    )


@router.message(AdminRemoveStatusStates.target)
async def remove_status_target(
    message: Message,
    bot: Bot,
    session: AsyncSession,
    state: FSMContext,
) -> None:
    target = _parse_target_from_admin_message(message)
    if not target:
        await message.answer("Не удалось распознать пользователя.")
        return
    try:
        user = await admin_service.resolve_admin_target(session, bot, target)
    except ValueError as error:
        await message.answer(str(error))
        return
    await state.update_data(target=_target_to_dict(target), target_db_id=user.id)
    await state.set_state(AdminRemoveStatusStates.confirm)
    await message.answer(
        f"Удалить активный статус у {escape(user.display_name)}?",
        reply_markup=admin_confirm_keyboard(),
    )


@router.callback_query(StateFilter(AdminRemoveStatusStates.confirm), F.data == "admin:confirm_status")
async def remove_status_confirm(callback: CallbackQuery, session: AsyncSession, state: FSMContext) -> None:
    data = await state.get_data()
    user = await session.get(User, data["target_db_id"])
    if not user:
        await callback.answer("Пользователь не найден.", show_alert=True)
        return
    removed = await admin_service.remove_active_status(session, user, callback.from_user.id)
    await state.clear()
    await callback.message.answer("Активный статус удалён." if removed else "Активного статуса не было.")
    await callback.answer()


@router.callback_query(F.data.startswith("admin:list:"))
async def admin_list_status(callback: CallbackQuery, session: AsyncSession) -> None:
    status_type = StatusType(callback.data.rsplit(":", 1)[-1])
    rows = await admin_service.list_users_by_status(session, status_type)
    if not rows:
        await callback.message.answer(f"Список пуст: {status_label(status_type)}")
        await callback.answer()
        return
    lines = [f"<b>{status_label(status_type)}</b>"]
    for user, status in rows:
        coverage = ""
        if status.coverage_limit_amount is not None:
            coverage = f" • лимит {format_money(status.coverage_limit_amount, status.coverage_currency)}"
        lines.append(
            f"• {escape(user.display_name)} | <code>{user.telegram_user_id or 'нет ID'}</code>"
            f" • {format_date(status.issued_at)}{coverage}"
        )
    await callback.message.answer("\n".join(lines))
    await callback.answer()


@router.callback_query(F.data.startswith("admin_report:review:"))
async def report_mark_review(callback: CallbackQuery, session: AsyncSession) -> None:
    report_id = int(callback.data.rsplit(":", 1)[-1])
    report = await report_service.get_report(session, report_id)
    if not report:
        await callback.answer("Жалоба не найдена.", show_alert=True)
        return
    await report_service.set_report_status(session, report, ReportStatus.reviewing, callback.from_user.id)
    await callback.message.answer(f"Жалоба #{report.id} помечена как «на проверке».")
    await callback.answer()


@router.callback_query(F.data.startswith("admin_report:reject:"))
async def report_reject(callback: CallbackQuery, session: AsyncSession) -> None:
    report_id = int(callback.data.rsplit(":", 1)[-1])
    report = await report_service.get_report(session, report_id)
    if not report:
        await callback.answer("Жалоба не найдена.", show_alert=True)
        return
    await report_service.set_report_status(
        session,
        report,
        ReportStatus.rejected,
        callback.from_user.id,
        comment="Отклонено администратором.",
    )
    await callback.message.answer(f"Жалоба #{report.id} отклонена.")
    await callback.answer()


@router.callback_query(F.data.startswith("admin_report:approve:"))
async def report_approve(
    callback: CallbackQuery,
    session: AsyncSession,
    bot: Bot,
) -> None:
    report_id = int(callback.data.rsplit(":", 1)[-1])
    report = await report_service.get_report(session, report_id)
    if not report:
        await callback.answer("Жалоба не найдена.", show_alert=True)
        return
    if not report.accused_user_id:
        await callback.answer("У жалобы нет обвиняемого пользователя.", show_alert=True)
        return
    accused = await session.get(User, report.accused_user_id)
    if not accused or not accused.telegram_user_id:
        await callback.answer("Для выдачи скам-статуса нужен Telegram ID обвиняемого.", show_alert=True)
        return
    evidence = await report_service.get_report_evidence_inputs(session, report.id)
    reason = f"Подтверждено по жалобе #{report.id}. {report.description[:500]}"
    payload = StatusPayload(
        target=ParsedTarget(
            raw=str(accused.telegram_user_id),
            user_id=accused.telegram_user_id,
            username=accused.username,
        ),
        status_type=StatusType.scammer,
        reason=reason,
        admin_id=callback.from_user.id,
        evidence=evidence,
    )
    try:
        await admin_service.set_user_status(session, bot, payload)
    except ValueError as error:
        await callback.answer(str(error), show_alert=True)
        return
    await report_service.set_report_status(session, report, ReportStatus.approved, callback.from_user.id)
    await callback.message.answer(f"Жалоба #{report.id} подтверждена. Статус скамера выдан.")
    await callback.answer()


@router.callback_query(F.data.startswith("admin_report:evidence:"))
async def report_evidence_start(callback: CallbackQuery, state: FSMContext) -> None:
    report_id = int(callback.data.rsplit(":", 1)[-1])
    await state.set_state(AdminReportStates.evidence)
    await state.update_data(report_id=report_id)
    await callback.message.answer(
        f"Отправьте материал для жалобы #{report_id}: фото, видео, документ, ссылку или текст.",
        reply_markup=admin_cancel_keyboard(),
    )
    await callback.answer()


@router.message(AdminReportStates.evidence)
async def report_evidence_add(message: Message, session: AsyncSession, state: FSMContext) -> None:
    item = evidence_from_message(message)
    if not item:
        await message.answer("Поддерживаются фото, видео, документы, ссылки и текст.")
        return
    data = await state.get_data()
    report = await report_service.get_report(session, int(data["report_id"]))
    if not report:
        await message.answer("Жалоба не найдена.")
        await state.clear()
        return
    await create_evidence_record(
        session,
        item,
        related_user_id=report.accused_user_id,
        related_report_id=report.id,
        uploaded_by_admin_id=message.from_user.id if message.from_user else None,
    )
    await message.answer(
        f"Материал добавлен к жалобе #{report.id}.",
        reply_markup=admin_report_evidence_collect_keyboard(),
    )


@router.callback_query(F.data == "admin_report:evidence_more")
async def report_evidence_more(callback: CallbackQuery) -> None:
    await callback.message.answer("Отправьте следующий материал.")
    await callback.answer()


@router.callback_query(F.data == "admin_report:evidence_done")
async def report_evidence_done(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await callback.message.answer("Добавление материалов к жалобе завершено.")
    await callback.answer()


@router.callback_query(F.data.startswith("admin_report:comment:"))
async def report_comment_start(callback: CallbackQuery, state: FSMContext) -> None:
    report_id = int(callback.data.rsplit(":", 1)[-1])
    await state.set_state(AdminReportStates.comment)
    await state.update_data(report_id=report_id)
    await callback.message.answer(f"Напишите комментарий администратора к жалобе #{report_id}.")
    await callback.answer()


@router.message(AdminReportStates.comment)
async def report_comment_save(message: Message, session: AsyncSession, state: FSMContext) -> None:
    comment = (message.text or "").strip()
    if len(comment) < 3:
        await message.answer("Комментарий слишком короткий.")
        return
    data = await state.get_data()
    report = await report_service.get_report(session, int(data["report_id"]))
    if not report:
        await message.answer("Жалоба не найдена.")
        await state.clear()
        return
    await report_service.set_report_status(
        session,
        report,
        report.status,
        message.from_user.id if message.from_user else 0,
        comment=comment,
    )
    await state.clear()
    await message.answer(f"Комментарий добавлен к жалобе #{report.id}.")
