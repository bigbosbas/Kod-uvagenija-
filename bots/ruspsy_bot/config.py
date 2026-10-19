import os
from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".env"))

BOT_TOKEN = os.getenv("FUNNEL_BOT_TOKEN", "")

ADMIN_IDS = [int(x) for x in os.getenv("FUNNEL_ADMIN_IDS", "").replace(" ", "").split(",") if x]

TECH_ADMIN_IDS = [int(x) for x in os.getenv("FUNNEL_TECH_ADMIN_IDS", "").replace(" ", "").split(",") if x] \
                 or ADMIN_IDS[:1]

DB_PATH = os.getenv("FUNNEL_DB_PATH", "bot.db")

TZ_HOURS = int(os.getenv("FUNNEL_REPORT_TZ_HOURS", "3"))

# Старый сайт nagaichenkopsy.com выведен из поиска и отвечает 410, поэтому
# документы бота лежат на kod., а покупки идут через лендинги privatebotrus.ru.
LINK_POLICY = os.getenv("FUNNEL_LINK_POLICY",
                        "https://kod.privatebotrus.ru/assets/legal/ruspsy-bot-privacy.pdf")

SUPPORT_USERNAME = os.getenv("FUNNEL_SUPPORT_USERNAME", "@username")

# Telegram из России заблокирован — ходим через SOCKS5 за границей
# (socks5h://user:pass@host:port). Пусто — без прокси.
TELEGRAM_PROXY = os.getenv("FUNNEL_TELEGRAM_PROXY", "").strip().replace("socks5://", "socks5h://", 1)

# Курсы и книги продаются на лендингах: бот только ведёт туда с UTM.
UTM = "utm_source=telegram&utm_medium=bot"
_BOOKS_URL = os.getenv("FUNNEL_URL_BOOKS", "https://knigi.privatebotrus.ru/")
LANDING_URLS = {
    "peresborka": os.getenv("FUNNEL_URL_PERESBORKA", "https://peresborka.privatebotrus.ru/"),
    "kod": os.getenv("FUNNEL_URL_KOD", "https://kod.privatebotrus.ru/"),
    "book_vliyanie": _BOOKS_URL + "#book-vliyanie",
    "book_obshchenie": _BOOKS_URL + "#book-obshchenie",
}


def landing_url(product, campaign=None):
    base, _, anchor = LANDING_URLS[product].partition("#")
    query = UTM + (f"&utm_campaign={campaign}" if campaign else "")
    return f"{base}?{query}" + (f"#{anchor}" if anchor else "")


CHANNEL_PRODUCTS = {"peresborka"}

DELIVERY_TEXT = {
    "peresborka": "персональную ссылку в закрытый канал курса — там все материалы "
                  "и видео-модули",
    "kod": "PDF-файл курса прямо в этот чат",
    "book_vliyanie": "книгу в PDF прямо в этот чат",
    "book_obshchenie": "книгу в PDF прямо в этот чат",
}

DELIVERY_SHORT = {
    "peresborka": "ссылку в закрытый канал я пришлю сам",
    "kod": "файл курса придёт сюда автоматически",
    "book_vliyanie": "книга придёт сюда автоматически",
    "book_obshchenie": "книга придёт сюда автоматически",
}



TYPING_ENABLED = True
MSG_DELAY_MIN = 2.0
MSG_DELAY_MAX = 6.0
MSG_READ_SPEED = 300

DRIP_HOURS = [24, 48, 72, 120, 216]

SCHEDULER_INTERVAL = 60

P_KOD = "kod"
P_PERESBORKA = "peresborka"
B_VLIYANIE = "book_vliyanie"
B_OBSHCHENIE = "book_obshchenie"

COURSES = [P_PERESBORKA, P_KOD]
BOOKS = [B_VLIYANIE, B_OBSHCHENIE]
ALL_PRODUCTS = COURSES + BOOKS

PRODUCT_TITLES = {
    P_KOD: "Код уважения",
    P_PERESBORKA: "Пересборка",
    B_VLIYANIE: "Невидимая энергия влияния",
    B_OBSHCHENIE: "Скрытая власть общения",
}

