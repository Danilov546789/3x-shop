from __future__ import annotations

import json
import logging

from aiogram import Bot
from aiogram.types import LabeledPrice
from fastapi import APIRouter, Header, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy import select

from core import payments_yookassa
from core.channel_check import is_subscribed
from core.config import settings
from core.database import Payment, Plan, Subscription, User, async_session
from core.provisioning import (
    build_sub_url,
    get_or_create_user,
    get_primary_panel,
    grant_trial,
    provision_subscription,
)
from core.security import InitDataError, verify_init_data

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api")
_bot = Bot(token=settings.BOT_TOKEN)


def _auth(x_telegram_init_data: str = Header(default="")) -> dict:
    try:
        return verify_init_data(x_telegram_init_data)
    except InitDataError as e:
        raise HTTPException(status_code=401, detail=f"invalid init data: {e}")


async def _require_channel_subscription(user_id: int) -> None:
    if not await is_subscribed(_bot, user_id):
        raise HTTPException(
            status_code=403,
            detail={"error": "not_subscribed", "channel_url": settings.REQUIRED_CHANNEL_URL},
        )


@router.get("/plans")
async def get_plans():
    async with async_session() as session:
        result = await session.execute(
            select(Plan).where(Plan.is_active == True, Plan.is_trial == False)  # noqa: E712
        )
        plans = result.scalars().all()
        return [
            {
                "id": p.id,
                "title": p.title,
                "description": p.description,
                "duration_days": p.duration_days,
                "data_limit_gb": p.data_limit_gb,
                "price_stars": p.price_stars,
                "price_rub": p.price_rub,
            }
            for p in plans
        ]


@router.get("/apps")
async def get_apps():
    """Список рекомендуемых приложений для использования подписки, по платформам."""
    return {
        "items": [
            {"platform": "iOS", "name": "Happ", "url": settings.APP_LINK_IOS},
            {"platform": "Android", "name": "Happ", "url": settings.APP_LINK_ANDROID},
            {"platform": "macOS", "name": "Happ", "url": settings.APP_LINK_MACOS},
            {"platform": "Windows", "name": "v2rayN", "url": settings.APP_LINK_WINDOWS},
            {"platform": "Linux", "name": "v2rayN", "url": settings.APP_LINK_LINUX},
        ]
    }


@router.get("/required-channel")
async def get_required_channel():
    return {"enabled": settings.required_channel_enabled, "url": settings.REQUIRED_CHANNEL_URL}


@router.get("/gate")
async def gate_check(x_telegram_init_data: str = Header(default="")):
    """Проверка обязательной подписки на канал для экрана-заглушки в Mini App."""
    user = _auth(x_telegram_init_data)
    user_id = user["id"]
    await get_or_create_user(user_id, user.get("username"), user.get("first_name"))
    if not settings.required_channel_enabled:
        return {"subscribed": True}
    subscribed = await is_subscribed(_bot, user_id)
    return {"subscribed": subscribed, "channel_url": settings.REQUIRED_CHANNEL_URL}


@router.get("/payment-methods")
async def get_payment_methods():
    methods = [{"id": "telegram_stars", "title": "Telegram Stars", "icon": "⭐"}]
    if settings.yookassa_enabled:
        methods.append({"id": "yookassa", "title": "Банковская карта", "icon": "💳"})
    return {"methods": methods}


@router.get("/me")
async def get_me(x_telegram_init_data: str = Header(default="")):
    user = _auth(x_telegram_init_data)
    user_id = user["id"]
    await get_or_create_user(user_id, user.get("username"), user.get("first_name"))

    async with async_session() as session:
        result = await session.execute(
            select(Subscription).where(Subscription.user_id == user_id, Subscription.is_active == True)  # noqa: E712
        )
        sub = result.scalars().first()

        db_user = await session.get(User, user_id)
        trial_available = settings.TRIAL_ENABLED and db_user is not None and not db_user.trial_used

    if not sub:
        return {"has_subscription": False, "trial_available": trial_available}

    primary = await get_primary_panel()
    sub_url = build_sub_url(sub, primary) if primary else ""
    return {
        "has_subscription": True,
        "expires_at": sub.expires_at.isoformat(),
        "data_limit_gb": sub.data_limit_gb,
        "sub_url": sub_url,
        "trial_available": trial_available,
    }


class OrderRequest(BaseModel):
    plan_id: int
    provider: str = "telegram_stars"  # telegram_stars | yookassa


