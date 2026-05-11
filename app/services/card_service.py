from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import UTC, datetime
from io import BytesIO
from pathlib import Path

from aiogram import Bot
from PIL import Image, ImageDraw, ImageFont, ImageOps

from app.config import settings
from app.database.models import Status, StatusType, User
from app.utils.formatters import format_date, format_money, profile_link, risk_for_status

try:
    import qrcode
except ImportError:  # pragma: no cover - optional runtime enhancement
    qrcode = None


@dataclass(slots=True)
class CardPalette:
    background: tuple[int, int, int] = (6, 9, 15)
    panel: tuple[int, int, int] = (24, 31, 44)
    panel_light: tuple[int, int, int] = (39, 49, 68)
    panel_dark: tuple[int, int, int] = (13, 18, 28)
    text: tuple[int, int, int] = (255, 255, 255)
    muted: tuple[int, int, int] = (216, 226, 240)
    soft: tuple[int, int, int] = (148, 163, 184)
    accent: tuple[int, int, int] = (26, 235, 196)
    warning: tuple[int, int, int] = (255, 203, 82)
    danger: tuple[int, int, int] = (255, 83, 83)


AVATAR_GRADIENTS: tuple[tuple[tuple[int, int, int], tuple[int, int, int]], ...] = (
    ((52, 152, 255), (78, 219, 206)),
    ((255, 137, 69), (255, 84, 122)),
    ((145, 105, 255), (67, 191, 255)),
    ((78, 205, 115), (19, 176, 143)),
    ((255, 187, 65), (255, 112, 67)),
    ((236, 92, 188), (127, 98, 255)),
)


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


def _fit_text(
    draw: ImageDraw.ImageDraw,
    text: str,
    max_width: int,
    font_size: int,
    bold: bool = False,
    min_size: int = 24,
) -> ImageFont.ImageFont:
    size = font_size
    while size > min_size:
        font = _font(size, bold=bold)
        bbox = draw.textbbox((0, 0), text, font=font)
        if bbox[2] - bbox[0] <= max_width:
            return font
        size -= 2
    return _font(min_size, bold=bold)


def _status_color(status_type: StatusType) -> tuple[int, int, int]:
    palette = CardPalette()
    return {
        StatusType.guarantor: palette.accent,
        StatusType.trusted_user: (86, 214, 255),
        StatusType.unknown: (232, 238, 247),
        StatusType.suspicious: palette.warning,
        StatusType.scammer: palette.danger,
    }[status_type]


def _status_title(status_type: StatusType) -> str:
    return {
        StatusType.guarantor: "Гарант",
        StatusType.trusted_user: "Поручитель",
        StatusType.unknown: "Не найден в базе",
        StatusType.suspicious: "Подозрительная личность",
        StatusType.scammer: "Подтвержденный скамер",
    }[status_type]


def _circle_mask(size: int) -> Image.Image:
    mask = Image.new("L", (size, size), 0)
    draw = ImageDraw.Draw(mask)
    draw.ellipse((0, 0, size - 1, size - 1), fill=255)
    return mask


def _initials(label: str | None) -> str:
    if not label:
        return "?"
    cleaned = label.replace("@", " ").replace("_", " ").strip()
    if not cleaned:
        return "?"
    parts = [part for part in cleaned.split() if part]
    if not parts:
        return cleaned[:1].upper()
    return "".join(part[:1] for part in parts[:2]).upper()


