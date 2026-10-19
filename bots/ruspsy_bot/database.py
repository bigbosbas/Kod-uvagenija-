import sqlite3
import threading
from datetime import datetime, timedelta, timezone

from config import DB_PATH, TZ_HOURS

_lock = threading.Lock()


def utcnow():
    return datetime.now(timezone.utc).replace(tzinfo=None)


def local_now():
    return utcnow() + timedelta(hours=TZ_HOURS)


TZ_SQL = f"'{TZ_HOURS:+d} hours'"
TZ_SQL_PY = TZ_SQL
LOCAL_DAY_CREATED = f"substr(datetime(created_at, {TZ_SQL}),1,10)"


def _conn():
    c = sqlite3.connect(DB_PATH, check_same_thread=False)
    c.row_factory = sqlite3.Row
    return c


def init_db():
    with _lock, _conn() as c:
        c.executescript("""
        CREATE TABLE IF NOT EXISTS users (
            user_id     INTEGER PRIMARY KEY,
            username    TEXT,
            first_name  TEXT,
            source      TEXT DEFAULT 'direct',   -- ig / yt / direct
            consent     INTEGER DEFAULT 0,       -- согласие на ПДн
            consent_at  TEXT,
            segment     TEXT,                    -- kod / peresborka
            created_at  TEXT,
            blocked     INTEGER DEFAULT 0
        );

        CREATE TABLE IF NOT EXISTS purchases (
            user_id  INTEGER,
            product  TEXT,
            paid_at  TEXT,
            PRIMARY KEY (user_id, product)
        );

        CREATE TABLE IF NOT EXISTS drip (
            user_id  INTEGER,
            product  TEXT,
            step     INTEGER DEFAULT 0,
            next_at  TEXT,
            stopped  INTEGER DEFAULT 0,   -- пауза: можно возобновить
            muted    INTEGER DEFAULT 0,   -- явный отказ: возобновлять нельзя
            PRIMARY KEY (user_id, product)
        );

        CREATE TABLE IF NOT EXISTS products (
            slug       TEXT PRIMARY KEY,
            enabled    INTEGER DEFAULT 0,
            price_rub  INTEGER,
            updated_at TEXT
        );

        CREATE TABLE IF NOT EXISTS settings (
            key   TEXT PRIMARY KEY,
            value TEXT
        );

        CREATE TABLE IF NOT EXISTS invites (
            user_id    INTEGER,
            product    TEXT,
            link       TEXT,
            created_at TEXT,
            PRIMARY KEY (user_id, product)
        );

        CREATE TABLE IF NOT EXISTS links (
            slug       TEXT PRIMARY KEY,   -- метка в ссылке t.me/bot?start=<slug>
            title      TEXT,               -- как называется в админке
            product    TEXT,               -- сразу открыть курс или NULL (диагностика)
            created_at TEXT
        );

        CREATE TABLE IF NOT EXISTS orders (
            order_id    INTEGER PRIMARY KEY,   -- id заказа на сайте
            user_id     INTEGER,
            product     TEXT,
            token       TEXT,                  -- нужен для опроса статуса
            email       TEXT,
            status      TEXT DEFAULT 'pending',
            invite_link TEXT,
            amount_rub  INTEGER,          -- сумма на момент заказа: нужна для выручки
            created_at  TEXT,
            paid_at     TEXT
        );

        CREATE TABLE IF NOT EXISTS broadcasts (
            id          TEXT PRIMARY KEY,
            audience    TEXT,
            total       INTEGER,
            sent        INTEGER DEFAULT 0,
            failed      INTEGER DEFAULT 0,
            status      TEXT DEFAULT 'running',
            payload     TEXT,
            created_at  TEXT,
            finished_at TEXT
        );

        CREATE TABLE IF NOT EXISTS broadcast_sent (
            broadcast_id TEXT,
            user_id      INTEGER,
            PRIMARY KEY (broadcast_id, user_id)
        );

        CREATE TABLE IF NOT EXISTS materials (
            id       INTEGER PRIMARY KEY AUTOINCREMENT,
            product  TEXT,
            kind     TEXT,      -- video / document
            file_id  TEXT,
            caption  TEXT,
            ord      INTEGER DEFAULT 0
        );

        CREATE TABLE IF NOT EXISTS events (
            id       INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id  INTEGER,
            event    TEXT,
            meta     TEXT,
            ts       TEXT
        );

        CREATE INDEX IF NOT EXISTS idx_events_user ON events(user_id);
        CREATE INDEX IF NOT EXISTS idx_events_event ON events(event);
        """)
        _migrate(c)


