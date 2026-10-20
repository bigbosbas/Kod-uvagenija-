from __future__ import annotations

import asyncio
import contextlib
import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from aiohttp import web
from aiogram import Bot
from aiogram.exceptions import TelegramForbiddenError, TelegramRetryAfter
from aiogram.utils.keyboard import InlineKeyboardBuilder

from bot.config import Settings
from bot.db import Database
from bot.keyboards import invite_keyboard
from bot.tg_webapp_auth import parse_init_data
from bot.telegram_admin_ops import build_invite_link, revoke_access
from bot.texts import format_subscription_expires_ru

ADMIN_ROOT = Path(__file__).resolve().parent.parent / "admin"

ALLOWED_SETTING_KEYS = frozenset(
    {
        "offer_url",
        "policy_url",
        "support_text",
        "channel_about_text",
        "tmpl_welcome",
        "promo_media_kind",
        "promo_media_file_id",
    }
)

MAX_PAGE = 100

BROADCAST_MAX_TEXT = 4000
BROADCAST_DELAY_SEC = 0.052
BROADCAST_MAX_BUTTONS = 8


def _row_to_dict(row: Any) -> dict[str, Any]:
    return {k: row[k] for k in row.keys()}


def _parse_int(val: str | None, default: int, *, min_v: int = 0, max_v: int = MAX_PAGE) -> int:
    try:
        n = int(val) if val is not None else default
    except ValueError:
        return default
    return max(min_v, min(n, max_v))


def _admin_from_request(request: web.Request) -> int | None:
    init = request.headers.get("X-Telegram-Init-Data", "")
    settings: Settings = request.app["settings"]
    parsed = parse_init_data(init, settings.bot_token)
    if not parsed or parsed["user_id"] not in settings.admin_ids:
        return None
    return int(parsed["user_id"])


def _json_error(msg: str, status: int = 400) -> web.Response:
    return web.json_response({"ok": False, "error": msg}, status=status)


def _validate_broadcast_buttons(raw: Any) -> list[dict[str, str]]:
    if raw is None:
        return []
    if not isinstance(raw, list):
        raise ValueError("buttons")
    out: list[dict[str, str]] = []
    for item in raw[:BROADCAST_MAX_BUTTONS]:
        if not isinstance(item, dict):
            continue
        text = str(item.get("text", "")).strip()[:64]
        url = str(item.get("url", "")).strip()[:2048]
        if not text or not url:
            continue
        parsed = urlparse(url)
        if parsed.scheme not in ("http", "https"):
            continue
        out.append({"text": text, "url": url})
    return out


def _broadcast_reply_markup(buttons: list[dict[str, str]]):
    if not buttons:
        return None
    kb = InlineKeyboardBuilder()
    for b in buttons:
        kb.button(text=b["text"], url=b["url"])
    kb.adjust(1)
    return kb.as_markup()


async def _run_broadcast_job(
    app: web.Application,
    job_id: str,
    text: str,
    segment: str,
    buttons: list[dict[str, str]],
) -> None:
    jobs: dict[str, dict[str, Any]] = app["broadcast_jobs"]
    st = jobs.get(job_id)
    if st is None:
        return
    bot: Bot = app["bot"]
    db: Database = app["db"]
    markup = _broadcast_reply_markup(buttons)
    try:
        ids = db.list_broadcast_recipient_ids(segment)
        st["total"] = len(ids)
        for uid in ids:
            while True:
                try:
                    await bot.send_message(
                        uid,
                        text,
                        reply_markup=markup,
                        disable_web_page_preview=True,
                        parse_mode=None,
                    )
                    st["sent"] += 1
                    break
                except TelegramRetryAfter as e:
                    await asyncio.sleep(float(e.retry_after) + 0.05)
                except TelegramForbiddenError:
                    st["skipped"] += 1
                    break
                except Exception:
                    st["failed"] += 1
                    break
            await asyncio.sleep(BROADCAST_DELAY_SEC)
        st["status"] = "done"
        st["finished_at"] = datetime.now(timezone.utc).isoformat()
        db.log_event(
            "broadcast_done",
            f"job={job_id} {segment} sent={st['sent']} fail={st['failed']} skip={st['skipped']}",
        )
    except Exception as exc:
        st["status"] = "error"
        st["error"] = str(exc)
        st["finished_at"] = datetime.now(timezone.utc).isoformat()
        db.log_event("broadcast_error", f"job={job_id}", error_text=str(exc))
    finally:
        app["broadcast_running"] = False


