import json
import logging
import threading
import time
from datetime import datetime

import telebot
from telebot import apihelper, types
from telebot.apihelper import ApiTelegramException

import broadcast
import config
import content
import database as db
import inbox
import keyboards as kb
import products

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
    handlers=[logging.FileHandler("bot.log", encoding="utf-8"), logging.StreamHandler()],
)
log = logging.getLogger(__name__)

if config.TELEGRAM_PROXY:
    apihelper.proxy = {"https": config.TELEGRAM_PROXY}

bot = telebot.TeleBot(config.BOT_TOKEN, parse_mode="HTML")

ADMIN_STATE = {}

USER_STATE = {}

BOT_USERNAME = [None]

_SEQ_LOCKS = {}
_SEQ_GUARD = threading.Lock()


def _seq_lock(chat_id):
    with _SEQ_GUARD:
        return _SEQ_LOCKS.setdefault(chat_id, threading.Lock())

SEND_PAUSE = 0.05
BULK_PAUSE = 0.05


def is_admin(user_id):
    return user_id in config.ADMIN_IDS


BLOCK_MARKERS = ("bot was blocked", "user is deactivated", "chat not found",
                 "user is deleted", "bot can't initiate conversation")


def handle_send_error(chat_id, e):
    desc = (getattr(e, "description", "") or "").lower()
    if e.error_code == 403 or any(m in desc for m in BLOCK_MARKERS):
        db.mark_blocked(chat_id)
        log.info("Пользователь %s недоступен: %s", chat_id, desc)
        return True
    log.warning("Ошибка отправки %s: %s", chat_id, e)
    return False


def notify_admins(text, reply_markup=None):
    for admin in config.ADMIN_IDS:
        safe_send(admin, text, reply_markup=reply_markup)


def notify_tech(text):
    for admin in config.TECH_ADMIN_IDS:
        safe_send(admin, text)


def safe_send(chat_id, text, reply_markup=None, **kw):
    try:
        return bot.send_message(chat_id, text, reply_markup=reply_markup,
                                disable_web_page_preview=True, **kw)
    except ApiTelegramException as e:
        handle_send_error(chat_id, e)
        return None


def typing_pause(chat_id, next_text):
    delay = min(config.MSG_DELAY_MAX,
                max(config.MSG_DELAY_MIN, len(next_text) / config.MSG_READ_SPEED))
    if not config.TYPING_ENABLED:
        time.sleep(delay)
        return
    left = delay
    while left > 0:
        try:
            bot.send_chat_action(chat_id, "typing")
        except ApiTelegramException:
            return
        chunk = min(4.5, left)
        time.sleep(chunk)
        left -= chunk


def send_sequence(chat_id, parts, final_markup=None, cover_slot=None):
    with _seq_lock(chat_id):
        if cover_slot:
            send_cover(chat_id, cover_slot)
        last = len(parts) - 1
        for i, txt in enumerate(parts):
            typing_pause(chat_id, txt)
            markup = final_markup if i == last else None
            if safe_send(chat_id, txt, reply_markup=markup) is None and db.is_blocked(chat_id):
                return


def send_sequence_async(chat_id, parts, final_markup=None, cover_slot=None):
    threading.Thread(target=send_sequence,
                     args=(chat_id, parts, final_markup, cover_slot),
                     daemon=True).start()


def send_cover(chat_id, slot):
    mats = db.get_materials(f"cover_{slot}")
    if mats:
        m = mats[0]
        senders = {"video": bot.send_video, "photo": bot.send_photo,
                   "animation": bot.send_animation, "document": bot.send_document}
        try:
            senders.get(m["kind"], bot.send_document)(
                chat_id, m["file_id"], caption=m["caption"] or None)
            return
        except ApiTelegramException as e:
            log.warning("Не отправлена обложка %s: %s", slot, e)
    safe_send(chat_id, content.COVER_PLACEHOLDER)


def parse_start_payload(message):
    parts = (message.text or "").split(maxsplit=1)
    if len(parts) < 2:
        return "direct", None
    payload = parts[1].strip().lower()

    link = db.get_link(payload)
    if link:
        return link["slug"], link["product"]

    source, product = "direct", None
    for token in payload.replace("-", "_").split("_"):
        if token in ("ig", "instagram"):
            source = "ig"
        elif token in ("yt", "youtube"):
            source = "yt"
        elif token in ("kod", "kodu", "uvazhenie"):
            product = config.P_KOD
        elif token in ("peresborka", "per", "scenario"):
            product = config.P_PERESBORKA
    return source, product


@bot.message_handler(commands=["start"])
def cmd_start(message):
    uid = message.from_user.id
    source, product = parse_start_payload(message)
    db.upsert_user(uid, message.from_user.username, message.from_user.first_name, source)
    db.log_event(uid, "start", f"source={source};product={product or '-'}")

    if not db.has_consent(uid):
        ADMIN_STATE.pop(uid, None)
        safe_send(uid, content.CONSENT, reply_markup=kb.kb_consent(product))
        db.log_event(uid, "consent_shown", product or "")
        return

    _route_after_consent(uid, product)


def _route_after_consent(uid, product=None):
    if product:
        send_product(uid, product)
    else:
        send_sequence_async(uid, content.INTRO, final_markup=kb.kb_segments(),
                            cover_slot="intro")
        db.log_event(uid, "intro_shown")


@bot.callback_query_handler(func=lambda c: c.data.startswith("consent:yes"))
def cb_consent(call):
    uid = call.from_user.id
    parts = call.data.split(":")
    product = parts[2] if len(parts) > 2 and parts[2] in config.PRODUCT_TITLES else None
    db.set_consent(uid)
    db.log_event(uid, "consent_given", product or "")
    try:
        bot.edit_message_reply_markup(uid, call.message.message_id, reply_markup=None)
    except ApiTelegramException:
        pass
    bot.answer_callback_query(call.id, "Спасибо")
    _route_after_consent(uid, product)


