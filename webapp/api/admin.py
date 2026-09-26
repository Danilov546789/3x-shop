from __future__ import annotations

import datetime as dt
import hmac

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy import func, select

from core.config import settings
from core.database import Panel, Payment, Plan, Subscription, User, WebSubscription, async_session
from core.provisioning import (
    admin_extend_subscription,
    admin_extend_web_subscription,
    admin_grant_subscription,
    admin_set_subscription_enabled,
    admin_set_web_subscription_enabled,
)
from core.xui_client import XUIClient

router = APIRouter(prefix="/admin/api")


# ---------------------------------------------------------------------------
# Авторизация: простая cookie-сессия (Starlette SessionMiddleware, см. webapp/main.py).
# Для одного/нескольких админов сайта этого достаточно; если нужно много ролей/аккаунтов —
# стоит завести отдельную таблицу пользователей админки с хэшированными паролями.
# ---------------------------------------------------------------------------


class LoginRequest(BaseModel):
    username: str
    password: str


@router.post("/login")
async def login(body: LoginRequest, request: Request):
    ok_user = hmac.compare_digest(body.username, settings.ADMIN_USERNAME)
    ok_pass = hmac.compare_digest(body.password, settings.ADMIN_PASSWORD)
    if not (ok_user and ok_pass):
        raise HTTPException(status_code=401, detail="Неверный логин или пароль")
    request.session["admin"] = True
    return {"ok": True}


@router.post("/logout")
async def logout(request: Request):
    request.session.clear()
    return {"ok": True}


@router.get("/me")
async def me(request: Request):
    if not request.session.get("admin"):
        raise HTTPException(status_code=401, detail="not authenticated")
    return {"username": settings.ADMIN_USERNAME}


def require_admin(request: Request) -> None:
    if not request.session.get("admin"):
        raise HTTPException(status_code=401, detail="not authenticated")


# ---------------------------------------------------------------------------
# Дашборд
# ---------------------------------------------------------------------------


@router.get("/stats", dependencies=[Depends(require_admin)])
async def stats():
    async with async_session() as session:
        users_total = (await session.execute(select(func.count(User.id)))).scalar_one()

        now = dt.datetime.utcnow()
        active_subs = (
            await session.execute(
                select(func.count(Subscription.id)).where(
                    Subscription.is_active == True, Subscription.expires_at > now  # noqa: E712
                )
            )
        ).scalar_one()

        month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        revenue_rows = await session.execute(
            select(Payment.currency, func.sum(Payment.amount))
            .where(Payment.status == "paid", Payment.created_at >= month_start)
            .group_by(Payment.currency)
        )
        revenue_month = {currency: float(total) for currency, total in revenue_rows.all()}

        payments_total = (
            await session.execute(select(func.count(Payment.id)).where(Payment.status == "paid"))
        ).scalar_one()

        panels_total = (await session.execute(select(func.count(Panel.id)))).scalar_one()

        web_active_subs = (
            await session.execute(
                select(func.count(WebSubscription.id)).where(
                    WebSubscription.is_active == True, WebSubscription.expires_at > now  # noqa: E712
                )
            )
        ).scalar_one()

    return {
        "users_total": users_total,
        "active_subscriptions": active_subs,
        "web_active_subscriptions": web_active_subs,
        "revenue_month": revenue_month,
        "payments_total": payments_total,
        "panels_total": panels_total,
    }


# ---------------------------------------------------------------------------
# Тарифы
# ---------------------------------------------------------------------------


class PlanIn(BaseModel):
    title: str
    description: str = ""
    duration_days: int
    data_limit_gb: int = 0
    price_stars: int
    price_rub: float = 0
    is_active: bool = True