def _migrate(c):
    cols = {r["name"] for r in c.execute("PRAGMA table_info(drip)")}
    if "muted" not in cols:
        c.execute("ALTER TABLE drip ADD COLUMN muted INTEGER DEFAULT 0")

    cols = {r["name"] for r in c.execute("PRAGMA table_info(orders)")}
    if "amount_rub" not in cols:
        c.execute("ALTER TABLE orders ADD COLUMN amount_rub INTEGER")


def upsert_user(user_id, username, first_name, source="direct"):
    now = utcnow().isoformat()
    with _lock, _conn() as c:
        row = c.execute("SELECT user_id, source FROM users WHERE user_id=?", (user_id,)).fetchone()
        if row:
            c.execute("UPDATE users SET username=?, first_name=?, blocked=0 WHERE user_id=?",
                      (username, first_name, user_id))
        else:
            c.execute(
                "INSERT INTO users (user_id, username, first_name, source, created_at) VALUES (?,?,?,?,?)",
                (user_id, username, first_name, source, now))


def get_user(user_id):
    with _lock, _conn() as c:
        return c.execute("SELECT * FROM users WHERE user_id=?", (user_id,)).fetchone()


def has_consent(user_id):
    u = get_user(user_id)
    return bool(u and u["consent"])


def set_consent(user_id):
    with _lock, _conn() as c:
        c.execute("UPDATE users SET consent=1, consent_at=? WHERE user_id=?",
                  (utcnow().isoformat(), user_id))


def set_segment(user_id, segment):
    with _lock, _conn() as c:
        c.execute("UPDATE users SET segment=? WHERE user_id=?", (segment, user_id))


def is_blocked(user_id):
    u = get_user(user_id)
    return bool(u and u["blocked"])


def mark_blocked(user_id):
    with _lock, _conn() as c:
        c.execute("UPDATE users SET blocked=1 WHERE user_id=?", (user_id,))


def add_purchase(user_id, product):
    with _lock, _conn() as c:
        c.execute("INSERT OR REPLACE INTO purchases (user_id, product, paid_at) VALUES (?,?,?)",
                  (user_id, product, utcnow().isoformat()))
        c.execute("UPDATE drip SET stopped=1 WHERE user_id=? AND product=?", (user_id, product))


def has_purchase(user_id, product):
    with _lock, _conn() as c:
        return c.execute("SELECT 1 FROM purchases WHERE user_id=? AND product=?",
                         (user_id, product)).fetchone() is not None


def find_user_id(query):
    q = query.strip().lstrip("@")
    with _lock, _conn() as c:
        if q.isdigit():
            row = c.execute("SELECT user_id FROM users WHERE user_id=?", (int(q),)).fetchone()
        else:
            row = c.execute("SELECT user_id FROM users WHERE lower(username)=lower(?)", (q,)).fetchone()
    return row["user_id"] if row else None


