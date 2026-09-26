import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode

from bot.handlers import router
from core.config import settings
from core.database import init_models
from core.notifications import check_expiring_subscriptions

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


async def notifier_loop(bot: Bot) -> None:
    """Раз в NOTIFY_CHECK_INTERVAL_MINUTES проверяет подписки: шлёт напоминания об истечении
    и отключает клиентов, у которых срок уже вышел (см. core/notifications.py)."""
    interval = max(1, settings.NOTIFY_CHECK_INTERVAL_MINUTES) * 60
    while True:
        try:
            await check_expiring_subscriptions(bot)
        except Exception:  # noqa: BLE001
            logger.exception("notifier_loop: ошибка при проверке подписок")
        await asyncio.sleep(interval)


async def main() -> None:
    await init_models()

    bot = Bot(token=settings.BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    dp = Dispatcher()
    dp.include_router(router)

    await bot.delete_webhook(drop_pending_updates=True)
    asyncio.create_task(notifier_loop(bot))
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