@bot.callback_query_handler(func=lambda c: c.data.startswith("seg:"))
def cb_segment(call):
    uid = call.from_user.id
    product = call.data.split(":", 1)[1]
    bot.answer_callback_query(call.id)
    send_product(uid, product)


def send_product(uid, product):
    db.set_segment(uid, product)
    db.log_event(uid, "product_shown", product)
    send_sequence_async(uid, content.PAGES[product],
                        final_markup=kb.kb_product(product, uid), cover_slot=product)

    if not db.has_purchase(uid, product):
        db.set_active_drip(uid, product)
        db.start_drip(uid, product, config.DRIP_HOURS[0])


@bot.callback_query_handler(func=lambda c: c.data.startswith("mine:"))
def cb_mine(call):
    uid = call.from_user.id
    product = call.data.split(":", 1)[1]
    bot.answer_callback_query(call.id)
    if not db.has_purchase(uid, product):
        send_product(uid, product)
        return
    if product in config.CHANNEL_PRODUCTS:
        deliver_access(uid, product, db.get_invite(uid, product), label=f"повторно, user {uid}")
    else:
        deliver_materials(uid, product)


@bot.callback_query_handler(func=lambda c: c.data.startswith("drip:"))
def cb_drips(call):
    if not is_admin(call.from_user.id):
        return
    on = call.data.split(":", 1)[1] == "on"
    db.set_setting("drips_enabled", "1" if on else "0")
    db.log_event(call.from_user.id, "drips_toggled", "on" if on else "off")
    bot.answer_callback_query(call.id, "Напоминания включены" if on else "Напоминания выключены")
    s = db.stats()
    panel(call.from_user.id,
          ("⏰ <b>Напоминания включены.</b>\n\nЛюди, не купившие курс, снова будут получать "
           "цепочку из 5 сообщений: через 1, 2, 3, 5 и 9 дней после просмотра страницы."
           if on else
           "⏰ <b>Напоминания выключены.</b>\n\nБот перестал отправлять дожимы. Очередь "
           "сохранена: если включить обратно, каждый продолжит с того шага, где остановился.")
          + f"\n\nСейчас в очереди: <b>{s['drip_active']}</b> · "
            f"отписались от напоминаний: {s['drip_muted']}",
          kb.kb_admin())


@bot.callback_query_handler(func=lambda c: c.data.startswith("notify:"))
def cb_notify(call):
    uid = call.from_user.id
    product = call.data.split(":", 1)[1]
    title = config.PRODUCT_TITLES[product]

    if products.get(product)["enabled"]:
        bot.answer_callback_query(call.id, "Продажи уже открыты")
        send_product(uid, product)
        return

    db.log_event(uid, "wants_notify", product)
    bot.answer_callback_query(call.id, "Сообщу, как откроем")
    safe_send(uid, f"Записал. Как только продажи «{title}» откроются — напишу вам первым.")

    uname = f"@{call.from_user.username}" if call.from_user.username else "без username"
    notify_admins(f"🔔 Ждёт старта продаж «{title}»\n"
                  f"{call.from_user.first_name} ({uname}) · <code>{uid}</code>")


@bot.callback_query_handler(func=lambda c: c.data.startswith("request:"))
def cb_request(call):
    uid = call.from_user.id
    product = call.data.split(":", 1)[1]
    title = config.PRODUCT_TITLES[product]
    db.log_event(uid, "purchase_request", product)
    bot.answer_callback_query(call.id, "Заявка отправлена")
    safe_send(uid, f"Заявка на курс «{title}» принята — с вами свяжутся "
                   f"и подскажут, как оплатить.\n\nВопросы: {config.SUPPORT_USERNAME}")

    uname = f"@{call.from_user.username}" if call.from_user.username else "без username"
    m = types.InlineKeyboardMarkup()
    m.add(types.InlineKeyboardButton("✅ Открыть доступ",
                                     callback_data=f"grant:{uid}:{product}", style=kb.GREEN))
    notify_admins(f"🛒 <b>Заявка на покупку</b>\n\nКурс: {title}\n"
                  f"{call.from_user.first_name} ({uname})\nID: <code>{uid}</code>",
                  reply_markup=m)


def deliver_access(uid, product, invite_link=None, label=""):
    title = config.PRODUCT_TITLES[product]
    if product in config.CHANNEL_PRODUCTS:
        invite_link = invite_link or db.get_invite(uid, product)
        if invite_link:
            safe_send(uid, content.BUY_PAID.format(title=title, link=invite_link),
                      reply_markup=kb.kb_channel(invite_link))
        else:
            safe_send(uid, content.BUY_PAID_NO_LINK)
            notify_tech(f"⚠️ Не удалось выпустить ссылку в канал для "
                        f"<code>{uid}</code> ({title}) — выдайте вручную.")
    else:
        safe_send(uid, content.BUY_PAID_FILES.format(title=title))
    deliver_materials(uid, product)
    return invite_link


@bot.callback_query_handler(func=lambda c: c.data.startswith("mute:"))
def cb_mute(call):
    uid = call.from_user.id
    product = call.data.split(":", 1)[1]
    db.stop_drip(uid, product, mute=True)
    db.log_event(uid, "drip_muted", product)
    bot.answer_callback_query(call.id, "Больше не напомню")
    safe_send(uid, "Хорошо, по этому курсу больше писать не буду.")


@bot.message_handler(commands=["menu", "books"])
def cmd_menu(message):
    show_nav(message.from_user.id)


