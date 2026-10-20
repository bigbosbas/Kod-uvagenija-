from __future__ import annotations

import hashlib
import json
from decimal import Decimal, ROUND_HALF_UP
from urllib.parse import urlencode

from bot.config import Settings


ROBOKASSA_PAYMENT_URL = "https://auth.robokassa.ru/Merchant/Index.aspx"


def _build_hash(algorithm: str, payload: str) -> str:
    normalized = algorithm.strip().lower().replace("-", "")
    aliases = {
        "md5": "md5",
        "ripemd160": "ripemd160",
        "sha1": "sha1",
        "hs1": "sha1",
        "sha256": "sha256",
        "hs256": "sha256",
        "sha384": "sha384",
        "hs384": "sha384",
        "sha512": "sha512",
        "hs512": "sha512",
    }
    digest_name = aliases.get(normalized)
    if digest_name is None:
        raise ValueError(f"Unsupported Robokassa hash algorithm: {algorithm}")
    return hashlib.new(digest_name, payload.encode("utf-8")).hexdigest()


def format_out_sum(amount_rub: int | float | Decimal) -> str:
    decimal_amount = Decimal(str(amount_rub)).quantize(Decimal("0.00"), rounding=ROUND_HALF_UP)
    return format(decimal_amount, "f")


def calculate_payment_signature(
    *,
    merchant_login: str,
    out_sum: str,
    invoice_id: int,
    password1: str,
    algorithm: str,
) -> str:
    payload = f"{merchant_login}:{out_sum}:{invoice_id}:{password1}"
    return _build_hash(algorithm, payload)


def calculate_result_signature(
    *,
    out_sum: str,
    invoice_id: int,
    password2: str,
    algorithm: str,
) -> str:
    payload = f"{out_sum}:{invoice_id}:{password2}"
    return _build_hash(algorithm, payload)


def build_receipt(out_sum: str, name: str) -> str:
    # Магазин «Privatebot» общий с лендингами (ИП на НПД, «Робочеки СМЗ»):
    # без номенклатуры чек не формируется, для СМЗ хватает tax "none".
    amount = Decimal(out_sum)
    total = int(amount) if amount == amount.to_integral_value() else float(amount)
    return json.dumps(
        {"items": [{"name": name[:128], "quantity": 1, "sum": total, "tax": "none"}]},
        ensure_ascii=False,
        separators=(",", ":"),
    )


def build_payment_url(
    *,
    settings: Settings,
    invoice_id: int,
    amount_rub: int,
    description: str,
) -> str:
    # Подпись: MerchantLogin:OutSum:InvId:Receipt:SuccessUrl2:GET:FailUrl2:GET:Пароль#1.
    # Receipt и URL входят в подпись сырыми, без url-кодирования (проверено на
    # лендингах, server/lib/robokassa.js). Обычный SuccessURL не перебивает
    # Success URL из настроек магазина (он ведёт на лендинг), поэтому возврат
    # в бота — только через SuccessUrl2/FailUrl2.
    out_sum = format_out_sum(amount_rub)
    receipt = build_receipt(out_sum, description)
    success_url2 = settings.robokassa_success_url or f"{settings.public_base_url}/robokassa/success"
    fail_url2 = settings.robokassa_fail_url or f"{settings.public_base_url}/robokassa/fail"
    signature = _build_hash(
        settings.robokassa_hash_algorithm,
        f"{settings.robokassa_merchant_login}:{out_sum}:{invoice_id}:{receipt}:"
        f"{success_url2}:GET:{fail_url2}:GET:{settings.robokassa_active_password1}",
    )
    params = {
        "MerchantLogin": settings.robokassa_merchant_login,
        "OutSum": out_sum,
        "InvId": str(invoice_id),
        "Description": description,
        "Receipt": receipt,
        "SignatureValue": signature,
        "Culture": "ru",
        "Encoding": "utf-8",
        "SuccessUrl2": success_url2,
        "SuccessUrl2Method": "GET",
        "FailUrl2": fail_url2,
        "FailUrl2Method": "GET",
    }
    if settings.robokassa_is_test:
        params["IsTest"] = "1"
    return f"{ROBOKASSA_PAYMENT_URL}?{urlencode(params)}"


def verify_result_signature(
    *,
    out_sum: str,
    invoice_id: int,
    signature_value: str,
    password2: str,
    algorithm: str,
) -> bool:
    expected = calculate_result_signature(
        out_sum=out_sum,
        invoice_id=invoice_id,
        password2=password2,
        algorithm=algorithm,
    )
    return expected.lower() == signature_value.strip().lower()
