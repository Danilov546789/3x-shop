from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware

from core.config import settings
from core.database import init_models
from webapp.api.admin import router as admin_router
from webapp.api.routes import router as api_router
from webapp.api.shop import router as shop_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_models()
    yield


app = FastAPI(title="VPN Shop", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)
# Cookie-сессии для веб-админки (/admin). Обязательно смените SECRET_KEY в .env на проде.
app.add_middleware(SessionMiddleware, secret_key=settings.SECRET_KEY, session_cookie="vpnshop_admin")

# Порядок важен: сначала JSON-роутеры, потом статика (иначе static-mount на "/"
# перехватит запросы раньше, чем до них дойдёт роутер), а среди статик — сначала более
# специфичные пути ("/admin", "/tgapp"), и только в конце общий "/" (лендинг-магазин).
app.include_router(api_router)         # /api/*        — Mini App (Telegram)
app.include_router(admin_router)       # /admin/api/*  — веб-админка
app.include_router(shop_router)        # /shop/api/*   — публичный веб-магазин (без Telegram)

app.mount("/admin", StaticFiles(directory="webapp/static/admin", html=True), name="admin_static")
app.mount("/tgapp", StaticFiles(directory="webapp/static/miniapp", html=True), name="miniapp_static")
app.mount("/", StaticFiles(directory="webapp/static/shop", html=True), name="shop_static")


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("webapp.main:app", host=settings.WEBAPP_HOST, port=settings.WEBAPP_PORT, reload=True)
