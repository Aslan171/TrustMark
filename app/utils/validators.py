from __future__ import annotations

import re
from dataclasses import dataclass

from aiogram.types import Message, MessageOriginHiddenUser, MessageOriginUser

USERNAME_RE = re.compile(r"^(?:@|https?://t\.me/)?([A-Za-z0-9_]{5,32})/?$")
USER_ID_RE = re.compile(r"^\d{5,20}$")
URL_RE = re.compile(r"^https?://[^\s<>\"]{3,2048}$", re.IGNORECASE)


@dataclass(frozen=True, slots=True)
class ParsedTarget:
    raw: str
    user_id: int | None = None
    username: str | None = None
    hidden_name: str | None = None

    @property
    def display(self) -> str:
        if self.username:
            return f"@{self.username}"
        if self.user_id:
            return str(self.user_id)
        return self.hidden_name or self.raw


def normalize_username(value: str | None) -> str | None:
    if not value:
        return None
    match = USERNAME_RE.match(value.strip())
    if not match:
        return None
    return match.group(1)


def is_valid_link(value: str) -> bool:
    return bool(URL_RE.match(value.strip()))


def parse_target_text(text: str | None) -> ParsedTarget | None:
    if not text:
        return None
    raw = text.strip()
    if not raw:
        return None
    if USER_ID_RE.match(raw):
        return ParsedTarget(raw=raw, user_id=int(raw))
    username = normalize_username(raw)
    if username:
        return ParsedTarget(raw=raw, username=username)
    return None


def parse_forwarded_user(message: Message) -> ParsedTarget | None:
    origin = message.forward_origin
    if isinstance(origin, MessageOriginUser):
        user = origin.sender_user
        return ParsedTarget(
            raw=str(user.id),
            user_id=user.id,
            username=user.username,
            hidden_name=user.full_name,
        )
    if isinstance(origin, MessageOriginHiddenUser):
        return ParsedTarget(raw=origin.sender_user_name, hidden_name=origin.sender_user_name)
    forward_from = getattr(message, "forward_from", None)
    if forward_from:
        user = forward_from
        return ParsedTarget(
            raw=str(user.id),
            user_id=user.id,
            username=user.username,
            hidden_name=user.full_name,
        )
    return None


def parse_check_command(text: str | None) -> str | None:
    if not text:
        return None
    stripped = text.strip()
    lowered = stripped.casefold()
    if lowered == "чек":
        return ""
    if lowered.startswith("чек "):
        return stripped[4:].strip()
    return None
