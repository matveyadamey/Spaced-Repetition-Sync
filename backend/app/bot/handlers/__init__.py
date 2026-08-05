from aiogram import Router

from .decks import router as decks_router
from .onboarding import router as onboarding_router
from .review import router as review_router
from .settings import router as settings_router
from .start import router as start_router

router = Router()


router.include_routers(
    start_router,
    onboarding_router,
    decks_router,
    review_router,
    settings_router,
)
