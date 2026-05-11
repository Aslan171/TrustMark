from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from html import escape

from aiogram import Bot
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.config import settings
from app.database.models import Evidence, ReportStatus, ScamReport, User
from app.keyboards.admin_keyboards import admin_report_keyboard
from app.services import user_service
from app.services.evidence_service import EvidenceInput, create_evidence_record
from app.utils.validators import ParsedTarget


@dataclass(slots=True)
class ReportPayload:
    reporter_telegram_user_id: int
    reporter_username: str | None
    reporter_name: str | None
    accused: ParsedTarget
    amount: Decimal | None
    currency: str | None
    description: str
    evidence: list[EvidenceInput]


async def _resolve_or_create_accused(session: AsyncSession, target: ParsedTarget) -> User | None:
    found = await user_service.find_user_by_target(session, target)
    if found:
        return found
    if target.user_id or target.username:
        return await user_service.upsert_user_identity(
            session,
            telegram_user_id=target.user_id,
            username=target.username,
            first_name=target.hidden_name,
        )
    return None


async def create_report(session: AsyncSession, payload: ReportPayload) -> ScamReport:
    reporter = await user_service.upsert_user_identity(
        session,
        telegram_user_id=payload.reporter_telegram_user_id,
        username=payload.reporter_username,
        first_name=payload.reporter_name,
    )
    accused = await _resolve_or_create_accused(session, payload.accused)
    report = ScamReport(
        reporter_user_id=reporter.id,
        accused_user_id=accused.id if accused else None,
        accused_raw=payload.accused.display,
        amount=payload.amount,
        currency=payload.currency,
        description=payload.description,
        status=ReportStatus.new if payload.evidence else ReportStatus.insufficient,
    )
    session.add(report)
    await session.flush()

    for item in payload.evidence:
        await create_evidence_record(
            session,
            item,
            related_user_id=accused.id if accused else None,
            related_report_id=report.id,
        )
    return report


def format_admin_report(report: ScamReport, reporter: User, accused: User | None, evidence_count: int) -> str:
    amount = f"{report.amount} {report.currency}" if report.amount and report.currency else "не указана"
    reporter_line = f"{escape(reporter.display_name)}\nID: <code>{reporter.telegram_user_id}</code>"
    accused_id = accused.telegram_user_id if accused else "неизвестен"
    accused_name = escape(accused.display_name) if accused else escape(report.accused_raw or "неизвестен")
    accused_line = f"{accused_name}\nID: <code>{accused_id}</code>"
    return (
        f"🚨 <b>Жалоба #{report.id}</b>\n\n"
        f"<b>Пострадавший:</b>\n{reporter_line}\n\n"
        f"<b>Обвиняемый:</b>\n{accused_line}\n\n"
        f"<b>Сумма:</b>\n{escape(amount)}\n\n"
        f"<b>Описание:</b>\n{escape(report.description)}\n\n"
        f"<b>Доказательства:</b> {evidence_count}\n\n"
        "Главное правило: для серьёзной жалобы нужно полное видео сделки от начала до конца без обрезок."
    )


async def notify_admin_chat(session: AsyncSession, bot: Bot, report: ScamReport) -> None:
    if settings.admin_chat_id is None:
        return
    result = await session.execute(
        select(ScamReport)
        .options(
            selectinload(ScamReport.reporter),
            selectinload(ScamReport.accused),
            selectinload(ScamReport.evidence),
        )
        .where(ScamReport.id == report.id),
    )
    loaded_report = result.scalar_one()
    text = format_admin_report(
        loaded_report,
        loaded_report.reporter,
        loaded_report.accused,
        len(loaded_report.evidence),
    )
    sent = await bot.send_message(
        settings.admin_chat_id,
        text,
        reply_markup=admin_report_keyboard(loaded_report.id, loaded_report.accused_user_id),
    )
    report.admin_chat_message_id = sent.message_id

    for item in loaded_report.evidence:
        caption = f"Доказательство к жалобе #{loaded_report.id}: {escape(item.title or item.file_type)}"
        if item.file_type == "photo" and item.telegram_file_id:
            await bot.send_photo(settings.admin_chat_id, item.telegram_file_id, caption=caption)
        elif item.file_type == "video" and item.telegram_file_id:
            await bot.send_video(settings.admin_chat_id, item.telegram_file_id, caption=caption)
        elif item.file_type == "document" and item.telegram_file_id:
            await bot.send_document(settings.admin_chat_id, item.telegram_file_id, caption=caption)
        else:
            body = item.external_url or item.text_content or "Материал без текста"
            await bot.send_message(settings.admin_chat_id, f"{caption}\n\n{escape(body)}")


async def get_report(session: AsyncSession, report_id: int) -> ScamReport | None:
    result = await session.execute(select(ScamReport).where(ScamReport.id == report_id))
    return result.scalar_one_or_none()


async def set_report_status(
    session: AsyncSession,
    report: ScamReport,
    status: ReportStatus,
    admin_id: int,
    comment: str | None = None,
) -> None:
    report.status = status
    report.assigned_admin_id = admin_id
    if comment:
        report.admin_comment = comment
    await session.flush()


async def get_report_evidence_inputs(session: AsyncSession, report_id: int) -> list[EvidenceInput]:
    result = await session.execute(
        select(Evidence).where(Evidence.related_report_id == report_id).order_by(Evidence.created_at.asc()),
    )
    items: list[EvidenceInput] = []
    for evidence in result.scalars().all():
        items.append(
            EvidenceInput(
                file_type=evidence.file_type,
                title=evidence.title,
                telegram_file_id=evidence.telegram_file_id,
                text_content=evidence.text_content,
                external_url=evidence.external_url,
            ),
        )
    return items
