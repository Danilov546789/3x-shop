"""Проверка, что пользователь подписан на обязательный канал (REQUIRED_CHANNEL_ID).
Если переменная не задана — проверка отключена (всегда возвращает True)."""
from __future__ import annotations

import logging

from aiogram import Bot

from core.config import settings

logger = logging.getLogger(__name__)

_NOT_MEMBER_STATUSES = {"left", "kicked"}


async def is_subscribed(bot: Bot, user_id: int) -> bool:
    if not settings.required_channel_enabled:
        return True
    try:
        member = await bot.get_chat_member(chat_id=settings.REQUIRED_CHANNEL_ID, user_id=user_id)
        return member.status not in _NOT_MEMBER_STATUSES
    except Exception as e:  # noqa: BLE001
        # Например, бот не состоит в канале, или пользователь никогда не открывал с ним чат.
        # Не блокируем пользователя из-за технической ошибки проверки.
        logger.warning("channel subscription check failed for user %s: %s", user_id, e)
        return True
