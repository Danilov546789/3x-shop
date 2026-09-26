from __future__ import annotations

import json

from aiogram import F, Router
from aiogram.filters import CommandStart
from aiogram.types import CallbackQuery, Message, PreCheckoutQuery
from sqlalchemy import select

from bot.keyboards import apps_kb, join_channel_kb, main_menu_kb
from core.channel_check import is_subscribed
from core.database import Subscription, async_session
from core.provisioning import (
    build_sub_url,
    get_or_create_user,
    get_primary_panel,
    grant_trial,
    provision_subscription,
)

router = Router()

APPS_TEXT = (
    "📱 Какое приложение скачать, чтобы подключить подписку:\n\n"
    "• <b>iOS / Android / macOS</b> — приложение <b>Happ</b> (Happ - Proxy Utility)\n"
    "• <b>Windows</b> — <b>v2rayN</b> (архив с GitHub)\n"
    "• <b>Linux</b> — тоже подойдёт <b>v2rayN</b> (страница релизов на GitHub)\n\n"
    "Скачай нужное приложение по кнопке ниже, затем вставь в него ссылку-подписку "
    "(её можно получить в разделе «Моя подписка» в боте или в мини-приложении)."
)


async def _send_main_menu(message: Message) -> None:
    await message.answer(
        "👋 Привет! Это магазин VPN-подписок.\n\n"
        "Нажми «Открыть магазин», чтобы выбрать тариф и оплатить его прямо в Telegram "
        "(Telegram Stars или картой). После оплаты пришлю ссылку-подписку для подключения.",
        reply_markup=main_menu_kb(),
    )


@router.message(CommandStart())
async def cmd_start(message: Message, bot) -> None:
    referrer_id = None
    parts = message.text.split(maxsplit=1)
    if len(parts) > 1 and parts[1].startswith("ref"):
        try:
            referrer_id = int(parts[1][3:])
        except ValueError:
            pass

    await get_or_create_user(
        user_id=message.from_user.id,
        username=message.from_user.username,
        first_name=message.from_user.first_name,
        referrer_id=referrer_id,
    )

    if not await is_subscribed(bot, message.from_user.id):
        await message.answer(
            "Чтобы пользоваться ботом, сначала подпишись на наш канал 👇",
            reply_markup=join_channel_kb(),
        )
        return

    await _send_main_menu(message)


@router.callback_query(F.data == "check_sub")
async def cb_check_sub(callback: CallbackQuery, bot) -> None:
    if await is_subscribed(bot, callback.from_user.id):
        await callback.answer("Спасибо за подписку!")
        await _send_main_menu(callback.message)
    else:
        await callback.answer("Похоже, подписки ещё нет. Проверь и попробуй снова.", show_alert=True)


@router.callback_query(F.data == "status")
async def cb_status(callback: CallbackQuery) -> None:
    async with async_session() as session:
        result = await session.execute(
            select(Subscription).where(
                Subscription.user_id == callback.from_user.id, Subscription.is_active == True  # noqa: E712
            )
        )
        sub = result.scalars().first()

    if not sub:
        await callback.message.answer("У тебя пока нет активной подписки. Открой магазин, чтобы её оформить.")
    else:
        primary = await get_primary_panel()
        sub_url = build_sub_url(sub, primary) if primary else "—"
        await callback.message.answer(
            f"📊 Подписка активна до <b>{sub.expires_at:%d.%m.%Y %H:%M}</b> UTC\n"
            f"Лимит трафика: {'безлимит' if sub.data_limit_gb == 0 else f'{sub.data_limit_gb} ГБ'}\n\n"
            f"🔗 Ссылка-подписка:\n<code>{sub_url}</code>\n\n"
            "Не знаешь, куда её вставить? Жми «📱 Какое приложение скачать» в главном меню.",
            parse_mode="HTML",
        )
    await callback.answer()


@router.callback_query(F.data == "apps")
async def cb_apps(callback: CallbackQuery) -> None:
    await callback.message.answer(APPS_TEXT, parse_mode="HTML", reply_markup=apps_kb())
    await callback.answer()


@router.callback_query(F.data == "trial")
async def cb_trial(callback: CallbackQuery, bot) -> None:
    if not await is_subscribed(bot, callback.from_user.id):
        await callback.answer("Сначала подпишись на канал", show_alert=True)
        await callback.message.answer("Подпишись на канал, чтобы продолжить 👇", reply_markup=join_channel_kb())
        return

    try:
        sub = await grant_trial(callback.from_user.id)
    except ValueError as e:
        await callback.answer(str(e), show_alert=True)
        return

    primary = await get_primary_panel()
    sub_url = build_sub_url(sub, primary) if primary else "—"
    await callback.message.answer(
        "🎁 Пробный период активирован!\n\n"
        f"Действует до: <b>{sub.expires_at:%d.%m.%Y %H:%M}</b> UTC\n\n"
        f"🔗 Ссылка-подписка:\n<code>{sub_url}</code>\n\n"
        "Не знаешь, куда её вставить? Жми «📱 Какое приложение скачать» в главном меню.",
        parse_mode="HTML",
    )
    await callback.answer()


@router.callback_query(F.data == "support")
async def cb_support(callback: CallbackQuery) -> None:
    await callback.message.answer("По всем вопросам пиши @your_support_username")
    await callback.answer()


@router.pre_checkout_query()
async def process_pre_checkout(pre_checkout_query: PreCheckoutQuery) -> None:
    # Здесь можно дополнительно проверить, что тариф всё ещё активен и т.п.
    await pre_checkout_query.answer(ok=True)


@router.message(F.successful_payment)
async def process_successful_payment(message: Message) -> None:
    payload = json.loads(message.successful_payment.invoice_payload)
    plan_id = payload["plan_id"]
    user_id = message.from_user.id

    sub = await provision_subscription(
        user_id=user_id,
        plan_id=plan_id,
        payment_provider="telegram_stars",
        provider_payment_id=message.successful_payment.telegram_payment_charge_id,
        amount=message.successful_payment.total_amount,
        currency=message.successful_payment.currency,
    )

    primary = await get_primary_panel()
    sub_url = build_sub_url(sub, primary) if primary else "—"
    await message.answer(
        "✅ Оплата получена, подписка активирована!\n\n"
        f"Действует до: <b>{sub.expires_at:%d.%m.%Y %H:%M}</b> UTC\n\n"
        f"🔗 Ссылка-подписка:\n<code>{sub_url}</code>\n\n"
        "Не знаешь, куда её вставить? Жми «📱 Какое приложение скачать» в главном меню "
        "(или открой раздел «Приложения» в мини-приложении).",
        parse_mode="HTML",
    )
