from __future__ import annotations

import asyncio
import contextlib
import logging
from datetime import datetime, timedelta, timezone

from aiogram import Bot, Dispatcher, F, Router
from aiogram.client.default import DefaultBotProperties
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message, WebAppInfo
from aiogram.utils.keyboard import InlineKeyboardBuilder

from bot.config import Settings, load_settings
from bot.db import Database
from bot.keyboards import invite_keyboard, payment_url_keyboard
from bot.robokassa import build_payment_url
from bot.telegram_admin_ops import build_invite_link, notify_admins, revoke_access
from bot.texts import PRE_PAYMENT_TEXT, format_subscription_expires_ru
from bot.webhook import run_webhook_server

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")

DEFAULT_PROMO_MEDIA_KIND = "photo"
DEFAULT_PROMO_MEDIA_FILE_ID = (
    "AgACAgIAAxkBAAMJad96T2TSniKNhcHs1sEOmRgOmoYAAj8Vaxv9uAABS-VeK5gy-MGlAQADAgADeQADOwQ"
)


class AdminState(StatesGroup):
    waiting_offer_url = State()
    waiting_policy_url = State()
    waiting_promo_media = State()
    waiting_support_text = State()
    waiting_channel_text = State()
    waiting_welcome_template = State()


def is_admin(settings: Settings, user_id: int) -> bool:
    return user_id in settings.admin_ids


def render(template: str, **values: str) -> str:
    try:
        return template.format(**{key: (value or "") for key, value in values.items()})
    except KeyError:
        return template


def terms_keyboard():
    kb = InlineKeyboardBuilder()
    kb.button(text="✅ Принимаю", callback_data="accept_terms")
    return kb.as_markup()


def menu_keyboard():
    kb = InlineKeyboardBuilder()
    kb.button(text="🚀 Оформить подписку", callback_data="show_plans")
    kb.adjust(1)
    return kb.as_markup()


def plans_keyboard(db: Database):
    kb = InlineKeyboardBuilder()
    for plan in db.list_active_plans():
        kb.button(text=f"{plan.title} - {plan.price_rub} руб", callback_data=f"plan:{plan.code}")
    kb.button(text="Назад", callback_data="back_to_menu")
    kb.adjust(1)
    return kb.as_markup()


def format_user(row) -> str:
    name = " ".join(part for part in [row["first_name"], row["last_name"]] if part).strip() or "без имени"
    username = f"@{row['username']}" if row["username"] else "без username"
    return (
        f"ID: {row['user_id']} | {name} | {username}\n"
        f"Статус: {row['subscription_status']} | Доступ: {row['access_status']}\n"
        f"Тариф: {row['plan_title'] or 'нет'} | До: {row['subscription_expires_at'] or 'не задано'}"
    )


def format_payment(row) -> str:
    return (
        f"Платеж #{row['id']} | user_id={row['user_id']}\n"
        f"Тариф: {row['plan_title']} | Сумма: {row['amount_rub']} руб\n"
        f"Статус: {row['status']} | Создан: {row['created_at']}\n"
        f"Оплачен: {row['paid_at'] or 'нет'}"
    )


def extract_media(message: Message):
    if message.photo:
        return "photo", message.photo[-1].file_id
    if message.video:
        return "video", message.video.file_id
    if message.document:
        return "document", message.document.file_id
    return None


async def send_card(message: Message, db: Database) -> None:
    text = db.get_setting("channel_about_text") or ""
    media_kind = (db.get_setting("promo_media_kind") or DEFAULT_PROMO_MEDIA_KIND).strip()
    media_file_id = (db.get_setting("promo_media_file_id") or "").strip() or DEFAULT_PROMO_MEDIA_FILE_ID

    async def send_text_fallback(note: str | None = None) -> None:
        body = text
        if note:
            body = f"{note}\n\n{body}".strip() if body else note
        if not body:
            body = "Выберите действие в меню ниже."
        await message.answer(body, reply_markup=menu_keyboard())

    if not media_file_id:
        await send_text_fallback()
        return

    try:
        if media_kind == "photo":
            await message.answer_photo(media_file_id, caption=text or None, reply_markup=menu_keyboard())
            return
        if media_kind == "video":
            await message.answer_video(media_file_id, caption=text or None, reply_markup=menu_keyboard())
            return
        if media_kind == "document":
            await message.answer_document(media_file_id, caption=text or None, reply_markup=menu_keyboard())
            return
    except TelegramBadRequest as exc:
        err = (exc.message or "").lower()
        if "wrong file identifier" in err or "wrong remote file identifier" in err or "http url" in err:
            logging.warning("send_card: медиа недоступно (%s), отправляю текст", exc.message)
            await send_text_fallback("Медиа устарело или с другого бота. Загрузите заново: /admin → «Установить file_id».")
            return
        raise

    await send_text_fallback()


