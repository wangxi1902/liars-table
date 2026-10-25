import asyncio

from fastapi.testclient import TestClient

from liars_table.api.server import app
from liars_table.api.session import GameManager


def test_session_runs_to_completion() -> None:
    async def go():
        manager = GameManager()
        session = await manager.create(seed=3, latency=0)
        await session.task
        return session

    session = asyncio.run(go())
    assert session.status == "finished"
    assert session.result is not None
    assert session.payloads, "会话应该记录事件"
    assert session.payloads[-1]["kind"] == "game_ended"


def test_create_game_endpoint() -> None:
    client = TestClient(app)
    response = client.post("/api/games", params={"seed": 11, "latency": 0})
    assert response.status_code == 200
    body = response.json()
    assert body["seed"] == 11
    assert body["id"]


def test_unknown_game_returns_404() -> None:
    client = TestClient(app)
    assert client.get("/api/games/does-not-exist").status_code == 404


def test_websocket_streams_events_and_result() -> None:
    client = TestClient(app)
    game_id = client.post("/api/games", params={"seed": 5, "latency": 0}).json()["id"]

    kinds: list[str] = []
    with client.websocket_connect(f"/ws/{game_id}") as ws:
        for _ in range(400):
            message = ws.receive_json()
            kinds.append(message["kind"])
            if message["kind"] == "result":
                break

    assert "game_ended" in kinds, "WebSocket 没有推完一整局"
    assert kinds[-1] == "result", "最后一条应该是终局结果"
