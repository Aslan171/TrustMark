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


@dataclass(slots=True)
class CardPalette:
    bg: tuple[int, int, int] = (5, 8, 14)
    base: tuple[int, int, int] = (20, 27, 40)
    panel: tuple[int, int, int] = (30, 40, 59)
    panel_dark: tuple[int, int, int] = (11, 16, 26)
    text: tuple[int, int, int] = (255, 255, 255)
    muted: tuple[int, int, int] = (207, 219, 238)
    subtle: tuple[int, int, int] = (137, 153, 176)
    green: tuple[int, int, int] = (26, 234, 185)
    blue: tuple[int, int, int] = (76, 201, 255)
    orange: tuple[int, int, int] = (255, 184, 64)
    red: tuple[int, int, int] = (255, 76, 95)
    white_chip: tuple[int, int, int] = (232, 239, 249)


AVATAR_GRADIENTS: tuple[tuple[tuple[int, int, int], tuple[int, int, int]], ...] = (
    ((40, 158, 255), (38, 224, 190)),
    ((255, 170, 54), (255, 88, 68)),
    ((151, 104, 255), (67, 196, 255)),
    ((36, 210, 135), (12, 169, 158)),
    ((255, 92, 174), (114, 96, 255)),
    ((255, 205, 72), (255, 127, 72)),
)


def _font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    candidates = [
        "C:/Windows/Fonts/segoeuib.ttf" if bold else "C:/Windows/Fonts/segoeui.ttf",
        "C:/Windows/Fonts/arialbd.ttf" if bold else "C:/Windows/Fonts/arial.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
        if bold
        else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf"
        if bold
        else "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
    ]
    for candidate in candidates:
        if Path(candidate).exists():
            return ImageFont.truetype(candidate, size=size)

    for font_name in ("DejaVuSans-Bold.ttf" if bold else "DejaVuSans.ttf", "Arial.ttf"):
        try:
            return ImageFont.truetype(font_name, size=size)
        except OSError:
            continue
    return ImageFont.load_default()


def _text_width(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.ImageFont) -> int:
    bbox = draw.textbbox((0, 0), text, font=font)
    return bbox[2] - bbox[0]


def _text_height(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.ImageFont) -> int:
    bbox = draw.textbbox((0, 0), text, font=font)
    return bbox[3] - bbox[1]


def _fit_font(
    draw: ImageDraw.ImageDraw,
    text: str,
    max_width: int,
    size: int,
    *,
    bold: bool = False,
    min_size: int = 28,
) -> ImageFont.ImageFont:
    current = size
    while current >= min_size:
        font = _font(current, bold=bold)
        if _text_width(draw, text, font) <= max_width:
            return font
        current -= 2
    return _font(min_size, bold=bold)


def _circle_mask(size: int) -> Image.Image:
    mask = Image.new("L", (size, size), 0)
    draw = ImageDraw.Draw(mask)
    draw.ellipse((0, 0, size - 1, size - 1), fill=255)
    return mask


def _initials(label: str | None) -> str:
    cleaned = (label or "?").replace("@", " ").replace("_", " ").strip()
    parts = [part for part in cleaned.split() if part]
    if not parts:
        return "?"
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
    draw.ellipse((7, 7, size - 8, size - 8), outline=(255, 255, 255, 170), width=6)

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


def _status_color(status_type: StatusType, palette: CardPalette) -> tuple[int, int, int]:
    return {
        StatusType.guarantor: palette.green,
        StatusType.trusted_user: palette.blue,
        StatusType.unknown: palette.white_chip,
        StatusType.suspicious: palette.orange,
        StatusType.scammer: palette.red,
    }[status_type]


def _status_title(status_type: StatusType) -> str:
    return {
        StatusType.guarantor: "GUARANTOR",
        StatusType.trusted_user: "TRUSTED USER",
        StatusType.unknown: "NOT IN DATABASE",
        StatusType.suspicious: "SUSPICIOUS",
        StatusType.scammer: "SCAMMER",
    }[status_type]


def _draw_label(draw: ImageDraw.ImageDraw, xy: tuple[int, int], text: str, palette: CardPalette) -> None:
    draw.text(xy, text, font=_font(28, bold=True), fill=palette.subtle)


def _draw_value_panel(
    draw: ImageDraw.ImageDraw,
    box: tuple[int, int, int, int],
    label: str,
    value: str,
    *,
    palette: CardPalette,
    color: tuple[int, int, int] | None = None,
    value_size: int = 48,
) -> None:
    x1, y1, x2, y2 = box
    draw.rounded_rectangle(box, radius=28, fill=palette.panel_dark)
    _draw_label(draw, (x1 + 30, y1 + 22), label, palette)
    font = _fit_font(draw, value, x2 - x1 - 60, value_size, bold=True, min_size=30)
    draw.text((x1 + 30, y1 + 64), value, font=font, fill=color or palette.text)


def _centered_text(
    draw: ImageDraw.ImageDraw,
    box: tuple[int, int, int, int],
    text: str,
    font: ImageFont.ImageFont,
    fill: tuple[int, int, int],
) -> None:
    x1, y1, x2, y2 = box
    draw.text(
        (
            x1 + (x2 - x1 - _text_width(draw, text, font)) / 2,
            y1 + (y2 - y1 - _text_height(draw, text, font)) / 2 - 4,
        ),
        text,
        font=font,
        fill=fill,
    )