async def handle_broadcast_meta(_request: web.Request) -> web.Response:
    if _admin_from_request(_request) is None:
        return _json_error("forbidden", 403)
    segments = [
        {
            "id": "everyone",
            "title": "Все пользователи",
            "hint": "Кто запускал бота, не заблокирован",
        },
        {
            "id": "active_subscription",
            "title": "С активной подпиской",
            "hint": "Действующий доступ по дате",
        },
        {
            "id": "no_active_now",
            "title": "Без активной подписки",
            "hint": "Не заблокированы, сейчас нет оплаченного периода",
        },
        {
            "id": "expired",
            "title": "Просроченная подписка",
            "hint": "Срок вышел или статус просрочен",
        },
        {
            "id": "ever_paid",
            "title": "Когда-либо оплачивали",
            "hint": "Есть хотя бы один платёж «Оплачен»",
        },
        {
            "id": "never_paid",
            "title": "Никогда не оплачивали",
            "hint": "Нет успешных платежей",
        },
    ]
    return web.json_response(
        {
            "ok": True,
            "max_text": BROADCAST_MAX_TEXT,
            "delay_sec": BROADCAST_DELAY_SEC,
            "max_buttons": BROADCAST_MAX_BUTTONS,
            "segments": segments,
        }
    )


async def handle_broadcast_count(request: web.Request) -> web.Response:
    if _admin_from_request(request) is None:
        return _json_error("forbidden", 403)
    try:
        body = await request.json()
    except json.JSONDecodeError:
        return _json_error("invalid json")
    segment = str(body.get("segment", "")).strip()
    if segment not in Database.BROADCAST_SEGMENTS:
        return _json_error("unknown segment")
    db: Database = request.app["db"]
    try:
        n = db.count_broadcast_recipients(segment)
    except ValueError:
        return _json_error("unknown segment")
    return web.json_response({"ok": True, "count": n})


async def handle_broadcast_test(request: web.Request) -> web.Response:
    admin_id = _admin_from_request(request)
    if admin_id is None:
        return _json_error("forbidden", 403)
    try:
        body = await request.json()
    except json.JSONDecodeError:
        return _json_error("invalid json")
    text = str(body.get("text", "")).strip()
    if not text or len(text) > BROADCAST_MAX_TEXT:
        return _json_error(f"текст 1…{BROADCAST_MAX_TEXT} символов")
    try:
        buttons = _validate_broadcast_buttons(body.get("buttons"))
    except ValueError:
        return _json_error("некорректные кнопки")
    bot: Bot = request.app["bot"]
    markup = _broadcast_reply_markup(buttons)
    try:
        await bot.send_message(
            admin_id,
            "🧪 Тест рассылки (только вам):\n\n" + text,
            reply_markup=markup,
            disable_web_page_preview=True,
            parse_mode=None,
        )
    except Exception as exc:
        return _json_error(str(exc), 500)
    return web.json_response({"ok": True})


async def handle_broadcast_start(request: web.Request) -> web.Response:
    if _admin_from_request(request) is None:
        return _json_error("forbidden", 403)
    if request.app.get("broadcast_running"):
        return _json_error("Уже идёт рассылка. Дождитесь окончания.", 409)
    try:
        body = await request.json()
    except json.JSONDecodeError:
        return _json_error("invalid json")
    text = str(body.get("text", "")).strip()
    if not text or len(text) > BROADCAST_MAX_TEXT:
        return _json_error(f"текст 1…{BROADCAST_MAX_TEXT} символов")
    segment = str(body.get("segment", "")).strip()
    if segment not in Database.BROADCAST_SEGMENTS:
        return _json_error("unknown segment")
    try:
        buttons = _validate_broadcast_buttons(body.get("buttons"))
    except ValueError:
        return _json_error("некорректные кнопки")
    db: Database = request.app["db"]
    job_id = str(uuid.uuid4())
    st: dict[str, Any] = {
        "job_id": job_id,
        "status": "running",
        "segment": segment,
        "total": 0,
        "sent": 0,
        "failed": 0,
        "skipped": 0,
        "error": None,
        "started_at": datetime.now(timezone.utc).isoformat(),
        "finished_at": None,
    }
    request.app["broadcast_jobs"][job_id] = st
    request.app["broadcast_running"] = True
    db.log_event("broadcast_start", f"job={job_id} segment={segment} recipients~{db.count_broadcast_recipients(segment)}")
    asyncio.create_task(_run_broadcast_job(request.app, job_id, text, segment, buttons))
    return web.json_response({"ok": True, "job_id": job_id})


