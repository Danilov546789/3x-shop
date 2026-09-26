"""
Периодическая проверка подписок: шлёт напоминания за N дней до истечения
(NOTIFY_DAYS_BEFORE) и, когда срок истёк, отключает клиента на всех панелях
и уведомляет пользователя. Запускается из bot/main.py фоновой задачей.
"""
from __future__ import annotations

import datetime as dt
import logging

from aiogram import Bot
from aiogram.exceptions import TelegramForbiddenError
from sqlalchemy import select

from core.config import settings
from core.database import Subscription, WebSubscription, async_session
from core.provisioning import admin_set_subscription_enabled, admin_set_web_subscription_enabled

logger = logging.getLogger(__name__)


def _plural_days(n: int) -> str:
    if n % 10 == 1 and n % 100 != 11:
        return "день"
    if 2 <= n % 10 <= 4 and not (12 <= n % 100 <= 14):
        return "дня"
    return "дней"


async def check_expiring_subscriptions(bot: Bot) -> None:
    await _check_telegram_subscriptions(bot)
    await _check_web_subscriptions()


async def _check_telegram_subscriptions(bot: Bot) -> None:
    now = dt.datetime.utcnow()
    thresholds = settings.notify_days_before  # напр. [3, 1], по убыванию

    async with async_session() as session:
        result = await session.execute(select(Subscription).where(Subscription.is_active == True))  # noqa: E712
        subs = list(result.scalars().all())

    for sub in subs:
        days_left = (sub.expires_at - now).total_seconds() / 86400

        if days_left <= 0:
            if not sub.notified_expired:
                try:
                    await admin_set_subscription_enabled(sub.id, False, mark_expired=True)
                except Exception as e:  # noqa: BLE001
                    logger.error("failed to disable expired subscription %s: %s", sub.id, e)
                    continue
                await _notify(
                    bot,
                    sub.user_id,
                    "❌ Твоя VPN-подписка истекла, доступ отключён.\n\n"
                    "Открой магазин в боте, чтобы продлить — это займёт меньше минуты.",
                )
            continue

        already = {int(x) for x in sub.notified_thresholds.split(",") if x}
        new_notifications = []
        for threshold in thresholds:
            if days_left <= threshold and threshold not in already:
                new_notifications.append(threshold)

        if not new_notifications:
            continue

        for threshold in new_notifications:
            word = _plural_days(threshold)
            await _notify(
                bot,
                sub.user_id,
                f"⏰ Твоя VPN-подписка истекает через {threshold} {word} "
                f"({sub.expires_at:%d.%m.%Y %H:%M} UTC).\n\n"
                "Продли её в магазине в боте, чтобы доступ не прервался.",
            )

        already.update(new_notifications)
        async with async_session() as session:
            fresh = await session.get(Subscription, sub.id)
            if fresh is not None:
                fresh.notified_thresholds = ",".join(str(x) for x in sorted(already))
                await session.commit()


async def _check_web_subscriptions() -> None:
    """Веб-покупателей (без Telegram) мы не можем уведомить напрямую (нет встроенной отправки
    email в этом проекте) — только автоматически отключаем клиента по истечении срока."""
    now = dt.datetime.utcnow()
    async with async_session() as session:
        result = await session.execute(select(WebSubscription).where(WebSubscription.is_active == True))  # noqa: E712
        subs = list(result.scalars().all())

    for sub in subs:
        if sub.expires_at <= now:
            try:
                await admin_set_web_subscription_enabled(sub.id, False)
            except Exception as e:  # noqa: BLE001
                logger.error("failed to disable expired web subscription %s: %s", sub.id, e)


async def _notify(bot: Bot, user_id: int, text: str) -> None:
    try:
        await bot.send_message(user_id, text)
    except TelegramForbiddenError:
        logger.info("user %s blocked the bot, skipping notification", user_id)
    except Exception as e:  # noqa: BLE001
        logger.warning("failed to notify user %s: %s", user_id, e)