def show_nav(uid):
    db.log_event(uid, "nav_opened")
    safe_send(uid, content.NAV_TEXT, reply_markup=kb.kb_nav(uid))


@bot.callback_query_handler(func=lambda c: c.data.startswith("nav:"))
def cb_nav(call):
    uid = call.from_user.id
    action = call.data.split(":", 1)[1]
    bot.answer_callback_query(call.id)

    if action == "intro":
        send_sequence_async(uid, content.INTRO, final_markup=kb.kb_segments(),
                            cover_slot="intro")
        db.log_event(uid, "intro_shown")
    elif action == "mine":
        cmd_materials(call)
    else:
        show_nav(uid)


def show_books(uid):
    db.log_event(uid, "books_opened")
    show_nav(uid)


@bot.callback_query_handler(func=lambda c: c.data == "books:list")
def cb_books_list(call):
    bot.answer_callback_query(call.id)
    show_books(call.from_user.id)


@bot.callback_query_handler(func=lambda c: c.data.startswith("book:"))
def cb_book(call):
    slug = call.data.split(":", 1)[1]
    book = next((b for b in content.BOOKS if b["slug"] == slug), None)
    bot.answer_callback_query(call.id)
    if not book:
        safe_send(call.from_user.id, content.BOOKS_EMPTY)
        return
    db.log_event(call.from_user.id, "book_shown", slug)
    send_sequence_async(call.from_user.id, book["text"], final_markup=kb.kb_book(book))


@bot.message_handler(commands=["materials"])
def cmd_materials(message):
    uid = message.from_user.id
    got = False
    for product in config.ALL_PRODUCTS:
        if db.has_purchase(uid, product):
            if product in config.CHANNEL_PRODUCTS:
                deliver_access(uid, product, db.get_invite(uid, product),
                               label=f"повторно, user {uid}")
            else:
                deliver_materials(uid, product)
            got = True
    if not got:
        safe_send(uid, "Пока нет открытых курсов. Если вы только что оплатили — "
                       "откройте экран оплаты и нажмите «Проверить оплату»: "
                       "доступ выдаётся автоматически после подтверждения платежа.")


@bot.message_handler(commands=["stop"])
def cmd_stop(message):
    uid = message.from_user.id
    db.stop_drip(uid, mute=True)
    db.log_event(uid, "unsubscribed")
    safe_send(uid, content.STOP_TEXT)


@bot.message_handler(commands=["help"])
def cmd_help(message):
    safe_send(message.from_user.id,
              content.HELP_TEXT.format(support=config.SUPPORT_USERNAME))


def deliver_materials(uid, product):
    mats = db.get_materials(product)
    title = config.PRODUCT_TITLES[product]

    if not mats:
        safe_send(uid, content.NO_MATERIALS)
        notify_tech(f"⚠️ Материалы курса «{title}» не загружены, "
                    f"пользователю <code>{uid}</code> нечего выдать.")
        return

    safe_send(uid, f"<b>{title}</b>\n\n{content.AFTER_PURCHASE}")
    for m in mats:
        try:
            if m["kind"] == "video":
                bot.send_video(uid, m["file_id"], caption=m["caption"] or None)
            else:
                bot.send_document(uid, m["file_id"], caption=m["caption"] or None)
            time.sleep(SEND_PAUSE)
        except ApiTelegramException as e:
            log.warning("Не отправлен материал %s пользователю %s: %s", m["id"], uid, e)
    db.log_event(uid, "materials_sent", product)


@bot.message_handler(commands=["admin"])
def cmd_admin(message):
    if not is_admin(message.from_user.id):
        return
    uid = message.from_user.id
    ADMIN_STATE.pop(uid, None)
    forget_input(message)
    drop_panel(uid)
    panel(uid, "<b>Панель управления</b>", kb.kb_admin())


@bot.callback_query_handler(func=lambda c: c.data.startswith("adm:"))
def cb_admin(call):
    if not is_admin(call.from_user.id):
        return
    uid = call.from_user.id
    action = call.data.split(":", 1)[1]
    bot.answer_callback_query(call.id)

    if action == "home":
        ADMIN_STATE.pop(uid, None)
        screen(call, "<b>Панель управления</b>", kb.kb_admin())

    elif action == "stats":
        panel(uid, stats_text(0), kb.kb_stats(0))

    elif action == "products":
        ADMIN_STATE.pop(uid, None)
        states = products_state()
        panel(uid, products_screen_text(states), kb.kb_products_settings(states))

    elif action == "links":
        ADMIN_STATE.pop(uid, None)
        panel(uid, links_screen_text(), kb.kb_links(db.links_with_stats()))

    elif action == "excel":
        screen(call, "Собираю отчёт…")
        threading.Thread(target=_send_excel, args=(uid,), daemon=True).start()

    elif action == "bcast":
        screen(call, "Кому отправляем?", kb.kb_audience())

    elif action == "mat":
        screen(call, "Материалы какого курса загружаем?", kb.kb_products("matadd"))

    elif action == "photo":
        screen(call, "Какую обложку меняем?\n\n"
                     "Где обложка не загружена, пользователь видит заглушку "
                     "«тут будет фото».", kb.kb_cover_slots())

    elif action == "grant":
        ADMIN_STATE[uid] = {"step": "grant_user"}
        screen(call, "Пришлите ID пользователя или @username.\n\nЗатем выберете курс.")


def products_state():
    out = {}
    for slug in config.ALL_PRODUCTS:
        st = products.get(slug)
        st["price_text"] = products.price_text(slug)
        out[slug] = st
    return out


