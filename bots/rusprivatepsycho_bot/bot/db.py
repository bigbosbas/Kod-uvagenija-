from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo


@dataclass(slots=True)
class Plan:
    id: int
    code: str
    title: str
    price_rub: int
    duration_days: int
    description: str
    is_active: bool


DEFAULT_PLANS = (
    ("week", "1 неделя", 500, 7, "Быстрый доступ к закрытому каналу", 1, 10),
    ("month", "1 месяц", 990, 30, "Полный доступ на 1 месяц", 1, 20),
    ("quarter", "3 месяца", 1990, 90, "Расширенный доступ на 3 месяца", 1, 30),
    ("halfyear", "6 месяцев", 3490, 180, "Долгий доступ на 6 месяцев", 0, 40),
    ("year", "12 месяцев", 5990, 365, "Максимальный тариф на 12 месяцев", 0, 50),
)


DEFAULT_SETTINGS = {
    "channel_about_text": (
        "Закрытый канал практической психологии\n\n"
        "Это закрытое пространство для тех, кто хочет лучше понимать людей, видеть манипуляции, "
        "увереннее выстраивать общение, защищать свои границы и усиливать свою позицию в жизни, "
        "отношениях и работе.\n\n"
        "Внутри канала:\n"
        "- практические разборы психологии общения\n"
        "- скрытые механизмы давления и манипуляций\n"
        "- психология мошенников и способы распознавания влияния\n"
        "- материалы о личных границах, самооценке и внутренней опоре\n"
        "- прикладные инструменты для реальной жизни\n\n"
        "Это закрытый формат с регулярными материалами для тех, кто хочет получать не мотивационные фразы, "
        "а реальные знания и работающие психологические инструменты.\n\n"
        "Подписка открывает доступ ко всем материалам закрытого канала на выбранный период."
    ),
    "support_text": "Если нужна помощь, напишите администратору: @support_username",
    "tmpl_welcome": (
        "Привет, {first_name}!\n\n"
        "Прежде чем начать, пожалуйста, ознакомьтесь с документами:\n\n"
        "📄 <a href=\"{offer_url}\">Публичная оферта</a>\n"
        "🔒 <a href=\"{policy_url}\">Политика обработки персональных данных</a>\n\n"
        "Нажимая кнопку «Принимаю», вы подтверждаете, что ознакомились и согласны "
        "с условиями публичной оферты и политикой обработки персональных данных."
    ),
    "tmpl_payment_success": (
        "Оплата прошла успешно.\n\n"
        "Ваш доступ в закрытый Telegram-канал активирован.\n"
        "Теперь вам доступны все материалы канала в течение оплаченного периода.\n\n"
        "Переходите в канал и начинайте с закрепленного сообщения."
    ),
    "tmpl_payment_error": "Оплата не была подтверждена. Попробуйте еще раз или напишите в поддержку.",
    "tmpl_access_granted": (
        "Доступ выдан.\n\n"
        "Ссылка для входа в канал:\n{invite_link}\n\n"
        "Доступ активен до: {expires_at}"
    ),
    "tmpl_renewal_reminder": (
        "Напоминание: подписка скоро закончится.\n"
        "Тариф: {plan_title}\n"
        "Доступ активен до: {expires_at}\n\n"
        "Чтобы сохранить доступ, продлите подписку."
    ),
    "tmpl_subscription_expired": (
        "Срок подписки закончился.\n\n"
        "Доступ в канал остановлен. Чтобы вернуть доступ, оформите продление."
    ),
}


