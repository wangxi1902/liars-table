"""单个 LLM Agent 的最小 LangGraph 决策工作流。

为什么要有这张图？
    原来的 ``LLMAgent.decide`` 同时负责召回记忆、拼 Prompt、调用模型、解析结果和
    失败重试。功能没有错，但所有步骤挤在一个循环里，不方便单独观察和测试。

这里把一次决策拆成四个节点：

    prepare_context → call_model → validate_output
                             ↑          │
                             └─ prepare_retry（解析失败时）

LangGraph 只编排 Agent 的认知步骤，不接管夜晚、投票或胜负等游戏规则。

Python 知识点：
    TypedDict
        描述一个字典应该有哪些键和对应类型。运行时它仍是普通 dict，但 IDE 和
        静态检查工具能知道 ``state["request"]`` 是 DecisionRequest。
    闭包式依赖
        节点是绑定到 ``DecisionWorkflow`` 实例的方法，因此可以使用这个实例里的
        client、memory 和 facts，同时图状态只保存一次决策真正要流转的数据。
"""

from __future__ import annotations

from typing import Literal, TypedDict

from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph

from ..cognition import Facts
from ..llm.base import ChatClient, ChatMessage
from ..llm.schema import ActionPayload, parse_action
from ..memory import MemoryStore
from ..roster import PlayerInfo
from .base import DecisionRequest
from .prompts import build_messages

_RETRY_HINT = (
    "你上一条输出不是合法 JSON 对象。请只输出一个 JSON 对象，"
    "不要任何解释、不要 markdown。"
)


class DecisionState(TypedDict):
    """节点之间传递的共享状态。

    ``attempt`` 表示已经调用模型多少次，而 ``max_retries`` 表示首次调用失败后
    还能额外重试几次。把两者分清可以避免常见的 off-by-one 错误。
    """

    request: DecisionRequest
    messages: list[ChatMessage]
    raw_output: str
    payload: ActionPayload | None
    attempt: int
    error: str


class DecisionWorkflow:
    """编译并执行一张可复用的 Agent 决策图。"""

    def __init__(
        self,
        client: ChatClient,
        memory: MemoryStore,
        facts: Facts,
        *,
        roster: dict[str, PlayerInfo] | None = None,
        memory_top_k: int = 6,
        temperature: float = 0.8,
        max_retries: int = 1,
    ) -> None:
        self.client = client
        self.memory = memory
        self.facts = facts
        self.roster = roster or {}
        self.memory_top_k = memory_top_k
        self.temperature = temperature
        self.max_retries = max_retries
        self.graph = self._build_graph()

    def _build_graph(self) -> CompiledStateGraph:
        """声明节点和边，然后编译成可执行图。"""
        graph = StateGraph(DecisionState)
        graph.add_node("prepare_context", self.prepare_context)
        graph.add_node("call_model", self.call_model)
        graph.add_node("validate_output", self.validate_output)
        graph.add_node("prepare_retry", self.prepare_retry)

        graph.add_edge(START, "prepare_context")
        graph.add_edge("prepare_context", "call_model")
        graph.add_edge("call_model", "validate_output")
        graph.add_conditional_edges(
            "validate_output",
            self.route_after_validation,
            {"finish": END, "retry": "prepare_retry"},
        )
        graph.add_edge("prepare_retry", "call_model")
        return graph.compile()

    async def run(self, request: DecisionRequest) -> ActionPayload | None:
        """执行一次完整决策；最终解析失败时返回 None，由引擎继续兜底。"""
        initial: DecisionState = {
            "request": request,
            "messages": [],
            "raw_output": "",
            "payload": None,
            "attempt": 0,
            "error": "",
        }
        result = await self.graph.ainvoke(initial)
        return result["payload"]

    def prepare_context(self, state: DecisionState) -> dict[str, object]:
        """节点 1：召回相关记忆，并生成本次模型消息。"""
        request = state["request"]
        # 最近发言代表“当前大家在讨论什么”，适合作为词面记忆的查询词。
        query = "\n".join(request.transcript[-4:]) or request.kind
        memories = self.memory.recall(
            query,
            current_round=request.round,
            k=self.memory_top_k,
        )
        return {
            "messages": build_messages(request, memories, self.roster, self.facts),
            "error": "",
        }

    async def call_model(self, state: DecisionState) -> dict[str, object]:
        """节点 2：进行一次异步模型调用，只保存原始结果。"""
        request = state["request"]
        result = await self.client.complete(
            state["messages"],
            meta={"kind": request.kind, "legal": list(request.legal), "seat": request.seat},
            temperature=self.temperature,
        )
        return {"raw_output": result.text, "attempt": state["attempt"] + 1}

    def validate_output(self, state: DecisionState) -> dict[str, object]:
        """节点 3：把不可信的模型文本解析为经过 Pydantic 校验的 Payload。"""
        payload = parse_action(state["raw_output"])
        if payload is None:
            return {"payload": None, "error": "模型输出不是合法的 Action JSON"}
        return {"payload": payload, "error": ""}

    def route_after_validation(self, state: DecisionState) -> Literal["finish", "retry"]:
        """条件边：成功就结束；失败且还有额度就进入修复节点。"""
        if state["payload"] is not None:
            return "finish"
        if state["attempt"] <= self.max_retries:
            return "retry"
        return "finish"

    def prepare_retry(self, state: DecisionState) -> dict[str, object]:
        """节点 4：把错误原文交还模型，并明确要求只输出 JSON。"""
        messages = [
            *state["messages"],
            # 最多带回 300 字，避免一次异常长输出不断放大下一轮 Prompt。
            ChatMessage(role="assistant", content=state["raw_output"][:300]),
            ChatMessage(role="user", content=_RETRY_HINT),
        ]
        return {"messages": messages}
