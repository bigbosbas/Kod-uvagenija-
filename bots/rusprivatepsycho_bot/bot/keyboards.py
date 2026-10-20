from __future__ import annotations

from aiogram.utils.keyboard import InlineKeyboardBuilder


def payment_url_keyboard(url: str):
    kb = InlineKeyboardBuilder()
    kb.button(text="Оплатить через Robokassa", url=url)
    kb.button(text="Назад", callback_data="show_plans")
    kb.adjust(1)
    return kb.as_markup()


def invite_keyboard(link: str):
    kb = InlineKeyboardBuilder()
    kb.button(text="Войти в канал", url=link)
    kb.button(text="Продлить подписку", callback_data="renew_subscription")
    kb.adjust(1)
    return kb.as_markup()
