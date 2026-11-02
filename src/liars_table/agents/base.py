"""Agent 接口：Agent 能看到什么、必须回答什么。

这里用一个很重要的设计约束：
    Agent **拿不到 GameState**，只能拿到一个裁剪过的 DecisionRequest。

为什么？因为 GameState 里有 ``roles``（所有人的身份）。
一旦把整个 state 递给 agent，它就能直接读出“谁是狼”，
LLM 会毫不客气地利用这一点作弊。所以接口层面就把信息掐断。

Python 知识点：
    Protocol
        结构化子类型（也叫“鸭子类型的静态版本”）。只要一个类实现了
        ``decide`` 方法，它就自动满足 Agent 协议——不需要继承。
        比抽象基类（ABC）更轻，特别适合这种只有一两个方法的接口。
    dataclass(frozen=True, slots=True)
        见 events.py 的说明。这里的 DecisionRequest 用 frozen，
        是为了保证“agent 收到的信息”在决策过程中不会被偷偷改掉。
    async def
        注意 Protocol 里也写了 ``async def``。协议描述的是"形状"，
        包括异步这个形状；实现方也必须是 async def，否则 await 会报错。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol

from ..core.claims import Claim
from ..core.events import Event
from ..core.roles import Role


@dataclass(frozen=True, slots=True)
class DecisionRequest:
    """一次决策请求：Agent 在某个时刻能看到的全部信息。

    字段说明：
        kind       要做哪种决策：kill / check / witch / speech / vote / shoot
        seat       自己的座位
        role       自己的身份（自己当然知道）
        round      第几轮
        legal      合法目标列表——越界的目标会被引擎拒绝，这是防作弊的第一道闸
        context    额外上下文，例如女巫会拿到“今晚谁被刀了”
        transcript 最近若干条公开发言（不是全部，防止 prompt 过长）
        notes      自己的私有笔记，例如预言家验过谁
    """

    kind: str
    seat: str
    role: Role
    round: int
    legal: tuple[str, ...] = ()
    context: dict[str, Any] = field(default_factory=dict)
    transcript: tuple[str, ...] = ()
    notes: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class Decision:
    """Agent 的回答。一个统一的结构覆盖所有决策类型。

    不同 kind 只会用到其中一部分字段：
        kill / check / vote / shoot  → target
        witch                        → save + target（毒谁）
        speech                       → text + claims + cites
    """

    target: str | None = None
    save: bool = False
    text: str = ""
    claims: tuple[Claim, ...] = ()
    cites: tuple[str, ...] = ()


class Agent(Protocol):
    """任何实现了 ``observe`` + 异步 ``decide`` 的对象都可以当 Agent 用。

    为什么要有 ``observe``？
        记忆不是"决策时临时查一下"，而是"事情发生时当场记下来"。
        引擎每发一条事件就广播给能看到它的 agent，agent 自己决定记不记。
        注意：可见性由**引擎**裁决，agent 没有"偷看"的能力。
    """

    def observe(
        self,
        event: Event,
        round_no: int,
        event_id: int | None = None,
    ) -> None: ...

    async def decide(self, request: DecisionRequest) -> Decision: ...
