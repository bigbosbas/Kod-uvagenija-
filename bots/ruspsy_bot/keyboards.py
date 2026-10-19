from telebot import types
import config

GREEN = "success"
BLUE = "primary"
RED = "danger"


def kb_consent(product=None):
    kb = types.InlineKeyboardMarkup()
    kb.add(types.InlineKeyboardButton("✅ Принимаю", callback_data=f"consent:yes:{product or ''}",
                                      style=GREEN))
    kb.add(types.InlineKeyboardButton("Политика обработки данных", url=config.LINK_POLICY))
    return kb


def kb_segments():
    kb = types.InlineKeyboardMarkup()
    kb.add(types.InlineKeyboardButton(
        "1 — Повторяющийся сценарий", callback_data="seg:peresborka"))
    kb.add(types.InlineKeyboardButton(
        "2 — Проявление позиции", callback_data="seg:kod"))
    return kb


def kb_product(product, uid=None):
    other = "kod" if product == "peresborka" else "peresborka"
    other_label = ("Посмотреть «Код уважения»" if other == "kod"
                   else "Посмотреть «Пересборку»")
    title = config.PRODUCT_TITLES[product]

    import database as db
    import products
    state = products.get(product)

    kb = types.InlineKeyboardMarkup()
    if uid and db.has_purchase(uid, product):
        kb.add(types.InlineKeyboardButton("✅ Курс куплен — открыть материалы",
                                          callback_data=f"mine:{product}", style=GREEN))
    elif not state["enabled"]:
        kb.add(types.InlineKeyboardButton("🔔 Сообщить о старте продаж",
                                          callback_data=f"notify:{product}", style=GREEN))
    else:
        kb.add(types.InlineKeyboardButton(
            f"Приобрести курс «{title}» — {products.price_text(product)}",
            url=products.buy_url(product), style=GREEN))
    kb.add(types.InlineKeyboardButton(other_label, callback_data=f"seg:{other}"))
    kb.add(types.InlineKeyboardButton("📚 Курсы и книги", callback_data="books:list"))
    return kb


def kb_channel(link):
    kb = types.InlineKeyboardMarkup()
    kb.add(types.InlineKeyboardButton("Перейти в закрытый канал", url=link, style=GREEN))
    return kb


def kb_catalog(uid=None):
    import content
    import database as db
    kb = types.InlineKeyboardMarkup()
    for slug in config.COURSES:
        mark = "✅ " if uid and db.has_purchase(uid, slug) else ""
        kb.add(types.InlineKeyboardButton(f"{mark}Курс «{config.PRODUCT_TITLES[slug]}»",
                                          callback_data=f"seg:{slug}"))
    import products
    for b in content.BOOKS:
        kb.add(types.InlineKeyboardButton(f"Книга «{b['title']}»",
                                          url=products.buy_url(b["slug"])))
    return kb


def kb_nav(uid=None):
    import database as db
    kb = kb_catalog(uid)
    if uid and any(db.has_purchase(uid, p) for p in config.ALL_PRODUCTS):
        kb.add(types.InlineKeyboardButton("📦 Мои материалы", callback_data="nav:mine"))
    kb.add(types.InlineKeyboardButton("🎯 Пройти диагностику заново",
                                      callback_data="nav:intro"))
    return kb


def kb_books_list(uid=None):
    return kb_catalog(uid)


def kb_book(book):
    import products
    slug = book["slug"]
    state = products.get(slug)
    kb = types.InlineKeyboardMarkup()
    if state["enabled"]:
        kb.add(types.InlineKeyboardButton(
            f"Купить PDF — {products.price_text(slug)}",
            url=products.buy_url(slug), style=GREEN))
    else:
        kb.add(types.InlineKeyboardButton("🔔 Сообщить, когда появится",
                                          callback_data=f"notify:{slug}", style=GREEN))
    if book.get("url_print"):
        kb.add(types.InlineKeyboardButton("Печатное издание", url=book["url_print"]))
    kb.add(types.InlineKeyboardButton("← К списку книг", callback_data="books:list"))
    return kb