def products_screen_text(states):
    lines = ["<b>⚙️ Продукты</b>\n"]
    for slug, st in states.items():
        where = "оплата на сайте " + config.LANDING_URLS[slug].split("/")[2]
        status = "🟢 продаётся" if st["enabled"] else "🔴 продажа выключена"
        lines.append(f"<b>{config.PRODUCT_TITLES[slug]}</b>\n"
                     f"{status} · {st['price_text']}\n<i>{where}</i>\n")
    lines.append("<i>Пока продажа выключена, на странице курса вместо кнопки покупки — "
                 "«Сообщить о старте продаж». Люди остаются в воронке, заявки видно в статистике.</i>\n\n"
                 "<i>Цена здесь — только подпись на кнопке. Если меняете цену на сайте, "
                 "поменяйте и тут.</i>")
    return "\n".join(lines)


@bot.callback_query_handler(func=lambda c: c.data.startswith("prod:"))
def cb_products(call):
    if not is_admin(call.from_user.id):
        return
    uid = call.from_user.id
    _, action, slug = call.data.split(":")

    if action == "price":
        ADMIN_STATE[uid] = {"step": "product_price", "data": {"slug": slug}}
        bot.answer_callback_query(call.id)
        screen(call, f"Новая цена курса «{config.PRODUCT_TITLES[slug]}» в рублях.\n\n"
                     f"Пришлите числом, например: <code>15000</code>")
        return

    products.set_enabled(slug, action == "on")
    bot.answer_callback_query(call.id, "Включено" if action == "on" else "Выключено")

    states = products_state()
    screen(call, products_screen_text(states), kb.kb_products_settings(states))


ADMIN_PANEL = {}


def drop_panel(uid):
    info = ADMIN_PANEL.pop(uid, None)
    if not info:
        return
    try:
        bot.delete_message(uid, info["id"])
    except ApiTelegramException:
        pass


def panel(uid, text, markup=None):
    info = ADMIN_PANEL.get(uid)
    if info and not info["media"]:
        try:
            bot.edit_message_text(text, uid, info["id"], reply_markup=markup,
                                  disable_web_page_preview=True)
            return
        except ApiTelegramException as e:
            if "message is not modified" in (e.description or ""):
                return
    drop_panel(uid)
    m = safe_send(uid, text, reply_markup=markup)
    if m:
        ADMIN_PANEL[uid] = {"id": m.message_id, "media": False}


def panel_media(uid, kind, file_id, caption, markup=None):
    drop_panel(uid)
    senders = {"photo": bot.send_photo, "video": bot.send_video,
               "animation": bot.send_animation, "document": bot.send_document}
    try:
        m = senders.get(kind, bot.send_document)(uid, file_id, caption=caption,
                                                 reply_markup=markup)
        ADMIN_PANEL[uid] = {"id": m.message_id, "media": True}
    except ApiTelegramException as e:
        log.warning("Не показал вложение %s: %s", kind, e)
        panel(uid, caption + "\n\n⚠️ Файл не открылся — возможно, он удалён из Telegram.",
              markup)


def screen(call, text, markup=None):
    panel(call.from_user.id, text, markup)


def forget_input(message):
    try:
        bot.delete_message(message.chat.id, message.message_id)
    except ApiTelegramException:
        pass


def links_screen_text():
    rows = db.links_with_stats()
    if not rows:
        return ("<b>🔗 Ссылки</b>\n\nСсылок пока нет.\n\n"
                "Ссылка — это отдельный вход в бота с меткой: видно, сколько людей "
                "пришло именно по ней, сколько дошло до выбора курса и сколько купило. "
                "Удобно для рекламы: своя ссылка на канал, на пост, на блогера.")
    me = BOT_USERNAME[0] or "ruspsy_bot"
    lines = ["<b>🔗 Ссылки</b>\n"]
    for l in rows:
        target = {"peresborka": "→ сразу «Пересборка»", "kod": "→ сразу «Код уважения»"}.get(
            l["product"], "→ диагностика")
        lines.append(
            f"<b>{l['title']}</b> {target}\n"
            f"<code>https://t.me/{me}?start={l['slug']}</code>\n"
            f"Пришло: <b>{l['starts']}</b> · согласие: {l['consents']} · "
            f"выбрали курс: {l['segments']} · купили: <b>{l['purchases']}</b>\n")
    lines.append("<i>Кнопка с 🗑 удаляет ссылку. Статистика уже пришедших сохранится.</i>")
    return "\n".join(lines)


@bot.callback_query_handler(func=lambda c: c.data.startswith("lnk"))
def cb_links(call):
    if not is_admin(call.from_user.id):
        return
    uid = call.from_user.id
    data = call.data
    bot.answer_callback_query(call.id)

    if data == "lnk:new":
        ADMIN_STATE[uid] = {"step": "link_title"}
        screen(call, "Как назовём ссылку?\n\nНапример: «Пост в канале 12 марта», "
                     "«Reels про границы», «Блогер Аня».")
        return

    if data.startswith("lnk:del:"):
        db.delete_link(data.split(":", 2)[2])
        screen(call, links_screen_text(), kb.kb_links(db.links_with_stats()))
        return

    if data.startswith("lnkt:"):
        st = ADMIN_STATE.get(uid, {})
        title = st.get("data", {}).get("title")
        if not title:
            screen(call, "Сессия истекла, начните заново.", kb.kb_admin())
            return
        product = data.split(":", 1)[1]
        product = None if product == "-" else product
        slug = make_slug(title)
        db.add_link(slug, title, product)
        ADMIN_STATE.pop(uid, None)
        screen(call, links_screen_text(), kb.kb_links(db.links_with_stats()))


