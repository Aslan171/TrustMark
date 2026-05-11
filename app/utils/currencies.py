from __future__ import annotations

from decimal import Decimal, InvalidOperation

SUPPORTED_CURRENCIES = ("KZT", "USD", "RUB", "TON", "Telegram Stars")
NORMALIZED_CURRENCIES = {
    "KZT": "KZT",
    "ТГ": "KZT",
    "USD": "USD",
    "$": "USD",
    "RUB": "RUB",
    "РУБ": "RUB",
    "TON": "TON",
    "STARS": "Telegram Stars",
    "STAR": "Telegram Stars",
    "TELEGRAM STARS": "Telegram Stars",
    "ЗВЕЗДЫ": "Telegram Stars",
}


def normalize_currency(value: str) -> str | None:
    return NORMALIZED_CURRENCIES.get(value.strip().upper())


def parse_amount(value: str) -> Decimal | None:
    normalized = value.replace(",", ".").strip()
    try:
        amount = Decimal(normalized)
    except InvalidOperation:
        return None
    if amount <= 0:
        return None
    return amount.quantize(Decimal("0.01"))

