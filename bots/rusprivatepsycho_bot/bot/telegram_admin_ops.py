from __future__ import annotations

import contextlib
import html
from datetime import datetime, timedelta, timezone

from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest

from bot.config import Settings


async def notify_admins(
    bot: Bot,
    settings: Settings,
    text: str,
    *,
    parse_mode: str | None = None,
    disable_web_page_preview: bool = True,
) -> None:
    for admin_id in settings.admin_ids:
        with contextlib.suppress(Exception):
            await bot.send_message(
                admin_id,
                text,
                disable_web_page_preview=disable_web_page_preview,
                parse_mode=parse_mode,
            )


def admin_new_payment_caption_html(
    *,
    payment_id: int,
    user_id: int,
    plan_title: str,
    amount_rub: int,
    expires_display: str,
    source: str,
    username: str | None,
    first_name: str | None,
    last_name: str | None,
) -> str:
    source_labels = {
        "robokassa_webhook": "Robokassa",
        "robokassa": "Robokassa",
        "telegram_stub": "Telegram",
    }
    src = html.escape(source_labels.get(source, source))
    title = html.escape(plan_title)
    name_raw = " ".join(p for p in [first_name or "", last_name or ""] if p).strip()
    name = html.escape(name_raw or "—")
    user_line = f"@{html.escape(username)}" if username else "—"
    exp = html.escape(expires_display)
    return (
        "💳 <b>Новая оплата</b>\n\n"
        "👤 <b>Клиент</b>\n"
        f"• ID: <code>{user_id}</code>\n"
        f"• Имя: {name}\n"
        f"• Username: {user_line}\n\n"
        f"📦 <b>Тариф:</b> {title}\n"
        f"💰 <b>Сумма:</b> {amount_rub} ₽\n"
        f"📅 <b>Доступ до:</b> {exp}\n"
        f"🔧 <b>Канал оплаты:</b> {src}\n\n"
        f"✅ Платёж <code>#{payment_id}</code> подтверждён, доступ выдан автоматически."
    )


async def build_invite_link(bot: Bot, settings: Settings, user_id: int, code: str) -> str:
    invite = await bot.create_chat_invite_link(
        chat_id=settings.channel_ref,
        name=f"user-{user_id}-{code}",
        member_limit=1,
    )
    return invite.invite_link


async def revoke_access(bot: Bot, settings: Settings, user_id: int) -> None:
    with contextlib.suppress(TelegramBadRequest):
        await bot.ban_chat_member(
            settings.channel_ref,
            user_id,
            until_date=datetime.now(timezone.utc) + timedelta(seconds=60),
        )
        await bot.unban_chat_member(settings.channel_ref, user_id, only_if_banned=True)