def start_drip(user_id, product, first_delay_hours):
    nxt = (utcnow() + timedelta(hours=first_delay_hours)).isoformat()
    with _lock, _conn() as c:
        row = c.execute("SELECT stopped, muted FROM drip WHERE user_id=? AND product=?",
                        (user_id, product)).fetchone()
        if row is None:
            c.execute("""INSERT INTO drip (user_id, product, step, next_at, stopped, muted)
                         VALUES (?,?,0,?,0,0)""", (user_id, product, nxt))
        elif row["stopped"] and not row["muted"]:
            c.execute("UPDATE drip SET stopped=0, next_at=? WHERE user_id=? AND product=?",
                      (nxt, user_id, product))


def set_active_drip(user_id, product):
    with _lock, _conn() as c:
        c.execute("UPDATE drip SET stopped=1 WHERE user_id=? AND product<>? AND muted=0",
                  (user_id, product))


def stop_drip(user_id, product=None, mute=False):
    fields = "stopped=1, muted=1" if mute else "stopped=1"
    with _lock, _conn() as c:
        if product:
            c.execute(f"UPDATE drip SET {fields} WHERE user_id=? AND product=?", (user_id, product))
        else:
            c.execute(f"UPDATE drip SET {fields} WHERE user_id=?", (user_id,))


def due_drips(limit=50):
    now = utcnow().isoformat()
    with _lock, _conn() as c:
        return c.execute("""
            SELECT d.* FROM drip d
            JOIN users u ON u.user_id = d.user_id
            WHERE d.stopped=0 AND d.next_at<=? AND u.blocked=0
            LIMIT ?""", (now, limit)).fetchall()


def advance_drip(user_id, product, next_delay_hours):
    with _lock, _conn() as c:
        if next_delay_hours is None:
            c.execute("UPDATE drip SET stopped=1, step=step+1 WHERE user_id=? AND product=?",
                      (user_id, product))
        else:
            nxt = (utcnow() + timedelta(hours=next_delay_hours)).isoformat()
            c.execute("UPDATE drip SET step=step+1, next_at=? WHERE user_id=? AND product=?",
                      (nxt, user_id, product))


def add_material(product, kind, file_id, caption="", ord_=0):
    with _lock, _conn() as c:
        c.execute("INSERT INTO materials (product, kind, file_id, caption, ord) VALUES (?,?,?,?,?)",
                  (product, kind, file_id, caption, ord_))


def get_materials(product):
    with _lock, _conn() as c:
        return c.execute("SELECT * FROM materials WHERE product=? ORDER BY ord, id",
                         (product,)).fetchall()


def clear_materials(product):
    with _lock, _conn() as c:
        c.execute("DELETE FROM materials WHERE product=?", (product,))


def log_event(user_id, event, meta=""):
    with _lock, _conn() as c:
        c.execute("INSERT INTO events (user_id, event, meta, ts) VALUES (?,?,?,?)",
                  (user_id, event, meta, utcnow().isoformat()))


def audience(filter_key="all"):
    sql = {
        "all": "SELECT user_id FROM users WHERE blocked=0 AND consent=1",
        "kod": "SELECT user_id FROM users WHERE blocked=0 AND consent=1 AND segment='kod'",
        "peresborka": "SELECT user_id FROM users WHERE blocked=0 AND consent=1 AND segment='peresborka'",
        "nopay": """SELECT u.user_id FROM users u
                    WHERE u.blocked=0 AND u.consent=1
                      AND NOT EXISTS (SELECT 1 FROM purchases p WHERE p.user_id=u.user_id)""",
        "buyers": """SELECT DISTINCT u.user_id FROM users u
                     JOIN purchases p ON p.user_id=u.user_id
                     WHERE u.blocked=0""",
        "ig": "SELECT user_id FROM users WHERE blocked=0 AND consent=1 AND source='ig'",
        "yt": "SELECT user_id FROM users WHERE blocked=0 AND consent=1 AND source='yt'",
    }[filter_key]
    with _lock, _conn() as c:
        return [r["user_id"] for r in c.execute(sql).fetchall()]


def get_setting(key, default=None):
    with _lock, _conn() as c:
        row = c.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
        return row["value"] if row else default