@router.post("/order")
async def create_order(body: OrderRequest, x_telegram_init_data: str = Header(default="")):
    user = _auth(x_telegram_init_data)
    user_id = user["id"]
    await get_or_create_user(user_id, user.get("username"), user.get("first_name"))
    await _require_channel_subscription(user_id)

    async with async_session() as session:
        plan = await session.get(Plan, body.plan_id)
        if plan is None or not plan.is_active:
            raise HTTPException(status_code=404, detail="plan not found")

    if body.provider == "telegram_stars":
        payload = json.dumps({"plan_id": plan.id, "user_id": user_id})
        invoice_link = await _bot.create_invoice_link(
            title=f"VPN — {plan.title}",
            description=plan.description or f"Подписка на {plan.duration_days} дней",
            payload=payload,
            currency="XTR",
            prices=[LabeledPrice(label=plan.title, amount=plan.price_stars)],
        )
        return {"type": "telegram_invoice", "invoice_link": invoice_link}

    elif body.provider == "yookassa":
        if not settings.yookassa_enabled:
            raise HTTPException(status_code=400, detail="yookassa is not configured")
        if not plan.price_rub or plan.price_rub <= 0:
            raise HTTPException(status_code=400, detail="plan has no RUB price set")

        yk_payment = await payments_yookassa.create_payment(
            amount_rub=plan.price_rub,
            description=f"VPN — {plan.title}",
            metadata={"kind": "telegram", "user_id": str(user_id), "plan_id": str(plan.id)},
        )

        async with async_session() as session:
            session.add(
                Payment(
                    user_id=user_id,
                    plan_id=plan.id,
                    amount=plan.price_rub,
                    currency="RUB",
                    provider="yookassa",
                    provider_payment_id=yk_payment["id"],
                    status="pending",
                )
            )
            await session.commit()

        return {"type": "redirect", "url": yk_payment["confirmation"]["confirmation_url"]}

    raise HTTPException(status_code=400, detail="unknown payment provider")


@router.post("/trial")
async def start_trial(x_telegram_init_data: str = Header(default="")):
    user = _auth(x_telegram_init_data)
    user_id = user["id"]
    await get_or_create_user(user_id, user.get("username"), user.get("first_name"))
    await _require_channel_subscription(user_id)

    try:
        sub = await grant_trial(user_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    primary = await get_primary_panel()
    sub_url = build_sub_url(sub, primary) if primary else ""
    return {"expires_at": sub.expires_at.isoformat(), "sub_url": sub_url}


@router.post("/yookassa/webhook")
async def yookassa_webhook(request: Request):
    """
    Уведомление от ЮKassa о смене статуса платежа.
    Телу вебхука не доверяем напрямую — сразу же сверяем статус платежа
    отдельным GET-запросом к API ЮKassa по его id, как рекомендует документация.
    """
    body = await request.json()
    payment_obj = body.get("object", {})
    payment_id = payment_obj.get("id")
    if not payment_id:
        raise HTTPException(status_code=400, detail="no payment id in payload")

    try:
        verified = await payments_yookassa.get_payment(payment_id)
    except payments_yookassa.YooKassaError as e:
        logger.error("yookassa verify failed: %s", e)
        raise HTTPException(status_code=502, detail="could not verify payment")

    status = verified.get("status")

    async with async_session() as session:
        result = await session.execute(select(Payment).where(Payment.provider_payment_id == payment_id))
        payment_row = result.scalars().first()
        if payment_row is None:
            logger.warning("yookassa webhook: unknown payment_id %s", payment_id)
            return {"ok": True}
        if payment_row.status == "paid":
            return {"ok": True}  # уже обработан, вебхук может дублироваться

        if status == "succeeded":
            payment_row.status = "paid"
            await session.commit()
        elif status in ("canceled",):
            payment_row.status = "failed"
            await session.commit()
            return {"ok": True}
        else:
            return {"ok": True}  # pending / waiting_for_capture — ждём следующего уведомления

    metadata = verified.get("metadata", {})
    kind = metadata.get("kind", "telegram")
    amount = float(verified["amount"]["value"])

    if kind == "web":
        from core.provisioning import provision_web_subscription  # локальный импорт — избегаем цикла

        email = metadata.get("email", payment_row.email)
        plan_id = int(metadata.get("plan_id", payment_row.plan_id))

        sub = await provision_web_subscription(email=email, plan_id=plan_id)

        async with async_session() as session:
            fresh_payment = await session.get(Payment, payment_row.id)
            if fresh_payment is not None:
                fresh_payment.web_subscription_id = sub.id
                await session.commit()

        return {"ok": True}

    # kind == "telegram" (в т.ч. старые платежи без поля kind — обратная совместимость)
    user_id = int(metadata.get("user_id", payment_row.user_id))
    plan_id = int(metadata.get("plan_id", payment_row.plan_id))

    sub = await provision_subscription(
        user_id=user_id,
        plan_id=plan_id,
        payment_provider="yookassa",
        provider_payment_id=payment_id,
        amount=amount,
        currency="RUB",
    )

    primary = await get_primary_panel()
    sub_url = build_sub_url(sub, primary) if primary else ""
    try:
        await _bot.send_message(
            user_id,
            "✅ Оплата картой получена, подписка активирована!\n\n"
            f"Действует до: <b>{sub.expires_at:%d.%m.%Y %H:%M}</b> UTC\n\n"
            f"🔗 Ссылка-подписка:\n<code>{sub_url}</code>",
            parse_mode="HTML",
        )
    except Exception as e:  # пользователь мог не открывать бота / заблокировать его
        logger.warning("failed to notify user %s: %s", user_id, e)

    return {"ok": True}