def translit(text):
    table = str.maketrans({
        "а": "a", "б": "b", "в": "v", "г": "g", "д": "d", "е": "e", "ё": "e", "ж": "zh",
        "з": "z", "и": "i", "й": "y", "к": "k", "л": "l", "м": "m", "н": "n", "о": "o",
        "п": "p", "р": "r", "с": "s", "т": "t", "у": "u", "ф": "f", "х": "h", "ц": "c",
        "ч": "ch", "ш": "sh", "щ": "sch", "ъ": "", "ы": "y", "ь": "", "э": "e",
        "ю": "yu", "я": "ya", " ": "_", "-": "_"})
    out = "".join(ch for ch in (text or "").strip().lower().translate(table)
                  if ch.isalnum() or ch == "_")
    return out.strip("_")


def make_slug(title):
    base = (translit(title)[:40].strip("_") or "link")
    slug, n = base, 2
    while db.get_link(slug):
        slug = f"{base}_{n}"
        n += 1
    return slug


PERIOD_NAMES = {1: "сегодня", 7: "за 7 дней", 30: "за 30 дней", 0: "за всё время"}


def money(v):
    return f"{int(v or 0):,} ₽".replace(",", " ")


def stats_text(days):
    r = db.period_report(days or None)
    pct = lambda part, whole: f"{part / whole * 100:.0f}%" if whole else "—"
    check = money(r["revenue"] / r["paid"]) if r["paid"] else "—"

    lines = [f"<b>📊 Статистика — {PERIOD_NAMES.get(days, '')}</b>\n",
             f"💰 Выручка: <b>{money(r['revenue'])}</b>",
             f"💳 Оплат: <b>{r['paid']}</b> · средний чек: {check}"]

    by_product = db.revenue_by_product(days or None)
    if by_product:
        lines.append("")
        for x in by_product:
            lines.append(f"   {config.PRODUCT_TITLES.get(x['product'], x['product'])} — "
                         f"{x['n']} шт · {money(x['total'])}")

    lines += ["", "<b>Воронка</b>",
              f"Пришли: <b>{r['users']}</b>",
              f"Дали согласие: {r['consents']} ({pct(r['consents'], r['users'])})",
              f"Открыли курс: {r['product_views']}",
              f"Оформили заказ: {r['orders']}",
              f"Оплатили: <b>{r['paid']}</b> ({pct(r['paid'], r['users'])} от пришедших)",
              "", f"Напоминаний отправлено: {r['drips']}",
              f"Заблокировали бота: {r['blocked']}",
              f"Заходили в каталог: {r['books_opened']}"]
    return "\n".join(lines)


def payments_text():
    rows = db.paid_orders()
    if not rows:
        return "<b>💳 История оплат</b>\n\nОплат пока не было."
    total = sum(x["amount_rub"] or 0 for x in rows)
    lines = [f"<b>💳 История оплат</b>\n\nВсего: <b>{len(rows)}</b> на <b>{money(total)}</b>\n"]
    for x in rows[:20]:
        who = f"@{x['username']}" if x["username"] else (x["first_name"] or f"id{x['user_id']}")
        when = (x["paid_at"] or "")[:16].replace("T", " ")
        lines.append(f"{when} · {config.PRODUCT_TITLES.get(x['product'], x['product'])}\n"
                     f"   {money(x['amount_rub'])} · {who} · {x['email'] or 'без почты'}")
    if len(rows) > 20:
        lines.append(f"\n<i>Показаны последние 20 из {len(rows)}. Полный список — в Excel.</i>")
    return "\n".join(lines)


def months_text():
    rows = db.monthly_stats()
    if not rows:
        return "<b>📅 По месяцам</b>\n\nОплат пока не было."
    names = {"01": "январь", "02": "февраль", "03": "март", "04": "апрель", "05": "май",
             "06": "июнь", "07": "июль", "08": "август", "09": "сентябрь", "10": "октябрь",
             "11": "ноябрь", "12": "декабрь"}
    lines = ["<b>📅 Выручка по месяцам</b>\n"]
    for r in rows:
        year, month = r["month"].split("-")
        lines.append(f"{names.get(month, month)} {year}: <b>{money(r['revenue'])}</b> "
                     f"· {r['paid']} оплат")
    return "\n".join(lines)


def sources_text():
    rows = db.source_report()
    titles = {"ig": "Instagram", "yt": "YouTube", "direct": "Прямой заход"}
    lines = ["<b>🔗 Откуда приходят</b>\n"]
    for r in rows:
        name = titles.get(r["source"], r["source"] or "не указан")
        link = db.get_link(r["source"] or "")
        if link:
            name = link["title"]
        lines.append(f"<b>{name}</b>\n"
                     f"   пришло {r['users']} · согласие {r['consents']} · "
                     f"выбрали курс {r['segments']} · купили <b>{r['buyers']}</b>")
    return "\n".join(lines)


@bot.callback_query_handler(func=lambda c: c.data.startswith("st:"))
def cb_stats(call):
    if not is_admin(call.from_user.id):
        return
    uid = call.from_user.id
    parts = call.data.split(":")
    bot.answer_callback_query(call.id)

    if parts[1] == "period":
        days = int(parts[2])
        panel(uid, stats_text(days), kb.kb_stats(days))
    elif parts[1] == "pay":
        panel(uid, payments_text(), kb.kb_stats_back())
    elif parts[1] == "months":
        panel(uid, months_text(), kb.kb_stats_back())
    elif parts[1] == "src":
        panel(uid, sources_text(), kb.kb_stats_back())


def _send_excel(uid):
    try:
        import excel_report
        name, buf = excel_report.build_report()
        drop_panel(uid)
        bot.send_document(uid, buf, visible_file_name=name,
                          caption="📥 Отчёт: дашборд, воронка, пользователи, покупки, "
                                  "динамика по дням, дожимы и журнал событий.")
        panel(uid, "<b>Панель управления</b>", kb.kb_admin())
    except Exception as e:
        log.exception("Не собрался Excel-отчёт: %s", e)
        panel(uid, f"⚠️ Не получилось собрать отчёт: {e}", kb.kb_admin())


