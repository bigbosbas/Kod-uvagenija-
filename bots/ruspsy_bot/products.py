import config
import database as db

# Продажа идёт на лендингах privatebotrus.ru, поэтому здесь только включатель
# кнопки «Приобрести» и цена для подписи на ней — обе хранятся в базе бота.
# Цену в боте меняют вместе с ценой на сайте, иначе подпись разойдётся с оплатой.


def get(slug):
    row = db.get_product(slug)
    return {"enabled": bool(row["enabled"]) if row else False,
            "price": int(row["price_rub"]) if row and row["price_rub"] else 0}


def set_enabled(slug, value):
    db.set_product(slug, enabled=value)


def set_price(slug, rub):
    db.set_product(slug, price_rub=rub)


def price_text(slug):
    price = get(slug)["price"]
    return f"{price:,} ₽".replace(",", " ") if price else "цена не задана"


def buy_url(slug):
    return config.landing_url(slug)