async def send_payment_link(callback: CallbackQuery, db: Database, settings: Settings, payment_id: int) -> None:
    payment = db.get_payment(payment_id)
    if payment is None or callback.message is None:
        await callback.answer("Платеж не найден", show_alert=True)
        return

    if payment["status"] == "paid" and payment["invite_link"]:
        user_row = db.get_user_status(payment["user_id"])
        exp_raw = user_row["subscription_expires_at"] if user_row else payment["access_expires_at"]
        await callback.message.answer(
            f"{db.get_setting('tmpl_payment_success') or 'Оплата уже подтверждена.'}\n\nДоступ активен до: {format_subscription_expires_ru(exp_raw)}",
            reply_markup=invite_keyboard(payment["invite_link"]),
        )
        await callback.answer()
        return

    if not settings.robokassa_merchant_login or not settings.robokassa_password1 or not settings.robokassa_password2:
        await callback.message.answer("Robokassa не настроена. Заполните MerchantLogin, Password1 и Password2 в .env.")
        await callback.answer()
        return

    payment_url = build_payment_url(
        settings=settings,
        invoice_id=payment_id,
        amount_rub=payment["amount_rub"],
        description=f"Подписка {payment['plan_title']}",
    )
    db.log_event("payment_created", f"Payment #{payment_id} payment url generated", user_id=payment["user_id"])
    sent = await callback.message.answer(
        f"Тариф: {payment['plan_title']}\nСтоимость: {payment['amount_rub']} руб\n\nПосле успешной оплаты доступ активируется автоматически.",
        reply_markup=payment_url_keyboard(payment_url),
    )
    db.set_payment_prompt_message(payment_id, sent.message_id)
    await callback.answer()


async def background_jobs(bot: Bot, db: Database, settings: Settings) -> None:
    while True:
        try:
            db.cancel_stale_pending_payments()
            await process_expired_users(bot, db, settings)
            await process_notifications(bot, db, settings)
        except Exception as exc:
            db.log_event("system_error", "Background job failed", error_text=str(exc))
            await notify_admins(bot, settings, f"Системная ошибка:\n{exc}")
        await asyncio.sleep(60)


async def process_expired_users(bot: Bot, db: Database, settings: Settings) -> None:
    if not settings.auto_expire:
        return
    for row in db.get_expired_active_users():
        await revoke_access(bot, settings, row["user_id"])
        db.expire_subscription(row["user_id"])
        expired_text = db.get_setting("tmpl_subscription_expired") or "Подписка закончилась."
        with contextlib.suppress(TelegramForbiddenError):
            await bot.send_message(row["user_id"], expired_text, reply_markup=plans_keyboard(db))
        await notify_admins(bot, settings, f"Подписка истекла user_id={row['user_id']}")


async def process_notifications(bot: Bot, db: Database, settings: Settings) -> None:
    reminder_template = db.get_setting("tmpl_renewal_reminder") or ""
    for kind in ("3d", "1d", "day"):
        for row in db.get_users_for_notification(kind):
            try:
                text = render(
                    reminder_template,
                    plan_title=row["plan_title"] or "не выбран",
                    expires_at=row["subscription_expires_at"] or "",
                )
                await bot.send_message(row["user_id"], text, reply_markup=plans_keyboard(db))
            except TelegramForbiddenError:
                pass
            db.mark_notification_sent(row["user_id"], kind)

    expired_template = db.get_setting("tmpl_subscription_expired") or ""
    for row in db.get_users_for_notification("expired"):
        with contextlib.suppress(TelegramForbiddenError):
            await bot.send_message(row["user_id"], expired_template, reply_markup=plans_keyboard(db))
        db.mark_notification_sent(row["user_id"], "expired")