@bot.callback_query_handler(func=lambda c: c.data.startswith("aud:"))
def cb_audience(call):
    if not is_admin(call.from_user.id):
        return
    uid = call.from_user.id
    key = call.data.split(":", 1)[1]
    users = db.audience(key)
    ADMIN_STATE[uid] = {"step": "bcast_text", "data": {"audience": key, "count": len(users)}}
    bot.answer_callback_query(call.id)
    screen(call, f"Получателей: <b>{len(users)}</b>\n\n"
                 f"Пришлите текст рассылки одним сообщением.\n"
                 f"Можно с фото или файлом — отправлю как есть.")


@bot.callback_query_handler(func=lambda c: c.data.startswith("matadd:"))
def cb_matadd(call):
    if not is_admin(call.from_user.id):
        return
    uid = call.from_user.id
    product = call.data.split(":", 1)[1]
    ADMIN_STATE[uid] = {"step": "mat_upload", "data": {"product": product}}
    bot.answer_callback_query(call.id)
    panel(uid, materials_screen_text(product), kb.kb_mat_done(product, db.get_materials(product)))


KIND_NAMES = {"photo": "фото", "video": "видео", "document": "документ",
              "animation": "гифка", "audio": "аудио"}


def materials_screen_text(product):
    mats = db.get_materials(product)
    lines = [f"<b>Материалы курса «{config.PRODUCT_TITLES[product]}»</b>\n"]
    if mats:
        for i, m in enumerate(mats, 1):
            подпись = m["caption"] or "без подписи"
            lines.append(f"{i}. {KIND_NAMES.get(m['kind'], m['kind'])} — {подпись}")
        lines.append("\nЭто уходит покупателю после оплаты, в этом же порядке.")
    else:
        lines.append("Пока ничего не загружено — покупателю нечего выдать.")
    lines.append("\nПрисылайте видео и документы по одному — сохраню в порядке отправки. "
                 "Подпись к файлу станет подписью для покупателя.")
    return "\n".join(lines)


@bot.callback_query_handler(func=lambda c: c.data.startswith("matshow:"))
def cb_matshow(call):
    if not is_admin(call.from_user.id):
        return
    uid = call.from_user.id
    product = call.data.split(":", 1)[1]
    mats = db.get_materials(product)
    bot.answer_callback_query(call.id, "Отправляю")
    drop_panel(uid)
    senders = {"photo": bot.send_photo, "video": bot.send_video,
               "animation": bot.send_animation, "document": bot.send_document}
    for i, m in enumerate(mats, 1):
        try:
            senders.get(m["kind"], bot.send_document)(
                uid, m["file_id"], caption=f"{i}. {m['caption'] or 'без подписи'}")
        except ApiTelegramException as e:
            safe_send(uid, f"{i}. ⚠️ файл не открылся: {e.description}")
    panel(uid, materials_screen_text(product), kb.kb_mat_done(product, mats))


@bot.callback_query_handler(func=lambda c: c.data.startswith("photoadd:"))
def cb_photoadd(call):
    if not is_admin(call.from_user.id):
        return
    uid = call.from_user.id
    slot = call.data.split(":", 1)[1]
    ADMIN_STATE[uid] = {"step": "cover_upload", "data": {"slot": slot}}
    cur = db.get_materials(f"cover_{slot}")
    bot.answer_callback_query(call.id)
    head = f"<b>{content.COVER_SLOTS[slot]}</b>\n\n"
    hint = ("Пришлите видео или фото — оно заменит эту обложку. "
            "Подпись станет подписью в боте.")
    if cur:
        panel_media(uid, cur[0]["kind"], cur[0]["file_id"],
                    head + f"Сейчас загружено ({KIND_NAMES.get(cur[0]['kind'], cur[0]['kind'])}). "
                    + hint, kb.kb_cover_done(slot))
    else:
        panel(uid, head + "Сейчас обложки нет — пользователь видит заглушку "
                          "«тут будет фото».\n\n" + hint, kb.kb_cover_done(slot))


@bot.callback_query_handler(func=lambda c: c.data.startswith("photodel:"))
def cb_photodel(call):
    if not is_admin(call.from_user.id):
        return
    slot = call.data.split(":", 1)[1]
    db.clear_materials(f"cover_{slot}")
    ADMIN_STATE.pop(call.from_user.id, None)
    bot.answer_callback_query(call.id, "Убрано")
    panel(call.from_user.id, f"Обложка «{content.COVER_SLOTS[slot]}» убрана — "
                             f"вернулась заглушка «тут будет фото».", kb.kb_admin())


@bot.callback_query_handler(func=lambda c: c.data.startswith("matclear:"))
def cb_matclear(call):
    if not is_admin(call.from_user.id):
        return
    product = call.data.split(":", 1)[1]
    db.clear_materials(product)
    bot.answer_callback_query(call.id, "Очищено")
    panel(call.from_user.id, materials_screen_text(product),
          kb.kb_mat_done(product, db.get_materials(product)))


@bot.callback_query_handler(func=lambda c: c.data.startswith("grant:"))
def cb_grant(call):
    if not is_admin(call.from_user.id):
        return
    _, target, product = call.data.split(":")
    target = int(target)
    db.add_purchase(target, product)
    db.log_event(target, "access_granted", product)
    bot.answer_callback_query(call.id, "Доступ открыт")
    panel(call.from_user.id,
          f"✅ Доступ к «{config.PRODUCT_TITLES[product]}» открыт "
          f"пользователю <code>{target}</code>", kb.kb_admin())
    deliver_access(target, product, label=f"выдал админ, user {target}")