def set_setting(key, value):
    with _lock, _conn() as c:
        c.execute("""INSERT INTO settings (key, value) VALUES (?,?)
                     ON CONFLICT(key) DO UPDATE SET value=excluded.value""",
                  (key, str(value)))


def drips_enabled():
    return get_setting("drips_enabled", "1") == "1"


def get_product(slug):
    with _lock, _conn() as c:
        return c.execute("SELECT * FROM products WHERE slug=?", (slug,)).fetchone()


def set_product(slug, enabled=None, price_rub=None):
    with _lock, _conn() as c:
        c.execute("INSERT OR IGNORE INTO products (slug, enabled, updated_at) VALUES (?,0,?)",
                  (slug, utcnow().isoformat()))
        if enabled is not None:
            c.execute("UPDATE products SET enabled=?, updated_at=? WHERE slug=?",
                      (1 if enabled else 0, utcnow().isoformat(), slug))
        if price_rub is not None:
            c.execute("UPDATE products SET price_rub=?, updated_at=? WHERE slug=?",
                      (int(price_rub), utcnow().isoformat(), slug))


def add_link(slug, title, product=None):
    with _lock, _conn() as c:
        c.execute("INSERT OR REPLACE INTO links (slug, title, product, created_at) VALUES (?,?,?,?)",
                  (slug, title, product, utcnow().isoformat()))


def get_link(slug):
    with _lock, _conn() as c:
        return c.execute("SELECT * FROM links WHERE slug=?", (slug,)).fetchone()


def find_link_by_word(text):
    word = (text or "").strip().lower().lstrip("/")
    if not word or len(word) > 64:
        return None
    with _lock, _conn() as c:
        return c.execute("SELECT * FROM links WHERE lower(slug)=? OR lower(title)=?",
                         (word, word)).fetchone()


def delete_link(slug):
    with _lock, _conn() as c:
        c.execute("DELETE FROM links WHERE slug=?", (slug,))


def links_with_stats():
    with _lock, _conn() as c:
        return c.execute("""
            SELECT l.*,
                   (SELECT COUNT(*) FROM users u WHERE u.source = l.slug) AS starts,
                   (SELECT COUNT(*) FROM users u WHERE u.source = l.slug AND u.consent=1) AS consents,
                   (SELECT COUNT(*) FROM users u WHERE u.source = l.slug
                     AND u.segment IS NOT NULL) AS segments,
                   (SELECT COUNT(DISTINCT p.user_id) FROM purchases p
                     JOIN users u ON u.user_id = p.user_id WHERE u.source = l.slug) AS purchases
            FROM links l ORDER BY l.created_at DESC""").fetchall()


def reset_users(keep_materials=True):
    with _lock, _conn() as c:
        for table in ("users", "purchases", "drip", "events", "orders",
                      "broadcasts", "broadcast_sent"):
            c.execute(f"DELETE FROM {table}")
        if not keep_materials:
            c.execute("DELETE FROM materials")


def add_order(order_id, user_id, product, token, email, amount_rub=None):
    with _lock, _conn() as c:
        c.execute("""INSERT OR REPLACE INTO orders
                     (order_id, user_id, product, token, email, status, amount_rub, created_at)
                     VALUES (?,?,?,?,?, 'pending', ?, ?)""",
                  (order_id, user_id, product, token, email, amount_rub, utcnow().isoformat()))


def add_site_payment(order_id, product, amount_rub, email, paid_at):
    with _lock, _conn() as c:
        c.execute("""INSERT OR IGNORE INTO orders
                     (order_id, user_id, product, token, email, status,
                      amount_rub, created_at, paid_at)
                     VALUES (?, NULL, ?, NULL, ?, 'paid', ?, ?, ?)""",
                  (order_id, product, email, amount_rub, paid_at, paid_at))
        return c.total_changes > 0


