from pydantic import BaseModel, Field


class SyncCardIn(BaseModel):
    question: str = Field(..., min_length=1, max_length=10000)
    answer: str = Field(..., min_length=1, max_length=100000)
    source_file: str | None = Field(default=None, max_length=1000)


class SyncRequest(BaseModel):
    source_file: str = Field(..., min_length=1, max_length=1000)
    deck: str | None = Field(default=None, max_length=200)
    cards: list[SyncCardIn] = Field(..., max_length=10000)


class SyncResponse(BaseModel):
    status: str = "ok"
    added: int = 0
    updated: int = 0
    skipped: int = 0
    deleted: int = 0
    errors: list[str] = Field(default_factory=list)
