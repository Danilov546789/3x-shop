"""
Общая логика выдачи/продления подписки после оплаты, из админки и с сайта (веб-магазин
на корне домена, без Telegram — см. WebSubscription/webapp/api/shop.py).

Поддержка нескольких панелей 3x-ui: клиент (один и тот же email/uuid/subId)
создаётся сразу на всех активных панелях (core.database.Panel). У одной из
панелей стоит is_primary=True — именно её ссылка-подписка (/sub/<subId>)
выдаётся пользователю. Чтобы в неё попали конфиги и с остальных панелей,
на клиенте главной панели прописываются внешние подписки (external links,
kind=subscription) со ссылками /sub/<subId> каждой из остальных панелей —
встроенный Subscription-сервис 3x-ui сам подтянет и объединит их. Это тот
же механизм, что и вкладка "Ссылки" -> "Добавить внешнюю подписку" в панели.
"""
from __future__ import annotations

import datetime as dt
import logging
import uuid as uuid_lib

from sqlalchemy import select

from core.config import settings
from core.database import Panel, Payment, Plan, Subscription, User, WebSubscription, async_session
from core.xui_client import ExternalSubscription, XUIClient

logger = logging.getLogger(__name__)


async def get_or_create_user(user_id: int, username: str | None, first_name: str | None,
                              referrer_id: int | None = None) -> None:
    async with async_session() as session:
        user = await session.get(User, user_id)
        if user is None:
            session.add(User(id=user_id, username=username, first_name=first_name, referrer_id=referrer_id))
            await session.commit()


async def get_active_panels() -> list[Panel]:
    async with async_session() as session:
        result = await session.execute(
            select(Panel).where(Panel.is_active == True).order_by(Panel.is_primary.desc(), Panel.id)  # noqa: E712
        )
        return list(result.scalars().all())


def _pick_primary(panels: list[Panel]) -> Panel:
    return next((p for p in panels if p.is_primary), panels[0])


async def get_primary_panel() -> Panel | None:
    panels = await get_active_panels()
    return _pick_primary(panels) if panels else None


def build_sub_url(sub: Subscription | WebSubscription, primary_panel: Panel) -> str:
    return f"{primary_panel.sub_base_url.rstrip('/')}/{sub.xui_sub_id}"


async def _sync_external_links_on_primary(primary: Panel, other_panels: list[Panel],
                                           email: str, sub_id: str) -> None:
    links = [
        ExternalSubscription(url=f"{p.sub_base_url.rstrip('/')}/{sub_id}", name_prefix=f"{p.name} ")
        for p in other_panels
        if p.sub_base_url
    ]
    links += [
        ExternalSubscription(url=s["url"], name_prefix=s.get("name_prefix", ""))
        for s in settings.xui_external_subscriptions
    ]
    if not links:
        return
    async with XUIClient(primary.base_url, primary.api_token) as xc:
        await xc.set_external_links(email, links)


async def _create_client_everywhere(email: str, expiry_ms: int, total_gb: int,
                                     panels: list[Panel]) -> tuple[str, str]:
    """Создаёт клиента с одним и тем же uuid/subId на всех переданных панелях, подмешивает
    внешние подписки на главной. Возвращает (client_uuid, sub_id)."""
    primary = _pick_primary(panels)
    other_panels = [p for p in panels if p.id != primary.id]

    client_uuid = str(uuid_lib.uuid4())
    sub_id = uuid_lib.uuid4().hex[:16]

    for panel in panels:
        async with XUIClient(panel.base_url, panel.api_token) as xc:
            await xc.add_client(
                email=email,
                expiry_time_ms=expiry_ms,
                total_gb=total_gb,
                inbound_ids=panel.inbound_ids_list,
                client_uuid=client_uuid,
                sub_id=sub_id,
            )

    await _sync_external_links_on_primary(primary, other_panels, email, sub_id)
    return client_uuid, sub_id


async def _renew_client_everywhere(xui_uuid: str, xui_email: str, xui_sub_id: str,
                                    expiry_ms: int, total_gb: int, panels: list[Panel],
                                    enable: bool = True) -> None:
    """Обновляет уже существующего клиента на всех переданных панелях. Недоступность/отсутствие
    клиента на отдельной панели не прерывает операцию на остальных (ошибка логируется)."""
    for panel in panels:
        try:
            async with XUIClient(panel.base_url, panel.api_token) as xc:
                await xc.update_client(
                    client_uuid=xui_uuid,
                    email=xui_email,
                    expiry_time_ms=expiry_ms,
                    total_gb=total_gb,
                    sub_id=xui_sub_id,
                    enable=enable,
                )
        except Exception as e:  # noqa: BLE001
            logger.error("update_client failed on panel %s: %s", panel.name, e)


