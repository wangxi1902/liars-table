"""一局游戏的"会话"：跑起来、存事件、推给订阅者。

为什么需要这一层？
    引擎是纯逻辑（不碰网络），Web 服务是 I/O（不碰规则）。
    中间需要一个东西把两者粘起来：**引擎每发一条事件，会话就把它存下来并广播出去**。

这里的并发达到了目前为止最有意思的程度：
    同一个进程里，uvicorn 在处理 HTTP 请求，游戏循环在跑 LLM 调用，
    WebSocket 在推送数据——三者互不阻塞，全靠 asyncio 的协作式调度。

Python 知识点：
    ``asyncio.Queue``
        协程之间传数据的管道。``put_nowait`` 不等待，满了就抛 QueueFull。
        对"直播"场景，**宁可丢事件也不能卡住游戏**，所以用 nowait + 丢弃。
    ``asyncio.create_task``
        把一个协程丢到后台跑，立刻返回 Task 对象。不 await 它就不会阻塞当前请求。
    ``set[asyncio.Queue]``
        订阅者集合，连接进来就加、断开就删。
"""

from __future__ import annotations

import asyncio
import uuid
from dataclasses import dataclass, field
from typing import Any

from ..agents.llm_agent import LLMAgent
from ..core.events import Event, Exiled, HunterShot, PlayerDied, Spoke, Voted
from ..core.roles import ROLE_ZH
from ..core.view import describe_public
from ..engine import Engine, GameResult
from ..llm.client import MockClient
from ..roster import PlayerInfo, build_roster


@dataclass
class GameSession:
    """一局正在跑（或已跑完）的游戏。"""

    id: str
    seed: int
    status: str = "running"  # running | finished | failed
    players: list[dict[str, Any]] = field(default_factory=list)
    roster: dict[str, PlayerInfo] = field(default_factory=dict)
    payloads: list[dict[str, Any]] = field(default_factory=list)
    result: GameResult | None = None
    task: asyncio.Task | None = None
    subscribers: set[asyncio.Queue] = field(default_factory=set)
    client: MockClient | None = None

    # ---------------------------------------------------------------- 广播

    def push(self, event: Event) -> None:
        """引擎的 on_event 回调：存一条、广播一条。

        ``seq`` 用的是事件在流里的下标，和静态 HTML 里的编号是同一套规则。
        私有事件（狼人刀口、验人结果）的 text 为 None，前端直接跳过。

        ``actor`` 是"这条事件是谁做的"，前端靠它决定高亮哪个头像——
        这比让前端从文本里正则抠 "P3：" 可靠得多。
        """
        seq = len(self.payloads)
        actor, kind_type = _actor_and_type(event)
        # 发言只给"说了什么"，说话人由 actor + 名册提供——
        # 否则前端会显示成 "P1: P1: ..." 这种重复
        text = event.text if isinstance(event, Spoke) else describe_public(event)
        payload = {
            "seq": seq,
            "kind": event.kind,
            "type": kind_type,
            "actor": actor,
            "text": text,
        }
        self.payloads.append(payload)
        for queue in list(self.subscribers):
            try:
                queue.put_nowait(payload)
            except asyncio.QueueFull:  # 慢客户端就丢事件，绝不拖住游戏
                continue

    def subscribe(self) -> asyncio.Queue:
        queue: asyncio.Queue = asyncio.Queue(maxsize=256)
        self.subscribers.add(queue)
        return queue

    def unsubscribe(self, queue: asyncio.Queue) -> None:
        self.subscribers.discard(queue)

    # ---------------------------------------------------------------- 结果

    def summary(self) -> dict[str, Any]:
        """给前端用的终局信息：名册 + 真实身份 + 存活状态。"""
        if self.result is None:
            return {}
        state = self.result.state
        roster = {p["seat"]: p for p in self.players}
        players = []
        for seat in sorted(state.roles, key=lambda s: int(s[1:])):
            info = roster.get(seat, {"seat": seat, "name": seat, "emoji": "🙂", "hue": 0})
            players.append(
                {
                    **info,
                    "role": ROLE_ZH[state.roles[seat]],
                    "survived": state.is_alive(seat),
                }
            )
        return {
            "winner": state.winner.value if state.winner else "unknown",
            "reason": state.reason,
            "rounds": state.round,
            "players": players,
        }


class GameManager:
    """管理所有会话。进程内存储，重启就没——够 demo 用，正式版再上数据库。"""

    def __init__(self) -> None:
        self._sessions: dict[str, GameSession] = {}

    def get(self, game_id: str) -> GameSession | None:
        return self._sessions.get(game_id)

    async def create(self, seed: int, latency: float = 0.05) -> GameSession:
        session = GameSession(id=uuid.uuid4().hex[:12], seed=seed)
        session.roster = build_roster(seed, 9)
        session.players = [info.as_payload() for info in session.roster.values()]
        self._sessions[session.id] = session
        session.task = asyncio.create_task(self._run(session, latency))
        return session

    async def _run(self, session: GameSession, latency: float) -> None:
        client = MockClient(latency=latency, seed=session.seed)
        session.client = client

        def factory(seat: str, role):  # noqa: ANN001
            return LLMAgent(seat, role, client, roster=session.roster)

        engine = Engine(
            agent_factory=factory,
            seed=session.seed,
            on_event=session.push,
            roster=session.roster,
        )
        try:
            session.result = await engine.run()
            session.status = "finished"
        except Exception:  # 边界兜底：一局崩了不能把整个服务带崩
            session.status = "failed"
            raise


def _actor_and_type(event: Event) -> tuple[str | None, str]:
    """从事件里取出"谁做的"和"这是什么类型"，给前端做高亮和分组。

    类型只有四种，够前端用了：
        speech 发言 / vote 投票 / death 出局 / system 系统播报
    """
    if isinstance(event, Spoke):
        return event.player, "speech"
    if isinstance(event, Voted):
        return event.voter, "vote"
    if isinstance(event, PlayerDied):
        return event.player, "death"
    if isinstance(event, Exiled):
        return event.player, "death"
    if isinstance(event, HunterShot):
        return event.hunter, "death"
    return None, "system"
