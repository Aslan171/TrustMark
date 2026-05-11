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
    background: tuple[int, int, int] = (12, 15, 22)
    panel: tuple[int, int, int] = (22, 27, 38)
    panel_alt: tuple[int, int, int] = (31, 38, 52)
    text: tuple[int, int, int] = (238, 242, 247)
    muted: tuple[int, int, int] = (150, 162, 178)
    accent: tuple[int, int, int] = (0, 188, 160)
    warning: tuple[int, int, int] = (245, 158, 11)
    danger: tuple[int, int, int] = (239, 68, 68)


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
        StatusType.trusted_user: (76, 201, 240),
        StatusType.unknown: palette.muted,
        StatusType.suspicious: palette.warning,
        StatusType.scammer: palette.danger,
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
    draw.ellipse((0, 0, size - 1, size - 1), fill=(31, 38, 52), outline=palette.accent, width=4)
    source = user.username or user.first_name or str(user.telegram_user_id or "?")
    initials = "".join(part[0] for part in source.replace("@", "").split()[:2]).upper()[:2] or "TM"
    font = _font(48, bold=True)
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
    width, height = 1200, 680
    image = Image.new("RGB", (width, height), palette.background)
    draw = ImageDraw.Draw(image)

    draw.rounded_rectangle((42, 42, width - 42, height - 42), radius=28, fill=palette.panel)
    draw.rounded_rectangle((70, 500, width - 70, 610), radius=20, fill=palette.panel_alt)

    current_status = status.status_type if status else StatusType.unknown
    risk = risk_for_status(current_status)
    accent = _status_color(current_status)
    draw.rectangle((42, 42, 58, height - 42), fill=accent)

    avatar_size = 168
    avatar = await _load_avatar(bot, user, avatar_size) or _fallback_avatar(user, avatar_size, palette)
    image.paste(avatar, (92, 92), avatar)

    title = user.display_name
    title_font = _fit_text(draw, title, 610, 52, bold=True, min_size=30)
    draw.text((292, 98), title, font=title_font, fill=palette.text)
    draw.text((294, 166), f"Telegram ID: {user.telegram_user_id or 'unknown'}", font=_font(28), fill=palette.muted)
    link = profile_link(user) or settings.bot_owner_link
    draw.text((294, 210), link, font=_font(25), fill=palette.accent)

    status_text = status_label(current_status).replace("✅ ", "").replace("🛡️ ", "").replace("🟠 ", "").replace("⛔ ", "").replace("⚪ ", "")
    draw.rounded_rectangle((292, 278, 820, 370), radius=18, fill=(17, 21, 30), outline=accent, width=2)
    draw.text((322, 298), "STATUS", font=_font(22, bold=True), fill=palette.muted)
    draw.text((322, 326), status_text, font=_fit_text(draw, status_text, 450, 32, bold=True), fill=accent)

    draw.rounded_rectangle((850, 278, 1088, 370), radius=18, fill=(17, 21, 30), outline=accent, width=2)
    draw.text((880, 298), "RISK", font=_font(22, bold=True), fill=palette.muted)
    draw.text((880, 324), f"{risk}%", font=_font(42, bold=True), fill=accent)

    coverage = "нет лимита"
    if status and status.coverage_limit_amount is not None:
        coverage = f"до {format_money(status.coverage_limit_amount, status.coverage_currency)}"
    draw.text((92, 418), "Лимит покрытия", font=_font(23), fill=palette.muted)
    draw.text((92, 450), coverage, font=_fit_text(draw, coverage, 420, 34, bold=True), fill=palette.text)
    draw.text((540, 418), "Дата выдачи", font=_font(23), fill=palette.muted)
    draw.text((540, 450), format_date(status.issued_at if status else None), font=_font(34, bold=True), fill=palette.text)

    warning = "Username может быть изменен. Основная проверка идет по Telegram ID."
    draw.text((96, 535), warning, font=_font(28, bold=True), fill=palette.warning)
    draw.text((96, 575), f"TrustMark • creator @{settings.bot_owner_username}", font=_font(22), fill=palette.muted)

    if qrcode:
        qr = qrcode.make(link).convert("RGB").resize((150, 150))
        qr = ImageOps.expand(qr, border=10, fill="white")
        image.paste(qr, (width - 250, 88))
    else:
        draw.rounded_rectangle((width - 270, 92, width - 82, 238), radius=18, fill=(17, 21, 30))
        draw.text((width - 244, 126), "PROFILE", font=_font(24, bold=True), fill=palette.muted)
        draw.text((width - 244, 164), "LINK", font=_font(42, bold=True), fill=palette.accent)

    output = BytesIO()
    image.save(output, format="PNG", optimize=True)
    return output.getvalue()