# ---------------------------------------------------------------------------
# Telegram-подписки (core.database.Subscription, ключ — telegram user_id)
# ---------------------------------------------------------------------------


async def provision_subscription(user_id: int, plan_id: int, payment_provider: str,
                                  provider_payment_id: str, amount: float, currency: str) -> Subscription:
    """Создаёт (или продлевает) подписку и синхронизирует её со ВСЕМИ активными панелями 3x-ui."""
    panels = await get_active_panels()
    if not panels:
        raise ValueError("Нет ни одной активной панели 3x-ui — добавьте её в /admin -> Серверы")

    async with async_session() as session:
        plan = await session.get(Plan, plan_id)
        if plan is None:
            raise ValueError(f"Plan {plan_id} not found")

        existing = await session.execute(
            select(Subscription).where(Subscription.user_id == user_id, Subscription.is_active == True)  # noqa: E712
        )
        sub = existing.scalars().first()

        now = dt.datetime.utcnow()
        if sub and sub.expires_at > now:
            new_expiry = sub.expires_at + dt.timedelta(days=plan.duration_days)
        else:
            new_expiry = now + dt.timedelta(days=plan.duration_days)
        expiry_ms = int(new_expiry.timestamp() * 1000)

        if sub:
            await _renew_client_everywhere(
                sub.xui_uuid, sub.xui_email, sub.xui_sub_id, expiry_ms, plan.data_limit_gb, panels
            )
            sub.expires_at = new_expiry
            sub.plan_id = plan.id
            sub.data_limit_gb = plan.data_limit_gb
            sub.is_active = True
            sub.notified_thresholds = ""
            sub.notified_expired = False
        else:
            email = f"user{user_id}-{int(now.timestamp())}"
            client_uuid, client_sub_id = await _create_client_everywhere(
                email, expiry_ms, plan.data_limit_gb, panels
            )
            sub = Subscription(
                user_id=user_id,
                plan_id=plan.id,
                xui_email=email,
                xui_uuid=client_uuid,
                xui_sub_id=client_sub_id,
                data_limit_gb=plan.data_limit_gb,
                expires_at=new_expiry,
                is_active=True,
            )
            session.add(sub)

        session.add(
            Payment(
                user_id=user_id,
                plan_id=plan_id,
                amount=amount,
                currency=currency,
                provider=payment_provider,
                provider_payment_id=provider_payment_id,
                status="paid",
            )
        )
        await session.commit()
        await session.refresh(sub)
        return sub


async def admin_extend_subscription(subscription_id: int, days: int) -> Subscription:
    """Продлевает подписку вручную из админки (без привязки к оплате), на всех панелях."""
    panels = await get_active_panels()

    async with async_session() as session:
        sub = await session.get(Subscription, subscription_id)
        if sub is None:
            raise ValueError(f"Subscription {subscription_id} not found")

        now = dt.datetime.utcnow()
        base = sub.expires_at if sub.expires_at > now else now
        new_expiry = base + dt.timedelta(days=days)
        expiry_ms = int(new_expiry.timestamp() * 1000)

        await _renew_client_everywhere(
            sub.xui_uuid, sub.xui_email, sub.xui_sub_id, expiry_ms, sub.data_limit_gb, panels, enable=True
        )

        sub.expires_at = new_expiry
        sub.is_active = True
        sub.notified_thresholds = ""
        sub.notified_expired = False
        await session.commit()
        await session.refresh(sub)
        return sub


async def admin_set_subscription_enabled(subscription_id: int, enabled: bool, mark_expired: bool = False) -> Subscription:
    """Включает/выключает клиента на всех панелях, не трогая дату окончания.
    mark_expired=True используется фоновой проверкой истечения (core/notifications.py),
    чтобы не слать повторно уведомление об истечении за одну и ту же подписку."""
    panels = await get_active_panels()

    async with async_session() as session:
        sub = await session.get(Subscription, subscription_id)
        if sub is None:
            raise ValueError(f"Subscription {subscription_id} not found")

        expiry_ms = int(sub.expires_at.timestamp() * 1000)
        await _renew_client_everywhere(
            sub.xui_uuid, sub.xui_email, sub.xui_sub_id, expiry_ms, sub.data_limit_gb, panels, enable=enabled
        )

        sub.is_active = enabled
        if mark_expired:
            sub.notified_expired = True
        await session.commit()
        await session.refresh(sub)
        return sub


async def grant_trial(user_id: int) -> Subscription:
    """Выдаёт бесплатный пробный период (TRIAL_DAYS) один раз на пользователя."""
    async with async_session() as session:
        user = await session.get(User, user_id)
        if user is None:
            raise ValueError("Сначала нужно хотя бы раз открыть бота (/start)")
        if user.trial_used:
            raise ValueError("Пробный период уже был использован")

        trial_plan = (
            await session.execute(select(Plan).where(Plan.is_trial == True))  # noqa: E712
        ).scalars().first()
        if trial_plan is None:
            raise ValueError("Пробный тариф не настроен")

        user.trial_used = True
        await session.commit()
        plan_id = trial_plan.id

    return await provision_subscription(
        user_id=user_id,
        plan_id=plan_id,
        payment_provider="trial",
        provider_payment_id="trial",
        amount=0,
        currency="TRIAL",
    )


