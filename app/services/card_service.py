from __future__ import annotations

from dataclasses import dataclass
from io import BytesIO
from pathlib import Path

from aiogram import Bot
from PIL import Image, ImageDraw, ImageFont, ImageOps

from app.config import settings
from app.database.models import Status, StatusType, User
from app.utils.formatters import format_date, format_money, profile_link, risk_for_status, status_label

try:
    import qrcode
except ImportError:  # pragma: no cover - optional runtime enhancement
    qrcode = None


@dataclass(slots=True)
class CardPalette:
    background: tuple[int, int, int] = (7, 10, 16)
    panel: tuple[int, int, int] = (31, 38, 52)
    panel_alt: tuple[int, int, int] = (45, 54, 72)
    text: tuple[int, int, int] = (255, 255, 255)
    muted: tuple[int, int, int] = (205, 216, 230)
    accent: tuple[int, int, int] = (18, 232, 190)
    warning: tuple[int, int, int] = (255, 196, 77)
    danger: tuple[int, int, int] = (255, 76, 76)


def _font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    candidates = [
        "C:/Windows/Fonts/arialbd.ttf" if bold else "C:/Windows/Fonts/arial.ttf",
        "C:/Windows/Fonts/segoeuib.ttf" if bold else "C:/Windows/Fonts/segoeui.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
        if bold
        else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    ]
    for candidate in candidates:
        if Path(candidate).exists():
            return ImageFont.truetype(candidate, size=size)
    return ImageFont.load_default()


def _rounded_mask(size: tuple[int, int], radius: int) -> Image.Image:
    mask = Image.new("L", size, 0)
    draw = ImageDraw.Draw(mask)
    draw.rounded_rectangle((0, 0, size[0], size[1]), radius=radius, fill=255)
    return mask


def _status_color(status_type: StatusType) -> tuple[int, int, int]:
    palette = CardPalette()
    return {
        StatusType.guarantor: palette.accent,
        StatusType.trusted_user: (92, 214, 255),
        StatusType.unknown: (224, 233, 245),
        StatusType.suspicious: palette.warning,
        StatusType.scammer: palette.danger,
    }[status_type]


def _status_card_title(status_type: StatusType) -> str:
    return {
        StatusType.guarantor: "Гарант",
        StatusType.trusted_user: "Поручитель",
        StatusType.unknown: "Не найден в базе",
        StatusType.suspicious: "Подозрительная личность",
        StatusType.scammer: "Подтвержденный скамер",
    }[status_type]


def _fit_text(
    draw: ImageDraw.ImageDraw,
    text: str,
    max_width: int,
    font_size: int,
    bold: bool = False,
    min_size: int = 18,
) -> ImageFont.ImageFont:
    size = font_size
    while size > min_size:
        font = _font(size, bold=bold)
        bbox = draw.textbbox((0, 0), text, font=font)
        if bbox[2] - bbox[0] <= max_width:
            return font
        size -= 2
    return _font(min_size, bold=bold)