def _gradient_avatar(label: str | None, size: int, palette: CardPalette) -> Image.Image:
    seed = label or "TrustMark"
    digest = hashlib.sha256(seed.encode("utf-8")).digest()
    top, bottom = AVATAR_GRADIENTS[digest[0] % len(AVATAR_GRADIENTS)]

    avatar = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    pixels = avatar.load()
    for y in range(size):
        ratio = y / max(size - 1, 1)
        color = tuple(int(top[i] * (1 - ratio) + bottom[i] * ratio) for i in range(3))
        for x in range(size):
            pixels[x, y] = (*color, 255)

    avatar.putalpha(_circle_mask(size))
    draw = ImageDraw.Draw(avatar)
    draw.ellipse((5, 5, size - 6, size - 6), outline=(255, 255, 255, 155), width=5)

    text = _initials(label)
    font = _font(max(72, size // 3), bold=True)
    bbox = draw.textbbox((0, 0), text, font=font)
    draw.text(
        ((size - (bbox[2] - bbox[0])) / 2, (size - (bbox[3] - bbox[1])) / 2 - 8),
        text,
        font=font,
        fill=palette.text,
    )
    return avatar


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
        avatar.putalpha(_circle_mask(size))
        return avatar
    except Exception:
        return None


def _draw_label(draw: ImageDraw.ImageDraw, xy: tuple[int, int], text: str, palette: CardPalette) -> None:
    draw.text(xy, text, font=_font(30, bold=True), fill=palette.soft)


def _draw_metric(
    draw: ImageDraw.ImageDraw,
    box: tuple[int, int, int, int],
    label: str,
    value: str,
    palette: CardPalette,
    value_color: tuple[int, int, int] | None = None,
    max_width: int | None = None,
) -> None:
    x1, y1, x2, y2 = box
    draw.rounded_rectangle(box, radius=24, fill=palette.panel_dark)
    draw.text((x1 + 36, y1 + 28), label, font=_font(30, bold=True), fill=palette.soft)
    value_font = _fit_text(
        draw,
        value,
        max_width or (x2 - x1 - 72),
        58,
        bold=True,
        min_size=32,
    )
    draw.text((x1 + 36, y1 + 72), value, font=value_font, fill=value_color or palette.text)


def _draw_qr_or_link_badge(
    image: Image.Image,
    draw: ImageDraw.ImageDraw,
    link: str,
    palette: CardPalette,
    x: int,
    y: int,
) -> None:
    if qrcode:
        qr = qrcode.make(link).convert("RGB").resize((198, 198))
        qr = ImageOps.expand(qr, border=12, fill="white")
        image.paste(qr, (x, y))
        return

    draw.rounded_rectangle((x, y, x + 222, y + 222), radius=26, fill=palette.panel_dark)
    draw.text((x + 34, y + 58), "PROFILE", font=_font(30, bold=True), fill=palette.soft)
    draw.text((x + 34, y + 104), "LINK", font=_font(58, bold=True), fill=palette.accent)


def _render_card(
    *,
    title: str,
    telegram_id: str,
    link: str,
    avatar: Image.Image,
    status_type: StatusType,
    coverage: str,
    issued_at: str,
) -> bytes:
    palette = CardPalette()
    width, height = 1600, 920
    status_color = _status_color(status_type)
    risk = risk_for_status(status_type)

    image = Image.new("RGB", (width, height), palette.background)
    draw = ImageDraw.Draw(image)

    draw.rounded_rectangle((34, 34, width - 34, height - 34), radius=36, fill=palette.panel)
    draw.rectangle((34, 34, 64, height - 34), fill=status_color)
    draw.rounded_rectangle((86, 86, width - 86, 420), radius=30, fill=palette.panel_light)

    draw.text((112, 92), "TRUSTMARK", font=_font(42, bold=True), fill=status_color)
    draw.text(
        (width - 410, 102),
        f"creator @{settings.bot_owner_username}",
        font=_font(30, bold=True),
        fill=palette.muted,
    )

    image.paste(avatar, (118, 166), avatar)

    title_font = _fit_text(draw, title, 820, 82, bold=True, min_size=44)
    draw.text((402, 162), title, font=title_font, fill=palette.text)
    draw.text((406, 268), f"Telegram ID: {telegram_id}", font=_font(44, bold=True), fill=palette.muted)
    draw.text((406, 326), link, font=_fit_text(draw, link, 760, 38, bold=True), fill=status_color)

    _draw_qr_or_link_badge(image, draw, link, palette, width - 342, 156)

    _draw_metric(
        draw,
        (112, 478, 936, 654),
        "СТАТУС",
        _status_title(status_type),
        palette,
        value_color=status_color,
        max_width=720,
    )
    _draw_metric(
        draw,
        (984, 478, 1488, 654),
        "РИСК СДЕЛКИ",
        f"{risk}%",
        palette,
        value_color=status_color,
    )
    _draw_metric(draw, (112, 704, 748, 820), "ЛИМИТ ПОКРЫТИЯ", coverage, palette, max_width=540)
    _draw_metric(draw, (792, 704, 1488, 820), "ДАТА ПРОВЕРКИ", issued_at, palette, max_width=600)

    warning = "Username может быть изменен. Главная проверка идет по Telegram ID."
    draw.text((112, 850), warning, font=_font(36, bold=True), fill=palette.warning)

    output = BytesIO()
    image.save(output, format="PNG", optimize=True)
    return output.getvalue()


async def generate_user_card(bot: Bot, user: User, status: Status | None) -> bytes:
    palette = CardPalette()
    current_status = status.status_type if status else StatusType.unknown
    avatar_size = 236
    avatar = await _load_avatar(bot, user, avatar_size)
    if avatar is None:
        avatar = _gradient_avatar(user.username or user.first_name or str(user.telegram_user_id), avatar_size, palette)

    coverage = "нет лимита"
    if status and status.coverage_limit_amount is not None:
        coverage = f"до {format_money(status.coverage_limit_amount, status.coverage_currency)}"

    return _render_card(
        title=user.display_name,
        telegram_id=str(user.telegram_user_id or "неизвестен"),
        link=profile_link(user) or settings.bot_owner_link,
        avatar=avatar,
        status_type=current_status,
        coverage=coverage,
        issued_at=format_date(status.issued_at if status else datetime.now(UTC)),
    )


def generate_unknown_card(target: str | None) -> bytes:
    palette = CardPalette()
    title = target or "Пользователь"
    link = f"https://t.me/{title[1:]}" if title.startswith("@") and len(title) > 1 else settings.bot_owner_link
    avatar = _gradient_avatar(title, 236, palette)
    return _render_card(
        title=title,
        telegram_id="неизвестен",
        link=link,
        avatar=avatar,
        status_type=StatusType.unknown,
        coverage="нет лимита",
        issued_at=format_date(datetime.now(UTC)),
    )