def mark_order_paid(order_id, invite_link=None):
    with _lock, _conn() as c:
        c.execute("""UPDATE orders SET status='paid', invite_link=?, paid_at=?
                     WHERE order_id=?""", (invite_link, utcnow().isoformat(), order_id))


def pending_orders(hours):
    since = (utcnow() - timedelta(hours=hours)).isoformat()
    with _lock, _conn() as c:
        return c.execute("SELECT * FROM orders WHERE status='pending' AND created_at>=?",
                         (since,)).fetchall()


def save_invite(user_id, product, link):
    with _lock, _conn() as c:
        c.execute("""INSERT OR REPLACE INTO invites (user_id, product, link, created_at)
                     VALUES (?,?,?,?)""", (user_id, product, link, utcnow().isoformat()))


def get_invite(user_id, product):
    with _lock, _conn() as c:
        row = c.execute("SELECT link FROM invites WHERE user_id=? AND product=?",
                        (user_id, product)).fetchone()
        return row["link"] if row else None


def get_order(order_id):
    with _lock, _conn() as c:
        return c.execute("SELECT * FROM orders WHERE order_id=?", (order_id,)).fetchone()


def last_order(user_id, product):
    with _lock, _conn() as c:
        return c.execute("""SELECT * FROM orders WHERE user_id=? AND product=?
                            ORDER BY order_id DESC LIMIT 1""", (user_id, product)).fetchone()


def user_orders(user_id):
    with _lock, _conn() as c:
        return c.execute("SELECT * FROM orders WHERE user_id=? ORDER BY order_id DESC",
                         (user_id,)).fetchall()


def all_orders():
    with _lock, _conn() as c:
        return c.execute("""SELECT o.*, u.username, u.first_name FROM orders o
                            LEFT JOIN users u ON u.user_id=o.user_id
                            ORDER BY o.order_id DESC""").fetchall()


def create_broadcast(broadcast_id, audience, total, payload):
    with _lock, _conn() as c:
        c.execute("""INSERT OR REPLACE INTO broadcasts
                     (id, audience, total, sent, failed, status, payload, created_at)
                     VALUES (?,?,?,0,0,'running',?,?)""",
                  (broadcast_id, audience, total, payload, utcnow().isoformat()))


def mark_broadcast_sent_bulk(broadcast_id, user_ids):
    if not user_ids:
        return
    with _lock, _conn() as c:
        c.executemany("INSERT OR IGNORE INTO broadcast_sent (broadcast_id, user_id) VALUES (?,?)",
                      [(broadcast_id, uid) for uid in user_ids])


def get_broadcast_sent_ids(broadcast_id):
    with _lock, _conn() as c:
        return {r["user_id"] for r in c.execute(
            "SELECT user_id FROM broadcast_sent WHERE broadcast_id=?", (broadcast_id,))}


def finalize_broadcast(broadcast_id, sent, failed, status="done"):
    with _lock, _conn() as c:
        c.execute("""UPDATE broadcasts SET sent=?, failed=?, status=?, finished_at=?
                     WHERE id=?""",
                  (sent, failed, status, utcnow().isoformat(), broadcast_id))


def last_broadcast():
    with _lock, _conn() as c:
        return c.execute("SELECT * FROM broadcasts ORDER BY created_at DESC LIMIT 1").fetchone()


def broadcasts(limit=50):
    with _lock, _conn() as c:
        return c.execute("SELECT * FROM broadcasts ORDER BY created_at DESC LIMIT ?",
                         (limit,)).fetchall()


def _since(days):
    if not days:
        return "1=1", ()
    start_local = (local_now() - timedelta(days=days - 1)).replace(
        hour=0, minute=0, second=0, microsecond=0)
    return "ts >= ?", ((start_local - timedelta(hours=TZ_HOURS)).isoformat(),)


