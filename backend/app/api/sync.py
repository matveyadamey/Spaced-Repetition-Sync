import logging

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.auth import get_current_user
from app.config import settings
from app.database import get_session
from app.models.user import User
from app.schemas.sync import SyncRequest, SyncResponse
from app.services.sync_service import sync_cards

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1", tags=["sync"])


@router.post("/sync", response_model=SyncResponse)
async def sync_endpoint(
    request: Request,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
) -> SyncResponse | JSONResponse:
    body = await request.body()
    if len(body) > settings.max_request_body_bytes:
        logger.error("Sync rejected: payload too large for user_id=%s", user.id)
        return JSONResponse(
            status_code=413,
            content={"detail": "Request body exceeds 10 MB limit"},
        )

    try:
        payload = SyncRequest.model_validate_json(body)
    except Exception as exc:
        logger.error("Sync validation error for user_id=%s: %s", user.id, exc)
        return JSONResponse(status_code=422, content={"detail": str(exc)})

    logger.info("Sync started for user_id=%s cards=%s", user.id, len(payload.cards))
    try:
        result = await sync_cards(session, user, payload.cards)
    except Exception:
        await session.rollback()
        logger.exception("Sync failed for user_id=%s", user.id)
        raise

    logger.info(
        "Sync finished for user_id=%s added=%s updated=%s skipped=%s deleted=%s",
        user.id,
        result.added,
        result.updated,
        result.skipped,
        result.deleted,
    )
    return result
