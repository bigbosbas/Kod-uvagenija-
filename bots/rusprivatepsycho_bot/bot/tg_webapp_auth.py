from __future__ import annotations

import hashlib
import hmac
import json
import time
from typing import Any
from urllib.parse import parse_qsl


def parse_init_data(init_data: str, bot_token: str, *, max_age_sec: int = 86400) -> dict[str, Any] | None:
    if not init_data or not bot_token:
        return None
    params = dict(parse_qsl(init_data, keep_blank_values=True))
    received = params.pop("hash", None)
    if not received:
        return None
    data_check_string = "\n".join(f"{k}={v}" for k, v in sorted(params.items()))
    secret_key = hmac.new(b"WebAppData", bot_token.encode("utf-8"), hashlib.sha256).digest()
    expected = hmac.new(secret_key, data_check_string.encode("utf-8"), hashlib.sha256).hexdigest()
    if expected != received:
        return None
    try:
        auth_date = int(params.get("auth_date", "0"))
    except ValueError:
        return None
    if auth_date and (time.time() - auth_date) > max_age_sec:
        return None
    raw_user = params.get("user")
    if not raw_user:
        return None
    try:
        user = json.loads(raw_user)
    except json.JSONDecodeError:
        return None
    uid = user.get("id")
    if uid is None:
        return None
    return {"user": user, "user_id": int(uid), "auth_date": auth_date}
