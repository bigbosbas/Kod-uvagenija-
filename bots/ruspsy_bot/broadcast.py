import json
import logging
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

from telebot.apihelper import ApiTelegramException

import database as db

log = logging.getLogger(__name__)

WORKERS = 12
RATE_PER_SEC = 25
CHECKPOINT_SEC = 2
STATUS_REFRESH_SEC = 5

_rate_lock = threading.Lock()
_next_slot = [0.0]

_current = {"id": None}


def is_running():
    return _current["id"] is not None


def _throttle():
    interval = 1.0 / RATE_PER_SEC
    with _rate_lock:
        now = time.time()
        slot = max(now, _next_slot[0] + interval)
        _next_slot[0] = slot
        wait = slot - now
    if wait > 0:
        time.sleep(wait)


def start(bot, admin_id, audience, from_chat, msg_id, on_error, broadcast_id=None):
    if is_running():
        return None
    resuming = bool(broadcast_id)
    if not broadcast_id:
        broadcast_id = f"bc_{int(time.time())}_{admin_id}"
    _current["id"] = broadcast_id

    def worker():
        try:
            _run(bot, admin_id, audience, from_chat, msg_id, on_error, broadcast_id, resuming)
        except Exception as e:
            log.exception("Рассылка упала: %s", e)
            db.finalize_broadcast(broadcast_id, 0, 0, status="error")
            try:
                bot.send_message(admin_id, f"❌ Рассылка прервалась с ошибкой: {e}")
            except ApiTelegramException:
                pass
        finally:
            _current["id"] = None

    threading.Thread(target=worker, daemon=True, name="broadcast").start()
    return broadcast_id


def _run(bot, admin_id, audience, from_chat, msg_id, on_error, broadcast_id, resuming):
    all_users = db.audience(audience)
    already = db.get_broadcast_sent_ids(broadcast_id) if resuming else set()
    recipients = [uid for uid in all_users if uid not in already]

    if not recipients:
        bot.send_message(admin_id, "📭 Отправлять некому: все уже получили это сообщение.")
        db.finalize_broadcast(broadcast_id, len(already), 0)
        return

    db.create_broadcast(broadcast_id, audience, len(recipients),
                        json.dumps({"from_chat": from_chat, "msg_id": msg_id},
                                   ensure_ascii=False))

    total = len(recipients)
    eta = int(total / RATE_PER_SEC)
    mins, secs = divmod(eta, 60)
    eta_text = f"{mins} мин {secs} сек" if mins else f"{secs} сек"

    bot.send_message(
        admin_id,
        ("📨 <b>Дорассылка</b> — только тем, кому не дошло\n" if resuming
         else "📢 <b>Рассылка запущена</b>\n")
        + f"👥 Получателей: <b>{total}</b>\n⏳ Примерно: <b>{eta_text}</b>",
        parse_mode="HTML")

    counters = {"ok": 0, "failed": 0}
    done = threading.Event()
    status_msg = bot.send_message(
        admin_id, f"🔄 Статус\n👥 Всего: {total}\n✅ Доставлено: 0\n❌ Не доставлено: 0")

    def refresh_status():
        last = None
        while not done.is_set():
            time.sleep(STATUS_REFRESH_SEC)
            ok, failed = counters["ok"], counters["failed"]
            text = (f"🔄 Статус\n👥 Всего: {total}\n"
                    f"✅ Доставлено: {ok} ({ok / total * 100:.1f}%)\n"
                    f"❌ Не доставлено: {failed} ({failed / total * 100:.1f}%)")
            if text == last:
                continue
            last = text
            try:
                bot.edit_message_text(text, admin_id, status_msg.message_id)
            except ApiTelegramException:
                pass

    threading.Thread(target=refresh_status, daemon=True).start()

    lock = threading.Lock()
    buffer = []

    def send_one(user_id):
        delivered = False
        try:
            _throttle()
            bot.copy_message(user_id, from_chat, msg_id)
            delivered = True
        except ApiTelegramException as e:
            if e.error_code == 429:
                time.sleep(min(getattr(e, "retry_after", 5), 60))
                try:
                    _throttle()
                    bot.copy_message(user_id, from_chat, msg_id)
                    delivered = True
                except ApiTelegramException as e2:
                    on_error(user_id, e2)
            else:
                on_error(user_id, e)
        except Exception as e:
            log.warning("Рассылка, %s: %s", user_id, e)

        with lock:
            if delivered:
                counters["ok"] += 1
                buffer.append(user_id)
            else:
                counters["failed"] += 1

    with ThreadPoolExecutor(max_workers=WORKERS) as pool:
        futures = [pool.submit(send_one, uid) for uid in recipients]
        last_flush = time.time()
        for _ in as_completed(futures):
            if time.time() - last_flush >= CHECKPOINT_SEC:
                with lock:
                    chunk, buffer[:] = list(buffer), []
                db.mark_broadcast_sent_bulk(broadcast_id, chunk)
                last_flush = time.time()

    with lock:
        chunk, buffer[:] = list(buffer), []
    db.mark_broadcast_sent_bulk(broadcast_id, chunk)

    done.set()
    db.finalize_broadcast(broadcast_id, counters["ok"], counters["failed"])

    bot.send_message(
        admin_id,
        f"✅ <b>Рассылка завершена</b>\n\n"
        f"👥 Получателей: <b>{total}</b>\n"
        f"✅ Доставлено: <b>{counters['ok']}</b>\n"
        f"❌ Не доставлено: <b>{counters['failed']}</b>\n\n"
        f"<i>Не доставленные — это те, кто заблокировал бота: они помечены "
        f"и в следующие рассылки не попадут.</i>",
        parse_mode="HTML", reply_markup=_kb().kb_after_broadcast())


def _kb():
    import keyboards
    return keyboards
