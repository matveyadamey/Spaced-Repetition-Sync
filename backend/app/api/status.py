import logging

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.auth import get_current_user
from app.database import get_session
from app.models.card import Card
from app.models.user import User
from app.schemas.status import StatusResponse

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1", tags=["status"])


@router.get("/status", response_model=StatusResponse)
async def status_endpoint(
    session: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
) -> StatusResponse:
    cards_count = await session.scalar(
        select(func.count()).select_from(Card).where(Card.user_id == user.id)
    )
    logger.info("Status requested for user_id=%s", user.id)
    return StatusResponse(
        user_id=user.id,
        cards_count=cards_count or 0,
        last_sync_at=user.last_sync_at,
        delimiter=user.delimiter,
    )