@bot.callback_query_handler(func=lambda c: c.data.startswith("grantsel:"))
def cb_grant_select(call):
    if not is_admin(call.from_user.id):
        return
    uid = call.from_user.id
    product = call.data.split(":", 1)[1]
    st = ADMIN_STATE.get(uid, {})
    target = st.get("data", {}).get("target")
    if not target:
        bot.answer_callback_query(call.id, "Сессия истекла")
        return
    db.add_purchase(target, product)
    db.log_event(target, "access_granted", product)
    ADMIN_STATE.pop(uid, None)
    bot.answer_callback_query(call.id, "Готово")
    panel(uid, f"✅ Доступ к «{config.PRODUCT_TITLES[product]}» открыт "
               f"пользователю <code>{target}</code>", kb.kb_admin())
    deliver_access(target, product, label=f"выдал админ, user {target}")


@bot.callback_query_handler(func=lambda c: c.data == "bc:go")
def cb_bcast_go(call):
    if not is_admin(call.from_user.id):
        return
    uid = call.from_user.id
    st = ADMIN_STATE.get(uid, {})
    data = st.get("data", {})
    if not data.get("msg_id"):
        bot.answer_callback_query(call.id, "Нечего отправлять")
        return

    if broadcast.is_running():
        bot.answer_callback_query(call.id, "Одна рассылка уже идёт", show_alert=True)
        return

    bot.answer_callback_query(call.id, "Запускаю")
    ADMIN_STATE.pop(uid, None)
    broadcast.start(bot, uid, data["audience"], data["from_chat"], data["msg_id"],
                    on_error=handle_send_error)


@bot.callback_query_handler(func=lambda c: c.data == "bc:resume")
def cb_bcast_resume(call):
    if not is_admin(call.from_user.id):
        return
    uid = call.from_user.id
    last = db.last_broadcast()
    if not last:
        bot.answer_callback_query(call.id, "Рассылок ещё не было", show_alert=True)
        return
    if broadcast.is_running():
        bot.answer_callback_query(call.id, "Одна рассылка уже идёт", show_alert=True)
        return

    payload = json.loads(last["payload"])
    bot.answer_callback_query(call.id, "Досылаю")
    broadcast.start(bot, uid, last["audience"], payload["from_chat"], payload["msg_id"],
                    on_error=handle_send_error, broadcast_id=last["id"])


def _download(file_id):
    f = bot.get_file(file_id)
    return bot.download_file(f.file_path), f.file_path


@bot.message_handler(commands=["inbox"])
def cmd_inbox(message):
    if not is_admin(message.from_user.id):
        return
    uid = message.from_user.id
    arg = (message.text.split(maxsplit=1) + [""])[1].strip().lower()

    if arg in ("on", "вкл", "start"):
        ADMIN_STATE.pop(uid, None)
        forget_input(message)
        inbox.set_on(True)
        panel(uid, "📥 <b>Приёмник включён.</b>\n\n"
                       "Пересылайте всё подряд — тексты, фото, видео, документы. "
                       "Сохраняю как есть: форматирование, премиум-эмодзи и file_id.\n\n"
                       "Отвечать на каждое сообщение не буду, чтобы не мешать.\n"
                       "Когда закончите — <code>/inbox off</code>.")
        return

    if arg in ("off", "выкл", "stop"):
        inbox.set_on(False)
        forget_input(message)
        path, s = inbox.build_digest()
        types_s = ", ".join(f"{k} — {v}" for k, v in sorted(s["by_type"].items())) or "—"
        panel(uid, "📥 <b>Приёмник выключен.</b>\n\n"
                       f"Собрано сообщений: <b>{s['total']}</b>\n"
                       f"По типам: {types_s}\n"
                       f"Премиум-эмодзи: {s['custom_emoji']}\n"
                       f"Файлов скачано: {s['downloaded']}, только по file_id: {s['only_id']}",
                   kb.kb_admin())
        log.info("Приёмник выключен, сводка: %s", path)
        return

    s = inbox.summary()
    state = "включён" if inbox.is_on() else "выключен"
    forget_input(message)
    panel(uid, f"📥 Приёмник {state}. Собрано: <b>{s['total']}</b>\n\n"
                   f"<code>/inbox on</code> — включить\n"
                   f"<code>/inbox off</code> — выключить и собрать сводку", kb.kb_admin())


@bot.message_handler(
    func=lambda m: is_admin(m.from_user.id) and inbox.is_on()
                   and not (m.text or "").startswith("/")
                   and not ADMIN_STATE.get(m.from_user.id),
    content_types=telebot.util.content_type_media)
def collect_message(message):
    try:
        rec = inbox.save(message, downloader=_download)
        log.info("Приёмник: #%s %s", rec["n"], rec["content_type"])
    except Exception as e:
        log.exception("Приёмник не сохранил сообщение: %s", e)
        safe_send(message.from_user.id, f"⚠️ Не сохранил это сообщение: {e}")


