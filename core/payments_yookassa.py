"""
Минимальная обёртка над ЮKassa API (https://yookassa.ru/developers/api).

Используется схема "redirect" confirmation: пользователь уходит на страницу
оплаты ЮKassa в браузере (внутри Mini App это делается через
Telegram.WebApp.openLink), после оплаты ЮKassa стучится к нам вебхуком
(HTTP-уведомлением), а мы на всякий случай ещё раз сверяем статус платежа
прямым GET-запросом — тело вебхука доверять напрямую нельзя, так как
эндпоинт публичный и его адрес не секрет.

Документация по уведомлениям: https://yookassa.ru/developers/using-api/webhooks
"""
from __future__ import annotations

import uuid

import httpx

from core.config import settings

API_BASE = "https://api.yookassa.ru/v3"


class YooKassaError(RuntimeError):
    pass


def _auth() -> tuple[str, str]:
    return (settings.YOOKASSA_SHOP_ID, settings.YOOKASSA_SECRET_KEY)


async def create_payment(amount_rub: float, description: str, metadata: dict, return_url: str | None = None) -> dict:
    """Создаёт платёж, возвращает JSON-ответ ЮKassa (в т.ч. id и confirmation.confirmation_url).
    return_url переопределяет YOOKASSA_RETURN_URL — используется веб-магазином, чтобы вернуть
    покупателя на страницу конкретного заказа (см. webapp/api/shop.py)."""
    idempotence_key = str(uuid.uuid4())
    payload = {
        "amount": {"value": f"{amount_rub:.2f}", "currency": "RUB"},
        "capture": True,
        "confirmation": {
            "type": "redirect",
            "return_url": return_url or settings.yookassa_return_url,
        },
        "description": description,
        "metadata": metadata,
    }
    async with httpx.AsyncClient(timeout=20) as client:
        resp = await client.post(
            f"{API_BASE}/payments",
            json=payload,
            auth=_auth(),
            headers={"Idempotence-Key": idempotence_key},
        )
    if resp.status_code >= 400:
        raise YooKassaError(f"create_payment failed: {resp.status_code} {resp.text}")
    return resp.json()


async def get_payment(payment_id: str) -> dict:
    """Прямая сверка статуса платежа по его id (не доверяем телу вебхука вслепую)."""
    async with httpx.AsyncClient(timeout=20) as client:
        resp = await client.get(f"{API_BASE}/payments/{payment_id}", auth=_auth())
    if resp.status_code >= 400:
        raise YooKassaError(f"get_payment failed: {resp.status_code} {resp.text}")
    return resp.json()
