from pydantic import BaseModel, Field


class DeckOut(BaseModel):
    id: int
    name: str


class DeckCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=200)


class DeckListResponse(BaseModel):
    decks: list[DeckOut]
