from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv


@dataclass(slots=True)
class Settings:
    bot_token: str
    admin_ids: set[int]
    channel_id: str
    base_url: str
    offer_url: str
    policy_url: str
    db_path: Path
    webhook_host: str
    webhook_port: int
    public_base_url: str
    robokassa_merchant_login: str
    robokassa_password1: str
    robokassa_password2: str
    robokassa_test_password1: str
    robokassa_test_password2: str
    robokassa_hash_algorithm: str
    robokassa_is_test: bool
    robokassa_result_path: str
    robokassa_success_url: str
    robokassa_fail_url: str
    auto_expire: bool
    telegram_proxy: str

    @property
    def channel_ref(self) -> int | str:
        value = self.channel_id.strip()
        if value.lstrip("-").isdigit():
            return int(value)
        return value

    @property
    def robokassa_active_password1(self) -> str:
        if self.robokassa_is_test and self.robokassa_test_password1:
            return self.robokassa_test_password1
        return self.robokassa_password1

    @property
    def robokassa_active_password2(self) -> str:
        if self.robokassa_is_test and self.robokassa_test_password2:
            return self.robokassa_test_password2
        return self.robokassa_password2


def load_settings() -> Settings:
    root_dir = Path(__file__).resolve().parent.parent
    load_dotenv(root_dir.parent / ".env")

    bot_token = os.getenv("PRIVATE_BOT_TOKEN", "").strip()
    admin_ids_raw = os.getenv("PRIVATE_ADMIN_IDS", "")
    channel_id = os.getenv("PRIVATE_TELEGRAM_CHANNEL_ID", "").strip()
    base_url = os.getenv("PRIVATE_BASE_URL", "").strip() or "https://example.com"
    offer_url = os.getenv("PRIVATE_OFFER_URL", "").strip()
    policy_url = os.getenv("PRIVATE_POLICY_URL", "").strip()
    db_path = Path(os.getenv("PRIVATE_DB_PATH", "bot_data.sqlite3"))
    webhook_host = os.getenv("PRIVATE_WEBHOOK_HOST", "127.0.0.1").strip() or "127.0.0.1"
    webhook_port = int(os.getenv("PRIVATE_WEBHOOK_PORT", "8080"))
    public_base_url = os.getenv("PRIVATE_PUBLIC_BASE_URL", "").strip().rstrip("/")
    robokassa_merchant_login = os.getenv("ROBOKASSA_MERCHANT_LOGIN", "").strip()
    robokassa_password1 = os.getenv("ROBOKASSA_PASSWORD1", "").strip()
    robokassa_password2 = os.getenv("ROBOKASSA_PASSWORD2", "").strip()
    robokassa_test_password1 = os.getenv("ROBOKASSA_TEST_PASSWORD1", "").strip()
    robokassa_test_password2 = os.getenv("ROBOKASSA_TEST_PASSWORD2", "").strip()
    robokassa_hash_algorithm = os.getenv("ROBOKASSA_HASH_ALGORITHM", "md5").strip() or "md5"
    robokassa_is_test = os.getenv("ROBOKASSA_IS_TEST", "1").strip().lower() in {"1", "true", "yes", "on"}
    robokassa_result_path = os.getenv("PRIVATE_ROBOKASSA_RESULT_PATH", "/webhook/robokassa/result").strip() or "/webhook/robokassa/result"
    robokassa_success_url = os.getenv("PRIVATE_ROBOKASSA_SUCCESS_URL", "").strip()
    robokassa_fail_url = os.getenv("PRIVATE_ROBOKASSA_FAIL_URL", "").strip()
    # Автоудаление просроченных из канала. После переезда выключено, пока
    # заказчик не сверит оплаты с 13.09 (их подтверждения до бота не доходили,
    # и часть оплативших числится просроченными). Включается PRIVATE_AUTO_EXPIRE=1.
    auto_expire = os.getenv("PRIVATE_AUTO_EXPIRE", "0").strip().lower() in {"1", "true", "yes", "on"}
    # Telegram из России заблокирован — SOCKS5 за границей (socks5://user:pass@host:port).
    telegram_proxy = os.getenv("PRIVATE_TELEGRAM_PROXY", "").strip()

    if not bot_token:
        raise RuntimeError("PRIVATE_BOT_TOKEN is not configured")
    if not admin_ids_raw:
        raise RuntimeError("PRIVATE_ADMIN_IDS is not configured")
    if not channel_id:
        raise RuntimeError("PRIVATE_TELEGRAM_CHANNEL_ID is not configured")

    admin_ids = {
        int(item.strip())
        for item in admin_ids_raw.split(",")
        if item.strip() and int(item.strip()) > 0
    }
    if not admin_ids:
        raise RuntimeError("PRIVATE_ADMIN_IDS does not contain valid values")

    if not db_path.is_absolute():
        db_path = root_dir / db_path

    return Settings(
        bot_token=bot_token,
        admin_ids=admin_ids,
        channel_id=channel_id,
        base_url=base_url,
        offer_url=offer_url,
        policy_url=policy_url,
        db_path=db_path,
        webhook_host=webhook_host,
        webhook_port=webhook_port,
        public_base_url=public_base_url,
        robokassa_merchant_login=robokassa_merchant_login,
        robokassa_password1=robokassa_password1,
        robokassa_password2=robokassa_password2,
        robokassa_test_password1=robokassa_test_password1,
        robokassa_test_password2=robokassa_test_password2,
        robokassa_hash_algorithm=robokassa_hash_algorithm,
        robokassa_is_test=robokassa_is_test,
        robokassa_result_path=robokassa_result_path,
        robokassa_success_url=robokassa_success_url,
        robokassa_fail_url=robokassa_fail_url,
        auto_expire=auto_expire,
        telegram_proxy=telegram_proxy,
    )
