from datetime import datetime

from pydantic import BaseModel


class StatusResponse(BaseModel):
    user_id: int
    cards_count: int
    last_sync_at: datetime | None
    delimiter: str
