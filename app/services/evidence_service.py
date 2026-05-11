from __future__ import annotations

import logging
from dataclasses import dataclass
from html import escape

from aiogram import Bot
from aiogram.types import Message
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database.models import Evidence
from app.utils.validators import is_valid_link

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class EvidenceInput:
    file_type: str
    title: str | None = None
    telegram_file_id: str | None = None
    text_content: str | None = None
    external_url: str | None = None


def evidence_from_message(message: Message) -> EvidenceInput | None:
    if message.photo:
        return EvidenceInput(
            file_type="photo",
            title=message.caption or "Фото",
            telegram_file_id=message.photo[-1].file_id,
            text_content=message.caption,
        )
    if message.video:
        return EvidenceInput(
            file_type="video",
            title=message.caption or "Видео сделки",
            telegram_file_id=message.video.file_id,
            text_content=message.caption,
        )
    if message.document:
        return EvidenceInput(
            file_type="document",
            title=message.document.file_name or message.caption or "Документ",
            telegram_file_id=message.document.file_id,
            text_content=message.caption,
        )
    if message.text:
        text = message.text.strip()
        if is_valid_link(text):
            return EvidenceInput(file_type="link", title="Ссылка", external_url=text, text_content=text)
        return EvidenceInput(file_type="text", title="Текст", text_content=text)
    return None


def evidence_channel_url(message_id: int) -> str | None:
    public_username = settings.public_evidence_username
    if public_username:
        return f"https://t.me/{public_username}/{message_id}"

    channel_id = settings.evidence_channel_id
    if isinstance(channel_id, int) and str(channel_id).startswith("-100"):
        return f"https://t.me/c/{str(abs(channel_id))[3:]}/{message_id}"
    return None


async def publish_evidence_item(
    bot: Bot,
    item: EvidenceInput,
    caption: str,
) -> tuple[int | None, str | None]:
    if settings.evidence_channel_id is None:
        logger.warning("EVIDENCE_CHANNEL_ID is empty; evidence will be saved without channel URL")
        return None, None

    channel_id = settings.evidence_channel_id
    safe_caption = caption[:1024]
    if item.file_type == "photo" and item.telegram_file_id:
        sent = await bot.send_photo(channel_id, item.telegram_file_id, caption=safe_caption)
    elif item.file_type == "video" and item.telegram_file_id:
        sent = await bot.send_video(channel_id, item.telegram_file_id, caption=safe_caption)
    elif item.file_type == "document" and item.telegram_file_id:
        sent = await bot.send_document(channel_id, item.telegram_file_id, caption=safe_caption)
    else:
        body = item.external_url or item.text_content or "Материал без текста"
        sent = await bot.send_message(channel_id, f"{caption}\n\n{escape(body)}")

    return sent.message_id, evidence_channel_url(sent.message_id)


async def create_evidence_record(
    session: AsyncSession,
    item: EvidenceInput,
    *,
    related_user_id: int | None = None,
    related_status_id: int | None = None,
    related_report_id: int | None = None,
    uploaded_by_admin_id: int | None = None,
    channel_message_id: int | None = None,
    channel_url: str | None = None,
) -> Evidence:
    evidence = Evidence(
        related_user_id=related_user_id,
        related_status_id=related_status_id,
        related_report_id=related_report_id,
        uploaded_by_admin_id=uploaded_by_admin_id,
        telegram_file_id=item.telegram_file_id,
        file_type=item.file_type,
        title=item.title,
        text_content=item.text_content,
        external_url=item.external_url,
        evidence_channel_id=settings.evidence_channel_id if isinstance(settings.evidence_channel_id, int) else None,
        evidence_message_id=channel_message_id,
        evidence_message_url=channel_url,
    )
    session.add(evidence)
    await session.flush()
    return evidence


async def publish_and_store_evidence(
    session: AsyncSession,
    bot: Bot,
    items: list[EvidenceInput],
    *,
    caption: str,
    related_user_id: int | None = None,
    related_status_id: int | None = None,
    related_report_id: int | None = None,
    uploaded_by_admin_id: int | None = None,
) -> list[Evidence]:
    saved: list[Evidence] = []
    for index, item in enumerate(items, start=1):
        item_caption = f"{caption}\n\nМатериал #{index}: {escape(item.title or item.file_type)}"
        message_id, url = await publish_evidence_item(bot, item, item_caption)
        saved.append(
            await create_evidence_record(
                session,
                item,
                related_user_id=related_user_id,
                related_status_id=related_status_id,
                related_report_id=related_report_id,
                uploaded_by_admin_id=uploaded_by_admin_id,
                channel_message_id=message_id,
                channel_url=url,
            ),
        )
    return saved

