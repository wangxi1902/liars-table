import asyncio

from fastapi.testclient import TestClient

from liars_table.agents.decision_runtime import DecisionBudget
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
    assert session.decision_traces
    assert session.decision_bases
    assert all("raw_output" not in trace for trace in session.decision_traces)
    assert all("raw_output" not in basis for basis in session.decision_bases)


def test_create_game_endpoint() -> None:
    client = TestClient(app)
    response = client.post(
        "/api/games",
        params={
            "seed": 11,
            "latency": 0,
            "decision_timeout": 3,
            "decision_max_model_calls": 1,
            "decision_max_retries": 0,
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["seed"] == 11
    assert body["id"]
    assert body["decision_budget"]["max_seconds"] == 3
    assert body["decision_budget"]["max_model_calls"] == 1
    assert body["decision_budget"]["max_retries"] == 0


def test_session_uses_supplied_dynamic_budget() -> None:
    async def go():
        manager = GameManager()
        budget = DecisionBudget(max_model_calls=1, max_retries=0)
        session = await manager.create(seed=13, latency=0, budget=budget)
        await session.task
        return session

    session = asyncio.run(go())
    assert session.budget.max_model_calls == 1
    assert session.budget.max_retries == 0
    assert session.decision_traces


def test_unknown_game_returns_404() -> None:
    client = TestClient(app)
    assert client.get("/api/games/does-not-exist").status_code == 404


def test_websocket_streams_events_and_result() -> None:
    kinds: list[str] = []
    # 开局接口会用 asyncio.create_task 启动后台游戏。TestClient 不使用上下文时，
    # 单次 POST 结束就会关闭自己的事件循环，真正会让出控制权的后台任务随之取消。
    # 把 HTTP 和 WebSocket 放进同一个上下文，等价于 Uvicorn 的长生命周期事件循环。
    with TestClient(app) as client:
        game_id = client.post("/api/games", params={"seed": 5, "latency": 0}).json()["id"]

        with client.websocket_connect(f"/ws/{game_id}") as ws:
            for _ in range(400):
                message = ws.receive_json()
                kinds.append(message["kind"])
                if message["kind"] == "result":
                    break

    assert "game_ended" in kinds, "WebSocket 没有推完一整局"
    assert "decision_trace" in kinds, "WebSocket 没有推送LangGraph执行阶段"
    assert "decision_basis" in kinds, "WebSocket 没有推送结构化决策依据"
    assert kinds[-1] == "result", "最后一条应该是终局结果"