@bot.message_handler(content_types=["text", "photo", "video", "document", "audio", "voice"])
def catch_all(message):
    uid = message.from_user.id
    st = ADMIN_STATE.get(uid)

    if is_admin(uid) and st:
        step = st["step"]

        if step == "mat_upload":
            product = st["data"]["product"]
            caption = message.caption or ""
            order = len(db.get_materials(product))
            forget_input(message)
            if message.content_type in ("video", "document", "audio", "photo"):
                fid = (message.photo[-1].file_id if message.content_type == "photo"
                       else getattr(message, message.content_type).file_id)
                db.add_material(product, message.content_type, fid, caption, order)
            else:
                panel(uid, "Присылайте видео, документ или фото.",
                      kb.kb_mat_done(product, db.get_materials(product)))
                return
            panel(uid, materials_screen_text(product),
                  kb.kb_mat_done(product, db.get_materials(product)))
            return

        if step == "cover_upload":
            slot = st["data"]["slot"]
            ct = message.content_type
            if ct == "photo":
                file_id = message.photo[-1].file_id
            elif ct in ("video", "animation"):
                file_id = getattr(message, ct).file_id
            else:
                panel(uid, "Пришлите видео или фото (не документом).",
                      kb.kb_cover_done(slot))
                return
            forget_input(message)
            db.clear_materials(f"cover_{slot}")
            db.add_material(f"cover_{slot}", ct, file_id, message.caption or "", 0)
            ADMIN_STATE.pop(uid, None)
            panel_media(uid, ct, file_id,
                        f"✅ Обложка «{content.COVER_SLOTS[slot]}» обновлена — "
                        f"теперь пользователь видит это.", kb.kb_admin())
            return

        if step == "product_price":
            slug = st["data"]["slug"]
            digits = "".join(ch for ch in (message.text or "") if ch.isdigit())
            forget_input(message)
            if not digits or int(digits) <= 0:
                panel(uid, "Пришлите цену числом, например: 15000")
                return
            products.set_price(slug, int(digits))
            ADMIN_STATE.pop(uid, None)
            states = products_state()
            panel(uid, products_screen_text(states), kb.kb_products_settings(states))
            return

        if step == "link_title":
            title = (message.text or "").strip()
            forget_input(message)
            if not title:
                panel(uid, "Пришлите название текстом.")
                return
            ADMIN_STATE[uid] = {"step": "link_target", "data": {"title": title}}
            panel(uid, f"Ссылка: <b>{title}</b>\n\nКуда она ведёт?", kb.kb_link_target())
            return

        if step == "grant_user":
            target = db.find_user_id(message.text or "")
            forget_input(message)
            if not target:
                panel(uid, "Не нашёл такого пользователя. "
                           "Он должен был хотя бы раз запустить бота.", kb.kb_admin())
                return
            ADMIN_STATE[uid] = {"step": "grant_product", "data": {"target": target}}
            panel(uid, f"Пользователь найден: <code>{target}</code>\n\nКакой курс открыть?",
                  kb.kb_products("grantsel"))
            return

        if step == "bcast_text":
            st["data"]["msg_id"] = message.message_id
            st["data"]["from_chat"] = message.chat.id
            st["step"] = "bcast_confirm"
            panel(uid, f"Сообщение для рассылки принято — оно выше.\n\n"
                       f"Получателей: <b>{st['data']['count']}</b>\n\nОтправляем?",
                  kb.kb_confirm_send())
            return

    link = None
    if message.content_type == "text":
        word = (message.text or "").strip()
        link = db.find_link_by_word(word) or db.find_link_by_word(translit(word))
    if link and not is_admin(uid):
        db.upsert_user(uid, message.from_user.username, message.from_user.first_name,
                       link["slug"])
        db.log_event(uid, "start", f"source={link['slug']};codeword=1")
        if not db.has_consent(uid):
            safe_send(uid, content.CONSENT, reply_markup=kb.kb_consent(link["product"]))
            return
        _route_after_consent(uid, link["product"])
        return

    if not db.has_consent(uid):
        cmd_start(message)
        return
    safe_send(uid, "Я отвечаю кнопками. Нажмите /start, чтобы вернуться к началу, "
                   f"или напишите {config.SUPPORT_USERNAME} по вопросам оплаты.")


def drip_worker():
    log.info("Планировщик дожимов запущен")
    while True:
        try:
            if not db.drips_enabled():
                time.sleep(config.SCHEDULER_INTERVAL)
                continue
            for row in db.due_drips():
                uid, product, step = row["user_id"], row["product"], row["step"]

                if db.has_purchase(uid, product):
                    db.stop_drip(uid, product)
                    continue

                texts = content.DRIP.get(product, [])
                if step >= len(texts):
                    db.advance_drip(uid, product, None)
                    continue

                safe_send(uid, texts[step], reply_markup=kb.kb_drip(product))
                db.log_event(uid, "drip_sent", f"{product}:{step + 1}")

                nxt = config.DRIP_HOURS[step + 1] - config.DRIP_HOURS[step] \
                    if step + 1 < len(config.DRIP_HOURS) else None
                db.advance_drip(uid, product, nxt)
                time.sleep(BULK_PAUSE)
        except Exception as e:
            log.exception("Ошибка планировщика: %s", e)
        time.sleep(config.SCHEDULER_INTERVAL)


def setup_commands():
    common = [
        types.BotCommand("start", "Начать заново"),
        types.BotCommand("menu", "Навигация по разделам"),
        types.BotCommand("help", "Помощь и связь"),
    ]
    try:
        bot.set_my_commands(common)
        admin_only = common + [types.BotCommand("admin", "Панель управления")]
        for admin in config.ADMIN_IDS:
            bot.set_my_commands(admin_only, scope=types.BotCommandScopeChat(chat_id=admin))
        log.info("Команды меню установлены")
    except ApiTelegramException as e:
        log.warning("Не удалось установить команды: %s", e)


def main():
    if not config.BOT_TOKEN:
        raise SystemExit("Не задан BOT_TOKEN в .env")
    db.init_db()
    try:
        BOT_USERNAME[0] = bot.get_me().username
    except ApiTelegramException as e:
        log.warning("Не узнал имя бота: %s", e)
    setup_commands()
    threading.Thread(target=drip_worker, daemon=True).start()
    log.info("Бот запущен")
    bot.infinity_polling(skip_pending=True, timeout=30, long_polling_timeout=30)


if __name__ == "__main__":
    main()
