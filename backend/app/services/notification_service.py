from aiogram import Bot
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from sqlalchemy import extract, func, select, update

from app.database import AsyncSessionLocal
from app.models.review_session import ReviewSession
from app.models.user import User


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
            > func.make_interval(hours=24)
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


async def start_scheduler():
    scheduler = AsyncIOScheduler()
    scheduler.add_job(send_notifications, "cron", hour="17", minute="0")
    scheduler.start()


async def get_allow_notifications(telegram_id: int) -> bool:
    async with AsyncSessionLocal() as session:
        query = select(User.allow_notifications).where(User.telegram_id == telegram_id)
        result = await session.execute(query)
        return result.scalar_one_or_none() or True


async def set_notifications_permission(telegram_id: int, allow: bool):
    async with AsyncSessionLocal() as session:
        await session.execute(
            update(User).where(User.telegram_id == telegram_id).values(allow_notifications=allow)
        )
        await session.commit()