async def handle_broadcast_status(request: web.Request) -> web.Response:
    if _admin_from_request(request) is None:
        return _json_error("forbidden", 403)
    job_id = (request.query.get("job_id") or "").strip()
    if not job_id:
        return _json_error("job_id required")
    st = request.app["broadcast_jobs"].get(job_id)
    if st is None:
        return _json_error("not found", 404)
    return web.json_response({"ok": True, "job": st})


async def handle_admin_index(_request: web.Request) -> web.Response:
    index = ADMIN_ROOT / "index.html"
    if not index.is_file():
        return web.Response(text="admin UI missing", status=404)
    return web.FileResponse(index)


async def handle_admin_js(_request: web.Request) -> web.Response:
    path = ADMIN_ROOT / "app.js"
    if not path.is_file():
        return web.Response(text="// missing", status=404)
    return web.FileResponse(path, headers={"Content-Type": "application/javascript; charset=utf-8"})


async def handle_admin_stats(request: web.Request) -> web.Response:
    if _admin_from_request(request) is None:
        return _json_error("forbidden", 403)
    db: Database = request.app["db"]
    return web.json_response(
        {
            "ok": True,
            "users_total": db.count_users("all"),
            "users_active": db.count_users("active"),
            "users_expired": db.count_users("expired"),
            "users_blocked": db.count_users("blocked"),
            "payments_total": db.count_payments(),
            "payments_paid": db.count_payments("paid"),
        }
    )


async def handle_users_list(request: web.Request) -> web.Response:
    if _admin_from_request(request) is None:
        return _json_error("forbidden", 403)
    db: Database = request.app["db"]
    mode = (request.query.get("mode") or "all").strip()
    if mode not in {"all", "active", "expired", "blocked"}:
        mode = "all"
    q = (request.query.get("q") or "").strip()
    limit = _parse_int(request.query.get("limit"), 50, min_v=1, max_v=MAX_PAGE)
    offset = _parse_int(request.query.get("offset"), 0, min_v=0, max_v=1_000_000)
    if q:
        rows = db.search_users(q, limit=limit, offset=offset)
        total = db.count_search_users(q)
    else:
        rows = db.list_users(mode, limit=limit, offset=offset)
        total = db.count_users(mode)
    return web.json_response(
        {
            "ok": True,
            "users": [_row_to_dict(r) for r in rows],
            "total": total,
            "mode": mode,
            "limit": limit,
            "offset": offset,
        }
    )


async def handle_payments_list(request: web.Request) -> web.Response:
    if _admin_from_request(request) is None:
        return _json_error("forbidden", 403)
    db: Database = request.app["db"]
    status = (request.query.get("status") or "").strip() or None
    if status and status not in {"pending", "paid", "failed", "cancelled"}:
        status = None
    limit = _parse_int(request.query.get("limit"), 50, min_v=1, max_v=MAX_PAGE)
    offset = _parse_int(request.query.get("offset"), 0, min_v=0, max_v=1_000_000)
    rows = db.list_payments(status=status, limit=limit, offset=offset)
    total = db.count_payments(status)
    return web.json_response(
        {
            "ok": True,
            "payments": [_row_to_dict(r) for r in rows],
            "total": total,
            "limit": limit,
            "offset": offset,
        }
    )


async def handle_plans_list(request: web.Request) -> web.Response:
    if _admin_from_request(request) is None:
        return _json_error("forbidden", 403)
    db: Database = request.app["db"]
    plans = db.list_all_plans()
    return web.json_response(
        {
            "ok": True,
            "plans": [
                {
                    "id": p.id,
                    "code": p.code,
                    "title": p.title,
                    "price_rub": p.price_rub,
                    "duration_days": p.duration_days,
                    "description": p.description,
                    "is_active": p.is_active,
                }
                for p in plans
            ],
        }
    )