def _id_line(telegram_id: str) -> str:
    return f"Telegram ID: {telegram_id}" if telegram_id.isdigit() else "ID unavailable"


def _render_card(
    *,
    title: str,
    telegram_id: str,
    link: str,
    avatar: Image.Image,
    status_type: StatusType,
    coverage: str,
    checked_at: str,
) -> bytes:
    palette = CardPalette()
    accent = _status_color(status_type, palette)
    risk = risk_for_status(status_type)
    width = height = 1080

    image = Image.new("RGB", (width, height), palette.bg)
    draw = ImageDraw.Draw(image)

    draw.rounded_rectangle((36, 36, 1044, 1044), radius=44, fill=palette.base)
    draw.rectangle((36, 94, 54, 986), fill=accent)

    draw.text((84, 72), "TRUSTMARK", font=_font(54, bold=True), fill=accent)
    owner = f"@{settings.bot_owner_username}"
    owner_font = _font(30, bold=True)
    draw.text((996 - _text_width(draw, owner, owner_font), 88), owner, font=owner_font, fill=palette.muted)

    draw.rounded_rectangle((84, 142, 996, 402), radius=38, fill=palette.panel)
    image.paste(avatar, (116, 166), avatar)

    title_font = _fit_font(draw, title, 590, 76, bold=True, min_size=42)
    draw.text((390, 164), title, font=title_font, fill=palette.text)
    draw.text((394, 254), _id_line(telegram_id), font=_font(42, bold=True), fill=palette.muted)
    draw.text((394, 312), link, font=_fit_font(draw, link, 560, 34, bold=True), fill=accent)

    chip_box = (756, 74, 996, 128)
    draw.rounded_rectangle(chip_box, radius=27, fill=palette.white_chip)
    chip_font = _font(27, bold=True)
    _centered_text(draw, chip_box, "CHECK CARD", chip_font, palette.bg)

    status_box = (84, 448, 996, 620)
    draw.rounded_rectangle(status_box, radius=34, fill=palette.panel_dark, outline=accent, width=5)
    _draw_label(draw, (122, 476), "STATUS", palette)
    status = _status_title(status_type)
    status_font = _fit_font(draw, status, 836, 78, bold=True, min_size=44)
    draw.text((122, 520), status, font=status_font, fill=accent)

    risk_box = (84, 664, 520, 850)
    draw.rounded_rectangle(risk_box, radius=34, fill=palette.panel_dark)
    _draw_label(draw, (122, 696), "DEAL RISK", palette)
    risk_text = f"{risk}%"
    risk_font = _font(118, bold=True)
    draw.text((122, 726), risk_text, font=risk_font, fill=accent)

    _draw_value_panel(
        draw,
        (560, 664, 996, 778),
        "COVERAGE LIMIT",
        coverage,
        palette=palette,
        value_size=38,
    )
    _draw_value_panel(
        draw,
        (560, 808, 996, 922),
        "CHECK DATE",
        checked_at,
        palette=palette,
        value_size=38,
    )

    warning = "Username can change. Telegram ID is the main identifier."
    warning_font = _fit_font(draw, warning, 900, 34, bold=True, min_size=26)
    draw.text((84, 958), warning, font=warning_font, fill=palette.orange)
    draw.text((84, 1000), "TrustMark reputation check", font=_font(28, bold=True), fill=palette.subtle)

    output = BytesIO()
    image.save(output, format="PNG", optimize=True)
    return output.getvalue()


async def generate_user_card(bot: Bot, user: User, status: Status | None) -> bytes:
    palette = CardPalette()
    status_type = status.status_type if status else StatusType.unknown
    avatar_size = 220
    avatar = await _load_avatar(bot, user, avatar_size)
    if avatar is None:
        avatar = _gradient_avatar(user.username or user.first_name or str(user.telegram_user_id), avatar_size, palette)

    coverage = "no limit"
    if status and status.coverage_limit_amount is not None:
        coverage = f"up to {format_money(status.coverage_limit_amount, status.coverage_currency)}"

    telegram_id = str(user.telegram_user_id) if user.telegram_user_id else "ID unavailable"
    return _render_card(
        title=user.display_name,
        telegram_id=telegram_id,
        link=profile_link(user) or settings.bot_owner_link,
        avatar=avatar,
        status_type=status_type,
        coverage=coverage,
        checked_at=format_date(status.issued_at if status else datetime.now(UTC)),
    )


def generate_unknown_card(target: str | None) -> bytes:
    palette = CardPalette()
    title = target or "Unknown user"
    link = f"https://t.me/{title[1:]}" if title.startswith("@") and len(title) > 1 else settings.bot_owner_link
    avatar = _gradient_avatar(title, 220, palette)
    return _render_card(
        title=title,
        telegram_id="ID unavailable",
        link=link,
        avatar=avatar,
        status_type=StatusType.unknown,
        coverage="no limit",
        checked_at=format_date(datetime.now(UTC)),
    )
