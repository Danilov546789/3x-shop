from __future__ import annotations

import datetime as dt

from sqlalchemy import BigInteger, Boolean, ForeignKey, Integer, String, Float, DateTime
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

from core.config import settings


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)  # telegram user id
    username: Mapped[str | None] = mapped_column(String(64), nullable=True)
    first_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    referrer_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    trial_used: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=dt.datetime.utcnow)

    subscriptions: Mapped[list["Subscription"]] = relationship(back_populates="user")


class Plan(Base):
    __tablename__ = "plans"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    title: Mapped[str] = mapped_column(String(128))
    description: Mapped[str] = mapped_column(String(512), default="")
    duration_days: Mapped[int] = mapped_column(Integer)
    data_limit_gb: Mapped[int] = mapped_column(Integer, default=0)  # 0 = безлимит
    price_stars: Mapped[int] = mapped_column(Integer)  # цена в Telegram Stars (XTR)
    price_rub: Mapped[float] = mapped_column(Float, default=0)  # цена в рублях для ЮKassa
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    # Пробный тариф не показывается в обычном списке тарифов магазина — на него ведёт
    # отдельная кнопка "Попробовать бесплатно", и выдаётся он не более одного раза на пользователя
    is_trial: Mapped[bool] = mapped_column(Boolean, default=False)


class Panel(Base):
    """Одна управляемая панель 3x-ui (сервер). Клиент подписки создаётся на всех активных
    панелях сразу; у одной из них is_primary=True — её /sub-ссылка выдаётся пользователю,
    а подписки остальных панелей подмешиваются в неё как внешние (см. core/provisioning.py)."""

    __tablename__ = "panels"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(64))  # напр. "RU Baget", "AEZA"
    base_url: Mapped[str] = mapped_column(String(256))
    api_token: Mapped[str] = mapped_column(String(256))
    sub_base_url: Mapped[str] = mapped_column(String(256))
    inbound_ids: Mapped[str] = mapped_column(String(128), default="")  # "1,2,3"
    is_primary: Mapped[bool] = mapped_column(Boolean, default=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=dt.datetime.utcnow)

    @property
    def inbound_ids_list(self) -> list[int]:
        return [int(x) for x in self.inbound_ids.split(",") if x.strip()]


class Subscription(Base):
    __tablename__ = "subscriptions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id"))
    plan_id: Mapped[int] = mapped_column(Integer, ForeignKey("plans.id"))

    xui_email: Mapped[str] = mapped_column(String(128), unique=True)  # уникальный идентификатор клиента в 3x-ui
    xui_uuid: Mapped[str] = mapped_column(String(64))
    xui_sub_id: Mapped[str] = mapped_column(String(64))

    data_limit_gb: Mapped[int] = mapped_column(Integer, default=0)
    expires_at: Mapped[dt.datetime] = mapped_column(DateTime)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=dt.datetime.utcnow)

    # Уведомления об истечении: какие пороги (в днях, см. NOTIFY_DAYS_BEFORE) уже отправлены,
    # напр. "3,1"; сбрасываются в "" при каждом продлении. notified_expired — было ли отправлено
    # финальное уведомление "подписка истекла" (и клиент отключён на всех панелях).
    notified_thresholds: Mapped[str] = mapped_column(String(32), default="")
    notified_expired: Mapped[bool] = mapped_column(Boolean, default=False)

    user: Mapped["User"] = relationship(back_populates="subscriptions")


class WebSubscription(Base):
    """Подписка, купленная напрямую на сайте (корень домена), без привязки к Telegram —
    покупатель идентифицируется по email, а не по telegram user id. Устроена аналогично
    Subscription, но отдельно, т.к. Subscription жёстко привязана к таблице users (Telegram)."""

    __tablename__ = "web_subscriptions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    email: Mapped[str] = mapped_column(String(256), index=True)
    plan_id: Mapped[int] = mapped_column(Integer, ForeignKey("plans.id"))

    xui_email: Mapped[str] = mapped_column(String(128), unique=True)
    xui_uuid: Mapped[str] = mapped_column(String(64))
    xui_sub_id: Mapped[str] = mapped_column(String(64))

    data_limit_gb: Mapped[int] = mapped_column(Integer, default=0)
    expires_at: Mapped[dt.datetime] = mapped_column(DateTime)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=dt.datetime.utcnow)


class Payment(Base):
    __tablename__ = "payments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    # Ровно одно из двух: telegram-покупатель (user_id) либо веб-покупатель (email).
    user_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("users.id"), nullable=True)
    email: Mapped[str | None] = mapped_column(String(256), nullable=True)
    plan_id: Mapped[int] = mapped_column(Integer, ForeignKey("plans.id"))
    amount: Mapped[float] = mapped_column(Float)
    currency: Mapped[str] = mapped_column(String(8), default="XTR")
    provider: Mapped[str] = mapped_column(String(32), default="telegram_stars")
    provider_payment_id: Mapped[str] = mapped_column(String(128), default="")
    status: Mapped[str] = mapped_column(String(16), default="pending")  # pending|paid|failed
    # Заполняется после успешного проведения веб-заказа — так страница success.html может
    # найти готовую подписку по id этого платежа (см. webapp/api/shop.py)
    web_subscription_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("web_subscriptions.id"), nullable=True
    )
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=dt.datetime.utcnow)


engine = create_async_engine(settings.DATABASE_URL, echo=False)
async_session = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)


async def init_models() -> None:
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    from sqlalchemy import select

    async with async_session() as session:
        # Тарифы по умолчанию, если таблица пустая
        result = await session.execute(select(Plan))
        if not result.scalars().first():
            session.add_all(
                [
                    Plan(title="1 месяц", description="Безлимитный трафик", duration_days=30,
                         data_limit_gb=0, price_stars=150, price_rub=149),
                    Plan(title="3 месяца", description="Безлимитный трафик, скидка 15%", duration_days=90,
                         data_limit_gb=0, price_stars=380, price_rub=379),
                    Plan(title="12 месяцев", description="Безлимитный трафик, скидка 35%", duration_days=365,
                         data_limit_gb=0, price_stars=1170, price_rub=1290),
                ]
            )
            await session.commit()

        # Пробный тариф — отдельно, не входит в обычный список выше
        if settings.TRIAL_ENABLED:
            result = await session.execute(select(Plan).where(Plan.is_trial == True))  # noqa: E712
            if not result.scalars().first():
                session.add(
                    Plan(
                        title=f"Пробный период — {settings.TRIAL_DAYS} дн.",
                        description="Бесплатно, один раз на пользователя",
                        duration_days=settings.TRIAL_DAYS,
                        data_limit_gb=settings.TRIAL_DATA_LIMIT_GB,
                        price_stars=0,
                        price_rub=0,
                        is_active=True,
                        is_trial=True,
                    )
                )
                await session.commit()

        # Если ни одной панели ещё не заведено в БД — создаём одну из старых XUI_* переменных
        # окружения (обратная совместимость), чтобы проект продолжал работать "из коробки".
        # Дальше панели удобнее добавлять/редактировать через админку (/admin -> Серверы).
        result = await session.execute(select(Panel))
        if not result.scalars().first() and settings.XUI_BASE_URL and settings.XUI_API_TOKEN:
            session.add(
                Panel(
                    name="Основная панель",
                    base_url=settings.XUI_BASE_URL,
                    api_token=settings.XUI_API_TOKEN,
                    sub_base_url=settings.XUI_SUB_BASE_URL,
                    inbound_ids=settings.XUI_INBOUND_IDS,
                    is_primary=True,
                    is_active=True,
                )
            )
            await session.commit()
