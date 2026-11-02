"""LLM Agent：接收游戏请求，并把内部决策交给 LangGraph 工作流。

容错策略（很重要）：
    模型输出不是 JSON → 决策图进入 prepare_retry 节点，补充纠错消息后重试一次。
    仍然失败 → 返回空 Decision，引擎会随机兜底。
    为什么不在 Agent 里随机兜底？因为 Agent 不该知道规则细节，
    "合法目标"的判断权在引擎手里，职责要分清。

Python 知识点：
    依赖注入
        client、memory 和 roster 都从构造函数传进来，而不是在 Agent 内部写死创建方式。
        所以测试可以传 Mock，真实运行可以传 LangChain 客户端。
    委托
        decide 不再亲自处理每一步，而是把流程委托给 DecisionWorkflow；Agent 只负责
        把通用的 ActionPayload 转换成狼人杀领域的 Decision。
"""

from __future__ import annotations

from ..cognition import Facts
from ..core.claims import Claim, extract_claims
from ..core.events import Event
from ..core.roles import Role
from ..llm.client import ChatClient
from ..memory import MemoryItem, MemoryStore
from ..roster import PlayerInfo, seat_of
from .base import Decision, DecisionRequest
from .decision_graph import DecisionWorkflow


class LLMAgent:
    """一个由 LLM 驱动的玩家。所有玩家共享同一个 client 实例即可（无状态）。"""

    def __init__(
        self,
        seat: str,
        role: Role,
        client: ChatClient,
        *,
        memory: MemoryStore | None = None,
        roster: dict[str, PlayerInfo] | None = None,
        memory_top_k: int = 6,
        temperature: float = 0.8,
        max_retries: int = 1,
    ) -> None:
        self.seat = seat
        self.role = role
        self.client = client
        self.memory = memory if memory is not None else MemoryStore()
        self.roster = roster or {}
        # 事实账本：比"最近几条发言"更可靠，模型靠它做全局判断
        self.facts = Facts.from_roster(self.roster) if self.roster else Facts()
        self.memory_top_k = memory_top_k
        self.temperature = temperature
        self.max_retries = max_retries
        # facts 和 memory 是可变对象。工作流拿到的是同一份引用，observe 更新后，
        # 下一次图执行能直接看到最新数据，不需要反复重建整张图。
        self.workflow = DecisionWorkflow(
            client,
            self.memory,
            self.facts,
            roster=self.roster,
            memory_top_k=memory_top_k,
            temperature=temperature,
            max_retries=max_retries,
        )
        #: 解析失败次数。不为 0 就说明 prompt 或参数有问题，必须暴露出来。
        self.failures = 0

    def observe(self, event: Event, round_no: int) -> None:
        """引擎广播来的事件：一份进记忆（模糊回忆），一份进事实账本（精确统计）。"""
        item = MemoryItem.from_event(event, self.seat, round_no)
        if item is not None:
            self.memory.add(item)
        self.facts.observe(event)

    async def decide(self, request: DecisionRequest) -> Decision:
        payload = await self.workflow.run(request)
        if payload is None:
            # 两次都解析失败：记一笔账，然后交给引擎随机兜底。
            # 这个计数很关键——上一版真机跑出"（沉默）"时，就是因为它不存在，
            # 谁也没发现是 JSON 被截断了。
            self.failures += 1
            return Decision()

        # 模型经常"嘴上说了、字段里没写"：文本里承认"我是预言家"，
        # claims 里却只写了指控。所以不是"为空才兜底"，而是每次都合并。
        claims = list(payload.claims)
        if payload.text:
            for claim in extract_claims(payload.text):
                if claim not in claims:
                    claims.append(claim)
        # 最终目标是否合法仍由 Engine._ask 再检查一次。LangGraph 只负责生成和解析，
        # 不拥有游戏规则的最终裁决权。
        return Decision(
            target=self._resolve(payload.target),
            save=payload.save,
            text=payload.text,
            claims=self._resolve_claims(claims),
            cites=payload.cites,
        )

    # ---------------------------------------------------------------- 归一化

    def _resolve(self, value: str | None) -> str | None:
        """把模型输出的"阿飞"换算成 P3。认不出来就返回 None（引擎会兜底）。"""
        if not self.roster:
            return value
        return seat_of(value, self.roster)

    def _resolve_claims(self, claims: list[Claim]) -> tuple[Claim, ...]:
        """指控对象同样可能是名字，统一换成座位号；换不出来的直接丢掉。"""
        resolved: list[Claim] = []
        for claim in claims:
            if claim.kind != "accuse" or not claim.target:
                resolved.append(claim)
                continue
            seat = self._resolve(claim.target)
            if seat:
                resolved.append(Claim("accuse", target=seat))
        return tuple(resolved)