def period_report(days=None):
    where, args = _since(days)
    ucond = where.replace("ts", "created_at")
    pcond = where.replace("ts", "paid_at")
    with _lock, _conn() as c:
        one = lambda q, a=(): c.execute(q, a).fetchone()[0]
        ev = lambda name: one(f"SELECT COUNT(*) FROM events WHERE event=? AND {where}",
                              (name,) + args)
        evu = lambda name: one(f"SELECT COUNT(DISTINCT user_id) FROM events WHERE event=? AND {where}",
                               (name,) + args)
        paid = one(f"SELECT COUNT(*) FROM orders WHERE status='paid' AND {pcond}", args)
        revenue = one(f"""SELECT COALESCE(SUM(amount_rub),0) FROM orders
                          WHERE status='paid' AND {pcond}""", args)
        return {
            "users": one(f"SELECT COUNT(*) FROM users WHERE {ucond}", args),
            "consents": ev("consent_given"),
            "product_views": evu("product_shown"),
            "orders": one(f"SELECT COUNT(*) FROM orders WHERE {where.replace('ts','created_at')}", args),
            "paid": paid,
            "revenue": revenue,
            "drips": ev("drip_sent"),
            "blocked": one(f"SELECT COUNT(*) FROM users WHERE blocked=1 AND {ucond}", args),
            "books_opened": evu("books_opened"),
        }


def revenue_by_product(days=None):
    where, args = _since(days)
    pcond = where.replace("ts", "paid_at")
    with _lock, _conn() as c:
        return c.execute(f"""SELECT product, COUNT(*) n, COALESCE(SUM(amount_rub),0) total
                             FROM orders WHERE status='paid' AND {pcond}
                             GROUP BY product ORDER BY total DESC""", args).fetchall()


def recent_payments(limit=10):
    with _lock, _conn() as c:
        return c.execute("""SELECT o.*, u.username, u.first_name FROM orders o
                            LEFT JOIN users u ON u.user_id=o.user_id
                            WHERE o.status='paid' ORDER BY o.paid_at DESC LIMIT ?""",
                         (limit,)).fetchall()


def source_report():
    with _lock, _conn() as c:
        return c.execute("""
            SELECT u.source,
                   COUNT(*) AS users,
                   SUM(u.consent=1) AS consents,
                   SUM(u.segment IS NOT NULL) AS segments,
                   (SELECT COUNT(DISTINCT p.user_id) FROM purchases p
                     JOIN users x ON x.user_id=p.user_id WHERE x.source=u.source) AS buyers
            FROM users u GROUP BY u.source ORDER BY users DESC""").fetchall()


def all_users():
    with _lock, _conn() as c:
        return c.execute("""
            SELECT u.*,
                   (SELECT GROUP_CONCAT(p.product) FROM purchases p
                     WHERE p.user_id = u.user_id) AS bought,
                   (SELECT MAX(d.step) FROM drip d WHERE d.user_id = u.user_id) AS drip_step
            FROM users u ORDER BY u.created_at""").fetchall()


def user_drips(user_id):
    with _lock, _conn() as c:
        return c.execute("SELECT * FROM drip WHERE user_id=? ORDER BY product",
                         (user_id,)).fetchall()


def all_purchases():
    with _lock, _conn() as c:
        return c.execute("""
            SELECT p.*, u.username, u.first_name, u.source
            FROM purchases p LEFT JOIN users u ON u.user_id = p.user_id
            ORDER BY p.paid_at""").fetchall()


def all_events(limit=5000):
    with _lock, _conn() as c:
        return c.execute("SELECT * FROM events ORDER BY id DESC LIMIT ?", (limit,)).fetchall()


