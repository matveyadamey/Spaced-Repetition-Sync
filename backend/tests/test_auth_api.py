import pytest


@pytest.mark.asyncio
async def test_sync_requires_auth(client):
    response = await client.post("/api/v1/sync", json={"cards": []})
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_sync_rejects_invalid_token(client):
    response = await client.post(
        "/api/v1/sync",
        json={"cards": []},
        headers={"Authorization": "Bearer invalidtokeninvalidtokeninvalidtoken12"},
    )
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_sync_with_valid_token(client, user_with_token):
    _, token = user_with_token
    response = await client.post(
        "/api/v1/sync",
        json={
            "cards": [
                {"question": "What is Python?", "answer": "A language", "source_file": "x.md"}
            ]
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert data["added"] == 1


@pytest.mark.asyncio
async def test_status_endpoint(client, user_with_token):
    user, token = user_with_token
    response = await client.get(
        "/api/v1/status",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["user_id"] == user.id
    assert data["delimiter"] == "::"
    assert data["cards_count"] == 0


@pytest.mark.asyncio
async def test_health(client):
    response = await client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"
