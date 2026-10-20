from __future__ import annotations

import contextlib
import logging

from aiohttp import web
from aiogram import Bot
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError

from bot.admin_api import setup_admin_routes
from bot.config import Settings
from bot.db import Database
from bot.keyboards import invite_keyboard
from bot.robokassa import verify_result_signature
from bot.telegram_admin_ops import admin_new_payment_caption_html, build_invite_link, notify_admins
from bot.texts import format_subscription_expires_ru


async def process_successful_payment(
    *,
    bot: Bot,
    db: Database,
    settings: Settings,
    payment_id: int,
    out_sum: str = "",
    source: str = "robokassa",
) -> bool:
    payment = db.get_payment(payment_id)
    if payment is None:
        return False
    if payment["status"] == "paid" and payment["invite_link"]:
        return True
    if payment["status"] not in {"pending", "cancelled"}:
        db.log_event(
            "payment_webhook_ignored",
            f"Платёж #{payment_id} не в ожидании (status={payment['status']}), доступ не выдан",
            user_id=payment["user_id"],
        )
        return True
    if payment["status"] == "cancelled":
        db.log_event(
            "payment_recovered_after_timeout",
            f"Платёж #{payment_id} был cancelled по таймауту, восстановлен webhook",
            user_id=payment["user_id"],
        )

    try:
        link = await build_invite_link(
            bot,
            settings,
            int(payment["user_id"]),
            str(payment["plan_code"]),
        )
    except TelegramBadRequest as exc:
        db.mark_payment_failed(payment_id, exc.message)
        db.log_event("access_issue", f"Failed to create invite link via {source}", user_id=payment["user_id"], error_text=exc.message)
        await notify_admins(bot, settings, f"Ошибка выдачи доступа user_id={payment['user_id']}\nПлатеж #{payment_id}\n{exc.message}")
        return False

    try:
        db.mark_payment_paid(payment_id, link)
    except ValueError as exc:
        db.log_event(
            "payment_paid_rejected",
            f"Платёж #{payment_id}: {exc}",
            user_id=payment["user_id"],
        )
        return True

    paid = db.get_payment(payment_id)
    if paid is None:
        return True

    prompt_mid = paid["payment_prompt_message_id"]
    if prompt_mid:
        with contextlib.suppress(TelegramBadRequest, TelegramForbiddenError):
            await bot.delete_message(chat_id=payment["user_id"], message_id=int(prompt_mid))
        db.clear_payment_prompt_message(payment_id)

    user_row = db.get_user_status(payment["user_id"])
    db.log_event("payment_paid", f"Payment #{payment_id} marked paid via {source}", user_id=payment["user_id"], technical_details=out_sum)

    success_text = db.get_setting("tmpl_payment_success") or "Оплата прошла успешно."
    expires_raw = user_row["subscription_expires_at"] if user_row else paid["access_expires_at"]
    expires_h = format_subscription_expires_ru(expires_raw)
    user_lines = f"{success_text}\n\nДоступ активен до: {expires_h}"
    try:
        await bot.send_message(
            payment["user_id"],
            user_lines,
            reply_markup=invite_keyboard(link),
        )
    except TelegramForbiddenError:
        logging.warning(
            "payment success: cannot message user_id=%s (blocked or no /start)",
            payment["user_id"],
        )

    admin_text = admin_new_payment_caption_html(
        payment_id=payment_id,
        user_id=int(payment["user_id"]),
        plan_title=str(payment["plan_title"]),
        amount_rub=int(payment["amount_rub"]),
        expires_display=expires_h,
        source=source,
        username=user_row["username"] if user_row else None,
        first_name=user_row["first_name"] if user_row else None,
        last_name=user_row["last_name"] if user_row else None,
    )
    await notify_admins(bot, settings, admin_text, parse_mode=ParseMode.HTML)
    return True


async def robokassa_result(request: web.Request) -> web.Response:
    bot: Bot = request.app["bot"]
    db: Database = request.app["db"]
    settings: Settings = request.app["settings"]

    post_data = await request.post()
    out_sum = str(post_data.get("OutSum", "")).strip()
    invoice_id_raw = str(post_data.get("InvId", "")).strip()
    signature_value = str(post_data.get("SignatureValue", "")).strip()

    if not invoice_id_raw.isdigit():
        db.log_event("payment_error", "Robokassa webhook received invalid invoice id", technical_details=str(dict(post_data)))
        return web.Response(text="bad inv id", status=400)

    invoice_id = int(invoice_id_raw)
    if not verify_result_signature(
        out_sum=out_sum,
        invoice_id=invoice_id,
        signature_value=signature_value,
        password2=settings.robokassa_active_password2,
        algorithm=settings.robokassa_hash_algorithm,
    ):
        db.log_event("payment_error", f"Robokassa signature mismatch for payment #{invoice_id}", technical_details=str(dict(post_data)))
        await notify_admins(bot, settings, f"Ошибка подписи Robokassa для платежа #{invoice_id}")
        return web.Response(text="bad sign", status=401)

    ok = await process_successful_payment(
        bot=bot,
        db=db,
        settings=settings,
        payment_id=invoice_id,
        out_sum=out_sum,
        source="robokassa_webhook",
    )
    if not ok:
        return web.Response(text="payment not found", status=404)
    return web.Response(text=f"OK{invoice_id}")


async def _back_to_bot(request: web.Request, fallback_text: str) -> web.Response:
    # После оплаты (SuccessUrl2/FailUrl2) сразу возвращаем человека в бота.
    try:
        username = (await request.app["bot"].me()).username
    except Exception:
        username = None
    if username:
        raise web.HTTPFound(f"https://t.me/{username}")
    return web.Response(text=fallback_text, content_type="text/plain")


async def robokassa_success(request: web.Request) -> web.Response:
    return await _back_to_bot(
        request, "Оплата прошла. Вернитесь в Telegram-бота: доступ активируется автоматически.")


async def robokassa_fail(request: web.Request) -> web.Response:
    return await _back_to_bot(
        request, "Оплата не завершена. Вернитесь в Telegram-бота и попробуйте снова.")


async def healthcheck(request: web.Request) -> web.Response:
    return web.Response(text="ok", content_type="text/plain")


async def run_webhook_server(*, bot: Bot, db: Database, settings: Settings) -> web.AppRunner:
    app = web.Application()
    app["bot"] = bot
    app["db"] = db
    app["settings"] = settings
    app["broadcast_jobs"] = {}
    app["broadcast_running"] = False
    app.add_routes(
        [
            web.get("/health", healthcheck),
            web.post(settings.robokassa_result_path, robokassa_result),
            web.get("/robokassa/success", robokassa_success),
            web.get("/robokassa/fail", robokassa_fail),
        ]
    )
    setup_admin_routes(app)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, settings.webhook_host, settings.webhook_port)
    await site.start()
    return runner