def daily_stats():
    with _lock, _conn() as c:
        return c.execute("""
            SELECT day,
                   SUM(starts) starts, SUM(consents) consents,
                   SUM(product_views) product_views, SUM(paid) paid,
                   SUM(revenue) revenue, SUM(drips) drips
            FROM (
                SELECT substr(datetime(ts, '+3 hours'),1,10) AS day,
                       SUM(event='start')         AS starts,
                       SUM(event='consent_given') AS consents,
                       SUM(event='product_shown') AS product_views,
                       0 AS paid, 0 AS revenue,
                       SUM(event='drip_sent')     AS drips
                FROM events GROUP BY day
                UNION ALL
                SELECT substr(datetime(paid_at, '+3 hours'),1,10) AS day, 0, 0, 0,
                       COUNT(*), COALESCE(SUM(amount_rub),0), 0
                FROM orders WHERE status='paid' GROUP BY day
            ) GROUP BY day ORDER BY day""").fetchall()


def monthly_stats():
    with _lock, _conn() as c:
        return c.execute("""
            SELECT substr(datetime(paid_at, '+3 hours'),1,7) AS month, COUNT(*) AS paid,
                   COALESCE(SUM(amount_rub),0) AS revenue
            FROM orders WHERE status='paid'
            GROUP BY month ORDER BY month DESC""").fetchall()


def paid_orders():
    with _lock, _conn() as c:
        return c.execute("""SELECT o.*, u.username, u.first_name, u.source
                            FROM orders o LEFT JOIN users u ON u.user_id=o.user_id
                            WHERE o.status='paid' ORDER BY o.paid_at DESC""").fetchall()


def funnel():
    with _lock, _conn() as c:
        g = lambda q: c.execute(q).fetchone()[0]
        return [
            ("Запустили бота", g("SELECT COUNT(*) FROM users")),
            ("Дали согласие", g("SELECT COUNT(*) FROM users WHERE consent=1")),
            ("Выбрали направление", g("SELECT COUNT(*) FROM users WHERE segment IS NOT NULL")),
            ("Сообщили об оплате",
             g("SELECT COUNT(DISTINCT user_id) FROM events WHERE event='claim_paid'")),
            ("Получили доступ", g("SELECT COUNT(DISTINCT user_id) FROM purchases")),
        ]


def stats():
    with _lock, _conn() as c:
        g = lambda q, *a: c.execute(q, a).fetchone()[0]
        return {
            "total": g("SELECT COUNT(*) FROM users"),
            "consent": g("SELECT COUNT(*) FROM users WHERE consent=1"),
            "blocked": g("SELECT COUNT(*) FROM users WHERE blocked=1"),
            "seg_kod": g("SELECT COUNT(*) FROM users WHERE segment='kod'"),
            "seg_per": g("SELECT COUNT(*) FROM users WHERE segment='peresborka'"),
            "src_ig": g("SELECT COUNT(*) FROM users WHERE source='ig'"),
            "src_yt": g("SELECT COUNT(*) FROM users WHERE source='yt'"),
            "src_direct": g("SELECT COUNT(*) FROM users WHERE source='direct'"),
            "buy_kod": g("SELECT COUNT(*) FROM purchases WHERE product='kod'"),
            "buy_per": g("SELECT COUNT(*) FROM purchases WHERE product='peresborka'"),
            "claims": g("SELECT COUNT(DISTINCT user_id) FROM events WHERE event='claim_paid'"),
            "buyers": g("SELECT COUNT(DISTINCT user_id) FROM purchases"),
            "drip_active": g("SELECT COUNT(*) FROM drip WHERE stopped=0"),
            "drip_muted": g("SELECT COUNT(DISTINCT user_id) FROM drip WHERE muted=1"),
            "drips_sent": g("SELECT COUNT(*) FROM events WHERE event='drip_sent'"),
            "books_opened": g("SELECT COUNT(DISTINCT user_id) FROM events WHERE event='books_opened'"),
            "today": g("SELECT COUNT(*) FROM users WHERE "
                       + LOCAL_DAY_CREATED + " = date('now', " + TZ_SQL_PY + ")"),
            "week": g("SELECT COUNT(*) FROM users WHERE created_at >= datetime('now','-7 days')"),
        }