@router.get("/plans", dependencies=[Depends(require_admin)])
async def list_plans():
    async with async_session() as session:
        result = await session.execute(select(Plan).order_by(Plan.id))
        return [
            {
                "id": p.id,
                "title": p.title,
                "description": p.description,
                "duration_days": p.duration_days,
                "data_limit_gb": p.data_limit_gb,
                "price_stars": p.price_stars,
                "price_rub": p.price_rub,
                "is_active": p.is_active,
            }
            for p in result.scalars().all()
        ]


@router.post("/plans", dependencies=[Depends(require_admin)])
async def create_plan(body: PlanIn):
    async with async_session() as session:
        plan = Plan(**body.model_dump())
        session.add(plan)
        await session.commit()
        return {"ok": True, "id": plan.id}


@router.put("/plans/{plan_id}", dependencies=[Depends(require_admin)])
async def update_plan(plan_id: int, body: PlanIn):
    async with async_session() as session:
        plan = await session.get(Plan, plan_id)
        if plan is None:
            raise HTTPException(status_code=404, detail="plan not found")
        for k, v in body.model_dump().items():
            setattr(plan, k, v)
        await session.commit()
        return {"ok": True}


# ---------------------------------------------------------------------------
# Панели (серверы 3x-ui)
# ---------------------------------------------------------------------------


class PanelIn(BaseModel):
    name: str
    base_url: str
    api_token: str = ""  # пусто при обновлении = не менять текущий токен
    sub_base_url: str
    inbound_ids: str  # "1,2,3"
    is_primary: bool = False
    is_active: bool = True


@router.get("/panels", dependencies=[Depends(require_admin)])
async def list_panels():
    async with async_session() as session:
        result = await session.execute(select(Panel).order_by(Panel.id))
        return [
            {
                "id": p.id,
                "name": p.name,
                "base_url": p.base_url,
                "api_token_masked": (p.api_token[:4] + "…" + p.api_token[-4:]) if len(p.api_token) > 8 else "••••",
                "sub_base_url": p.sub_base_url,
                "inbound_ids": p.inbound_ids,
                "is_primary": p.is_primary,
                "is_active": p.is_active,
            }
            for p in result.scalars().all()
        ]


async def _unset_other_primary(session, except_id: int | None = None) -> None:
    result = await session.execute(select(Panel).where(Panel.is_primary == True))  # noqa: E712
    for p in result.scalars().all():
        if p.id != except_id:
            p.is_primary = False


@router.post("/panels", dependencies=[Depends(require_admin)])
async def create_panel(body: PanelIn):
    if not body.api_token:
        raise HTTPException(status_code=400, detail="api_token is required for a new panel")
    async with async_session() as session:
        panel = Panel(**body.model_dump())
        if panel.is_primary:
            await _unset_other_primary(session)
        session.add(panel)
        await session.commit()
        return {"ok": True, "id": panel.id}


@router.put("/panels/{panel_id}", dependencies=[Depends(require_admin)])
async def update_panel(panel_id: int, body: PanelIn):
    async with async_session() as session:
        panel = await session.get(Panel, panel_id)
        if panel is None:
            raise HTTPException(status_code=404, detail="panel not found")
        data = body.model_dump()
        if not data["api_token"]:
            data["api_token"] = panel.api_token  # пустое поле = не менять токен
        if data["is_primary"]:
            await _unset_other_primary(session, except_id=panel_id)
        for k, v in data.items():
            setattr(panel, k, v)
        await session.commit()
        return {"ok": True}


@router.delete("/panels/{panel_id}", dependencies=[Depends(require_admin)])
async def delete_panel(panel_id: int):
    async with async_session() as session:
        panel = await session.get(Panel, panel_id)
        if panel is None:
            raise HTTPException(status_code=404, detail="panel not found")
        await session.delete(panel)
        await session.commit()
        return {"ok": True}


