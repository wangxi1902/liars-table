"""单个 LLM Agent 的 LangGraph 决策工作流。

图只编排 Agent 的认知步骤，不接管夜晚、投票或胜负等确定性规则。运行时预算
通过 ``DecisionBudget`` 传入，因此不同对局、座位和决策类型可以使用不同上限，
不需要修改或重新编译图节点。

当前流程：

    prepare_context -> check_budget -> call_model -> validate_output
                           ^                              |
                           +------ prepare_retry <-------+

``check_budget`` 是守门节点，不计入认知步骤；它只判断本次运行是否还有时间、
步骤和模型调用额度。
"""

from __future__ import annotations

import asyncio
from typing import Literal, TypedDict

from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph

from ..cognition import ConversationMemory, Facts, SuspicionLedger
from ..llm.base import ChatClient, ChatMessage
from ..llm.schema import ActionPayload, parse_action
from ..memory import MemoryStore
from ..roster import PlayerInfo
from .base import DecisionRequest
from .decision_runtime import (
    DecisionBudget,
    DecisionRunMetrics,
    DecisionRunResult,
    DecisionTrace,
    TraceSink,
    TraceStatus,
)
from .prompts import build_messages

_RETRY_HINT = (
    "你上一条输出不是合法 JSON 对象。请只输出一个 JSON 对象，"
    "不要任何解释、不要 markdown。"
)


class DecisionState(TypedDict):
    """节点之间传递的共享状态，运行时仍是普通 ``dict``。"""

    request: DecisionRequest
    budget: DecisionBudget
    metrics: DecisionRunMetrics
    messages: list[ChatMessage]
    raw_output: str
    payload: ActionPayload | None
    attempt: int
    error: str
    budget_exhausted: bool


