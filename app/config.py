from __future__ import annotations

import os
from dataclasses import dataclass
from decimal import Decimal

from dotenv import load_dotenv

load_dotenv()


def _parse_int_list(value: str | None) -> frozenset[int]:
    if not value:
        return frozenset()
    items: list[int] = []
    for raw_item in value.split(","):
        item = raw_item.strip()
        if not item:
            continue
        items.append(int(item))
    return frozenset(items)


def _parse_optional_int(value: str | None) -> int | None:
    if value is None or not value.strip():
        return None
    return int(value)


def _parse_bool(value: str | None, default: bool = False) -> bool:
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "y", "on"}


@dataclass(frozen=True, slots=True)
class Settings:
    bot_token: str
    database_url: str
    admin_ids: frozenset[int]
    admin_chat_id: int | None
    evidence_channel_id: int | str | None
    evidence_channel_username: str | None
    project_name: str
    bot_owner_username: str
    create_db_on_startup: bool
    rate_limit_seconds: float
    log_level: str
    guarantor_entry_fee_usd: Decimal = Decimal("20")

    @property
    def bot_owner_link(self) -> str:
        return f"https://t.me/{self.bot_owner_username.lstrip('@')}"

    @property
    def public_evidence_username(self) -> str | None:
        if not self.evidence_channel_username:
            return None
        return self.evidence_channel_username.lstrip("@")

    def is_admin(self, telegram_user_id: int | None) -> bool:
        return telegram_user_id is not None and telegram_user_id in self.admin_ids

    def validate_runtime(self) -> None:
        missing: list[str] = []
        if not self.bot_token:
            missing.append("BOT_TOKEN")
        if not self.database_url:
            missing.append("DATABASE_URL")
        if missing:
            raise RuntimeError(f"Missing required environment variables: {', '.join(missing)}")


def load_settings() -> Settings:
    evidence_raw = os.getenv("EVIDENCE_CHANNEL_ID")
    evidence_channel_id: int | str | None
    if evidence_raw and evidence_raw.strip():
        stripped = evidence_raw.strip()
        evidence_channel_id = int(stripped) if stripped.lstrip("-").isdigit() else stripped
    else:
        evidence_channel_id = None

    return Settings(
        bot_token=os.getenv("BOT_TOKEN", ""),
        database_url=os.getenv(
            "DATABASE_URL",
            "postgresql+asyncpg://trustmark:trustmark@localhost:5432/trustmark",
        ),
        admin_ids=_parse_int_list(os.getenv("ADMIN_IDS")),
        admin_chat_id=_parse_optional_int(os.getenv("ADMIN_CHAT_ID")),
        evidence_channel_id=evidence_channel_id,
        evidence_channel_username=os.getenv("EVIDENCE_CHANNEL_USERNAME", "trustcheck_evidence"),
        project_name=os.getenv("PROJECT_NAME", "TrustMark"),
        bot_owner_username=os.getenv("BOT_OWNER_USERNAME", "Vexsento").lstrip("@"),
        create_db_on_startup=_parse_bool(os.getenv("CREATE_DB_ON_STARTUP"), default=False),
        rate_limit_seconds=float(os.getenv("RATE_LIMIT_SECONDS", "1.2")),
        log_level=os.getenv("LOG_LEVEL", "INFO").upper(),
    )


settings = load_settings()