@router.post("/panels/{panel_id}/test", dependencies=[Depends(require_admin)])
async def test_panel(panel_id: int):
    """Проверка связи с панелью — пробуем получить список инбаундов через её же клиента."""
    async with async_session() as session:
        panel = await session.get(Panel, panel_id)
        if panel is None:
            raise HTTPException(status_code=404, detail="panel not found")
    try:
        async with XUIClient(panel.base_url, panel.api_token) as xc:
            await xc.list_inbounds()
        return {"ok": True}
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": str(e)}


# ---------------------------------------------------------------------------
# Пользователи / подписки
# ---------------------------------------------------------------------------


@router.get("/users", dependencies=[Depends(require_admin)])
async def list_users(search: str = "", page: int = 1, page_size: int = 30):
    async with async_session() as session:
        query = select(User)
        if search:
            like = f"%{search}%"
            query = query.where((User.username.ilike(like)) | (User.first_name.ilike(like)))
        total = (await session.execute(select(func.count()).select_from(query.subquery()))).scalar_one()

        query = query.order_by(User.created_at.desc()).offset((page - 1) * page_size).limit(page_size)
        users = (await session.execute(query)).scalars().all()

        user_ids = [u.id for u in users]
        subs_by_user: dict[int, Subscription] = {}
        if user_ids:
            subs = (
                await session.execute(
                    select(Subscription).where(
                        Subscription.user_id.in_(user_ids), Subscription.is_active == True  # noqa: E712
                    )
                )
            ).scalars().all()
            subs_by_user = {s.user_id: s for s in subs}

        items = []
        for u in users:
            sub = subs_by_user.get(u.id)
            items.append(
                {
                    "id": u.id,
                    "username": u.username,
                    "first_name": u.first_name,
                    "created_at": u.created_at.isoformat(),
                    "subscription": (
                        {
                            "id": sub.id,
                            "expires_at": sub.expires_at.isoformat(),
                            "is_active": sub.is_active,
                            "data_limit_gb": sub.data_limit_gb,
                        }
                        if sub
                        else None
                    ),
                }
            )
        return {"items": items, "total": total, "page": page, "page_size": page_size}


@router.get("/users/{user_id}", dependencies=[Depends(require_admin)])
async def get_user(user_id: int):
    async with async_session() as session:
        user = await session.get(User, user_id)
        if user is None:
            raise HTTPException(status_code=404, detail="user not found")

        subs = (
            await session.execute(
                select(Subscription).where(Subscription.user_id == user_id).order_by(Subscription.id.desc())
            )
        ).scalars().all()
        payments = (
            await session.execute(
                select(Payment).where(Payment.user_id == user_id).order_by(Payment.id.desc())
            )
        ).scalars().all()

        return {
            "id": user.id,
            "username": user.username,
            "first_name": user.first_name,
            "created_at": user.created_at.isoformat(),
            "subscriptions": [
                {
                    "id": s.id,
                    "plan_id": s.plan_id,
                    "expires_at": s.expires_at.isoformat(),
                    "is_active": s.is_active,
                    "data_limit_gb": s.data_limit_gb,
                    "xui_email": s.xui_email,
                }
                for s in subs
            ],
            "payments": [
                {
                    "id": p.id,
                    "plan_id": p.plan_id,
                    "amount": p.amount,
                    "currency": p.currency,
                    "provider": p.provider,
                    "status": p.status,
                    "created_at": p.created_at.isoformat(),
                }
                for p in payments
            ],
        }


class GrantRequest(BaseModel):
    user_id: int
    plan_id: int
    username: str = ""
    first_name: str = ""


@router.post("/users/grant", dependencies=[Depends(require_admin)])
async def grant_subscription(body: GrantRequest):
    """Ручная выдача/продление подписки по Telegram ID — без оплаты. Если пользователя ещё
    нет в БД (никогда не запускал бота), запись о нём будет создана из переданных данных;
    учти, что бот сможет прислать ему сообщение только после того, как он хотя бы раз
    напишет боту (ограничение Bot API — по одному только ID написать первым нельзя)."""
    try:
        sub = await admin_grant_subscription(
            user_id=body.user_id,
            plan_id=body.plan_id,
            username=body.username or None,
            first_name=body.first_name or None,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"ok": True, "subscription_id": sub.id, "expires_at": sub.expires_at.isoformat()}


