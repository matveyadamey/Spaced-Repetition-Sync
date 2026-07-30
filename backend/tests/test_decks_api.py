import pytest


@pytest.mark.asyncio
async def test_decks_require_auth(client):
    assert (await client.get("/api/v1/decks")).status_code == 401
    assert (await client.post("/api/v1/decks", json={"name": "D"})).status_code == 401


@pytest.mark.asyncio
async def test_create_and_list_decks(client, user_with_token):
    _, token = user_with_token
    headers = {"Authorization": f"Bearer {token}"}
    created = await client.post("/api/v1/decks", json={"name": "Матан"}, headers=headers)
    assert created.status_code == 201
    assert created.json()["name"] == "Матан"

    listed = await client.get("/api/v1/decks", headers=headers)
    assert listed.status_code == 200
    names = [d["name"] for d in listed.json()["decks"]]
    assert names == ["Матан"]


@pytest.mark.asyncio
async def test_create_deck_duplicate_returns_400(client, user_with_token):
    _, token = user_with_token
    headers = {"Authorization": f"Bearer {token}"}
    assert (
        await client.post("/api/v1/decks", json={"name": "D"}, headers=headers)
    ).status_code == 201
    dup = await client.post("/api/v1/decks", json={"name": "d"}, headers=headers)
    assert dup.status_code == 400


@pytest.mark.asyncio
async def test_sync_missing_deck_returns_400(client, user_with_token):
    _, token = user_with_token
    response = await client.post(
        "/api/v1/sync",
        json={
            "source_file": "a.md",
            "deck": "Нет такой",
            "cards": [{"question": "Q?", "answer": "A", "source_file": "a.md"}],
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 400


@pytest.mark.asyncio
async def test_token_rotation_invalidates_old_token(client, session, user_with_token):
    from app.services.token_service import generate_token, hash_token

    user, old_token = user_with_token
    new_token = generate_token()
    user.token_hash = hash_token(new_token)
    await session.commit()

    old = await client.get(
        "/api/v1/status",
        headers={"Authorization": f"Bearer {old_token}"},
    )
    assert old.status_code == 401

    fresh = await client.get(
        "/api/v1/status",
        headers={"Authorization": f"Bearer {new_token}"},
    )
    assert fresh.status_code == 200


@pytest.mark.asyncio
async def test_status_after_sync(client, user_with_token):
    _, token = user_with_token
    headers = {"Authorization": f"Bearer {token}"}
    await client.post(
        "/api/v1/sync",
        json={
            "source_file": "a.md",
            "deck": None,
            "cards": [{"question": "Q?", "answer": "A", "source_file": "a.md"}],
        },
        headers=headers,
    )
    status = await client.get("/api/v1/status", headers=headers)
    assert status.status_code == 200
    data = status.json()
    assert data["cards_count"] == 1
    assert data["last_sync_at"] is not None