async def handle_plan_upsert(request: web.Request) -> web.Response:
    if _admin_from_request(request) is None:
        return _json_error("forbidden", 403)
    try:
        body = await request.json()
    except json.JSONDecodeError:
        return _json_error("invalid json")
    db: Database = request.app["db"]
    try:
        code = str(body.get("code", "")).strip()
        title = str(body.get("title", "")).strip()
        price_rub = int(body.get("price_rub"))
        duration_days = int(body.get("duration_days"))
        description = str(body.get("description", "")).strip()
        is_active = bool(body.get("is_active", True))
    except (TypeError, ValueError):
        return _json_error("bad fields")
    if not code or not title or price_rub < 0 or duration_days < 1:
        return _json_error("validation")
    db.upsert_plan(code, title, price_rub, duration_days, description, is_active)
    return web.json_response({"ok": True})


async def handle_plan_active(request: web.Request) -> web.Response:
    if _admin_from_request(request) is None:
        return _json_error("forbidden", 403)
    code = request.match_info.get("code", "").strip()
    if not code:
        return _json_error("code required")
    try:
        body = await request.json()
        active = bool(body.get("active"))
    except json.JSONDecodeError:
        return _json_error("invalid json")
    db: Database = request.app["db"]
    db.set_plan_active(code, active)
    return web.json_response({"ok": True})


async def handle_settings_get(request: web.Request) -> web.Response:
    if _admin_from_request(request) is None:
        return _json_error("forbidden", 403)
    db: Database = request.app["db"]
    settings: Settings = request.app["settings"]
    smap = db.list_settings()
    return web.json_response(
        {
            "ok": True,
            "settings": {k: smap.get(k, "") for k in sorted(ALLOWED_SETTING_KEYS)},
            "defaults": {
                "offer_url": settings.offer_url,
                "policy_url": settings.policy_url,
            },
            "robokassa_ready": bool(
                settings.robokassa_merchant_login
                and settings.robokassa_password1
                and settings.robokassa_password2
            ),
            "public_base_url": settings.public_base_url,
        }
    )


async def handle_settings_set(request: web.Request) -> web.Response:
    if _admin_from_request(request) is None:
        return _json_error("forbidden", 403)
    try:
        body = await request.json()
    except json.JSONDecodeError:
        return _json_error("invalid json")
    key = str(body.get("key", "")).strip()
    if key not in ALLOWED_SETTING_KEYS:
        return _json_error("key not allowed")
    value = body.get("value")
    if value is None:
        value = ""
    elif not isinstance(value, str):
        value = str(value)
    db: Database = request.app["db"]
    db.set_setting(key, value)
    return web.json_response({"ok": True})


async def handle_user_grant(request: web.Request) -> web.Response:
    if _admin_from_request(request) is None:
        return _json_error("forbidden", 403)
    try:
        uid = int(request.match_info["user_id"])
    except (KeyError, ValueError):
        return _json_error("bad user_id")
    try:
        body = await request.json()
    except json.JSONDecodeError:
        return _json_error("invalid json")
    db: Database = request.app["db"]
    bot: Bot = request.app["bot"]
    settings: Settings = request.app["settings"]
    now = db._now_dt()
    expires_date_str = body.get("expires_date")
    if expires_date_str is not None and str(expires_date_str).strip() != "":
        exp = db.parse_expires_date_moscow_end(str(expires_date_str))
        if exp is None:
            return _json_error("expires_date: use YYYY-MM-DD")
        if exp <= now:
            return _json_error("дата должна быть в будущем")
        row = db.manual_set_subscription_expires_at(uid, exp)
    else:
        try:
            days = int(body.get("days", 0))
        except (TypeError, ValueError):
            return _json_error("invalid days")
        if days < 1 or days > 3650:
            return _json_error("days 1..3650")
        user_before = db.get_user_status(uid)
        plan_id = int(user_before["current_plan_id"]) if user_before and user_before["current_plan_id"] else None
        if plan_id is None:
            plans = db.list_active_plans()
            plan_id = int(plans[0].id) if plans else None
        row = db.manual_extend_subscription(uid, days, plan_id)
    if row is None:
        return _json_error("user not found", 404)
    db.ensure_plan_for_manual_grant(uid)
    row = db.get_user_status(uid)
    if row is None:
        return _json_error("user not found", 404)

    raw_notify = body.get("notify_user", True)
    if isinstance(raw_notify, str):
        notify_user = raw_notify.strip().lower() not in {"0", "false", "no", ""}
    else:
        notify_user = bool(raw_notify)

    plan = db.get_plan_by_id(row["current_plan_id"]) if row["current_plan_id"] else None
    if plan is not None and notify_user:
        link = await build_invite_link(bot, settings, uid, plan.code)
        db.update_user_invite(uid, link)
        with contextlib.suppress(Exception):
            await bot.send_message(
                uid,
                f"Доступ выдан вручную.\nДоступ активен до: {format_subscription_expires_ru(row['subscription_expires_at'])}",
                reply_markup=invite_keyboard(link),
            )
    return web.json_response({"ok": True, "subscription_expires_at": row["subscription_expires_at"]})