class DecisionWorkflow:
    """编译并执行一张可复用的 Agent 决策图。"""

    def __init__(
        self,
        client: ChatClient,
        memory: MemoryStore,
        facts: Facts,
        suspicion: SuspicionLedger | None = None,
        conversation_memory: ConversationMemory | None = None,
        *,
        roster: dict[str, PlayerInfo] | None = None,
        memory_top_k: int = 6,
        temperature: float = 0.8,
        max_retries: int = 1,
        on_trace: TraceSink | None = None,
    ) -> None:
        self.client = client
        self.memory = memory
        self.facts = facts
        self.suspicion = suspicion
        self.conversation_memory = conversation_memory
        self.roster = roster or {}
        self.memory_top_k = memory_top_k
        self.temperature = temperature
        # 保留旧构造参数作为默认值，调用方可以在每次 run 时传入不同预算。
        self.default_budget = DecisionBudget(max_retries=max_retries)
        self.on_trace = on_trace
        self.graph = self._build_graph()

    def _build_graph(self) -> CompiledStateGraph:
        """声明节点和边，然后编译成可执行图。"""
        graph = StateGraph(DecisionState)
        graph.add_node("prepare_context", self.prepare_context)
        graph.add_node("check_budget", self.check_budget)
        graph.add_node("call_model", self.call_model)
        graph.add_node("validate_output", self.validate_output)
        graph.add_node("prepare_retry", self.prepare_retry)

        graph.add_edge(START, "prepare_context")
        graph.add_edge("prepare_context", "check_budget")
        graph.add_conditional_edges(
            "check_budget",
            self.route_after_budget_check,
            {"call": "call_model", "finish": END},
        )
        graph.add_edge("call_model", "validate_output")
        graph.add_conditional_edges(
            "validate_output",
            self.route_after_validation,
            {"finish": END, "retry": "prepare_retry"},
        )
        graph.add_edge("prepare_retry", "check_budget")
        return graph.compile()

    async def run(
        self,
        request: DecisionRequest,
        budget: DecisionBudget | None = None,
    ) -> DecisionRunResult:
        """在动态预算内执行一次决策，超时会返回可观测结果而不是卡住对局。"""
        active_budget = budget or self.default_budget
        metrics = DecisionRunMetrics()
        initial: DecisionState = {
            "request": request,
            "budget": active_budget,
            "metrics": metrics,
            "messages": [],
            "raw_output": "",
            "payload": None,
            "attempt": 0,
            "error": "",
            "budget_exhausted": False,
        }

        try:
            async with asyncio.timeout(active_budget.max_seconds):
                state = await self.graph.ainvoke(initial)
        except TimeoutError:
            self._record(
                initial,
                "workflow",
                TraceStatus.TIMED_OUT,
                "决策超过时间上限，已取消本次执行",
            )
            return metrics.to_result(
                None,
                active_budget,
                timed_out=True,
                error="决策执行超时",
            )

        return metrics.to_result(
            state["payload"],
            active_budget,
            timed_out=False,
            error=state["error"],
        )

    def prepare_context(self, state: DecisionState) -> dict[str, object]:
        """节点 1：召回相关记忆，并生成本次模型消息。"""
        self._start(state, "prepare_context", "开始准备事实、记忆和公开上下文")
        try:
            request = state["request"]
            query = "\n".join(request.transcript[-4:]) or request.kind
            memories = self.memory.recall(
                query,
                current_round=request.round,
                k=self.memory_top_k,
            )
            messages = build_messages(
                request,
                memories,
                self.roster,
                self.facts,
                self.suspicion,
                self.conversation_memory,
            )
        except Exception:
            self._finish(state, "prepare_context", TraceStatus.FAILED, "准备上下文失败")
            raise
        self._finish(state, "prepare_context", TraceStatus.COMPLETED, "已准备模型上下文")
        return {"messages": messages, "error": ""}

    def check_budget(self, state: DecisionState) -> dict[str, object]:
        """守门节点：下一次模型调用前检查剩余资源，不额外消耗步骤。"""
        budget = state["budget"]
        metrics = state["metrics"]
        reason = ""
        if metrics.elapsed_seconds >= budget.max_seconds:
            reason = "时间预算已用尽"
        elif metrics.steps_used >= budget.max_steps:
            reason = "步骤预算已用尽"
        elif metrics.model_calls >= budget.max_model_calls:
            reason = "模型调用预算已用尽"

        if reason:
            self._record(state, "check_budget", TraceStatus.SKIPPED, reason)
            return {"budget_exhausted": True, "error": reason}
        return {"budget_exhausted": False}

    async def call_model(self, state: DecisionState) -> dict[str, object]:
        """节点 2：异步调用一次模型，并累计本次调用的 token 用量。"""
        self._start(state, "call_model", "开始请求模型生成结构化行动")
        request = state["request"]
        metrics = state["metrics"]
        metrics.model_calls += 1
        try:
            result = await self.client.complete(
                state["messages"],
                meta={
                    "kind": request.kind,
                    "legal": list(request.legal),
                    "seat": request.seat,
                },
                temperature=self.temperature,
                max_tokens=state["budget"].max_completion_tokens,
            )
        except Exception:
            self._finish(state, "call_model", TraceStatus.FAILED, "模型调用失败")
            raise
        metrics.prompt_tokens += result.prompt_tokens
        metrics.completion_tokens += result.completion_tokens
        self._finish(state, "call_model", TraceStatus.COMPLETED, "模型调用完成")
        return {"raw_output": result.text, "attempt": state["attempt"] + 1}

    def validate_output(self, state: DecisionState) -> dict[str, object]:
        """节点 3：把不可信文本解析为经过 Pydantic 校验的 Payload。"""
        if state["metrics"].steps_used >= state["budget"].max_steps:
            self._record(
                state,
                "validate_output",
                TraceStatus.SKIPPED,
                "步骤预算已用尽，跳过输出校验",
            )
            return {
                "payload": None,
                "error": "步骤预算已用尽",
                "budget_exhausted": True,
            }
        self._start(state, "validate_output", "开始校验模型输出格式")
        payload = parse_action(state["raw_output"])
        if payload is None:
            self._finish(
                state,
                "validate_output",
                TraceStatus.FAILED,
                "模型输出格式不合法",
            )
            return {"payload": None, "error": "模型输出不是合法的 Action JSON"}
        self._finish(state, "validate_output", TraceStatus.COMPLETED, "结构化行动校验通过")
        return {"payload": payload, "error": ""}

    def route_after_budget_check(self, state: DecisionState) -> Literal["call", "finish"]:
        """条件边：预算充足才允许调用模型。"""
        return "finish" if state["budget_exhausted"] else "call"

    def route_after_validation(self, state: DecisionState) -> Literal["finish", "retry"]:
        """条件边：成功就结束；格式错误且还有重试额度时进入修复节点。"""
        if state["payload"] is not None:
            return "finish"
        if state["budget_exhausted"]:
            return "finish"
        if state["metrics"].steps_used >= state["budget"].max_steps:
            return "finish"
        if state["attempt"] <= state["budget"].max_retries:
            return "retry"
        return "finish"

    def prepare_retry(self, state: DecisionState) -> dict[str, object]:
        """节点 4：附加简短纠错提示，避免错误输出无限放大 Prompt。"""
        self._start(state, "prepare_retry", "开始准备格式修复提示")
        messages = [
            *state["messages"],
            ChatMessage(role="assistant", content=state["raw_output"][:300]),
            ChatMessage(role="user", content=_RETRY_HINT),
        ]
        self._finish(state, "prepare_retry", TraceStatus.COMPLETED, "已准备格式修复提示")
        return {"messages": messages}

    def _start(self, state: DecisionState, node: str, summary: str) -> None:
        """记录节点开始；开始事件不占用步骤，完成或失败才算一次。"""
        self._record(state, node, TraceStatus.STARTED, summary)

    def _finish(
        self,
        state: DecisionState,
        node: str,
        status: TraceStatus,
        summary: str,
    ) -> None:
        state["metrics"].steps_used += 1
        self._record(state, node, status, summary)

    def _record(
        self,
        state: DecisionState,
        node: str,
        status: TraceStatus,
        summary: str,
    ) -> None:
        metrics = state["metrics"]
        trace = DecisionTrace(
            seat=state["request"].seat,
            decision_kind=state["request"].kind,
            node=node,
            status=status,
            summary=summary,
            elapsed_ms=int(metrics.elapsed_seconds * 1000),
            steps_used=metrics.steps_used,
            model_calls=metrics.model_calls,
        )
        metrics.traces.append(trace)
        if self.on_trace is not None:
            self.on_trace(trace)