def kb_drip(product):
    title = config.PRODUCT_TITLES[product]
    kb = types.InlineKeyboardMarkup()
    kb.add(types.InlineKeyboardButton(
        f"Открыть курс «{title}»", callback_data=f"seg:{product}", style=GREEN))
    kb.add(types.InlineKeyboardButton("Больше не напоминать", callback_data=f"mute:{product}"))
    return kb


def kb_admin():
    kb = types.InlineKeyboardMarkup(row_width=2)
    kb.add(
        types.InlineKeyboardButton("📊 Статистика", callback_data="adm:stats"),
        types.InlineKeyboardButton("📣 Рассылка", callback_data="adm:bcast"),
    )
    kb.add(
        types.InlineKeyboardButton("📎 Материалы", callback_data="adm:mat"),
        types.InlineKeyboardButton("🔑 Выдать доступ", callback_data="adm:grant"),
    )
    kb.add(
        types.InlineKeyboardButton("🖼 Обложки", callback_data="adm:photo"),
        types.InlineKeyboardButton("🔗 Ссылки", callback_data="adm:links"),
    )
    kb.add(types.InlineKeyboardButton("⚙️ Продукты: продажа и цены", callback_data="adm:products"))
    import database as db
    if db.drips_enabled():
        kb.add(types.InlineKeyboardButton("⏰ Напоминания: включены — выключить",
                                          callback_data="drip:off", style=RED))
    else:
        kb.add(types.InlineKeyboardButton("⏰ Напоминания: выключены — включить",
                                          callback_data="drip:on", style=GREEN))
    kb.add(types.InlineKeyboardButton("📥 Excel-отчёт", callback_data="adm:excel", style=BLUE))
    return kb


def kb_stats(period=0):
    kb = types.InlineKeyboardMarkup(row_width=2)
    marks = {1: "Сегодня", 7: "7 дней", 30: "30 дней", 0: "Всё время"}
    row = [types.InlineKeyboardButton(("• " if d == period else "") + name,
                                      callback_data=f"st:period:{d}")
           for d, name in marks.items()]
    kb.add(row[0], row[1]); kb.add(row[2], row[3])
    kb.add(types.InlineKeyboardButton("💳 История оплат", callback_data="st:pay"),
           types.InlineKeyboardButton("📅 По месяцам", callback_data="st:months"))
    kb.add(types.InlineKeyboardButton("🔗 Откуда приходят", callback_data="st:src"),
           types.InlineKeyboardButton("📥 Excel", callback_data="adm:excel", style=BLUE))
    kb.add(types.InlineKeyboardButton("← В меню", callback_data="adm:home"))
    return kb


def kb_stats_back(period=0):
    kb = types.InlineKeyboardMarkup()
    kb.add(types.InlineKeyboardButton("← К статистике", callback_data=f"st:period:{period}"))
    return kb


def kb_products_settings(states):
    kb = types.InlineKeyboardMarkup()
    for slug, st in states.items():
        title = config.PRODUCT_TITLES[slug]
        if st["enabled"]:
            kb.add(types.InlineKeyboardButton(
                f"🟢 {title} — выключить продажу", callback_data=f"prod:off:{slug}", style=RED))
        else:
            kb.add(types.InlineKeyboardButton(
                f"🔴 {title} — включить продажу", callback_data=f"prod:on:{slug}", style=GREEN))
        kb.add(types.InlineKeyboardButton(
            f"💰 Цена «{title}»: {st['price_text']}", callback_data=f"prod:price:{slug}"))
    kb.add(types.InlineKeyboardButton("← В меню", callback_data="adm:home"))
    return kb


