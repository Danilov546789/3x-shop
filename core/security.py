"""
Валидация Telegram.WebApp.initData по алгоритму из официальной документации:
https://core.telegram.org/bots/webapps#validating-data-received-via-the-mini-app
"""
from __future__ import annotations

import hashlib
import hmac
import json
from urllib.parse import parse_qsl

from core.config import settings


class InitDataError(ValueError):
    pass


def verify_init_data(init_data: str, max_age_seconds: int = 86400) -> dict:
    if not init_data:
        raise InitDataError("empty init_data")

    pairs = dict(parse_qsl(init_data, strict_parsing=True))
    received_hash = pairs.pop("hash", None)
    if not received_hash:
        raise InitDataError("hash missing")

    data_check_string = "\n".join(f"{k}={v}" for k, v in sorted(pairs.items()))

    secret_key = hmac.new(b"WebAppData", settings.BOT_TOKEN.encode(), hashlib.sha256).digest()
    calculated_hash = hmac.new(secret_key, data_check_string.encode(), hashlib.sha256).hexdigest()

    if not hmac.compare_digest(calculated_hash, received_hash):
        raise InitDataError("hash mismatch")

    auth_date = int(pairs.get("auth_date", "0"))
    import time

    if time.time() - auth_date > max_age_seconds:
        raise InitDataError("init_data expired")

    user = json.loads(pairs["user"]) if "user" in pairs else {}
    return user
