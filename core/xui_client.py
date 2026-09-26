"""
Обёртка над клиенто-центричным REST API актуальных версий панели 3x-ui
(https://github.com/MHSanaei/3x-ui), эндпоинты живут под /panel/api/clients/*.

Авторизация — Bearer-токен (Settings -> Security -> API Token в панели),
без логина/пароля и без cookie-сессии.

В отличие от предыдущей версии, класс больше не хранит настройки одной
"глобальной" панели — он параметризуется base_url/api_token конкретной
панели (см. core.database.Panel) и создаётся на лету под каждую панель,
т.к. проект теперь поддерживает управление НЕСКОЛЬКИМИ панелями 3x-ui
одновременно (core/provisioning.py).

Используемые эндпоинты:
  POST /panel/api/clients/add                    -> создать клиента сразу в нескольких инбаундах
  POST /panel/api/clients/update/{email}          -> обновить клиента (продление и т.п.)
  POST /panel/api/clients/del/{email}             -> удалить клиента
  POST /panel/api/clients/{email}/attach          -> добавить существующего клиента в доп. инбаунды
  POST /panel/api/clients/{email}/detach          -> отвязать клиента от инбаундов
  POST /panel/api/clients/{email}/externalLinks   -> задать внешние ссылки/подписки клиента
                                                      (полная замена набора, как во вкладке "Ссылки")
  GET  /panel/api/clients/get/{email}             -> данные клиента + inboundIds
  GET  /panel/api/clients/traffic/{email}         -> счётчики трафика клиента
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field

import httpx

from core.config import settings


class XUIError(RuntimeError):
    pass


@dataclass
class ExternalSubscription:
    url: str
    name_prefix: str = ""
    enable: bool = True


@dataclass
class ClientInfo:
    uuid: str
    email: str
    sub_id: str
    sub_url: str
    inbound_ids: list[int] = field(default_factory=list)


class XUIClient:
    """Клиент для ОДНОЙ панели 3x-ui. Использовать как async context manager:

        async with XUIClient(panel.base_url, panel.api_token) as xc:
            await xc.add_client(...)
    """

    def __init__(self, base_url: str, api_token: str) -> None:
        self._base = base_url.rstrip("/")
        self._client = httpx.AsyncClient(
            base_url=self._base,
            verify=False,
            timeout=20,
            headers={"Authorization": f"Bearer {api_token}"},
        )

    async def __aenter__(self) -> "XUIClient":
        return self

    async def __aexit__(self, *exc) -> None:
        await self.close()

    async def close(self) -> None:
        await self._client.aclose()

    async def _request(self, method: str, path: str, **kwargs) -> dict:
        resp = await self._client.request(method, path, **kwargs)
        resp.raise_for_status()
        data = resp.json()
        if not data.get("success", True):
            raise XUIError(f"3x-ui error on {path}: {data}")
        return data

    async def set_external_links(self, email: str, subs: list[ExternalSubscription]) -> None:
        """Полностью заменяет набор внешних ссылок/подписок клиента (как во вкладке 'Ссылки').
        Если subs пуст — ничего не отправляем (не хотим случайно стереть то, что настроено
        вручную в панели, если вызывающий код не собирался этим управлять)."""
        if not subs:
            return
        payload = {
            "externalLinks": [
                {
                    "kind": "subscription",
                    "value": s.url,
                    "namePrefix": s.name_prefix,
                    "enable": s.enable,
                    "expiryTime": 0,
                }
                for s in subs
            ]
        }
        await self._request("POST", f"/panel/api/clients/{email}/externalLinks", json=payload)

    async def add_client(
        self,
        email: str,
        expiry_time_ms: int,
        total_gb: int = 0,
        limit_ip: int = 0,
        flow: str | None = None,
        inbound_ids: list[int] | None = None,
        client_uuid: str | None = None,
        sub_id: str | None = None,
    ) -> ClientInfo:
        """
        Создаёт нового клиента и сразу привязывает его к списку инбаундов этой панели.
        client_uuid/sub_id можно передать явно, чтобы один и тот же клиент имел одинаковый
        uuid/subId сразу на нескольких панелях (нужно для склейки подписок, см. provisioning.py).
        По умолчанию клиенту сразу включается Flow (XUI_CLIENT_FLOW, обычно xtls-rprx-vision).
        """
        client_uuid = client_uuid or str(uuid.uuid4())
        sub_id = sub_id or uuid.uuid4().hex[:16]
        flow = flow if flow is not None else settings.XUI_CLIENT_FLOW
        if not inbound_ids:
            raise XUIError("inbound_ids is empty — nowhere to create the client on this panel")

        client_obj = {
            "id": client_uuid,
            "email": email,
            "limitIp": limit_ip,
            "totalGB": total_gb * 1024 * 1024 * 1024,
            "expiryTime": expiry_time_ms,
            "enable": True,
            "subId": sub_id,
        }
        if flow:
            client_obj["flow"] = flow

        await self._request(
            "POST", "/panel/api/clients/add", json={"client": client_obj, "inboundIds": inbound_ids}
        )

        return ClientInfo(uuid=client_uuid, email=email, sub_id=sub_id, sub_url="", inbound_ids=inbound_ids)

    async def update_client(
        self,
        client_uuid: str,
        email: str,
        expiry_time_ms: int,
        total_gb: int = 0,
        sub_id: str = "",
        limit_ip: int = 0,
        enable: bool = True,
        flow: str | None = None,
    ) -> None:
        """Продление / изменение существующего клиента. inboundIds не трогаем — клиент остаётся
        привязан ко всем инбаундам, к которым был привязан при создании. Так как обновление
        полностью заменяет запись клиента, Flow передаём заново, иначе он слетит при продлении."""
        flow = flow if flow is not None else settings.XUI_CLIENT_FLOW
        payload = {
            "id": client_uuid,
            "email": email,
            "subId": sub_id,
            "limitIp": limit_ip,
            "totalGB": total_gb * 1024 * 1024 * 1024,
            "expiryTime": expiry_time_ms,
            "enable": enable,
        }
        if flow:
            payload["flow"] = flow
        await self._request("POST", f"/panel/api/clients/update/{email}", json=payload)

    async def attach_inbounds(self, email: str, inbound_ids: list[int]) -> None:
        """Добавить уже существующего клиента в дополнительные инбаунды этой же панели."""
        await self._request(
            "POST", f"/panel/api/clients/{email}/attach", json={"inboundIds": inbound_ids}
        )

    async def delete_client(self, email: str, keep_traffic: bool = False) -> None:
        await self._request(
            "POST", f"/panel/api/clients/del/{email}", params={"keepTraffic": int(keep_traffic)}
        )

    async def get_client(self, email: str) -> dict | None:
        data = await self._request("GET", f"/panel/api/clients/get/{email}")
        return data.get("obj")

    async def list_inbounds(self) -> list[dict]:
        """Лёгкий запрос, удобный в том числе для проверки токена/связи с панелью."""
        data = await self._request("GET", "/panel/api/inbounds/list")
        return data.get("obj", [])

    async def get_client_traffic(self, email: str) -> dict | None:
        data = await self._request("GET", f"/panel/api/clients/traffic/{email}")
        return data.get("obj")
