from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # Telegram
    BOT_TOKEN: str
    ADMIN_IDS: str = ""
    WEBAPP_URL: str
    WEBAPP_HOST: str = "0.0.0.0"
    WEBAPP_PORT: int = 8000

    # Веб-админка (отдельная от Mini App, доступна по /admin в браузере)
    ADMIN_USERNAME: str = "admin"
    ADMIN_PASSWORD: str = "change-me"
    # Секрет для подписи cookie сессии админки — сгенерируйте случайную строку
    # (например: python -c "import secrets; print(secrets.token_hex(32))")
    SECRET_KEY: str = "change-me-too-please"

    # 3x-ui: это НЕ обязательные настройки, а лишь "бутстрап" первой панели — при первом
    # запуске (если панелей ещё нет в БД) из них создаётся одна запись в таблице `panels`.
    # Дальше все панели (в том числе эта) редактируются через админку (/admin -> Серверы).
    # Поддерживается сразу несколько панелей 3x-ui (см. core/provisioning.py) — например,
    # входная панель в одной стране и несколько "выходных" в других.
    XUI_BASE_URL: str = ""
    XUI_API_TOKEN: str = ""
    # Список ID инбаундов (через запятую) на этой панели, в которые добавляется клиент
    XUI_INBOUND_IDS: str = "1"
    XUI_SUB_BASE_URL: str = ""
    # Дополнительные внешние ссылки/подписки, подмешиваемые в подписку КАЖДОГО клиента
    # на ГЛАВНОЙ (is_primary) панели, независимо от количества управляемых панелей
    # (см. вкладку "Ссылки" в "Изменить клиента" -> "Добавить внешнюю подписку").
    # Формат — JSON-массив объектов {"url": "...", "name_prefix": "..."}
    # Пример: [{"url":"https://raw.githubusercontent.com/.../vless-sub","name_prefix":"LTE "}]
    XUI_EXTERNAL_SUBSCRIPTIONS: str = "[]"
    # Flow, с которым создаётся/обновляется каждый клиент. Актуален для VLESS-инбаундов
    # с TCP+TLS/Reality; для инбаундов без поддержки Vision оставьте пустую строку.
    XUI_CLIENT_FLOW: str = "xtls-rprx-vision"

    # DB
    DATABASE_URL: str = "sqlite+aiosqlite:///./vpnshop.db"

    # Payments
    YOOKASSA_SHOP_ID: str = ""
    YOOKASSA_SECRET_KEY: str = ""
    # Куда возвращать пользователя из формы оплаты ЮKassa (страница-заглушка "вернитесь в Telegram")
    YOOKASSA_RETURN_URL: str = ""
    CRYPTOBOT_TOKEN: str = ""

    # ---- Уведомления об истечении подписки ----
    # За сколько дней до истечения слать напоминания (через запятую, по убыванию), напр. "3,1"
    NOTIFY_DAYS_BEFORE: str = "3,1"
    # Как часто (в минутах) фоновая задача в боте проверяет подписки
    NOTIFY_CHECK_INTERVAL_MINUTES: int = 60

    # ---- Пробный период ----
    TRIAL_ENABLED: bool = True
    TRIAL_DAYS: int = 1
    TRIAL_DATA_LIMIT_GB: int = 0  # 0 = безлимит

    # ---- Обязательная подписка на канал ----
    # ID или @username канала, на который бот проверяет подписку (бот должен быть добавлен
    # в канал хотя бы участником, лучше — админом). Оставьте пустым, чтобы отключить проверку.
    REQUIRED_CHANNEL_ID: str = ""
    # Ссылка-приглашение, которая показывается пользователю ("https://t.me/your_channel")
    REQUIRED_CHANNEL_URL: str = ""

    # ---- Рекомендуемые приложения для использования подписки ----
    APP_LINK_IOS: str = "https://www.happ.su/main/ru"
    APP_LINK_ANDROID: str = "https://www.happ.su/main/ru"
    APP_LINK_MACOS: str = "https://www.happ.su/main/ru"
    APP_LINK_WINDOWS: str = "https://github.com/2dust/v2rayN/releases/download/7.24.9/v2rayN-windows-64.zip"
    APP_LINK_LINUX: str = "https://github.com/2dust/v2rayN/releases"

    # ---- Веб-магазин на корне домена (покупка подписки без Telegram, картой через ЮKassa) ----
    SHOP_ENABLED: bool = True
    SHOP_TITLE: str = "VPN Shop"
    # Ссылка на Telegram-бота, показывается на сайте как альтернативный способ купить/управлять
    SHOP_BOT_URL: str = ""

    @property
    def admin_ids(self) -> list[int]:
        return [int(x) for x in self.ADMIN_IDS.split(",") if x.strip()]

    @property
    def notify_days_before(self) -> list[int]:
        return sorted({int(x) for x in self.NOTIFY_DAYS_BEFORE.split(",") if x.strip()}, reverse=True)

    @property
    def required_channel_enabled(self) -> bool:
        return bool(self.REQUIRED_CHANNEL_ID)

    @property
    def xui_inbound_ids(self) -> list[int]:
        return [int(x) for x in self.XUI_INBOUND_IDS.split(",") if x.strip()]

    @property
    def xui_external_subscriptions(self) -> list[dict]:
        import json

        try:
            data = json.loads(self.XUI_EXTERNAL_SUBSCRIPTIONS or "[]")
            return data if isinstance(data, list) else []
        except (json.JSONDecodeError, TypeError):
            return []

    @property
    def yookassa_enabled(self) -> bool:
        return bool(self.YOOKASSA_SHOP_ID and self.YOOKASSA_SECRET_KEY)

    @property
    def yookassa_return_url(self) -> str:
        return self.YOOKASSA_RETURN_URL or f"{self.WEBAPP_URL.rstrip('/')}/tgapp/payment-return.html"

    @property
    def miniapp_url(self) -> str:
        """URL Mini App, вынесенного на /tgapp (см. webapp/main.py)."""
        return f"{self.WEBAPP_URL.rstrip('/')}/tgapp"


settings = Settings()