async def handle_user_revoke(request: web.Request) -> web.Response:
    if _admin_from_request(request) is None:
        return _json_error("forbidden", 403)
    try:
        uid = int(request.match_info["user_id"])
    except (KeyError, ValueError):
        return _json_error("bad user_id")
    db: Database = request.app["db"]
    bot: Bot = request.app["bot"]
    settings: Settings = request.app["settings"]
    await revoke_access(bot, settings, uid)
    db.expire_subscription(uid)
    return web.json_response({"ok": True})


async def handle_user_block(request: web.Request) -> web.Response:
    if _admin_from_request(request) is None:
        return _json_error("forbidden", 403)
    try:
        uid = int(request.match_info["user_id"])
    except (KeyError, ValueError):
        return _json_error("bad user_id")
    try:
        body = await request.json()
        blocked = bool(body.get("blocked"))
    except json.JSONDecodeError:
        return _json_error("invalid json")
    db: Database = request.app["db"]
    bot: Bot = request.app["bot"]
    settings: Settings = request.app["settings"]
    db.set_user_blocked(uid, blocked)
    if blocked:
        await revoke_access(bot, settings, uid)
    return web.json_response({"ok": True})


async def handle_user_payments(request: web.Request) -> web.Response:
    if _admin_from_request(request) is None:
        return _json_error("forbidden", 403)
    try:
        uid = int(request.match_info["user_id"])
    except (KeyError, ValueError):
        return _json_error("bad user_id")
    db: Database = request.app["db"]
    limit = _parse_int(request.query.get("limit"), 30, min_v=1, max_v=MAX_PAGE)
    rows = db.get_user_payment_history(uid, limit=limit)
    return web.json_response({"ok": True, "payments": [_row_to_dict(r) for r in rows]})


def setup_admin_routes(app: web.Application) -> None:
    app.router.add_get("/admin/app.js", handle_admin_js)
    app.router.add_get("/admin/", handle_admin_index)
    app.router.add_get("/admin", handle_admin_index)
    app.router.add_get("/api/admin/stats", handle_admin_stats)
    app.router.add_get("/api/admin/users", handle_users_list)
    app.router.add_get("/api/admin/payments", handle_payments_list)
    app.router.add_get("/api/admin/plans", handle_plans_list)
    app.router.add_post("/api/admin/plans", handle_plan_upsert)
    app.router.add_post("/api/admin/plans/{code}/active", handle_plan_active)
    app.router.add_get("/api/admin/settings", handle_settings_get)
    app.router.add_post("/api/admin/settings", handle_settings_set)
    app.router.add_post("/api/admin/users/{user_id}/grant", handle_user_grant)
    app.router.add_post("/api/admin/users/{user_id}/revoke", handle_user_revoke)
    app.router.add_post("/api/admin/users/{user_id}/block", handle_user_block)
    app.router.add_get("/api/admin/users/{user_id}/payments", handle_user_payments)
    app.router.add_get("/api/admin/broadcast/meta", handle_broadcast_meta)
    app.router.add_post("/api/admin/broadcast/count", handle_broadcast_count)
    app.router.add_post("/api/admin/broadcast/test", handle_broadcast_test)
    app.router.add_post("/api/admin/broadcast/start", handle_broadcast_start)
    app.router.add_get("/api/admin/broadcast/status", handle_broadcast_status)