def create_router(db: Database, settings: Settings) -> Router:
    router = Router()

    @router.message(Command("start"))
    async def start(message: Message, state: FSMContext) -> None:
        await state.clear()
        user = message.from_user
        if user is None:
            return
        db.upsert_user(user.id, user.username, user.first_name, user.last_name)
        if db.has_accepted_terms(user.id):
            await send_card(message, db)
            return
        text = render(
            db.get_setting("tmpl_welcome") or "",
            first_name=user.first_name or "друг",
            offer_url=db.get_setting("offer_url") or settings.offer_url,
            policy_url=db.get_setting("policy_url") or settings.policy_url,
        )
        await message.answer(text, reply_markup=terms_keyboard(), disable_web_page_preview=True)

    @router.message(Command("admin"))
    async def admin(message: Message, state: FSMContext) -> None:
        if message.from_user is None or not is_admin(settings, message.from_user.id):
            await message.answer("Эта команда доступна только администраторам.")
            return
        await state.clear()
        base = (settings.public_base_url or "").rstrip("/")
        if not base:
            await message.answer("В .env не задан PUBLIC_BASE_URL — Mini App не откроется.")
            return
        url = f"{base}/admin/"
        kb = InlineKeyboardBuilder()
        kb.button(text="Открыть админ-панель", web_app=WebAppInfo(url=url))
        text = (
            "Админ-панель\n\n"
            "Пользователи, оплаты, тарифы, настройки и поддержка — всё в одном интерфейсе.\n\n"
            "Нажмите кнопку ниже."
        )
        await message.answer(text, reply_markup=kb.as_markup(), parse_mode=None)

    @router.message(Command("finduser"))
    async def find_user(message: Message) -> None:
        if message.from_user is None or not is_admin(settings, message.from_user.id):
            return
        query = (message.text or "").replace("/finduser", "", 1).strip()
        rows = db.search_users(query) if query else []
        await message.answer("\n\n".join(format_user(row) for row in rows) or "Ничего не найдено.")

    @router.message(Command("grant"))
    async def grant(message: Message) -> None:
        if message.from_user is None or not is_admin(settings, message.from_user.id):
            return
        parts = (message.text or "").split()
        if len(parts) < 3:
            await message.answer("Формат: /grant <user_id> <days>")
            return
        user_id = int(parts[1])
        days = int(parts[2])
        row = db.manual_extend_subscription(user_id, days)
        if row is None:
            await message.answer("Пользователь не найден.")
            return
        plan = db.get_plan_by_id(row["current_plan_id"]) if row["current_plan_id"] else None
        if plan is not None:
            link = await build_invite_link(message.bot, settings, user_id, plan.code)
            db.update_user_invite(user_id, link)
            with contextlib.suppress(Exception):
                await message.bot.send_message(
                    user_id,
                    f"Доступ выдан вручную.\nДоступ активен до: {row['subscription_expires_at']}",
                    reply_markup=invite_keyboard(link),
                )
        await message.answer(f"Доступ выдан user_id={user_id} до {row['subscription_expires_at']}")

    @router.message(Command("revoke"))
    async def revoke(message: Message) -> None:
        if message.from_user is None or not is_admin(settings, message.from_user.id):
            return
        parts = (message.text or "").split()
        if len(parts) < 2:
            await message.answer("Формат: /revoke <user_id>")
            return
        user_id = int(parts[1])
        await revoke_access(message.bot, settings, user_id)
        db.expire_subscription(user_id)
        await message.answer(f"Доступ отключен для {user_id}.")

    @router.message(Command("block"))
    async def block(message: Message) -> None:
        if message.from_user is None or not is_admin(settings, message.from_user.id):
            return
        parts = (message.text or "").split()
        if len(parts) < 2:
            await message.answer("Формат: /block <user_id>")
            return
        user_id = int(parts[1])
        db.set_user_blocked(user_id, True)
        await revoke_access(message.bot, settings, user_id)
        await message.answer(f"Пользователь {user_id} заблокирован.")

    @router.message(Command("unblock"))
    async def unblock(message: Message) -> None:
        if message.from_user is None or not is_admin(settings, message.from_user.id):
            return
        parts = (message.text or "").split()
        if len(parts) < 2:
            await message.answer("Формат: /unblock <user_id>")
            return
        user_id = int(parts[1])
        db.set_user_blocked(user_id, False)
        await message.answer(f"Пользователь {user_id} разблокирован.")

    @router.message(Command("payments"))
    async def payments_cmd(message: Message) -> None:
        if message.from_user is None or not is_admin(settings, message.from_user.id):
            return
        await message.answer("\n\n".join(format_payment(row) for row in db.list_payments(limit=15)) or "Оплат пока нет.")

    @router.message(Command("plans"))
    async def plans_cmd(message: Message) -> None:
        if message.from_user is None or not is_admin(settings, message.from_user.id):
            return
        lines = []
        for plan in db.list_all_plans():
            status = "активен" if plan.is_active else "выключен"
            lines.append(f"{plan.code} | {plan.title}\nЦена: {plan.price_rub} руб | Срок: {plan.duration_days} дней | {status}\n{plan.description}")
        await message.answer("\n\n".join(lines) or "Тарифов нет.")

    @router.message(Command("planadd"))
    async def planadd(message: Message) -> None:
        if message.from_user is None or not is_admin(settings, message.from_user.id):
            return
        parts = [item.strip() for item in (message.text or "").replace("/planadd", "", 1).strip().split("|")]
        if len(parts) != 6:
            await message.answer("Формат: /planadd code|title|price|days|description|active(0/1)")
            return
        code, title, price, days, description, active = parts
        db.upsert_plan(code, title, int(price), int(days), description, active == "1")
        await message.answer(f"Тариф {code} сохранен.")

    @router.message(Command("planon"))
    async def planon(message: Message) -> None:
        if message.from_user and is_admin(settings, message.from_user.id):
            db.set_plan_active((message.text or "").replace("/planon", "", 1).strip(), True)
            await message.answer("Тариф включен.")

    @router.message(Command("planoff"))
    async def planoff(message: Message) -> None:
        if message.from_user and is_admin(settings, message.from_user.id):
            db.set_plan_active((message.text or "").replace("/planoff", "", 1).strip(), False)
            await message.answer("Тариф выключен.")

    @router.message(Command("userpayments"))
    async def userpayments(message: Message) -> None:
        if message.from_user is None or not is_admin(settings, message.from_user.id):
            return
        parts = (message.text or "").split()
        if len(parts) < 2:
            await message.answer("Формат: /userpayments <user_id>")
            return
        rows = db.get_user_payment_history(int(parts[1]))
        await message.answer("\n\n".join(format_payment(row) for row in rows) or "История оплат пуста.")

    @router.callback_query(F.data == "accept_terms")
    async def accept(callback: CallbackQuery) -> None:
        if callback.from_user and callback.message:
            db.set_terms_accepted(callback.from_user.id)
            await send_card(callback.message, db)
            await callback.answer()

    @router.callback_query(F.data.in_({"show_plans", "renew_subscription"}))
    async def show_plans(callback: CallbackQuery) -> None:
        if callback.message:
            await callback.message.answer(PRE_PAYMENT_TEXT, reply_markup=plans_keyboard(db))
            await callback.answer()

    @router.callback_query(F.data == "show_channel_info")
    async def show_channel_info(callback: CallbackQuery) -> None:
        if callback.message:
            await callback.message.answer(db.get_setting("channel_about_text") or "", reply_markup=menu_keyboard())
            await callback.answer()

    @router.callback_query(F.data == "show_support")
    async def show_support(callback: CallbackQuery) -> None:
        if callback.message:
            await callback.message.answer(db.get_setting("support_text") or "", reply_markup=menu_keyboard())
            await callback.answer()

    @router.callback_query(F.data == "show_status")
    async def show_status(callback: CallbackQuery) -> None:
        if callback.message is None or callback.from_user is None:
            return
        row = db.get_user_status(callback.from_user.id)
        if row is None:
            await callback.message.answer("Статус пока не найден.", reply_markup=plans_keyboard(db))
            await callback.answer()
            return
        text = (
            "Мой статус\n\n"
            f"Текущий тариф: {row['plan_title'] or 'не выбран'}\n"
            f"Дата начала: {row['subscription_started_at'] or 'нет'}\n"
            f"Дата окончания: {row['subscription_expires_at'] or 'нет'}\n"
            f"Подписка активна: {'да' if row['subscription_status'] == 'active' else 'нет'}\n"
            f"Доступ в канал: {row['access_status']}"
        )
        await callback.message.answer(text, reply_markup=plans_keyboard(db))
        await callback.answer()

    @router.callback_query(F.data == "back_to_menu")
    async def back_to_menu(callback: CallbackQuery) -> None:
        if callback.message:
            await callback.message.answer("Главное меню", reply_markup=menu_keyboard())
            await callback.answer()

    @router.callback_query(F.data.startswith("plan:"))
    async def plan(callback: CallbackQuery) -> None:
        if callback.from_user is None or callback.data is None:
            return
        plan_row = db.get_plan_by_code(callback.data.split(":", 1)[1])
        if plan_row is None or not plan_row.is_active:
            await callback.answer("Тариф недоступен", show_alert=True)
            return
        payment_id = db.create_payment(callback.from_user.id, plan_row.id, plan_row.price_rub)
        await send_payment_link(callback, db, settings, payment_id)

    @router.callback_query(F.data.startswith("admin:"))
    async def admin_callbacks(callback: CallbackQuery, state: FSMContext) -> None:
        if callback.from_user is None or not is_admin(settings, callback.from_user.id) or callback.message is None:
            await callback.answer("Нет доступа", show_alert=True)
            return

        action = callback.data.split(":", 1)[1]
        if action == "users_all":
            await callback.message.answer("\n\n".join(format_user(row) for row in db.list_users("all")) or "Пользователей нет.")
        elif action == "users_active":
            await callback.message.answer("\n\n".join(format_user(row) for row in db.list_users("active")) or "Активных подписчиков нет.")
        elif action == "users_expired":
            await callback.message.answer("\n\n".join(format_user(row) for row in db.list_users("expired")) or "Просроченных пользователей нет.")
        elif action == "payments":
            await callback.message.answer("\n\n".join(format_payment(row) for row in db.list_payments(limit=15)) or "Оплат нет.")
        elif action == "plans":
            lines = []
            for plan in db.list_all_plans():
                status = "активен" if plan.is_active else "выключен"
                lines.append(f"{plan.code} | {plan.title}\nЦена: {plan.price_rub} руб | Срок: {plan.duration_days} дней | {status}\n{plan.description}")
            await callback.message.answer("\n\n".join(lines) or "Тарифов нет.")
        elif action == "settings":
            settings_map = db.list_settings()
            text = (
                f"offer_url: {settings_map.get('offer_url', settings.offer_url)}\n"
                f"policy_url: {settings_map.get('policy_url', settings.policy_url)}\n"
                f"support_text: {settings_map.get('support_text', '')}\n"
                f"promo_media_kind: {settings_map.get('promo_media_kind', DEFAULT_PROMO_MEDIA_KIND)}\n"
                f"robokassa_ready: {'yes' if settings.robokassa_merchant_login and settings.robokassa_password1 and settings.robokassa_password2 else 'no'}\n"
                f"public_base_url: {settings.public_base_url or '-'}"
            )
            await callback.message.answer(text)
        elif action == "set_media":
            await state.set_state(AdminState.waiting_promo_media)
            await callback.message.answer("Отправьте фото, видео или документ.")
        elif action == "set_offer":
            await state.set_state(AdminState.waiting_offer_url)
            await callback.message.answer("Отправьте новую ссылку на оферту.")
        elif action == "set_policy":
            await state.set_state(AdminState.waiting_policy_url)
            await callback.message.answer("Отправьте новую ссылку на политику.")
        elif action == "set_support":
            await state.set_state(AdminState.waiting_support_text)
            await callback.message.answer("Отправьте новый текст поддержки.")
        elif action == "set_channel_text":
            await state.set_state(AdminState.waiting_channel_text)
            await callback.message.answer("Отправьте новый текст раздела 'Что внутри канала'.")
        elif action == "set_welcome_template":
            await state.set_state(AdminState.waiting_welcome_template)
            await callback.message.answer("Отправьте новый шаблон приветствия.")
        await callback.answer()

    @router.message(AdminState.waiting_offer_url)
    async def offer_url(message: Message, state: FSMContext) -> None:
        if message.from_user and is_admin(settings, message.from_user.id):
            db.set_setting("offer_url", (message.text or "").strip())
            await state.clear()
            await message.answer("Ссылка на оферту сохранена. (удобнее править в Mini App → Настройки)")

    @router.message(AdminState.waiting_policy_url)
    async def policy_url(message: Message, state: FSMContext) -> None:
        if message.from_user and is_admin(settings, message.from_user.id):
            db.set_setting("policy_url", (message.text or "").strip())
            await state.clear()
            await message.answer("Ссылка на политику сохранена. (Mini App → Настройки)")

    @router.message(AdminState.waiting_support_text)
    async def support_text(message: Message, state: FSMContext) -> None:
        if message.from_user and is_admin(settings, message.from_user.id):
            db.set_setting("support_text", message.html_text or message.text or "")
            await state.clear()
            await message.answer("Текст поддержки сохранен. (Mini App → Настройки)")

    @router.message(AdminState.waiting_channel_text)
    async def channel_text(message: Message, state: FSMContext) -> None:
        if message.from_user and is_admin(settings, message.from_user.id):
            db.set_setting("channel_about_text", message.html_text or message.text or "")
            await state.clear()
            await message.answer("Текст канала сохранен. (Mini App → Настройки)")

    @router.message(AdminState.waiting_welcome_template)
    async def welcome_template(message: Message, state: FSMContext) -> None:
        if message.from_user and is_admin(settings, message.from_user.id):
            db.set_setting("tmpl_welcome", message.html_text or message.text or "")
            await state.clear()
            await message.answer("Шаблон приветствия сохранен. (Mini App → Настройки)")

    @router.message(AdminState.waiting_promo_media)
    async def promo_media(message: Message, state: FSMContext) -> None:
        if message.from_user and is_admin(settings, message.from_user.id):
            media = extract_media(message)
            if media is None:
                await message.answer("Отправьте фото, видео или документ.")
                return
            kind, file_id = media
            db.set_setting("promo_media_kind", kind)
            db.set_setting("promo_media_file_id", file_id)
            await state.clear()
            await message.answer(f"Сохранено.\nТип: {kind}\nfile_id: {file_id}\n(Mini App → Настройки — можно вставить file_id вручную)")

    @router.message(Command("my_access"))
    async def my_access(message: Message) -> None:
        if message.from_user is None:
            return
        row = db.get_user_status(message.from_user.id)
        if row is None:
            await message.answer("Статус пока не найден.", reply_markup=plans_keyboard(db))
            return
        await message.answer(
            f"Текущий тариф: {row['plan_title'] or 'не выбран'}\nДоступ до: {row['subscription_expires_at'] or 'нет'}\nСтатус: {row['subscription_status']}",
            reply_markup=plans_keyboard(db),
        )

    return router


async def main() -> None:
    settings = load_settings()
    db = Database(settings.db_path)
    session = AiohttpSession(proxy=settings.telegram_proxy) if settings.telegram_proxy else None
    bot = Bot(
        token=settings.bot_token,
        session=session,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    dp = Dispatcher()
    dp.include_router(create_router(db, settings))

    webhook_runner = await run_webhook_server(bot=bot, db=db, settings=settings)
    background_task = asyncio.create_task(background_jobs(bot, db, settings))
    try:
        await dp.start_polling(bot)
    finally:
        background_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await background_task
        await webhook_runner.cleanup()


if __name__ == "__main__":
    asyncio.run(main())
