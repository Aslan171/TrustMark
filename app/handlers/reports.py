from __future__ import annotations

from dataclasses import asdict
from html import escape

from aiogram import Bot, F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from sqlalchemy.ext.asyncio import AsyncSession

from app.keyboards.user_keyboards import report_confirm_keyboard, report_evidence_keyboard
from app.services.evidence_service import EvidenceInput, evidence_from_message
from app.services.report_service import ReportPayload, create_report, notify_admin_chat
from app.states.report_states import ReportStates
from app.utils.currencies import SUPPORTED_CURRENCIES, normalize_currency, parse_amount
from app.utils.validators import ParsedTarget, parse_forwarded_user, parse_target_text

router = Router(name="reports")


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


async def _start_report(message: Message, state: FSMContext) -> None:
    await state.clear()
    await state.set_state(ReportStates.accused)
    await state.update_data(evidence=[])
    await message.answer(
        "🧾 <b>Подача жалобы</b>\n\n"
        "Кто заскамил? Укажите Telegram ID, @username или перешлите сообщение пользователя.\n\n"
        "Важно: без доказательств жалоба будет считаться недостаточной."
    )


@router.callback_query(F.data == "report:start")
async def start_report_callback(callback: CallbackQuery, state: FSMContext) -> None:
    await _start_report(callback.message, state)
    await callback.answer()


@router.message(F.text == "🧾 Подать жалобу")
async def start_report_message(message: Message, state: FSMContext) -> None:
    await _start_report(message, state)


@router.callback_query(F.data == "report:cancel")
async def cancel_report_callback(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await callback.message.answer("Подача жалобы отменена.")
    await callback.answer()


@router.message(ReportStates.accused)
async def report_accused(message: Message, state: FSMContext) -> None:
    target = parse_forwarded_user(message) or parse_target_text(message.text)
    if not target:
        await message.answer("Не удалось распознать пользователя. Укажите ID, @username или перешлите сообщение.")
        return
    await state.update_data(accused=_target_to_dict(target))
    await state.set_state(ReportStates.amount)
    await message.answer("Укажите сумму ущерба числом. Если суммы нет, напишите <code>пропустить</code>.")


@router.message(ReportStates.amount)
async def report_amount(message: Message, state: FSMContext) -> None:
    text = (message.text or "").strip()
    if text.casefold() in {"пропустить", "skip", "-"}:
        await state.update_data(amount=None)
    else:
        amount = parse_amount(text)
        if amount is None:
            await message.answer("Сумма должна быть положительным числом. Например: <code>1360</code>.")
            return
        await state.update_data(amount=str(amount))
    await state.set_state(ReportStates.currency)
    await message.answer(
        "Укажите валюту:\n" + "\n".join(f"• {currency}" for currency in SUPPORTED_CURRENCIES),
    )


@router.message(ReportStates.currency)
async def report_currency(message: Message, state: FSMContext) -> None:
    text = (message.text or "").strip()
    currency = normalize_currency(text)
    if not currency:
        await message.answer("Поддерживаются только: " + ", ".join(SUPPORTED_CURRENCIES))
        return
    await state.update_data(currency=currency)
    await state.set_state(ReportStates.description)
    await message.answer("Опишите ситуацию: что покупали, как шла сделка, где произошёл обман.")


@router.message(ReportStates.description)
async def report_description(message: Message, state: FSMContext) -> None:
    description = (message.text or "").strip()
    if len(description) < 20:
        await message.answer("Описание слишком короткое. Добавьте детали сделки.")
        return
    await state.update_data(description=description)
    await state.set_state(ReportStates.evidence)
    await message.answer(
        "Прикрепите доказательства: видео, фото, документ, ссылку или текст.\n\n"
        "Для серьёзной жалобы нужно полное видео сделки от начала до конца без обрезок.",
        reply_markup=report_evidence_keyboard(has_evidence=False),
    )


@router.message(ReportStates.evidence)
async def report_evidence(message: Message, state: FSMContext) -> None:
    item = evidence_from_message(message)
    if not item:
        await message.answer("Поддерживаются фото, видео, документы, ссылки и текст.")
        return

    data = await state.get_data()
    evidence = list(data.get("evidence", []))
    evidence.append(asdict(item))
    await state.update_data(evidence=evidence)
    await message.answer(
        f"Материал добавлен. Всего доказательств: {len(evidence)}",
        reply_markup=report_evidence_keyboard(has_evidence=True),
    )


@router.callback_query(F.data == "report:evidence:more")
async def report_evidence_more(callback: CallbackQuery) -> None:
    await callback.message.answer("Отправьте следующий материал.")
    await callback.answer()


@router.callback_query(F.data == "report:evidence:done")
async def report_evidence_done(callback: CallbackQuery, state: FSMContext) -> None:
    data = await state.get_data()
    evidence = data.get("evidence", [])
    if not evidence:
        await callback.answer("Нужен хотя бы один материал.", show_alert=True)
        return
    await state.set_state(ReportStates.confirm)
    accused = _target_from_dict(data["accused"])
    amount = data.get("amount") or "не указана"
    await callback.message.answer(
        "Проверьте жалобу перед отправкой:\n\n"
        f"Обвиняемый: <code>{accused.display}</code>\n"
        f"Сумма: {amount} {data.get('currency')}\n"
        f"Доказательства: {len(evidence)}\n\n"
        f"Описание:\n{escape(data.get('description') or '')}",
        reply_markup=report_confirm_keyboard(),
    )
    await callback.answer()


@router.callback_query(F.data == "report:confirm")
async def report_confirm(
    callback: CallbackQuery,
    state: FSMContext,
    session: AsyncSession,
    bot: Bot,
) -> None:
    if callback.from_user is None:
        return
    data = await state.get_data()
    evidence = [_evidence_from_dict(item) for item in data.get("evidence", [])]
    payload = ReportPayload(
        reporter_telegram_user_id=callback.from_user.id,
        reporter_username=callback.from_user.username,
        reporter_name=callback.from_user.full_name,
        accused=_target_from_dict(data["accused"]),
        amount=parse_amount(data["amount"]) if data.get("amount") else None,
        currency=data.get("currency"),
        description=data["description"],
        evidence=evidence,
    )
    report = await create_report(session, payload)
    await notify_admin_chat(session, bot, report)
    await state.clear()
    await callback.message.answer(
        f"Жалоба #{report.id} отправлена администрации.\n\n"
        "Если материалов недостаточно, заявка может быть отклонена."
    )
    await callback.answer()