async def _load_avatar(bot: Bot, user: User, size: int) -> Image.Image | None:
    if not user.telegram_user_id:
        return None
    try:
        photos = await bot.get_user_profile_photos(user.telegram_user_id, limit=1)
        if not photos.photos:
            return None
        file_id = photos.photos[0][-1].file_id
        buffer = BytesIO()
        await bot.download(file_id, destination=buffer)
        buffer.seek(0)
        avatar = Image.open(buffer).convert("RGB")
        avatar = ImageOps.fit(avatar, (size, size))
        avatar.putalpha(_rounded_mask((size, size), size // 2))
        return avatar
    except Exception:
        return None


def _fallback_avatar(user: User, size: int, palette: CardPalette) -> Image.Image:
    avatar = Image.new("RGBA", (size, size), palette.panel_alt + (255,))
    draw = ImageDraw.Draw(avatar)
    draw.ellipse((0, 0, size - 1, size - 1), fill=(45, 54, 72), outline=palette.accent, width=7)
    source = user.username or user.first_name or str(user.telegram_user_id or "?")
    initials = "".join(part[0] for part in source.replace("@", "").split()[:2]).upper()[:2] or "TM"
    font = _font(max(54, size // 3), bold=True)
    bbox = draw.textbbox((0, 0), initials, font=font)
    draw.text(
        ((size - (bbox[2] - bbox[0])) / 2, (size - (bbox[3] - bbox[1])) / 2 - 4),
        initials,
        font=font,
        fill=palette.text,
    )
    return avatar


async def generate_user_card(bot: Bot, user: User, status: Status | None) -> bytes:
    palette = CardPalette()
    width, height = 1500, 860
    image = Image.new("RGB", (width, height), palette.background)
    draw = ImageDraw.Draw(image)

    current_status = status.status_type if status else StatusType.unknown
    risk = risk_for_status(current_status)
    accent = _status_color(current_status)

    draw.rounded_rectangle((34, 34, width - 34, height - 34), radius=32, fill=palette.panel)
    draw.rectangle((34, 34, 58, height - 34), fill=accent)
    draw.rounded_rectangle((78, 78, width - 78, 380), radius=26, fill=(38, 47, 64))

    draw.text((96, 72), "TRUSTMARK", font=_font(34, bold=True), fill=accent)
    draw.text(
        (width - 350, 82),
        f"creator @{settings.bot_owner_username}",
        font=_font(28, bold=True),
        fill=palette.muted,
    )

    avatar_size = 230
    avatar = await _load_avatar(bot, user, avatar_size) or _fallback_avatar(user, avatar_size, palette)
    image.paste(avatar, (102, 132), avatar)

    title = user.display_name
    title_font = _fit_text(draw, title, 760, 74, bold=True, min_size=44)
    draw.text((368, 142), title, font=title_font, fill=palette.text)
    draw.text(
        (370, 238),
        f"Telegram ID: {user.telegram_user_id or 'unknown'}",
        font=_font(40, bold=True),
        fill=palette.muted,
    )
    link = profile_link(user) or settings.bot_owner_link
    draw.text((370, 300), link, font=_fit_text(draw, link, 720, 34, bold=True), fill=accent)

    status_text = _status_card_title(current_status)
    draw.rounded_rectangle((96, 430, 900, 590), radius=24, fill=(18, 23, 34), outline=accent, width=4)
    draw.text((132, 462), "СТАТУС", font=_font(32, bold=True), fill=palette.muted)
    draw.text(
        (132, 505),
        status_text,
        font=_fit_text(draw, status_text, 710, 58, bold=True, min_size=34),
        fill=accent,
    )

    draw.rounded_rectangle((940, 430, 1378, 590), radius=24, fill=(18, 23, 34), outline=accent, width=4)
    draw.text((976, 462), "РИСК СДЕЛКИ", font=_font(32, bold=True), fill=palette.muted)
    draw.text((976, 502), f"{risk}%", font=_font(76, bold=True), fill=accent)

    coverage = "нет лимита"
    if status and status.coverage_limit_amount is not None:
        coverage = f"до {format_money(status.coverage_limit_amount, status.coverage_currency)}"
    draw.rounded_rectangle((96, 632, 710, 748), radius=22, fill=palette.panel_alt)
    draw.text((132, 654), "ЛИМИТ ПОКРЫТИЯ", font=_font(28, bold=True), fill=palette.muted)
    draw.text(
        (132, 694),
        coverage,
        font=_fit_text(draw, coverage, 520, 46, bold=True, min_size=30),
        fill=palette.text,
    )
    draw.rounded_rectangle((752, 632, 1378, 748), radius=22, fill=palette.panel_alt)
    draw.text((788, 654), "ДАТА ВЫДАЧИ", font=_font(28, bold=True), fill=palette.muted)
    draw.text(
        (788, 694),
        format_date(status.issued_at if status else None),
        font=_font(46, bold=True),
        fill=palette.text,
    )

    warning = "Username может быть изменен. Главная проверка идет по Telegram ID."
    draw.text((96, 784), warning, font=_font(34, bold=True), fill=palette.warning)

    if qrcode:
        qr = qrcode.make(link).convert("RGB").resize((190, 190))
        qr = ImageOps.expand(qr, border=12, fill="white")
        image.paste(qr, (width - 314, 140))
    else:
        draw.rounded_rectangle((width - 320, 146, width - 96, 330), radius=22, fill=(18, 23, 34))
        draw.text((width - 286, 190), "PROFILE", font=_font(30, bold=True), fill=palette.muted)
        draw.text((width - 286, 232), "LINK", font=_font(54, bold=True), fill=palette.accent)

    output = BytesIO()
    image.save(output, format="PNG", optimize=True)
    return output.getvalue()