async def admin_grant_subscription(user_id: int, plan_id: int, username: str | None = None,
                                    first_name: str | None = None) -> Subscription:
    """Ручная выдача/продление подписки из админки — без оплаты, по Telegram ID."""
    await get_or_create_user(user_id, username, first_name)
    return await provision_subscription(
        user_id=user_id,
        plan_id=plan_id,
        payment_provider="admin",
        provider_payment_id="manual",
        amount=0,
        currency="ADMIN",
    )


# ---------------------------------------------------------------------------
# Веб-подписки (core.database.WebSubscription, ключ — email, покупка на сайте без Telegram)
# ---------------------------------------------------------------------------


async def provision_web_subscription(email: str, plan_id: int) -> WebSubscription:
    """Аналог provision_subscription, но для покупателя без Telegram — идентификатор
    это email, а не user_id. Если у этого email уже есть активная веб-подписка — продлевает её,
    иначе создаёт новую (и новый набор клиентов на всех панелях)."""
    panels = await get_active_panels()
    if not panels:
        raise ValueError("Нет ни одной активной панели 3x-ui — добавьте её в /admin -> Серверы")

    async with async_session() as session:
        plan = await session.get(Plan, plan_id)
        if plan is None:
            raise ValueError(f"Plan {plan_id} not found")

        existing = await session.execute(
            select(WebSubscription).where(
                WebSubscription.email == email, WebSubscription.is_active == True  # noqa: E712
            )
        )
        sub = existing.scalars().first()

        now = dt.datetime.utcnow()
        if sub and sub.expires_at > now:
            new_expiry = sub.expires_at + dt.timedelta(days=plan.duration_days)
        else:
            new_expiry = now + dt.timedelta(days=plan.duration_days)
        expiry_ms = int(new_expiry.timestamp() * 1000)

        if sub:
            await _renew_client_everywhere(
                sub.xui_uuid, sub.xui_email, sub.xui_sub_id, expiry_ms, plan.data_limit_gb, panels
            )
            sub.expires_at = new_expiry
            sub.plan_id = plan.id
            sub.data_limit_gb = plan.data_limit_gb
            sub.is_active = True
        else:
            xui_email = f"web-{email}-{int(now.timestamp())}"
            client_uuid, client_sub_id = await _create_client_everywhere(
                xui_email, expiry_ms, plan.data_limit_gb, panels
            )
            sub = WebSubscription(
                email=email,
                plan_id=plan.id,
                xui_email=xui_email,
                xui_uuid=client_uuid,
                xui_sub_id=client_sub_id,
                data_limit_gb=plan.data_limit_gb,
                expires_at=new_expiry,
                is_active=True,
            )
            session.add(sub)

        await session.commit()
        await session.refresh(sub)
        return sub


async def admin_extend_web_subscription(subscription_id: int, days: int) -> WebSubscription:
    """Аналог admin_extend_subscription, но для веб-подписки (по email, без Telegram)."""
    panels = await get_active_panels()

    async with async_session() as session:
        sub = await session.get(WebSubscription, subscription_id)
        if sub is None:
            raise ValueError(f"WebSubscription {subscription_id} not found")

        now = dt.datetime.utcnow()
        base = sub.expires_at if sub.expires_at > now else now
        new_expiry = base + dt.timedelta(days=days)
        expiry_ms = int(new_expiry.timestamp() * 1000)

        await _renew_client_everywhere(
            sub.xui_uuid, sub.xui_email, sub.xui_sub_id, expiry_ms, sub.data_limit_gb, panels, enable=True
        )

        sub.expires_at = new_expiry
        sub.is_active = True
        await session.commit()
        await session.refresh(sub)
        return sub


async def admin_set_web_subscription_enabled(subscription_id: int, enabled: bool) -> WebSubscription:
    """Аналог admin_set_subscription_enabled, но для веб-подписки."""
    panels = await get_active_panels()

    async with async_session() as session:
        sub = await session.get(WebSubscription, subscription_id)
        if sub is None:
            raise ValueError(f"WebSubscription {subscription_id} not found")

        expiry_ms = int(sub.expires_at.timestamp() * 1000)
        await _renew_client_everywhere(
            sub.xui_uuid, sub.xui_email, sub.xui_sub_id, expiry_ms, sub.data_limit_gb, panels, enable=enabled
        )

        sub.is_active = enabled
        await session.commit()
        await session.refresh(sub)
        return sub