class Database:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()
        self._migrate_legacy_schema()
        self._migrate_payments_columns()
        self._seed_defaults()

    @contextmanager
    def connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    def _init_db(self) -> None:
        with self.connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS users (
                    user_id INTEGER PRIMARY KEY,
                    username TEXT,
                    first_name TEXT,
                    last_name TEXT,
                    accepted_terms INTEGER NOT NULL DEFAULT 0,
                    registered_at TEXT NOT NULL,
                    subscription_status TEXT NOT NULL DEFAULT 'inactive',
                    current_plan_id INTEGER,
                    subscription_started_at TEXT,
                    subscription_expires_at TEXT,
                    access_status TEXT NOT NULL DEFAULT 'inactive',
                    current_invite_link TEXT,
                    blocked INTEGER NOT NULL DEFAULT 0,
                    notified_3d_at TEXT,
                    notified_1d_at TEXT,
                    notified_day_at TEXT,
                    notified_expired_at TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS plans (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    code TEXT NOT NULL UNIQUE,
                    title TEXT NOT NULL,
                    price_rub INTEGER NOT NULL,
                    duration_days INTEGER NOT NULL,
                    description TEXT NOT NULL,
                    is_active INTEGER NOT NULL DEFAULT 1,
                    sort_order INTEGER NOT NULL DEFAULT 100,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS payments (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    plan_id INTEGER NOT NULL,
                    amount_rub INTEGER NOT NULL,
                    status TEXT NOT NULL,
                    payment_provider TEXT NOT NULL,
                    external_payment_id TEXT,
                    invite_link TEXT,
                    access_expires_at TEXT,
                    payment_prompt_message_id INTEGER,
                    created_at TEXT NOT NULL,
                    paid_at TEXT,
                    error_message TEXT,
                    raw_payload TEXT,
                    UNIQUE(payment_provider, external_payment_id),
                    FOREIGN KEY(user_id) REFERENCES users(user_id),
                    FOREIGN KEY(plan_id) REFERENCES plans(id)
                );

                CREATE TABLE IF NOT EXISTS settings (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS logs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    event_type TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    user_id INTEGER,
                    description TEXT NOT NULL,
                    error_text TEXT,
                    technical_details TEXT
                );
                """
            )

    def _migrate_legacy_schema(self) -> None:
        required_columns: dict[str, str] = {
            "registered_at": "TEXT",
            "subscription_status": "TEXT NOT NULL DEFAULT 'inactive'",
            "current_plan_id": "INTEGER",
            "subscription_started_at": "TEXT",
            "subscription_expires_at": "TEXT",
            "access_status": "TEXT NOT NULL DEFAULT 'inactive'",
            "blocked": "INTEGER NOT NULL DEFAULT 0",
            "notified_3d_at": "TEXT",
            "notified_1d_at": "TEXT",
            "notified_day_at": "TEXT",
            "notified_expired_at": "TEXT",
        }
        with self.connect() as conn:
            existing = {
                row["name"]
                for row in conn.execute("PRAGMA table_info(users)").fetchall()
            }
            for column_name, column_type in required_columns.items():
                if column_name not in existing:
                    conn.execute(f"ALTER TABLE users ADD COLUMN {column_name} {column_type}")

            conn.execute(
                "UPDATE users SET registered_at = COALESCE(registered_at, created_at) "
                "WHERE registered_at IS NULL"
            )

            if "invite_expires_at" in existing:
                conn.execute(
                    """
                    UPDATE users
                    SET subscription_expires_at = COALESCE(subscription_expires_at, invite_expires_at),
                        access_status = 'active',
                        subscription_status = 'active'
                    WHERE COALESCE(subscription_expires_at, invite_expires_at) IS NOT NULL
                      AND (subscription_status IS NULL OR subscription_status = 'inactive')
                    """
                )

    def _migrate_payments_columns(self) -> None:
        with self.connect() as conn:
            pay_cols = {row["name"] for row in conn.execute("PRAGMA table_info(payments)").fetchall()}
            if "payment_prompt_message_id" not in pay_cols:
                conn.execute("ALTER TABLE payments ADD COLUMN payment_prompt_message_id INTEGER")

    def _seed_defaults(self) -> None:
        now = self._now_iso()
        with self.connect() as conn:
            for code, title, price_rub, duration_days, description, is_active, sort_order in DEFAULT_PLANS:
                conn.execute(
                    """
                    INSERT INTO plans (
                        code, title, price_rub, duration_days, description, is_active, sort_order, created_at, updated_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(code) DO NOTHING
                    """,
                    (
                        code,
                        title,
                        price_rub,
                        duration_days,
                        description,
                        is_active,
                        sort_order,
                        now,
                        now,
                    ),
                )
            for key, value in DEFAULT_SETTINGS.items():
                conn.execute(
                    """
                    INSERT INTO settings (key, value)
                    VALUES (?, ?)
                    ON CONFLICT(key) DO NOTHING
                    """,
                    (key, value),
                )

    def log_event(
        self,
        event_type: str,
        description: str,
        user_id: int | None = None,
        error_text: str | None = None,
        technical_details: str | None = None,
    ) -> None:
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO logs (event_type, created_at, user_id, description, error_text, technical_details)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (event_type, self._now_iso(), user_id, description, error_text, technical_details),
            )

    def upsert_user(
        self,
        user_id: int,
        username: str | None,
        first_name: str | None,
        last_name: str | None,
    ) -> None:
        now = self._now_iso()
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO users (
                    user_id, username, first_name, last_name, registered_at, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(user_id) DO UPDATE SET
                    username = excluded.username,
                    first_name = excluded.first_name,
                    last_name = excluded.last_name,
                    updated_at = excluded.updated_at
                """,
                (user_id, username, first_name, last_name, now, now, now),
            )

    def set_terms_accepted(self, user_id: int) -> None:
        with self.connect() as conn:
            conn.execute(
                "UPDATE users SET accepted_terms = 1, updated_at = ? WHERE user_id = ?",
                (self._now_iso(), user_id),
            )

    def has_accepted_terms(self, user_id: int) -> bool:
        with self.connect() as conn:
            row = conn.execute(
                "SELECT accepted_terms FROM users WHERE user_id = ?",
                (user_id,),
            ).fetchone()
        return bool(row and row["accepted_terms"])

    def get_setting(self, key: str) -> str | None:
        with self.connect() as conn:
            row = conn.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
        return row["value"] if row else None

    def set_setting(self, key: str, value: str) -> None:
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO settings (key, value)
                VALUES (?, ?)
                ON CONFLICT(key) DO UPDATE SET value = excluded.value
                """,
                (key, value),
            )

    def delete_setting(self, key: str) -> None:
        with self.connect() as conn:
            conn.execute("DELETE FROM settings WHERE key = ?", (key,))

    def list_settings(self) -> dict[str, str]:
        with self.connect() as conn:
            rows = conn.execute("SELECT key, value FROM settings ORDER BY key").fetchall()
        return {row["key"]: row["value"] for row in rows}

    def list_active_plans(self) -> list[Plan]:
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT id, code, title, price_rub, duration_days, description, is_active
                FROM plans
                WHERE is_active = 1
                ORDER BY sort_order, id
                """
            ).fetchall()
        return [self._row_to_plan(row) for row in rows]

    def list_all_plans(self) -> list[Plan]:
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT id, code, title, price_rub, duration_days, description, is_active
                FROM plans
                ORDER BY is_active DESC, id
                """
            ).fetchall()
        return [self._row_to_plan(row) for row in rows]

    def get_plan_by_code(self, code: str) -> Plan | None:
        with self.connect() as conn:
            row = conn.execute(
                """
                SELECT id, code, title, price_rub, duration_days, description, is_active
                FROM plans
                WHERE code = ?
                """,
                (code,),
            ).fetchone()
        return self._row_to_plan(row) if row else None

    def get_plan_by_id(self, plan_id: int) -> Plan | None:
        with self.connect() as conn:
            row = conn.execute(
                """
                SELECT id, code, title, price_rub, duration_days, description, is_active
                FROM plans
                WHERE id = ?
                """,
                (plan_id,),
            ).fetchone()
        return self._row_to_plan(row) if row else None

    def upsert_plan(
        self,
        code: str,
        title: str,
        price_rub: int,
        duration_days: int,
        description: str,
        is_active: bool,
    ) -> None:
        now = self._now_iso()
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO plans (
                    code, title, price_rub, duration_days, description, is_active, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(code) DO UPDATE SET
                    title = excluded.title,
                    price_rub = excluded.price_rub,
                    duration_days = excluded.duration_days,
                    description = excluded.description,
                    is_active = excluded.is_active,
                    updated_at = excluded.updated_at
                """,
                (code, title, price_rub, duration_days, description, int(is_active), now, now),
            )

    def set_plan_active(self, code: str, is_active: bool) -> None:
        with self.connect() as conn:
            conn.execute(
                "UPDATE plans SET is_active = ?, updated_at = ? WHERE code = ?",
                (int(is_active), self._now_iso(), code),
            )

    def create_payment(
        self,
        user_id: int,
        plan_id: int,
        amount_rub: int,
        payment_provider: str = "telegram_stub",
        external_payment_id: str | None = None,
    ) -> int:
        with self.connect() as conn:
            cursor = conn.execute(
                """
                INSERT INTO payments (
                    user_id, plan_id, amount_rub, status, payment_provider, external_payment_id, created_at
                )
                VALUES (?, ?, ?, 'pending', ?, ?, ?)
                """,
                (user_id, plan_id, amount_rub, payment_provider, external_payment_id, self._now_iso()),
            )
            return int(cursor.lastrowid)

    def set_payment_prompt_message(self, payment_id: int, message_id: int) -> None:
        with self.connect() as conn:
            conn.execute(
                """
                UPDATE payments
                SET payment_prompt_message_id = ?
                WHERE id = ? AND status = 'pending'
                """,
                (message_id, payment_id),
            )

    def clear_payment_prompt_message(self, payment_id: int) -> None:
        with self.connect() as conn:
            conn.execute(
                "UPDATE payments SET payment_prompt_message_id = NULL WHERE id = ?",
                (payment_id,),
            )

    def get_payment(self, payment_id: int) -> sqlite3.Row | None:
        with self.connect() as conn:
            return conn.execute(
                """
                SELECT p.*, pl.code AS plan_code, pl.title AS plan_title, pl.duration_days
                FROM payments p
                JOIN plans pl ON pl.id = p.plan_id
                WHERE p.id = ?
                """,
                (payment_id,),
            ).fetchone()

    def get_user_status(self, user_id: int) -> sqlite3.Row | None:
        with self.connect() as conn:
            return conn.execute(
                """
                SELECT
                    u.*,
                    pl.title AS plan_title,
                    pl.duration_days AS plan_duration_days
                FROM users u
                LEFT JOIN plans pl ON pl.id = u.current_plan_id
                WHERE u.user_id = ?
                """,
                (user_id,),
            ).fetchone()

    def get_user_access(self, user_id: int) -> sqlite3.Row | None:
        with self.connect() as conn:
            return conn.execute(
                """
                SELECT current_invite_link, subscription_expires_at, access_status, subscription_status
                FROM users
                WHERE user_id = ?
                """,
                (user_id,),
            ).fetchone()

    def mark_payment_paid(self, payment_id: int, invite_link: str) -> sqlite3.Row:
        payment = self.get_payment(payment_id)
        if payment is None:
            raise ValueError("Payment not found")
        if payment["status"] == "paid":
            return payment
        if payment["status"] not in {"pending", "cancelled"}:
            raise ValueError(f"Payment not pending/cancelled (status={payment['status']})")

        now = self._now_dt()
        user = self.get_user_status(payment["user_id"])
        current_expiry = self._parse_dt(user["subscription_expires_at"]) if user and user["subscription_expires_at"] else None
        base_dt = current_expiry if current_expiry and current_expiry > now else now
        expires_at = base_dt + timedelta(days=int(payment["duration_days"]))
        now_iso = now.isoformat()
        expires_iso = expires_at.isoformat()

        with self.connect() as conn:
            cur = conn.execute(
                """
                UPDATE payments
                SET status = 'paid',
                    invite_link = ?,
                    access_expires_at = ?,
                    paid_at = ?,
                    error_message = NULL
                WHERE id = ? AND status IN ('pending', 'cancelled')
                """,
                (invite_link, expires_iso, now_iso, payment_id),
            )
            if not cur.rowcount:
                raise ValueError("Payment not pending/cancelled")
            conn.execute(
                """
                UPDATE users
                SET subscription_status = 'active',
                    current_plan_id = ?,
                    subscription_started_at = COALESCE(subscription_started_at, ?),
                    subscription_expires_at = ?,
                    access_status = 'active',
                    current_invite_link = ?,
                    blocked = 0,
                    notified_3d_at = NULL,
                    notified_1d_at = NULL,
                    notified_day_at = NULL,
                    notified_expired_at = NULL,
                    updated_at = ?
                WHERE user_id = ?
                """,
                (
                    payment["plan_id"],
                    now_iso,
                    expires_iso,
                    invite_link,
                    now_iso,
                    payment["user_id"],
                ),
            )
        self.log_event("payment_paid", f"Payment #{payment_id} marked paid", user_id=payment["user_id"])
        refreshed = self.get_payment(payment_id)
        if refreshed is None:
            raise ValueError("Payment disappeared")
        return refreshed

    def mark_payment_failed(self, payment_id: int, error_message: str) -> None:
        with self.connect() as conn:
            conn.execute(
                """
                UPDATE payments
                SET status = 'failed',
                    error_message = ?
                WHERE id = ? AND status = 'pending'
                """,
                (error_message, payment_id),
            )
        payment = self.get_payment(payment_id)
        self.log_event("payment_failed", f"Payment #{payment_id} failed", user_id=payment["user_id"] if payment else None, error_text=error_message)

    def mark_payment_cancelled(self, payment_id: int) -> None:
        with self.connect() as conn:
            conn.execute(
                "UPDATE payments SET status = 'cancelled' WHERE id = ? AND status = 'pending'",
                (payment_id,),
            )

    STALE_PENDING_MINUTES = 30

    def cancel_stale_pending_payments(self, max_age_minutes: int | None = None) -> int:
        minutes = max_age_minutes if max_age_minutes is not None else self.STALE_PENDING_MINUTES
        cutoff = (self._now_dt() - timedelta(minutes=minutes)).isoformat()
        msg = f"Истёк срок ожидания оплаты ({minutes} мин.)"
        with self.connect() as conn:
            cur = conn.execute(
                """
                UPDATE payments
                SET status = 'cancelled',
                    error_message = ?
                WHERE status = 'pending'
                  AND created_at < ?
                """,
                (msg, cutoff),
            )
            rc = cur.rowcount
        n = int(rc) if rc is not None and rc >= 0 else 0
        if n:
            self.log_event(
                "payments_stale_pending_cancelled",
                f"Отменено зависших pending: {n} (старше {minutes} мин.)",
            )
        return n

    def count_search_users(self, query: str) -> int:
        pattern = f"%{query.lower()}%"
        with self.connect() as conn:
            row = conn.execute(
                """
                SELECT COUNT(*) AS c
                FROM users u
                WHERE CAST(u.user_id AS TEXT) LIKE ?
                   OR LOWER(COALESCE(u.username, '')) LIKE ?
                   OR LOWER(COALESCE(u.first_name, '') || ' ' || COALESCE(u.last_name, '')) LIKE ?
                """,
                (pattern, pattern, pattern),
            ).fetchone()
        return int(row["c"]) if row else 0

    def search_users(self, query: str, limit: int = 20, offset: int = 0) -> list[sqlite3.Row]:
        pattern = f"%{query.lower()}%"
        with self.connect() as conn:
            return conn.execute(
                """
                SELECT u.*, pl.title AS plan_title
                FROM users u
                LEFT JOIN plans pl ON pl.id = u.current_plan_id
                WHERE CAST(u.user_id AS TEXT) LIKE ?
                   OR LOWER(COALESCE(u.username, '')) LIKE ?
                   OR LOWER(COALESCE(u.first_name, '') || ' ' || COALESCE(u.last_name, '')) LIKE ?
                ORDER BY u.updated_at DESC
                LIMIT ? OFFSET ?
                """,
                (pattern, pattern, pattern, limit, offset),
            ).fetchall()

    def count_users(self, mode: str = "all") -> int:
        now_iso = self._now_iso()
        with self.connect() as conn:
            if mode == "active":
                row = conn.execute(
                    """
                    SELECT COUNT(*) AS c FROM users
                    WHERE blocked = 0
                      AND subscription_expires_at IS NOT NULL
                      AND subscription_expires_at > ?
                      AND subscription_status NOT IN ('expired', 'blocked')
                    """,
                    (now_iso,),
                ).fetchone()
            elif mode == "expired":
                row = conn.execute(
                    """
                    SELECT COUNT(*) AS c FROM users
                    WHERE blocked = 0
                      AND (
                        subscription_status = 'expired'
                        OR (
                          subscription_expires_at IS NOT NULL
                          AND subscription_expires_at <= ?
                          AND subscription_status != 'blocked'
                        )
                      )
                    """,
                    (now_iso,),
                ).fetchone()
            elif mode == "blocked":
                row = conn.execute("SELECT COUNT(*) AS c FROM users WHERE blocked = 1").fetchone()
            else:
                row = conn.execute("SELECT COUNT(*) AS c FROM users").fetchone()
        return int(row["c"]) if row else 0

    def list_users(self, mode: str = "all", limit: int = 20, offset: int = 0) -> list[sqlite3.Row]:
        now_iso = self._now_iso()
        with self.connect() as conn:
            if mode == "active":
                return conn.execute(
                    """
                    SELECT u.*, pl.title AS plan_title
                    FROM users u
                    LEFT JOIN plans pl ON pl.id = u.current_plan_id
                    WHERE u.blocked = 0
                      AND u.subscription_expires_at IS NOT NULL
                      AND u.subscription_expires_at > ?
                      AND u.subscription_status NOT IN ('expired', 'blocked')
                    ORDER BY u.updated_at DESC
                    LIMIT ? OFFSET ?
                    """,
                    (now_iso, limit, offset),
                ).fetchall()
            if mode == "expired":
                return conn.execute(
                    """
                    SELECT u.*, pl.title AS plan_title
                    FROM users u
                    LEFT JOIN plans pl ON pl.id = u.current_plan_id
                    WHERE u.blocked = 0
                      AND (
                        u.subscription_status = 'expired'
                        OR (
                          u.subscription_expires_at IS NOT NULL
                          AND u.subscription_expires_at <= ?
                          AND u.subscription_status != 'blocked'
                        )
                      )
                    ORDER BY u.updated_at DESC
                    LIMIT ? OFFSET ?
                    """,
                    (now_iso, limit, offset),
                ).fetchall()
            if mode == "blocked":
                return conn.execute(
                    """
                    SELECT u.*, pl.title AS plan_title
                    FROM users u
                    LEFT JOIN plans pl ON pl.id = u.current_plan_id
                    WHERE u.blocked = 1
                    ORDER BY u.updated_at DESC
                    LIMIT ? OFFSET ?
                    """,
                    (limit, offset),
                ).fetchall()
            return conn.execute(
                """
                SELECT u.*, pl.title AS plan_title
                FROM users u
                LEFT JOIN plans pl ON pl.id = u.current_plan_id
                ORDER BY u.updated_at DESC
                LIMIT ? OFFSET ?
                """,
                (limit, offset),
            ).fetchall()

    def list_payments(self, status: str | None = None, limit: int = 20, offset: int = 0) -> list[sqlite3.Row]:
        where = ""
        params: list[object] = []
        if status:
            where = "WHERE p.status = ?"
            params.append(status)
        params.extend([limit, offset])
        with self.connect() as conn:
            return conn.execute(
                f"""
                SELECT p.*, pl.title AS plan_title
                FROM payments p
                JOIN plans pl ON pl.id = p.plan_id
                {where}
                ORDER BY p.created_at DESC
                LIMIT ? OFFSET ?
                """,
                params,
            ).fetchall()

    def count_payments(self, status: str | None = None) -> int:
        where = ""
        params: list[object] = []
        if status:
            where = "WHERE status = ?"
            params.append(status)
        with self.connect() as conn:
            row = conn.execute(f"SELECT COUNT(*) AS c FROM payments {where}", params).fetchone()
        return int(row["c"]) if row else 0

    def get_user_payment_history(self, user_id: int, limit: int = 20) -> list[sqlite3.Row]:
        with self.connect() as conn:
            return conn.execute(
                """
                SELECT p.*, pl.title AS plan_title
                FROM payments p
                JOIN plans pl ON pl.id = p.plan_id
                WHERE p.user_id = ?
                ORDER BY p.created_at DESC
                LIMIT ?
                """,
                (user_id, limit),
            ).fetchall()

    BROADCAST_SEGMENTS = frozenset(
        {
            "everyone",
            "active_subscription",
            "expired",
            "ever_paid",
            "never_paid",
            "no_active_now",
        }
    )

    def count_broadcast_recipients(self, segment: str) -> int:
        if segment not in self.BROADCAST_SEGMENTS:
            raise ValueError("unknown segment")
        now_iso = self._now_iso()
        with self.connect() as conn:
            if segment == "everyone":
                row = conn.execute("SELECT COUNT(*) AS c FROM users WHERE blocked = 0").fetchone()
            elif segment == "active_subscription":
                row = conn.execute(
                    """
                    SELECT COUNT(*) AS c FROM users
                    WHERE blocked = 0
                      AND subscription_expires_at IS NOT NULL
                      AND subscription_expires_at > ?
                      AND subscription_status NOT IN ('expired', 'blocked')
                    """,
                    (now_iso,),
                ).fetchone()
            elif segment == "expired":
                row = conn.execute(
                    """
                    SELECT COUNT(*) AS c FROM users
                    WHERE blocked = 0
                      AND (
                        subscription_status = 'expired'
                        OR (
                          subscription_expires_at IS NOT NULL
                          AND subscription_expires_at <= ?
                          AND subscription_status != 'blocked'
                        )
                      )
                    """,
                    (now_iso,),
                ).fetchone()
            elif segment == "ever_paid":
                row = conn.execute(
                    """
                    SELECT COUNT(DISTINCT u.user_id) AS c
                    FROM users u
                    INNER JOIN payments p ON p.user_id = u.user_id AND p.status = 'paid'
                    WHERE u.blocked = 0
                    """
                ).fetchone()
            elif segment == "never_paid":
                row = conn.execute(
                    """
                    SELECT COUNT(*) AS c FROM users u
                    WHERE u.blocked = 0
                      AND NOT EXISTS (
                        SELECT 1 FROM payments p
                        WHERE p.user_id = u.user_id AND p.status = 'paid'
                      )
                    """
                ).fetchone()
            else:
                row = conn.execute(
                    """
                    SELECT COUNT(*) AS c FROM users
                    WHERE blocked = 0
                      AND NOT (
                        subscription_expires_at IS NOT NULL
                        AND subscription_expires_at > ?
                        AND subscription_status NOT IN ('expired', 'blocked')
                      )
                    """,
                    (now_iso,),
                ).fetchone()
        return int(row["c"]) if row else 0

    def list_broadcast_recipient_ids(self, segment: str) -> list[int]:
        if segment not in self.BROADCAST_SEGMENTS:
            raise ValueError("unknown segment")
        now_iso = self._now_iso()
        with self.connect() as conn:
            if segment == "everyone":
                rows = conn.execute(
                    "SELECT user_id FROM users WHERE blocked = 0 ORDER BY user_id"
                ).fetchall()
            elif segment == "active_subscription":
                rows = conn.execute(
                    """
                    SELECT user_id FROM users
                    WHERE blocked = 0
                      AND subscription_expires_at IS NOT NULL
                      AND subscription_expires_at > ?
                      AND subscription_status NOT IN ('expired', 'blocked')
                    ORDER BY user_id
                    """,
                    (now_iso,),
                ).fetchall()
            elif segment == "expired":
                rows = conn.execute(
                    """
                    SELECT user_id FROM users
                    WHERE blocked = 0
                      AND (
                        subscription_status = 'expired'
                        OR (
                          subscription_expires_at IS NOT NULL
                          AND subscription_expires_at <= ?
                          AND subscription_status != 'blocked'
                        )
                      )
                    ORDER BY user_id
                    """,
                    (now_iso,),
                ).fetchall()
            elif segment == "ever_paid":
                rows = conn.execute(
                    """
                    SELECT DISTINCT u.user_id AS user_id
                    FROM users u
                    INNER JOIN payments p ON p.user_id = u.user_id AND p.status = 'paid'
                    WHERE u.blocked = 0
                    ORDER BY u.user_id
                    """
                ).fetchall()
            elif segment == "never_paid":
                rows = conn.execute(
                    """
                    SELECT u.user_id AS user_id FROM users u
                    WHERE u.blocked = 0
                      AND NOT EXISTS (
                        SELECT 1 FROM payments p
                        WHERE p.user_id = u.user_id AND p.status = 'paid'
                      )
                    ORDER BY u.user_id
                    """
                ).fetchall()
            else:
                rows = conn.execute(
                    """
                    SELECT user_id FROM users
                    WHERE blocked = 0
                      AND NOT (
                        subscription_expires_at IS NOT NULL
                        AND subscription_expires_at > ?
                        AND subscription_status NOT IN ('expired', 'blocked')
                      )
                    ORDER BY user_id
                    """,
                    (now_iso,),
                ).fetchall()
        return [int(r["user_id"]) for r in rows]

    def set_user_blocked(self, user_id: int, blocked: bool) -> None:
        now_iso = self._now_iso()
        if blocked:
            with self.connect() as conn:
                conn.execute(
                    """
                    UPDATE users
                    SET blocked = 1,
                        subscription_status = 'blocked',
                        access_status = 'blocked',
                        updated_at = ?
                    WHERE user_id = ?
                    """,
                    (now_iso, user_id),
                )
            return
        user = self.get_user_status(user_id)
        if user is None:
            return
        now = self._now_dt()
        exp = self._parse_dt(user["subscription_expires_at"]) if user["subscription_expires_at"] else None
        if exp and exp > now:
            sub_st, acc_st = "active", "active"
        elif exp and exp <= now:
            sub_st, acc_st = "expired", "expired"
        else:
            sub_st, acc_st = "inactive", "inactive"
        with self.connect() as conn:
            conn.execute(
                """
                UPDATE users
                SET blocked = 0,
                    subscription_status = ?,
                    access_status = ?,
                    updated_at = ?
                WHERE user_id = ?
                """,
                (sub_st, acc_st, now_iso, user_id),
            )

    def manual_extend_subscription(self, user_id: int, days: int, plan_id: int | None = None) -> sqlite3.Row | None:
        user = self.get_user_status(user_id)
        if user is None:
            return None
        now = self._now_dt()
        current_expiry = self._parse_dt(user["subscription_expires_at"]) if user["subscription_expires_at"] else None
        base_dt = current_expiry if current_expiry and current_expiry > now else now
        expires_at = base_dt + timedelta(days=days)
        with self.connect() as conn:
            conn.execute(
                """
                UPDATE users
                SET subscription_status = 'active',
                    current_plan_id = COALESCE(?, current_plan_id),
                    subscription_started_at = COALESCE(subscription_started_at, ?),
                    subscription_expires_at = ?,
                    access_status = 'active',
                    blocked = 0,
                    notified_3d_at = NULL,
                    notified_1d_at = NULL,
                    notified_day_at = NULL,
                    notified_expired_at = NULL,
                    updated_at = ?
                WHERE user_id = ?
                """,
                (plan_id, now.isoformat(), expires_at.isoformat(), self._now_iso(), user_id),
            )
        return self.get_user_status(user_id)

    def parse_expires_date_moscow_end(self, ymd: str) -> datetime | None:
        try:
            d = date.fromisoformat(ymd.strip())
        except ValueError:
            return None
        msk = ZoneInfo("Europe/Moscow")
        end_local = datetime.combine(d, time(23, 59, 59, 999999), tzinfo=msk)
        return end_local.astimezone(timezone.utc)

    def manual_set_subscription_expires_at(self, user_id: int, expires_at: datetime) -> sqlite3.Row | None:
        user = self.get_user_status(user_id)
        if user is None:
            return None
        now = self._now_dt()
        expires_iso = expires_at.isoformat()
        with self.connect() as conn:
            conn.execute(
                """
                UPDATE users
                SET subscription_status = 'active',
                    subscription_started_at = COALESCE(subscription_started_at, ?),
                    subscription_expires_at = ?,
                    access_status = 'active',
                    blocked = 0,
                    notified_3d_at = NULL,
                    notified_1d_at = NULL,
                    notified_day_at = NULL,
                    notified_expired_at = NULL,
                    updated_at = ?
                WHERE user_id = ?
                """,
                (now.isoformat(), expires_iso, self._now_iso(), user_id),
            )
        return self.get_user_status(user_id)

    def ensure_plan_for_manual_grant(self, user_id: int) -> int | None:
        user = self.get_user_status(user_id)
        if user is None:
            return None
        if user["current_plan_id"]:
            return int(user["current_plan_id"])
        plans = self.list_active_plans()
        if not plans:
            return None
        pid = int(plans[0].id)
        with self.connect() as conn:
            conn.execute(
                "UPDATE users SET current_plan_id = ?, updated_at = ? WHERE user_id = ?",
                (pid, self._now_iso(), user_id),
            )
        return pid

    def update_user_invite(self, user_id: int, invite_link: str | None) -> None:
        with self.connect() as conn:
            conn.execute(
                """
                UPDATE users
                SET current_invite_link = ?, updated_at = ?
                WHERE user_id = ?
                """,
                (invite_link, self._now_iso(), user_id),
            )

    def expire_subscription(self, user_id: int) -> None:
        with self.connect() as conn:
            conn.execute(
                """
                UPDATE users
                SET subscription_status = 'expired',
                    access_status = 'expired',
                    current_invite_link = NULL,
                    updated_at = ?
                WHERE user_id = ?
                """,
                (self._now_iso(), user_id),
            )

    def get_expired_active_users(self) -> list[sqlite3.Row]:
        now_iso = self._now_iso()
        with self.connect() as conn:
            return conn.execute(
                """
                SELECT u.*, pl.title AS plan_title
                FROM users u
                LEFT JOIN plans pl ON pl.id = u.current_plan_id
                WHERE u.subscription_status = 'active'
                  AND u.subscription_expires_at IS NOT NULL
                  AND u.subscription_expires_at <= ?
                """,
                (now_iso,),
            ).fetchall()

    def get_users_for_notification(self, kind: str) -> list[sqlite3.Row]:
        now = self._now_dt()
        with self.connect() as conn:
            if kind == "3d":
                from_dt = (now + timedelta(days=2)).isoformat()
                to_dt = (now + timedelta(days=3)).isoformat()
                return conn.execute(
                    """
                    SELECT u.*, pl.title AS plan_title
                    FROM users u
                    LEFT JOIN plans pl ON pl.id = u.current_plan_id
                    WHERE u.subscription_status = 'active'
                      AND u.subscription_expires_at > ?
                      AND u.subscription_expires_at <= ?
                      AND u.notified_3d_at IS NULL
                    """,
                    (from_dt, to_dt),
                ).fetchall()
            if kind == "1d":
                from_dt = now.isoformat()
                to_dt = (now + timedelta(days=1)).isoformat()
                return conn.execute(
                    """
                    SELECT u.*, pl.title AS plan_title
                    FROM users u
                    LEFT JOIN plans pl ON pl.id = u.current_plan_id
                    WHERE u.subscription_status = 'active'
                      AND u.subscription_expires_at > ?
                      AND u.subscription_expires_at <= ?
                      AND u.notified_1d_at IS NULL
                    """,
                    (from_dt, to_dt),
                ).fetchall()
            if kind == "day":
                from_dt = (now - timedelta(hours=12)).isoformat()
                to_dt = (now + timedelta(hours=12)).isoformat()
                return conn.execute(
                    """
                    SELECT u.*, pl.title AS plan_title
                    FROM users u
                    LEFT JOIN plans pl ON pl.id = u.current_plan_id
                    WHERE u.subscription_status = 'active'
                      AND u.subscription_expires_at >= ?
                      AND u.subscription_expires_at <= ?
                      AND u.notified_day_at IS NULL
                    """,
                    (from_dt, to_dt),
                ).fetchall()
            if kind == "expired":
                return conn.execute(
                    """
                    SELECT u.*, pl.title AS plan_title
                    FROM users u
                    LEFT JOIN plans pl ON pl.id = u.current_plan_id
                    WHERE u.subscription_status = 'expired'
                      AND u.notified_expired_at IS NULL
                    """,
                ).fetchall()
        return []

    def mark_notification_sent(self, user_id: int, kind: str) -> None:
        field_map = {
            "3d": "notified_3d_at",
            "1d": "notified_1d_at",
            "day": "notified_day_at",
            "expired": "notified_expired_at",
        }
        field = field_map[kind]
        with self.connect() as conn:
            conn.execute(
                f"UPDATE users SET {field} = ?, updated_at = ? WHERE user_id = ?",
                (self._now_iso(), self._now_iso(), user_id),
            )

    @staticmethod
    def _parse_dt(value: str | None) -> datetime | None:
        if not value:
            return None
        return datetime.fromisoformat(value)

    @staticmethod
    def _row_to_plan(row: sqlite3.Row) -> Plan:
        return Plan(
            id=int(row["id"]),
            code=str(row["code"]),
            title=str(row["title"]),
            price_rub=int(row["price_rub"]),
            duration_days=int(row["duration_days"]),
            description=str(row["description"]),
            is_active=bool(row["is_active"]),
        )

    @staticmethod
    def _now_dt() -> datetime:
        return datetime.now(timezone.utc)

    @classmethod
    def _now_iso(cls) -> str:
        return cls._now_dt().isoformat()