def kb_links(links):
    kb = types.InlineKeyboardMarkup()
    kb.add(types.InlineKeyboardButton("➕ Создать ссылку", callback_data="lnk:new", style=GREEN))
    for l in links:
        kb.add(types.InlineKeyboardButton(f"🗑 {l['title']}", callback_data=f"lnk:del:{l['slug']}"))
    kb.add(types.InlineKeyboardButton("← В меню", callback_data="adm:home"))
    return kb


def kb_link_target():
    kb = types.InlineKeyboardMarkup()
    kb.add(types.InlineKeyboardButton("Диагностика (общая воронка)", callback_data="lnkt:-"))
    kb.add(types.InlineKeyboardButton("Сразу «Пересборка»", callback_data="lnkt:peresborka"))
    kb.add(types.InlineKeyboardButton("Сразу «Код уважения»", callback_data="lnkt:kod"))
    kb.add(types.InlineKeyboardButton("← Отмена", callback_data="adm:links"))
    return kb


def kb_after_broadcast():
    kb = types.InlineKeyboardMarkup()
    kb.add(types.InlineKeyboardButton("📨 Дослать не получившим", callback_data="bc:resume", style=BLUE))
    kb.add(types.InlineKeyboardButton("← В меню", callback_data="adm:home"))
    return kb


def kb_cover_slots():
    import content
    kb = types.InlineKeyboardMarkup()
    for slot, title in content.COVER_SLOTS.items():
        kb.add(types.InlineKeyboardButton(title, callback_data=f"photoadd:{slot}"))
    kb.add(types.InlineKeyboardButton("← Назад", callback_data="adm:home"))
    return kb


def kb_cover_done(slot):
    kb = types.InlineKeyboardMarkup()
    kb.add(types.InlineKeyboardButton("Готово", callback_data="adm:home"))
    kb.add(types.InlineKeyboardButton("Убрать обложку", callback_data=f"photodel:{slot}"))
    return kb


def kb_audience():
    kb = types.InlineKeyboardMarkup(row_width=2)
    kb.add(
        types.InlineKeyboardButton("Все", callback_data="aud:all"),
        types.InlineKeyboardButton("Не купившие", callback_data="aud:nopay"),
    )
    kb.add(
        types.InlineKeyboardButton("Сегмент «Пересборка»", callback_data="aud:peresborka"),
        types.InlineKeyboardButton("Сегмент «Код уважения»", callback_data="aud:kod"),
    )
    kb.add(
        types.InlineKeyboardButton("Покупатели", callback_data="aud:buyers"),
        types.InlineKeyboardButton("Из Instagram", callback_data="aud:ig"),
    )
    kb.add(types.InlineKeyboardButton("Из YouTube", callback_data="aud:yt"))
    kb.add(types.InlineKeyboardButton("← Отмена", callback_data="adm:home"))
    return kb


def kb_products(prefix):
    kb = types.InlineKeyboardMarkup()
    kb.add(types.InlineKeyboardButton("«Код уважения»", callback_data=f"{prefix}:kod"))
    kb.add(types.InlineKeyboardButton("«Пересборка»", callback_data=f"{prefix}:peresborka"))
    kb.add(types.InlineKeyboardButton("← Назад", callback_data="adm:home"))
    return kb


def kb_confirm_send():
    kb = types.InlineKeyboardMarkup()
    kb.add(types.InlineKeyboardButton("🚀 Отправить", callback_data="bc:go", style=RED))
    kb.add(types.InlineKeyboardButton("← Отмена", callback_data="adm:home"))
    return kb


def kb_mat_done(product, materials=()):
    kb = types.InlineKeyboardMarkup()
    if materials:
        kb.add(types.InlineKeyboardButton(f"👁 Показать вложения ({len(materials)})",
                                          callback_data=f"matshow:{product}"))
    kb.add(types.InlineKeyboardButton("Готово", callback_data="adm:home"))
    if materials:
        kb.add(types.InlineKeyboardButton("Очистить материалы курса",
                                          callback_data=f"matclear:{product}"))
    return kb
