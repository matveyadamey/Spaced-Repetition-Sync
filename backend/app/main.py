import asyncio
import logging
from contextlib import asynccontextmanager

from aiogram import Bot, Dispatcher
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.status import router as status_router
from app.api.sync import router as sync_router
from app.bot.handlers import router as bot_router
from app.config import settings

logging.basicConfig(
    level=getattr(logging, settings.log_level.upper(), logging.INFO),
    format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
)
logger = logging.getLogger(__name__)


async def run_bot() -> None:
    if not settings.bot_token:
        logger.error("BOT_TOKEN is not set; Telegram bot will not start")
        return

    bot = Bot(token=settings.bot_token)
    dp = Dispatcher()
    dp.include_router(bot_router)
    logger.info("Starting Telegram bot (long polling)")
    try:
        await dp.start_polling(bot)
    except Exception:
        logger.exception("Telegram bot error")
        raise
    finally:
        await bot.session.close()


@asynccontextmanager
async def lifespan(_app: FastAPI):
    bot_task: asyncio.Task | None = None
    should_start_bot = bool(settings.bot_token) and settings.environment.lower() != "test"
    if should_start_bot:
        bot_task = asyncio.create_task(run_bot())
    else:
        logger.info("Telegram bot not started (missing token or ENVIRONMENT=test)")
    try:
        yield
    finally:
        if bot_task is not None:
            bot_task.cancel()
            try:
                await bot_task
            except asyncio.CancelledError:
                pass


app = FastAPI(title="Spaced Repetition API", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(sync_router)
app.include_router(status_router)


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}