class ExtendRequest(BaseModel):
    days: int


@router.post("/subscriptions/{subscription_id}/extend", dependencies=[Depends(require_admin)])
async def extend_subscription(subscription_id: int, body: ExtendRequest):
    try:
        sub = await admin_extend_subscription(subscription_id, body.days)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    return {"ok": True, "expires_at": sub.expires_at.isoformat()}


class EnabledRequest(BaseModel):
    enabled: bool


@router.post("/subscriptions/{subscription_id}/set-enabled", dependencies=[Depends(require_admin)])
async def set_subscription_enabled(subscription_id: int, body: EnabledRequest):
    try:
        await admin_set_subscription_enabled(subscription_id, body.enabled)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    return {"ok": True}


# ---------------------------------------------------------------------------
# Платежи
# ---------------------------------------------------------------------------


@router.get("/payments", dependencies=[Depends(require_admin)])
async def list_payments(page: int = 1, page_size: int = 30, status_filter: str = ""):
    async with async_session() as session:
        query = select(Payment)
        if status_filter:
            query = query.where(Payment.status == status_filter)
        total = (await session.execute(select(func.count()).select_from(query.subquery()))).scalar_one()

        query = query.order_by(Payment.id.desc()).offset((page - 1) * page_size).limit(page_size)
        payments = (await session.execute(query)).scalars().all()

        return {
            "items": [
                {
                    "id": p.id,
                    "user_id": p.user_id,
                    "email": p.email,
                    "plan_id": p.plan_id,
                    "amount": p.amount,
                    "currency": p.currency,
                    "provider": p.provider,
                    "provider_payment_id": p.provider_payment_id,
                    "status": p.status,
                    "created_at": p.created_at.isoformat(),
                }
                for p in payments
            ],
            "total": total,
            "page": page,
            "page_size": page_size,
        }


# ---------------------------------------------------------------------------
# Веб-подписки (покупатели с сайта, без Telegram — идентификатор email)
# ---------------------------------------------------------------------------


@router.get("/web-subscriptions", dependencies=[Depends(require_admin)])
async def list_web_subscriptions(search: str = "", page: int = 1, page_size: int = 30):
    async with async_session() as session:
        query = select(WebSubscription)
        if search:
            query = query.where(WebSubscription.email.ilike(f"%{search}%"))
        total = (await session.execute(select(func.count()).select_from(query.subquery()))).scalar_one()

        query = query.order_by(WebSubscription.id.desc()).offset((page - 1) * page_size).limit(page_size)
        subs = (await session.execute(query)).scalars().all()

        return {
            "items": [
                {
                    "id": s.id,
                    "email": s.email,
                    "plan_id": s.plan_id,
                    "expires_at": s.expires_at.isoformat(),
                    "data_limit_gb": s.data_limit_gb,
                    "is_active": s.is_active,
                    "created_at": s.created_at.isoformat(),
                }
                for s in subs
            ],
            "total": total,
            "page": page,
            "page_size": page_size,
        }


@router.post("/web-subscriptions/{subscription_id}/extend", dependencies=[Depends(require_admin)])
async def extend_web_subscription(subscription_id: int, body: ExtendRequest):
    try:
        sub = await admin_extend_web_subscription(subscription_id, body.days)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    return {"ok": True, "expires_at": sub.expires_at.isoformat()}


@router.post("/web-subscriptions/{subscription_id}/set-enabled", dependencies=[Depends(require_admin)])
async def set_web_subscription_enabled(subscription_id: int, body: EnabledRequest):
    try:
        await admin_set_web_subscription_enabled(subscription_id, body.enabled)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    return {"ok": True}
