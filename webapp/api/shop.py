from __future__ import annotations

import logging
import re

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from sqlalchemy import select

from core import payments_yookassa
from core.config import settings
from core.database import Payment, Plan, WebSubscription, async_session
from core.provisioning import build_sub_url, get_primary_panel

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/shop/api")

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


@router.get("/config")
async def shop_config():
    return {"title": settings.SHOP_TITLE, "bot_url": settings.SHOP_BOT_URL}


@router.get("/plans")
async def shop_plans():
    """Только тарифы с ценой в рублях — оплата на сайте картой через ЮKassa (без Telegram Stars)."""
    async with async_session() as session:
        result = await session.execute(
            select(Plan).where(Plan.is_active == True, Plan.is_trial == False, Plan.price_rub > 0)  # noqa: E712
        )
        plans = result.scalars().all()
        return [
            {
                "id": p.id,
                "title": p.title,
                "description": p.description,
                "duration_days": p.duration_days,
                "data_limit_gb": p.data_limit_gb,
                "price_rub": p.price_rub,
            }
            for p in plans
        ]


class ShopOrderRequest(BaseModel):
    email: str
    plan_id: int


@router.post("/order")
async def shop_create_order(body: ShopOrderRequest):
    if not settings.yookassa_enabled:
        raise HTTPException(status_code=400, detail="Оплата картой сейчас недоступна")
    email = body.email.strip().lower()
    if not _EMAIL_RE.match(email):
        raise HTTPException(status_code=400, detail="Некорректный email")

    async with async_session() as session:
        plan = await session.get(Plan, body.plan_id)
        if plan is None or not plan.is_active or not plan.price_rub:
            raise HTTPException(status_code=404, detail="Тариф не найден")

        payment = Payment(
            user_id=None,
            email=email,
            plan_id=plan.id,
            amount=plan.price_rub,
            currency="RUB",
            provider="yookassa",
            provider_payment_id="",
            status="pending",
        )
        session.add(payment)
        await session.commit()
        await session.refresh(payment)
        order_id = payment.id

    return_url = f"{settings.WEBAPP_URL.rstrip('/')}/success.html?order_id={order_id}"

    try:
        yk_payment = await payments_yookassa.create_payment(
            amount_rub=plan.price_rub,
            description=f"VPN — {plan.title}",
            metadata={"kind": "web", "email": email, "plan_id": str(plan.id), "order_id": str(order_id)},
            return_url=return_url,
        )
    except payments_yookassa.YooKassaError as e:
        logger.error("shop_create_order: yookassa error: %s", e)
        raise HTTPException(status_code=502, detail="Платёжный сервис временно недоступен")

    async with async_session() as session:
        payment = await session.get(Payment, order_id)
        if payment is not None:
            payment.provider_payment_id = yk_payment["id"]
            await session.commit()

    return {"order_id": order_id, "redirect_url": yk_payment["confirmation"]["confirmation_url"]}


@router.get("/order/{order_id}")
async def shop_order_status(order_id: int):
    """Опрашивается страницей success.html, пока платёж не подтвердится вебхуком."""
    async with async_session() as session:
        payment = await session.get(Payment, order_id)
        if payment is None:
            raise HTTPException(status_code=404, detail="order not found")

        result = {"status": payment.status}
        if payment.status == "paid" and payment.web_subscription_id:
            sub = await session.get(WebSubscription, payment.web_subscription_id)
            if sub is not None:
                primary = await get_primary_panel()
                sub_url = build_sub_url(sub, primary) if primary else ""
                result.update(
                    {
                        "expires_at": sub.expires_at.isoformat(),
                        "data_limit_gb": sub.data_limit_gb,
                        "sub_url": sub_url,
                    }
                )
        return result
