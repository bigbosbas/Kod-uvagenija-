from __future__ import annotations

from datetime import datetime, timezone
from zoneinfo import ZoneInfo

PRE_PAYMENT_TEXT = """Выберите тариф. После подтверждения оплаты бот автоматически активирует доступ в закрытый канал."""

_RU_MONTHS = (
    "января",
    "февраля",
    "марта",
    "апреля",
    "мая",
    "июня",
    "июля",
    "августа",
    "сентября",
    "октября",
    "ноября",
    "декабря",
)


def format_subscription_expires_ru(iso_str: str | None) -> str:
    if not iso_str:
        return "не указано"
    s = iso_str.strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    msk = dt.astimezone(ZoneInfo("Europe/Moscow"))
    return f"{msk.day} {_RU_MONTHS[msk.month - 1]} {msk.year} в {msk.strftime('%H:%M')} (МСК)"
