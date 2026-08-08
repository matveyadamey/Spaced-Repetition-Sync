import logging
from datetime import timedelta

from aiogram import Bot
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from sqlalchemy import extract, func, select, update

from app.config import settings
from app.database import AsyncSessionLocal
from app.models.review_session import ReviewSession
from app.models.user import User

logging.basicConfig(
    level=getattr(logging, settings.log_level.upper(), logging.INFO),
    format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
)

logging.getLogger("apscheduler").setLevel(logging.DEBUG)

logger = logging.getLogger(__name__)


async def get_users_to_notify() -> dict[int, int]:
    query = (
        select(
            User.telegram_id.label("telegram_id"),
            (
                extract(
                    "epoch",
                    func.now() - func.coalesce(func.max(ReviewSession.created_at), User.created_at),
                )
                / 3600
            ).label("delta_hours"),
        )
        .select_from(User)
        .outerjoin(ReviewSession, User.id == ReviewSession.user_id)
        .where(User.allow_notifications)
        .group_by(User.id, User.telegram_id)
        .having(
            func.now() - func.coalesce(func.max(ReviewSession.created_at), User.created_at)
            > timedelta(hours=24)
        )
    )

    async with AsyncSessionLocal() as session:
        result = await session.execute(query)
        return {row.telegram_id: int(row.delta_hours) for row in result}


async def send_notifications(bot: Bot):
    users = await get_users_to_notify()

    for telegram_id, delta_hours in users.items():
        try:
            await bot.send_message(
                telegram_id,
                text=f"Вы не повторяли карточки {delta_hours} ч., пора учиться!",
                reply_markup=InlineKeyboardMarkup(
                    inline_keyboard=[
                        [
                            InlineKeyboardButton(
                                text="Отключить уведомления", callback_data="disable_notifications"
                            )
                        ]
                    ]
                ),
                parse_mode="HTML",
            )
        except Exception as e:
            print(f"Не удалось отправить уведомление пользователю {telegram_id}: {e}")


# --- УВЕДОМЛЕНИЕ О ПЕРВОМ SYNC ---
async def notify_first_sync(
    bot: Bot, telegram_id: int, cards_count: int, deck_name: str | None = None
):
    """Отправляет поздравление после первого успешного sync."""
    deck_text = f" в колоде «{deck_name}»" if deck_name else ""
    text = (
        f"🎉 <b>Отлично! Получено {cards_count} карточек{deck_text}.</b>\n\n"
        "Ваша первая синхронизация прошла успешно. Теперь вы можете начать повторение."
    )

    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="▶️ Начать повторение", callback_data="menu_review")],
            [InlineKeyboardButton(text="🏠 В главное меню", callback_data="back_to_main")],
        ]
    )

    try:
        await bot.send_message(telegram_id, text, reply_markup=keyboard, parse_mode="HTML")
        logger.info(
            "First sync notification sent to telegram_id=%s cards=%s", telegram_id, cards_count
        )
    except Exception as e:
        logger.warning(
            "Failed to send first sync notification to telegram_id=%s: %s", telegram_id, e
        )


def start_scheduler(bot: Bot):
    scheduler = AsyncIOScheduler()
    scheduler.add_job(
        send_notifications, "cron", hour="15", minute="30", timezone="Europe/Moscow", args=[bot]
    )
    scheduler.start()


async def get_allow_notifications(telegram_id: int) -> bool:
    async with AsyncSessionLocal() as session:
        query = select(User.allow_notifications).where(User.telegram_id == telegram_id)
        result = await session.execute(query)
        val = result.scalar_one_or_none()
        return True if val is None else val


async def set_notifications_permission(telegram_id: int, allow: bool):
    async with AsyncSessionLocal() as session:
        await session.execute(
            update(User).where(User.telegram_id == telegram_id).values(allow_notifications=allow)
        )
        await session.commit()
