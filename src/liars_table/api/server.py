"""HTTP + WebSocket 服务。

三个端点：
    POST /api/games      开一局，立刻返回 id（游戏在后台跑）
    GET  /api/games/{id} 查状态和已有事件（断线重连用）
    WS   /ws/{id}        订阅实时事件
    GET  /               观战页

设计要点：**开局的请求不等待整局跑完**。
    ``create_task`` 把整局丢到后台，HTTP 立刻返回。
    如果这里写成 ``await engine.run()``，一个请求会挂十几秒，浏览器直接超时。

Python 知识点：
    ``@app.websocket`` 的处理函数生命周期 == 连接生命周期。
    ``WebSocketDisconnect`` 是客户端关页面时抛的异常，必须捕获，否则日志里全是堆栈。
"""

from __future__ import annotations

import asyncio
import json
import random
from dataclasses import asdict

from fastapi import FastAPI, HTTPException, Query, WebSocket
from fastapi.responses import HTMLResponse
from starlette.websockets import WebSocketDisconnect

from ..agents.decision_runtime import DecisionBudget
from ..config import get_settings
from .page import LIVE_PAGE
from .session import GameManager

app = FastAPI(title="Liar's Table", version="0.1.0")
manager = GameManager()


@app.get("/", response_class=HTMLResponse)
async def index(id: str | None = None) -> str:
    """观战页。带 ``?id=xxx`` 时把这一局的已有事件直接嵌进 HTML。

    为什么要内嵌而不是只靠 WebSocket？
        首屏不能等连接：断线、慢网、截图场景下都会看到空白。
        内嵌 + 增量推送的组合，打开就有内容，连上之后继续长。
    """
    boot: dict = {"payloads": [], "result": None, "seed": None, "players": []}
    if id:
        session = manager.get(id)
        if session is not None:
            boot = {
                "payloads": session.payloads,
                "result": session.summary() or None,
                "seed": session.seed,
                "players": session.players,
            }
    data = json.dumps(boot, ensure_ascii=False).replace("</", "<\\/")
    return LIVE_PAGE.replace("__BOOT_DATA__", data)


@app.post("/api/games")
async def create_game(
    seed: int | None = None,
    latency: float = 0.05,
    decision_timeout: float | None = Query(default=None, gt=0),
    decision_max_steps: int | None = Query(default=None, gt=0),
    decision_max_model_calls: int | None = Query(default=None, gt=0),
    decision_max_tokens: int | None = Query(default=None, gt=0),
    decision_max_retries: int | None = Query(default=None, ge=0),
) -> dict:
    """创建后台对局；决策参数只覆盖本局，不会修改全局环境配置。"""
    settings = get_settings()
    budget = DecisionBudget(
        max_seconds=decision_timeout or settings.decision_timeout_seconds,
        max_steps=decision_max_steps or settings.decision_max_steps,
        max_model_calls=(
            decision_max_model_calls or settings.decision_max_model_calls
        ),
        max_completion_tokens=(
            decision_max_tokens or settings.decision_max_completion_tokens
        ),
        max_retries=(
            settings.decision_max_retries
            if decision_max_retries is None
            else decision_max_retries
        ),
    )
    session = await manager.create(
        seed if seed is not None else random.randrange(10_000),
        latency,
        budget,
    )
    return {
        "id": session.id,
        "seed": session.seed,
        "players": session.players,
        "decision_budget": asdict(session.budget),
    }


@app.get("/api/games/{game_id}")
async def get_game(game_id: str) -> dict:
    session = manager.get(game_id)
    if session is None:
        raise HTTPException(status_code=404, detail="game not found")
    return {
        "id": session.id,
        "seed": session.seed,
        "status": session.status,
        "players": session.players,
        "payloads": session.payloads,
        "decision_budget": asdict(session.budget),
        "decision_traces": session.decision_traces,
        "decision_bases": session.decision_bases,
        "stream_cursor": len(session.stream_payloads) - 1,
        "summary": session.summary(),
    }


@app.websocket("/ws/{game_id}")
async def stream(websocket: WebSocket, game_id: str) -> None:
    session = manager.get(game_id)
    if session is None:
        await websocket.close(code=4004)
        return

    await websocket.accept()
    queue = session.subscribe()
    try:
        # 先报名册，前端才知道每个座位叫什么、用哪个 emoji
        await websocket.send_json({"kind": "roster", "players": session.players})

        # 再补发历史，最后订阅增量——断线重连也能看到完整过程
        for payload in list(session.stream_payloads):
            await websocket.send_json(payload)

        if session.status != "running":
            await websocket.send_json({"kind": "result", **session.summary()})
            return

        while True:
            payload = await queue.get()
            await websocket.send_json(payload)
            if payload["kind"] != "game_ended":
                continue

            # 事件已经发完，但 result 要等 run() 返回才写入，轮询等一小会儿
            for _ in range(200):
                if session.status != "running":
                    break
                await asyncio.sleep(0.01)
            await websocket.send_json({"kind": "result", **session.summary()})
            break
    except WebSocketDisconnect:
        pass
    finally:
        session.unsubscribe(queue)
