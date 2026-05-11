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
    surface: tuple[int, int, int] = (16, 22, 34)
    surface_2: tuple[int, int, int] = (26, 35, 52)
    surface_3: tuple[int, int, int] = (35, 46, 66)
    text: tuple[int, int, int] = (255, 255, 255)
    muted: tuple[int, int, int] = (194, 207, 226)
    subtle: tuple[int, int, int] = (121, 137, 159)
    green: tuple[int, int, int] = (24, 232, 182)
    blue: tuple[int, int, int] = (79, 196, 255)
    orange: tuple[int, int, int] = (255, 183, 69)
    red: tuple[int, int, int] = (255, 74, 92)


AVATAR_GRADIENTS: tuple[tuple[tuple[int, int, int], tuple[int, int, int]], ...] = (
    ((45, 156, 255), (41, 222, 190)),
    ((255, 169, 53), (255, 92, 64)),
    ((151, 106, 255), (68, 198, 255)),
    ((38, 210, 136), (13, 167, 158)),
    ((255, 96, 170), (112, 95, 255)),
    ((255, 203, 70), (255, 126, 76)),
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

    # Last attempt: Pillow can sometimes resolve bundled/system fonts by name.
    for name in ("DejaVuSans-Bold.ttf" if bold else "DejaVuSans.ttf", "Arial.ttf"):
        try:
            return ImageFont.truetype(name, size=size)
        except OSError:
            continue
    return ImageFont.load_default()


def _text_width(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.ImageFont) -> int:
    bbox = draw.textbbox((0, 0), text, font=font)
    return bbox[2] - bbox[0]


def _fit_font(
    draw: ImageDraw.ImageDraw,
    text: str,
    max_width: int,
    size: int,
    *,
    bold: bool = False,
    min_size: int = 24,
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
    draw.ellipse((6, 6, size - 7, size - 7), outline=(255, 255, 255, 170), width=5)
    text = _initials(label)
    font = _font(size // 3, bold=True)
    bbox = draw.textbbox((0, 0), text, font=font)
    draw.text(
        ((size - (bbox[2] - bbox[0])) / 2, (size - (bbox[3] - bbox[1])) / 2 - 6),
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
        StatusType.unknown: (229, 236, 246),
        StatusType.suspicious: palette.orange,
        StatusType.scammer: palette.red,
    }[status_type]


def _status_title(status_type: StatusType) -> str:
    return {
        StatusType.guarantor: "GUARANTOR",
        StatusType.trusted_user: "TRUSTED USER",
        StatusType.unknown: "NOT IN DATABASE",
        StatusType.suspicious: "SUSPICIOUS",
        StatusType.scammer: "CONFIRMED SCAMMER",
    }[status_type]


def _draw_pill(
    draw: ImageDraw.ImageDraw,
    xy: tuple[int, int],
    text: str,
    fill: tuple[int, int, int],
    palette: CardPalette,
) -> None:
    x, y = xy
    font = _font(26, bold=True)
    width = _text_width(draw, text, font) + 42
    draw.rounded_rectangle((x, y, x + width, y + 48), radius=24, fill=fill)
    draw.text((x + 21, y + 9), text, font=font, fill=palette.bg)


def _draw_panel(
    draw: ImageDraw.ImageDraw,
    box: tuple[int, int, int, int],
    label: str,
    value: str,
    *,
    palette: CardPalette,
    color: tuple[int, int, int] | None = None,
    value_size: int = 58,
    label_size: int = 25,
) -> None:
    x1, y1, x2, y2 = box
    draw.rounded_rectangle(box, radius=26, fill=palette.surface)
    draw.text((x1 + 32, y1 + 24), label, font=_font(label_size, bold=True), fill=palette.subtle)
    font = _fit_font(draw, value, x2 - x1 - 64, value_size, bold=True, min_size=30)
    draw.text((x1 + 32, y1 + 66), value, font=font, fill=color or palette.text)


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
    width, height = 1200, 720

    image = Image.new("RGB", (width, height), palette.bg)
    draw = ImageDraw.Draw(image)

    draw.rounded_rectangle((28, 28, width - 28, height - 28), radius=34, fill=palette.surface_2)
    draw.rounded_rectangle((54, 54, width - 54, 276), radius=30, fill=palette.surface_3)
    draw.rectangle((28, 72, 42, height - 72), fill=accent)

    draw.text((78, 76), "TRUSTMARK", font=_font(32, bold=True), fill=accent)
    draw.text((916, 83), f"@{settings.bot_owner_username}", font=_font(26, bold=True), fill=palette.muted)

    image.paste(avatar, (82, 126), avatar)
    title_font = _fit_font(draw, title, 560, 62, bold=True, min_size=38)
    draw.text((294, 124), title, font=title_font, fill=palette.text)
    draw.text((298, 194), f"Telegram ID: {telegram_id}", font=_font(34, bold=True), fill=palette.muted)
    draw.text((298, 236), link, font=_fit_font(draw, link, 570, 26, bold=True), fill=accent)
    _draw_pill(draw, (905, 190), "CHECK CARD", accent, palette)

    _draw_panel(
        draw,
        (72, 326, 696, 488),
        "STATUS",
        _status_title(status_type),
        palette=palette,
        color=accent,
        value_size=54,
    )
    _draw_panel(
        draw,
        (736, 326, 1128, 488),
        "DEAL RISK",
        f"{risk}%",
        palette=palette,
        color=accent,
        value_size=88,
    )
    _draw_panel(
        draw,
        (72, 528, 552, 632),
        "COVERAGE LIMIT",
        coverage,
        palette=palette,
        value_size=38,
    )
    _draw_panel(
        draw,
        (592, 528, 1128, 632),
        "CHECK DATE",
        checked_at,
        palette=palette,
        value_size=38,
    )

    draw.text(
        (76, 666),
        "Username can change. Telegram ID is the main identifier.",
        font=_font(28, bold=True),
        fill=palette.orange,
    )

    output = BytesIO()
    image.save(output, format="PNG", optimize=True)
    return output.getvalue()


async def generate_user_card(bot: Bot, user: User, status: Status | None) -> bytes:
    palette = CardPalette()
    status_type = status.status_type if status else StatusType.unknown
    avatar_size = 150
    avatar = await _load_avatar(bot, user, avatar_size)
    if avatar is None:
        avatar = _gradient_avatar(user.username or user.first_name or str(user.telegram_user_id), avatar_size, palette)

    coverage = "no limit"
    if status and status.coverage_limit_amount is not None:
        coverage = f"up to {format_money(status.coverage_limit_amount, status.coverage_currency)}"

    return _render_card(
        title=user.display_name,
        telegram_id=str(user.telegram_user_id or "unknown"),
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
    avatar = _gradient_avatar(title, 150, palette)
    return _render_card(
        title=title,
        telegram_id="unavailable",
        link=link,
        avatar=avatar,
        status_type=StatusType.unknown,
        coverage="no limit",
        checked_at=format_date(datetime.now(UTC)),
    )

